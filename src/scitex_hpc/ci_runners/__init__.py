"""Durable, deterministic self-hosted GitHub Actions runner fleet on SLURM.

Background (root cause, 2026-06-25)
-----------------------------------
72 GitHub Actions self-hosted runners (one per SciTeX package plus a
handful of helpers) lived under
``/data/gpfs/projects/punim0264/ywatanabe/ci/actions-runner-<name>/``
on Spartan and were started, by a pile of ad-hoc ``~`` band-aid scripts,
**directly on a shared login node** (or borrowed onto unrelated holder
jobs via ``srun --overlap``). A login node carrying 61 users at load
10-16 cannot sustain 72 long-poll HTTPS connections: the fleet logged
4000-5000 ``HTTP request timed out`` errors/day and finally mass-died at
05:23 when one process took a ``Bus error (core dumped)``.

The fix (this package)
----------------------
A **dedicated, long-walltime CPU allocation** that hosts the whole fleet
on ONE compute node, each runner wrapped in a keep-alive loop that
auto-restarts ``run.sh`` if it exits. No login-node compute, no borrowed
holder jobs. The allocation is booked through the existing
:class:`scitex_hpc.Reservation` primitive with ``persistent=True`` so it
auto-resubmits before walltime (SIGUSR1 trap) — the fleet survives the
cluster's walltime cap indefinitely.

A cron-driven **health monitor** then scans the fleet, restarts dead
runners in place, and *alarms the operator* (explicit feedback, never
fire-and-forget) when a runner cannot be revived or the whole allocation
is gone.

This subpackage is **pure string/plan generation plus thin SSH calls**:
it emits the supervisor sbatch body and the monitor script, and books /
inspects the allocation. It never kills a live runner and never submits
on import — the operator drives deployment explicitly (see the package
README and the ``scitex-hpc ci-runners`` CLI group).

No cluster names are baked in; Spartan-specific values (partition, QOS,
account, CI base dir) are passed in by the operator or resolved from the
SciTeX config cascade, exactly like the rest of ``scitex-hpc``.
"""

from __future__ import annotations

from ._fleet import (
    DEFAULT_DIAG_KEEP,
    DEFAULT_DIAG_PRUNE_INTERVAL_SECONDS,
    DEFAULT_RESTART_BACKOFF_SECONDS,
    RUNNER_DIR_PREFIX,
    RUNNER_DIR_PREFIXES,
    FleetSpec,
    RunnerSpec,
    parse_runner_dirs,
)
from ._monitor import build_monitor_script
from ._overlap import (
    build_exec_supervisor_script,
    build_overlap_srun_command,
    build_write_body_command,
)
from ._register import (
    DEFAULT_RUNNER_LABELS,
    REQUIRED_LABEL,
    build_register_command,
    missing_required_labels,
    normalize_labels,
)
from ._supervisor import (
    build_supervisor_hold_body,
    diag_pruner_fragment,
    runner_keepalive_fragment,
)

__all__ = [
    "DEFAULT_DIAG_KEEP",
    "DEFAULT_DIAG_PRUNE_INTERVAL_SECONDS",
    "DEFAULT_RESTART_BACKOFF_SECONDS",
    "DEFAULT_RUNNER_LABELS",
    "REQUIRED_LABEL",
    "RUNNER_DIR_PREFIX",
    "RUNNER_DIR_PREFIXES",
    "FleetSpec",
    "RunnerSpec",
    "build_exec_supervisor_script",
    "build_monitor_script",
    "build_overlap_srun_command",
    "build_register_command",
    "build_supervisor_hold_body",
    "build_write_body_command",
    "diag_pruner_fragment",
    "missing_required_labels",
    "normalize_labels",
    "parse_runner_dirs",
    "runner_keepalive_fragment",
]
