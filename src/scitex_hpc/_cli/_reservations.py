"""``scitex-hpc lease`` group assembly + the deprecated ``reservations`` alias.

This module owns three things and nothing else:

  1. the ``lease`` :class:`click.Group` itself;
  2. the EXPLICIT registration of every subcommand onto it — the command
     bodies live in :mod:`_lease_book` (book / adopt, the two verbs that
     create an allocation) and :mod:`_lease_ops` (list / get / exec /
     sync-state / attach / close, which operate on one that exists);
  3. the deprecated ``reservations`` alias group.

Registration is by ``add_command``, not by importing a module for its
decorator side effects: importing ``_lease_book`` never mutates a group,
so there is no import-order surprise and no cycle (the command modules do
not import this one).

``lease`` is the primary, documented command name. ``reservations`` is
kept as a **deprecated alias** that delegates to the same subcommands
(see :class:`_DeprecatedAliasGroup` / :data:`reservations`) so existing
callers keep working; it prints a one-line deprecation notice to stderr.

The canonical verbs are ``sync-state`` (reconcile the local lease record
from ``squeue``) and ``close`` (``scancel`` + lease cleanup). Their older
spellings — ``refresh``, ``cancel``, ``release`` — stay registered as
hidden, warning aliases for one minor-version cycle.
"""

from __future__ import annotations

import click

from ._deprecated_group import deprecated_alias_group
from ._lease_book import adopt_cmd, book_cmd
from ._lease_ops import (
    attach_cmd,
    cancel_alias,
    close_cmd,
    exec_cmd,
    get_cmd,
    list_cmd,
    refresh_alias,
    release_alias,
    sync_state_cmd,
)


@click.group("lease")
def lease() -> None:
    """Persistent SLURM allocations (book once, exec many).

    \b
    Note: the legacy ``reservations`` command is a deprecated alias for
    ``lease`` and forwards to these same subcommands.
    """


for _cmd in (
    # canonical
    book_cmd,
    adopt_cmd,
    list_cmd,
    get_cmd,
    exec_cmd,
    sync_state_cmd,
    attach_cmd,
    close_cmd,
    # deprecated spellings — hidden, warn once, same bodies
    refresh_alias,
    cancel_alias,
    release_alias,
):
    lease.add_command(_cmd)
del _cmd


# ---------------------------------------------------------------------------
# Deprecated alias: ``scitex-hpc reservations`` → ``scitex-hpc lease``
# ---------------------------------------------------------------------------
#
# The alias machinery itself lives in :mod:`_deprecated_group` — it is not
# specific to this group, and a second copy of it is exactly what
# :mod:`_deprecated_verb` was written to avoid on the command side.

reservations = deprecated_alias_group(
    "reservations", target=lease, replacement="scitex-hpc lease"
)
