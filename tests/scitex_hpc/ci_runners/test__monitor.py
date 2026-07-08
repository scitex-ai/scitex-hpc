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
