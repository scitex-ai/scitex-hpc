"""Profile descriptor for the generic tunnel/service supervisor.

A :class:`TunnelSupervisorProfile` is a pure-data description of ONE
supervised endpoint: where its sentinel/lockfile/log live, the command
that launches the service (an SSH tunnel, a dev server, a port-forward —
anything that blocks while alive), and the health URL to poll through it.

No cluster names, hostnames, or ports are baked in here — the operator
supplies every site-specific value through the profile, exactly like
:class:`scitex_hpc.ci_runners.FleetSpec` does for the runner fleet. The
render/install layer turns a profile into a shell script; this module is
just the parameter object, so it is trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

# How often the health watcher curls the endpoint (seconds). Short enough
# that a wedged tunnel is caught within a poll, long enough not to hammer
# the health route.
DEFAULT_POLL_INTERVAL_SECONDS = 30

# How long the keep-alive loop waits before relaunching a service whose
# launch command just exited. Avoids a hot crash-loop; a transient blip
# still self-heals within the backoff.
DEFAULT_RESTART_BACKOFF_SECONDS = 15

# curl --max-time for a single health probe. A probe that hangs past this
# counts as unhealthy (a live PID behind a wedged endpoint is exactly the
# failure mode we exist to catch).
DEFAULT_HEALTH_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class TunnelSupervisorProfile:
    """One supervised tunnel/service.

    Attributes
    ----------
    name:
        Human tag for this supervisor (used in log lines and the default
        script filename). Must be non-empty.
    sentinel_path:
        Path to the sentinel file. The supervisor runs for as long as this
        file exists; deleting it is the clean-shutdown signal.
    lockfile_path:
        Path to the ``flock`` lockfile enforcing single-instance. A second
        invocation that cannot take the lock exits without double-launching.
    log_path:
        Path to the timestamped heartbeat log the loop appends to.
    launch_command:
        The shell command that starts the service/tunnel. It MUST block
        while the service is alive (e.g. ``ssh -N -L ...``); when it exits
        the loop restarts it. Rendered verbatim into the script.
    health_url:
        The endpoint the watcher probes (e.g.
        ``http://127.0.0.1:8080/health``). A live PID with a dead endpoint
        counts as unhealthy and triggers a restart.
    poll_interval:
        Seconds between health probes.
    restart_backoff:
        Seconds to wait before relaunching after the service exits.
    health_timeout:
        ``curl --max-time`` for a single probe (seconds).
    health_check_command:
        Optional override for the health probe. When ``None`` the renderer
        builds a ``curl -fsS --max-time <health_timeout> <health_url>``
        probe. Supplying an explicit command makes the health check
        injectable — tests pass a local stub so they never touch the
        network, and operators can swap in an auth'd/custom probe.
    """

    name: str
    sentinel_path: str
    lockfile_path: str
    log_path: str
    launch_command: str
    health_url: str
    poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS
    restart_backoff: int = DEFAULT_RESTART_BACKOFF_SECONDS
    health_timeout: int = DEFAULT_HEALTH_TIMEOUT_SECONDS
    health_check_command: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("TunnelSupervisorProfile.name must be non-empty")
        for field_name in (
            "sentinel_path",
            "lockfile_path",
            "log_path",
            "launch_command",
            "health_url",
        ):
            if not getattr(self, field_name):
                raise ValueError(
                    f"TunnelSupervisorProfile.{field_name} must be non-empty"
                )
        for field_name in ("poll_interval", "restart_backoff", "health_timeout"):
            if getattr(self, field_name) <= 0:
                raise ValueError(
                    f"TunnelSupervisorProfile.{field_name} must be positive"
                )

    def health_probe(self) -> str:
        """Return the shell command that exits 0 iff the endpoint is healthy.

        Uses ``health_check_command`` verbatim when set; otherwise builds a
        ``curl`` probe from ``health_url`` + ``health_timeout``.
        """
        if self.health_check_command:
            return self.health_check_command
        return f'curl -fsS --max-time {self.health_timeout} "{self.health_url}"'
