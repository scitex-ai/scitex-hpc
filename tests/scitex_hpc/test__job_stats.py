"""Tests for scitex_hpc._job_stats.

Pure-parser tests over REAL captured ``sacct --parsable2`` output (Spartan
job 26778282, a TIMEOUT run near its memory + walltime limits, and array job
26820686). No mocks: the network wrapper ``job_stats`` is thin; everything
worth testing is the pure parse + derive layer.
"""

from __future__ import annotations

from scitex_hpc._job_stats import (
    _derive_signals,
    _duration_to_secs,
    _mem_to_bytes,
    _parse_sacct_stats,
)

# Real sacct output: a single job that hit TIMEOUT with MaxRSS ~= ReqMem.
_TIMEOUT_JOB = (
    "JobID|JobName|State|ExitCode|Elapsed|TotalCPU|MaxRSS|MaxDiskRead|"
    "MaxDiskWrite|ReqMem|Timelimit\n"
    "26778282|qwen-h100-cutover|TIMEOUT|0:0|1-00:00:29|05:51:32||||128G|"
    "1-00:00:00\n"
    "26778282.batch|batch|CANCELLED|0:15|1-00:00:30|05:51:32|134193604K|"
    "50106.86M|65763.77M||\n"
    "26778282.extern|extern|COMPLETED|0:0|1-00:00:31|00:00:00|3096K|0.67M|"
    "0.01M||\n"
)

# Real array-task values, laid out in the full requested column format.
_ARRAY_JOB = (
    "JobID|JobName|State|ExitCode|Elapsed|TotalCPU|MaxRSS|MaxDiskRead|"
    "MaxDiskWrite|ReqMem|Timelimit\n"
    "26820686_201|pac_rc_feit_005|COMPLETED|0:0|00:00:54|00:00:30||||16G|"
    "00:05:00\n"
    "26820686_201.batch|batch|COMPLETED|0:0|00:00:54|00:00:30|2721644K|1.00M|"
    "0.50M||\n"
    "26820686_202|pac_rc_feit_005|COMPLETED|0:0|00:01:07|00:00:31||||16G|"
    "00:05:00\n"
    "26820686_202.batch|batch|COMPLETED|0:0|00:01:07|00:00:31|2722644K|1.00M|"
    "0.50M||\n"
)

_HEADER_ONLY = (
    "JobID|JobName|State|ExitCode|Elapsed|TotalCPU|MaxRSS|MaxDiskRead|"
    "MaxDiskWrite|ReqMem|Timelimit\n"
)


# ---------------------------------------------------------------------------
# _mem_to_bytes
# ---------------------------------------------------------------------------


def test_mem_to_bytes_parses_kilobytes():
    # Arrange
    value = "134193604K"
    # Act
    result = _mem_to_bytes(value)
    # Assert
    assert result == 134193604 * 1024


def test_mem_to_bytes_parses_gigabytes():
    # Arrange
    value = "128G"
    # Act
    result = _mem_to_bytes(value)
    # Assert
    assert result == 128 * 1024**3


def test_mem_to_bytes_strips_per_cpu_suffix():
    # Arrange
    value = "4Gc"
    # Act
    result = _mem_to_bytes(value)
    # Assert
    assert result == 4 * 1024**3


def test_mem_to_bytes_returns_none_for_empty():
    # Arrange
    value = ""
    # Act
    result = _mem_to_bytes(value)
    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# _duration_to_secs
# ---------------------------------------------------------------------------


def test_duration_to_secs_parses_day_hms():
    # Arrange
    value = "1-00:00:29"
    # Act
    result = _duration_to_secs(value)
    # Assert
    assert result == 86429


def test_duration_to_secs_parses_hms():
    # Arrange
    value = "05:51:32"
    # Act
    result = _duration_to_secs(value)
    # Assert
    assert result == 5 * 3600 + 51 * 60 + 32


def test_duration_to_secs_parses_mm_ss():
    # Arrange
    value = "00:00:54"
    # Act
    result = _duration_to_secs(value)
    # Assert
    assert result == 54


def test_duration_to_secs_returns_none_for_unlimited():
    # Arrange
    value = "UNLIMITED"
    # Act
    result = _duration_to_secs(value)
    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# _parse_sacct_stats — merge + array handling
# ---------------------------------------------------------------------------


def test_parse_sacct_returns_empty_for_header_only():
    # Arrange
    stdout = _HEADER_ONLY
    # Act
    result = _parse_sacct_stats(stdout)
    # Assert
    assert result == []


def test_parse_sacct_merges_maxrss_from_batch_step():
    # Arrange
    stdout = _TIMEOUT_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["max_rss_bytes"] == 134193604 * 1024


def test_parse_sacct_takes_state_from_main_row():
    # Arrange
    stdout = _TIMEOUT_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["state"] == "TIMEOUT"


def test_parse_sacct_takes_reqmem_from_main_row():
    # Arrange
    stdout = _TIMEOUT_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["req_mem"] == "128G"


def test_parse_sacct_flags_timed_out():
    # Arrange
    stdout = _TIMEOUT_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["timed_out"] is True


def test_parse_sacct_flags_walltime_tight():
    # Arrange
    stdout = _TIMEOUT_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["walltime_tight"] is True


def test_parse_sacct_flags_mem_tight_near_reqmem():
    # Arrange
    stdout = _TIMEOUT_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["mem_tight"] is True


def test_parse_sacct_keeps_array_tasks_distinct():
    # Arrange
    stdout = _ARRAY_JOB
    # Act
    job_ids = [r["job_id"] for r in _parse_sacct_stats(stdout)]
    # Assert
    assert job_ids == ["26820686_201", "26820686_202"]


def test_parse_sacct_array_task_not_mem_tight():
    # Arrange
    stdout = _ARRAY_JOB
    # Act
    record = _parse_sacct_stats(stdout)[0]
    # Assert
    assert record["mem_tight"] is False


# ---------------------------------------------------------------------------
# _derive_signals — OOM
# ---------------------------------------------------------------------------


def test_derive_signals_flags_oom_killed():
    # Arrange
    record = {"state": "OUT_OF_MEMORY", "req_mem": "16G", "max_rss_bytes": None}
    # Act
    signals = _derive_signals(record)
    # Assert
    assert signals["oom_killed"] is True
