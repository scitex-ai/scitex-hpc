"""Batch compute facade over existing SSH transport and two scheduler CLIs."""

from __future__ import annotations

import re
import shlex
import uuid

from scitex_ssh import exec_remote

from ._models import BatchRequest, HostProfile, JobHandle, JobState, JobStatus
from ._plan import SubmissionPlan, login_command, plan_job
from ._states import (
    grid_engine_accounting,
    grid_engine_queue,
    slurm_accounting,
    slurm_queue,
)


class SubmissionError(RuntimeError):
    """A submission was refused or its outcome is unknown; never auto-retry."""

    def __init__(self, message: str, *, outcome: str, name: str):
        super().__init__(f"{message} (outcome={outcome}, job_name={name})")
        self.outcome, self.name = outcome, name


class ComputeClient:
    """Single-node batch lifecycle with explicit host/scheduler selection.

    Does not modify legacy Slurm reservations, stage files, read credentials,
    auto-resubmit, or claim site admission. The runner injection uses the
    existing scitex-ssh exec_remote signature and is useful for offline tests.
    """

    def __init__(self, profile: HostProfile, *, runner=None):
        self.profile = profile
        self._runner = runner if runner is not None else exec_remote

    def capabilities(self) -> dict:
        return {
            "scheduler": self.profile.scheduler,
            "dialect": self.profile.dialect,
            "batch": True,
            "status": True,
            "cancel": True,
            "plan": True,
            "interactive": False,
            "arrays": False,
            "mpi": False,
            "allocation_reuse": False,
            "renewal": False,
            "log_retrieval": False,
            "result_retrieval": False,
            "site_admission": "not_probed",
        }

    def plan(self, spec: BatchRequest, *, name: str | None = None) -> SubmissionPlan:
        return plan_job(
            self.profile, spec, name=name or "scitex-" + uuid.uuid4().hex[:20]
        )

    def submit(self, spec: BatchRequest, *, name: str | None = None) -> JobHandle:
        plan = self.plan(spec, name=name)
        try:
            result = self._runner(plan.host, plan.command)
        except Exception as exc:
            raise SubmissionError(
                "Submission transport failed; reconcile the job name before retrying",
                outcome="unknown",
                name=plan.name,
            ) from exc
        if result.returncode:
            outcome = (
                "unknown"
                if result.returncode < 0 or result.returncode >= 128
                else "rejected"
            )
            raise SubmissionError(
                "Submission did not return success; inspect the scheduler before retrying",
                outcome=outcome,
                name=plan.name,
            )
        lines = (result.stdout or "").strip().splitlines()
        response = lines[-1].strip() if lines else ""
        pattern = (
            r"([1-9][0-9]*)(?:;([A-Za-z0-9][A-Za-z0-9_.-]{0,127}))?"
            if plan.scheduler == "slurm"
            else r"([1-9][0-9]*)"
        )
        match = re.fullmatch(pattern, response)
        if not match:
            raise SubmissionError(
                "Submission may have succeeded but returned no supported job ID; do not blindly retry",
                outcome="unknown",
                name=plan.name,
            )
        cluster = match.group(2) if plan.scheduler == "slurm" else None
        return JobHandle(plan.host, plan.scheduler, match.group(1), cluster)

    def _check_handle(self, job: JobHandle) -> None:
        if job.host != self.profile.host or job.scheduler != self.profile.scheduler:
            raise ValueError("Job handle belongs to another host or scheduler")

    def status(self, job: JobHandle) -> JobStatus:
        self._check_handle(job)
        if job.scheduler == "slurm":
            queue = [
                "squeue",
                "--noheader",
                "--jobs",
                job.native_id,
                "--format=%i|%T|%R",
            ]
            accounting = [
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs",
                job.native_id,
                "--format=JobIDRaw,State,ExitCode",
            ]
            read_queue, read_accounting = slurm_queue, slurm_accounting
            if job.cluster:
                queue.append(f"--clusters={job.cluster}")
                accounting.append(f"--clusters={job.cluster}")
        else:
            queue = ["qstat", "-xml"]
            accounting = ["qacct", "-j", job.native_id]
            read_queue, read_accounting = grid_engine_queue, grid_engine_accounting
        try:
            result = self._runner(job.host, login_command(shlex.join(queue)))
            if result.returncode:
                return JobStatus(JobState.UNKNOWN, reason="Queue query failed")
            observed = read_queue(result.stdout or "", job.native_id)
            if observed is not None:
                return observed
            result = self._runner(job.host, login_command(shlex.join(accounting)))
            if result.returncode:
                return JobStatus(
                    JobState.UNKNOWN,
                    reason="Accounting query failed or is not yet available",
                )
            return read_accounting(result.stdout or "", job.native_id)
        except Exception:
            return JobStatus(
                JobState.UNKNOWN, reason="Status transport or parsing failed"
            )

    def cancel(self, job: JobHandle) -> None:
        """Request cancellation; return does not certify terminal job state."""
        self._check_handle(job)
        executable = "scancel" if job.scheduler == "slurm" else "qdel"
        args = [executable, job.native_id]
        if job.cluster:
            args.append(f"--clusters={job.cluster}")
        result = self._runner(job.host, login_command(shlex.join(args)))
        if result.returncode:
            raise RuntimeError(
                "Cancellation was not acknowledged; query job status before retrying"
            )
