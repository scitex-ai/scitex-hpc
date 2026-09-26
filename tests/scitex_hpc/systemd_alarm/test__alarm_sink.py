#!/usr/bin/env python3
"""Tests for the alarm sink and its locator.

The sink is executed for real against a REAL stand-in binary on disk. A mocked
subprocess cannot reproduce the failure being fenced here, which was an
executable that resolves on one host and is absent on another.

The script is invoked as ``bash <script>`` rather than through its shebang, so
the environment under test is the one the test sets. The login-shell shebang is
a separate and load-bearing property, asserted by reading the file.
"""

from __future__ import annotations

import subprocess

import pytest

from scitex_hpc.systemd_alarm import _alarm_sink


def _run(env_extra, args=("hello",), home=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home or "/nonexistent-home")}
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(_alarm_sink.sink_path()), *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def fake_scitex(tmp_path):
    """A real executable standing in for scitex, echoing what it was handed."""
    exe = tmp_path / "scitex"
    exe.write_text('#!/bin/bash\necho "CALLED:$*"\n')
    exe.chmod(0o755)
    return exe


def test_sink_is_shipped_in_the_package():
    # Arrange
    sink = _alarm_sink.sink_path()
    # Act
    exists = sink.is_file()
    # Assert — five version-controlled files name it; it must BE here
    assert exists is True


def test_sink_shebang_requests_a_login_shell():
    # Arrange
    sink = _alarm_sink.sink_path()
    # Act
    first_line = sink.read_text().splitlines()[0]
    # Assert — without -l an EasyBuild-symlinked interpreter exits 127
    assert first_line == "#!/bin/bash -l"


def test_unit_template_name_carries_the_at_sign():
    # Arrange
    expected = "scitex-unit-failed@.service"
    # Act
    name = _alarm_sink.unit_template_path().name
    # Assert
    assert name == expected


def test_override_binary_is_used_when_set(fake_scitex):
    # Arrange
    env = {"SCITEX_ALARM_BIN": str(fake_scitex)}
    # Act
    proc = _run(env)
    # Assert
    assert proc.returncode == 0


def test_override_binary_receives_notification_send(fake_scitex):
    # Arrange
    env = {"SCITEX_ALARM_BIN": str(fake_scitex)}
    # Act
    proc = _run(env)
    # Assert
    assert proc.stdout.strip() == "CALLED:notification send hello"


def test_arguments_are_passed_through_verbatim(fake_scitex):
    # Arrange
    env = {"SCITEX_ALARM_BIN": str(fake_scitex)}
    # Act
    proc = _run(env, args=("subject line", "-t", "title"))
    # Assert
    assert proc.stdout.strip() == "CALLED:notification send subject line -t title"


def test_home_venv_is_found_without_an_override(tmp_path):
    # Arrange — the compute-04 layout: scitex lives in ~/.venv, not ~/.env-3.11
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    exe = venv_bin / "scitex"
    exe.write_text('#!/bin/bash\necho "CALLED:$*"\n')
    exe.chmod(0o755)
    # Act
    proc = _run({}, home=tmp_path)
    # Assert — a hardcoded spartan path missed this host entirely
    assert proc.stdout.strip() == "CALLED:notification send hello"


def test_unresolvable_binary_exits_three(tmp_path):
    # Arrange — no override target, no HOME dirs, no PATH entry
    env = {"SCITEX_ALARM_BIN": str(tmp_path / "absent")}
    # Act
    proc = _run(env, home=tmp_path)
    # Assert — an alarm that cannot send is a FAILURE, not a silent no-op
    assert proc.returncode == 3


def test_unresolvable_binary_says_it_cannot_send(tmp_path):
    # Arrange
    env = {"SCITEX_ALARM_BIN": str(tmp_path / "absent")}
    # Act
    proc = _run(env, home=tmp_path)
    # Assert
    assert "CANNOT be sent" in proc.stderr


def test_unresolvable_binary_names_the_override(tmp_path):
    # Arrange
    env = {"SCITEX_ALARM_BIN": str(tmp_path / "absent")}
    # Act
    proc = _run(env, home=tmp_path)
    # Assert — the message must carry the FIX, not only the diagnosis
    assert "SCITEX_ALARM_BIN" in proc.stderr


def test_non_executable_candidate_is_skipped(tmp_path):
    # Arrange — present but not executable is the same as absent, and the
    # hardcoded path made that distinction impossible to see
    dud = tmp_path / "scitex-not-exec"
    dud.write_text("#!/bin/bash\necho NOPE\n")
    dud.chmod(0o644)
    env = {"SCITEX_ALARM_BIN": str(dud)}
    # Act
    proc = _run(env, home=tmp_path)
    # Assert
    assert proc.returncode == 3

# EOF
