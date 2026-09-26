"""The install path writes bytes, so these tests carry extra weight.

Two reasons for the care here:

  1. this is the only module in the package that touches a filesystem, and
     the scitex-dev linter's IO/PA rules (STX-IO001-014, STX-PA001-005) are
     NOT registered in this venv — it says so on every run. A green lint
     verdict does not cover this file's IO, so the tests have to.
  2. arming this monitor can raise P1 cards on the shared fleet board. The
     tests below pin the boundary that stops an install from doing that as
     a side effect.

Everything writes into pytest's ``tmp_path``. Nothing here touches a real
``$HOME``, a real systemd directory, or the live card store.
"""

from __future__ import annotations

import os
import stat

from scitex_hpc.tree_monitor import (
    EXAMPLE_PROFILE,
    TreeMonitorProfile,
    enable_commands,
    install,
    rehearse_command,
    write_check_script,
    write_units,
)


# --------------------------------------------------------------------------
# write_check_script
# --------------------------------------------------------------------------
def test_script_is_written_to_the_requested_path(tmp_path):
    # Arrange
    target = str(tmp_path / "nested" / "check.sh")
    # Act
    written = write_check_script(EXAMPLE_PROFILE, target)
    # Assert
    assert os.path.isfile(written)


def test_script_is_executable(tmp_path):
    # Arrange
    target = str(tmp_path / "check.sh")
    # Act
    written = write_check_script(EXAMPLE_PROFILE, target)
    # Assert
    assert os.stat(written).st_mode & stat.S_IXUSR


def test_written_script_contains_the_profile_manifest(tmp_path):
    # Arrange
    profile = EXAMPLE_PROFILE.with_manifest("/watched/by/test")
    # Act
    written = write_check_script(profile, str(tmp_path / "check.sh"))
    # Assert
    assert "/watched/by/test" in open(written).read()


def test_missing_parent_directories_are_created(tmp_path):
    # Arrange
    target = str(tmp_path / "a" / "b" / "c" / "check.sh")
    # Act
    write_check_script(EXAMPLE_PROFILE, target)
    # Assert
    assert os.path.isdir(os.path.dirname(target))


# --------------------------------------------------------------------------
# write_units
# --------------------------------------------------------------------------
def test_service_unit_is_written(tmp_path):
    # Arrange
    unit_dir = str(tmp_path / "systemd")
    # Act
    service, _timer = write_units(EXAMPLE_PROFILE, unit_dir)
    # Assert
    assert os.path.isfile(service)


def test_timer_unit_is_written(tmp_path):
    # Arrange
    unit_dir = str(tmp_path / "systemd")
    # Act
    _service, timer = write_units(EXAMPLE_PROFILE, unit_dir)
    # Assert
    assert os.path.isfile(timer)


def test_unit_filenames_follow_the_profile_name(tmp_path):
    # Arrange
    profile = TreeMonitorProfile(name="other-monitor")
    # Act
    service, _timer = write_units(profile, str(tmp_path / "systemd"))
    # Assert
    assert os.path.basename(service) == "other-monitor.service"


# --------------------------------------------------------------------------
# The boundary: installing must not ARM anything
# --------------------------------------------------------------------------
def test_enable_commands_are_returned_not_run():
    """Arming a P1-capable alarm is a decision, not an install side effect."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    commands = enable_commands(profile)
    # Assert
    assert commands == [
        "systemctl --user daemon-reload",
        f"systemctl --user enable --now {profile.name}.timer",
    ]


def test_install_does_not_create_a_systemd_enable_marker(tmp_path):
    """Negative control: install writes units and nothing that arms them."""
    # Arrange
    unit_dir = tmp_path / "systemd"
    profile = TreeMonitorProfile(script_path=str(tmp_path / "check.sh"))
    # Act
    install(profile, unit_dir=str(unit_dir))
    # Assert
    assert not (unit_dir / "timers.target.wants").exists()


def test_rehearse_command_suppresses_the_card_write():
    """The flag that exists because a test run once carded the live board."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    command = rehearse_command(profile)
    # Assert
    assert "SCITEX_TREE_MONITOR_DRYRUN=1" in command


# --------------------------------------------------------------------------
# install() answers in a fixed, declared shape
# --------------------------------------------------------------------------
def test_install_result_carries_every_declared_key(tmp_path):
    # Arrange
    profile = TreeMonitorProfile(script_path=str(tmp_path / "check.sh"))
    # Act
    result = install(profile, unit_dir=str(tmp_path / "systemd"))
    # Assert
    assert set(result) == {"script", "service", "timer", "enable", "rehearse"}


def test_install_writes_the_script_it_reports(tmp_path):
    # Arrange
    profile = TreeMonitorProfile(script_path=str(tmp_path / "check.sh"))
    # Act
    result = install(profile, unit_dir=str(tmp_path / "systemd"))
    # Assert
    assert os.path.isfile(str(result["script"]))


def test_install_writes_the_timer_it_reports(tmp_path):
    # Arrange
    profile = TreeMonitorProfile(script_path=str(tmp_path / "check.sh"))
    # Act
    result = install(profile, unit_dir=str(tmp_path / "systemd"))
    # Assert
    assert os.path.isfile(str(result["timer"]))
