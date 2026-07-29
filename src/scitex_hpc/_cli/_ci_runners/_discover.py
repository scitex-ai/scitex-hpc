"""``ci-runners discover`` — read-only listing of the fleet's install dirs."""

from __future__ import annotations

import json as _json

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand

from . import _group
from ._group import _DEFAULT_CI_BASE, ci_runners


@ci_runners.command(
    "discover",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="List the runner install dirs found under the CI base.",
        description=(
            "Light `ls` only — admin-flagged: no recursive scans on the "
            "login node."
        ),
        examples=(
            Example(
                "{prog} ci-runners discover --host spartan",
                "List the fleet's runner install dirs.",
            ),
            Example(
                "{prog} ci-runners discover --json",
                "Structured output for scripts.",
            ),
        ),
    ),
)
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def discover_cmd(host, ci_base, exclude, as_json):
    # Resolved through the module object, not bound at import: the CLI tests
    # swap `_group._discover` to avoid SSH, and a from-import would capture
    # the real one here and silently defeat that patch.
    fleet = _group._discover(host, ci_base, tuple(exclude))
    active = fleet.active()
    if as_json:
        click.echo(
            _json.dumps([{"name": r.name, "dir": r.dir} for r in active], indent=2)
        )
        return
    click.echo(f"{len(active)} runners under {ci_base}:")
    for r in active:
        click.echo(f"  {r.name:32}  {r.dir}")
