#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ci-runner-dup-watch.sh — capture a duplicate keepalive AT THE MOMENT IT IS BORN.
#
# WHY THIS EXISTS. Duplicate Runner.Listener processes for one runner are a real
# fault (two keepalive loops each `rm -rf`-ing the shared `_temp`, stalling the
# other's job into a zero-step timeout). Three attempts to explain WHERE they
# came from were RECONSTRUCTIONS after the fact, and all three were wrong:
#   - "the rescan keeps spawning them" -> those log lines were from 07-14
#   - "GPFS quota broke marker creation" -> TRACKED_DIR is node-local /tmp
#   - "the rescan loop is dead" -> read with an ambiguous pgrep selector
#
# THIS SCRIPT SETTLED IT ON ITS FIRST RUN, and the answer contradicted all of
# them. Captured ancestry, live, for one runner:
#
#   new listener 19079 <- 19052 <- 222511 (born Tue Jul 14 00:06:54) <- 45403
#   old listener 41150 <- 41111 <-   5732 (born Tue Jul 14 00:16:55) <- 45403
#
# 222511 and 5732 are TWO keepalive subshells for the SAME runner, created ten
# minutes apart on 07-14 and both still alive. The marker mtime matches 5732 to
# the second.
#
# So the duplication was a SINGLE EVENT on 07-14 that never healed -- not a
# recurring spawn. What recurs is only the LISTENER, because each loop correctly
# restarts `run.sh` after it exits. That is why killing listeners never held:
# it killed the output of two healthy loops and left the loops running. The
# remediation is to kill one LOOP per affected runner, which is a different
# command than the obvious one.
#
# Keep this running. The forensic trail is gone within seconds of a loop being
# reaped, and every wrong answer above came from looking after the fact.
#
# Deliberately records rather than repairs. Killing duplicates has been shown
# not to hold, and a watcher that also acts would destroy the evidence it
# exists to collect.
#
# RUN INSIDE THE ALLOCATION, DETACHED:
#   JOBID=$(squeue --user="$USER" --name=spartan-ci-runner-supervisor \
#                  --states=RUNNING --noheader --format='%i' | head -1)
#   srun --jobid="$JOBID" --overlap -n1 \
#       setsid nohup bash scripts/ci-runner-dup-watch.sh &
#
# `/tmp` is node-local, so the LOG goes to GPFS (shared, readable from a login
# node); the WATCHING must happen on the runner node. Those are different
# requirements and they pull in opposite directions -- do not "simplify" by
# putting both in one place.
# ---------------------------------------------------------------------------
set -uo pipefail

CI="${CI_ROOT:-/data/gpfs/projects/punim0264/ywatanabe/ci}"
LOG="${DUP_WATCH_LOG:-/data/gpfs/projects/punim0264/ywatanabe/ci-dup-watch.log}"
INTERVAL="${DUP_WATCH_INTERVAL:-20}"

# pid -> runner tag, for listeners already seen. A pid appearing here is not
# news; a pid NOT here, for a runner that already had one, is the event.
declare -A seen

_stamp() { date -u +%FT%TZ; }

_snapshot() {
    # Capture while the ancestry still exists. Walk up from the new listener:
    # the parent chain is the whole question, and it is gone within seconds of
    # the loop being reaped.
    local pid="$1" tag="$2"
    {
        echo "=== $(_stamp) NEW LISTENER pid=$pid runner=$tag host=$(hostname -s)"
        echo "--- ancestry"
        local p="$pid" i
        for i in 1 2 3 4 5 6; do
            local line
            line="$(ps -o pid=,ppid=,lstart=,args= -p "$p" 2>/dev/null | head -1)"
            [ -z "$line" ] && break
            echo "    $line"
            p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
            [ -z "$p" ] && break
            [ "$p" = "1" ] && { echo "    (reparented to init)"; break; }
        done
        echo "--- all listeners for this runner"
        ps -o pid=,ppid=,lstart=,args= -C Runner.Listener 2>/dev/null | grep -F "$tag" || echo "    (none)"
        echo "--- marker"
        ls -la --time-style=+%F_%T "/tmp/scitex-ci-runner-work/.tracked/$tag" 2>&1 | tail -1
        echo "--- supervisor log tail"
        tail -3 "$HOME/slurm-27144058.out" 2>/dev/null || echo "    (unreadable)"
        echo
    } >> "$LOG" 2>&1
}

echo "=== $(_stamp) dup-watch started on $(hostname -s), interval ${INTERVAL}s" >> "$LOG"

# Prime: everything currently running is the baseline, not an event.
while read -r pid path; do
    [ -z "$pid" ] && continue
    tag="$(basename "$(dirname "$(dirname "$path")")")"
    seen["$pid"]="$tag"
done < <(pgrep -a -x Runner.Listener 2>/dev/null | awk '{print $1, $2}')

echo "    primed with ${#seen[@]} existing listener(s)" >> "$LOG"

while :; do
    while read -r pid path; do
        [ -z "$pid" ] && continue
        [ -n "${seen[$pid]:-}" ] && continue
        tag="$(basename "$(dirname "$(dirname "$path")")")"
        tag="${tag#actions-runner-}"
        seen["$pid"]="$tag"
        # Only interesting if this runner ALREADY had a listener -- a lone
        # restart after a crash is normal keepalive behaviour, not the fault.
        n="$(pgrep -f "/actions-runner-$tag/bin/Runner.Listener" 2>/dev/null | wc -l)"
        if [ "$n" -gt 1 ]; then
            _snapshot "$pid" "$tag"
        fi
    done < <(pgrep -a -x Runner.Listener 2>/dev/null | awk '{print $1, $2}')
    sleep "$INTERVAL"
done
