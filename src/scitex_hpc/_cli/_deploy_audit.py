#!/usr/bin/env python3
"""``scitex-hpc audit-deploys`` — is every editable install the merged code?

Named with a READ verb on purpose. It was briefly ``deploy-audit``, which the
CLI-conventions audit correctly flagged as a mutating verb missing ``--yes``
and ``--dry-run``: a command whose name starts with ``deploy`` promises to
deploy something. This one only ever reads -- it fetches and compares, and
never writes to a checkout -- so the name had to stop claiming otherwise
rather than acquire flags that would lie about what it does.
"""

from __future__ import annotations

import json as _json
import sys

import click

from ..ci_runners._monitor import _ALARM_FUNC
from ..deploy_audit import audit_venv, summarize

#: Two-digit for the same reason the fleet monitor's are: 1-9 are what the
#: interpreter and shell return when the command could not run at all, so a
#: two-digit code always means "the audit RAN and reached a verdict".
EXIT_DRIFT = 20
EXIT_BROKEN = 21


def _fire_alarm(subject: str, body: str) -> None:
    """Fire through the monitor's OWN alarm contract, never a second one."""
    import subprocess as _sp

    _sp.run(
        ["bash", "-c", _ALARM_FUNC + '\nalarm "$1" "$2"', "alarm", subject, body],
        check=False,
    )


@click.command("audit-deploys")
@click.option(
    "--venv",
    default=None,
    help="Venv to audit (default: the venv of the running interpreter, so the "
    "audit describes the environment actually in use).",
)
@click.option(
    "--no-fetch",
    "no_fetch",
    is_flag=True,
    help="Do not fetch first. Faster, and WRONG for drift: without a fetch a "
    "stale checkout cannot see that it is behind and reports 'current'.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the rows as JSON.")
@click.option(
    "--quiet",
    is_flag=True,
    help="Print only the summary line and anything needing action.",
)
def audit_deploys_cmd(venv, no_fetch, as_json, quiet):
    """Audit every EDITABLE install in a venv for deploy drift.

    \b
      0   nothing to act on
      20  DRIFT: at least one install is behind or diverged from its upstream
      21  BROKEN: at least one install's source directory is GONE

    \b
    21 outranks 20 deliberately. A stale install runs old code; an install
    whose source has vanished may not import at all, so it is a different and
    worse fault, not a more severe grade of the same one.

    \b
    `unknown` and `not-a-checkout` are NEVER faults. An unreachable origin is
    a network blip and a real wheel has nothing to compare -- an alarm rail
    that cannot tell "did not see" from "saw a fault" spends its credibility
    on neither.

    \b
    Measured on spartan-login1 2026-08-30 across 62 editable distributions:
    38 behind (two by 470 commits), 2 diverged holding 58 commits that exist
    on no remote, 9 with a vanished source of which 5 could not be imported.

    \b
    READ-ONLY. It fetches and compares; it never writes to a checkout, which
    is why it carries no --yes or --dry-run. Deploying is a separate,
    deliberate act.

    \b
    Example:
      $ scitex-hpc audit-deploys --quiet
      $ scitex-hpc audit-deploys --venv ~/.venv --json
    """
    rows = audit_venv(venv, fetch=not no_fetch)
    counts = summarize(rows)

    if as_json:
        click.echo(
            _json.dumps(
                {"summary": counts, "installs": [r.__dict__ for r in rows]},
                indent=2,
            )
        )
    else:
        for row in rows:
            if quiet and not (row.is_drift or row.is_broken):
                continue
            click.echo(
                f"{row.name:28} {row.state:16} "
                f"ahead={row.ahead:<4} behind={row.behind:<4}"
            )
        click.echo(
            f"summary: {counts['_total']} editable install(s), "
            f"{counts['_drift']} drifted, {counts['_broken']} broken"
        )

    if counts["_broken"]:
        broken = [r for r in rows if r.is_broken]
        _fire_alarm(
            f"scitex-hpc: {len(broken)} BROKEN editable install(s)",
            "The recorded source directory is GONE for:\n"
            + "\n".join(f"  {r.name}: {r.source}" for r in broken)
            + "\n\nThese may not import at all. This is a broken install, not "
            "a stale one.",
        )
        sys.exit(EXIT_BROKEN)

    if counts["_drift"]:
        drifted = [r for r in rows if r.is_drift]
        _fire_alarm(
            f"scitex-hpc: {len(drifted)} editable install(s) not the merged code",
            "\n".join(f"  {r.name}: {r.detail}" for r in drifted)
            + "\n\nAn editable install makes a working tree the artifact, so "
            "'merged' reads as 'deployed' while the deployed bytes never move.",
        )
        sys.exit(EXIT_DRIFT)

    sys.exit(0)

# EOF
