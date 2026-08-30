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
  * ``watch`` — run ONE monitor tick (the federated cron entrypoint).
  * ``show-register`` — print the ``config.sh`` command that registers a
    runner WITH the ``scitex-ci`` label baked in (closes label drift at
    the source, so a re-registered runner never queues its repo's CI).
  * ``show-archive`` — emit a script that archives the old ``~`` band-aid
    scripts to ``.old/<timestamp>/`` on the cluster (the operator runs it
    AFTER cutover; live runners still depend on the band-aids until then).
  * ``discover`` — list the runner install dirs found under the CI base.

The CLI only ever *reads* the cluster (discover) or *prints plans /
scripts* — submission and archival are explicit operator actions guarded
behind ``--confirm`` / hand-running the generated scripts.

The two LAUNCH verbs live in :mod:`_ci_runners_supervisor`; cluster
discovery and script emission live in :mod:`_ci_runners_common`. This
module owns the group, the read-only / print-only verbs, and the explicit
``add_command`` assembly.
"""

from __future__ import annotations

import json as _json
import sys

import click

from ..ci_runners import build_monitor_script
from ..ci_runners._deploy import inspect_deploy
from ..ci_runners._monitor import _ALARM_FUNC
from ..ci_runners._archive import build_archive_script
from ..ci_runners._overlap import DEFAULT_HOLDER_JOBID_PATH
from ..ci_runners._register import DEFAULT_RUNNER_LABELS, build_register_command
from . import _ci_runners_common as _common
from ._ci_runners_supervisor import book_supervisor_cmd, exec_supervisor_cmd


@click.group("ci-runners")
def ci_runners() -> None:
    """Durable self-hosted GitHub Actions runner fleet on SLURM.

    \b
    Replaces the login-node band-aids: one dedicated allocation hosts all
    runners under auto-restart keep-alive loops, with a cron health
    monitor that alarms the operator on failure.
    """


@click.command("discover")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_common.DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def discover_cmd(host, ci_base, exclude, as_json):
    """List the runner install dirs found under the CI base (light ls).

    \b
    Example:
      $ scitex-hpc ci-runners discover --host spartan
      $ scitex-hpc ci-runners discover --json
    """
    fleet = _common.discover_fleet(host, ci_base, tuple(exclude))
    active = fleet.active()
    if as_json:
        click.echo(
            _json.dumps([{"name": r.name, "dir": r.dir} for r in active], indent=2)
        )
        return
    click.echo(f"{len(active)} runners under {ci_base}:")
    for r in active:
        click.echo(f"  {r.name:32}  {r.dir}")


@click.command("show-monitor")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_common.DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--name",
    "lease_name",
    default=_common.DEFAULT_LEASE_NAME,
    help="Supervisor job name.",
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
def show_monitor_cmd(
    host, ci_base, exclude, lease_name, overlap_jobid, out_path, as_json
):
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
    fleet = _common.discover_fleet(host, ci_base, tuple(exclude))
    _common.require_active_fleet(fleet, ci_base)
    script = build_monitor_script(
        fleet, host=host, lease_name=lease_name, overlap_jobid=overlap_jobid
    )
    _common.emit_script(script, out_path, as_json)


def _fire_alarm(subject: str, body: str) -> None:
    """Fire an alarm through the monitor's OWN contract.

    Deliberately re-uses ``_ALARM_FUNC`` rather than reimplementing it in
    Python: two alarm paths drift, and the one that drifts is always the
    one that has never fired.
    """
    import subprocess as _sp

    _sp.run(
        ["bash", "-c", _ALARM_FUNC + '\nalarm "$1" "$2"', "alarm", subject, body],
        check=False,
    )

@click.command("watch")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option("--ci-base", default=_common.DEFAULT_CI_BASE, help="CI base dir.")
@click.option("--exclude", multiple=True, help="Runner name(s) to exclude.")
@click.option(
    "--jobid-file",
    default=DEFAULT_HOLDER_JOBID_PATH,
    help="Runtime file the supervisor writes its holder job id to.",
)
@click.option(
    "--no-deploy-check",
    "no_deploy_check",
    is_flag=True,
    help="Skip the deploy-drift check (exit 14). See _deploy.py for why it "
    "exists: an editable install makes a working tree the artifact, so "
    "merged silently reads as deployed.",
)
def watch_cmd(host, ci_base, exclude, jobid_file, no_deploy_check):
    """Run ONE supervisor health-check tick (the cron watchdog entrypoint).

    This is the command the federated ``scitex_dev.jobs`` JobSpec runs every
    few minutes. It discovers the fleet, resolves the live holder job id from
    ``--jobid-file`` (written by exec-supervisor — no fragile squeue-by-name
    lookup), runs the health monitor, pipes any alarm to ``$SCITEX_CI_ALARM_CMD``,
    and exits with the monitor's code:

    \b
      0   fleet healthy
      10  degraded (some runners down) — alarm fired
      11  allocation gone / unreachable — alarm fired
      12  supervisor UNREGISTERED (no holder jobid file) — alarm fired
      13  runner fileset out of inodes — alarm fired
      14  DEPLOY DRIFT: the running code is not the merged code — alarm fired

    \b
    10-13 are the monitor's own codes, passed through unchanged by
    ``sys.exit(proc.returncode)``. They start at 10 deliberately: 1-9 are
    what bash itself returns when the generated script cannot run at all
    (127 = interpreter/PATH, 126 = not executable, 1 = a shell-level
    failure), so a two-digit code always means "the monitor RAN and
    reached a verdict" and a one-digit one always means "it never got
    that far". A watchdog that cannot tell those apart reports an
    unreachable cluster and a broken launcher identically.

    \b
    14 is this command's own, and it is the one code that is NOT a fleet
    verdict: it says the fleet's verdict cannot be trusted because the
    code that produced it is not the merged code. It fires only when the
    fleet is otherwise HEALTHY -- a real outage always wins the exit code,
    because a stale deploy must never mask a down cluster. Pass
    ``--no-deploy-check`` to skip it (or when origin is deliberately
    unreachable).

    \b
    Example (federated cron installs this automatically):
      $ scitex-hpc ci-runners watch
    """
    import subprocess

    fleet = _common.discover_fleet(host, ci_base, tuple(exclude))
    _common.require_active_fleet(fleet, ci_base)
    script = build_monitor_script(
        fleet,
        host=host,
        lease_name=_common.DEFAULT_LEASE_NAME,
        overlap_jobid_file=jobid_file,
    )
    proc = subprocess.run(["bash", "-c", script])
    rc = proc.returncode

    if no_deploy_check:
        sys.exit(rc)

    # Ask the IMPORTED module where it lives -- never guess a path, because
    # guessing is exactly what the editable-install indirection defeats.
    from ..ci_runners import _monitor as _monitor_mod

    dep = inspect_deploy(_monitor_mod.__file__)
    click.echo(f"DEPLOY {dep.state} {dep.detail}", err=(rc != 0))

    if not dep.is_drift:
        sys.exit(rc)

    if rc != 0:
        # A real outage outranks drift. Say both, exit the outage's code:
        # silencing a down cluster to report a pull would be a strict
        # downgrade of the alarm.
        click.echo(
            f"DEPLOY drift NOT escalated: fleet verdict {rc} takes "
            "precedence (fix the fleet, then deploy)",
            err=True,
        )
        sys.exit(rc)

    _fire_alarm(
        "scitex-ci: DEPLOY DRIFT -- watchdog is grading stale code",
        f"{dep.detail}\n\nThe fleet itself reported HEALTHY, so this is not "
        "an outage. It is worse in one specific way: every verdict this "
        "watchdog produces is sourced from code that is not the merged "
        "code, so both its OK and its CRITICAL are untrustworthy until the "
        "deploy site is fast-forwarded.",
    )
    sys.exit(14)


@click.command("show-register")
@click.option(
    "--url",
    required=True,
    help="Repo or org URL the runner registers to "
    "(e.g. https://github.com/ywatanabe1989/scitex-hpc).",
)
@click.option("--name", required=True, help="Runner name (install-dir tag).")
@click.option(
    "--token",
    default="<TOKEN>",
    help="Registration token from GitHub → Settings → Actions → Runners → "
    "New (short-lived; default prints a <TOKEN> placeholder to fill in).",
)
@click.option(
    "--label",
    "labels",
    multiple=True,
    help="Extra label(s) to register with (repeatable). scitex-ci is ALWAYS "
    f"added even if omitted. Default: {','.join(DEFAULT_RUNNER_LABELS)}.",
)
@click.option(
    "--work", default=None, help="Runner _work dir (keep off the home quota)."
)
@click.option(
    "--runner-group", "runner_group", default=None, help="Runner group name."
)
@click.option(
    "--no-replace",
    "no_replace",
    is_flag=True,
    help="Do NOT pass --replace (error instead of re-registering same name).",
)
@click.option("--json", "as_json", is_flag=True, help='Emit JSON ({"command": ...}).')
def show_register_cmd(url, name, token, labels, work, runner_group, no_replace, as_json):
    """Show the ``config.sh`` command that registers a runner WITH ``scitex-ci``.

    \b
    The label the ci-template ``runs-on: [self-hosted, scitex-ci]`` selects
    on is baked into every command this prints, so a re-registered or
    freshly-stood-up runner can never drift back to the un-labelled state
    that queues a repo's CI forever (the 2026-06-26 label-drift outage).
    Print-only: run the emitted command on the cluster in the runner's
    install dir with a fresh registration token.

    \b
    Example:
      $ scitex-hpc ci-runners show-register \\
          --url https://github.com/ywatanabe1989/scitex-hpc \\
          --name scitex-hpc --work /tmp/scitex-ci-runner-work/scitex-hpc
      ./config.sh --unattended --url https://github.com/... --token <TOKEN> \\
          --name scitex-hpc --labels spartan-cpu,scitex-ci --work ... --replace
    """
    command = build_register_command(
        url=url,
        name=name,
        token=token,
        labels=tuple(labels) if labels else DEFAULT_RUNNER_LABELS,
        work=work,
        runner_group=runner_group,
        replace=not no_replace,
    )
    click.echo(_json.dumps({"command": command}) if as_json else command)


@click.command("show-archive")
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
    _common.emit_script(script, out_path, as_json)


for _cmd in (
    discover_cmd,
    book_supervisor_cmd,
    exec_supervisor_cmd,
    show_monitor_cmd,
    watch_cmd,
    show_register_cmd,
    show_archive_cmd,
):
    ci_runners.add_command(_cmd)
del _cmd
