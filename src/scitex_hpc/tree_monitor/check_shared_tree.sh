#!/usr/bin/env bash
# Catch-it-live monitor for shared punim0264 tree deletions.
#
# WHY THIS EXISTS: ~/.scitex/hpc/, ~/.scitex/dev/containers/ and the clew
# for_solver roots have vanished before, and every post-hoc attempt to identify
# the deleter failed — crontab disabled, systemd --user swept twice, own SLURM
# history clean, four concrete leads closed with hard evidence. Forensics after
# the fact are exhausted. This catches the NEXT one while it is happening.
#
# WHAT IT DOES: stat a fixed manifest of critical paths, diff against the
# last-known-present state persisted between runs, and on a path that WAS
# present and is now MISSING, capture cheap in-the-moment forensics and alarm
# loudly through scitex-todo — not merely a local log, which is what a deleter
# would also be able to remove.
#
# THREE-VALUED BY CONSTRUCTION. A path is PRESENT, MISSING, or UNKNOWN. It only
# alarms on a present->missing TRANSITION, never on "I could not tell":
#   - first run has no baseline               -> record, never alarm
#   - stat itself fails (GPFS hiccup, EIO)    -> UNKNOWN, never alarm, and the
#                                                baseline is NOT overwritten, so
#                                                a real deletion during an
#                                                unreadable window is still
#                                                caught on the next good run
# Collapsing UNKNOWN into MISSING would page on every filesystem stutter and
# train everyone to ignore it; collapsing it into PRESENT would lose the event.
#
# MANIFEST IS PARTIAL AND SAYS SO. It covers the paths I own and can verify.
# paper-scitex-clew and scitex-storage were to confirm their own critical paths
# and are unreachable, so their entries are absent rather than guessed. A
# monitor over the paths we know beats no monitor; add lines as owners confirm.
set -uo pipefail

STATE_DIR="${SCITEX_TREE_MONITOR_STATE:-$HOME/.scitex/hpc/runtime}"
STATE="$STATE_DIR/shared-tree-manifest.state"
LOG="$STATE_DIR/shared-tree-monitor.log"
mkdir -p "$STATE_DIR"

# The manifest. One path per line. Comments and blanks ignored.
# Keep ABSOLUTE and avoid globs: a glob that matches nothing is
# indistinguishable from a path that was deleted.
MANIFEST="${SCITEX_TREE_MANIFEST:-}"
if [ -z "$MANIFEST" ]; then
    MANIFEST=$(cat <<'PATHS'
$HOME/.scitex/hpc
$HOME/.scitex/dev/containers
$HOME/.scitex/dev/containers/ci-cpu.sif
PATHS
)
fi

now() { date -u +%FT%TZ; }
log() { printf '%s %s\n' "$(now)" "$*" >> "$LOG"; }

# --- read the manifest into a present/missing/unknown map -------------------
declare -A CUR
while IFS= read -r raw; do
    line="${raw%%#*}"; line="$(printf '%s' "$line" | xargs 2>/dev/null || true)"
    [ -z "$line" ] && continue
    p="$(eval printf '%s' "\"$line\"")"          # expand $HOME only
    if stat "$p" >/dev/null 2>&1; then
        CUR["$p"]=PRESENT
    elif [ -e "$p" ] 2>/dev/null; then
        # exists but stat failed — genuinely ambiguous
        CUR["$p"]=UNKNOWN
    else
        # distinguish "definitely gone" from "cannot read the parent at all":
        # if the PARENT is unreadable we cannot claim the child is missing.
        parent="$(dirname "$p")"
        if stat "$parent" >/dev/null 2>&1; then CUR["$p"]=MISSING; else CUR["$p"]=UNKNOWN; fi
    fi
done <<< "$MANIFEST"

# --- load the previous state ------------------------------------------------
declare -A PREV
if [ -f "$STATE" ]; then
    while IFS=$'\t' read -r st p; do [ -n "${p:-}" ] && PREV["$p"]="$st"; done < "$STATE"
fi

# --- detect PRESENT -> MISSING transitions ----------------------------------
VANISHED=()
for p in "${!CUR[@]}"; do
    if [ "${CUR[$p]}" = "MISSING" ] && [ "${PREV[$p]:-}" = "PRESENT" ]; then
        VANISHED+=("$p")
    fi
done

# --- persist, but NEVER overwrite a PRESENT baseline with UNKNOWN -----------
: > "$STATE.new"
for p in "${!CUR[@]}"; do
    st="${CUR[$p]}"
    [ "$st" = "UNKNOWN" ] && st="${PREV[$p]:-UNKNOWN}"
    printf '%s\t%s\n' "$st" "$p" >> "$STATE.new"
done
mv "$STATE.new" "$STATE"

if [ ${#VANISHED[@]} -eq 0 ]; then
    log "ok $(printf '%s' "${#CUR[@]}") path(s) checked, no present->missing transition"
    exit 0
fi

# --- a path vanished: capture forensics WHILE IT IS HAPPENING ---------------
FORENSICS="$STATE_DIR/vanish-$(date -u +%Y%m%dT%H%M%SZ).txt"
{
    echo "VANISHED AT $(now)"
    for p in "${VANISHED[@]}"; do echo "  MISSING: $p"; done
    echo
    echo "== parent listings =="
    for p in "${VANISHED[@]}"; do echo "--- $(dirname "$p")"; ls -la "$(dirname "$p")" 2>&1 | head -30; done
    echo
    echo "== my SLURM jobs at this moment =="
    (squeue -u "$USER" -o '%i %T %N %j' 2>&1 || echo "squeue unavailable") | head -20
    echo
    echo "== who is on this node =="
    (who 2>&1 || true) | head -10
    echo "hostname: $(hostname -s)  uid: $(id -un)"
} > "$FORENSICS" 2>&1

log "ALARM ${#VANISHED[@]} path(s) vanished; forensics -> $FORENSICS"

# --- alarm LOUDLY through the shared board, not just a local file -----------
# A local log is exactly what a deleter could also remove. The card is the rail
# that survives the host.
#
# SCITEX_TREE_MONITOR_DRYRUN=1 suppresses the card write. This exists because
# testing this script WITHOUT it puts a real P1 alarm card on the shared fleet
# board — measured 2026-08-05: exercising the deletion branch created
# spartan-shared-tree-vanish-20260805T163310Z against a temp path, which I then
# had to hunt down and delete. An alarm path that cannot be rehearsed safely
# will either go untested or teach everyone to ignore its cards.
if [ "${SCITEX_TREE_MONITOR_DRYRUN:-0}" = "1" ]; then
    log "DRYRUN alarm suppressed; would have carded ${#VANISHED[@]} vanished path(s)"
    echo "DRYRUN: would alarm for: ${VANISHED[*]}"
elif command -v scitex-todo >/dev/null 2>&1; then
    SCITEX_TODO_AGENT_ID=scitex-hpc scitex-todo add \
        "spartan-shared-tree-vanish-$(date -u +%Y%m%dT%H%M%SZ)" \
        "[P1][ALARM] shared tree path(s) vanished on $(hostname -s) — caught live" \
        --status blocked --blocker operator-decision \
        --assignee scitex-hpc --project scitex-hpc --priority 1 \
        --task "$(printf 'Caught by the catch-it-live monitor at %s.\n\nVANISHED:\n%s\n\nForensics captured on the host at:\n  %s\n\nThis is the in-the-moment evidence the previous incidents lacked — every post-hoc investigation failed to identify the deleter.\n' \
                 "$(now)" "$(printf '  %s\n' "${VANISHED[@]}")" "$FORENSICS")" \
        >/dev/null 2>&1 && log "alarm card created" || log "WARN alarm card FAILED — local forensics only"
else
    log "WARN scitex-todo unavailable on this host — local forensics only at $FORENSICS"
fi
exit 1
