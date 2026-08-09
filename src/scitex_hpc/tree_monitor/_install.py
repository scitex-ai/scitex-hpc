"""Install the rendered tree-monitor script and its systemd user units.

Mirrors :mod:`scitex_hpc.tunnel_supervisor._install`: rendering is pure
(:mod:`._render`), and THIS module is the only one that writes bytes. The
side-effecting functions are never called implicitly — a caller has to ask
for them by name.

This replaces a README that said "scp these three files, then run
systemctl". Constitution §3: prefer durable automation to manual steps. A
README is followed correctly the first time and approximately after that.

WHAT IS DELIBERATELY NOT AUTOMATED: `systemctl --user enable --now`. The
install writes artifacts; ENABLING a timer that can raise P1 cards on the
shared board is a decision, and :func:`enable_commands` hands the operator
the exact two lines rather than running them. That is the same boundary
tunnel_supervisor draws, and it is the reason a rehearsal cannot
accidentally arm the alarm.
"""

from __future__ import annotations

import os
import stat

from ._profile import EXAMPLE_PROFILE, TreeMonitorProfile
from ._render import render_check_script, render_service_unit, render_timer_unit


def _expand(path: str) -> str:
    """Expand ``$HOME``/``~`` in a profile path. Local-only; no globbing."""
    return os.path.expanduser(os.path.expandvars(path))


def write_check_script(
    profile: TreeMonitorProfile = EXAMPLE_PROFILE,
    target_path: str | None = None,
) -> str:
    """Write the rendered monitor to disk and chmod +x it.

    ``target_path`` defaults to ``profile.script_path`` expanded. Creates
    parent directories. Returns the resolved path for chaining.
    """
    resolved = _expand(target_path or profile.script_path)
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    with open(resolved, "w") as fh:
        fh.write(render_check_script(profile))
    mode = os.stat(resolved).st_mode
    os.chmod(resolved, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return resolved


def write_units(
    profile: TreeMonitorProfile = EXAMPLE_PROFILE,
    unit_dir: str = "$HOME/.config/systemd/user",
) -> tuple[str, str]:
    """Write the ``.service`` and ``.timer`` into ``unit_dir``.

    Returns ``(service_path, timer_path)``. Does NOT reload the daemon or
    enable anything — see :func:`enable_commands`.
    """
    resolved_dir = _expand(unit_dir)
    os.makedirs(resolved_dir, exist_ok=True)
    service_path = os.path.join(resolved_dir, f"{profile.name}.service")
    timer_path = os.path.join(resolved_dir, f"{profile.name}.timer")
    with open(service_path, "w") as fh:
        fh.write(render_service_unit(profile))
    with open(timer_path, "w") as fh:
        fh.write(render_timer_unit(profile))
    return service_path, timer_path


def enable_commands(profile: TreeMonitorProfile = EXAMPLE_PROFILE) -> list[str]:
    """Return the commands that arm the timer, WITHOUT running them.

    Pure string generation. Arming a monitor that can raise P1 cards on the
    shared fleet board is an operator decision, not a side effect of an
    install verb.
    """
    return [
        "systemctl --user daemon-reload",
        f"systemctl --user enable --now {profile.name}.timer",
    ]


def rehearse_command(profile: TreeMonitorProfile = EXAMPLE_PROFILE) -> str:
    """Return the command that exercises the alarm branch WITHOUT carding.

    ``SCITEX_TREE_MONITOR_DRYRUN=1`` is the flag that exists because a test
    run once put a real P1 alarm card on the shared board. Surfacing the
    rehearsal as a first-class verb is the difference between a safe path
    that is documented and a safe path that is used.
    """
    return (
        f"SCITEX_TREE_MONITOR_DRYRUN=1 bash {profile.script_path}"
    )


def install(
    profile: TreeMonitorProfile = EXAMPLE_PROFILE,
    *,
    unit_dir: str = "$HOME/.config/systemd/user",
) -> dict[str, object]:
    """Write script + units and return what was written and what remains.

    Returns a FIXED SHAPE every time — ``script``, ``service``, ``timer``,
    ``enable`` (commands not run), ``rehearse`` — so a caller never has to
    guess which keys exist on this call. Constitution §2: answer in a fixed,
    declared shape.
    """
    script = write_check_script(profile)
    service, timer = write_units(profile, unit_dir)
    return {
        "script": script,
        "service": service,
        "timer": timer,
        "enable": enable_commands(profile),
        "rehearse": rehearse_command(profile),
    }
