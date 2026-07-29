"""``list-python-apis`` introspection command (§1a)."""

from __future__ import annotations

import json as _json

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand


@click.command(
    "list-python-apis",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="List public Python API symbols of scitex_hpc.",
        examples=(
            Example("{prog} list-python-apis", "Names only."),
            Example("{prog} list-python-apis -v", "Names with descriptions."),
            Example("{prog} list-python-apis --json", "Structured JSON output."),
        ),
    ),
)
@click.option("-v", "--verbose", count=True, help="Verbosity (-v, -vv).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list_python_apis(verbose, as_json):
    apis = [
        ("JobConfig", "Cluster-agnostic SLURM job configuration."),
        ("Reservation", "Persistent SLURM allocation handle."),
        ("srun", "Blocking interactive srun dispatch."),
        ("sbatch", "Async sbatch submission; returns job_id."),
        ("sync", "rsync local sources to the cluster."),
        ("poll_job", "Check sacct status for a job_id."),
        ("job_stats", "Per-job (and per-array-task) sacct resource report."),
        ("fetch_result", "scp the .out file of a finished sbatch job."),
    ]
    if as_json:
        click.echo(
            _json.dumps(
                {
                    "module": "scitex_hpc",
                    "apis": [{"name": n, "description": d} for n, d in apis],
                },
                indent=2,
            )
        )
        return
    click.echo("scitex_hpc Python API:")
    click.echo()
    for name, desc in apis:
        if verbose >= 1:
            click.echo(f"  {name:16s} {desc}")
        else:
            click.echo(f"  {name}")
