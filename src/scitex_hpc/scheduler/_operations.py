"""Functional Python entry points for the same typed batch lifecycle."""

from __future__ import annotations

from ._client import ComputeClient
from ._models import BatchRequest, HostProfile, JobHandle, JobStatus
from ._plan import SubmissionPlan


def compute_plan(
    profile: HostProfile, spec: BatchRequest, *, name: str | None = None
) -> SubmissionPlan:
    """Resolve a batch plan without connecting to a host or submitting work."""
    return ComputeClient(profile).plan(spec, name=name)


def compute_submit(
    profile: HostProfile, spec: BatchRequest, *, name: str | None = None, runner=None
) -> JobHandle:
    """Submit once; return a domain handle, never a transport JSON envelope."""
    return ComputeClient(profile, runner=runner).submit(spec, name=name)


def compute_status(profile: HostProfile, job: JobHandle, *, runner=None) -> JobStatus:
    """Observe normalized state and original accounting/exit evidence."""
    return ComputeClient(profile, runner=runner).status(job)


def compute_cancel(profile: HostProfile, job: JobHandle, *, runner=None) -> None:
    """Request cancellation of the identified job without automatic retry."""
    ComputeClient(profile, runner=runner).cancel(job)
