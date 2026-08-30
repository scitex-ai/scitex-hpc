#!/usr/bin/env python3
"""``scitex-hpc lease verify`` — does the name match what SLURM granted?"""

from __future__ import annotations

import json as _json
import sys

import click

from ..lease_spec import parse_lease_name, read_granted, verify

#: Two-digit, for the same reason the fleet monitor's codes are: 1-9 are what
#: the interpreter and shell return when the command could not run at all.
EXIT_MISMATCH = 30


@click.command("verify")
@click.argument("label")
@click.option(
    "--job-id",
    "job_id",
    default=None,
    help="SLURM job id to compare against. Defaults to LABEL when LABEL is "
    "numeric, so `lease verify 29677925` works.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the verdict as JSON.")
def lease_verify_cmd(label, job_id, as_json):
    """Check a lease NAME against the allocation SLURM actually granted.

    \b
    The name is the spec. It is also an on-disk key -- it appears in lease
    files, unit files, `squeue`, and every card that refers to the allocation.
    So a lease booked as 64 cores and granted 32 keeps the old name, and every
    downstream reader believes the name.

    \b
      0   match, or nothing to check
      30  MISMATCH: the grant differs from what the name claims

    \b
    This NEVER renames anything. Auto-renaming would turn a loud failure into
    a silent one: the name would quietly become true and the fact that a
    request went unmet would disappear (operator, 2026-07-12). Read-only --
    it does not submit, cancel or modify any job.

    \b
    A name outside the `lease book` grammar reports `unknown`, not a fault: a
    name that promised nothing cannot have broken a promise.

    \b
    Example:
      $ scitex-hpc lease verify spartan-cpu-32-cores-64-ram --job-id 29677925
      $ scitex-hpc lease verify 29677925 --json
    """
    resolved = job_id or (label if label.isdigit() else None)
    if resolved is None:
        raise click.UsageError(
            "no job id: pass --job-id, or give a numeric LABEL. Comparing a "
            "name against nothing would report a pass that measured nothing."
        )

    granted = read_granted(resolved)
    # When LABEL is the job id, the NAME to check is the one SLURM recorded.
    name = granted.job_name if label.isdigit() else label
    verdict = verify(parse_lease_name(name), granted)

    if as_json:
        click.echo(
            _json.dumps(
                {
                    "name": name,
                    "job_id": resolved,
                    "state": verdict.state,
                    "detail": verdict.detail,
                    "mismatches": [
                        {
                            "field": m.field_name,
                            "claimed": m.claimed,
                            "granted": m.granted,
                        }
                        for m in verdict.mismatches
                    ],
                },
                indent=2,
            )
        )
    else:
        click.echo(f"{verdict.state.upper()}: {verdict.detail}")

    sys.exit(EXIT_MISMATCH if verdict.is_mismatch else 0)

# EOF
