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

The monitor's contract is explicit and cron-friendly:

  * exit 0  -> fleet healthy
  * exit 1  -> degraded (some runners down) — alarm fired
  * exit 2  -> allocation gone / unreachable — alarm fired
  * a one-line human summary goes to stdout every tick; failures also go
    to stderr so ``cron`` mails them and any wrapper sees them.

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
    3 ("supervisor UNREGISTERED"), distinct from exit 2 (allocation down),
    rather than false-alarming a live-but-unnamed overlap step.

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
            'HOLDER_JOBID="$(ssh "$HOST" bash -lc '
            f"'cat {overlap_jobid_file} 2>/dev/null'"
            ' 2>/dev/null | tr -dc "0-9")"\n'
            'if [ -z "$HOLDER_JOBID" ]; then\n'
            '  alarm "scitex-ci: supervisor UNREGISTERED" \\\n'
            f'    "no holder jobid at {overlap_jobid_file} on $HOST -- the '
            "supervisor never started or its runtime file was cleared. "
            "Launch: scitex-hpc ci-runners exec-supervisor --overlap-jobid "
            '<holder> (operator action)."\n'
            '  echo "$TS CRITICAL supervisor-unregistered"\n'
            "  exit 3\n"
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
    return f"""#!/usr/bin/env bash
# scitex-ci runner-fleet health monitor (generated by scitex_hpc.ci_runners).
# Run from a workstation crontab, e.g. every 5 min:
#   */5 * * * * /path/to/scitex-ci-monitor.sh >> ~/.scitex/ci/monitor.log 2>&1
set -uo pipefail

HOST="{host}"
LEASE_NAME="{lease_name}"
SRUN="{srun}"

{_ALARM_FUNC}
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
  ssh "$HOST" bash -lc \\
    "squeue --user=\\$USER {squeue_selector} --noheader --format='%i %T %N' 2>/dev/null" \\
    2>/dev/null | awk 'NR==1{{print $1, $2, $3}}'
)
if [ "${{STATE:-}}" != "RUNNING" ] || [ -z "${{JOBID:-}}" ] || [ -z "${{NODE:-}}" ]; then
  alarm "scitex-ci: supervisor allocation DOWN" \\
    "{target_ident} on $HOST is not RUNNING (state='${{STATE:-none}}'). {recover_hint}"
  echo "$TS CRITICAL allocation-down state=${{STATE:-none}}"
  exit 2
fi

# --- 2. per-runner listener liveness on the compute node --------------
# ONE srun --overlap step into the allocation lists every Runner.Listener
# cmdline; each runner is matched by its install dir appearing in the
# listener argv (run.sh passes the dir). This is read-only.
LIVE="$(
  ssh "$HOST" bash -lc \\
    "$SRUN --jobid=$JOBID --overlap pgrep -af Runner.Listener 2>/dev/null" \\
    2>/dev/null || true
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
    ssh "$HOST" bash -lc "touch '$dir/.needs-restart' 2>/dev/null" \\
      >/dev/null 2>&1 || true
  fi
done

if [ "${{#down[@]}}" -gt 0 ]; then
  alarm "scitex-ci: ${{#down[@]}} runner(s) DOWN on $NODE" \\
    "Down: ${{down[*]}}. Supervisor keep-alive should relaunch within the restart backoff; alarming so the operator can confirm recovery."
  echo "$TS DEGRADED node=$NODE down=${{down[*]}}"
  exit 1
fi

echo "$TS OK node=$NODE runners=$(echo "$RUNNER_NAMES" | wc -w)"
exit 0
"""
