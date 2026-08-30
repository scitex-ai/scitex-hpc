#!/usr/bin/env python3
"""Real git repos, no mocks — the bug being fenced was a WRONG ANSWER from a
real checkout, and a mocked git cannot reproduce a wrong answer it was told
to give.
"""

from __future__ import annotations

import subprocess

import pytest

from scitex_hpc.ci_runners._deploy import inspect_deploy


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def deployment(tmp_path):
    """An origin, plus a clone standing in for the deploy site."""
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


def _advance_origin(author, tmp_path, n=3):
    for i in range(n):
        (author / "mod.py").write_text(f"v{i + 2}\n")
        _run("git", "-C", str(author), "commit", "-am", f"v{i + 2}", cwd=tmp_path)
    _run("git", "-C", str(author), "push", cwd=tmp_path)


def test_current_deploy_is_not_drift(deployment):
    _author, deploy, _tmp = deployment
    st = inspect_deploy(deploy / "mod.py")
    assert st.state == "current"
    assert st.is_drift is False
    assert st.behind == 0


def test_behind_is_drift_and_counts_the_gap(deployment):
    """The Spartan case: clean tree, no local commits, simply never pulled."""
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)

    st = inspect_deploy(deploy / "mod.py")
    assert st.state == "behind"
    assert st.is_drift is True
    assert st.behind == 3
    assert st.ahead == 0
    # The detail must carry the FIX, not just the diagnosis.
    assert "pull --ff-only" in st.detail


def test_behind_requires_the_fetch(deployment):
    """Without a fetch the deploy site cannot even SEE that it is behind.

    This is the failure the check exists to prevent, so it is asserted
    rather than assumed: a drift check that trusts a stale remote-tracking
    ref reports 'current' forever.
    """
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=3)

    assert inspect_deploy(deploy / "mod.py", fetch=False).state == "current"
    assert inspect_deploy(deploy / "mod.py", fetch=True).state == "behind"


def test_diverged_is_distinguished_from_behind(deployment):
    """'behind' and 'diverged' are identical from one side and call for
    different actions — a plain pull will not fast-forward a diverged tree.
    """
    author, deploy, tmp_path = deployment
    _advance_origin(author, tmp_path, n=2)

    _run("git", "-C", str(deploy), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(deploy), "config", "user.name", "t", cwd=tmp_path)
    (deploy / "local.py").write_text("local\n")
    _run("git", "-C", str(deploy), "add", "local.py", cwd=tmp_path)
    _run("git", "-C", str(deploy), "commit", "-m", "local", cwd=tmp_path)

    st = inspect_deploy(deploy / "local.py")
    assert st.state == "diverged"
    assert st.is_drift is True
    assert st.behind == 2 and st.ahead == 1
    assert "NOT fast-forward" in st.detail


def test_non_checkout_is_not_a_fault(tmp_path):
    """A real wheel install has nothing to compare. That is not drift."""
    plain = tmp_path / "site-packages"
    plain.mkdir()
    (plain / "mod.py").write_text("x\n")

    st = inspect_deploy(plain / "mod.py")
    assert st.state == "not-a-checkout"
    assert st.is_drift is False


def test_unreachable_origin_never_alarms(deployment, tmp_path):
    """A network blip must not page anyone about deployment."""
    _author, deploy, _tmp = deployment
    _run(
        "git", "-C", str(deploy), "remote", "set-url", "origin",
        str(tmp_path / "gone.git"), cwd=tmp_path,
    )
    _advance = inspect_deploy(deploy / "mod.py")
    # Still has its old remote-tracking ref, so it grades 'current' — the
    # point is only that a dead origin does not manufacture an alarm.
    assert _advance.is_drift is False

# EOF


def test_tracks_a_differently_named_upstream(deployment, tmp_path):
    """The deploy site's branch need not share its upstream's name.

    Assuming ``origin/<same-name>`` graded such a checkout 'unknown', i.e.
    silently blind — the single outcome this module exists to prevent.
    """
    author, deploy, tmp_path_ = deployment
    _advance_origin(author, tmp_path_, n=2)

    # Rename the local branch; it still tracks origin/develop.
    _run("git", "-C", str(deploy), "branch", "-m", "deployed", cwd=tmp_path_)

    st = inspect_deploy(deploy / "mod.py")
    assert st.branch == "deployed"
    assert st.state == "behind", f"went blind: {st.state} — {st.detail}"
    assert st.behind == 2
