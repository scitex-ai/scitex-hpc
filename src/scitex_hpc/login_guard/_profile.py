"""Site PROFILE for the HPC login-node guard (config-driven, reusable).

The guard logic is identical across HPC sites — refuse heavy compute /
recursive metadata walks on a LOGIN node, allow everything inside a SLURM
job or on a compute node. Only the *values* differ per site: which hosts
are login nodes, which filesystem prefixes are expensive to walk, which
texlive bin path to use, etc.

This module captures those site-specific values in a frozen
:class:`GuardProfile` dataclass so the guard can be GENERALIZED to any HPC
site. :data:`SPARTAN_PROFILE` ships as the default (UniMelb Spartan).

A non-Spartan user defines their own profile and renders a guard from it::

    from scitex_hpc.login_guard import GuardProfile, render_guard

    my_site = GuardProfile(
        name="gadi",
        login_node_patterns=["gadi-login*"],
        protected_path_prefixes=["/g/data/", "/scratch/"],
        quota_hint_cmd="lquota",
        srun_template=(
            "srun --partition=normal --time=0:30:00 "
            "--cpus-per-task=2 --mem=4G"
        ),
        texbin="/apps/texlive/2023/bin/x86_64-linux",
    )
    guard_sh = render_guard(my_site)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List

# ---------------------------------------------------------------------------
# Spartan defaults (UniMelb). These are the SOURCE-OF-TRUTH site values; the
# renderer templates them into the guard shell.
# ---------------------------------------------------------------------------
SPARTAN_LOGIN_NODE_PATTERNS = [
    "spartan-login*",
    "spartan-gateway*",
    "spartanlogin*",
]
SPARTAN_PROTECTED_PATH_PREFIXES = ["/data/"]
# The TeX toolchain — the heavy-compute incident vector (2026-07-01).
SPARTAN_HEAVY_TOOLS = [
    "xelatex",
    "pdflatex",
    "lualatex",
    "luatex",
    "latex",
    "latexmk",
    "biber",
    "bibtex",
    "makeindex",
    "dvipdfmx",
    "xdvipdfmx",
    "dvips",
    "ps2pdf",
    "tex",
]
SPARTAN_FSWALK_TOOLS = ["du", "find"]
SPARTAN_QUOTA_HINT_CMD = "mmlsquota -j punim2354 punim2354"
SPARTAN_SRUN_TEMPLATE = (
    "srun --partition=cascade --qos=publiccpu --time=0:30:00 "
    "--cpus-per-task=2 --mem=4G"
)
SPARTAN_TEXBIN = (
    "/apps/easybuild-2022/easybuild/software/Compiler/GCCcore/"
    "11.3.0/texlive/20230313/bin/x86_64-linux"
)


@dataclass(frozen=True)
class GuardProfile:
    """Site-specific values for the login-node guard.

    Every field has a Spartan default, so ``GuardProfile()`` is the Spartan
    profile. Override only the fields that differ for another HPC site.

    Fields
    ------
    name
        Short site identifier (e.g. ``"spartan"``); used only in comments.
    login_node_patterns
        ``case``-glob patterns that match a LOGIN-node hostname (the guard
        refuses there, outside a SLURM job). The first pattern's stem is
        also used as the cheap top-level "only meaningful here" no-op gate.
    protected_path_prefixes
        Filesystem prefixes the ``du``/``find`` walk-guard must not let a
        recursive walk target on a login node (checked against each
        argument AND ``$PWD``). Scoped — walks elsewhere still work.
    heavy_tools
        Commands to override as "heavy compute, refuse on login node"
        (the TeX toolchain for Spartan).
    fswalk_tools
        Commands to override with the protected-prefix walk-guard
        (``du``/``find``).
    quota_hint_cmd
        The metadata-only quota/usage query to suggest INSTEAD of a walk.
    srun_template
        The ``srun ...`` prefix that sends work to a compute node.
    texbin
        Absolute texlive ``bin`` path the ``<name>-tex`` helper prepends
        to ``PATH`` inside the srun job.
    """

    name: str = "spartan"
    login_node_patterns: List[str] = field(
        default_factory=lambda: list(SPARTAN_LOGIN_NODE_PATTERNS)
    )
    protected_path_prefixes: List[str] = field(
        default_factory=lambda: list(SPARTAN_PROTECTED_PATH_PREFIXES)
    )
    heavy_tools: List[str] = field(
        default_factory=lambda: list(SPARTAN_HEAVY_TOOLS)
    )
    fswalk_tools: List[str] = field(
        default_factory=lambda: list(SPARTAN_FSWALK_TOOLS)
    )
    quota_hint_cmd: str = SPARTAN_QUOTA_HINT_CMD
    srun_template: str = SPARTAN_SRUN_TEMPLATE
    texbin: str = SPARTAN_TEXBIN

    def replace(self, **changes: object) -> "GuardProfile":
        """Return a copy with ``changes`` applied (thin ``dataclasses.replace``)."""
        return replace(self, **changes)


# The default, ready-to-ship profile.
SPARTAN_PROFILE = GuardProfile()

# Registry so the CLI can look a profile up by name.
PROFILES = {SPARTAN_PROFILE.name: SPARTAN_PROFILE}


def get_profile(name: str = "spartan") -> GuardProfile:
    """Return a built-in profile by name (default: ``spartan``)."""
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(
            f"unknown guard profile {name!r}; known profiles: {known}"
        ) from None
