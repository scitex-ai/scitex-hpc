"""Scheduler-neutral compute commands; all execution delegates to the leaf API."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import click

from ..scheduler import BatchRequest, ComputeClient, JobHandle, load_profile

try:
    from scitex_dev.ecosystem import CliHelp, Example, SpecCommand, SpecGroup
except ImportError:
    CliHelp = None


def _help(summary, *, group=False, example=None):
    if CliHelp is None:
        return {"help": summary}
    examples = (Example(example, summary),) if example else ()
    return {
        "cls": SpecGroup if group else SpecCommand,
        "help_spec": CliHelp(summary=summary, examples=examples),
    }


@click.group(
    "compute",
    **_help(
        "Plan and manage single-node batch jobs on Slurm or Grid Engine.", group=True
    ),
)
def compute():
    """Plan and manage single-node batch jobs on Slurm or Grid Engine."""


def _options(function):
    function = click.option(
        "--config",
        type=click.Path(exists=True, dir_okay=False),
        help="HPC configuration path.",
    )(function)
    return click.option(
        "--profile", required=True, help="Named profile in the HPC configuration."
    )(function)


def _client(profile, config):
    return ComputeClient(load_profile(profile, path=config))


def _spec(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("argv"), list):
        raise ValueError("Job JSON must be a mapping containing an argv array")
    data["argv"] = tuple(data["argv"])
    return BatchRequest(**data)


def _handle(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Job handle must be a JSON object returned by submit")
    return JobHandle(**data)


@compute.command(
    "plan",
    **_help(
        "Print a JSON plan without contacting SSH or submitting work.",
        example="{prog} compute plan --profile my-cluster --spec job.json",
    ),
)
@_options
@click.option(
    "--name", help="Correlation name; reuse it when submitting the reviewed plan."
)
@click.option(
    "--spec",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Portable BatchRequest JSON file.",
)
def compute_plan(profile, config, spec, name):
    """Print a JSON submission plan; does not contact SSH or submit work."""
    try:
        result = _client(profile, config).plan(_spec(spec), name=name)
    except (OSError, ValueError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(asdict(result), indent=2))


@compute.command(
    "submit",
    **_help(
        "Submit once and return a JSON handle; never automatically retry.",
        example="{prog} compute submit --profile my-cluster --spec job.json --yes",
    ),
)
@_options
@click.option("--name", help="Correlation name from the reviewed plan.")
@click.option(
    "--spec",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Portable BatchRequest JSON file.",
)
@click.option(
    "--yes",
    is_flag=True,
    required=True,
    help="Acknowledge that submitting can consume billed resources.",
)
def compute_submit(profile, config, spec, yes, name):
    """Submit once and print a JSON job handle; never automatically retries."""
    try:
        result = _client(profile, config).submit(_spec(spec), name=name)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(asdict(result), indent=2))


@compute.command(
    "status",
    **_help(
        "Query normalized job state and original exit evidence.",
        example="{prog} compute status --profile my-cluster --job-handle job-handle.json",
    ),
)
@_options
@click.option(
    "--job-handle",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="JSON handle returned by submit.",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Emit the complete machine-readable status."
)
@click.pass_context
def compute_status(ctx, profile, config, job_handle, as_json):
    """Print normalized state and native exit evidence; query failure is unknown."""
    try:
        client = _client(profile, config)
        job = _handle(job_handle)
        result = client.status(job)
    except (OSError, ValueError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json or (ctx.obj or {}).get("as_json"):
        click.echo(json.dumps(asdict(result), indent=2))
    else:
        import scitex_logging as slogging

        slogging.getConsole(__name__).info(
            f"{result.state.value}: {result.native_state or result.reason}"
        )


@compute.command(
    "cancel",
    **_help(
        "Request cancellation of this job only; terminal state remains unobserved.",
        example="{prog} compute cancel --profile my-cluster --job-handle job-handle.json --yes",
    ),
)
@_options
@click.option(
    "--job-handle",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="JSON handle returned by submit.",
)
@click.option(
    "--yes", is_flag=True, required=True, help="Acknowledge cancelling this job."
)
def compute_cancel(profile, config, job_handle, yes):
    """Request cancellation; query status separately to confirm completion."""
    try:
        client = _client(profile, config)
        job = _handle(job_handle)
        client.cancel(job)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "job": asdict(job),
                "cancellation_acknowledged": True,
                "terminal_state": "not_observed",
            }
        )
    )
