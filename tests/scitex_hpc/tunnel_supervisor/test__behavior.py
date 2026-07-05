"""Behavioral tests — run the rendered script under a real bash.

These are NOT mocks of the thing under test: they render the actual
supervisor script and execute it with bash, then observe the sentinel
loop restarting, flock rejecting a second instance, the heartbeat log
format, and a dead ENDPOINT (live PID) triggering a restart. The health
check is injected as a local shell command so no test touches the network.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest

from scitex_hpc.tunnel_supervisor import (
    TunnelSupervisorProfile,
    install_supervisor_script,
)

TS_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] ")


def _bash():
    return "/bin/bash"


def _spawn(script: Path) -> subprocess.Popen:
    # start_new_session so we can kill the whole process group (script +
    # backgrounded health watcher + service child) in teardown.
    return subprocess.Popen(
        [_bash(), str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _install(tmp_path: Path, **over) -> tuple[TunnelSupervisorProfile, Path]:
    base = dict(
        name="itest",
        sentinel_path=str(tmp_path / "sentinel.alive"),
        lockfile_path=str(tmp_path / "svc.lock"),
        log_path=str(tmp_path / "svc.log"),
        launch_command="true",
        health_url="http://127.0.0.1:0/health",
        poll_interval=1,
        restart_backoff=1,
        # Injected: healthy iff the flag file exists (no network).
        health_check_command=f'test -f {tmp_path / "healthy.flag"}',
    )
    base.update(over)
    p = TunnelSupervisorProfile(**base)
    script = install_supervisor_script(p, tmp_path / "sup.sh")
    return p, script


def _wait_for(predicate, timeout=8.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_sentinel_loop_restarts_the_command(tmp_path: Path):
    # Arrange — a launch command that records one line then exits; the loop
    # must relaunch it repeatedly while the sentinel exists.
    counter = tmp_path / "count"
    _p, script = _install(
        tmp_path,
        launch_command=f"sh -c 'echo x >> {counter}; exit 0'",
    )
    Path(_p.sentinel_path).write_text("go\n")
    proc = _spawn(script)
    # Act — let a few restart iterations accumulate, then signal shutdown.
    ran = _wait_for(
        lambda: counter.exists() and len(counter.read_text().split()) >= 3
    )
    Path(_p.sentinel_path).unlink(missing_ok=True)
    _kill(proc)
    # Assert — the command was restarted multiple times (auto-restart works).
    assert ran


def test_flock_rejects_second_instance(tmp_path: Path):
    # Arrange — instance A holds the lock and stays alive; instance B shares
    # the SAME lockfile but a distinct launch marker + log.
    markerA = tmp_path / "A.launched"
    markerB = tmp_path / "B.launched"
    logB = tmp_path / "B.log"
    pA, scriptA = _install(
        tmp_path,
        name="A",
        launch_command=f"sh -c 'echo a >> {markerA}; sleep 30'",
    )
    Path(pA.sentinel_path).write_text("go\n")
    procA = _spawn(scriptA)
    _wait_for(lambda: markerA.exists())
    pB, scriptB = _install(
        tmp_path,
        name="B",
        lockfile_path=pA.lockfile_path,  # same lock -> B must be rejected
        log_path=str(logB),
        launch_command=f"sh -c 'echo b >> {markerB}; sleep 30'",
    )
    Path(pB.sentinel_path).write_text("go\n")
    # Act — B runs to completion quickly because it should refuse and exit 0.
    rcB = subprocess.run([_bash(), str(scriptB)], timeout=10).returncode
    Path(pA.sentinel_path).unlink(missing_ok=True)
    Path(pB.sentinel_path).unlink(missing_ok=True)
    _kill(procA)
    # Assert — B never launched its service (no double-launch under one lock).
    assert not markerB.exists()


def test_flock_rejection_is_logged(tmp_path: Path):
    # Arrange — same as above but assert the rejection was recorded.
    logB = tmp_path / "B.log"
    pA, scriptA = _install(tmp_path, name="A", launch_command="sh -c 'sleep 30'")
    Path(pA.sentinel_path).write_text("go\n")
    procA = _spawn(scriptA)
    _wait_for(lambda: Path(pA.lockfile_path).exists())
    time.sleep(0.3)
    pB, scriptB = _install(
        tmp_path,
        name="B",
        lockfile_path=pA.lockfile_path,
        log_path=str(logB),
        launch_command="sh -c 'sleep 30'",
    )
    Path(pB.sentinel_path).write_text("go\n")
    # Act
    subprocess.run([_bash(), str(scriptB)], timeout=10)
    Path(pA.sentinel_path).unlink(missing_ok=True)
    _kill(procA)
    # Assert
    assert "not double-launching" in logB.read_text()


def test_heartbeat_log_lines_are_timestamped(tmp_path: Path):
    # Arrange
    _p, script = _install(tmp_path, launch_command="sh -c 'exit 0'")
    Path(_p.sentinel_path).write_text("go\n")
    proc = _spawn(script)
    # Act — wait for at least one heartbeat line, then stop.
    _wait_for(lambda: Path(_p.log_path).exists() and Path(_p.log_path).read_text())
    Path(_p.sentinel_path).unlink(missing_ok=True)
    _kill(proc)
    lines = [ln for ln in Path(_p.log_path).read_text().splitlines() if ln.strip()]
    # Assert — every heartbeat line carries an ISO-8601-UTC timestamp prefix.
    assert lines and all(TS_RE.match(ln) for ln in lines)


def test_dead_endpoint_with_live_pid_triggers_restart(tmp_path: Path):
    # Arrange — a long-lived service (live PID) that is HEALTHY initially,
    # so the loop does NOT restart it while the endpoint is up.
    counter = tmp_path / "starts"
    flag = tmp_path / "healthy.flag"
    flag.write_text("ok\n")  # endpoint healthy
    _p, script = _install(
        tmp_path,
        launch_command=f"sh -c 'echo s >> {counter}; sleep 30'",
        health_check_command=f"test -f {flag}",
        poll_interval=1,
        restart_backoff=1,
    )
    Path(_p.sentinel_path).write_text("go\n")
    proc = _spawn(script)
    _wait_for(lambda: counter.exists() and len(counter.read_text().split()) == 1)
    time.sleep(2.5)  # healthy window: live PID must NOT be restarted
    healthy_starts = len(counter.read_text().split())
    # Act — kill the endpoint (PID stays alive); watcher must restart it.
    flag.unlink()
    restarted = _wait_for(
        lambda: len(counter.read_text().split()) > healthy_starts, timeout=8
    )
    Path(_p.sentinel_path).unlink(missing_ok=True)
    _kill(proc)
    # Assert — a live PID behind a dead endpoint was restarted.
    assert restarted


def test_healthy_live_pid_is_not_restarted(tmp_path: Path):
    # Arrange — endpoint stays healthy; a live service must be left alone.
    counter = tmp_path / "starts"
    flag = tmp_path / "healthy.flag"
    flag.write_text("ok\n")
    _p, script = _install(
        tmp_path,
        launch_command=f"sh -c 'echo s >> {counter}; sleep 30'",
        health_check_command=f"test -f {flag}",
        poll_interval=1,
        restart_backoff=1,
    )
    Path(_p.sentinel_path).write_text("go\n")
    proc = _spawn(script)
    _wait_for(lambda: counter.exists() and len(counter.read_text().split()) == 1)
    # Act — observe across several health polls with the endpoint healthy.
    time.sleep(3.0)
    starts = len(counter.read_text().split())
    Path(_p.sentinel_path).unlink(missing_ok=True)
    _kill(proc)
    # Assert — no spurious restart while the endpoint is healthy.
    assert starts == 1


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="bash required")
def test_deleting_sentinel_stops_the_loop(tmp_path: Path):
    # Arrange
    _p, script = _install(tmp_path, launch_command="sh -c 'exit 0'")
    Path(_p.sentinel_path).write_text("go\n")
    proc = _spawn(script)
    _wait_for(lambda: Path(_p.log_path).exists() and Path(_p.log_path).read_text())
    # Act — remove the sentinel; the supervisor process must terminate.
    Path(_p.sentinel_path).unlink(missing_ok=True)
    stopped = _wait_for(lambda: proc.poll() is not None, timeout=8)
    _kill(proc)
    # Assert
    assert stopped
