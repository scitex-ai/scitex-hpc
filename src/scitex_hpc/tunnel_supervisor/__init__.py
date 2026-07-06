"""Generic, reusable per-node service/tunnel keepalive supervisor.

Generalized out of the ad-hoc sentinel + keep-alive pattern already used
by this repo's ``ci_runners`` fleet supervisor
(``scitex_hpc.ci_runners._supervisor``) and various one-off SSH-tunnel
keepalive scripts, so a sibling project (e.g. paper-scitex-clew's
``clew-tunnel-supervisor``) can build on this primitive instead of
hand-rolling flock scripts (promised 2026-07-03).

Shape (mirrors ``scitex_hpc.login_guard``): a :class:`TunnelProfile`
supplies every site/service-specific value (sentinel path, lockfile path,
log path, the command to run, health-check URL, poll interval, restart
backoff — no cluster names or hostnames baked into the code). The
primitive RENDERS a shell script from the profile
(:func:`render_supervisor`) and can install it
(:func:`~._install.write_supervisor`, plus cron/systemd-user-unit
artifacts). A pure-Python reference implementation of the same loop
logic (:mod:`._loop`) is also provided, fully dependency-injected
(process launcher, health checker, clock, sleep) for unit testing and
for callers who'd rather run the loop in-process than install the shell
script.

Core guarantees:

  * **Sentinel + keepalive loop** — restarts the wrapped command every
    time it exits, for as long as the sentinel file exists; deleting it
    is the clean-shutdown signal.
  * **flock single-instance semantics** — only one supervisor instance
    per (sentinel path / service name) may run at a time.
  * **Timestamped heartbeat log** — one line per loop iteration for
    post-hoc forensics.
  * **Endpoint health-checking** — periodically probes the configured
    health-check URL (not just the wrapped process's PID); a hung tunnel
    with a live PID but a dead endpoint still triggers a restart.
"""

from __future__ import annotations

from ._health import (
    HealthChecker,
    check_endpoint,
    default_health_checker,
)
from ._install import (
    cron_line,
    supervisor_text,
    systemd_unit_text,
    write_supervisor,
)
from ._loop import (
    HealthMonitorResult,
    LockHeldError,
    SupervisedProcess,
    acquire_lock,
    append_heartbeat,
    monitor_health_until_unhealthy,
    release_lock,
    run_supervisor,
    sentinel_active,
)
from ._profile import (
    EXAMPLE_PROFILE,
    PROFILES,
    TunnelProfile,
    get_profile,
    register_profile,
)
from ._render import render_install_script, render_supervisor

__all__ = [
    "EXAMPLE_PROFILE",
    "HealthChecker",
    "HealthMonitorResult",
    "LockHeldError",
    "PROFILES",
    "SupervisedProcess",
    "TunnelProfile",
    "acquire_lock",
    "append_heartbeat",
    "check_endpoint",
    "cron_line",
    "default_health_checker",
    "get_profile",
    "monitor_health_until_unhealthy",
    "register_profile",
    "release_lock",
    "render_install_script",
    "render_supervisor",
    "run_supervisor",
    "sentinel_active",
    "supervisor_text",
    "systemd_unit_text",
    "write_supervisor",
]
