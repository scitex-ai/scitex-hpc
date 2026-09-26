"""Tests for the command-level deprecated-verb aliases (alias-then-remove).

Covers the migration contract rather than the implementation: the canonical
verb is the one ``--help`` shows, the old spelling still runs the SAME body,
and using it prints exactly one notice naming the replacement.

No SSH and no SLURM — every assertion here is about click wiring, so the
commands are inspected through their group rather than invoked against a
cluster.
"""

from __future__ import annotations

import click
import pytest

from scitex_hpc._cli._deprecated_verb import deprecated_verb
from scitex_hpc._cli._quota import quota
from scitex_hpc._cli._reservations import lease, reservations

# (group, old spelling, canonical spelling)
MIGRATIONS = [
    (lease, "refresh", "sync-state"),
    (lease, "cancel", "close"),
    (lease, "release", "close"),
    (quota, "check", "validate"),
]


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_canonical_verb_is_registered(group, old, new):
    # Arrange
    ctx = click.Context(group)
    # Act
    cmd = group.get_command(ctx, new)
    # Assert
    assert cmd is not None


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_old_spelling_still_resolves(group, old, new):
    # Arrange
    ctx = click.Context(group)
    # Act
    cmd = group.get_command(ctx, old)
    # Assert — alias-then-remove: the published verb keeps working
    assert cmd is not None


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_old_spelling_is_hidden_from_help(group, old, new):
    # Arrange
    ctx = click.Context(group)
    # Act
    cmd = group.get_command(ctx, old)
    # Assert — only the canonical name is advertised
    assert cmd.hidden is True


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_alias_shares_the_canonical_callback(group, old, new):
    # Arrange
    ctx = click.Context(group)
    # Act
    alias = group.get_command(ctx, old)
    # Assert — one body, so the alias cannot drift from what it aliases
    assert alias.callback is group.get_command(ctx, new).callback


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_alias_accepts_the_same_options(group, old, new):
    # Arrange
    ctx = click.Context(group)
    # Act
    alias = group.get_command(ctx, old)
    # Assert
    assert [p.name for p in alias.params] == [
        p.name for p in group.get_command(ctx, new).params
    ]


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_using_the_old_spelling_warns_exactly_once(group, old, new, capsys):
    # Arrange
    alias = group.get_command(click.Context(group), old)
    ctx = click.Context(alias, info_name=old)
    # Act — two calls within ONE invocation must not double-print
    alias.get_help(ctx)
    alias.get_help(ctx)
    # Assert
    assert capsys.readouterr().err.count("deprecated") == 1


@pytest.mark.parametrize("group,old,new", MIGRATIONS)
def test_the_warning_names_the_replacement_verb(group, old, new, capsys):
    # Arrange
    alias = group.get_command(click.Context(group), old)
    ctx = click.Context(alias, info_name=old)
    # Act
    alias.get_help(ctx)
    # Assert — an error that only says "deprecated" is half-written
    assert new in capsys.readouterr().err


def test_the_warning_is_keyed_to_the_invocation_not_the_command():
    """A long-lived process invoking the CLI repeatedly must be told each time.

    Keying the flag to the command object would silence every run after the
    first; keying it to the root click Context warns once per invocation.
    """
    # Arrange
    alias = lease.get_command(click.Context(lease), "refresh")
    # Act — an independent context, as a second CLI run would produce
    fresh = click.Context(alias, info_name="refresh")
    # Assert — nothing carried over from any earlier invocation
    assert not hasattr(fresh, "_deprecated_verbs_warned")


def test_deprecated_group_alias_exposes_the_migrated_verbs():
    # Arrange
    ctx = click.Context(reservations)
    # Act — `reservations` forwards to `lease`, so it inherits the new verbs
    cmd = reservations.get_command(ctx, "sync-state")
    # Assert
    assert cmd is not None


def test_deprecated_verb_borrows_context_settings():
    # Arrange
    @click.command("canon", context_settings={"ignore_unknown_options": True})
    @click.argument("thing")
    def canon(thing):
        pass

    # Act
    alias = deprecated_verb(canon, "old-canon", group="demo")
    # Assert — the alias must parse exactly like what it aliases
    assert alias.context_settings == canon.context_settings
