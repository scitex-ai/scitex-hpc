"""Group-level deprecated aliases — the group counterpart to
:mod:`scitex_hpc._cli._deprecated_verb`.

Same contract as the verb aliases: the old spelling keeps working for one
minor-version cycle and prints a one-line notice to stderr naming its
replacement.

The alias SHARES the target's command objects rather than delegating lookups at
dispatch time. Both are DRY — neither duplicates a command body — but only the
sharing form is visible to a STATIC reader. That matters: the CLI-conventions
auditor introspects ``group.commands``, and a dynamically-delegating alias reads
to it as an EMPTY group, which produced three spurious "missing required
subcommand" errors when this was written the other way.

    reservations = deprecated_alias_group("reservations", target=lease,
                                          replacement="scitex-hpc lease")

Because the commands are shared by reference, the alias cannot drift from its
target; because they are attached at construction time, every group must be
fully populated before its alias is built (all of them are — registration
happens at import).
"""

from __future__ import annotations

import click

_WARNED_ATTR = "_deprecated_groups_warned"


class _DeprecatedAliasGroup(click.Group):
    """A hidden group holding the target's commands, warning once when used.

    The notice is keyed to the per-invocation click ``Context`` rather than to
    the long-lived group instance, so every distinct CLI invocation warns
    exactly once: ``get_help`` and ``invoke`` are mutually exclusive within a
    single run, and the context flag guards the rare double-call.
    """

    def __init__(self, *args, replacement: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.replacement = replacement

    def _warn_once(self, ctx: click.Context) -> None:
        root = ctx.find_root()
        warned = getattr(root, _WARNED_ATTR, None)
        if warned is None:
            warned = set()
            setattr(root, _WARNED_ATTR, warned)
        if self.name in warned:
            return
        warned.add(self.name)
        click.echo(
            f"warning: 'scitex-hpc {self.name}' is deprecated; "
            f"use '{self.replacement}' instead.",
            err=True,
        )

    def get_help(self, ctx):
        # Fires for ``<alias> --help`` and the bare ``<alias>`` case.
        self._warn_once(ctx)
        return super().get_help(ctx)

    def invoke(self, ctx):
        # Fires for ``<alias> <subcommand> ...``.
        self._warn_once(ctx)
        return super().invoke(ctx)


def deprecated_alias_group(
    old_name: str, *, target: click.Group, replacement: str
) -> click.Group:
    """Build a hidden group named ``old_name`` exposing ``target``'s commands.

    ``replacement`` is the full command a user should type instead — spelled
    out (``"scitex-hpc dev skills"``) rather than assembled, because the target
    may be mounted under a different parent than the alias.
    """
    alias = _DeprecatedAliasGroup(
        name=old_name,
        replacement=replacement,
        hidden=True,
        help=f"(deprecated alias) Use '{replacement}' instead.",
    )
    # Share the SAME command objects — one definition, statically visible.
    alias.commands = dict(target.commands)
    return alias
