"""The ``lease`` group, its serializer, and the deprecated ``reservations`` alias.

Split out of the former single-module ``_cli/_reservations.py``: that file was
564 lines against the 512 cap BEFORE any change, so it blocked its own §4b
conversion. Command bodies live in the sibling modules.

``_DeprecatedAliasGroup`` delegates ``list_commands``/``get_command`` to its
target at CALL TIME, so the alias reflects whatever is registered on ``lease``
regardless of module import order. Verified before splitting: the root tests
assert object IDENTITY between the alias's commands and lease's.
"""

from __future__ import annotations

import click
from scitex_dev.ecosystem import CliHelp, SpecGroup

from ..._reservation import Reservation


def _serialize(res: Reservation) -> dict:
    return {
        "id": res.id,
        "name": res.name,
        "host": res.host,
        "job_id": res.job_id,
        "node": res.node,
        "submitted_at": res.submitted_at,
        "walltime_end": res.walltime_end,
        "persistent": res.persistent,
    }


@click.group(
    "lease",
    cls=SpecGroup,
    help_spec=CliHelp(
        summary="Persistent SLURM allocations (book once, exec many).",
        description=(
            "The legacy `reservations` command is a deprecated alias for "
            "`lease` and forwards to these same subcommands."
        ),
    ),
)
def lease() -> None:
    pass


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
        "the same book / list / get / exec / refresh / attach / cancel "
        "subcommands."
    ),
)
