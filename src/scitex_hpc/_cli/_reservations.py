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

_DEPRECATION_NOTICE = (
    "warning: 'scitex-hpc reservations' is deprecated; use 'scitex-hpc lease' instead."
)


class _DeprecatedAliasGroup(click.Group):
    """Thin alias group that forwards to another (target) group.

    DRY by construction: it does not own any commands. Both
    ``list_commands`` and ``get_command`` delegate to ``self.target``,
    so the alias always exposes exactly the same subcommands as the
    primary group with zero duplicated command bodies. A one-line
    deprecation notice is emitted to stderr when the alias is used —
    including for ``--help`` and the no-subcommand case — without
    altering behavior or exit codes.

    The notice is keyed to the per-invocation click ``Context`` (not to
    the long-lived group instance) so every distinct CLI invocation
    warns exactly once: ``get_help`` and ``invoke`` are mutually
    exclusive within a single run, and the context flag guards against
    the rare double-call.
    """

    def __init__(self, *args, target: click.Group, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target

    @staticmethod
    def _warn_once(ctx: click.Context) -> None:
        root = ctx.find_root()
        if not getattr(root, "_reservations_alias_warned", False):
            root._reservations_alias_warned = True
            click.echo(_DEPRECATION_NOTICE, err=True)

    def list_commands(self, ctx):
        return self.target.list_commands(ctx)

    def get_command(self, ctx, cmd_name):
        return self.target.get_command(ctx, cmd_name)

    def get_help(self, ctx):
        # Fires for ``reservations --help`` and bare ``reservations``.
        self._warn_once(ctx)
        return super().get_help(ctx)

    def invoke(self, ctx):
        # Fires for ``reservations <subcommand> ...``.
        self._warn_once(ctx)
        return super().invoke(ctx)


reservations = _DeprecatedAliasGroup(
    name="reservations",
    target=lease,
    hidden=True,
    help=(
        "(deprecated alias) Use 'scitex-hpc lease' instead. Forwards to "
        "the same book / list / get / exec / sync-state / attach / close "
        "subcommands."
    ),
)
