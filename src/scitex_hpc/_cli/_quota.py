"""``scitex-hpc quota`` group — filesystem inode-quota early warning.

Subcommands:

  * ``check`` — ``df -i`` the tracked filesets and alarm (exit 1) if any is
    at/over the threshold (default 90%). The command the federated
    ``scitex-hpc.inode-quota-warn`` cron JobSpec runs.

Cluster-agnostic (plain ``df -i``); no hostnames baked in beyond the
``--host`` / ``--path`` defaults, both overridable.
"""

from __future__ import annotations

import json as _json
import sys

import click

from .._quota import (
    DEFAULT_PATHS,
    DEFAULT_THRESHOLD_PCT,
    alarm,
    check_inode_quota,
)


@click.group("quota")
def quota() -> None:
    """Filesystem inode-quota early warning (df -i based).

    \b
    Guardrail for the GPFS inode-quota wall: alarm at 90% so a fileset is
    never silently exhausted (the failure mode that breaks SAC state-dbs).
    """


@quota.command("check")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option(
    "--path",
    "paths",
    multiple=True,
    help="Fileset path to check (repeatable; default: the punim0264 project).",
)
@click.option(
    "--threshold",
    "threshold_pct",
    type=int,
    default=DEFAULT_THRESHOLD_PCT,
    help="Alarm when inode usage %% is at/over this (default: 90).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
def check_cmd(host, paths, threshold_pct, as_json):
    """Report inode-quota usage; alarm + exit 1 if any fileset is over threshold.

    \b
    Exit codes: 0 = all under threshold, 1 = one or more filesets at/over it
    (alarm fired via $SCITEX_CI_ALARM_CMD).

    \b
    Example:
      $ scitex-hpc quota check
      $ scitex-hpc quota check --path /data/gpfs/projects/punim0264 \\
          --threshold 90 --json
    """
    report = check_inode_quota(
        host, tuple(paths) or DEFAULT_PATHS, threshold_pct=threshold_pct
    )
    if as_json:
        click.echo(_json.dumps(report, indent=2))
    else:
        for row in report["paths"]:
            if row.get("error"):
                click.echo(f"  {row['path']}: {row['error']}")
            else:
                click.echo(
                    f"  {row['path']}: {row['pct']}% inodes "
                    f"({row['used']}/{row['total']}, {row['free']} free)"
                )
    if report["over"]:
        worst = max(report["over"], key=lambda r: r["pct"])
        alarm(
            f"scitex-hpc: inode quota {worst['pct']}% on {host}",
            f"Filesets at/over {threshold_pct}%: "
            + ", ".join(f"{r['path']} ({r['pct']}%)" for r in report["over"])
            + ". Reclaim inodes before the fileset walls (SAC state-dbs fail "
            "at the wall). A heavy du --inodes scan must run on a compute "
            "node, not the login node.",
        )
        sys.exit(1)
    sys.exit(0)
