"""``scitex-hpc ci-runners`` group — durable self-hosted runner fleet.

Subcommands:

  * ``book-supervisor`` — book a dedicated long-walltime CPU allocation
    and host the whole runner fleet on it under auto-restart keep-alive
    loops. Default ``--dry-run`` prints the plan; pass ``--confirm`` to
    actually submit (never on import, never implicitly).
  * ``show-monitor`` — emit the cron-driven health-monitor script.
  * ``show-archive`` — emit a script that archives the old ``~`` band-aid
    scripts to ``.old/<timestamp>/`` on the cluster (the operator runs it
    AFTER cutover; live runners still depend on the band-aids until then).
  * ``discover`` — list the runner install dirs found under the CI base.

The CLI only ever *reads* the cluster (discover) or *prints plans /
scripts* — submission and archival are explicit operator actions guarded
behind ``--confirm`` / hand-running the generated scripts.
"""

from __future__ import annotations

import json as _json
import sys

import click

from .._config import JobConfig
from .._reservation import Reservation
from ..ci_runners import (
    FleetSpec,
    build_monitor_script,
    build_supervisor_hold_body,
    parse_runner_dirs,
)
from ..ci_runners._archive import build_archive_script

# Spartan default CI base (overridable). Documented, not magic: this is
# where the 72 install dirs live today.
_DEFAULT_CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"
_DEFAULT_LEASE_NAME = "spartan-ci-runner-fleet"


@click.group("ci-runners")
def ci_runners() -> None:
    """Durable self-hosted GitHub Actions runner fleet on SLURM.

    \b
    Replaces the login-node band-aids: one dedicated allocation hosts all
    runners under auto-restart keep-alive loops, with a cron health
    monitor that alarms the operator on failure.
    """


def _discover(host: str, ci_base: str, exclude: tuple[str, ...]) -> FleetSpec:
    """Read the CI base dir over SSH and build a FleetSpec.

    Light ``ls`` only (admin-flagged: no recursive scans on the login
    node).
    """
    from scitex_ssh import exec_remote

    out = exec_remote(host, f"bash -lc 'ls {ci_base} 2>/dev/null'")
    runners = parse_runner_dirs(out.stdout or "", ci_base=ci_base)
    return FleetSpec(ci_base=ci_base, runners=runners, exclude=exclude)


@ci_runners.command("discover")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def discover_cmd(host, ci_base, exclude, as_json):
    """List the runner install dirs found under the CI base (light ls).

    \b
    Example:
      $ scitex-hpc ci-runners discover --host spartan
      $ scitex-hpc ci-runners discover --json
    """
    fleet = _discover(host, ci_base, tuple(exclude))
    active = fleet.active()
    if as_json:
        click.echo(
            _json.dumps(
                [{"name": r.name, "dir": r.dir} for r in active], indent=2
            )
        )
        return
    click.echo(f"{len(active)} runners under {ci_base}:")
    for r in active:
        click.echo(f"  {r.name:32}  {r.dir}")


@ci_runners.command("book-supervisor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name", "lease_name", default=_DEFAULT_LEASE_NAME, help="Lease/job name."
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
    fleet = _discover(host, ci_base, tuple(exclude))
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


@ci_runners.command("show-monitor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name", "lease_name", default=_DEFAULT_LEASE_NAME, help="Supervisor job name."
)
@click.option("--out", "out_path", default=None, help="Write to file (default stdout).")
def show_monitor_cmd(host, ci_base, exclude, lease_name, out_path):
    """Emit the cron-driven health-monitor script.

    \b
    Example:
      $ scitex-hpc ci-runners show-monitor --out ~/.scitex/ci/monitor.sh
      $ chmod +x ~/.scitex/ci/monitor.sh
      # crontab: */5 * * * * ~/.scitex/ci/monitor.sh >> ~/.scitex/ci/monitor.log 2>&1
    """
    fleet = _discover(host, ci_base, tuple(exclude))
    script = build_monitor_script(fleet, host=host, lease_name=lease_name)
    if out_path:
        from pathlib import Path

        p = Path(out_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(script)
        p.chmod(0o755)
        click.echo(f"wrote {p}")
    else:
        click.echo(script)


@ci_runners.command("show-archive")
@click.option(
    "--home", default="~", help="Remote home dir holding the band-aid scripts."
)
@click.option("--out", "out_path", default=None, help="Write to file (default stdout).")
def show_archive_cmd(home, out_path):
    """Emit a script that archives the old ``~`` band-aid scripts.

    Run this on the cluster AFTER the new supervisor is live — the live
    runners still depend on the band-aids until cutover.

    \b
    Example:
      $ scitex-hpc ci-runners show-archive --out ~/.scitex/ci/archive.sh
      $ bash ~/.scitex/ci/archive.sh   # run on the cluster after cutover
    """
    script = build_archive_script(home=home)
    if out_path:
        from pathlib import Path

        p = Path(out_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(script)
        p.chmod(0o755)
        click.echo(f"wrote {p}")
    else:
        click.echo(script)
