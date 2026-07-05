"""Tests for the health-monitor script generator."""

from __future__ import annotations

from scitex_hpc.ci_runners import FleetSpec, RunnerSpec, build_monitor_script
from scitex_hpc.ci_runners._archive import build_archive_script

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"


def _fleet(*names: str) -> FleetSpec:
    runners = [
        RunnerSpec(name=n, dir=f"{CI_BASE}/actions-runner-{n}") for n in names
    ]
    return FleetSpec(ci_base=CI_BASE, runners=runners)


def test_monitor_is_bash_script():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert
    assert script.startswith("#!/usr/bin/env bash")


def test_monitor_exits_2_on_allocation_down():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — critical path uses exit code 2
    assert "exit 2" in script


def test_monitor_exits_1_when_runners_down():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert
    assert "exit 1" in script


def test_monitor_has_alarm_contract():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — operator-overridable alarm command
    assert "SCITEX_CI_ALARM_CMD" in script


def test_monitor_lists_each_runner():
    # Arrange
    fleet = _fleet("a", "b")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert
    assert '["b"]=' in script


def test_monitor_never_scancels():
    # Arrange — the monitor must NEVER kill the supervisor or a runner
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert
    assert "scancel" not in script


def test_monitor_default_resolves_by_name():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — book-supervisor path keys off the job name
    assert "--name=fleet" in script


def test_monitor_overlap_jobid_resolves_by_job_id():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet", overlap_jobid="26437532"
    )
    # Assert — exec-supervisor path keys off the holder job id
    assert "--job=26437532" in script


def test_monitor_overlap_jobid_omits_name_selector():
    # Arrange — no job named 'fleet' exists in the exec-supervisor deploy
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet", overlap_jobid="26437532"
    )
    # Assert — the name lookup (which would false-alarm) is not emitted
    assert "--name=" not in script


def test_monitor_overlap_jobid_hint_points_at_exec_supervisor():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet", overlap_jobid="26437532"
    )
    # Assert — the allocation-down alarm names the correct recovery path
    assert "exec-supervisor" in script


def test_monitor_overlap_jobid_still_never_scancels():
    # Arrange — the read-mostly safety invariant holds in job-id mode too
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet", overlap_jobid="26437532"
    )
    # Assert
    assert "scancel" not in script


def test_archive_is_non_destructive():
    # Arrange
    home = "~"
    # Act
    script = build_archive_script(home=home)
    # Assert — moves, never deletes
    assert "rm " not in script


def test_archive_moves_known_bandaids():
    # Arrange
    home = "~"
    # Act
    script = build_archive_script(home=home)
    # Assert
    assert "relaunch_all.sh" in script
