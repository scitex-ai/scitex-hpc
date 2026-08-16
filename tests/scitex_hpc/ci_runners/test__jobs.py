"""Tests for the scitex_dev.jobs entry-point (CI supervisor watchdog)."""

from __future__ import annotations

import pytest


def test_jobs_module_imports_without_scitex_dev():
    # Arrange
    from scitex_hpc.ci_runners import _jobs
    # Act — the JobSpec import is lazy (inside the callable), so importing
    # the module must NOT require scitex_dev to be installed.
    fn = _jobs.jobs
    # Assert
    assert callable(fn)


def test_jobs_returns_the_ci_supervisor_watch_spec():
    # Arrange — the real JobSpec dataclass lives in scitex_dev
    pytest.importorskip("scitex_dev.jobs")
    from scitex_hpc.ci_runners._jobs import jobs
    # Act
    names = [spec.name for spec in jobs()]
    # Assert
    assert "scitex-hpc-ci-supervisor-watch" in names


def test_jobs_spec_runs_the_watch_command():
    # Arrange
    pytest.importorskip("scitex_dev.jobs")
    from scitex_hpc.ci_runners._jobs import jobs
    # Act
    spec = jobs()[0]
    # Assert — the cron command is the watch entrypoint, not piped bash
    assert spec.command == "scitex-hpc ci-runners watch"


def test_jobs_includes_the_inode_quota_warn_spec():
    # Arrange
    pytest.importorskip("scitex_dev.jobs")
    from scitex_hpc.ci_runners._jobs import jobs
    # Act
    names = [spec.name for spec in jobs()]
    # Assert
    assert "scitex-hpc-inode-quota-warn" in names
