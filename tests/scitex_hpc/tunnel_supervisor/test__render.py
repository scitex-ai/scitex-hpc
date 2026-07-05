"""Tests for the tunnel-supervisor shell-script generator."""

from __future__ import annotations

from scitex_hpc.tunnel_supervisor import TunnelProfile, render_supervisor
from scitex_hpc.tunnel_supervisor._render import render_install_script


def _profile(**overrides) -> TunnelProfile:
    base = dict(
        name="clew-tunnel",
        command="ssh -N -L 8080:127.0.0.1:8080 remote-host",
        sentinel_path="/tmp/clew-tunnel.sentinel",
        lockfile_path="/tmp/clew-tunnel.lock",
        log_path="/tmp/clew-tunnel.log",
        health_check_url="http://127.0.0.1:8080/health",
        health_check_interval=10.0,
        health_check_timeout=5.0,
        unhealthy_threshold=3,
        poll_interval=5.0,
        restart_backoff=7,
    )
    base.update(overrides)
    return TunnelProfile(**base)


def test_render_includes_sentinel_while_loop():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert — sentinel + keepalive loop shape
    assert 'while [ -f "$SENTINEL" ]' in script


def test_render_includes_the_wrapped_command():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert
    assert "ssh -N -L 8080:127.0.0.1:8080 remote-host" in script


def test_render_uses_flock_for_single_instance():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert
    assert "flock -n 200" in script


def test_render_uses_backoff_value():
    # Arrange
    profile = _profile(restart_backoff=42)
    # Act
    script = render_supervisor(profile)
    # Assert
    assert "sleep 42" in script


def test_render_substitutes_sentinel_path():
    # Arrange
    profile = _profile(sentinel_path="/tmp/my-service.sentinel")
    # Act
    script = render_supervisor(profile)
    # Assert
    assert 'SENTINEL="/tmp/my-service.sentinel"' in script


def test_render_substitutes_lockfile_path():
    # Arrange
    profile = _profile(lockfile_path="/tmp/my-service.lock")
    # Act
    script = render_supervisor(profile)
    # Assert
    assert 'LOCKFILE="/tmp/my-service.lock"' in script


def test_render_writes_timestamped_heartbeat_on_start():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert — every loop iteration logs a UTC-timestamped line
    assert '$(date -u +%FT%TZ)' in script


def test_render_heartbeat_appends_to_log_file():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert
    assert '>> "$LOG"' in script


def test_render_logs_exit_event():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert
    assert "exited rc=" in script


def test_render_logs_restart_delay():
    # Arrange
    profile = _profile()
    # Act
    script = render_supervisor(profile)
    # Assert
    assert "restart in" in script


def test_render_includes_health_check_url_when_configured():
    # Arrange
    profile = _profile(health_check_url="http://127.0.0.1:9000/health")
    # Act
    script = render_supervisor(profile)
    # Assert — health-checks the ENDPOINT, not just the PID
    assert "http://127.0.0.1:9000/health" in script


def test_render_health_watcher_uses_curl():
    # Arrange
    profile = _profile(health_check_url="http://127.0.0.1:9000/health")
    # Act
    script = render_supervisor(profile)
    # Assert
    assert "curl -fsS" in script


def test_render_kills_command_after_unhealthy_threshold():
    # Arrange
    profile = _profile(unhealthy_threshold=5)
    # Act
    script = render_supervisor(profile)
    # Assert
    assert '"$fails" -ge 5' in script


def test_render_kill_targets_wrapped_command_pid():
    # Arrange
    profile = _profile(unhealthy_threshold=5)
    # Act
    script = render_supervisor(profile)
    # Assert
    assert 'kill "$pid_to_kill"' in script


def test_render_omits_health_watcher_when_no_url_configured():
    # Arrange
    profile = _profile(health_check_url=None)
    # Act
    script = render_supervisor(profile)
    # Assert — no curl watcher fragment when health-checking is disabled
    assert "curl -fsS" not in script


def test_render_has_no_hardcoded_cluster_names():
    # Arrange — a custom profile with generic values proves genericity
    profile = _profile(name="acme-svc", command="/opt/acme/run.sh")
    # Act
    script = render_supervisor(profile)
    # Assert — none of the known HPC-specific tokens leak in
    assert not any(tok in script.lower() for tok in ("spartan", "punim", "gadi"))


def test_install_script_chmods_target():
    # Arrange
    profile = _profile()
    # Act
    script = render_install_script(profile)
    # Assert
    assert 'chmod +x "$TARGET"' in script


def test_install_script_embeds_rendered_command():
    # Arrange
    profile = _profile()
    # Act
    script = render_install_script(profile)
    # Assert
    assert "ssh -N -L 8080" in script
