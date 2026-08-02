"""``ci-runners book-supervisor`` / ``exec-supervisor`` — the two verbs that LAUNCH
the runner fleet.

Both build the SAME keep-alive supervisor body from a discovered
:class:`~scitex_hpc.ci_runners.FleetSpec`; they differ only in where it runs —
``book-supervisor`` sbatches a dedicated allocation, ``exec-supervisor``
overlaps a step onto an allocation that is already running. Both default to
dry-run and require ``--confirm`` to act.

Commands are standalone :func:`click.command` objects, attached to the
``ci-runners`` group by :mod:`scitex_hpc._cli._ci_runners`.
"""

from __future__ import annotations

import json as _json
import shlex
import sys

import click

from .._config import JobConfig
from .._reservation import Reservation
from ..ci_runners import (
    build_exec_supervisor_script,
    build_overlap_srun_command,
    build_supervisor_hold_body,
)
from ..ci_runners._overlap import DEFAULT_BODY_PATH, DEFAULT_LOG_PATH
from . import _ci_runners_common as _common


@click.command("book-supervisor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_common.DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name",
    "lease_name",
    default=_common.DEFAULT_LEASE_NAME,
    help="Lease/job name.",
)
@click.option("--partition", default="cascade", help="SLURM partition.")
@click.option("--cpus", type=int, default=32, help="cores for the whole fleet.")
@click.option("--mem", default="128G", help="RAM for the whole fleet.")
@click.option("--time", "time_", default="7-0", help="walltime (cap: 7d cascade).")
@click.option("--account", default="punim2354", help="SLURM account.")
@click.option("--qos", default="publiccpu", help="SLURM QOS.")
@click.option(
    "--confirm",
    is_flag=True,
    help="Actually submit the sbatch job (default is dry-run).",
)
def book_supervisor_cmd(
    host,
    ci_base,
    exclude,
    lease_name,
    partition,
    cpus,
    mem,
    time_,
    account,
    qos,
    confirm,
):
    """Book a dedicated allocation hosting the whole runner fleet.

    \b
    Default is DRY-RUN: prints the plan and the supervisor hold body so
    you can review before paying for a node. Add --confirm to submit.

    \b
    Example (Spartan cascade, 32 cores / 128 GB / 7 days, auto-resubmit):
      $ scitex-hpc ci-runners book-supervisor --confirm
    """
    fleet = _common.discover_fleet(host, ci_base, tuple(exclude))
    active = fleet.active()
    if not active:
        click.echo(f"no runners found under {ci_base}", err=True)
        sys.exit(2)
    hold_body = build_supervisor_hold_body(fleet)
    cfg = JobConfig(
        project=lease_name,
        host=host,
        partition=partition,
        cpus=cpus,
        mem=mem,
        time=time_,
        account=account,
        qos=qos,
        job_name=lease_name,
    )
    if not confirm:
        click.echo("DRY RUN — would book supervisor allocation:")
        click.echo(
            _json.dumps(
                {
                    "lease_name": lease_name,
                    "host": host,
                    "partition": partition,
                    "cpus": cpus,
                    "mem": mem,
                    "time": time_,
                    "account": account,
                    "qos": qos,
                    "persistent": True,
                    "runners": [r.name for r in active],
                },
                indent=2,
            )
        )
        click.echo("\n--- supervisor hold body ---")
        click.echo(hold_body)
        click.echo("Re-run with --confirm to submit.")
        return
    res = Reservation.book(cfg, persistent=True, hold_body=hold_body)
    click.echo(f"booked: id={res.id} job={res.job_id} node={res.node}")
    click.echo(
        "Wire the health monitor next:\n"
        "  scitex-hpc ci-runners show-monitor "
        f"--host {host} --name {lease_name} > ~/.scitex/ci/monitor.sh"
    )


@click.command("exec-supervisor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option(
    "--overlap-jobid",
    "overlap_jobid",
    required=True,
    help="SLURM jobid of an ALREADY-RUNNING holder allocation to overlap onto.",
)
@click.option("--ci-base", default=_common.DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name",
    "lease_name",
    default=_common.DEFAULT_LEASE_NAME,
    help="Lease/job name.",
)
@click.option(
    "--backoff",
    type=int,
    default=None,
    help="Seconds a keep-alive loop waits before relaunching a dead runner.",
)
@click.option(
    "--toolcache",
    default=None,
    help="Runner tool cache dir (AGENT_TOOLSDIRECTORY / RUNNER_TOOL_CACHE).",
)
@click.option(
    "--work-root",
    "work_root",
    default=None,
    help="Root for per-runner _work dirs (kept off the home quota).",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Actually launch the overlap step (default is dry-run).",
)
def exec_supervisor_cmd(
    host,
    overlap_jobid,
    ci_base,
    exclude,
    lease_name,
    backoff,
    toolcache,
    work_root,
    confirm,
):
    """Run the supervisor on an ALREADY-RUNNING allocation (no new node).

    \b
    Same fleet, same keep-alive body as ``book-supervisor`` — but instead
    of booking a fresh dedicated node (which won't schedule on a full
    partition), it launches the supervisor as a STEP inside an existing
    holder allocation via ``srun --jobid=<holder> --overlap``. The step
    is detached with ``setsid nohup`` and stays alive because the body's
    ``wait`` blocks in the step's foreground.

    \b
    Default is DRY-RUN: prints the supervisor body + the exact srun
    command. Add --confirm to actually launch over SSH.

    \b
    Example (overlay the fleet onto running holder job 26437532):
      $ scitex-hpc ci-runners exec-supervisor --overlap-jobid 26437532 --confirm
    """
    fleet = _common.discover_fleet(host, ci_base, tuple(exclude))
    # Apply the optional supervisor knobs onto the shared FleetSpec so the
    # SAME body generator (build_supervisor_hold_body) honours them.
    if backoff is not None:
        fleet.restart_backoff = backoff
    if toolcache is not None:
        fleet.toolcache = toolcache
    if work_root is not None:
        fleet.work_root = work_root
    active = fleet.active()
    if not active:
        click.echo(f"no runners found under {ci_base}", err=True)
        sys.exit(2)
    hold_body = build_supervisor_hold_body(fleet)
    srun_cmd = build_overlap_srun_command(overlap_jobid)
    if not confirm:
        click.echo("DRY RUN — would exec supervisor on existing allocation:")
        click.echo(
            _json.dumps(
                {
                    "lease_name": lease_name,
                    "host": host,
                    "overlap_jobid": overlap_jobid,
                    "body_path": DEFAULT_BODY_PATH,
                    "log_path": DEFAULT_LOG_PATH,
                    "runners": [r.name for r in active],
                },
                indent=2,
            )
        )
        click.echo("\n--- supervisor hold body ---")
        click.echo(hold_body)
        click.echo("\n--- srun launch command ---")
        click.echo(srun_cmd)
        click.echo("\nRe-run with --confirm to launch over SSH.")
        return
    from scitex_ssh import exec_remote

    script = build_exec_supervisor_script(hold_body, overlap_jobid)
    # shlex.quote (NOT json.dumps): the script is a multi-line body with a
    # heredoc; json.dumps escapes newlines to literal \n, which collapses the
    # heredoc onto one line and breaks the env-hardening function. Single-quote
    # quoting preserves real newlines and the body's embedded single quotes.
    res = exec_remote(host, f"bash -lc {shlex.quote(script)}")
    if res.stdout:
        click.echo(res.stdout)
    if res.stderr:
        click.echo(res.stderr, err=True)
    if res.returncode != 0:
        click.echo(f"exec-supervisor failed (rc={res.returncode})", err=True)
        sys.exit(res.returncode)
    click.echo(
        f"launched: overlap step on jobid {overlap_jobid} ({host}); "
        f"log: {DEFAULT_LOG_PATH}"
    )
    click.echo(
        "Wire the health monitor next:\n"
        "  scitex-hpc ci-runners show-monitor "
        f"--host {host} --name {lease_name} > ~/.scitex/ci/monitor.sh"
    )
