"""Spartan login-node heavy-compute guard — versioned + reproducible.

Incident (2026-07-01): an agent ran the TeX toolchain
(``pdflatex``/``latexmk``) over SSH on a Spartan **login node**, which
UniMelb HPC policy strictly prohibits (admins kill it and can sanction
the whole account). A working guard was already hand-deployed onto the
fleet; this subpackage **versions** it so it can be re-installed
deterministically and reviewed (SSoT + dogfood).

The guard (``login-guard.sh``, vendored verbatim) installs shell
**FUNCTION** overrides for the TeX toolchain that refuse to run on
``spartan-login*`` hosts UNLESS inside a SLURM allocation
(``$SLURM_JOB_ID`` set) — a no-op inside jobs and on compute nodes, so
the CI runner fleet is unaffected. Functions beat both PATH and
``module load`` (a PATH shim cannot).

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

__all__ = [
    "REMOTE_GUARD_PATH",
    "build_bashrc",
    "build_install_script",
    "guard_text",
    "install",
]
