#!/usr/bin/env python3
"""Read what SLURM actually GRANTED, from `scontrol show job` output."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

__all__ = ["Granted", "parse_scontrol", "read_granted"]

#: `scontrol show job` emits space-separated key=value pairs across lines.
#: Values never contain a space in the fields read here.
_KV = re.compile(r"(?P<key>[A-Za-z/]+)=(?P<value>\S+)")

_MEM = re.compile(r"^(?P<value>[\d.]+)(?P<unit>[KMGT]?)$", re.IGNORECASE)

#: e.g. gres:gpu:h100:2  /  gres:gpu:2  /  gpu:h100:1
_GRES = re.compile(
    r"gpu:(?:(?P<gputype>[a-z0-9]+):)?(?P<count>\d+)", re.IGNORECASE
)


@dataclass(frozen=True)
class Granted:
    """What the scheduler actually handed over."""

    job_id: str | None = None
    job_name: str | None = None
    state: str | None = None
    cores: int | None = None
    ram_gb: int | None = None
    gpu_type: str | None = None
    gpu_count: int = 0


def _mem_to_gb(raw: str) -> int | None:
    m = _MEM.match(raw)
    if not m:
        return None
    value = float(m["value"])
    unit = (m["unit"] or "M").upper()
    factor = {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1.0, "T": 1024.0}[unit]
    return int(round(value * factor))


def parse_scontrol(text: str) -> Granted:
    """Parse `scontrol show job <id>` output. Pure: no SLURM required.

    Unreadable fields stay None rather than defaulting to a number. A zero
    that means "not stated" is indistinguishable from a zero that means "none
    granted", and only one of those is a fault.
    """
    fields = {m["key"]: m["value"] for m in _KV.finditer(text or "")}

    cores = fields.get("NumCPUs")
    mem = fields.get("mem") or fields.get("MinMemoryNode") or fields.get("Mem")

    gpu_type = None
    gpu_count = 0
    for key in ("TresPerNode", "TresPerJob", "TRES", "ReqTRES", "Gres"):
        raw = fields.get(key)
        if not raw:
            continue
        g = _GRES.search(raw)
        if g:
            gpu_count = int(g["count"])
            gpu_type = (g["gputype"] or "").lower() or None
            break

    return Granted(
        job_id=fields.get("JobId"),
        job_name=fields.get("JobName"),
        state=fields.get("JobState"),
        cores=int(cores) if cores and cores.isdigit() else None,
        ram_gb=_mem_to_gb(mem) if mem else None,
        gpu_type=gpu_type,
        gpu_count=gpu_count,
    )


def read_granted(job_id: str, *, runner=subprocess.run) -> Granted:
    """Ask SLURM about ``job_id``. Read-only; never submits or cancels."""
    proc = runner(
        ["scontrol", "show", "job", str(job_id)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return parse_scontrol(proc.stdout or "")

# EOF
