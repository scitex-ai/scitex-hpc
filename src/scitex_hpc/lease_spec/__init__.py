#!/usr/bin/env python3
"""The lease NAME is the spec — so check it against what SLURM granted.

A lease is booked under a name that states its own shape:

    spartan-cpu-64-cores-256-ram
    spartan-gpu-16-cores-128-ram-80-vram-h100

That name is an on-disk key: it appears in lease files, in unit files, in
`squeue`, and in every card that refers to the allocation. So the name and the
grant can disagree — a lease booked as 64 cores and granted 32 keeps the old
name, and everything downstream reads the NAME and believes it.

This package parses the name, reads what was actually granted, and states any
mismatch. It NEVER renames. Auto-renaming would convert a loud failure into a
silent one: the name would quietly become true and the fact that a request was
not satisfied would vanish. (Operator, 2026-07-12.)

Verifying is READ-ONLY by construction — nothing here writes, submits or
cancels anything.
"""

from ._granted import Granted, parse_scontrol, read_granted
from ._parse import LeaseSpec, parse_lease_name
from ._verify import Mismatch, Verdict, verify

__all__ = [
    "Granted",
    "LeaseSpec",
    "Mismatch",
    "Verdict",
    "parse_lease_name",
    "parse_scontrol",
    "read_granted",
    "verify",
]

# EOF
