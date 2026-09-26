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
from .._heartbeat import DEFAULT_GRACE, heartbeat_liveness
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


@liveness.command("check-heartbeat")
@click.option(
    "--log",
    required=True,
    help="ABSOLUTE path to the component's heartbeat log ON THE REMOTE HOST. "
    "A tilde path is expanded by your local shell before this command sees "
    "it, so you would send your own home directory to another machine.",
)
@click.option(
    "--lock",
    default="",
    help="ABSOLUTE path to its lockfile on the remote host (same caveat as "
    "--log). Without one, no holder can be observed and a stale cadence can "
    "only ever be UNKNOWN.",
)
@click.option(
    "--interval",
    type=int,
    default=None,
    help="Cadence in seconds. Read from the START line ('interval=1800s') "
    "when omitted.",
)
@click.option(
    "--grace",
    type=float,
    default=DEFAULT_GRACE,
    show_default=True,
    help="Multiplier on the cadence before a missed tick counts as STALLED.",
)
@click.option(
    "--match",
    default="",
    help="Substring the holder's /proc/<pid>/cmdline must contain; guards "
    "against a recycled pid.",
)
@click.option(
    "--host",
    default=None,
    help="SSH host to probe FROM. To earn STOPPED this must be the node the "
    "component started on (falls back to $SCITEX_HPC_HOST / user config).",
)
@click.option(
    "--indent",
    type=int,
    default=2,
    show_default=True,
    help="JSON indent (pass 0 for a single compact line).",
)
def check_heartbeat_cmd(log, lock, interval, grace, match, host, indent):
    """Report whether a cadenced background loop is running, as JSON.

    \b
    For components that are NOT SLURM jobs: a bare loop holding a lockfile and
    appending to a log on a fixed interval. `liveness check` cannot see these
    at all — they live inside somebody else's allocation.

    \b
    Contract (the JSON `verdict` field is the contract, not the exit code):
      ALIVE   A holder is observed AND the last tick is within interval*grace.
      STALLED A holder is observed but the cadence was missed — the process
              exists and is not doing its job. Never folded into ALIVE.
      STOPPED Positive, NODE-LOCAL evidence of no holder: the recorded pid has
              no /proc entry, or a non-blocking acquire of the lock succeeded,
              and the probe ran on the node the component started on.
      UNKNOWN Everything else — transport failure, truncated probe output, no
              log, unknown cadence, a recycled pid, or any negative holder
              observation made from a DIFFERENT node than the holder's.

    \b
    Why the node rule: /proc is node-local and flock is not guaranteed
    cluster-coherent on shared storage, so a probe from the login node can
    acquire a lock a compute node genuinely holds. A false STOPPED authorises
    starting a second copy, and two copies read-modify-writing shared state is
    worse than none — both logs keep moving, so it presents as healthy.

    \b
    PATHS ARE REMOTE AND MUST BE ABSOLUTE. A tilde is expanded by YOUR shell
    before this command runs, so a tilde path sends your own home directory to
    the remote host. On a container agent that is /home/agent, which does not
    exist there — the probe then reports no log and the verdict is UNKNOWN.
    Honest, but it is your path that was wrong, not the world.

    \b
    Example:
      $ scitex-hpc liveness check-heartbeat \\
          --log /home/ywatanabe/.scitex/hpc/runtime/x.log \\
          --lock /home/ywatanabe/.scitex/hpc/runtime/x.lock \\
          --match bridge --host spartan
    """
    config = JobConfig(project="", host=host)
    result = heartbeat_liveness(
        config.resolve("host"),
        log=log,
        lock=lock,
        interval=interval,
        grace=grace,
        match=match,
    )
    click.echo(_json.dumps(result.to_dict(), indent=indent or None))
