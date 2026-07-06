"""Config-driven HPC login-node guard — reusable across HPC sites.

Incidents (2026-07-01) on UniMelb Spartan: (1) an agent ran the TeX
toolchain (``pdflatex``/``latexmk``) over SSH on a **login node**, which
HPC policy strictly prohibits (admins kill it and can sanction the whole
account); (2) agents ran recursive ``du``/``find`` over the GPFS project
tree (``/data/...``) on login nodes, stressing the metadata disks (reads
as a DoS to storage), which drew admin complaints and fed the 8M-file
quota pressure.

The guard is **GENERALIZED** to any HPC site via a :class:`GuardProfile`
(site-specific login-node patterns, protected FS prefixes, tool lists,
quota hint, srun prefix, texlive bin). :func:`render_guard` GENERATES the
guard shell from a profile (like ``ci_runners`` generates its supervisor
shell) — it installs shell **FUNCTION** overrides that refuse heavy tools
and protected-path ``du``/``find`` walks on a login node UNLESS inside a
SLURM allocation (``$SLURM_JOB_ID`` set). Functions beat both PATH and
``module load`` (a PATH shim cannot). A no-op inside jobs and on compute
nodes, so the CI runner fleet is unaffected.

:data:`SPARTAN_PROFILE` ships as the default profile. A non-Spartan user
defines their own :class:`GuardProfile` and renders a guard from it.

Like ``ci_runners``, this is pure string/transform generation plus a
thin SSH call: nothing runs on import; :func:`install` is the explicit
operator action.
"""

from __future__ import annotations

from ._install import (
    REMOTE_GUARD_PATH,
    build_bashrc,
    build_install_script,
    guard_text,
    install,
)
from ._profile import (
    PROFILES,
    SPARTAN_PROFILE,
    GuardProfile,
    get_profile,
)
from ._render import BLOCKED_RC, BLOCKED_TOKEN, render_guard

__all__ = [
    "BLOCKED_RC",
    "BLOCKED_TOKEN",
    "GuardProfile",
    "PROFILES",
    "REMOTE_GUARD_PATH",
    "SPARTAN_PROFILE",
    "build_bashrc",
    "build_install_script",
    "get_profile",
    "guard_text",
    "install",
    "render_guard",
]
