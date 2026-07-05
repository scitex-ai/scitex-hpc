"""Endpoint health-check for the tunnel-supervisor primitive (Python side).

The RENDERED shell supervisor (see ``._render``) health-checks its
endpoint with ``curl``. This module is the Python-side counterpart used
by :mod:`._loop` (the pure-Python reference supervisor loop) and by
callers who want to health-check a profile's endpoint programmatically
(e.g. a CLI ``healthcheck`` subcommand) without shelling out.

:func:`default_health_checker` is the real network-hitting implementation
(``urllib``-based, no extra dependency). It is always passed as an
explicit, INJECTABLE argument — never called implicitly — so tests can
substitute a fake checker and never touch the network.
"""

from __future__ import annotations

from typing import Callable, Optional

HealthChecker = Callable[[str, float], bool]


def default_health_checker(url: str, timeout: float = 5.0) -> bool:
    """Return ``True`` if ``url`` responds with a 2xx status within ``timeout``s.

    Any exception (connection refused, timeout, DNS failure, non-2xx via
    ``HTTPError``) is treated as unhealthy rather than propagated — a
    health check that raises would crash the supervisor loop instead of
    triggering the restart it exists to cause.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(status) < 300
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 300
    except Exception:
        return False


def check_endpoint(
    url: Optional[str],
    *,
    timeout: float = 5.0,
    checker: HealthChecker = default_health_checker,
) -> bool:
    """Return whether ``url`` is healthy, using the injectable ``checker``.

    ``url is None`` means "no endpoint configured" — treated as healthy
    (health-checking is opt-in per :class:`~._profile.TunnelProfile`).
    """
    if url is None:
        return True
    return checker(url, timeout)
