#!/usr/bin/env python3
"""Tests for the venv-wide deploy-drift audit.

Real venv layouts with real ``direct_url.json`` metadata and real git repos.
The failure being fenced is a WRONG ANSWER from real on-disk state -- a
distribution that records a source directory which has moved, or a checkout
that silently never got pulled. A mocked filesystem cannot reproduce either.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from scitex_hpc.deploy_audit import _audit


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _make_editable(venv, name, source):
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    dist = site / f"{name}-1.0.dist-info"
    dist.mkdir(exist_ok=True)
    (dist / "direct_url.json").write_text(
        json.dumps({"url": f"file://{source}", "dir_info": {"editable": True}})
    )
    return dist


def _make_checkout(tmp_path, name):
    origin = tmp_path / f"{name}.git"
    _run("git", "init", "--bare", "-b", "develop", str(origin), cwd=tmp_path)
    author = tmp_path / f"{name}-author"
    _run("git", "clone", str(origin), str(author), cwd=tmp_path)
    _run("git", "-C", str(author), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(author), "config", "user.name", "t", cwd=tmp_path)
    (author / "mod.py").write_text("v1\n")
    _run("git", "-C", str(author), "add", "mod.py", cwd=tmp_path)
    _run("git", "-C", str(author), "commit", "-m", "v1", cwd=tmp_path)
    _run("git", "-C", str(author), "push", "-u", "origin", "develop", cwd=tmp_path)
    deploy = tmp_path / f"{name}-deploy"
    _run("git", "clone", str(origin), str(deploy), cwd=tmp_path)
    return author, deploy


def _advance(author, tmp_path, n=2):
    """Land ``n`` real commits upstream.

    APPENDS rather than overwrites: rewriting the same content leaves nothing
    to commit, and `git commit -am` then fails instead of advancing — which is
    how a "two advances" test silently became a one-advance test.
    """
    target = author / "mod.py"
    for _ in range(n):
        with target.open("a") as handle:
            handle.write("another line\n")
        _run("git", "-C", str(author), "commit", "-am", "advance", cwd=tmp_path)
    _run("git", "-C", str(author), "push", cwd=tmp_path)


@pytest.fixture
def venv(tmp_path):
    return tmp_path / "venv"


def test_editable_installs_are_discovered(venv, tmp_path):
    # Arrange
    _make_editable(venv, "pkg_a", tmp_path / "src_a")
    # Act
    found = _audit.editable_installs(venv)
    # Assert
    assert "pkg_a" in found


def test_non_editable_installs_are_ignored(venv, tmp_path):
    # Arrange — a normal wheel records direct_url only sometimes, and never
    # with editable=true; grading it would be noise
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    dist = site / "pkg_wheel-1.0.dist-info"
    dist.mkdir()
    (dist / "direct_url.json").write_text(
        json.dumps({"url": "file:///somewhere", "dir_info": {"editable": False}})
    )
    # Act
    found = _audit.editable_installs(venv)
    # Assert
    assert found == {}


def test_missing_source_directory_is_its_own_state(venv, tmp_path):
    # Arrange — the compute case: source recorded, directory gone
    _make_editable(venv, "pkg_gone", tmp_path / "definitely-absent")
    # Act
    rows = _audit.audit_venv(venv)
    # Assert
    assert rows[0].state == _audit.STATE_SOURCE_MISSING


def test_missing_source_is_broken_not_drift(venv, tmp_path):
    # Arrange
    _make_editable(venv, "pkg_gone", tmp_path / "definitely-absent")
    # Act
    row = _audit.audit_venv(venv)[0]
    # Assert — a vanished source may not import at all; that is a different
    # fault from running old code, not a more severe grade of it
    assert row.is_broken is True


def test_missing_source_is_not_counted_as_drift(venv, tmp_path):
    # Arrange
    _make_editable(venv, "pkg_gone", tmp_path / "definitely-absent")
    # Act
    row = _audit.audit_venv(venv)[0]
    # Assert
    assert row.is_drift is False


def test_up_to_date_checkout_reports_current(venv, tmp_path):
    # Arrange
    _author, deploy = _make_checkout(tmp_path, "fresh")
    _make_editable(venv, "pkg_fresh", deploy)
    # Act
    row = _audit.audit_venv(venv)[0]
    # Assert
    assert row.state == "current"


def test_stale_checkout_reports_behind(venv, tmp_path):
    # Arrange
    author, deploy = _make_checkout(tmp_path, "stale")
    _advance(author, tmp_path, n=2)
    _make_editable(venv, "pkg_stale", deploy)
    # Act
    row = _audit.audit_venv(venv)[0]
    # Assert
    assert row.state == "behind"


def test_stale_checkout_counts_the_gap(venv, tmp_path):
    # Arrange
    author, deploy = _make_checkout(tmp_path, "stale")
    _advance(author, tmp_path, n=2)
    _make_editable(venv, "pkg_stale", deploy)
    # Act
    row = _audit.audit_venv(venv)[0]
    # Assert
    assert row.behind == 2


def test_summary_counts_drift_separately_from_broken(venv, tmp_path):
    # Arrange — one of each, so a single counter could not satisfy both
    author, deploy = _make_checkout(tmp_path, "mixed")
    _advance(author, tmp_path, n=1)
    _make_editable(venv, "pkg_stale", deploy)
    _make_editable(venv, "pkg_gone", tmp_path / "absent")
    # Act
    counts = _audit.summarize(_audit.audit_venv(venv))
    # Assert
    assert (counts["_drift"], counts["_broken"]) == (1, 1)


def test_summary_totals_every_install(venv, tmp_path):
    # Arrange
    _make_editable(venv, "pkg_one", tmp_path / "absent1")
    _make_editable(venv, "pkg_two", tmp_path / "absent2")
    # Act
    counts = _audit.summarize(_audit.audit_venv(venv))
    # Assert
    assert counts["_total"] == 2


def test_an_empty_venv_audits_to_nothing(venv):
    # Arrange
    (venv / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    # Act
    rows = _audit.audit_venv(venv)
    # Assert — no installs is not a fault, and must not read as one
    assert rows == []

# EOF


def test_signature_ignores_installs_needing_no_action(venv, tmp_path):
    # Arrange — one clean install and nothing else
    _author, deploy = _make_checkout(tmp_path, "clean")
    _make_editable(venv, "pkg_clean", deploy)
    # Act
    sig = _audit.actionable_signature(_audit.audit_venv(venv))
    # Assert
    assert sig == ""


def test_signature_names_the_actionable_install(venv, tmp_path):
    # Arrange
    _make_editable(venv, "pkg_gone", tmp_path / "absent")
    # Act
    sig = _audit.actionable_signature(_audit.audit_venv(venv))
    # Assert
    assert sig == f"pkg_gone:{_audit.STATE_SOURCE_MISSING}"


def test_signature_is_stable_as_a_checkout_falls_further_behind(venv, tmp_path):
    # Arrange — already-known-behind, then more commits land upstream
    author, deploy = _make_checkout(tmp_path, "drifting")
    _advance(author, tmp_path, n=1)
    _make_editable(venv, "pkg_drift", deploy)
    first = _audit.actionable_signature(_audit.audit_venv(venv))
    _advance(author, tmp_path, n=3)
    # Act
    second = _audit.actionable_signature(_audit.audit_venv(venv))
    # Assert — the same standing condition must not re-page every commit
    assert second == first


def test_signature_changes_when_a_new_install_breaks(venv, tmp_path):
    # Arrange
    _make_editable(venv, "pkg_gone", tmp_path / "absent")
    first = _audit.actionable_signature(_audit.audit_venv(venv))
    _make_editable(venv, "pkg_gone_two", tmp_path / "absent2")
    # Act
    second = _audit.actionable_signature(_audit.audit_venv(venv))
    # Assert
    assert second != first


def test_missing_state_file_reads_as_cannot_compare(tmp_path):
    # Arrange — a deleted state file and a first run are the same situation
    target = tmp_path / "never-written.state"
    # Act
    previous = _audit.read_previous_signature(target)
    # Assert — None, NOT "" — "cannot compare" must not read as "was clean"
    assert previous is None


def test_a_written_signature_reads_back(tmp_path):
    # Arrange
    target = tmp_path / "sub" / "deploy-audit.state"
    _audit.write_signature("pkg_x:behind", target)
    # Act
    previous = _audit.read_previous_signature(target)
    # Assert
    assert previous == "pkg_x:behind"


def test_writing_to_an_unwritable_path_does_not_raise(tmp_path):
    # Arrange — best effort: losing the memo must never fail the audit itself
    blocked = tmp_path / "afile"
    blocked.write_text("x")
    target = blocked / "nested" / "state"
    # Act
    _audit.write_signature("pkg_x:behind", target)
    # Assert
    assert _audit.read_previous_signature(target) is None
