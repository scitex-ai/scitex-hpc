"""Conservative scheduler state interpretation; absent evidence stays unknown."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ._models import JobState, JobStatus

_SLURM = {
    "PENDING": JobState.QUEUED,
    "CONFIGURING": JobState.QUEUED,
    "RUNNING": JobState.RUNNING,
    "COMPLETING": JobState.RUNNING,
    "COMPLETED": JobState.SUCCEEDED,
    "FAILED": JobState.FAILED,
    "TIMEOUT": JobState.FAILED,
    "OUT_OF_MEMORY": JobState.FAILED,
    "NODE_FAIL": JobState.FAILED,
    "BOOT_FAIL": JobState.FAILED,
    "CANCELLED": JobState.CANCELLED,
}


def slurm_queue(text: str, job_id: str) -> JobStatus | None:
    for line in text.splitlines():
        fields = line.split("|", 2)
        if len(fields) == 3 and fields[0].strip() == job_id:
            native = fields[1].strip()
            # Queue presence alone cannot certify terminal success.
            state = _SLURM.get(native, JobState.UNKNOWN)
            if state == JobState.SUCCEEDED:
                state = JobState.UNKNOWN
            return JobStatus(state, native, reason=fields[2].strip())
    return None


def slurm_accounting(text: str, job_id: str) -> JobStatus:
    for line in text.splitlines():
        fields = line.strip().split("|")
        if len(fields) < 3 or fields[0] != job_id:
            continue
        native = fields[1].strip()
        state = _SLURM.get(native.split()[0].rstrip("+"), JobState.UNKNOWN)
        try:
            exit_code, signal = (int(n) for n in fields[2].split(":"))
            if exit_code < 0 or signal < 0:
                raise ValueError
        except (ValueError, TypeError):
            return JobStatus(
                JobState.UNKNOWN,
                native,
                reason="Accounting exit evidence is missing or invalid",
            )
        if state == JobState.SUCCEEDED and (exit_code or signal):
            state = JobState.FAILED
        return JobStatus(state, native, exit_code, f"signal={signal}")
    return JobStatus(
        JobState.UNKNOWN,
        reason="No matching accounting record; completion is not established",
    )


def grid_engine_queue(text: str, job_id: str) -> JobStatus | None:
    if len(text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Scheduler XML exceeds the bounded status response size")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("Invalid Grid Engine queue XML") from exc
    for job in root.iter("job_list"):
        if (job.findtext("JB_job_number") or "").strip() != job_id:
            continue
        native = (job.findtext("state") or "").strip()
        if native in ("r", "t", "Rr", "Rt"):
            state = JobState.RUNNING
        elif native in ("qw", "hqw", "hRqw"):
            state = JobState.QUEUED
        else:
            state = JobState.UNKNOWN
        return JobStatus(state, native)
    return None


def grid_engine_accounting(text: str, job_id: str) -> JobStatus:
    records = re.split(r"(?m)^=+\s*$", text)
    for record in records:
        fields = {}
        for line in record.splitlines():
            pair = line.split(None, 1)
            if len(pair) == 2:
                fields[pair[0]] = pair[1].strip()
        if fields.get("jobnumber") != job_id:
            continue
        # Array accounting cannot be collapsed into one successful batch job.
        if fields.get("taskid", "undefined") not in ("undefined", "0", "NONE"):
            return JobStatus(JobState.UNKNOWN, reason="Array accounting is unsupported")
        try:
            failed = int(fields["failed"].split()[0])
            exit_code = int(fields["exit_status"])
            if min(failed, exit_code) < 0:
                raise ValueError
        except (KeyError, ValueError, IndexError):
            return JobStatus(
                JobState.UNKNOWN,
                reason="Accounting exit evidence is missing or invalid",
            )
        state = JobState.FAILED if failed or exit_code else JobState.SUCCEEDED
        return JobStatus(state, f"failed={failed}", exit_code)
    return JobStatus(
        JobState.UNKNOWN,
        reason="No matching accounting record; completion is not established",
    )
