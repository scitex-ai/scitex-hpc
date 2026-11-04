"""Public functional adapters return domain models, not MCP JSON envelopes."""

from types import SimpleNamespace

import scitex_hpc
from scitex_hpc import scheduler


def test_functional_facade_retains_canonical_leaf_operations():
    # Arrange
    names = ["compute_plan", "compute_submit", "compute_status", "compute_cancel"]
    # Act
    same = [getattr(scitex_hpc, name) is getattr(scheduler, name) for name in names]
    # Assert
    assert same == [True] * len(names)


def test_functional_batch_operations_preserve_domain_models():
    # Arrange
    profile = scheduler.HostProfile("example", "slurm")
    spec = scheduler.BatchRequest(("hostname",), "/work")
    def runner(*_):
        return SimpleNamespace(returncode=0, stdout="123\n")
    # Act
    plan = scheduler.compute_plan(profile, spec)
    job = scheduler.compute_submit(profile, spec, runner=runner)
    status = scheduler.compute_status(profile, job, runner=runner)
    cancellation = scheduler.compute_cancel(profile, job, runner=runner)
    # Assert
    assert (type(plan), type(job), type(status), cancellation) == (
        scheduler.SubmissionPlan,
        scheduler.JobHandle,
        scheduler.JobStatus,
        None,
    )
