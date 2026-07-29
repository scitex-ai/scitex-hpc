"""Lease creation verbs: ``book`` and ``adopt``."""

from __future__ import annotations

import json as _json
import sys

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand

from ..._config import JobConfig
from ..._reservation import Reservation

from ._group import _serialize, lease


@lease.command(
    "book",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Submit a hold-job and wait for SLURM allocation.",
        description=(
            "NAMING CONVENTION for NAME — encodes the shape so any operator "
            "can read an allocation without re-discovering it:\n"
            "  CPU-only : <cluster>-cpu-<cores>-cores-<ram_gb>-ram\n"
            "             e.g. spartan-cpu-64-cores-256-ram\n"
            "  GPU      : <cluster>-gpu-<cores>-cores-<ram_gb>-ram"
            "-<vram_gb>-vram-<gputype>\n"
            "             e.g. spartan-gpu-16-cores-128-ram-80-vram-h100\n"
            "Suffix the GPU type so similar-shape allocations on different "
            "GPU classes cannot collide; for multiple GPUs use -NxTYPE "
            "(e.g. ...-80-vram-4xh100). Always embed the cluster prefix so "
            "multi-cluster operators do not collide on one lease id.\n\n"
            "SPARTAN GOTCHAS (learned the hard way):\n"
            "  * --gpus is CASE-SENSITIVE on Spartan: use UPPERCASE H100:1 / "
            "A100:1. Lowercase fails with 'Requested node configuration is "
            "not available'.\n"
            "  * Per-GPU caps on shared nodes: gpu-a100 (32 cores/512GB/4 "
            "A100) allows max 8 cores + 128GB per A100; gpu-h100 (64 "
            "cores/1TB/4 H100) allows max 16 cores + ~256GB per H100. "
            "Asking above these for a 1-GPU job is rejected.\n"
            "  * QOS by partition (account=punim2354): cascade/sapphire -> "
            "publiccpu, gpu-a100 -> publicgpu, gpu-h100 -> feit."
        ),
        examples=(
            Example(
                "{prog} lease book spartan-cpu-64-cores-256-ram "
                "--partition cascade --cpus 64 --mem 256G --time 7-0 "
                "--account punim2354 --qos publiccpu --persistent",
                "VERIFIED on Spartan — CPU, cascade (64 cores/256GB/7d).",
            ),
            Example(
                "{prog} lease book spartan-cpu-64-cores-128-ram "
                "--partition sapphire --cpus 64 --mem 128G --time 7-0 "
                "--account punim2354 --qos publiccpu --persistent",
                "VERIFIED — CPU, sapphire (64 cores/128GB/7d).",
            ),
            Example(
                "{prog} lease book spartan-gpu-16-cores-128-ram-80-vram-h100 "
                "--partition gpu-h100 --cpus 16 --mem 128G --gpus H100:1 "
                "--time 7-0 --account punim2354 --qos feit --persistent",
                "VERIFIED — 1x H100 (16 cores/128GB/7d).",
            ),
            Example(
                "{prog} lease book spartan-gpu-8-cores-128-ram-80-vram-a100 "
                "--partition gpu-a100 --cpus 8 --mem 128G --gpus A100:1 "
                "--time 7-0 --account punim2354 --qos publicgpu --persistent",
                "VERIFIED — 1x A100 (8 cores/128GB/7d).",
            ),
        ),
    ),
)
@click.argument("name")
@click.option(
    "--host",
    default=None,
    help=(
        "SSH host to submit sbatch from (e.g. spartan). Optional — "
        "falls back to $SCITEX_HPC_HOST or "
        "~/.scitex/hpc/config.yaml's `host:` if unset, so an operator "
        "with a single cluster doesn't need to pass this every time."
    ),
)
@click.option("--partition", default=None)
@click.option("--cpus", type=int, default=None)
@click.option("--time", "time_", default=None, help="walltime, e.g. 7-0 or 01:00:00")
@click.option("--mem", default=None)
@click.option(
    "--nodelist",
    default=None,
    metavar="NODE",
    help=(
        "Pin the allocation to a specific node (e.g. spartan-bm198). "
        "SLURM will wait for the named node to free up rather than "
        "scheduling elsewhere."
    ),
)
@click.option(
    "--account",
    default=None,
    help="SLURM account / project to bill (e.g. punim2354).",
)
@click.option("--qos", default=None, help="SLURM QOS tier (e.g. publiccpu).")
@click.option(
    "--gpus",
    default=None,
    metavar="SPEC",
    help=(
        "Request GPUs. Pass-through to SLURM's --gpus=<SPEC>. "
        "Examples: '1' (any 1 GPU), 'a100:2' (two A100s), 'h100:4'. "
        "Omit for CPU-only allocations."
    ),
)
@click.option(
    "--persistent",
    is_flag=True,
    help="walltime auto-resubmit via SIGUSR1 (Phase 2).",
)
@click.option(
    "--hold-body",
    default=None,
    help="Custom sbatch script body (default: tail -f /dev/null).",
)
@click.option(
    "--tmux-server",
    default=None,
    metavar="SOCKET",
    help=(
        "Bootstrap a long-lived tmux server with this socket name as the "
        "job's PID 1. Required for scitex-agent-container's slurm-tenant "
        "runtime. Example: --tmux-server sac"
    ),
)
@click.option("--poll-timeout", type=float, default=300.0)
@click.option("--poll-interval", type=float, default=2.0)
@click.option("--dry-run", is_flag=True, help="Print plan without sbatch'ing.")
@click.option("-y", "--yes", "yes", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def book_cmd(
    name,
    host,
    partition,
    cpus,
    time_,
    mem,
    nodelist,
    account,
    qos,
    gpus,
    persistent,
    hold_body,
    tmux_server,
    poll_timeout,
    poll_interval,
    dry_run,
    yes,
    as_json,
):
    del yes
    cfg = JobConfig(
        project=name,
        host=host,
        partition=partition,
        cpus=cpus,
        time=time_,
        mem=mem,
        nodelist=nodelist,
        account=account,
        qos=qos,
        gpus=gpus,
        job_name=name,
    )
    if dry_run:
        plan = {
            "would_book": name,
            "config": {
                "host": cfg.host,
                "partition": cfg.partition,
                "cpus": cfg.cpus,
                "time": cfg.time,
                "mem": cfg.mem,
                "nodelist": cfg.nodelist,
                "account": cfg.account,
                "qos": cfg.qos,
                "gpus": cfg.gpus,
            },
            "persistent": persistent,
            "tmux_server": tmux_server,
        }
        click.echo(_json.dumps(plan, indent=2))
        return
    res = Reservation.book(
        cfg,
        persistent=persistent,
        hold_body=hold_body,
        tmux_server=tmux_server,
        poll_timeout=poll_timeout,
        poll_interval=poll_interval,
    )
    if as_json:
        click.echo(_json.dumps(_serialize(res), indent=2))
    else:
        click.echo(f"booked: id={res.id} job={res.job_id} node={res.node}")


@lease.command(
    "adopt",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary=(
            "Register an EXISTING running SLURM job as a reservation "
            "(no sbatch)."
        ),
        description=(
            "Writes the SAME lease state `book` writes, but adopts a job "
            "already running instead of submitting a new one — use it to "
            "bring an ad-hoc or externally-submitted hold-job under "
            "reservation management WITHOUT requesting a new node. "
            "Afterwards `lease get NAME` and `lease refresh NAME` work "
            "normally; refresh re-discovers the job_id by NAME via squeue, "
            "so it survives a future re-key or resubmit.\n\n"
            "--persistent only MARKS the lease persistent. It does NOT (and "
            "cannot) add a SIGUSR1 walltime auto-resubmit trap to an "
            "already-running ad-hoc job — that trap is installed only by "
            "`book --persistent` at sbatch time. At walltime the adopted job "
            "ends and one fresh node must be re-booked.\n\n"
            "Refuses to overwrite an existing lease of the same id; cancel "
            "it first if you mean to re-adopt a different job under that "
            "name."
        ),
        examples=(
            Example(
                "{prog} lease adopt spartan-ci-runner-permanent "
                "--job-id 26332626 --host spartan --persistent",
                "Adopt the long-running CI lease so it is refresh-tracked "
                "rather than re-booked.",
            ),
        ),
    ),
)
@click.argument("name")
@click.option(
    "--job-id",
    "job_id",
    required=True,
    help="SLURM job id of the ALREADY-RUNNING job to register (from squeue).",
)
@click.option(
    "--host",
    default=None,
    help=(
        "SSH host the job runs on (e.g. spartan). Optional — falls back to "
        "$SCITEX_HPC_HOST or ~/.scitex/hpc/config.yaml's `host:` if unset."
    ),
)
@click.option(
    "--persistent",
    is_flag=True,
    help=(
        "MARK the adopted lease persistent so the solver tracks it as a "
        "long-lived allocation. NOTE: adopt canNOT retro-fit a SIGUSR1 "
        "walltime auto-resubmit trap onto an already-running ad-hoc job "
        "(that trap can only be installed at sbatch time by `book "
        "--persistent`). The flag only sets the metadata; at walltime the "
        "job ends and the solver re-books a fresh node — the one unavoidable "
        "future node. Until then, `ensure` refresh-tracks this lease instead "
        "of requesting a new node."
    ),
)
@click.option(
    "--no-refresh-node",
    "no_refresh_node",
    is_flag=True,
    help="Skip the one-time squeue probe that fills in the compute node.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
@click.pass_context
def adopt_cmd(ctx, name, job_id, host, persistent, no_refresh_node, as_json):
    # Resolve host via the same cascade as ``book`` (direct → $SCITEX_HPC_HOST
    # → user config) so ``--host`` stays optional for single-cluster operators.
    resolved_host = JobConfig(project=name, host=host).resolve("host")
    try:
        res = Reservation.from_jobid(
            host=resolved_host,
            job_id=job_id,
            name=name,
            persistent=persistent,
            refresh_node=not no_refresh_node,
        )
    except FileExistsError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx.exit(1)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx.exit(2)
    if as_json:
        click.echo(_json.dumps(_serialize(res), indent=2))
    else:
        click.echo(f"adopted: id={res.id} job={res.job_id} node={res.node or '-'}")
