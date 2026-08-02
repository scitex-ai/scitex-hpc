"""Command-level deprecated aliases — the verb counterpart to
``_reservations._DeprecatedAliasGroup``.

A published CLI verb is a MIGRATION, not a rename: the old spelling keeps
working for one minor-version cycle while a one-line notice on stderr points
at the new one. :func:`deprecated_verb` builds that alias FROM the canonical
command, so the body, options and arguments have exactly one definition — the
alias cannot drift from what it aliases.

    sync_state_cmd = ...                       # the canonical command
    refresh_cmd = deprecated_verb(sync_state_cmd, "refresh", group="lease")

Aliases are ``hidden=True`` so ``--help`` shows only the canonical name.
"""

from __future__ import annotations

import click

_WARNED_ATTR = "_deprecated_verbs_warned"


def _warn_once(ctx: click.Context, old: str, new: str, group: str) -> None:
    """Emit the deprecation notice at most once per CLI invocation, per verb.

    Keyed to the per-invocation root :class:`click.Context` rather than to the
    long-lived command object, so a long-running process that invokes the CLI
    repeatedly warns on every invocation — and ``get_help`` / ``invoke``, which
    are mutually exclusive within one run, cannot double-print.
    """
    root = ctx.find_root()
    warned = getattr(root, _WARNED_ATTR, None)
    if warned is None:
        warned = set()
        setattr(root, _WARNED_ATTR, warned)
    if old in warned:
        return
    warned.add(old)
    click.echo(
        f"warning: 'scitex-hpc {group} {old}' is deprecated; "
        f"use 'scitex-hpc {group} {new}' instead.",
        err=True,
    )


class _DeprecatedVerb(click.Command):
    """A hidden command that warns, then runs the canonical command's body."""

    def __init__(self, *args, canonical: str, group: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.canonical = canonical
        self.group = group

    def get_help(self, ctx: click.Context) -> str:
        # Fires for ``<group> <old-verb> --help``.
        _warn_once(ctx, self.name, self.canonical, self.group)
        return super().get_help(ctx)

    def invoke(self, ctx: click.Context):
        # Fires for ``<group> <old-verb> ...``.
        _warn_once(ctx, self.name, self.canonical, self.group)
        return super().invoke(ctx)


def deprecated_verb(
    canonical: click.Command, old_name: str, *, group: str
) -> click.Command:
    """Build a hidden alias named ``old_name`` that runs ``canonical``.

    The alias borrows the canonical command's callback, params and context
    settings by reference, so there is nothing to keep in sync: adding an
    option to the canonical verb adds it to the alias in the same edit.
    """
    return _DeprecatedVerb(
        name=old_name,
        callback=canonical.callback,
        params=list(canonical.params),
        context_settings=dict(canonical.context_settings),
        help=f"(deprecated alias) Use ``{group} {canonical.name}`` instead.",
        hidden=True,
        canonical=canonical.name,
        group=group,
    )
