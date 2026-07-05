"""Static (string) tests for the rendered supervisor script."""

from __future__ import annotations

from scitex_hpc.tunnel_supervisor import (
    TunnelSupervisorProfile,
    render_supervisor_script,
)


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


def test_script_has_sentinel_keepalive_loop():
    # Arrange
    p = _profile()
    # Act
    script = render_supervisor_script(p)
    # Assert
    assert 'while [ -f "$SENTINEL" ]; do' in script


def test_script_uses_flock_single_instance():
    # Arrange
    p = _profile()
    # Act
    script = render_supervisor_script(p)
    # Assert
    assert "flock -n 9" in script


def test_script_embeds_launch_command():
    # Arrange
    p = _profile(launch_command="ssh -N -L 5000:127.0.0.1:5000 gateway")
    # Act
    script = render_supervisor_script(p)
    # Assert
    assert "ssh -N -L 5000:127.0.0.1:5000 gateway" in script


def test_script_logs_timestamped_lines():
    # Arrange
    p = _profile()
    # Act
    script = render_supervisor_script(p)
    # Assert — heartbeat log lines are ISO-8601-UTC timestamped
    assert 'echo "[$(date -u +%FT%TZ)] $NAME: $*" >> "$LOG"' in script


def test_script_health_watcher_probes_endpoint_by_default():
    # Arrange
    p = _profile(health_url="http://127.0.0.1:1234/health")
    # Act
    script = render_supervisor_script(p)
    # Assert — the ENDPOINT (curl of the URL), not the PID, is the health signal
    assert "http://127.0.0.1:1234/health" in script


def test_script_kills_live_pid_on_dead_endpoint():
    # Arrange
    p = _profile()
    # Act
    script = render_supervisor_script(p)
    # Assert — unhealthy endpoint kills the live PID so the loop restarts it
    assert "if ! health_probe; then" in script


def test_script_injected_health_command_used():
    # Arrange
    p = _profile(health_check_command="test -f /tmp/hc")
    # Act
    script = render_supervisor_script(p)
    # Assert
    assert "test -f /tmp/hc" in script


def test_script_uses_restart_backoff_value():
    # Arrange
    p = _profile(restart_backoff=42)
    # Act
    script = render_supervisor_script(p)
    # Assert
    assert "RESTART_BACKOFF=42" in script
