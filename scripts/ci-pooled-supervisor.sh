#!/bin/bash
#SBATCH --partition=sapphire
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=128G
#SBATCH --time=1-00:00:00
#SBATCH --account=punim0264
#SBATCH --qos=publiccpu
#SBATCH --job-name=spartan-ci-runner-pooled-supervisor
#SBATCH --signal=B:USR1@3600
# Pooled org-level CI runner supervisor (2026-07-13, operator escalation via
# scitex-agent-container: CI felt slow, wants permanent allocations + fast
# parallel dispatch, ~64c/128GB each, hold multiple if needed).
#
# WALLTIME CHOSEN EMPIRICALLY, not by convention: sapphire is deeply
# contended right now (5811 pending jobs, ~94% from one other user's
# array). Live-tested via real submissions (not just --test-only, which
# gave a wildly pessimistic ~2-month estimate for ANY size at 14-day
# walltime): a 64c/128GB request backfills and starts within seconds at
# walltimes up to 24h, but gets genuinely Priority-blocked at 14 days.
# So: SHORT walltime (24h) + frequent verified resubmit, not long walltime
# + rare resubmit -- permanence comes from the resubmit, not the walltime
# (see 14_permanent-allocation-doctrine.md, scitex-hpc PR #58). Re-verify
# this empirically if scheduling conditions change; don't treat 24h as
# doctrine, it's this cluster's current congestion talking.
#
# Separate CI dir from the existing 76 repo-pinned runners
# (spartan-ci-runner-supervisor / $CI=.../ci) -- additive pilot, zero risk
# to the existing fleet while this is being validated.
CI=/data/gpfs/projects/punim0264/ywatanabe/ci-pooled
WORK_ROOT=/tmp/scitex-ci-pooled-work
TOOLCACHE="$HOME/.runner-toolcache"
SENTINEL="$WORK_ROOT/.supervisor-live"
TRACKED_DIR="$WORK_ROOT/.tracked"
RESCAN_INTERVAL=300
FAIL_MARKER="$HOME/.scitex/hpc/runtime/ci-pooled-supervisor-resubmit-FAILED"
SBATCH_BIN="$(command -v sbatch 2>/dev/null)"
[ -x "$SBATCH_BIN" ] || SBATCH_BIN="/apps/slurm/latest/bin/sbatch"
_resubmit() {
  echo "[pooled-supervisor] walltime; resubmitting $0 via $SBATCH_BIN" >&2
  mkdir -p "$(dirname "$FAIL_MARKER")" 2>/dev/null
  if [ -x "$SBATCH_BIN" ] && "$SBATCH_BIN" "$0"; then
    rm -f "$FAIL_MARKER" 2>/dev/null
  else
    echo "[pooled-supervisor] RESUBMIT FAILED (sbatch bin='$SBATCH_BIN') -- pooled runners will die with no successor job" >&2
    echo "$(date -u +%FT%TZ) resubmit of $0 failed; SBATCH_BIN='$SBATCH_BIN'" > "$FAIL_MARKER" 2>/dev/null
  fi
}
trap _resubmit USR1
mkdir -p "$WORK_ROOT" "$TRACKED_DIR" "$CI"
echo "$(date -u +%FT%TZ) $(hostname)" > "$SENTINEL"
trap 'rm -f "$SENTINEL"' TERM INT
# --- env hardening ---
source "$HOME/.bashrc" 2>/dev/null || true
module purge 2>/dev/null || true
for _n in $(compgen -v 2>/dev/null); do
  case "$_n" in
    *PASSWORD*|*PASSWD*|*TOKEN*|*SECRET*|*API_KEY*|*APIKEY*|*_KEY|*_KEYS|*BEARER*|*CREDENTIAL*|*CONSUMER_KEY*|*ACCESS_KEY*|*PRIVATE_KEY*) unset "$_n" 2>/dev/null || true ;;
  esac
done
unset _n PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
_scrub() { echo "${1:-}" | tr ':' '\n' | grep -v easybuild | grep -v '^$' | tr '\n' ':' | sed 's/:$//'; }
export LD_LIBRARY_PATH="$(_scrub "${LD_LIBRARY_PATH:-}")"
export PATH="$(_scrub "${PATH:-}")"
export AGENT_TOOLSDIRECTORY="$TOOLCACHE"
export RUNNER_TOOL_CACHE="$TOOLCACHE"
export TMPDIR="$WORK_ROOT/tmp" TMP="$WORK_ROOT/tmp" TEMP="$WORK_ROOT/tmp"
mkdir -p "$TMPDIR"
HOOK="$WORK_ROOT/clear_temp_hook.sh"
printf '%s\n' '#!/usr/bin/env bash' '[ -n "${RUNNER_TEMP:-}" ] && rm -rf "$RUNNER_TEMP" 2>/dev/null' 'exit 0' > "$HOOK"; chmod +x "$HOOK"
export ACTIONS_RUNNER_HOOK_JOB_COMPLETED="$HOOK"
# --- per-runner keepalive ---
_spawn_keepalive() {
  d="$1"
  tag="$(basename "$d")"; tag="${tag#actions-runner-}"
  (
    wd="$WORK_ROOT/$tag"; mkdir -p "$wd"
    if [ ! -L "$d/_work" ]; then mv "$d/_work" "$d/_work.stale.$$" 2>/dev/null; rm -rf "$d/_work.stale.$$" 2>/dev/null & fi
    ln -sfn "$wd" "$d/_work"
    while [ -f "$SENTINEL" ]; do
      rm -rf "$wd/_temp"
      ( cd "$d" && RUNNER_WORK_DIRECTORY="$wd" PATH="$d/shims:$HOME/.cargo/bin:$HOME/.local/bin:$PATH" ./run.sh ) >> "$d/keepalive.log" 2>&1
      [ -f "$SENTINEL" ] || break
      sleep 15
    done
  ) &
}
# Is a live listener already serving this runner directory?
#
# The marker file records that we ONCE spawned a keepalive; it is not
# evidence that one is alive, and it is not evidence that one is absent.
# The process table is. This is a positive check against the actual world,
# so it holds no matter how a marker is lost, duplicated, or raced.
#
# MUST resolve the path first. A runner directory may be a SYMLINK into this
# tree (that is how a runner from a dead supervisor's pool is adopted by a
# surviving allocation), and the listener process reports its RESOLVED path
# in argv. Matching the symlink path finds nothing, so the guard would fail
# OPEN and cheerfully spawn the duplicate it exists to prevent -- silently,
# and only for adopted runners, which are exactly the ones in an unusual
# enough state to warrant the check. Verified against a live grafted runner:
# symlink pattern NO-MATCH, resolved pattern MATCH.
#
# SCOPE LIMIT -- READ THIS BEFORE RELYING ON IT. `pgrep` reads the LOCAL
# node's process table, so this guard prevents duplicate loops WITHIN one
# allocation. It CANNOT see a listener for the same runner started by a
# DIFFERENT supervisor on a DIFFERENT node, and two supervisors serving one
# runner registration produce SessionConflictException plus the same
# _temp race this guard exists to prevent.
#
# Practical consequence: never run two supervisors over overlapping runner
# sets. In particular, do not submit this script while its runners are
# grafted into another allocation's tree -- retire the graft FIRST. See
# scripts/README.md "Cutting over".
_listener_running() {
  _real="$(readlink -f "$1" 2>/dev/null)" || _real=""
  [ -n "$_real" ] || _real="$1"
  pgrep -f "^$_real/bin/Runner.Listener" >/dev/null 2>&1
}
_scan_and_spawn() {
  for d in "$CI"/actions-runner-*/; do
    d="${d%/}"
    [ -x "$d/run.sh" ] || continue
    case "$d" in *.wrap.log) continue;; esac
    tag="$(basename "$d")"; tag="${tag#actions-runner-}"
    marker="$TRACKED_DIR/$tag"
    [ -f "$marker" ] && continue
    # NEVER run two keepalive loops for one runner. Each loop does
    # `rm -rf "$wd/_temp"` on every iteration, so a second loop deletes the
    # first listener's job temp directory out from under its worker: the
    # worker stalls, the listener keeps renewing the job once a minute, and
    # the run burns to its timeout having executed ZERO steps. Observed
    # 2026-07-21 on two runners; the marker files were intact throughout, so
    # marker-based dedup alone did not prevent it and the provenance of the
    # duplicate loops was never established. Hence this check, which does not
    # depend on knowing how the duplication happened.
    if _listener_running "$d"; then
      echo "[pooled-supervisor] $tag already has a live listener; adopting marker, NOT spawning a second keepalive" >&2
      touch "$marker"
      continue
    fi
    touch "$marker"
    echo "[pooled-supervisor] $([ "$2" = "rescan" ] && echo "rescan found new" || echo "launching") keepalive for $tag" >&2
    _spawn_keepalive "$d"
  done
}
_scan_and_spawn "$CI" "initial"
(
  while [ -f "$SENTINEL" ]; do
    sleep "$RESCAN_INTERVAL"
    [ -f "$SENTINEL" ] || break
    _scan_and_spawn "$CI" "rescan"
  done
) &
echo "[pooled-supervisor] launched keepalive loops + periodic rescan (every ${RESCAN_INTERVAL}s) on $(hostname); waiting" >&2

# SERVE OUT THE FULL WALLTIME -- do not exit when the USR1 handler returns.
#
# `wait` is interrupted by the USR1 trap. With a BARE `wait`, the handler
# runs (submitting the successor), `wait` then returns, the script falls off
# the end, and the allocation is surrendered ~1h before its walltime.
# Measured: Timelimit 1-00:00:00 but Elapsed 22:59:5x on every hop.
#
# That forfeited hour is exactly the window that should cover the
# successor's SLURM queue wait. Because the incumbent left early, each
# successor's wait was served with NO runner online at all:
#
#   27225547  submitted 07-14T12:21:16  started 07-14T12:22:20    64s
#   27281296  submitted 07-15T11:21:52  started 07-15T13:24:27  2h 02m
#   27331011  submitted 07-16T12:24:26  started 07-17T04:27:04  16h 03m
#   27709706  submitted 07-21T00:26:56  did not backfill        OUTAGE
#
# (cluster-local times; Spartan is UTC+10.) Re-entering `wait` keeps this
# allocation serving jobs until SLURM actually kills it at the walltime
# boundary, so the successor queues while the service is still UP. The
# overlap is free -- it uses time already allocated and previously wasted.
#
# This does NOT lengthen the walltime. 24h is deliberate: a 64c/128GB
# request backfills in seconds at 24h and is Priority-blocked at 14 days on
# this partition. Permanence comes from the resubmit, not the walltime.
while [ -f "$SENTINEL" ]; do
  wait || true
  # `wait` also returns immediately if no children remain; bound the loop
  # so a fully-dead runner set cannot spin the CPU.
  sleep 5
done
