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

printf '{"ts":%s,"host":"%s","event":"census","scanned":%s,"locked":%s}\n' \
  "$now" "$host" "$scanned" "$locked" >> "$LOG"

echo "[lock-census] $(date -u +%FT%TZ) host=$host scanned=$scanned locked=$locked log=$LOG"

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

# exit 1 == locks present. That is the monitor WORKING, not failing; the unit
# declares SuccessExitStatus=0 1 so a true positive does not render as a broken
# unit while the timer keeps firing.
[ "$locked" -eq 0 ] || exit 1
exit 0
