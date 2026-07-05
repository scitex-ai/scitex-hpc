"""Tests for install_supervisor_script / default_script_path."""

from __future__ import annotations

import os
from pathlib import Path

from scitex_hpc.tunnel_supervisor import (
    TunnelSupervisorProfile,
    default_script_path,
    install_supervisor_script,
)


def _profile(tmp_path: Path, **over):
    base = dict(
        name="mytunnel",
        sentinel_path=str(tmp_path / "s.alive"),
        lockfile_path=str(tmp_path / "s.lock"),
        log_path=str(tmp_path / "s.log"),
        launch_command="ssh -N host",
        health_url="http://127.0.0.1:8080/health",
    )
    base.update(over)
    return TunnelSupervisorProfile(**base)


def test_install_writes_file(tmp_path: Path):
    # Arrange
    p = _profile(tmp_path)
    dest = tmp_path / "sup.sh"
    # Act
    written = install_supervisor_script(p, dest)
    # Assert
    assert written.exists()


def test_install_writes_shebang(tmp_path: Path):
    # Arrange
    p = _profile(tmp_path)
    dest = tmp_path / "sup.sh"
    # Act
    written = install_supervisor_script(p, dest)
    # Assert
    assert written.read_text().startswith("#!/usr/bin/env bash")


def test_install_sets_executable_bit(tmp_path: Path):
    # Arrange
    p = _profile(tmp_path)
    dest = tmp_path / "sup.sh"
    # Act
    written = install_supervisor_script(p, dest)
    # Assert
    assert os.access(written, os.X_OK)


def test_install_creates_parent_dirs(tmp_path: Path):
    # Arrange
    p = _profile(tmp_path)
    dest = tmp_path / "nested" / "deep" / "sup.sh"
    # Act
    written = install_supervisor_script(p, dest)
    # Assert
    assert written.exists()


def test_default_script_path_includes_name(tmp_path: Path):
    # Arrange
    p = _profile(tmp_path, name="edge-proxy")
    # Act
    path = default_script_path(p)
    # Assert
    assert path.name == "scitex-hpc-supervisor-edge-proxy.sh"


def test_install_without_dest_uses_default_path(tmp_path: Path):
    # Arrange
    p = _profile(tmp_path, name="edge")
    # Act
    written = install_supervisor_script(p)
    # Assert
    assert written == default_script_path(p)
