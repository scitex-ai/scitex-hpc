"""Verbs that operate on an existing lease: ``exec``, ``refresh``, ``attach``, ``cancel`` (and the hidden legacy ``release`` alias)."""

from __future__ import annotations

import json as _json
import sys

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand

from ..._reservation import Reservation

from ._group import _serialize, lease


@lease.command(
    "exec",
    cls=SpecCommand,
    context_settings={
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
    },
    help_spec=CliHelp(
        summary="Run a command inside the reservation's allocation.",
        description="Exits with the remote command's own exit code.",
        examples=(
            Example("{prog} lease exec dev-pool 'hostname'", "Which node am I on."),
            Example(
                "{prog} lease exec dev-pool 'python -m pytest'",
                "Run a test suite inside the allocation.",
            ),
        ),
    ),
)
@click.argument("name")
@click.argument("command")
@click.option("--host", default=None)
@click.option("--dry-run", is_flag=True, help="Print plan without ssh-execing.")
@click.option("-y", "--yes", "yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def exec_cmd(ctx, name, command, host, dry_run, yes):
    del yes
    res = Reservation.require(name, host=host)
    if dry_run:
        click.echo(f"DRY RUN — would exec on {res.id}: {command}")
        return
    out = res.exec(command)
    sys.stdout.write(out.stdout or "")
    sys.stderr.write(out.stderr or "")
    ctx.exit(out.returncode)


@lease.command(
    "refresh",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Re-discover the current job_id via squeue.",
        description=(
            "Use after a walltime auto-resubmit has replaced the job: the "
            "lease name is stable, the job id is not. Exits 2 when no live "
            "job is found."
        ),
        examples=(
            Example("{prog} lease refresh dev-pool", "Re-resolve the job id."),
            Example("{prog} lease refresh dev-pool --json", "Structured output."),
        ),
    ),
)
@click.argument("name")
@click.option("--host", default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def refresh_cmd(ctx, name, host, as_json):
    res = Reservation.require(name, host=host)
    res.refresh()
    if as_json:
        click.echo(_json.dumps(_serialize(res), indent=2))
        return
    if res.job_id:
        click.echo(f"refreshed: id={res.id} job={res.job_id} node={res.node}")
    else:
        click.echo(
            f"refreshed: id={res.id} (no live job found via squeue --name={res.name})",
            err=True,
        )
        ctx.exit(2)


@lease.command(
    "attach",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Open an interactive shell on the reservation's compute node.",
        examples=(
            Example("{prog} lease attach dev-pool", "Attach with bash."),
            Example("{prog} lease attach dev-pool --shell zsh", "Attach with zsh."),
        ),
    ),
)
@click.argument("name")
@click.option("--host", default=None)
@click.option("--shell", default="bash")
@click.pass_context
def attach_cmd(ctx, name, host, shell):
    res = Reservation.require(name, host=host)
    rc = res.attach(cmd=shell, pty=True)
    ctx.exit(rc)


def _do_cancel(name, host, missing_ok, ctx):
    res = Reservation.get(name, host=host)
    if res is None:
        click.echo(f"(no reservation named {name!r})", err=True)
        ctx.exit(0 if missing_ok else 2)
    ok = res.release(missing_ok=True)
    click.echo(f"released: {res.id} ({'ok' if ok else 'scancel-failed'})")
    ctx.exit(0 if ok else 1)


@lease.command(
    "cancel",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="scancel + clear lease state for a reservation.",
        description=(
            "Canonical teardown verb. The legacy `release` spelling remains "
            "as a hidden alias for one minor-version cycle."
        ),
        examples=(
            Example("{prog} lease cancel dev-pool", "Tear down; exit 0 if already gone."),
            Example(
                "{prog} lease cancel dev-pool --no-missing-ok",
                "Fail with exit 2 if the lease does not exist.",
            ),
        ),
    ),
)
@click.argument("name")
@click.option("--host", default=None)
@click.option(
    "--missing-ok/--no-missing-ok",
    default=True,
    help="Exit 0 if the lease is already gone (default).",
)
@click.option("--dry-run", is_flag=True, help="Print plan without scancel'ing.")
@click.option("-y", "--yes", "yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def cancel_cmd(ctx, name, host, missing_ok, dry_run, yes):
    del yes
    if dry_run:
        click.echo(f"DRY RUN — would cancel reservation {name!r}")
        return
    _do_cancel(name, host, missing_ok, ctx)


@lease.command("release", hidden=True)
@click.argument("name")
@click.option("--host", default=None)
@click.option("--missing-ok/--no-missing-ok", default=True)
@click.pass_context
def release_cmd(ctx, name, host, missing_ok):
    """(deprecated alias) Use ``lease cancel`` instead."""
    _do_cancel(name, host, missing_ok, ctx)
