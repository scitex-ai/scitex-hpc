"""Tests for the pure-Python sentinel + keep-alive + flock + health loop.

Uses ``tmp_path`` for sentinel/lock/log files and a fake
``SupervisedProcess`` double (no real subprocess) so restart behavior,
flock rejection, heartbeat format, and health-triggered-restart are all
exercised without touching the network or spawning real processes. The
health checker is always passed in explicitly (never the real
``default_health_checker``) so no test call reaches the network.
"""

from __future__ import annotations

import pytest

from scitex_hpc.tunnel_supervisor import TunnelProfile
from scitex_hpc.tunnel_supervisor._loop import (
    LockHeldError,
    acquire_lock,
    append_heartbeat,
    monitor_health_until_unhealthy,
    release_lock,
    run_supervisor,
    sentinel_active,
)


class FakeProcess:
    """A scripted ``SupervisedProcess`` double: exits after N ``poll()`` calls."""

    def __init__(self, exit_after_polls: int = 0, rc: int = 0):
        self._polls_left = exit_after_polls
        self._rc = rc
        self._killed = False

    def poll(self):
        if self._killed:
            return self._rc
        if self._polls_left <= 0:
            return self._rc
        self._polls_left -= 1
        return None

    def wait(self):
        self._polls_left = 0
        return self._rc

    def kill(self):
        self._killed = True
        self._rc = -9


def _profile(tmp_path, **overrides) -> TunnelProfile:
    base = dict(
        name="test-tunnel",
        command="true",
        sentinel_path=str(tmp_path / "sentinel"),
        lockfile_path=str(tmp_path / "lock"),
        log_path=str(tmp_path / "log"),
        health_check_url=None,
        restart_backoff=0,
        poll_interval=0,
    )
    base.update(overrides)
    return TunnelProfile(**base)


# ---------------------------------------------------------------------------
# Sentinel check
# ---------------------------------------------------------------------------
def test_sentinel_active_true_when_file_exists(tmp_path):
    # Arrange
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("")
    # Act
    active = sentinel_active(str(sentinel))
    # Assert
    assert active is True


def test_sentinel_active_false_when_file_absent(tmp_path):
    # Arrange
    sentinel = tmp_path / "sentinel-missing"
    # Act
    active = sentinel_active(str(sentinel))
    # Assert
    assert active is False


# ---------------------------------------------------------------------------
# flock single-instance guard
# ---------------------------------------------------------------------------
def test_acquire_lock_succeeds_when_unheld(tmp_path):
    # Arrange
    lockfile = str(tmp_path / "lock")
    # Act
    fh = acquire_lock(lockfile)
    # Assert
    assert fh is not None
    release_lock(fh)


def test_acquire_lock_rejects_second_instance(tmp_path):
    # Arrange
    lockfile = str(tmp_path / "lock")
    held = acquire_lock(lockfile)
    # Act
    def act():
        return acquire_lock(lockfile)

    # Assert
    with pytest.raises(LockHeldError):
        act()
    release_lock(held)


def test_release_lock_allows_reacquire(tmp_path):
    # Arrange
    lockfile = str(tmp_path / "lock")
    fh = acquire_lock(lockfile)
    release_lock(fh)
    # Act
    reacquired = acquire_lock(lockfile)
    # Assert
    assert reacquired is not None
    release_lock(reacquired)


# ---------------------------------------------------------------------------
# Heartbeat log format
# ---------------------------------------------------------------------------
def test_append_heartbeat_writes_bracketed_utc_timestamp(tmp_path):
    # Arrange
    log_path = str(tmp_path / "log")
    # Act
    line = append_heartbeat(log_path, "hello", now_fn=lambda: 0.0)
    # Assert
    assert line == "[1970-01-01T00:00:00Z] hello\n"


def test_append_heartbeat_appends_across_calls(tmp_path):
    # Arrange
    log_path = str(tmp_path / "log")
    append_heartbeat(log_path, "first", now_fn=lambda: 0.0)
    # Act
    append_heartbeat(log_path, "second", now_fn=lambda: 0.0)
    # Assert
    content = open(log_path).read()
    assert content.count("\n") == 2


# ---------------------------------------------------------------------------
# Sentinel-loop restart behavior
# ---------------------------------------------------------------------------
def test_run_supervisor_restarts_command_each_iteration(tmp_path):
    # Arrange
    profile = _profile(tmp_path)
    (tmp_path / "sentinel").write_text("")
    launches = []

    def command_runner():
        launches.append(1)
        return FakeProcess()

    # Act
    run_supervisor(
        profile,
        command_runner=command_runner,
        sleep_fn=lambda s: None,
        max_iterations=3,
    )
    # Assert
    assert len(launches) == 3


def test_run_supervisor_stops_when_sentinel_removed_mid_loop(tmp_path):
    # Arrange
    profile = _profile(tmp_path)
    sentinel_path = tmp_path / "sentinel"
    sentinel_path.write_text("")
    launches = []

    def command_runner():
        launches.append(1)
        if len(launches) == 2:
            sentinel_path.unlink()
        return FakeProcess()

    # Act
    run_supervisor(
        profile,
        command_runner=command_runner,
        sleep_fn=lambda s: None,
        max_iterations=10,
    )
    # Assert — loop exits right after the sentinel disappears, not 10 times
    assert len(launches) == 2


def test_run_supervisor_returns_zero_iterations_when_sentinel_absent(tmp_path):
    # Arrange — sentinel never created
    profile = _profile(tmp_path)

    def command_runner():
        return FakeProcess()

    # Act
    iterations = run_supervisor(
        profile, command_runner=command_runner, sleep_fn=lambda s: None
    )
    # Assert
    assert iterations == 0


def test_run_supervisor_raises_lock_held_error_for_second_instance(tmp_path):
    # Arrange
    profile = _profile(tmp_path)
    (tmp_path / "sentinel").write_text("")
    held = acquire_lock(profile.lockfile_path)

    def act():
        return run_supervisor(
            profile,
            command_runner=lambda: FakeProcess(),
            sleep_fn=lambda s: None,
            max_iterations=1,
        )

    # Act
    # Assert
    with pytest.raises(LockHeldError):
        act()
    release_lock(held)


def test_run_supervisor_logs_heartbeat_on_start(tmp_path):
    # Arrange
    profile = _profile(tmp_path)
    (tmp_path / "sentinel").write_text("")
    # Act
    run_supervisor(
        profile,
        command_runner=lambda: FakeProcess(),
        sleep_fn=lambda s: None,
        max_iterations=1,
    )
    # Assert
    log_content = open(profile.log_path).read()
    assert "starting" in log_content


def test_run_supervisor_logs_exit_rc(tmp_path):
    # Arrange
    profile = _profile(tmp_path)
    (tmp_path / "sentinel").write_text("")
    # Act
    run_supervisor(
        profile,
        command_runner=lambda: FakeProcess(rc=7),
        sleep_fn=lambda s: None,
        max_iterations=1,
    )
    # Assert
    log_content = open(profile.log_path).read()
    assert "exited rc=7" in log_content


# ---------------------------------------------------------------------------
# Health-check-triggers-restart logic (health checker is always injected)
# ---------------------------------------------------------------------------
def test_monitor_health_kills_process_after_threshold_failures(tmp_path):
    # Arrange
    profile = _profile(
        tmp_path,
        health_check_url="http://fake/health",
        unhealthy_threshold=2,
        health_check_interval=0,
    )
    process = FakeProcess(exit_after_polls=100)
    always_unhealthy = lambda url, timeout: False

    # Act
    result = monitor_health_until_unhealthy(
        profile,
        process,
        health_checker=always_unhealthy,
        sleep_fn=lambda s: None,
        max_checks=10,
    )
    # Assert
    assert result.restarted is True


def test_monitor_health_kill_actually_terminates_fake_process(tmp_path):
    # Arrange
    profile = _profile(
        tmp_path,
        health_check_url="http://fake/health",
        unhealthy_threshold=1,
        health_check_interval=0,
    )
    process = FakeProcess(exit_after_polls=100)
    always_unhealthy = lambda url, timeout: False

    # Act
    monitor_health_until_unhealthy(
        profile,
        process,
        health_checker=always_unhealthy,
        sleep_fn=lambda s: None,
        max_checks=10,
    )
    # Assert
    assert process.poll() is not None


def test_monitor_health_does_not_restart_when_healthy(tmp_path):
    # Arrange
    profile = _profile(
        tmp_path,
        health_check_url="http://fake/health",
        unhealthy_threshold=2,
        health_check_interval=0,
    )
    process = FakeProcess(exit_after_polls=3)
    always_healthy = lambda url, timeout: True

    # Act
    result = monitor_health_until_unhealthy(
        profile,
        process,
        health_checker=always_healthy,
        sleep_fn=lambda s: None,
        max_checks=10,
    )
    # Assert
    assert result.restarted is False


def test_monitor_health_noop_when_no_url_configured(tmp_path):
    # Arrange
    profile = _profile(tmp_path, health_check_url=None)
    process = FakeProcess(exit_after_polls=100)
    calls = []

    def spy_checker(url, timeout):
        calls.append(1)
        return False

    # Act
    monitor_health_until_unhealthy(
        profile, process, health_checker=spy_checker, sleep_fn=lambda s: None
    )
    # Assert — health-checking disabled means the checker is never called
    assert calls == []


def test_monitor_health_resets_failure_count_on_recovery(tmp_path):
    # Arrange
    profile = _profile(
        tmp_path,
        health_check_url="http://fake/health",
        unhealthy_threshold=2,
        health_check_interval=0,
    )
    process = FakeProcess(exit_after_polls=100)
    # Fails once, recovers, then the loop stops (max_checks reached) without
    # ever hitting 2 CONSECUTIVE failures.
    responses = iter([False, True, False])

    def flaky_checker(url, timeout):
        return next(responses, True)

    # Act
    result = monitor_health_until_unhealthy(
        profile,
        process,
        health_checker=flaky_checker,
        sleep_fn=lambda s: None,
        max_checks=3,
    )
    # Assert — never reached the consecutive-failure threshold
    assert result.restarted is False
