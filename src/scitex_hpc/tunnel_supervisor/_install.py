"""Install a rendered supervisor script to disk.

Thin filesystem side of the primitive: render the profile (pure) then
write the script and make it executable. Kept separate from the renderer
so the string generation stays trivially testable and the only impure
step (writing bytes) is isolated here.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ._profile import TunnelSupervisorProfile
from ._render import render_supervisor_script


def default_script_path(
    profile: TunnelSupervisorProfile, *, base_dir: str | os.PathLike[str] | None = None
) -> Path:
    """Return the default install path for ``profile``'s script.

    ``<base_dir>/scitex-hpc-supervisor-<name>.sh`` — ``base_dir`` defaults
    to the directory holding the profile's log so all of a supervisor's
    artifacts co-locate.
    """
    if base_dir is None:
        base_dir = Path(profile.log_path).parent
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in profile.name)
    return Path(base_dir) / f"scitex-hpc-supervisor-{safe}.sh"


def install_supervisor_script(
    profile: TunnelSupervisorProfile,
    dest: str | os.PathLike[str] | None = None,
    *,
    executable: bool = True,
) -> Path:
    """Render ``profile`` and write the script to ``dest``.

    Returns the path written. ``dest`` defaults to
    :func:`default_script_path`. Parent directories are created. When
    ``executable`` is true (default) the file gets ``+x`` for owner/group/
    other-read so it can be run directly or wired into systemd/cron.
    """
    p = Path(dest) if dest is not None else default_script_path(profile)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_supervisor_script(profile), encoding="utf-8")
    if executable:
        mode = p.stat().st_mode
        p.chmod(
            mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH | stat.S_IRUSR
        )
    return p
