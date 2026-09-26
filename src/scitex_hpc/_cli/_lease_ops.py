"""``scitex-hpc lease`` read + lifecycle verbs — list / get / exec / sync-state /
attach / close.

Everything here operates on a lease that ALREADY exists; the two verbs that
create one live in :mod:`scitex_hpc._cli._lease_book`. Commands are declared
as standalone :func:`click.command` objects and attached to the ``lease``
group by :mod:`scitex_hpc._cli._reservations`.

Three deprecated spellings are kept for one minor-version cycle and defined at
the bottom of this module: ``refresh`` -> ``sync-state``, ``cancel`` -> ``close``,
``release`` -> ``close``. They are built from the canonical commands via
:func:`~scitex_hpc._cli._deprecated_verb.deprecated_verb`, so each old verb runs
the same body it always did and warns once on stderr.
"""

from __future__ import annotations

import json as _json
import sys

import click

from .._reservation import Reservation
from ._deprecated_verb import deprecated_verb
from ._lease_common import serialize_reservation


@click.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def list_cmd(as_json):
    """List active reservations.

    \b
    Example:
      $ scitex-hpc lease list
      $ scitex-hpc lease list --json
    """
    rows = Reservation.list()
    if as_json:
        click.echo(_json.dumps([serialize_reservation(r) for r in rows], indent=2))
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


@click.command("get")
@click.argument("name")
@click.option("--host", default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def get_cmd(ctx, name, host, as_json):
    """Show one reservation as JSON.

    \b
    Example:
      $ scitex-hpc lease get dev-pool
      $ scitex-hpc lease get dev-pool --json
    """
    res = Reservation.get(name, host=host)
    if res is None:
        click.echo(f"(no reservation named {name!r})", err=True)
        ctx.exit(2)
    click.echo(_json.dumps(serialize_reservation(res), indent=2))


@click.command(
    "exec",
    context_settings={
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
    },
)
@click.argument("name")
@click.argument("command")
@click.option("--host", default=None)
@click.option("--dry-run", is_flag=True, help="Print plan without ssh-execing.")
@click.option("-y", "--yes", "yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def exec_cmd(ctx, name, command, host, dry_run, yes):
    """Run a command inside the reservation's allocation.

    \b
    Example:
      $ scitex-hpc lease exec dev-pool 'hostname'
      $ scitex-hpc lease exec dev-pool 'python -m pytest'
    """
    del yes
    res = Reservation.require(name, host=host)
    if dry_run:
        click.echo(f"DRY RUN — would exec on {res.id}: {command}")
        return
    out = res.exec(command)
    sys.stdout.write(out.stdout or "")
    sys.stderr.write(out.stderr or "")
    ctx.exit(out.returncode)


@click.command("sync-state")
@click.argument("name")
@click.option("--host", default=None)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Query squeue and print the record it WOULD write, without saving.",
)
@click.option("-y", "--yes", "yes", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def sync_state_cmd(ctx, name, host, dry_run, yes, as_json):
    """Re-discover the current job_id via squeue (after walltime auto-resubmit).

    Reconciles the LOCAL lease record from SLURM's live state. It moves no
    files — ``scitex_hpc.sync`` is the file transfer, which is why this verb
    names its object (``sync-state``) rather than being a bare ``sync``.

    \b
    It REWRITES the local lease record, so it takes ``--dry-run`` like the
    other mutating verbs. The dry run performs the same squeue query and
    prints the record it would have saved — it is the real answer withheld,
    not a description of one.

    \b
    Example:
      $ scitex-hpc lease sync-state dev-pool
      $ scitex-hpc lease sync-state dev-pool --dry-run
      $ scitex-hpc lease sync-state dev-pool --json
    """
    del yes
    res = Reservation.require(name, host=host)
    before = serialize_reservation(res)
    res.refresh(save=not dry_run)
    after = serialize_reservation(res)
    if as_json:
        click.echo(
            _json.dumps(
                {"dry_run": True, "before": before, "would_write": after}, indent=2
            )
            if dry_run
            else _json.dumps(after, indent=2)
        )
        return
    if dry_run:
        click.echo(f"DRY RUN — would sync lease state for {res.id}, not saved:")
        for key in ("job_id", "node", "walltime_end"):
            mark = " " if before[key] == after[key] else "*"
            click.echo(f" {mark} {key}: {before[key]!r} -> {after[key]!r}")
        return
    if res.job_id:
        click.echo(f"synced: id={res.id} job={res.job_id} node={res.node}")
    else:
        click.echo(
            f"synced: id={res.id} (no live job found via squeue --name={res.name})",
            err=True,
        )
        ctx.exit(2)


@click.command("attach")
@click.argument("name")
@click.option("--host", default=None)
@click.option("--shell", default="bash")
@click.pass_context
def attach_cmd(ctx, name, host, shell):
    """Open an interactive shell on the reservation's compute node.

    \b
    Example:
      $ scitex-hpc lease attach dev-pool
      $ scitex-hpc lease attach dev-pool --shell zsh
    """
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


@click.command("close")
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
def close_cmd(ctx, name, host, missing_ok, dry_run, yes):
    """scancel + clear lease state for a reservation.

    \b
    Example:
      $ scitex-hpc lease close dev-pool
      $ scitex-hpc lease close dev-pool --no-missing-ok
    """
    del yes
    if dry_run:
        click.echo(f"DRY RUN — would close reservation {name!r}")
        return
    _do_cancel(name, host, missing_ok, ctx)


# Deprecated spellings, one migration cycle. Built FROM the canonical commands
# above, so they cannot drift from the bodies they alias. ``release`` predates
# this migration and was already hidden — it now warns like the others, which
# it previously did not.
refresh_alias = deprecated_verb(sync_state_cmd, "refresh", group="lease")
cancel_alias = deprecated_verb(close_cmd, "cancel", group="lease")
release_alias = deprecated_verb(close_cmd, "release", group="lease")
