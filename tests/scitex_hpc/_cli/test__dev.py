"""``scitex-hpc dev`` — the §13 self-maintenance group.

Doctrine (scitex_dev skill ``general/03_interface/02_cli/20_dev-commands.md``,
an operator directive): a package's top level is its DOMAIN, its own upkeep
mounts under ``dev``. These tests pin the nesting and the migration, not the
verb set — §13 enforces the former and explicitly not the latter.
"""

from __future__ import annotations

import click

from scitex_hpc._cli._dev import dev
from scitex_hpc._cli._root import cli


def test_dev_group_is_registered_on_the_root_cli():
    # Arrange
    ctx = click.Context(cli)
    # Act
    group = cli.get_command(ctx, "dev")
    # Assert
    assert group is not None


def test_skills_is_reachable_under_dev():
    # Arrange
    ctx = click.Context(dev)
    # Act
    cmd = dev.get_command(ctx, "skills")
    # Assert
    assert cmd is not None


def test_dev_is_a_group_not_a_leaf():
    # Arrange — §13: "dev is a group only — it never takes a positional"
    ctx = click.Context(dev)
    # Act
    params = [p for p in dev.params if isinstance(p, click.Argument)]
    # Assert
    assert params == []


def test_dev_is_visible_in_help():
    # Arrange — housekeeping is nested, not hidden; only the ALIAS hides
    ctx = click.Context(cli)
    # Act
    group = cli.get_command(ctx, "dev")
    # Assert
    assert group.hidden is False


def test_legacy_top_level_skills_still_resolves():
    # Arrange — constitution §3: published contract is a MIGRATION, not a rename
    ctx = click.Context(cli)
    # Act
    cmd = cli.get_command(ctx, "skills")
    # Assert
    assert cmd is not None


def test_legacy_top_level_skills_is_hidden():
    # Arrange
    ctx = click.Context(cli)
    # Act
    cmd = cli.get_command(ctx, "skills")
    # Assert — only `dev skills` is advertised
    assert cmd.hidden is True


def test_legacy_skills_alias_warns_naming_dev_skills(capsys):
    # Arrange
    alias = cli.get_command(click.Context(cli), "skills")
    ctx = click.Context(alias, info_name="skills")
    # Act
    alias.get_help(ctx)
    # Assert
    assert "scitex-hpc dev skills" in capsys.readouterr().err
