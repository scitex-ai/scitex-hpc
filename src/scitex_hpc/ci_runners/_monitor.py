"""Generate the cron-driven health-monitor script for the runner fleet.

Run from a workstation/laptop crontab (NOT on the Spartan login node).
Each tick it, over a single SSH login shell to the cluster:

  1. Confirms the supervisor allocation is still RUNNING (squeue by the
     lease's job name). If the whole allocation is gone -> ALARM and
     exit non-zero (only the operator can rebook; the monitor must never
     silently resurrect a 64-core allocation).
  2. For each runner, checks a ``Runner.Listener`` process is alive on
     the compute node. The supervisor's keep-alive loop already restarts
     a runner whose ``run.sh`` exits, so a *missing* listener that
     persists across two ticks means the loop itself is wedged -> the
     monitor logs it and ALARMS, naming the dead runners.

The monitor's contract is explicit and cron-friendly. **Domain verdicts
start at 10, never at 1 or 2** — see "Why 10+" below:

  * exit 0   -> fleet healthy
  * exit 10  -> degraded (some runners down) — alarm fired
  * exit 11  -> allocation gone / unreachable — alarm fired
  * exit 12  -> supervisor UNREGISTERED (no holder-jobid file) — alarm fired
  * exit 13  -> runner fileset out of inodes — alarm fired (listeners are
    up but Workers cannot create files, so jobs silently phantom; the
    2026-07-06 GPFS inode-wall outage the listener check was blind to)
  * a one-line human summary goes to stdout every tick; failures also go
    to stderr so ``cron`` mails them and any wrapper sees them.

**Why 10+ (changed 2026-07-29).** This script previously used 1/2/3/4 for
those four verdicts. ``1`` and ``2`` already mean "generic failure" and
"usage error" in every shell and CLI framework, so anything that killed the
script *before it measured anything* — an ImportError, a renamed module, a
bad interpreter path, a syntax error — exited 1 and was read as the verdict
"degraded: some runners down". That is worse than a crash, because it is
ACTIONABLE-LOOKING: the operator goes hunting for downed runners that were
never down, and a monitor that never ran reports a plausible fleet state.
Moving domain meanings out of the reserved low range makes a script that
did not run distinguishable from a fleet that is unhealthy.

**Supervisors must be taught the non-failure codes**, or this is undone one
layer up. Under ``cron`` any non-zero simply mails, which is what we want.
Under systemd, a unit wrapping this script needs::

    SuccessExitStatus=10 11 12 13

otherwise a correct three-state answer is collapsed back to two-state by
the supervisor reporting every verdict as a unit FAILURE.

Alarm wiring is a single, swappable command. By default it tries the
fleet ``notify.sh`` helper if present; the operator overrides it with
``$SCITEX_CI_ALARM_CMD`` (the script pipes ``<subject>\n<body>`` to it on
stdin). No telegram/email internals are baked in — just the contract.
"""

from __future__ import annotations

from ._fleet import FleetSpec

# Default alarm: pipe "subject\nbody" to whatever $SCITEX_CI_ALARM_CMD
# names. If unset, fall back to the fleet notify.sh helper (subject =
# first line, body = rest) when it exists; otherwise just emit to stderr
# so cron mails it. Never silently swallow a failure.
#: Run ONE command on the cluster under a LOGIN shell.
#
# WHY THIS EXISTS RATHER THAN AN INLINE ``ssh "$HOST" bash -lc "<cmd>"``.
# ssh does NOT pass argv through. It JOINS its arguments with spaces and
# hands the result to the remote shell as one command string, so the local
# quotes around <cmd> are consumed HERE and the remote receives
#
#     bash -lc squeue --user=$USER --job=123 --noheader ...
#
# where ``-c`` takes only the next WORD as its command and the rest become
# $0/$1/... The remote then runs a BARE ``squeue``. That is not an error,
# it is a WRONG ANSWER, and it is why this monitor could never pass.
# Measured 2026-08-30 against a healthy, RUNNING supervisor:
#   step 0  read an EMPTY holder id  -> exit 12 "supervisor UNREGISTERED"
#           while the file plainly existed and `cat` returned it
#   step 1  read `squeue`'s HEADER row -> STATE=PARTITION, JOBID=JOBID
#           -> exit 11 "allocation DOWN"
#   step 3  would run a bare `df` and take an arbitrary filesystem's IUse%
# ``printf %q`` escapes the command into a single shell WORD, so it
# survives the join intact and ``-c`` receives the whole thing.
_RSH_FUNC = r"""# --- remote exec (see _RSH_FUNC in _monitor.py for why %q) ---
rsh() { ssh "$HOST" bash -lc "$(printf '%q' "$1")" 2>/dev/null; }
"""

_ALARM_FUNC = r"""# --- alarm contract ---
# Override the whole mechanism with $SCITEX_CI_ALARM_CMD (reads
# "<subject>\n<body>" on stdin). Default: fleet notify.sh, else stderr.
_NOTIFY_SH="$HOME/.dotfiles/src/.bin/utils/notify.sh"
alarm() {
  local subject="$1"; shift
  local body="$*"
  echo "ALARM: $subject -- $body" >&2
  if [ -n "${SCITEX_CI_ALARM_CMD:-}" ]; then
    printf '%s\n%s\n' "$subject" "$body" | bash -c "$SCITEX_CI_ALARM_CMD" || true
  elif [ -x "$_NOTIFY_SH" ]; then
    "$_NOTIFY_SH" -s "$subject" -m "$body" >/dev/null 2>&1 || true
  fi
}
"""


def build_monitor_script(
    fleet: FleetSpec,
    *,
    host: str,
    lease_name: str,
    overlap_jobid: str | None = None,
    overlap_jobid_file: str | None = None,
    inode_path: str | None = None,
    inode_threshold_pct: int = 90,
) -> str:
    """Return a self-contained POSIX ``bash`` health-monitor script.

    ``host`` is the SSH alias for the cluster (e.g. ``spartan``);
    ``lease_name`` is the supervisor allocation's SLURM job name (matches
    the Reservation friendly name, e.g. ``spartan-ci-runner-fleet``).

    ``overlap_jobid`` switches step 1 from a name lookup to a **job-id**
    lookup (``squeue --job=<id>``). Use it when the supervisor runs as an
    ``exec-supervisor`` step on an EXISTING holder allocation rather than a
    dedicated named ``book-supervisor`` job — there is no job named
    ``lease_name`` in that deploy, so the name lookup would find nothing and
    false-alarm "allocation DOWN" every tick. Both paths key the per-runner
    listener check off the resolved job id, so step 2 is identical.

    ``overlap_jobid_file`` is the durable form used by ``ci-runners watch``:
    instead of a build-time id, the script reads the current holder id from
    a file on the cluster (written by exec-supervisor) at RUNTIME — so it
    survives the id churn of a walltime-resubmit. A missing/empty file exits
    12 ("supervisor UNREGISTERED"), distinct from exit 11 (allocation down),
    rather than false-alarming a live-but-unnamed overlap step.

    ``inode_path`` is the path whose fileset the monitor checks for inode
    headroom (defaults to ``fleet.ci_base`` — the fileset the runner install
    dirs live on). If that fileset is at/above ``inode_threshold_pct`` inodes
    used, the monitor ALARMS and exits 13: the listeners can be perfectly
    alive while every job phantoms, because a full-inode fileset stops the
    Worker from creating its ``_diag``/``_work``/job-temp files (the
    2026-07-06 outage). ``df -i`` is read-only.

    The generated script is idempotent and read-mostly: its only write to
    the cluster is, when a runner's listener is missing, to *touch* a
    per-runner ``.needs-restart`` marker the supervisor loop notices — it
    never kills the supervisor or any live runner. Allocation rebooking /
    supervisor re-exec stays a deliberate operator action.
    """
    resolve_preamble = ""
    if overlap_jobid_file:
        # Resolve the holder id at RUNTIME from the supervisor's runtime
        # file (survives walltime-resubmit id churn). A missing/empty file
        # means the supervisor never registered -> a DISTINCT exit 3, not a
        # false "allocation DOWN".
        squeue_selector = "--job=$HOLDER_JOBID"
        target_ident = "holder job $HOLDER_JOBID"
        recover_hint = (
            "the supervisor runs as an --overlap step; re-exec with: "
            "scitex-hpc ci-runners exec-supervisor --overlap-jobid "
            "<holder> ... (operator action)"
        )
        resolve_preamble = (
            "# --- 0. resolve holder job id from the supervisor runtime "
            "file --\n"
            'HOLDER_JOBID="$(rsh '
            f"'cat {overlap_jobid_file} 2>/dev/null'"
            ' | tr -dc "0-9")"\n'
            'if [ -z "$HOLDER_JOBID" ]; then\n'
            '  alarm "scitex-ci: supervisor UNREGISTERED" \\\n'
            f'    "no holder jobid at {overlap_jobid_file} on $HOST -- the '
            "supervisor never started or its runtime file was cleared. "
            "Launch: scitex-hpc ci-runners exec-supervisor --overlap-jobid "
            '<holder> (operator action)."\n'
            '  echo "$TS CRITICAL supervisor-unregistered"\n'
            "  exit 12\n"
            "fi\n"
        )
    elif overlap_jobid:
        squeue_selector = f"--job={overlap_jobid}"
        target_ident = f"holder job {overlap_jobid}"
        recover_hint = (
            "the supervisor runs as an --overlap step on this holder; "
            "re-exec with: scitex-hpc ci-runners exec-supervisor "
            f"--overlap-jobid {overlap_jobid} ... (operator action)"
        )
    else:
        squeue_selector = f"--name={lease_name}"
        target_ident = f"lease '{lease_name}'"
        recover_hint = (
            "Rebook with: scitex-hpc ci-runners book-supervisor ... "
            "(operator action)."
        )
    names = " ".join(r.name for r in fleet.active())
    dirs = "\n".join(
        f'  ["{r.name}"]="{r.dir}"' for r in fleet.active()
    )
    srun = "/apps/slurm/latest/bin/srun"
    # Default the inode check to the fileset the runner install dirs live on.
    inode_target = inode_path if inode_path is not None else fleet.ci_base
    return f"""#!/usr/bin/env bash
# scitex-ci runner-fleet health monitor (generated by scitex_hpc.ci_runners).
# Run from a workstation crontab, e.g. every 5 min:
#   */5 * * * * /path/to/scitex-ci-monitor.sh >> ~/.scitex/ci/monitor.log 2>&1
set -uo pipefail

HOST="{host}"
LEASE_NAME="{lease_name}"
SRUN="{srun}"

{_ALARM_FUNC}
{_RSH_FUNC}
declare -A RUNNER_DIRS=(
{dirs}
)
RUNNER_NAMES="{names}"
TS="$(date -u +%FT%TZ)"

{resolve_preamble}
# --- 1. resolve the supervisor allocation (job id + node) ------------
# A single login-shell SSH does the squeue lookup; everything else keys
# off the resolved JOBID so we never re-query the scheduler per runner.
read -r JOBID STATE NODE < <(
  rsh "squeue --user=\\$USER {squeue_selector} --noheader --format='%i %T %N' 2>/dev/null" \\
    | awk 'NR==1{{print $1, $2, $3}}'
)
if [ "${{STATE:-}}" != "RUNNING" ] || [ -z "${{JOBID:-}}" ] || [ -z "${{NODE:-}}" ]; then
  alarm "scitex-ci: supervisor allocation DOWN" \\
    "{target_ident} on $HOST is not RUNNING (state='${{STATE:-none}}'). {recover_hint}"
  echo "$TS CRITICAL allocation-down state=${{STATE:-none}}"
  exit 11
fi

# --- 2. per-runner listener liveness on the compute node --------------
# ONE srun --overlap step into the allocation lists every Runner.Listener
# cmdline; each runner is matched by its install dir appearing in the
# listener argv (run.sh passes the dir). This is read-only.
LIVE="$(
  rsh "$SRUN --jobid=$JOBID --overlap pgrep -af Runner.Listener 2>/dev/null" || true
)"

down=()
for name in $RUNNER_NAMES; do
  dir="${{RUNNER_DIRS[$name]}}"
  if ! printf '%s\\n' "$LIVE" | grep -qF "$dir"; then
    down+=("$name")
    # Nudge the supervisor keep-alive loop WITHOUT touching live runners:
    # drop a marker the loop's next iteration picks up. The monitor never
    # cancels the job nor kills a process -- relaunch is the supervisor's
    # job, alarm is ours.
    rsh "touch '$dir/.needs-restart' 2>/dev/null" \\
      >/dev/null 2>&1 || true
  fi
done

if [ "${{#down[@]}}" -gt 0 ]; then
  alarm "scitex-ci: ${{#down[@]}} runner(s) DOWN on $NODE" \\
    "Down: ${{down[*]}}. Supervisor keep-alive should relaunch within the restart backoff; alarming so the operator can confirm recovery."
  echo "$TS DEGRADED node=$NODE down=${{down[*]}}"
  exit 10
fi

# --- 3. runner fileset inode headroom ---------------------------------
# A runner whose Listener is alive still cannot run jobs if its install
# fileset is out of INODES: the Worker can't create _diag/_work/job-temp
# files, so every job silently phantoms in_progress on GitHub (the
# 2026-07-06 punim0264 inode-wall outage). Step 2 is blind to this -- a
# full fileset with live listeners would report "healthy" -- so check it
# explicitly. df -i is read-only; IUse% is the second-to-last column.
IUSE="$(
  rsh "df -i '{inode_target}' 2>/dev/null | tail -1" \\
    | awk '{{u=$(NF-1); gsub(/%/,"",u); print u}}'
)"
if [ -n "$IUSE" ] && [ "$IUSE" -ge {inode_threshold_pct} ] 2>/dev/null; then
  alarm "scitex-ci: runner fileset inode-critical (${{IUSE}}%)" \\
    "{inode_target} on $HOST is at ${{IUSE}}% inodes (>= {inode_threshold_pct}%). Listeners are up but Workers cannot create files -> jobs will phantom in_progress. Free inodes (stale _work/_diag, per-run session dirs) before CI wedges."
  echo "$TS CRITICAL inode-wall iuse=${{IUSE}}%"
  exit 13
fi

echo "$TS OK node=$NODE runners=$(echo "$RUNNER_NAMES" | wc -w) inodes=${{IUSE:-?}}%"
exit 0
"""
