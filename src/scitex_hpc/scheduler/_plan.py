"""Pure scheduler command generation: no SSH, files, or submissions."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ._models import BatchRequest, HostProfile, identifier


def path_argument(path: str) -> str:
    # Preserve home expansion without evaluating characters in the path.
    return (
        '"$HOME"/' + shlex.quote(path[2:])
        if path.startswith("~/")
        else shlex.quote(path)
    )


def login_command(command: str) -> str:
    return "bash -lc " + shlex.quote(command)


@dataclass(frozen=True)
class SubmissionPlan:
    host: str
    scheduler: str
    name: str
    command: str
    requested: dict[str, int]
    planned: dict[str, int]
    warnings: tuple[str, ...]
    stdout_path: str
    stderr_path: str
    billing_account: str | None
    resource_type: str | None
    allocation_observed: bool = False
    dialect: str | None = None


def plan_job(profile: HostProfile, spec: BatchRequest, *, name: str) -> SubmissionPlan:
    """Resolve a single-node batch plan without consuming cluster resources."""
    identifier(name, "job name")
    if "$" in spec.working_directory or "%" in spec.working_directory:
        raise ValueError(
            "Scheduler log paths do not support '$' or '%' in working_directory"
        )
    if profile.scheduler == "grid-engine" and any(
        separator in spec.working_directory for separator in (",", ":")
    ):
        raise ValueError(
            "Grid Engine log paths do not support ',' or ':' in working_directory"
        )
    if (
        profile.max_walltime_seconds
        and spec.walltime_seconds > profile.max_walltime_seconds
    ):
        raise ValueError("requested walltime exceeds this profile's declared limit")
    requested = {key: getattr(spec, key) for key in ("cpus", "memory_mib", "gpus")}
    allocated = dict(requested)
    warnings = []
    hours, remainder = divmod(spec.walltime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    walltime = f"{hours:02}:{minutes:02}:{seconds:02}"
    base = spec.working_directory.rstrip("/") + "/.scitex-hpc/logs"
    if profile.scheduler == "slurm":
        days, day_hours = divmod(hours, 24)
        if days:
            walltime = f"{days}-{day_hours:02}:{minutes:02}:{seconds:02}"
        stdout, stderr = f"{base}/{name}-%j.out", f"{base}/{name}-%j.err"
        args = [
            "sbatch",
            "--parsable",
            "--nodes=1",
            "--ntasks=1",
            f"--job-name={name}",
            f"--cpus-per-task={spec.cpus}",
            f"--mem={spec.memory_mib}M",
            f"--time={walltime}",
        ]
        if profile.account:
            args.append(f"--account={profile.account}")
        if profile.partition:
            args.append(f"--partition={profile.partition}")
        if spec.gpus:
            args.append(f"--gpus={spec.gpus}")
    else:
        bundle = profile.bundle
        assert bundle is not None  # HostProfile validates the backend contract.
        allocated = {key: getattr(bundle, key) for key in requested}
        if any(requested[k] > allocated[k] for k in requested):
            raise ValueError(
                "request exceeds the explicitly selected Grid Engine resource bundle"
            )
        if allocated != requested:
            warnings.append(
                "The configured resource bundle allocates more than the requested minima; review usage and site charges."
            )
        stdout, stderr = f"{base}/{name}.$JOB_ID.out", f"{base}/{name}.$JOB_ID.err"
        args = [
            "qsub",
            "-clear",
            "-terse",
            "-C",
            "",
            "-S",
            "/bin/bash",
            "-cwd",
            "-N",
            name,
            "-g",
            profile.account,
            "-l",
            f"{bundle.resource_type}=1",
            "-l",
            f"h_rt={walltime}",
        ]
    # Redirection paths may contain spaces; scheduler arguments are individually
    # quoted. No workload content is ever rendered into #SBATCH/#$ directives.
    script = (
        "#!/bin/bash\nset -o pipefail\ncd -- "
        + path_argument(spec.working_directory)
        + " || exit 125\n"
    )
    if profile.module_init:
        script += "source " + path_argument(profile.module_init) + " || exit 125\n"
    if profile.modules:
        script += "type module >/dev/null 2>&1 || exit 125\n"
        script += "module load " + shlex.join(profile.modules) + " || exit 125\n"
    script += "exec -- " + shlex.join(spec.argv) + "\n"
    cwd, logs = path_argument(spec.working_directory), path_argument(base)
    output_flag, error_flag = (
        ("--output", "--error") if profile.scheduler == "slurm" else ("-o", "-e")
    )
    # Home-relative paths must be expanded by the remote login shell, before
    # passing them to the scheduler. JOB_ID and %j remain scheduler placeholders.
    submit = (
        shlex.join(args)
        + " "
        + output_flag
        + " "
        + path_argument(stdout)
        + " "
        + error_flag
        + " "
        + path_argument(stderr)
    )
    clear_environment = (
        'for scitex_hpc_var in "${!SBATCH_@}"; do unset "$scitex_hpc_var" || exit 125; done\n'
        if profile.scheduler == "slurm"
        else ""
    )
    command = login_command(
        clear_environment
        + f"mkdir -p -- {logs} && cd -- {cwd} && printf %s {shlex.quote(script)} | {submit}"
    )
    return SubmissionPlan(
        profile.host,
        profile.scheduler,
        name,
        command,
        requested,
        allocated,
        tuple(warnings),
        stdout,
        stderr,
        profile.account,
        profile.bundle.resource_type if profile.bundle else None,
        dialect=profile.dialect,
    )
