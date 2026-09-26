"""Tests for empirically-verified SLURM walltime limits.

Hand-rolled fake runner, no ``unittest.mock`` — matches
``tests/scitex_hpc/test__dispatch.py``'s convention. One assertion per
test (STX-TQ007): each test names the single behaviour it verifies.
"""

from __future__ import annotations

from dataclasses import dataclass

from scitex_hpc import JobConfig
from scitex_hpc._walltime import walltime_max


@dataclass
class _Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class _ScriptedRunner:
    """Returns a scripted result per remote command, matched by substring.

    Records every ``(host, command)`` call for assertions.
    """

    def __init__(self, *, by_substring: dict[str, _Result], default: _Result | None = None):
        self.calls: list[tuple[str, str]] = []
        self._by_substring = by_substring
        self._default = default if default is not None else _Result()

    def __call__(self, host, command, *, check=False, timeout=None):
        self.calls.append((host, command))
        for substr, result in self._by_substring.items():
            if substr in command:
                return result
        return self._default


SINFO_OUT = "sapphire* 30-00:00:00\ngpu-h100 7-00:00:00\n"


def _no_override_runner() -> _ScriptedRunner:
    return _ScriptedRunner(
        by_substring={
            "sinfo": _Result(stdout=SINFO_OUT),
            "sacctmgr show assoc": _Result(
                stdout="Account|QOS|MaxWall\npunim0264|publiccpu|\n"
            ),
        }
    )


def _assoc_override_runner() -> _ScriptedRunner:
    return _ScriptedRunner(
        by_substring={
            "sinfo": _Result(stdout=SINFO_OUT),
            "sacctmgr show assoc": _Result(
                stdout="Account|QOS|MaxWall\npunim0264|publiccpu|7-00:00:00\n"
            ),
        }
    )


def _qos_override_runner() -> _ScriptedRunner:
    return _ScriptedRunner(
        by_substring={
            "sinfo": _Result(stdout=SINFO_OUT),
            "sacctmgr show assoc": _Result(
                stdout="Account|QOS|MaxWall\npunim0264|publiccpu|\n"
            ),
            "sacctmgr show qos": _Result(
                stdout="Name|MaxWall\npubliccpu|14-00:00:00\n"
            ),
        }
    )


def _verify_accepted_runner() -> _ScriptedRunner:
    return _ScriptedRunner(
        by_substring={
            "sinfo": _Result(stdout=SINFO_OUT),
            "sacctmgr show assoc": _Result(stdout="Account|QOS|MaxWall\np|q|\n"),
            "sbatch --test-only": _Result(returncode=0, stdout="Job ... to start at ..."),
        }
    )


def _verify_rejected_runner() -> _ScriptedRunner:
    return _ScriptedRunner(
        by_substring={
            "sinfo": _Result(stdout=SINFO_OUT),
            "sacctmgr show assoc": _Result(stdout="Account|QOS|MaxWall\np|q|\n"),
            "sbatch --test-only": _Result(
                returncode=1, stderr="allocation failure: Requested time limit is invalid"
            ),
        }
    )


def test_walltime_max_reads_sinfo_ceiling():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_no_override_runner())
    # Assert
    assert result.sinfo_ceiling == "30-00:00:00"


def test_walltime_max_no_assoc_override_reports_none():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_no_override_runner())
    # Assert
    assert result.assoc_max_wall is None


def test_walltime_max_achievable_falls_back_to_sinfo_when_no_overrides():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_no_override_runner())
    # Assert
    assert result.achievable() == "30-00:00:00"


def test_walltime_max_default_is_not_verified():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_no_override_runner())
    # Assert
    assert result.verified is False


def test_walltime_max_reads_assoc_max_wall_override():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_assoc_override_runner())
    # Assert
    assert result.assoc_max_wall == "7-00:00:00"


def test_walltime_max_achievable_prefers_assoc_override_over_sinfo():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_assoc_override_runner())
    # Assert — association override wins even though sinfo says 30d
    assert result.achievable() == "7-00:00:00"


def test_walltime_max_reads_qos_max_wall_fallback():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_qos_override_runner())
    # Assert
    assert result.qos_max_wall == "14-00:00:00"


def test_walltime_max_achievable_uses_qos_fallback_when_assoc_unset():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", runner=_qos_override_runner())
    # Assert
    assert result.achievable() == "14-00:00:00"


def test_walltime_max_unknown_partition_has_no_sinfo_ceiling():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "does-not-exist", runner=_no_override_runner())
    # Assert
    assert result.sinfo_ceiling is None


def test_walltime_max_unknown_partition_has_no_achievable_estimate():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "does-not-exist", runner=_no_override_runner())
    # Assert
    assert result.achievable() is None


def test_walltime_max_verify_true_sets_verified_flag():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", verify=True, runner=_verify_accepted_runner())
    # Assert
    assert result.verified is True


def test_walltime_max_verify_accepted_records_accepted_value():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", verify=True, runner=_verify_accepted_runner())
    # Assert
    assert result.verified_accepted == "30-00:00:00"


def test_walltime_max_verify_accepted_leaves_rejected_none():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", verify=True, runner=_verify_accepted_runner())
    # Assert
    assert result.verified_rejected is None


def test_walltime_max_verify_rejected_records_rejected_value():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", verify=True, runner=_verify_rejected_runner())
    # Assert
    assert result.verified_rejected == "30-00:00:00"


def test_walltime_max_verify_rejected_leaves_accepted_none():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", verify=True, runner=_verify_rejected_runner())
    # Assert
    assert result.verified_accepted is None


def test_walltime_max_verify_rejected_note_mentions_rejected():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    # Act
    result = walltime_max(cfg, "sapphire", verify=True, runner=_verify_rejected_runner())
    # Assert
    assert "REJECTED" in result.note


def test_walltime_max_no_verify_skips_test_only_probe():
    # Arrange
    cfg = JobConfig(project="x", host="spartan")
    runner = _no_override_runner()
    # Act
    walltime_max(cfg, "sapphire", verify=False, runner=runner)
    # Assert — no sbatch --test-only call was ever made
    assert not any("sbatch" in cmd for _host, cmd in runner.calls)
