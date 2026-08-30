#!/usr/bin/env python3
"""CLI-level tests for ``audit-deploys``, especially the transition gate.

The gate is the difference between a check and alarm fatigue, so it is tested
where it actually runs — through the command — rather than only at the helper
that computes the signature.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from click.testing import CliRunner

from scitex_hpc._cli._deploy_audit import EXIT_BROKEN, audit_deploys_cmd


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _make_editable(venv, name, source):
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    dist = site / f"{name}-1.0.dist-info"
    dist.mkdir(exist_ok=True)
    (dist / "direct_url.json").write_text(
        json.dumps({"url": f"file://{source}", "dir_info": {"editable": True}})
    )


@pytest.fixture
def broken_venv(tmp_path):
    """A venv holding one install whose source directory does not exist."""
    venv = tmp_path / "venv"
    _make_editable(venv, "pkg_gone", tmp_path / "absent")
    return venv


def test_broken_install_exits_twenty_one(broken_venv, tmp_path):
    # Arrange
    state = tmp_path / "state"
    # Act
    result = CliRunner().invoke(
        audit_deploys_cmd,
        ["--venv", str(broken_venv), "--no-fetch", "--state-file", str(state)],
    )
    # Assert
    assert result.exit_code == EXIT_BROKEN


def test_first_on_change_run_still_reports(broken_venv, tmp_path):
    # Arrange — no state file yet: "cannot compare" must not read as "clean"
    state = tmp_path / "state"
    # Act
    result = CliRunner().invoke(
        audit_deploys_cmd,
        ["--venv", str(broken_venv), "--no-fetch", "--on-change",
         "--state-file", str(state)],
    )
    # Assert
    assert result.exit_code == EXIT_BROKEN


def test_second_on_change_run_stays_silent(broken_venv, tmp_path):
    # Arrange — same condition, already reported once
    state = tmp_path / "state"
    args = ["--venv", str(broken_venv), "--no-fetch", "--on-change",
            "--state-file", str(state)]
    CliRunner().invoke(audit_deploys_cmd, args)
    # Act
    second = CliRunner().invoke(audit_deploys_cmd, args)
    # Assert — a standing condition must not re-page every tick
    assert second.exit_code == 0


def test_unchanged_run_still_states_what_is_outstanding(broken_venv, tmp_path):
    # Arrange
    state = tmp_path / "state"
    args = ["--venv", str(broken_venv), "--no-fetch", "--on-change",
            "--state-file", str(state)]
    CliRunner().invoke(audit_deploys_cmd, args)
    # Act
    second = CliRunner().invoke(audit_deploys_cmd, args)
    # Assert — silent about the ALARM, never silent about the FACT
    assert "still outstanding" in second.output


def test_a_new_breakage_reports_again(broken_venv, tmp_path):
    # Arrange — condition already seen, then a SECOND install breaks
    state = tmp_path / "state"
    args = ["--venv", str(broken_venv), "--no-fetch", "--on-change",
            "--state-file", str(state)]
    CliRunner().invoke(audit_deploys_cmd, args)
    _make_editable(broken_venv, "pkg_gone_two", tmp_path / "absent2")
    # Act
    third = CliRunner().invoke(audit_deploys_cmd, args)
    # Assert — suppression must never swallow a genuinely new finding
    assert third.exit_code == EXIT_BROKEN


def test_without_on_change_every_run_reports(broken_venv, tmp_path):
    # Arrange — a human running it by hand wants the CURRENT state
    state = tmp_path / "state"
    args = ["--venv", str(broken_venv), "--no-fetch", "--state-file", str(state)]
    CliRunner().invoke(audit_deploys_cmd, args)
    # Act
    second = CliRunner().invoke(audit_deploys_cmd, args)
    # Assert
    assert second.exit_code == EXIT_BROKEN


def test_a_clean_venv_exits_zero(tmp_path):
    # Arrange
    venv = tmp_path / "venv"
    (venv / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    # Act
    result = CliRunner().invoke(
        audit_deploys_cmd, ["--venv", str(venv), "--no-fetch"]
    )
    # Assert
    assert result.exit_code == 0

# EOF
