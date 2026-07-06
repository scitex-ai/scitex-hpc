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


def test_monitor_jobid_file_resolves_holder_from_file():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet",
        overlap_jobid_file="$HOME/.scitex/hpc/runtime/holder.jobid",
    )
    # Assert — reads the id from the file at runtime, not a build-time const
    assert "HOLDER_JOBID=" in script


def test_monitor_jobid_file_exits_3_when_unregistered():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet",
        overlap_jobid_file="$HOME/.scitex/hpc/runtime/holder.jobid",
    )
    # Assert — a missing/empty file is a DISTINCT exit (not false allocation-down)
    assert "exit 3" in script


def test_monitor_jobid_file_squeue_uses_resolved_id():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet",
        overlap_jobid_file="$HOME/.scitex/hpc/runtime/holder.jobid",
    )
    # Assert — the scheduler lookup keys off the file-resolved id
    assert "--job=$HOLDER_JOBID" in script


def test_monitor_jobid_file_still_never_scancels():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet",
        overlap_jobid_file="$HOME/.scitex/hpc/runtime/holder.jobid",
    )
    # Assert
    assert "scancel" not in script


# ---------------------------------------------------------------------------
# inode-headroom arm — catches the "listeners up but fileset full" outage
# ---------------------------------------------------------------------------


def test_monitor_exits_4_on_inode_wall():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — a distinct exit code for the inode-critical case
    assert "exit 4" in script


def test_monitor_checks_inodes_with_df_i():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — read-only df -i inode probe
    assert "df -i" in script


def test_monitor_inode_check_defaults_to_ci_base_fileset():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — checks the fileset the runner install dirs live on
    assert f"df -i '{CI_BASE}'" in script


def test_monitor_inode_threshold_is_configurable():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet", inode_threshold_pct=80
    )
    # Assert
    assert '"$IUSE" -ge 80' in script


def test_monitor_inode_path_override():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(
        fleet, host="spartan", lease_name="fleet", inode_path="/data/scratch"
    )
    # Assert
    assert "df -i '/data/scratch'" in script


def test_monitor_inode_check_is_read_only():
    # Arrange
    fleet = _fleet("a")
    # Act
    script = build_monitor_script(fleet, host="spartan", lease_name="fleet")
    # Assert — the inode arm must never delete on the cluster (monitor is read-mostly)
    assert "rm -rf" not in script


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
