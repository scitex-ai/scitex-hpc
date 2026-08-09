"""Rendering is pure, so the artifact can be asserted on without running it.

These tests exist because of a specific, measured failure on this card's
predecessor: PR #82 changed a shell script that NO CI leg executed, and
seven green checks said nothing about the file the PR touched. Asserting on
rendered text is what makes that file testable at all.

Two properties get the most attention, because they are the ones a future
edit is most likely to quietly break:

  1. the manifest is DATA — a profile change must show up in the artifact
  2. the three-valued logic survives rendering verbatim
"""

from __future__ import annotations

from scitex_hpc.tree_monitor import (
    EXAMPLE_PROFILE,
    TreeMonitorProfile,
    render_check_script,
    render_manifest_block,
    render_service_unit,
    render_timer_unit,
)


# --------------------------------------------------------------------------
# The manifest is data, not a heredoc someone has to patch
# --------------------------------------------------------------------------
def test_default_manifest_paths_appear_in_the_block():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    block = render_manifest_block(profile)
    # Assert
    assert "$HOME/.scitex/hpc" in block


def test_a_custom_manifest_path_reaches_the_block():
    # Arrange
    profile = EXAMPLE_PROFILE.with_manifest("/data/gpfs/projects/punim0264/for_solver")
    # Act
    block = render_manifest_block(profile)
    # Assert
    assert "/data/gpfs/projects/punim0264/for_solver" in block


def test_a_replaced_manifest_drops_the_old_paths():
    """Negative control: without this, the previous test passes on a stale default."""
    # Arrange
    profile = EXAMPLE_PROFILE.with_manifest("/only/this/one")
    # Act
    block = render_manifest_block(profile)
    # Assert
    assert "$HOME/.scitex/hpc" not in block


def test_custom_manifest_reaches_the_rendered_script():
    # Arrange
    profile = EXAMPLE_PROFILE.with_manifest("/watched/path")
    # Act
    script = render_check_script(profile)
    # Assert
    assert "/watched/path" in script


def test_unconfirmed_owners_are_named_in_the_artifact():
    """The manifest's partiality must be visible where someone reads it."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    block = render_manifest_block(profile)
    # Assert
    assert "paper-scitex-clew" in block


def test_no_unconfirmed_owners_renders_no_partiality_notice():
    # Arrange
    profile = TreeMonitorProfile(unconfirmed_owners=())
    # Act
    block = render_manifest_block(profile)
    # Assert
    assert "PARTIAL BY CONSTRUCTION" not in block


# --------------------------------------------------------------------------
# The three-valued logic survives rendering
# --------------------------------------------------------------------------
def test_script_records_present_state():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    script = render_check_script(profile)
    # Assert
    assert "CUR[\"$p\"]=PRESENT" in script


def test_script_records_unknown_state():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    script = render_check_script(profile)
    # Assert
    assert "CUR[\"$p\"]=UNKNOWN" in script


def test_script_alarms_only_on_present_to_missing():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    script = render_check_script(profile)
    # Assert
    assert '[ "${PREV[$p]:-}" = "PRESENT" ]' in script


def test_unknown_never_overwrites_a_present_baseline():
    """The line that keeps a deletion catchable after an unreadable window."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    script = render_check_script(profile)
    # Assert
    assert '[ "$st" = "UNKNOWN" ] && st="${PREV[$p]:-UNKNOWN}"' in script


def test_script_honours_the_dryrun_rehearsal_flag():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    script = render_check_script(profile)
    # Assert
    assert "SCITEX_TREE_MONITOR_DRYRUN" in script


def test_script_stamps_the_alarm_card_with_the_profile_agent():
    # Arrange
    profile = TreeMonitorProfile(agent_id="someone-else")
    # Act
    script = render_check_script(profile)
    # Assert
    assert "SCITEX_TODO_AGENT_ID=someone-else" in script


def test_script_is_marked_generated():
    """A reader must not hand-edit the artifact and lose it on next render."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    script = render_check_script(profile)
    # Assert
    assert "[GENERATED" in script


# --------------------------------------------------------------------------
# The units stop being baked for one host
# --------------------------------------------------------------------------
def test_service_execstart_follows_the_profile_script_path():
    # Arrange
    profile = TreeMonitorProfile(script_path="$HOME/elsewhere/check.sh")
    # Act
    unit = render_service_unit(profile)
    # Assert
    assert "ExecStart=%h/elsewhere/check.sh" in unit


def test_service_treats_exit_one_as_success():
    """exit 1 means a path vanished — the monitor WORKING, not failing."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    unit = render_service_unit(profile)
    # Assert
    assert "SuccessExitStatus=0 1" in unit


def test_service_is_niced_on_a_shared_host():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    unit = render_service_unit(profile)
    # Assert
    assert "Nice=19" in unit


def test_timer_cadence_follows_the_profile():
    # Arrange
    profile = TreeMonitorProfile(interval="90s")
    # Act
    unit = render_timer_unit(profile)
    # Assert
    assert "OnUnitActiveSec=90s" in unit


def test_timer_is_persistent_across_reboots():
    """A monitor that stops at reboot is the gap the incidents fell through."""
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    unit = render_timer_unit(profile)
    # Assert
    assert "Persistent=true" in unit


def test_timer_installs_into_timers_target():
    # Arrange
    profile = EXAMPLE_PROFILE
    # Act
    unit = render_timer_unit(profile)
    # Assert
    assert "WantedBy=timers.target" in unit
