"""Site/service-agnostic PROFILE for the tunnel-supervisor primitive.

Generalized out of two ad-hoc patterns already living in this repo:
``ci_runners/_supervisor.py`` (sentinel + keep-alive loop for the CI
runner fleet) and the one-off SSH-tunnel keepalive scripts written this
session. Both hand-rolled the same shape — ``while [ -f SENTINEL ]; do
<launch>; sleep N; done`` plus a heartbeat log — for a single, specific
deployment. This module lifts that shape into a reusable
:class:`TunnelProfile` so ANY per-node service/tunnel keepalive
(``clew-tunnel-supervisor`` or any other sibling project) can render its
own supervisor from a profile instead of hand-rolling flock scripts.

No cluster names, hostnames, or ports are baked in here — every value
below is a field with a generic placeholder default. A real user always
supplies their own profile.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TunnelProfile:
    """Profile-driven configuration for one supervised tunnel/service.

    Fields
    ------
    name
        Short identifier for this supervisor instance (used in log lines,
        the default lock/sentinel/log paths, and shell-function naming).
    command
        The shell command that starts the tunnel/service. Runs in the
        FOREGROUND inside the keep-alive loop — it must BLOCK until the
        tunnel/service dies (e.g. ``ssh -N -L 8080:127.0.0.1:8080 host``).
        The string is spliced **raw and unquoted** into the generated loop
        (``( {command} ) & wait $!``) and runs under ``set -u``, so it must
        be a single shell-safe line — the caller is responsible for shell
        quoting. This is the opaque seam: scitex-ssh's ``tunnel render-argv``
        output (a bare ``ssh …`` string) drops in here verbatim; no tunnel
        argv is constructed inside scitex_hpc.
    sentinel_path
        Path to the sentinel file. The keep-alive loop runs
        ``while [ -f sentinel_path ]; do ...; done`` — deleting this file
        is the clean-shutdown signal; the loop notices on its next
        iteration and exits instead of relaunching.
    lockfile_path
        Path to the ``flock`` lockfile. Only one supervisor instance per
        (sentinel / service name) may hold this lock at a time, so a
        second invocation exits immediately instead of double-launching.
    log_path
        Path to the heartbeat log. Every loop iteration (start attempt,
        exit/restart event, health-check failure) appends one
        UTC-timestamped line for post-hoc forensics.
    health_check_url
        URL to poll through the tunnel (e.g.
        ``http://127.0.0.1:8080/health``). When set, the supervisor
        health-checks the ENDPOINT, not just the wrapped process's PID —
        a hung tunnel with a live PID but a dead endpoint still counts as
        unhealthy and triggers a restart. ``None`` disables endpoint
        health-checking (process-exit-triggered restart only).
    health_check_interval
        Seconds between health-check polls while the command is running.
    health_check_timeout
        Per-request timeout (seconds) for the health-check probe.
    unhealthy_threshold
        Number of CONSECUTIVE failed health checks before the supervisor
        kills the wrapped command and restarts it.
    poll_interval
        Seconds the outer loop sleeps between sentinel re-checks when
        idling (not currently running the command).
    restart_backoff
        Seconds to sleep after the command exits (or is killed for being
        unhealthy) before relaunching it.
    """

    name: str = "example-tunnel"
    command: str = "true"
    sentinel_path: str = "/tmp/example-tunnel.sentinel"
    lockfile_path: str = "/tmp/example-tunnel.lock"
    log_path: str = "/tmp/example-tunnel.log"
    health_check_url: str | None = "http://127.0.0.1:8000/health"
    health_check_interval: float = 10.0
    health_check_timeout: float = 5.0
    unhealthy_threshold: int = 3
    poll_interval: float = 5.0
    restart_backoff: float = 5.0

    def replace(self, **changes: object) -> "TunnelProfile":
        """Return a copy with ``changes`` applied (thin ``dataclasses.replace``)."""
        return replace(self, **changes)


# The generic, ready-to-render example profile. Real deployments always
# construct their own ``TunnelProfile`` — this exists so the module has a
# usable default and so tests/docs have something concrete to render.
EXAMPLE_PROFILE = TunnelProfile()

# Registry so a CLI can look a profile up by name (mirrors login_guard).
PROFILES = {EXAMPLE_PROFILE.name: EXAMPLE_PROFILE}


def get_profile(name: str = "example-tunnel") -> TunnelProfile:
    """Return a registered profile by name (default: the example profile)."""
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(
            f"unknown tunnel-supervisor profile {name!r}; known profiles: {known}"
        ) from None


def register_profile(profile: TunnelProfile) -> None:
    """Register ``profile`` in :data:`PROFILES` under its ``name``."""
    PROFILES[profile.name] = profile
