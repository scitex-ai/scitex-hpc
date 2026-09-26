"""Install the rendered tunnel-supervisor script (profile-driven, local).

Mirrors ``login_guard``'s "render then install" shape: :func:`supervisor_text`
renders the script from a profile (pure string generation, nothing runs on
import), :func:`write_supervisor` performs the actual filesystem write +
``chmod +x`` (the explicit, side-effecting step — never called implicitly),
and :func:`cron_line` / :func:`systemd_unit_text` produce the artifacts
needed to register the installed script as a keepalive under cron or a
systemd user unit — again pure string generation, so the caller decides
whether/how to actually wire it in (``crontab``, ``systemctl --user``,
an sbatch script, ...).
"""

from __future__ import annotations

import os
import stat

from ._profile import EXAMPLE_PROFILE, TunnelProfile
from ._render import render_supervisor


def supervisor_text(profile: TunnelProfile = EXAMPLE_PROFILE) -> str:
    """Return the supervisor script generated from ``profile``.

    Thin alias over :func:`~._render.render_supervisor` kept for symmetry
    with ``login_guard.guard_text`` (so callers reach for the same verb
    shape across primitives).
    """
    return render_supervisor(profile)


def write_supervisor(
    profile: TunnelProfile,
    target_path: str,
) -> str:
    """Write the rendered supervisor script to ``target_path`` and chmod +x it.

    Explicit, side-effecting step (creates parent dirs as needed). Returns
    ``target_path`` for convenience chaining.
    """
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    text = supervisor_text(profile)
    with open(target_path, "w") as fh:
        fh.write(text)
    mode = os.stat(target_path).st_mode
    os.chmod(
        target_path,
        mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
    )
    return target_path


def cron_line(
    profile: TunnelProfile,
    script_path: str,
    *,
    schedule: str = "@reboot",
) -> str:
    """Return a crontab line that launches the installed script on ``schedule``.

    Pure string generation — the caller pipes this into ``crontab`` (e.g.
    ``(crontab -l; echo "$(cron_line(...))") | crontab -``) or writes it to
    a drop-in ``/etc/cron.d`` file. Default ``@reboot`` matches the
    keepalive's own restart-loop semantics: it only needs to be (re)started
    once per boot, after which the sentinel-loop keeps it alive.
    """
    return f'{schedule} /bin/bash "{script_path}" >> "{profile.log_path}.cron" 2>&1'


def systemd_unit_text(
    profile: TunnelProfile,
    script_path: str,
) -> str:
    """Return a systemd **user** unit that runs the installed script.

    ``Restart=always`` is intentionally set even though the script has its
    own keep-alive loop: this covers the case where the SUPERVISOR ITSELF
    dies (OOM-killed, node reboot) rather than just the wrapped command.
    Pure string generation; the caller writes it to
    ``~/.config/systemd/user/<name>.service`` and runs
    ``systemctl --user enable --now <name>.service``.
    """
    return f"""[Unit]
Description=scitex-hpc tunnel-supervisor: {profile.name}

[Service]
Type=simple
ExecStart=/bin/bash "{script_path}"
Restart=always
RestartSec={profile.restart_backoff}

[Install]
WantedBy=default.target
"""
