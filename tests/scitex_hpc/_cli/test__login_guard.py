"""CLI tests for the ``sentinel`` group (rename + convention flags).

Pure text paths only: ``show`` renders from the profile and ``install``
without ``--yes`` stays in dry-run, so nothing SSHes to a cluster.
"""

from __future__ import annotations

import json

from scitex_hpc._cli import main


def test_group_registered_under_noun_name(capsys):
    # Arrange
    argv = ["sentinel", "--help"]
    # Act
    rc = main(argv)
    # Assert — the audit-§1 noun group name resolves
    out = capsys.readouterr().out
    assert rc == 0 and "install" in out


def test_show_prints_guard_with_blocked_token(capsys):
    # Arrange
    argv = ["sentinel", "show"]
    # Act
    main(argv)
    # Assert — the rendered guard carries the cross-repo [BLOCKED] contract
    out = capsys.readouterr().out
    assert "[BLOCKED]" in out


def test_show_json_emits_object(capsys):
    # Arrange
    argv = ["sentinel", "show", "--json"]
    # Act
    main(argv)
    # Assert — machine-readable output has the documented keys
    out = capsys.readouterr().out
    assert sorted(json.loads(out)) == ["content", "kind", "profile"]


def test_show_json_kind_is_guard_by_default(capsys):
    # Arrange
    argv = ["sentinel", "show", "--json"]
    # Act
    main(argv)
    # Assert
    out = capsys.readouterr().out
    assert json.loads(out)["kind"] == "guard"


def test_install_dry_run_by_default_does_not_deploy(capsys):
    # Arrange — no --yes => dry-run => never SSHes
    argv = ["sentinel", "install", "--host", "spartan"]
    # Act
    rc = main(argv)
    # Assert
    out = capsys.readouterr().out
    assert rc == 0 and "DRY RUN" in out


def test_install_dry_run_prints_install_script(capsys):
    # Arrange
    argv = ["sentinel", "install"]
    # Act
    main(argv)
    # Assert — the dry-run shows the exact install script for review
    out = capsys.readouterr().out
    assert "login-guard.sh" in out
