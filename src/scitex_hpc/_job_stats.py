"""Per-job (and per-array-task) resource report derived from sacct.

Sibling of :func:`scitex_hpc._results.poll_job`: where ``poll_job`` returns a
one-line state check, ``job_stats`` returns a full per-job resource report --
elapsed vs walltime, MaxRSS vs ReqMem, CPU time, disk IO -- plus derived
signals (memory-tight / OOM / walltime-tight) for post-run cohort analysis.

Cluster-agnostic: plain SLURM ``sacct`` only. No ``seff`` / acct_gather
profiling dependency (``seff`` is not installed on every cluster, e.g. Spartan).
"""

from __future__ import annotations

from scitex_ssh import exec_remote

from ._config import JobConfig

_SACCT_FORMAT = (
    "JobID,JobName,State,ExitCode,Elapsed,TotalCPU,"
    "MaxRSS,MaxDiskRead,MaxDiskWrite,ReqMem,Timelimit"
)

_UNIT_BYTES = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}


def _mem_to_bytes(value: str) -> int | None:
    """Parse a SLURM memory string to bytes.

    Handles sacct MaxRSS forms (``134193604K``, ``50106.86M``) and ReqMem
    forms (``128G``, plus older per-cpu / per-node ``4Gc`` / ``2Gn`` suffixes).
    Returns None for empty / unparseable input.
    """
    v = (value or "").strip().rstrip("cn")  # drop per-cpu / per-node suffix
    if not v:
        return None
    unit = v[-1].upper()
    if unit in _UNIT_BYTES:
        try:
            return int(float(v[:-1]) * _UNIT_BYTES[unit])
        except ValueError:
            return None
    try:
        return int(float(v))  # bare bytes
    except ValueError:
        return None


def _duration_to_secs(value: str) -> int | None:
    """Parse a SLURM duration to seconds.

    Handles ``MM:SS``, ``HH:MM:SS`` and ``D-HH:MM:SS`` (e.g. ``1-00:00:29``).
    Returns None for ``UNLIMITED`` / ``Partition_Limit`` / empty.
    """
    v = (value or "").strip()
    if not v or not v[0].isdigit():
        return None
    days = 0
    if "-" in v:
        d, _, v = v.partition("-")
        days = int(d)
    try:
        nums = [int(float(p)) for p in v.split(":")]
    except ValueError:
        return None
    if len(nums) == 3:
        h, m, s = nums
    elif len(nums) == 2:
        h, m, s = 0, nums[0], nums[1]
    elif len(nums) == 1:
        h, m, s = 0, 0, nums[0]
    else:
        return None
    return days * 86400 + h * 3600 + m * 60 + s


def _derive_signals(rec: dict) -> dict:
    """Compute memory / walltime efficiency + failure signals from a record."""
    req = _mem_to_bytes(rec.get("req_mem", ""))
    rss = rec.get("max_rss_bytes")
    mem_ratio = round(rss / req, 3) if req and rss else None
    elapsed_s = _duration_to_secs(rec.get("elapsed", ""))
    limit_s = _duration_to_secs(rec.get("timelimit", ""))
    wall_ratio = (
        round(elapsed_s / limit_s, 3)
        if limit_s and elapsed_s is not None
        else None
    )
    state = rec.get("state", "")
    return {
        "mem_ratio": mem_ratio,
        "walltime_ratio": wall_ratio,
        "oom_killed": state == "OUT_OF_MEMORY",
        "timed_out": state == "TIMEOUT",
        "mem_tight": mem_ratio is not None and mem_ratio >= 0.9,
        "walltime_tight": (wall_ratio is not None and wall_ratio >= 0.95)
        or state == "TIMEOUT",
    }


def _merge_group(base: str, rows: list[dict]) -> dict:
    """Merge a job's main row + sub-steps into one record + derived signals.

    Resource peaks (MaxRSS, MaxDisk*) live on the ``.batch`` / ``.extern``
    sub-steps while State / ReqMem / Timelimit live on the main row, so take
    each job-level field from the main row and the max peak across all rows.
    """
    main = next((r for r in rows if r.get("JobID") == base), rows[0])
    peak = {
        key: max(
            (_mem_to_bytes(r.get(col, "")) or 0 for r in rows), default=0
        )
        for key, col in (
            ("max_rss_bytes", "MaxRSS"),
            ("max_disk_read_bytes", "MaxDiskRead"),
            ("max_disk_write_bytes", "MaxDiskWrite"),
        )
    }
    rec = {
        "job_id": base,
        "job_name": main.get("JobName", "").strip(),
        "state": main.get("State", "").strip(),
        "exit_code": (main.get("ExitCode", "").strip() or None),
        "elapsed": main.get("Elapsed", "").strip(),
        "total_cpu": main.get("TotalCPU", "").strip(),
        "req_mem": main.get("ReqMem", "").strip(),
        "timelimit": main.get("Timelimit", "").strip(),
        **{k: (v or None) for k, v in peak.items()},
    }
    rec.update(_derive_signals(rec))
    return rec


def _parse_sacct_stats(stdout: str) -> list[dict]:
    """Parse ``sacct --parsable2`` output into one merged record per job.

    One record per base JobID; array tasks (``<jobid>_<taskid>``) stay
    distinct. Empty list if there is no data (header only / unknown job).
    """
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    header = lines[0].split("|")
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for ln in lines[1:]:
        row = dict(zip(header, ln.split("|")))
        base = row.get("JobID", "").split(".")[0]
        if not base:
            continue
        if base not in groups:
            groups[base] = []
            order.append(base)
        groups[base].append(row)
    return [_merge_group(base, groups[base]) for base in order]


def job_stats(config: JobConfig, job_id: str) -> dict:
    """Return a per-job (and per-array-task) resource report from sacct.

    Sibling of :func:`scitex_hpc.poll_job`: where ``poll_job`` is a one-line
    state probe, ``job_stats`` returns ``{"jobs": [<record>, ...]}`` with one
    record per base JobID (array tasks distinct), each carrying ``elapsed`` /
    ``timelimit`` / ``max_rss_bytes`` / ``req_mem`` / disk IO plus derived
    signals: ``mem_ratio``, ``walltime_ratio``, ``oom_killed``, ``timed_out``,
    ``mem_tight`` (MaxRSS/ReqMem >= 0.9), ``walltime_tight`` (Elapsed/Timelimit
    >= 0.95 or TIMEOUT). Empty ``{"jobs": []}`` if sacct doesn't know the job.
    """
    host = config.resolve("host")
    cmd = f"sacct -j {job_id} --format={_SACCT_FORMAT} --parsable2"
    result = exec_remote(host, f"bash -lc '{cmd}'")
    return {"jobs": _parse_sacct_stats(result.stdout or "")}
