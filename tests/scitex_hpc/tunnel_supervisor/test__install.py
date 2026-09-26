"""Tests for writing the rendered supervisor script + cron/systemd artifacts."""

from __future__ import annotations

import os
import stat

from scitex_hpc.tunnel_supervisor import TunnelProfile
from scitex_hpc.tunnel_supervisor._install import (
    cron_line,
    supervisor_text,
    systemd_unit_text,
    write_supervisor,
)


def _profile(**overrides) -> TunnelProfile:
    base = dict(name="acme-tunnel", command="ssh -N acme-host")
    base.update(overrides)
    return TunnelProfile(**base)


def test_supervisor_text_matches_render_supervisor():
    # Arrange
    profile = _profile()
    from scitex_hpc.tunnel_supervisor import render_supervisor

    # Act
    text = supervisor_text(profile)
    # Assert
    assert text == render_supervisor(profile)


def test_write_supervisor_creates_file(tmp_path):
    # Arrange
    profile = _profile()
    target = tmp_path / "sub" / "supervisor.sh"
    # Act
    write_supervisor(profile, str(target))
    # Assert
    assert target.exists()


def test_write_supervisor_makes_file_executable(tmp_path):
    # Arrange
    profile = _profile()
    target = tmp_path / "supervisor.sh"
    # Act
    write_supervisor(profile, str(target))
    # Assert
    mode = os.stat(target).st_mode
    assert mode & stat.S_IXUSR


def test_write_supervisor_content_matches_render(tmp_path):
    # Arrange
    profile = _profile()
    target = tmp_path / "supervisor.sh"
    # Act
    write_supervisor(profile, str(target))
    # Assert
    assert target.read_text() == supervisor_text(profile)


def test_cron_line_includes_script_path():
    # Arrange
    profile = _profile()
    # Act
    line = cron_line(profile, "/opt/acme/supervisor.sh")
    # Assert
    assert "/opt/acme/supervisor.sh" in line


def test_cron_line_defaults_to_reboot_schedule():
    # Arrange
    profile = _profile()
    # Act
    line = cron_line(profile, "/opt/acme/supervisor.sh")
    # Assert
    assert line.startswith("@reboot")


def test_systemd_unit_includes_script_path():
    # Arrange
    profile = _profile()
    # Act
    unit = systemd_unit_text(profile, "/opt/acme/supervisor.sh")
    # Assert
    assert "/opt/acme/supervisor.sh" in unit


def test_systemd_unit_restarts_always():
    # Arrange
    profile = _profile()
    # Act
    unit = systemd_unit_text(profile, "/opt/acme/supervisor.sh")
    # Assert
    assert "Restart=always" in unit
