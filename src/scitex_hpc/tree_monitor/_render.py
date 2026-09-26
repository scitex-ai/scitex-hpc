"""Render the tree-monitor script and its systemd units from a profile.

Same convention as :mod:`scitex_hpc.tunnel_supervisor._render`: pure string
generation, no filesystem access and no process launch, so every branch is
unit-testable by asserting on the rendered text. :mod:`._install` is the
only module that writes bytes.

WHAT MOVED, AND WHY IT MATTERS
  - the manifest was a heredoc inside the script; it is now templated from
    ``profile.manifest``, so adding a path is a config edit
  - the units hard-coded ``%h/.scitex/hpc/scripts/check_shared_tree.sh``;
    the ExecStart is now rendered from ``profile.script_path``, so the same
    code installs on a second machine instead of one

WHAT DID NOT MOVE, DELIBERATELY: the script's three-valued logic. A path is
PRESENT, MISSING or UNKNOWN, and only a PRESENT->MISSING transition alarms.
Collapsing UNKNOWN into MISSING would page on every filesystem stutter and
train everyone to ignore the alarm; collapsing it into PRESENT would lose
the event. That is the whole correctness argument of this monitor and it is
reproduced here verbatim rather than paraphrased.
"""

from __future__ import annotations

from ._profile import EXAMPLE_PROFILE, TreeMonitorProfile


def render_manifest_block(profile: TreeMonitorProfile = EXAMPLE_PROFILE) -> str:
    """Return the manifest lines plus the unconfirmed-owner comments.

    Split out so a test can assert on the manifest alone without matching
    the whole script, and so a caller can show an operator what would be
    watched before installing anything.
    """
    lines = [
        "# The manifest. One path per line. Comments and blanks ignored.",
        "# Keep ABSOLUTE and avoid globs: a glob that matches nothing is",
        "# indistinguishable from a path that was deleted.",
    ]
    if profile.unconfirmed_owners:
        lines.append("#")
        lines.append("# PARTIAL BY CONSTRUCTION. These owners have not confirmed their")
        lines.append("# critical paths, so their entries are ABSENT rather than guessed:")
        lines.extend(f"#   - {owner}" for owner in profile.unconfirmed_owners)
        lines.append("# A monitor over the paths we know beats no monitor; add lines as")
        lines.append("# owners confirm them.")
    lines.extend(profile.manifest)
    return "\n".join(lines)


def render_check_script(profile: TreeMonitorProfile = EXAMPLE_PROFILE) -> str:
    """Return the monitor shell text generated from ``profile``."""
    manifest_block = render_manifest_block(profile)
    return f"""#!/usr/bin/env bash
# ============================================================================
# Catch-it-live monitor for shared tree deletions  (scitex-hpc: {profile.name})
# [GENERATED — edit the profile + renderer, not this artifact]
# ----------------------------------------------------------------------------
# WHY THIS EXISTS: critical shared paths have vanished before, and every
# post-hoc attempt to identify the deleter failed — crontab disabled, systemd
# --user swept twice, own SLURM history clean, four concrete leads closed with
# hard evidence. Forensics after the fact are exhausted. This catches the NEXT
# one while it is happening.
#
# THREE-VALUED BY CONSTRUCTION. A path is PRESENT, MISSING, or UNKNOWN, and it
# only alarms on a present->missing TRANSITION, never on "I could not tell":
#   - first run has no baseline            -> record, never alarm
#   - stat fails (GPFS hiccup, EIO)        -> UNKNOWN, never alarm, and the
#                                             baseline is NOT overwritten, so a
#                                             real deletion during an unreadable
#                                             window is still caught next run
# ============================================================================
set -uo pipefail

STATE_DIR="${{SCITEX_TREE_MONITOR_STATE:-{profile.state_dir}}}"
STATE="$STATE_DIR/{profile.name}-manifest.state"
LOG="$STATE_DIR/{profile.name}.log"
mkdir -p "$STATE_DIR"

{manifest_block.splitlines()[0]}
MANIFEST="${{SCITEX_TREE_MANIFEST:-}}"
if [ -z "$MANIFEST" ]; then
    MANIFEST=$(cat <<'PATHS'
{manifest_block}
PATHS
)
fi

now() {{ date -u +%FT%TZ; }}
log() {{ printf '%s %s\\n' "$(now)" "$*" >> "$LOG"; }}

# --- read the manifest into a present/missing/unknown map -------------------
declare -A CUR
while IFS= read -r raw; do
    line="${{raw%%#*}}"; line="$(printf '%s' "$line" | xargs 2>/dev/null || true)"
    [ -z "$line" ] && continue
    p="$(eval printf '%s' "\\"$line\\"")"          # expand $HOME only
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
    while IFS=$'\\t' read -r st p; do [ -n "${{p:-}}" ] && PREV["$p"]="$st"; done < "$STATE"
fi

# --- detect PRESENT -> MISSING transitions ----------------------------------
VANISHED=()
for p in "${{!CUR[@]}}"; do
    if [ "${{CUR[$p]}}" = "MISSING" ] && [ "${{PREV[$p]:-}}" = "PRESENT" ]; then
        VANISHED+=("$p")
    fi
done

# --- persist, but NEVER overwrite a PRESENT baseline with UNKNOWN -----------
: > "$STATE.new"
for p in "${{!CUR[@]}}"; do
    st="${{CUR[$p]}}"
    [ "$st" = "UNKNOWN" ] && st="${{PREV[$p]:-UNKNOWN}}"
    printf '%s\\t%s\\n' "$st" "$p" >> "$STATE.new"
done
mv "$STATE.new" "$STATE"

if [ ${{#VANISHED[@]}} -eq 0 ]; then
    log "ok $(printf '%s' "${{#CUR[@]}}") path(s) checked, no present->missing transition"
    exit 0
fi

# --- a path vanished: capture forensics WHILE IT IS HAPPENING ---------------
FORENSICS="$STATE_DIR/vanish-$(date -u +%Y%m%dT%H%M%SZ).txt"
{{
    echo "VANISHED AT $(now)"
    for p in "${{VANISHED[@]}}"; do echo "  MISSING: $p"; done
    echo
    echo "== parent listings =="
    for p in "${{VANISHED[@]}}"; do echo "--- $(dirname "$p")"; ls -la "$(dirname "$p")" 2>&1 | head -30; done
    echo
    echo "== my SLURM jobs at this moment =="
    (squeue -u "$USER" -o '%i %T %N %j' 2>&1 || echo "squeue unavailable") | head -20
    echo
    echo "== who is on this node =="
    (who 2>&1 || true) | head -10
    echo "hostname: $(hostname -s)  uid: $(id -un)"
}} > "$FORENSICS" 2>&1

log "ALARM ${{#VANISHED[@]}} path(s) vanished; forensics -> $FORENSICS"

# --- alarm LOUDLY through the shared board, not just a local file -----------
# A local log is exactly what a deleter could also remove. The card is the rail
# that survives the host.
#
# SCITEX_TREE_MONITOR_DRYRUN=1 suppresses the card write. This exists because
# testing this script WITHOUT it puts a real P1 alarm card on the shared fleet
# board — measured 2026-08-05: exercising the deletion branch created a live
# alarm card against a temp path, which then had to be hunted down and deleted.
# An alarm path that cannot be rehearsed safely will either go untested or
# teach everyone to ignore its cards.
if [ "${{SCITEX_TREE_MONITOR_DRYRUN:-0}}" = "1" ]; then
    log "DRYRUN alarm suppressed; would have carded ${{#VANISHED[@]}} vanished path(s)"
    echo "DRYRUN: would alarm for: ${{VANISHED[*]}}"
elif command -v scitex-todo >/dev/null 2>&1; then
    SCITEX_TODO_AGENT_ID={profile.agent_id} scitex-todo add \\
        "spartan-shared-tree-vanish-$(date -u +%Y%m%dT%H%M%SZ)" \\
        "[P1][ALARM] shared tree path(s) vanished on $(hostname -s) — caught live" \\
        --status blocked --blocker operator-decision \\
        --assignee {profile.agent_id} --project scitex-hpc --priority 1 \\
        --task "$(printf 'Caught by the catch-it-live monitor at %s.\\n\\nVANISHED:\\n%s\\n\\nForensics captured on the host at:\\n  %s\\n\\nThis is the in-the-moment evidence the previous incidents lacked — every post-hoc investigation failed to identify the deleter.\\n' \\
                 "$(now)" "$(printf '  %s\\n' "${{VANISHED[@]}}")" "$FORENSICS")" \\
        >/dev/null 2>&1 && log "alarm card created" || log "WARN alarm card FAILED — local forensics only"
else
    log "WARN scitex-todo unavailable on this host — local forensics only at $FORENSICS"
fi
exit 1
"""


def render_service_unit(profile: TreeMonitorProfile = EXAMPLE_PROFILE) -> str:
    """Return the systemd ``.service`` text for ``profile``."""
    return f"""[Unit]
Description={profile.description}
Documentation=card:{profile.documentation_card}
# [GENERATED — edit the profile + renderer, not this artifact]

[Service]
Type=oneshot
ExecStart={profile.script_path.replace("$HOME", "%h")}
# exit 1 means "a path vanished" — that is the monitor WORKING, not failing.
# Without this, systemd marks the unit failed on a true positive and the timer
# keeps running but every alarm also looks like a broken unit.
SuccessExitStatus=0 1
# Never let the monitor itself become the load problem on a shared host.
Nice=19
IOSchedulingClass=idle
"""


def render_timer_unit(profile: TreeMonitorProfile = EXAMPLE_PROFILE) -> str:
    """Return the systemd ``.timer`` text for ``profile``."""
    return f"""[Unit]
Description=Run the shared-tree catch-it-live monitor every {profile.interval}
Documentation=card:{profile.documentation_card}
# [GENERATED — edit the profile + renderer, not this artifact]

[Timer]
# {profile.interval}: short enough that the forensics (parent listing, squeue
# snapshot, active sessions) are still contemporaneous with the deletion, long
# enough that a stat of a handful of paths is negligible on a shared login node.
OnBootSec={profile.boot_delay}
OnUnitActiveSec={profile.interval}
# Persistent so a missed window after a reboot runs once on the next start
# rather than silently skipping — a monitor that stops at reboot is exactly
# the gap the incidents fell through.
Persistent=true
AccuracySec={profile.accuracy}

[Install]
WantedBy=timers.target
"""
