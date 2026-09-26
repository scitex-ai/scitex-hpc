#!/bin/bash
# Watch the dotfiles SSoT gitconfig for CI-runner safe.directory accumulation.
#
# WHY THIS EXISTS, and why it is a WATCH rather than a fix:
# ~/.gitconfig on Spartan is a SYMLINK into the tracked dotfiles SSoT, so a CI
# job running `git config --global --add safe.directory <path>` writes into a
# VERSION-CONTROLLED file. actions/checkout does that unconditionally at job
# start and does not deduplicate, so growth is proportional to CI RUNS, not to
# repositories.
#
# Measured history:
#   2026-08-17  reset to 0 entries / 92 lines
#   2026-08-29  ~260 entries / ~350 lines, one runner (spartan-cpu-org-03)
#               -> ~22 entries/day, twelve days after a fix that was believed
#                  structural and was not
#
# On 2026-08-17 I wrote that the right artefact was "a watch on the file's line
# count" and that "nobody has ever pointed one at it -- the growth was invisible
# for months not because it was subtle but because nothing looked." Twelve days
# later nothing was looking, and the regression was found by accident. This is
# that watch.
#
# READ-ONLY BY DESIGN. It never edits, reverts or commits the file. The dotfiles
# SSoT is not this repo's to modify, and the entries are the only evidence of
# WHICH runner is writing -- clearing them destroys the diagnosis, which is the
# mistake the index.lock census was built to stop repeating.
set -u

GITCONFIG=${GITCONFIG_WATCH_TARGET:-$HOME/.gitconfig}
LOG=${GITCONFIG_WATCH_LOG:-$HOME/.scitex/hpc/runtime/gitconfig-drift.jsonl}
# Alarm above this many entries. 0 is the post-reset baseline; a handful of
# legitimate hand-added entries should not page anyone.
THRESHOLD=${GITCONFIG_WATCH_THRESHOLD:-20}

mkdir -p "$(dirname "$LOG")" 2>/dev/null

now=$(date -u +%FT%TZ)
host=$(hostname -s 2>/dev/null || echo unknown)

# --- Alarm sink, resolved by ABSOLUTE PATH, on EVERY run -----------------------
# Not `command -v`: a systemd --user unit gets
# PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin, which contains no
# scitex entry point, so a PATH lookup is false regardless of what is installed.
# Measured on this host 2026-08-29 via `systemd-run --user`.
# Resolution happens on every run, not only when alarming: a monitor that CANNOT
# report is broken NOW, and deferring that discovery to the day it matters means
# finding out too late.
_resolve_alarm_sink() {
  _c=""
  for _c in "${GITCONFIG_WATCH_ALARM_CMD:-}" "$HOME/.local/bin/scitex-ci-alarm"; do
    [ -n "$_c" ] && [ -x "$_c" ] && { printf '%s\n' "$_c"; return 0; }
  done
  return 1
}

SINK=$(_resolve_alarm_sink) || SINK=""
if [ -z "$SINK" ]; then
  echo "[gitconfig-watch] ERROR no alarm sink resolved (tried" \
       "\$GITCONFIG_WATCH_ALARM_CMD, \$HOME/.local/bin/scitex-ci-alarm)." \
       "Detection cannot be reported, so this run is a FAILURE even if the" \
       "file is clean." >&2
  exit 3
fi

if [ "${GITCONFIG_WATCH_SELFTEST:-0}" = "1" ]; then
  if "$SINK" "[selftest] gitconfig-drift-watch alarm rail reachable from $host" \
             -t "gitconfig-watch selftest" -l info; then
    echo "[gitconfig-watch] SELFTEST ok via $SINK" >&2; exit 0
  fi
  echo "[gitconfig-watch] SELFTEST FAILED via $SINK" >&2; exit 3
fi

# --- Measure -------------------------------------------------------------------
# Follow the symlink deliberately: the POINT is that ~/.gitconfig resolves into
# the tracked SSoT, so the resolved path is part of the finding and is recorded.
real=$(readlink -f "$GITCONFIG" 2>/dev/null || echo "$GITCONFIG")

# A MISSING FILE IS A BROKEN PROBE, NOT A CLEAN RESULT.
# Same guard as the index.lock census: an absent target and an empty target look
# identical in a count, and only one of them means "nothing to worry about".
if [ ! -r "$real" ]; then
  echo "[gitconfig-watch] ERROR: $real is not readable (via $GITCONFIG)." \
       "This is a FAILED LOOK, not a clean config. Do not read the 0 as" \
       "reassurance." >&2
  exit 2
fi

# NOT `grep -c ... || echo 0`. `grep -c` PRINTS "0" and EXITS 1 when nothing
# matches, so the `||` fires and appends a SECOND zero: entries becomes "0\n0"
# and every later integer test dies with "integer expression expected". The
# failure only appears on a CLEAN file -- i.e. the good case -- and would have
# reported drift on a config that had none. Caught by testing the clean path;
# the polluted path passes either way, which is exactly why testing only the
# interesting case is not enough.
entries=$(/usr/bin/grep -c '^[[:space:]]*directory[[:space:]]*=' "$real" 2>/dev/null)
entries=${entries:-0}
lines=$(wc -l < "$real" 2>/dev/null)
lines=${lines:-0}

PREV="none"
if [ -s "$LOG" ]; then
  PREV=$(/usr/bin/grep '"event":"gitconfig"' "$LOG" 2>/dev/null | tail -1 \
         | sed -n 's/.*"entries":\([0-9]*\).*/\1/p')
  PREV=${PREV:-none}
fi

printf '{"ts":%s,"host":"%s","event":"gitconfig","path":"%s","entries":%s,"lines":%s,"prev_entries":"%s"}\n' \
  "$(date -u +%s)" "$host" "$real" "$entries" "$lines" "$PREV" >> "$LOG"

echo "[gitconfig-watch] $now host=$host entries=$entries lines=$lines prev=$PREV path=$real"

# --- Alarm ON THE TRANSITION, not on the state ---------------------------------
# The file stays polluted until someone clears it, and this timer fires
# regularly, so alarming on "entries > threshold" would re-card the same
# condition every run until it was fixed -- which teaches everyone to ignore the
# alarm, the exact failure the alarm exists to prevent. Copied deliberately from
# index-lock-census, which learned it the same way.
if [ "$entries" -gt "$THRESHOLD" ] \
   && { [ "$PREV" = "none" ] || [ "$PREV" -le "$THRESHOLD" ] 2>/dev/null; }; then
  _msg=$(printf 'CI-runner safe.directory entries are accumulating in the dotfiles SSoT on %s: %s entries, %s lines in %s (threshold %s). ~/.gitconfig is a SYMLINK into the tracked repo, so `git config --global` from a CI job writes into version control. DO NOT just clear it -- the entries name WHICH runner is writing, which is the diagnosis. Card: ci-runners-write-uncommitted-into-dotfiles-ssot-20260802. Evidence: %s' \
         "$host" "$entries" "$lines" "$real" "$THRESHOLD" "$LOG")
  if [ "${GITCONFIG_WATCH_DRYRUN:-0}" = "1" ]; then
    echo "[gitconfig-watch] DRYRUN would alarm via $SINK: $_msg" >&2
  elif "$SINK" "$_msg" -t "gitconfig drift on $host" -l error; then
    echo "[gitconfig-watch] alarm sent via $SINK" >&2
  else
    echo "[gitconfig-watch] ERROR alarm SEND FAILED via $SINK — evidence is in $LOG" >&2
    exit 3
  fi
elif [ "$entries" -gt "$THRESHOLD" ]; then
  echo "[gitconfig-watch] still above threshold (prev=$PREV); already alarmed, not re-sending" >&2
fi

# exit 1 == drift present. That is the monitor WORKING, not failing; the unit
# declares SuccessExitStatus=0 1 so a true positive does not render as a broken
# unit while the timer keeps firing.
[ "$entries" -le "$THRESHOLD" ] || exit 1
exit 0
