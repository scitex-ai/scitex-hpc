#!/usr/bin/env python3
"""Compare what the name CLAIMS against what SLURM GRANTED."""

from __future__ import annotations

from dataclasses import dataclass, field

from ._granted import Granted
from ._parse import LeaseSpec

__all__ = ["Mismatch", "Verdict", "verify"]


@dataclass(frozen=True)
class Mismatch:
    """One field where the name and the grant disagree."""

    field_name: str
    claimed: object
    granted: object

    def __str__(self) -> str:
        return (
            f"{self.field_name}: name claims {self.claimed}, "
            f"SLURM granted {self.granted}"
        )


@dataclass(frozen=True)
class Verdict:
    """The result of checking one lease name against one allocation."""

    state: str
    detail: str
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def is_mismatch(self) -> bool:
        return self.state == "mismatch"


def verify(spec: LeaseSpec | None, granted: Granted) -> Verdict:
    """State whether the grant matches the name.

    THREE outcomes, and the third is why this is not a boolean:

    * ``match``     — every field the name states was granted as stated
    * ``mismatch``  — at least one field disagrees; ACT on this
    * ``unknown``   — the name states no spec, or SLURM stated no value to
                      compare. NOT a fault: a name that promised nothing
                      cannot have broken a promise, and a field the scheduler
                      did not report is one this check could not see.
    """
    if spec is None:
        return Verdict(
            "unknown",
            "the name states no spec (not the `lease book` grammar), so there "
            "is nothing to check it against — this is not a fault",
        )

    mismatches: list[Mismatch] = []
    unread: list[str] = []

    if granted.cores is None:
        unread.append("cores")
    elif granted.cores != spec.cores:
        mismatches.append(Mismatch("cores", spec.cores, granted.cores))

    if granted.ram_gb is None:
        unread.append("ram_gb")
    elif granted.ram_gb != spec.ram_gb:
        mismatches.append(Mismatch("ram_gb", spec.ram_gb, granted.ram_gb))

    if spec.kind == "gpu":
        if granted.gpu_count != spec.gpu_count:
            mismatches.append(
                Mismatch("gpu_count", spec.gpu_count, granted.gpu_count)
            )
        # A grant that does not name the model cannot contradict one that does.
        if granted.gpu_type is None:
            unread.append("gpu_type")
        elif granted.gpu_type != spec.gpu_type:
            mismatches.append(
                Mismatch("gpu_type", spec.gpu_type, granted.gpu_type)
            )

    if mismatches:
        return Verdict(
            "mismatch",
            f"{spec.name} was granted something else: "
            + "; ".join(str(m) for m in mismatches)
            + ". The NAME is what every downstream reader believes, so fix the "
            "booking or rebook — do NOT rename, which would make the name true "
            "and the unmet request invisible.",
            mismatches,
        )

    if unread:
        return Verdict(
            "unknown",
            f"{spec.name} matches on every field that could be read, but "
            f"SLURM stated no value for: {', '.join(unread)}. Reporting what "
            "was NOT checked rather than calling it a pass.",
        )

    return Verdict("match", f"{spec.name} matches what SLURM granted")

# EOF
