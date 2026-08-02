"""Group-level deprecated aliases.

The load-bearing test here is
``test_alias_exposes_the_targets_commands_to_a_static_reader``. The first
version of this alias delegated ``get_command`` / ``list_commands`` at dispatch
time — correct at runtime, and INVISIBLE to any reader that does not execute
the CLI. The CLI-conventions auditor is such a reader, and it raised three
"missing required subcommand" errors against a `skills` alias that worked
perfectly when invoked. Sharing the target's command objects fixes it; this
test fails if anyone reverts to delegation.
"""

from __future__ import annotations

import click
import pytest

from scitex_hpc._cli._deprecated_group import deprecated_alias_group


@pytest.fixture
def target_group():
    """A populated group to alias."""
    # Arrange
    @click.group("canonical")
    def canonical():
        pass

    @canonical.command("alpha")
    def alpha():
        pass

    @canonical.command("beta")
    def beta():
        pass

    return canonical


@pytest.fixture
def alias(target_group):
    return deprecated_alias_group(
        "legacy", target=target_group, replacement="scitex-hpc canonical"
    )


def test_alias_exposes_the_targets_commands_to_a_static_reader(alias):
    # Arrange — no Context, no dispatch: exactly what the auditor does
    # Act
    names = sorted(alias.commands)
    # Assert
    assert names == ["alpha", "beta"]


def test_alias_shares_the_command_objects_rather_than_copying(alias, target_group):
    # Arrange
    # Act
    shared = alias.commands["alpha"]
    # Assert — one definition; the alias cannot drift from its target
    assert shared is target_group.commands["alpha"]


def test_alias_is_hidden(alias):
    # Arrange
    # Act
    hidden = alias.hidden
    # Assert
    assert hidden is True


def test_using_the_alias_warns_once(alias, capsys):
    # Arrange
    ctx = click.Context(alias, info_name="legacy")
    # Act — twice within ONE invocation
    alias.get_help(ctx)
    alias.get_help(ctx)
    # Assert
    assert capsys.readouterr().err.count("deprecated") == 1


def test_the_warning_names_the_replacement(alias, capsys):
    # Arrange
    ctx = click.Context(alias, info_name="legacy")
    # Act
    alias.get_help(ctx)
    # Assert
    assert "scitex-hpc canonical" in capsys.readouterr().err


def test_two_aliases_warn_independently(target_group, capsys):
    # Arrange — the warn-once flag is per-alias, not global to the invocation
    first = deprecated_alias_group("one", target=target_group, replacement="x")
    second = deprecated_alias_group("two", target=target_group, replacement="y")
    root = click.Context(first, info_name="one")
    # Act — a shared root context, as two aliases in one CLI would have
    first._warn_once(root)
    second._warn_once(root)
    # Assert — the earlier global flag would have silenced the second
    assert capsys.readouterr().err.count("deprecated") == 2
