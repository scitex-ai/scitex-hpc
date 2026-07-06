"""Filesystem inode-quota early warning.

Guardrail for the recurring GPFS inode-quota wall (2026-07-03 incident:
punim0264 silently hit its 7M fileset inode quota -> mass SAC state-db
"unable to open database file"). Reports fileset inode usage and alarms
BEFORE the wall (default 90%) so it is never silently exhausted.

SoC: this owns FILESYSTEM inode quota; scitex-agent-container's
``quota_watch`` owns Anthropic API quota (different domains, kept separate).

Cluster-agnostic: uses plain ``df -i <path>`` — which reports the fileset
inode quota + usage on GPFS/Lustre/ext — rather than ``lfs`` / ``mmlsquota``
(not on every node's PATH). Dogfoods scitex-ssh's ``exec_remote``.
"""

from __future__ import annotations

import os
import subprocess
import sys

from scitex_ssh import exec_remote

# Default fileset(s) to watch on Spartan: the punim0264 project tree whose
# 7M path-based inode quota is the one that walls.
DEFAULT_PATHS = ("/data/gpfs/projects/punim0264",)
DEFAULT_THRESHOLD_PCT = 90


def parse_df_inodes(stdout: str) -> dict | None:
    """Parse ``df -i <path>`` output into inode usage.

    Returns ``{filesystem, total, used, free, pct}`` from the last data row
    (``FS Inodes IUsed IFree IUse% Mounted``), or ``None`` if unparseable.
    Scans from the bottom so a wrapped long-filesystem-name header is skipped.
    """
    for line in reversed([ln for ln in (stdout or "").splitlines() if ln.strip()]):
        parts = line.split()
        if len(parts) < 5 or not parts[-2].rstrip("%").isdigit():
            continue
        try:
            return {
                "filesystem": parts[-6] if len(parts) >= 6 else parts[0],
                "total": int(parts[-5]),
                "used": int(parts[-4]),
                "free": int(parts[-3]),
                "pct": int(parts[-2].rstrip("%")),
            }
        except (ValueError, IndexError):
            continue
    return None


def check_inode_quota(
    host: str,
    paths: tuple[str, ...] = DEFAULT_PATHS,
    *,
    threshold_pct: int = DEFAULT_THRESHOLD_PCT,
) -> dict:
    """``df -i`` each path on ``host``; return a report with any over threshold.

    Result: ``{threshold_pct, paths: [<row>...], over: [<row over threshold>]}``.
    Each row carries the parsed inode usage plus ``path`` and
    ``over_threshold``; an unparseable df output yields a row with ``error``.
    """
    rows: list[dict] = []
    over: list[dict] = []
    for path in paths:
        result = exec_remote(host, f"df -i {path}")
        parsed = parse_df_inodes(result.stdout or "")
        if parsed is None:
            rows.append({"path": path, "error": "unparseable df -i output"})
            continue
        parsed["path"] = path
        parsed["over_threshold"] = parsed["pct"] >= threshold_pct
        rows.append(parsed)
        if parsed["over_threshold"]:
            over.append(parsed)
    return {"threshold_pct": threshold_pct, "paths": rows, "over": over}


def alarm(subject: str, body: str) -> None:
    """Emit an alarm via ``$SCITEX_CI_ALARM_CMD`` (stdin ``<subject>\\n<body>``).

    Always writes the alarm to stderr (so cron mails it); additionally pipes
    it to the operator-configured ``$SCITEX_CI_ALARM_CMD`` when set. Mirrors
    the monitor's alarm contract so both watchdogs alarm the same way.
    """
    sys.stderr.write(f"ALARM: {subject} -- {body}\n")
    cmd = os.environ.get("SCITEX_CI_ALARM_CMD")
    if not cmd:
        return
    try:
        subprocess.run(
            ["bash", "-c", cmd],
            input=f"{subject}\n{body}\n",
            text=True,
            timeout=30,
        )
    except Exception:  # pragma: no cover — alarm must never crash the check
        pass
