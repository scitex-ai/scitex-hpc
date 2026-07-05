"""Generic, reusable tunnel/service supervisor primitive.

A profile-driven keep-alive supervisor for any command that blocks while
a service is alive — an SSH tunnel/port-forward, a dev server, a proxy.
It generalizes the sentinel + keep-alive + flock idiom the CI-runner
:mod:`scitex_hpc.ci_runners._supervisor` bakes into the sbatch hold body,
lifting it out so anything (not just SLURM-hosted runners) can be
supervised.

What a rendered supervisor does:

  * **Sentinel keep-alive loop** — restarts the wrapped launch command
    whenever it exits, for as long as the sentinel file exists. Deleting
    the sentinel is the clean-shutdown signal.
  * **flock single-instance** — only one supervisor per lockfile; a second
    invocation never double-launches.
  * **Timestamped heartbeat log** — a line per start/exit/restart for
    post-hoc blip forensics.
  * **Endpoint health-check** — periodically probes a health URL through
    the tunnel; a live PID with a dead endpoint counts as unhealthy and is
    restarted. We health-check the endpoint, not the PID.

Everything is profile-driven: no hostnames/ports/cluster names are baked
into code (same rule as the rest of ``scitex-hpc``). Render a script from
a :class:`TunnelSupervisorProfile` with
:func:`render_supervisor_script`, or render-and-write it with
:func:`install_supervisor_script`.
"""

from __future__ import annotations

from ._install import default_script_path, install_supervisor_script
from ._profile import (
    DEFAULT_HEALTH_TIMEOUT_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_RESTART_BACKOFF_SECONDS,
    TunnelSupervisorProfile,
)
from ._render import render_supervisor_script

__all__ = [
    "DEFAULT_HEALTH_TIMEOUT_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_RESTART_BACKOFF_SECONDS",
    "TunnelSupervisorProfile",
    "default_script_path",
    "install_supervisor_script",
    "render_supervisor_script",
]
