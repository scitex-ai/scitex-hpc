"""``scitex-hpc ci-runners`` group — durable self-hosted runner fleet.

Subcommands:

  * ``book-supervisor`` — book a dedicated long-walltime CPU allocation
    and host the whole runner fleet on it under auto-restart keep-alive
    loops. Default ``--dry-run`` prints the plan; pass ``--confirm`` to
    actually submit (never on import, never implicitly).
  * ``exec-supervisor`` — run the SAME supervisor body inside an
    ALREADY-RUNNING allocation via ``srun --jobid=<holder> --overlap``,
    for when a dedicated node won't schedule. Same ``--confirm`` gate.
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
import shlex
import sys

import click

from .._config import JobConfig
from .._reservation import Reservation
from ..ci_runners import (
    FleetSpec,
    build_exec_supervisor_script,
    build_monitor_script,
    build_overlap_srun_command,
    build_supervisor_hold_body,
    parse_runner_dirs,
)
from ..ci_runners._archive import build_archive_script
from ..ci_runners._overlap import (
    DEFAULT_BODY_PATH,
    DEFAULT_HOLDER_JOBID_PATH,
    DEFAULT_LOG_PATH,
)

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


@ci_runners.command("exec-supervisor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option(
    "--overlap-jobid",
    "overlap_jobid",
    required=True,
    help="SLURM jobid of an ALREADY-RUNNING holder allocation to overlap onto.",
)
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name", "lease_name", default=_DEFAULT_LEASE_NAME, help="Lease/job name."
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
    fleet = _discover(host, ci_base, tuple(exclude))
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
        click.echo(
            f"exec-supervisor failed (rc={res.returncode})", err=True
        )
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


def _emit_script(script: str, out_path: str | None, as_json: bool) -> None:
    """Write ``script`` to ``out_path`` (chmod +x) or echo it; JSON-wrap if asked."""
    if out_path:
        from pathlib import Path

        p = Path(out_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(script)
        p.chmod(0o755)
        click.echo(_json.dumps({"wrote": str(p)}) if as_json else f"wrote {p}")
    else:
        click.echo(_json.dumps({"script": script}) if as_json else script)


@ci_runners.command("show-monitor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name", "lease_name", default=_DEFAULT_LEASE_NAME, help="Supervisor job name."
)
@click.option(
    "--overlap-jobid",
    "overlap_jobid",
    default=None,
    help="Resolve the supervisor via this holder JOB ID (squeue --job) "
    "instead of --name. Use for the exec-supervisor deploy, where the "
    "supervisor is an --overlap step on an existing holder job (no job "
    "named --name exists, so the name lookup would false-alarm).",
)
@click.option("--out", "out_path", default=None, help="Write to file (default stdout).")
@click.option("--json", "as_json", is_flag=True, help='Emit JSON ({"script": ...}).')
def show_monitor_cmd(host, ci_base, exclude, lease_name, overlap_jobid, out_path, as_json):
    """Show the cron-driven health-monitor script.

    \b
    Example:
      # dedicated book-supervisor allocation (resolve by name):
      $ scitex-hpc ci-runners show-monitor --out ~/.scitex/ci/monitor.sh
      # exec-supervisor on an existing holder (resolve by job id):
      $ scitex-hpc ci-runners show-monitor --overlap-jobid 26437532 --out ~/.scitex/ci/monitor.sh
      $ chmod +x ~/.scitex/ci/monitor.sh
      # crontab: */5 * * * * ~/.scitex/ci/monitor.sh >> ~/.scitex/ci/monitor.log 2>&1
    """
    fleet = _discover(host, ci_base, tuple(exclude))
    script = build_monitor_script(
        fleet, host=host, lease_name=lease_name, overlap_jobid=overlap_jobid
    )
    _emit_script(script, out_path, as_json)


@ci_runners.command("watch")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--jobid-file",
    default=DEFAULT_HOLDER_JOBID_PATH,
    help="Runtime file the supervisor writes its holder job id to.",
)
def watch_cmd(host, ci_base, exclude, jobid_file):
    """Run ONE supervisor health-check tick (the cron watchdog entrypoint).

    This is the command the federated ``scitex_dev.jobs`` JobSpec runs every
    few minutes. It discovers the fleet, resolves the live holder job id from
    ``--jobid-file`` (written by exec-supervisor — no fragile squeue-by-name
    lookup), runs the health monitor, pipes any alarm to ``$SCITEX_CI_ALARM_CMD``,
    and exits with the monitor's code:

    \b
      0  fleet healthy
      1  degraded (some runners down) — alarm fired
      2  allocation gone / unreachable — alarm fired
      3  supervisor UNREGISTERED (no holder jobid file) — alarm fired

    \b
    Example (federated cron installs this automatically):
      $ scitex-hpc ci-runners watch
    """
    import subprocess

    fleet = _discover(host, ci_base, tuple(exclude))
    script = build_monitor_script(
        fleet,
        host=host,
        lease_name=_DEFAULT_LEASE_NAME,
        overlap_jobid_file=jobid_file,
    )
    proc = subprocess.run(["bash", "-c", script])
    sys.exit(proc.returncode)


@ci_runners.command("show-archive")
@click.option(
    "--home", default="~", help="Remote home dir holding the band-aid scripts."
)
@click.option("--out", "out_path", default=None, help="Write to file (default stdout).")
@click.option("--json", "as_json", is_flag=True, help='Emit JSON ({"script": ...}).')
def show_archive_cmd(home, out_path, as_json):
    """Show a script that archives the old ``~`` band-aid scripts.

    Run this on the cluster AFTER the new supervisor is live — the live
    runners still depend on the band-aids until cutover.

    \b
    Example:
      $ scitex-hpc ci-runners show-archive --out ~/.scitex/ci/archive.sh
      $ bash ~/.scitex/ci/archive.sh   # run on the cluster after cutover
    """
    script = build_archive_script(home=home)
    _emit_script(script, out_path, as_json)
