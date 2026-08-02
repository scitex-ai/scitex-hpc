"""``scitex-hpc dev`` — the one group every self-maintenance surface mounts under.

§13 of the CLI doctrine (``scitex_dev`` skill
``general/03_interface/02_cli/20_dev-commands.md``, an operator directive):
a package's top level is its DOMAIN; its own upkeep is housekeeping and belongs
under ``dev``, so ``scitex-hpc --help`` reads as the tool rather than the tool's
maintenance.

The six reserved verbs are ``daemon`` / ``cron`` / ``systemd`` / ``hooks`` /
``skills`` / ``shell``. scitex-hpc ships one of them today (``skills``); the
doctrine enforces the NESTING, not a fixed verb set, so the group is the
namespace those verbs land in as the package grows rather than a wrapper around
a single command.

``dev`` is a group only — it never takes a positional argument itself.
"""

from __future__ import annotations

import click

from ._skills import skills_group


@click.group("dev")
def dev() -> None:
    """Self-maintenance for scitex-hpc itself (skills, and future upkeep verbs).

    \b
    Housekeeping lives here so the top-level command stays the domain:
    leases, CI runners, quota, walltime, liveness.
    """


dev.add_command(skills_group, name="skills")
