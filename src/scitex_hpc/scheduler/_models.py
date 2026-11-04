"""Portable single-node batch requests and explicit scheduler profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath

from pydantic import ConfigDict, StrictInt


def identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise ValueError(f"{field} must be a simple nonempty identifier")
    return value


def positive(value: int, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def remote_path(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError(
            "working_directory must be a nonempty remote path without control characters"
        )
    if (
        not (value.startswith("/") or value.startswith("~/"))
        or ".." in PurePosixPath(value).parts
    ):
        raise ValueError(
            "working_directory must be absolute or home-relative, without '..'"
        )
    return value


@dataclass(frozen=True)
class ResourceBundle:
    """Operator-verified Grid Engine allocation; sizes are per bundle unit."""

    resource_type: str
    cpus: int
    memory_mib: int
    gpus: int = 0

    def __post_init__(self):
        identifier(self.resource_type, "resource_type")
        positive(self.cpus, "cpus")
        positive(self.memory_mib, "memory_mib")
        positive(self.gpus, "gpus", minimum=0)


@dataclass(frozen=True)
class HostProfile:
    """Explicit SSH alias and scheduler settings; contains no credentials.

    The supported TSUBAME Grid Engine dialect requires an account/group and
    a configured bundle. Requests
    describe resource minima; the chosen bundle is the explicit allocation
    ceiling, not an automatically selected or silently enlarged resource type.
    """

    host: str
    scheduler: str
    account: str | None = None
    partition: str | None = None
    bundle: ResourceBundle | None = None
    max_walltime_seconds: int | None = None
    module_init: str | None = None
    modules: tuple[str, ...] = ()
    dialect: str | None = None

    def __post_init__(self):
        identifier(self.host, "host SSH alias")
        if self.scheduler not in ("slurm", "grid-engine"):
            raise ValueError("scheduler must be explicitly 'slurm' or 'grid-engine'")
        for field in ("account", "partition"):
            value = getattr(self, field)
            if value is not None:
                identifier(value, field)
        if self.max_walltime_seconds is not None:
            positive(self.max_walltime_seconds, "max_walltime_seconds")
        if self.module_init is not None:
            remote_path(self.module_init)
        if not isinstance(self.modules, tuple) or any(
            not isinstance(module, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+/-]*", module)
            or ".." in module.split("/")
            for module in self.modules
        ):
            raise ValueError("modules must be a tuple of explicit module names")
        if self.scheduler == "grid-engine":
            if self.dialect != "tsubame":
                raise ValueError(
                    "Grid Engine requires dialect='tsubame'; generic Grid Engine is unsupported"
                )
            if not self.account or not isinstance(self.bundle, ResourceBundle):
                raise ValueError(
                    "Grid Engine requires an explicit billing group and resource bundle"
                )
            if self.partition is not None:
                raise ValueError(
                    "Slurm partitions cannot be translated to Grid Engine queues"
                )
        else:
            if self.bundle is not None:
                raise ValueError(
                    "Grid Engine resource bundles cannot be applied to Slurm"
                )
            if self.dialect is not None:
                raise ValueError("Slurm does not accept a Grid Engine dialect")


@dataclass(frozen=True)
class BatchRequest:
    """One process on one node; CPU/memory/GPU values are minimum resources.

    Pass an argument vector. Intentional shell scripts must explicitly request
    a shell, e.g. ('bash', '-lc', script). No argument is interpreted as a
    scheduler option or directive. Arrays, MPI and dependencies are not implied.
    """

    __pydantic_config__ = ConfigDict(extra="forbid")

    argv: tuple[str, ...]
    working_directory: str
    cpus: StrictInt = 1
    memory_mib: StrictInt = 1024
    gpus: StrictInt = 0
    walltime_seconds: StrictInt = 60

    def __post_init__(self):
        if not isinstance(self.argv, tuple) or not self.argv:
            raise ValueError("argv must be a nonempty tuple of arguments")
        if not self.argv[0] or any(
            not isinstance(a, str) or "\0" in a for a in self.argv
        ):
            raise ValueError(
                "argv must contain strings without NUL and a nonempty executable"
            )
        remote_path(self.working_directory)
        for field in ("cpus", "memory_mib", "walltime_seconds"):
            positive(getattr(self, field), field)
        positive(self.gpus, "gpus", minimum=0)


@dataclass(frozen=True)
class JobHandle:
    """A batch job identity scoped to an SSH host and scheduler."""

    __pydantic_config__ = ConfigDict(extra="forbid")

    host: str
    scheduler: str
    native_id: str
    cluster: str | None = None

    def __post_init__(self):
        identifier(self.host, "host SSH alias")
        if self.scheduler not in ("slurm", "grid-engine"):
            raise ValueError("unsupported scheduler")
        if not isinstance(self.native_id, str) or not re.fullmatch(
            r"[1-9][0-9]*", self.native_id
        ):
            raise ValueError(
                "native_id must be a positive batch job ID; array IDs are unsupported"
            )
        if self.cluster is not None:
            identifier(self.cluster, "Slurm cluster")
            if self.scheduler != "slurm":
                raise ValueError("cluster is only meaningful for Slurm job handles")


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobStatus:
    state: JobState
    native_state: str = ""
    exit_code: int | None = None
    reason: str = ""
    observed_at: str = dataclass_field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
