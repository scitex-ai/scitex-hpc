#!/usr/bin/env python3
"""What this package must SHIP, as opposed to what it merely commits.

Measured 2026-08-30 by building a wheel and listing it: the wheel carried 14
non-``.py`` files -- 13 skill documents and ``login-guard.sh`` -- and not one
systemd unit, watch script, model config or alarm sink. Every one of those
artifacts was committed, referenced by README instructions, and absent from
the installed package.

It was invisible because the Spartan install is EDITABLE: there, the working
tree IS the artifact, so unshipped files are reachable anyway. Converting that
editable install into a proper wheel -- the obvious hygiene fix -- would have
broken the alarm rail. The packaging bug was being masked by the deployment
smell, and fixing the smell first would have caused the outage.

This module states the rule so a test can enforce it, rather than leaving it
as a glob nobody re-reads.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

__all__ = [
    "OPERATIONAL_SUFFIXES",
    "operational_artifacts",
    "package_data_globs",
    "unpackaged_artifacts",
]

#: Suffixes of files a subpackage exists to DELIVER. Documentation (``.md``)
#: is deliberately not here: a missing README is an inconvenience, a missing
#: ``.service`` is a monitor that cannot be installed.
OPERATIONAL_SUFFIXES = frozenset({".sh", ".service", ".timer", ".conf"})

#: Committed Sphinx output and the skills tree, which has its own glob.
_EXCLUDED_TOP = frozenset({"_sphinx_html", "_skills"})


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    """The checkout containing pyproject.toml, or raise saying so."""
    for parent in _package_root().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise FileNotFoundError(
        "no pyproject.toml above "
        f"{_package_root()} — package-data can only be inspected from a "
        "source checkout, not from an installed wheel"
    )


def operational_artifacts() -> list[str]:
    """Package-relative posix paths of every artifact that must ship."""
    root = _package_root()
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in _EXCLUDED_TOP or "__pycache__" in rel.parts:
            continue
        if path.suffix in (".py", ".md"):
            continue
        if path.suffix in OPERATIONAL_SUFFIXES or path.suffix == "":
            found.append(rel.as_posix())
    return found


def package_data_globs() -> list[str]:
    """The ``[tool.setuptools.package-data]`` globs declared for this package."""
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text())
    return list(data["tool"]["setuptools"]["package-data"]["scitex_hpc"])


def _as_regex(glob: str) -> re.Pattern[str]:
    """Translate a setuptools package-data glob to a regex.

    ``**/`` spans directories; ``*`` and ``?`` do not cross a separator.
    """
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def unpackaged_artifacts() -> list[str]:
    """Artifacts that exist on disk and would NOT be installed. Empty is correct."""
    patterns = [_as_regex(g) for g in package_data_globs()]
    return [
        rel
        for rel in operational_artifacts()
        if not any(p.match(rel) for p in patterns)
    ]

# EOF
