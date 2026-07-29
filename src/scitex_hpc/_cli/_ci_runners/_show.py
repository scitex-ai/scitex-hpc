"""Print-only verbs: ``show-monitor``, ``show-register``, ``show-archive``.

All three render a script or command and share ``_emit_script``. None of
them mutates the cluster — the operator runs what they emit.
"""

from __future__ import annotations

import json as _json

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand

from ...ci_runners import build_monitor_script
from ...ci_runners._archive import build_archive_script
from ...ci_runners._register import DEFAULT_RUNNER_LABELS, build_register_command
from . import _group
from ._group import _DEFAULT_CI_BASE, _DEFAULT_LEASE_NAME, ci_runners


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


@ci_runners.command(
    "show-monitor",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Show the cron-driven health-monitor script.",
        description=(
            "Resolve the supervisor by NAME for a dedicated book-supervisor "
            "allocation, or by JOB ID for an exec-supervisor overlap step "
            "(where no job named --name exists, so a name lookup would "
            "false-alarm)."
        ),
        examples=(
            Example(
                "{prog} ci-runners show-monitor --out ~/.scitex/ci/monitor.sh",
                "Dedicated allocation: resolve by name.",
            ),
            Example(
                "{prog} ci-runners show-monitor --overlap-jobid 26437532 "
                "--out ~/.scitex/ci/monitor.sh",
                "Overlap deploy: resolve by holder job id.",
            ),
        ),
    ),
)
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
def show_monitor_cmd(
    host, ci_base, exclude, lease_name, overlap_jobid, out_path, as_json
):
    fleet = _group._discover(host, ci_base, tuple(exclude))
    script = build_monitor_script(
        fleet, host=host, lease_name=lease_name, overlap_jobid=overlap_jobid
    )
    _emit_script(script, out_path, as_json)


@ci_runners.command(
    "show-register",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary=(
            "Show the config.sh command that registers a runner WITH "
            "scitex-ci."
        ),
        description=(
            "The label the ci-template `runs-on: [self-hosted, scitex-ci]` "
            "selects on is baked into every command this prints, so a "
            "re-registered or freshly stood-up runner can never drift back "
            "to the un-labelled state that queues a repo's CI forever (the "
            "2026-06-26 label-drift outage). Print-only: run the emitted "
            "command on the cluster in the runner's install dir with a fresh "
            "registration token."
        ),
        examples=(
            Example(
                "{prog} ci-runners show-register "
                "--url https://github.com/ywatanabe1989/scitex-hpc "
                "--name scitex-hpc",
                "Print the labelled config.sh registration command.",
            ),
        ),
    ),
)
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


@ci_runners.command(
    "show-archive",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Show a script that archives the old ~ band-aid scripts.",
        description=(
            "Run this on the cluster AFTER the new supervisor is live — the "
            "live runners still depend on the band-aids until cutover."
        ),
        examples=(
            Example(
                "{prog} ci-runners show-archive --out ~/.scitex/ci/archive.sh",
                "Emit the archival script for the operator to run.",
            ),
        ),
    ),
)
@click.option(
    "--home", default="~", help="Remote home dir holding the band-aid scripts."
)
@click.option("--out", "out_path", default=None, help="Write to file (default stdout).")
@click.option("--json", "as_json", is_flag=True, help='Emit JSON ({"script": ...}).')
def show_archive_cmd(home, out_path, as_json):
    script = build_archive_script(home=home)
    _emit_script(script, out_path, as_json)
