"""Thin FastMCP adapters for the shared scheduler-neutral Python operations."""

from __future__ import annotations

from dataclasses import asdict

from .. import scheduler as operations
from ..scheduler import BatchRequest, JobHandle, load_profile


def register_compute_tools(mcp):
    """Register on the package's existing server; never construct another one."""

    @mcp.tool()
    def compute_plan(profile: str, spec: BatchRequest) -> dict:
        """Plan a single-node batch job using a configured profile; no SSH or submission."""
        return asdict(operations.compute_plan(load_profile(profile), spec))

    @mcp.tool()
    def compute_submit(profile: str, spec: BatchRequest, confirm: bool = False) -> dict:
        """Submit once; requires confirm=true because allocation may consume billed resources."""
        if not confirm:
            raise ValueError("Explicit confirm=true is required to submit a job")
        return asdict(operations.compute_submit(load_profile(profile), spec))

    @mcp.tool()
    def compute_status(profile: str, job: JobHandle) -> dict:
        """Query a configured host; missing accounting or transport failure stays unknown."""
        return asdict(operations.compute_status(load_profile(profile), job))

    @mcp.tool()
    def compute_cancel(profile: str, job: JobHandle, confirm: bool = False) -> dict:
        """Request cancellation of this job only; confirm=true required. Terminal state is unobserved."""
        if not confirm:
            raise ValueError("Explicit confirm=true is required to cancel a job")
        operations.compute_cancel(load_profile(profile), job)
        return {
            "job": asdict(job),
            "cancellation_acknowledged": True,
            "terminal_state": "not_observed",
        }
