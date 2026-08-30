#!/usr/bin/env python3
"""Enumerate a venv's editable installs and grade each one."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..ci_runners._deploy import inspect_checkout

__all__ = ["InstallRow", "editable_installs", "audit_venv", "summarize"]

#: A source directory recorded by the install but absent on disk. NOT the same
#: as stale: the package may not import at all. Measured 2026-08-30, 9 of 62
#: distributions recorded ``/home/ywatanabe/proj/<pkg>`` after the code moved
#: to GPFS, and 5 of those 9 raised on import.
STATE_SOURCE_MISSING = "source-missing"


@dataclass(frozen=True)
class InstallRow:
    """One editable distribution, and what it is relative to its upstream."""

    name: str
    source: str
    state: str
    detail: str
    ahead: int = 0
    behind: int = 0
    branch: str | None = None

    @property
    def is_drift(self) -> bool:
        """Stale or divergent — the running code is not the merged code."""
        return self.state in ("behind", "diverged")

    @property
    def is_broken(self) -> bool:
        """The recorded source is gone; this is worse than drift, not a kind of it."""
        return self.state == STATE_SOURCE_MISSING


def _site_packages(venv: Path) -> list[Path]:
    return sorted(venv.glob("lib/python3*/site-packages"))


def editable_installs(venv: str | Path | None = None) -> dict[str, str]:
    """Map distribution name -> recorded source directory, for editable installs.

    Read from each ``*.dist-info/direct_url.json``, which is what pip itself
    records. Defaults to the venv of the RUNNING interpreter, so the audit
    describes the environment actually in use rather than one passed by hand.
    """
    root = Path(venv) if venv is not None else Path(sys.prefix)
    found: dict[str, str] = {}
    for site in _site_packages(root):
        for meta in sorted(site.glob("*.dist-info/direct_url.json")):
            try:
                payload = json.loads(meta.read_text())
            except (OSError, ValueError):
                continue
            if not payload.get("dir_info", {}).get("editable"):
                continue
            url = payload.get("url", "")
            if not url.startswith("file://"):
                continue
            found[meta.parent.name.split("-")[0]] = url[len("file://") :]
    return found


def audit_venv(
    venv: str | Path | None = None, *, fetch: bool = True
) -> list[InstallRow]:
    """Grade every editable install in ``venv``. Sorted by name."""
    rows = []
    for name, source in sorted(editable_installs(venv).items()):
        if not Path(source).is_dir():
            rows.append(
                InstallRow(
                    name=name,
                    source=source,
                    state=STATE_SOURCE_MISSING,
                    detail=(
                        f"{source} does not exist — the install points at a "
                        "directory that is gone, so this is a BROKEN install "
                        "rather than a stale one; it may not import at all"
                    ),
                )
            )
            continue
        st = inspect_checkout(source, fetch=fetch)
        rows.append(
            InstallRow(
                name=name,
                source=source,
                state=st.state,
                detail=st.detail,
                ahead=st.ahead,
                behind=st.behind,
                branch=st.branch,
            )
        )
    return rows


def summarize(rows: list[InstallRow]) -> dict[str, int]:
    """Counts by state, plus the two totals a caller acts on."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1
    counts["_total"] = len(rows)
    counts["_drift"] = sum(1 for r in rows if r.is_drift)
    counts["_broken"] = sum(1 for r in rows if r.is_broken)
    return counts

# EOF
