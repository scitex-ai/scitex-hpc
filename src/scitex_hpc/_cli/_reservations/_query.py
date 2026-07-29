"""Read-only lease verbs: ``list`` and ``get``."""

from __future__ import annotations

import json as _json
import sys

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand

from ..._reservation import Reservation
from ._group import _serialize, lease


@lease.command(
    "list",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="List active reservations.",
        examples=(
            Example("{prog} lease list", "Table of active leases."),
            Example("{prog} lease list --json", "Structured JSON output."),
        ),
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def list_cmd(as_json):
    rows = Reservation.list()
    if as_json:
        click.echo(_json.dumps([_serialize(r) for r in rows], indent=2))
        return
    if not rows:
        click.echo("(no reservations)")
        return
    fmt = "{:32}  {:10}  {:14}  {:30}"
    click.echo(fmt.format("ID", "JOB", "PERSIST", "NODE"))
    for r in rows:
        click.echo(
            fmt.format(r.id, r.job_id, "yes" if r.persistent else "no", r.node or "-")
        )


@lease.command(
    "get",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Show one reservation as JSON.",
        description="Exits 2 if no lease of that NAME exists.",
        examples=(
            Example("{prog} lease get dev-pool", "Show one lease."),
            Example("{prog} lease get dev-pool --json", "Same, explicit JSON."),
        ),
    ),
)
@click.argument("name")
@click.option("--host", default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def get_cmd(ctx, name, host, as_json):
    res = Reservation.get(name, host=host)
    if res is None:
        click.echo(f"(no reservation named {name!r})", err=True)
        ctx.exit(2)
    click.echo(_json.dumps(_serialize(res), indent=2))
