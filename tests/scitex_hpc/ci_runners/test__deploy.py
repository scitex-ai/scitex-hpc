#!/usr/bin/env python3
"""Tests for the deploy-drift check.

Real git repositories, no mocks: the bug being fenced was a WRONG ANSWER
from a real checkout, and a mocked git cannot reproduce a wrong answer it
was told to give.
"""

from __future__ import annotations

import subprocess

import pytest

from scitex_hpc.ci_runners._deploy import inspect_deploy


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _advance_origin(author, tmp_path, n=3):
    for i in range(n):
        (author / "mod.py").write_text(f"v{i + 2}\n")
        _run("git", "-C", str(author), "commit", "-am", f"v{i + 2}", cwd=tmp_path)
    _run("git", "-C", str(author), "push", cwd=tmp_path)


@pytest.fixture
def deployment(tmp_path):
    """An origin, an author clone, and a clone standing in for the deploy site."""
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", "-b", "develop", str(origin), cwd=tmp_path)

    author = tmp_path / "author"
    _run("git", "clone", str(origin), str(author), cwd=tmp_path)
    _run("git", "-C", str(author), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(author), "config", "user.name", "t", cwd=tmp_path)
    (author / "mod.py").write_text("v1\n")
    _run("git", "-C", str(author), "add", "mod.py", cwd=tmp_path)
    _run("git", "-C", str(author), "commit", "-m", "v1", cwd=tmp_path)
    _run("git", "-C", str(author), "push", "-u", "origin", "develop", cwd=tmp_path)

    deploy = tmp_path / "deploy"
    _run("git", "clone", str(origin), str(deploy), cwd=tmp_path)
    return author, deploy, tmp_path


def test_up_to_date_checkout_is_state_current(deployment):
    # Arrange
    _author, deploy, _tmp = deployment
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.state == "current"


def test_up_to_date_checkout_is_not_drift(deployment):
    # Arrange
    _author, deploy, _tmp = deployment
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.is_drift is False


def test_stale_checkout_reports_state_behind(deployment):
    # Arrange — the Spartan case: clean tree, no local commits, never pulled
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.state == "behind"


def test_stale_checkout_counts_the_commit_gap(deployment):
    # Arrange
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.behind == 3


def test_stale_checkout_is_reported_as_drift(deployment):
    # Arrange
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.is_drift is True


def test_behind_detail_names_the_deploy_command(deployment):
    # Arrange — the detail must carry the FIX, not only the diagnosis
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert "pull --ff-only" in state.detail


def test_without_fetch_stale_checkout_looks_current(deployment):
    # Arrange — a drift check that trusts a stale remote-tracking ref
    # reports "current" forever, which is the failure being prevented.
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)
    # Act
    state = inspect_deploy(deploy / "mod.py", fetch=False)
    # Assert
    assert state.state == "current"


def test_with_fetch_stale_checkout_is_seen(deployment):
    # Arrange
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)
    # Act
    state = inspect_deploy(deploy / "mod.py", fetch=True)
    # Assert — so the fetch is load-bearing, not decoration
    assert state.state == "behind"


def _diverge(deployment):
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=2)
    _run("git", "-C", str(deploy), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(deploy), "config", "user.name", "t", cwd=tmp_path)
    (deploy / "local.py").write_text("local\n")
    _run("git", "-C", str(deploy), "add", "local.py", cwd=tmp_path)
    _run("git", "-C", str(deploy), "commit", "-m", "local", cwd=tmp_path)
    return deploy


def test_diverged_checkout_reports_state_diverged(deployment):
    # Arrange — "behind" and "diverged" are identical from one side
    deploy = _diverge(deployment)
    # Act
    state = inspect_deploy(deploy / "local.py")
    # Assert
    assert state.state == "diverged"


def test_diverged_checkout_counts_local_commits(deployment):
    # Arrange
    deploy = _diverge(deployment)
    # Act
    state = inspect_deploy(deploy / "local.py")
    # Assert — work that exists nowhere else must be visible
    assert state.ahead == 1


def test_diverged_detail_warns_pull_will_not_fast_forward(deployment):
    # Arrange
    deploy = _diverge(deployment)
    # Act
    state = inspect_deploy(deploy / "local.py")
    # Assert
    assert "NOT fast-forward" in state.detail


def test_wheel_install_reports_not_a_checkout(tmp_path):
    # Arrange — a real wheel install has nothing to compare
    plain = tmp_path / "site-packages"
    plain.mkdir()
    (plain / "mod.py").write_text("x\n")
    # Act
    state = inspect_deploy(plain / "mod.py")
    # Assert
    assert state.state == "not-a-checkout"


def test_wheel_install_is_not_reported_as_drift(tmp_path):
    # Arrange
    plain = tmp_path / "site-packages"
    plain.mkdir()
    (plain / "mod.py").write_text("x\n")
    # Act
    state = inspect_deploy(plain / "mod.py")
    # Assert — "nothing to compare" is not a fault
    assert state.is_drift is False


def test_unreachable_origin_never_reports_drift(deployment, tmp_path):
    # Arrange — a network blip must not page anyone about deployment
    _author, deploy, _tmp = deployment
    _run(
        "git", "-C", str(deploy), "remote", "set-url", "origin",
        str(tmp_path / "gone.git"), cwd=tmp_path,
    )
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.is_drift is False


def _rename_deploy_branch(deployment):
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=2)
    # Renamed locally; it still tracks origin/develop.
    _run("git", "-C", str(deploy), "branch", "-m", "deployed", cwd=tmp_path)
    return deploy


def test_renamed_branch_still_detects_drift(deployment):
    # Arrange — assuming origin/<same-name> graded this "unknown", i.e.
    # silently blind, which is the outcome this module exists to prevent.
    deploy = _rename_deploy_branch(deployment)
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.state == "behind"


def test_renamed_branch_reports_its_local_name(deployment):
    # Arrange
    deploy = _rename_deploy_branch(deployment)
    # Act
    state = inspect_deploy(deploy / "mod.py")
    # Assert
    assert state.branch == "deployed"

# EOF
