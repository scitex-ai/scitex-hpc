"""Pure-Python reference implementation of the sentinel + keep-alive loop.

``._render`` generates the DEPLOYABLE bash supervisor (the artifact you
actually install via cron/systemd/sbatch). This module is a second,
pure-Python implementation of the SAME logic — sentinel-loop restart,
``flock`` single-instance rejection, timestamped heartbeat log, and
endpoint-health-triggers-restart — kept deliberately small and fully
dependency-injected (process launcher, health checker, clock, sleep) so
the *decision logic* is unit-testable without shelling out, without
touching the network, and without real ``sleep`` calls slowing tests
down. It doubles as a Python entrypoint for callers who'd rather run
``python -m scitex_hpc.tunnel_supervisor`` than install the shell script.
"""

from __future__ import annotations

import fcntl
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from ._health import HealthChecker, check_endpoint, default_health_checker
from ._profile import TunnelProfile


class SupervisedProcess(Protocol):
    """Minimal process handle the loop needs (subset of ``subprocess.Popen``)."""

    def poll(self) -> Optional[int]:
        """Return the exit code if finished, else ``None`` (still running)."""

    def wait(self) -> int:
        """Block until the process exits and return its exit code."""

    def kill(self) -> None:
        """Forcibly terminate the process."""


CommandRunner = Callable[[], SupervisedProcess]


# ---------------------------------------------------------------------------
# flock single-instance guard
# ---------------------------------------------------------------------------
class LockHeldError(RuntimeError):
    """Raised when a second supervisor instance can't acquire the lockfile."""


def acquire_lock(lockfile_path: str):
    """Acquire an exclusive, non-blocking ``flock`` on ``lockfile_path``.

    Returns the open file handle (keep it alive — the lock releases when
    it is closed/garbage-collected). Raises :class:`LockHeldError` if
    another process already holds the lock — this is what gives
    single-instance-per-(sentinel/service) semantics: a second
    invocation for the same lockfile never double-launches.
    """
    os.makedirs(os.path.dirname(lockfile_path) or ".", exist_ok=True)
    fh = open(lockfile_path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise LockHeldError(
            f"tunnel-supervisor lock already held: {lockfile_path}"
        ) from exc
    return fh


def release_lock(fh) -> None:
    """Release a lock previously acquired by :func:`acquire_lock`."""
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


# ---------------------------------------------------------------------------
# Sentinel check
# ---------------------------------------------------------------------------
def sentinel_active(sentinel_path: str) -> bool:
    """Return whether the sentinel file exists (loop keeps running while true)."""
    return os.path.exists(sentinel_path)


# ---------------------------------------------------------------------------
# Heartbeat log
# ---------------------------------------------------------------------------
def _now_iso(now_fn: Callable[[], float] = time.time) -> str:
    return (
        datetime.fromtimestamp(now_fn(), tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def append_heartbeat(
    log_path: str,
    message: str,
    *,
    now_fn: Callable[[], float] = time.time,
) -> str:
    """Append a timestamped heartbeat line to ``log_path``; return the line.

    Format: ``[<UTC ISO-8601>] <message>\\n`` — matches the format the
    rendered shell supervisor emits, so forensics reads one consistent
    shape whether the Python or shell implementation was running.
    """
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    line = f"[{_now_iso(now_fn)}] {message}\n"
    with open(log_path, "a") as fh:
        fh.write(line)
    return line


# ---------------------------------------------------------------------------
# Health-check-triggers-restart
# ---------------------------------------------------------------------------
@dataclass
class HealthMonitorResult:
    """Outcome of one round of health-check polling for a running process."""

    restarted: bool
    consecutive_failures: int


def monitor_health_until_unhealthy(
    profile: TunnelProfile,
    process: SupervisedProcess,
    *,
    health_checker: HealthChecker = default_health_checker,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_checks: Optional[int] = None,
) -> HealthMonitorResult:
    """Poll the endpoint while ``process`` runs; kill it if unhealthy.

    Health-checks the CONFIGURED ENDPOINT (``profile.health_check_url``),
    not the process's PID — a hung tunnel with a live PID but a dead
    endpoint still counts unhealthy. After
    ``profile.unhealthy_threshold`` CONSECUTIVE failed checks, kills
    ``process`` (the caller's outer loop then observes the exit and
    restarts). Returns immediately, healthy, if no ``health_check_url``
    is configured (process-exit-triggered restart only) or once the
    process has already exited on its own.

    ``max_checks`` bounds the loop for tests (real callers leave it
    ``None`` and rely on ``process.poll()`` to end the loop when the
    process exits).
    """
    if profile.health_check_url is None:
        return HealthMonitorResult(restarted=False, consecutive_failures=0)

    failures = 0
    checks = 0
    while process.poll() is None:
        if max_checks is not None and checks >= max_checks:
            break
        checks += 1
        sleep_fn(profile.health_check_interval)
        if process.poll() is not None:
            break
        healthy = check_endpoint(
            profile.health_check_url,
            timeout=profile.health_check_timeout,
            checker=health_checker,
        )
        if healthy:
            failures = 0
            continue
        failures += 1
        if failures >= profile.unhealthy_threshold:
            process.kill()
            return HealthMonitorResult(restarted=True, consecutive_failures=failures)
    return HealthMonitorResult(restarted=False, consecutive_failures=failures)


# ---------------------------------------------------------------------------
# The keep-alive loop itself
# ---------------------------------------------------------------------------
def run_supervisor(
    profile: TunnelProfile,
    *,
    command_runner: CommandRunner,
    health_checker: HealthChecker = default_health_checker,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.time,
    max_iterations: Optional[int] = None,
) -> int:
    """Run the sentinel + keep-alive loop; return the iteration count.

    ``while sentinel_active(profile.sentinel_path): <run command_runner()
    to completion, health-monitored>; sleep(restart_backoff)`` — restarts
    the wrapped command every time it exits, for as long as the sentinel
    file exists. Deleting the sentinel is the clean-shutdown signal: the
    loop notices on its next check and exits instead of relaunching.

    Acquires the ``flock`` lock for ``profile.lockfile_path`` up front;
    raises :class:`LockHeldError` if another instance already holds it
    (never double-launches). The lock is released when this function
    returns.

    ``max_iterations`` bounds the loop for tests; real callers leave it
    ``None`` (loop runs until the sentinel is removed).
    """
    lock = acquire_lock(profile.lockfile_path)
    try:
        iterations = 0
        while sentinel_active(profile.sentinel_path):
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            append_heartbeat(
                profile.log_path,
                f"{profile.name} starting: {profile.command}",
                now_fn=now_fn,
            )
            process = command_runner()
            monitor_health_until_unhealthy(
                profile,
                process,
                health_checker=health_checker,
                sleep_fn=sleep_fn,
            )
            rc = process.wait()
            append_heartbeat(
                profile.log_path,
                f"{profile.name} exited rc={rc}; restart in "
                f"{profile.restart_backoff}s",
                now_fn=now_fn,
            )
            if not sentinel_active(profile.sentinel_path):
                break
            sleep_fn(profile.restart_backoff)
        append_heartbeat(
            profile.log_path,
            f"{profile.name} keep-alive loop exiting (sentinel removed)",
            now_fn=now_fn,
        )
        return iterations
    finally:
        release_lock(lock)
