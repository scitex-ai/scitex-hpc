#!/usr/bin/env python3
"""The operational artifacts must actually SHIP, not merely be committed.

PR #97 version-controlled the OnFailure target and called the alarm rail
rebuildable. Measured 2026-08-30 by building a wheel: it carried 14 non-.py
files -- 13 skill documents and login-guard.sh -- and none of the units, watch
scripts or the sink. "In git" and "in the wheel" are different claims, and the
editable install on Spartan hid the difference by making the working tree the
artifact.

This file is the consumer for that distinction: add a new .service, or a new
extensionless helper, forget the package-data glob, and it fails here rather
than on a host months later.
"""

from __future__ import annotations

from scitex_hpc import _packaging


def test_artifacts_are_found_to_be_checked():
    # Arrange
    expected_minimum = 10
    # Act
    artifacts = _packaging.operational_artifacts()
    # Assert — a control: an empty list would make every assertion below pass
    # while measuring nothing, which is this file's own subject matter
    assert len(artifacts) > expected_minimum


def test_no_operational_artifact_is_left_unpackaged():
    # Arrange
    _ = _packaging.package_data_globs()
    # Act
    missing = _packaging.unpackaged_artifacts()
    # Assert
    assert missing == []


def test_the_alarm_sink_is_declared_as_package_data():
    # Arrange — extensionless, so no type glob catches it; it needs its own
    # entry and is the single likeliest file to be dropped again
    sink = "systemd_alarm/scitex-ci-alarm"
    # Act
    artifacts = _packaging.operational_artifacts()
    # Assert
    assert sink in artifacts


def test_the_onfailure_target_unit_is_an_artifact():
    # Arrange — the file PR #97 believed it had made rebuildable
    unit = "systemd_alarm/scitex-unit-failed@.service"
    # Act
    artifacts = _packaging.operational_artifacts()
    # Assert
    assert unit in artifacts


def test_the_hoist_pool_timer_is_an_artifact():
    # Arrange — #101's timer; without it that watch cannot run at all
    timer = "hoist_pool_watch/hoist-pool-drift-watch.timer"
    # Act
    artifacts = _packaging.operational_artifacts()
    # Assert
    assert timer in artifacts


def test_readme_files_are_not_treated_as_artifacts():
    # Arrange — a missing README is an inconvenience; a missing .service is a
    # monitor that cannot be installed. The rule must not conflate them.
    artifacts = _packaging.operational_artifacts()
    # Act
    markdown = [a for a in artifacts if a.endswith(".md")]
    # Assert
    assert markdown == []

# EOF
