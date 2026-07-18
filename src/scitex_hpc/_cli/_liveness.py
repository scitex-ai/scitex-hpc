"""``scitex-hpc liveness`` group — the SLURM job-liveness instrument.

Emits a JSON verdict (ALIVE / DEAD / UNKNOWN) plus the evidence behind it,
for consumers like ``sac db reconcile-remote`` deciding whether a stale
remote agent row may be tombstoned. A false DEAD would tombstone a LIVE
agent, so DEAD must be earned; see ``_liveness.py`` for the full contract.
"""

from __future__ import annotations

import json as _json

import click

from .._config import JobConfig
from .._liveness import DEFAULT_SACCT_WINDOW, job_liveness


@click.group("liveness")
def liveness() -> None:
    """SLURM job-liveness instrument (ALIVE / DEAD / UNKNOWN, with evidence).

    \b
    SLURM on the login node is the only authoritative dead-signal: once an
    allocation ends, pam_slurm_adopt blocks login->compute ssh, so a tmux
    probe can only ever say UNKNOWN.
    """


@liveness.command("check")
@click.option("--job-id", default=None, help="SLURM job id to check.")
@click.option("--name", default=None, help="SLURM job name (friendly/lease name).")
@click.option(
    "--node",
    default=None,
    help="Expected compute node; cross-check only (a mismatch yields UNKNOWN).",
)
@click.option(
    "--host",
    default=None,
    help="SSH login host (falls back to $SCITEX_HPC_HOST / user config).",
)
@click.option(
    "--sacct-window",
    default=DEFAULT_SACCT_WINDOW,
    show_default=True,
    help="sacct --starttime window; older job-ids are UNKNOWN, never DEAD.",
)
@click.option(
    "--indent",
    type=int,
    default=2,
    show_default=True,
    help="JSON indent (pass 0 for a single compact line).",
)
def check_cmd(job_id, name, node, host, sacct_window, indent):
    """Report whether a SLURM job is ALIVE, DEAD, or UNKNOWN, as JSON.

    \b
    Contract (the JSON `verdict` field is the contract, not the exit code):
      ALIVE   squeue rc=0 and the job is present in an active state
              (RUNNING / PENDING / CONFIGURING / COMPLETING).
      DEAD    Positive evidence only: squeue rc=0 with the job absent, AND
              sacct rc=0 reporting a terminal state (or confirming the
              absence with a witness query proving the window is populated).
      UNKNOWN Everything else — any non-zero exit, stderr indicating
              failure, transport error, unparseable output, a job-id outside
              the sacct retention window, a name matching 2+ jobs, or a
              recycled job-id whose name does not match.

    \b
    At least one of --job-id / --name is required; --node alone cannot
    identify a job. Exit code is 0 whenever a verdict was produced (all
    three are legitimate answers) and 2 for a usage error, so exit status
    never conflates with the verdict.

    \b
    Example:
      $ scitex-hpc liveness check --job-id 24386489 --name spartan-cpu-agent
      $ scitex-hpc liveness check --name spartan-cpu-agent --host spartan
    """
    if not job_id and not name:
        raise click.UsageError(
            "at least one of --job-id / --name is required "
            "(--node alone cannot identify a job)"
        )

    config = JobConfig(project="", host=host)
    result = job_liveness(
        config.resolve("host"),
        job_id=job_id,
        name=name,
        node=node,
        sacct_window=sacct_window,
    )
    click.echo(_json.dumps(result.to_dict(), indent=indent or None))
