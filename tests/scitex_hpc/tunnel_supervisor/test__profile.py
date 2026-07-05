"""Tests for TunnelSupervisorProfile (pure data + probe rendering)."""

from __future__ import annotations

import pytest

from scitex_hpc.tunnel_supervisor import TunnelSupervisorProfile


def _profile(**over):
    base = dict(
        name="mytunnel",
        sentinel_path="/tmp/mytunnel.alive",
        lockfile_path="/tmp/mytunnel.lock",
        log_path="/tmp/mytunnel.log",
        launch_command="ssh -N -L 8080:127.0.0.1:8080 host",
        health_url="http://127.0.0.1:8080/health",
    )
    base.update(over)
    return TunnelSupervisorProfile(**base)


def test_default_poll_interval_is_positive():
    # Arrange
    p = _profile()
    # Act
    value = p.poll_interval
    # Assert
    assert value > 0


def test_default_restart_backoff_is_positive():
    # Arrange
    p = _profile()
    # Act
    value = p.restart_backoff
    # Assert
    assert value > 0


def test_health_probe_default_uses_curl():
    # Arrange
    p = _profile()
    # Act
    probe = p.health_probe()
    # Assert
    assert "curl" in probe


def test_health_probe_default_includes_url():
    # Arrange
    p = _profile(health_url="http://127.0.0.1:9000/health")
    # Act
    probe = p.health_probe()
    # Assert
    assert "http://127.0.0.1:9000/health" in probe


def test_health_probe_default_includes_timeout():
    # Arrange
    p = _profile(health_timeout=7)
    # Act
    probe = p.health_probe()
    # Assert
    assert "--max-time 7" in probe


def test_health_probe_injected_command_used_verbatim():
    # Arrange
    p = _profile(health_check_command="test -f /tmp/flag")
    # Act
    probe = p.health_probe()
    # Assert
    assert probe == "test -f /tmp/flag"


def test_health_probe_injected_command_skips_curl():
    # Arrange
    p = _profile(health_check_command="test -f /tmp/flag")
    # Act
    probe = p.health_probe()
    # Assert
    assert "curl" not in probe


def test_empty_name_rejected():
    # Arrange
    kwargs = dict(name="  ")
    # Act
    # Assert
    with pytest.raises(ValueError):
        _profile(**kwargs)


def test_empty_launch_command_rejected():
    # Arrange
    kwargs = dict(launch_command="")
    # Act
    # Assert
    with pytest.raises(ValueError):
        _profile(**kwargs)


def test_nonpositive_interval_rejected():
    # Arrange
    kwargs = dict(poll_interval=0)
    # Act
    # Assert
    with pytest.raises(ValueError):
        _profile(**kwargs)
