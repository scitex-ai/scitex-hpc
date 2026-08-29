#!/bin/bash
# READ-ONLY census of stale .git/index.lock across the Spartan repo estate.
#
# IT REMOVES NOTHING, EVER, AND THAT IS THE POINT.
#
# On 2026-08-15, 59 of 108 repos on Spartan were found write-locked by 0-byte
# index.lock files, some for up to two months. They were cleared — and clearing
# them destroyed their mtimes, which were the only evidence capable of
# identifying the recurring nightly process that laid them. The card records it
# plainly: "REMEDIATING DESTROYED THE DIAGNOSTIC." Capturing `stat` first would
# have cost one command.
#
# So this monitor observes and records. Whoever clears the locks does it as a
# separate, deliberate act, after the evidence is already on disk.
#
# WHY A STALE LOCK IS INVISIBLE, which is why nobody noticed for two months:
# a stale index.lock blocks every WRITE and no READ. `git log`, `rev-parse`,
# `rev-list --count` and `grep` all succeed normally, so a locked repo is
# indistinguishable from a healthy one by inspection and reports itself as fine.
# One measured example: `git rev-list --count HEAD..origin/develop` returned 0
# ("up to date") for a repo that was 57 commits behind and had been unwritable
# for 18 days — the 0 came from a remote-tracking ref last fetched 51 days
# earlier. Both readings were reassuring and both were worthless.
set -u

# Repo parents. Fixed-depth globs only — NO `find`, NO `du`. Two admin warnings
# about tree walks on shared GPFS (2026-06-09, 2026-07-01) make a third a
# cluster-access risk.
PARENTS=${LOCK_CENSUS_PARENTS:-"/data/gpfs/projects/punim0264/ywatanabe $HOME/proj"}
LOG=${LOCK_CENSUS_LOG:-$HOME/.scitex/hpc/runtime/index-lock-census.jsonl}

mkdir -p "$(dirname "$LOG")" 2>/dev/null

SEEN=$(mktemp) || exit 2
trap 'rm -f "$SEEN"' EXIT

scanned=0
locked=0
now=$(date -u +%s)
host=$(hostname -s)

for parent in $PARENTS; do
  for g in "$parent"/*/.git; do
    [ -e "$g" ] || continue
    # DEDUPE BY REALPATH. $HOME/proj/<pkg> is a SYMLINK to the GPFS tree, so
    # globbing both arms counts many repos twice — that is exactly how 59
    # distinct locked repos were first reported as 85, and "61% of the estate"
    # was arithmetic on two inflated numbers.
    real=$(realpath "$g" 2>/dev/null) || continue
    grep -qxF "$real" "$SEEN" && continue
    printf '%s\n' "$real" >> "$SEEN"
    scanned=$((scanned + 1))

    lock="$real/index.lock"
    [ -e "$lock" ] || continue
    locked=$((locked + 1))
    # EPOCH is load-bearing: the correlation test is `sacct --format=End` in
    # epoch seconds, and this host has already produced one phantom anomaly
    # from a JST/AEST mix-up. Never emit bare local time.
    mt=$(stat -c %Y "$lock" 2>/dev/null)
    sz=$(stat -c %s "$lock" 2>/dev/null)
    printf '{"ts":%s,"host":"%s","event":"lock","repo":"%s","mtime_epoch":%s,"size":%s}\n' \
      "$now" "$host" "$real" "${mt:-0}" "${sz:-0}" >> "$LOG"
  done
done

# PREVIOUS locked count, read BEFORE this run's census line is appended, so the
# comparison is against the last run rather than against ourselves.
# "none" when no prior census exists.
PREV=none
if [ -s "$LOG" ]; then
  PREV=$(grep '"event":"census"' "$LOG" 2>/dev/null | tail -1 \
         | sed -n 's/.*"locked":\([0-9]*\).*/\1/p')
  [ -n "$PREV" ] || PREV=none
fi

printf '{"ts":%s,"host":"%s","event":"census","scanned":%s,"locked":%s,"prev_locked":"%s"}\n' \
  "$now" "$host" "$scanned" "$locked" "$PREV" >> "$LOG"

echo "[lock-census] $(date -u +%FT%TZ) host=$host scanned=$scanned locked=$locked prev=$PREV log=$LOG"

# A SCANNED COUNT OF ZERO IS A BROKEN PROBE, NOT AN EMPTY ESTATE.
# If the globs match nothing — wrong host, moved tree, unmounted GPFS — the
# census would otherwise report "0 locked" and read as healthy. That is the
# absence-indistinguishable-from-failure shape this estate keeps producing, so
# it is made loud here rather than left to a reader.
if [ "$scanned" -eq 0 ]; then
  echo "[lock-census] ERROR: scanned 0 repos. The parent globs matched nothing" >&2
  echo "[lock-census]        (PARENTS='$PARENTS'). This is a FAILED LOOK, not a" >&2
  echo "[lock-census]        clean estate. Do not read the 0 as reassurance." >&2
  exit 2
fi

# --- ALARM through the shared board, because an exit code has no reader --------
# This monitor shipped without this block and was, for its first hours, a
# recorder nobody opened: it exited 1 on detection into a unit declaring
# SuccessExitStatus=0 1, so a real find rendered as success and the JSONL had no
# consumer. The exit code carried the verdict to systemd, and systemd had been
# told to treat it as success.
#
# ALARM ON THE TRANSITION, NOT ON THE STATE. Locks persist until someone clears
# them, and this timer fires every 6h, so alarming on "locks present" would card
# the same batch four times a day until it was fixed — which teaches everyone to
# ignore the cards, the exact failure the alarm exists to prevent.
#   prev=0 or none, now>0  -> ALARM (new batch)
#   prev>0,         now>0  -> already alarmed, log only
#   now=0                  -> nothing
# Alarming on a first run WITH no baseline is deliberate here, and differs from
# tree_monitor: a MISSING path might never have existed, so absence needs a
# baseline — but a PRESENT lock is unambiguous evidence on its own.
#
# LOCK_CENSUS_DRYRUN=1 suppresses the SEND, never the sink RESOLUTION. That
# distinction is the whole point of the 2026-08-29 rewrite below.

# --- Alarm sink, resolved by ABSOLUTE PATH on EVERY run ------------------------
# The previous version guarded the alarm with `command -v scitex-todo` and, on
# failure, warned to stderr. Every part of that was wrong, measured 2026-08-29:
#
#   1. A systemd --user unit gets PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:
#      /usr/sbin -- verified with `systemd-run --user`. NO scitex entry point is
#      on it. So `command -v <anything scitex>` is FALSE under systemd no matter
#      what it is called or whether it is installed. The guard could not pass.
#   2. `scitex-todo` is the RETIRED name; the current package reads only
#      SCITEX_CARDS_AGENT_ID. The branch exported the old variable.
#   3. scitex_cards is not installed on this host at all (ModuleNotFoundError),
#      so no card CLI can work here regardless. Notification is the only rail.
#   4. The else-branch warned to stderr -> journal, and this unit's journal has
#      held ZERO lines for fourteen days. The warning that the alarm was broken
#      was itself delivered nowhere.
#
# Hence: absolute paths, not PATH lookup; and resolution happens on EVERY run,
# not only when alarming. A monitor that CANNOT report is broken NOW -- deferring
# that discovery to the day locks return means discovering it exactly when it is
# too late to matter. Resolution failure exits 3 (the unit declares
# SuccessExitStatus=0 1, so 3 renders as a genuine failure).
#
# NOTE the remaining gap, stated rather than papered over: a failed unit is
# visible in `systemctl --user --failed` but still pushes nothing to a human.
# Wiring OnFailure= is tracked on no-onfailure-anywhere-systemd-failures-reach
# -nobody-20260816. This change moves the failure from invisible to pullable,
# which is an improvement and not yet an alarm.
_resolve_alarm_sink() {
  _c=""
  for _c in "${LOCK_CENSUS_ALARM_CMD:-}" "$HOME/.local/bin/scitex-ci-alarm"; do
    [ -n "$_c" ] && [ -x "$_c" ] && { printf '%s\n' "$_c"; return 0; }
  done
  return 1
}

SINK=$(_resolve_alarm_sink) || SINK=""
if [ -z "$SINK" ]; then
  echo "[lock-census] ERROR no alarm sink resolved (tried \$LOCK_CENSUS_ALARM_CMD," >&2
  echo "[lock-census]       \$HOME/.local/bin/scitex-ci-alarm). Detection cannot be" >&2
  echo "[lock-census]       reported, so this run is a FAILURE even if 0 locks were" >&2
  echo "[lock-census]       found. Evidence, if any, is in $LOG" >&2
  exit 3
fi

# LOCK_CENSUS_ALARM_SELFTEST=1 sends a real notification and exits. This is the
# rehearsal the old DRYRUN could not provide: DRYRUN returned before touching the
# sink, so the one thing that was broken was the one thing it did not exercise.
if [ "${LOCK_CENSUS_ALARM_SELFTEST:-0}" = "1" ]; then
  if "$SINK" "[selftest] index-lock-census alarm rail is reachable from $host" \
             -t "lock-census selftest" -l info; then
    echo "[lock-census] SELFTEST ok via $SINK" >&2; exit 0
  else
    echo "[lock-census] SELFTEST FAILED via $SINK" >&2; exit 3
  fi
fi

if [ "$locked" -gt 0 ] && { [ "$PREV" = "none" ] || [ "$PREV" -eq 0 ] 2>/dev/null; }; then
  _msg=$(printf '[ALARM] stale .git/index.lock returned on %s: %s of %s repos locked. DO NOT CLEAR THEM YET -- the mtimes ARE the evidence; the 2026-08-15 remediation cleared 59 locks and destroyed the only data that could identify the recurring cause. Correlate first: compare mtime_epoch against `sacct --format=End` in epoch seconds, computed ON Spartan (a bare 10-digit epoch is secret-shaped and gets redacted in an agent transcript, so return the derived verdict, not the numbers). Evidence: %s' \
         "$host" "$locked" "$scanned" "$LOG")
  if [ "${LOCK_CENSUS_DRYRUN:-0}" = "1" ]; then
    echo "[lock-census] DRYRUN would alarm via $SINK: $_msg" >&2
  elif "$SINK" "$_msg" -t "index.lock recurrence on $host" -l error; then
    echo "[lock-census] alarm sent via $SINK" >&2
  else
    echo "[lock-census] ERROR alarm SEND FAILED via $SINK — evidence is in $LOG" >&2
    exit 3
  fi
elif [ "$locked" -gt 0 ]; then
  echo "[lock-census] locks still present (prev=$PREV); already alarmed, not re-sending" >&2
fi

# exit 1 == locks present. That is the monitor WORKING, not failing; the unit
# declares SuccessExitStatus=0 1 so a true positive does not render as a broken
# unit while the timer keeps firing.
[ "$locked" -eq 0 ] || exit 1
exit 0
