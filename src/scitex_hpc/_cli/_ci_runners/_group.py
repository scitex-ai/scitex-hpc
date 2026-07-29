"""The ``ci-runners`` group, its shared defaults, and fleet discovery.

Split out of the former single-module ``_cli/_ci_runners.py`` when the
§4b ``CliHelp`` migration pushed that file past the 512-line cap. Command
bodies live in the sibling modules; this holds only what they all need.
"""

from __future__ import annotations

import click
from scitex_dev.ecosystem import CliHelp, SpecGroup

from ...ci_runners import FleetSpec, parse_runner_dirs

# Spartan default CI base (overridable). Documented, not magic: this is
# where the 72 install dirs live today.
_DEFAULT_CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"
_DEFAULT_LEASE_NAME = "spartan-ci-runner-fleet"


@click.group(
    "ci-runners",
    cls=SpecGroup,
    help_spec=CliHelp(
        summary="Durable self-hosted GitHub Actions runner fleet on SLURM.",
        description=(
            "Replaces the login-node band-aids: one dedicated allocation "
            "hosts all runners under auto-restart keep-alive loops, with a "
            "cron health monitor that alarms the operator on failure. The "
            "CLI only ever READS the cluster (discover) or PRINTS plans and "
            "scripts — submission and archival are explicit operator actions "
            "behind --confirm or hand-running the generated script."
        ),
    ),
)
def ci_runners() -> None:
    pass


def _discover(host: str, ci_base: str, exclude: tuple[str, ...]) -> FleetSpec:
    """Read the CI base dir over SSH and build a FleetSpec.

    Light ``ls`` only (admin-flagged: no recursive scans on the login
    node).
    """
    from scitex_ssh import exec_remote

    out = exec_remote(host, f"bash -lc 'ls {ci_base} 2>/dev/null'")
    runners = parse_runner_dirs(out.stdout or "", ci_base=ci_base)
    return FleetSpec(ci_base=ci_base, runners=runners, exclude=exclude)
