"""Shared discovery + output helpers for the ``scitex-hpc ci-runners`` commands.

:func:`discover_fleet` is the SINGLE place the CLI reads the cluster, and
therefore the single seam a test replaces to run the whole group without SSH.
Callers reach it through this module (``_common.discover_fleet(...)``) rather
than importing the function by name, so swapping the attribute here takes
effect for every command regardless of which module the command lives in.
"""

from __future__ import annotations

import json as _json

import click

from ..ci_runners import FleetSpec, parse_runner_dirs

# Spartan default CI base (overridable). Documented, not magic: this is
# where the 72 install dirs live today.
DEFAULT_CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"
DEFAULT_LEASE_NAME = "spartan-ci-runner-fleet"


def discover_fleet(host: str, ci_base: str, exclude: tuple[str, ...]) -> FleetSpec:
    """Read the CI base dir over SSH and build a FleetSpec.

    Light ``ls`` only (admin-flagged: no recursive scans on the login
    node).
    """
    from scitex_ssh import exec_remote

    out = exec_remote(host, f"bash -lc 'ls {ci_base} 2>/dev/null'")
    runners = parse_runner_dirs(out.stdout or "", ci_base=ci_base)
    return FleetSpec(ci_base=ci_base, runners=runners, exclude=exclude)


def emit_script(script: str, out_path: str | None, as_json: bool) -> None:
    """Write ``script`` to ``out_path`` (chmod +x) or echo it; JSON-wrap if asked."""
    if out_path:
        from pathlib import Path

        p = Path(out_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(script)
        p.chmod(0o755)
        click.echo(_json.dumps({"wrote": str(p)}) if as_json else f"wrote {p}")
    else:
        click.echo(_json.dumps({"script": script}) if as_json else script)
