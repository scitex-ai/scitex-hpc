#!/usr/bin/env python3
"""Parse a lease name into the spec it claims to be."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["LeaseSpec", "parse_lease_name"]

#: The grammar shipped by ``lease book``. Kept as ONE regex per kind rather
#: than a token walk, so the accepted shape is readable in full and a name
#: that ALMOST matches is rejected rather than half-parsed.
_CPU = re.compile(
    r"^(?P<cluster>[a-z0-9]+)-cpu-"
    r"(?P<cores>\d+)-cores-"
    r"(?P<ram>\d+)-ram"
    r"(?:-(?P<purpose>[a-z0-9-]+))?$"
)

_GPU = re.compile(
    r"^(?P<cluster>[a-z0-9]+)-gpu-"
    r"(?P<cores>\d+)-cores-"
    r"(?P<ram>\d+)-ram-"
    r"(?P<vram>\d+)-vram-"
    r"(?:(?P<count>\d+)x)?(?P<gputype>[a-z0-9]+)"
    r"(?:-(?P<purpose>[a-z0-9-]+))?$"
)


@dataclass(frozen=True)
class LeaseSpec:
    """What a lease name CLAIMS. Not what was granted."""

    name: str
    cluster: str
    kind: str
    cores: int
    ram_gb: int
    vram_gb: int | None = None
    gpu_type: str | None = None
    gpu_count: int = 0
    purpose: str | None = None


def parse_lease_name(name: str) -> LeaseSpec | None:
    """Parse a lease name, or return None if it does not state a spec.

    None means "this name makes no claim", which is NOT a mismatch. A name
    that never promised anything cannot have broken its promise, and treating
    the two alike would flag every hand-named job as a fault.
    """
    text = (name or "").strip()
    if not text:
        return None

    m = _CPU.match(text)
    if m:
        return LeaseSpec(
            name=text,
            cluster=m["cluster"],
            kind="cpu",
            cores=int(m["cores"]),
            ram_gb=int(m["ram"]),
            purpose=m["purpose"],
        )

    m = _GPU.match(text)
    if m:
        return LeaseSpec(
            name=text,
            cluster=m["cluster"],
            kind="gpu",
            cores=int(m["cores"]),
            ram_gb=int(m["ram"]),
            vram_gb=int(m["vram"]),
            gpu_type=m["gputype"],
            # A bare `-h100` means one; `-4xh100` means four.
            gpu_count=int(m["count"]) if m["count"] else 1,
            purpose=m["purpose"],
        )

    return None

# EOF
