"""``scitex-hpc walltime`` group — empirically verified SLURM walltime limits.

Decision-info command, not lore: the answer to "what walltime can I
actually get?" should live here, not in a doc, a memory, or a table that
drifts. See ``_walltime.py`` and the
``14_permanent-allocation-doctrine.md`` skill for why ``sinfo``'s MaxTime
alone is not enough.
"""

from __future__ import annotations

import json as _json

import click

from .._config import JobConfig
from .._walltime import WalltimeMax, walltime_max


def _serialize(result: WalltimeMax) -> dict:
    return {
        "partition": result.partition,
        "sinfo_ceiling": result.sinfo_ceiling,
        "qos_max_wall": result.qos_max_wall,
        "assoc_max_wall": result.assoc_max_wall,
        "achievable": result.achievable(),
        "verified": result.verified,
        "verified_accepted": result.verified_accepted,
        "verified_rejected": result.verified_rejected,
        "note": result.note,
    }


@click.group("walltime")
def walltime() -> None:
    """Empirically-verified SLURM walltime limits (not sinfo alone)."""


@walltime.command("show")
@click.argument("partition")
@click.option(
    "--host",
    default=None,
    help="SSH host (falls back to $SCITEX_HPC_HOST / user config).",
)
@click.option(
    "--account", default=None, help="SLURM account (falls back to config)."
)
@click.option("--qos", default=None, help="SLURM QOS tier (falls back to config).")
@click.option(
    "--verify",
    is_flag=True,
    help=(
        "Decisively confirm the achievable walltime with a real "
        "sbatch --test-only probe (SLURM's own dry-run — never actually "
        "queues a job). Without this flag, the command only reports "
        "sinfo/sacctmgr readings without confirming them."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def walltime_show_cmd(partition, host, account, qos, verify, as_json):
    """Report the empirically achievable walltime ceiling for PARTITION.

    \b
    sinfo's MaxTime is a partition CEILING, not a guarantee — the real
    limit is the tightest of the partition ceiling, the QOS's MaxWall,
    and your account association's MaxWall, none of which sinfo alone
    reveals. This command checks all three, and with --verify submits a
    real (non-queuing) sbatch --test-only probe as the decisive check.

    \b
    Example:
      $ scitex-hpc walltime show sapphire --verify
      $ scitex-hpc walltime show gpu-h100 --json
    """
    config = JobConfig(project="", host=host, account=account, qos=qos)
    result = walltime_max(config, partition, verify=verify)

    if as_json:
        click.echo(_json.dumps(_serialize(result), indent=2))
        return

    click.echo(f"partition:        {result.partition}")
    click.echo(f"sinfo ceiling:    {result.sinfo_ceiling or '(unknown)'}")
    click.echo(f"QOS MaxWall:      {result.qos_max_wall or '(none set)'}")
    click.echo(f"assoc MaxWall:    {result.assoc_max_wall or '(none set)'}")
    click.echo(f"achievable (est): {result.achievable() or '(unknown)'}")
    if result.verified_rejected:
        click.echo(f"VERIFIED REJECTED: {result.verified_rejected}", err=True)
    elif result.verified_accepted:
        click.echo(f"verified accepted: {result.verified_accepted}")
    click.echo(f"note: {result.note}")

    if result.verified_rejected:
        raise SystemExit(1)
