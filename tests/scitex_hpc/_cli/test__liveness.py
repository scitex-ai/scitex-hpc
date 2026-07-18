"""CLI plumbing tests for ``scitex-hpc liveness``.

Only the surface that needs no SLURM contact is exercised here — command
registration, help text, and the usage guard. The decision contract itself
is covered by ``tests/scitex_hpc/test__liveness.py`` through the ``runner=``
DI seam.
"""

from __future__ import annotations

import click

from scitex_hpc._cli import main
from scitex_hpc._cli._liveness import liveness


def test_liveness_group_is_registered_on_the_root_cli(capsys):
    # Arrange
    argv = ["--help"]
    # Act
    main(argv)
    # Assert
    assert "liveness" in capsys.readouterr().out


def test_liveness_help_documents_the_three_verdicts(capsys):
    # Arrange
    argv = ["liveness", "check", "--help"]
    main(argv)
    # Act
    out = capsys.readouterr().out
    # Assert
    assert all(verdict in out for verdict in ("ALIVE", "DEAD", "UNKNOWN"))


def test_check_without_any_identifier_is_a_usage_error():
    # Arrange
    argv = ["liveness", "check"]
    # Act
    code = main(argv)
    # Assert
    assert code == 2


def test_check_usage_error_names_the_required_options(capsys):
    # Arrange
    argv = ["liveness", "check"]
    # Act
    main(argv)
    # Assert
    assert "--job-id" in capsys.readouterr().err


def test_check_command_is_exposed_on_the_group():
    # Arrange
    ctx = click.Context(liveness)
    # Act
    names = liveness.list_commands(ctx)
    # Assert
    assert "check" in names
