"""Smoke tests: fast subprocess-driven CLI happy-path (<60s).

Every test shells out to the installed ``scitex-hpc`` entry-point with an
isolated ``SCITEX_DIR`` so no user state bleeds in. No network, no SSH.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    """Redirect SCITEX_DIR at a tmp dir, restoring prior values after."""
    keys = ("SCITEX_DIR", "SCITEX_HPC_LEASE_DIR", "SCITEX_HPC_HOST")
    prior = {k: os.environ.get(k) for k in keys}
    os.environ["SCITEX_DIR"] = str(tmp_path / "scitex")
    os.environ["SCITEX_HPC_LEASE_DIR"] = str(tmp_path / "leases")
    os.environ.pop("SCITEX_HPC_HOST", None)
    try:
        yield
    finally:
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scitex_hpc", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_version_exits_zero() -> None:
    # Arrange / Act
    proc = _run("--version")
    # Assert
    assert proc.returncode == 0


def test_version_reports_package() -> None:
    # Arrange / Act
    proc = _run("--version")
    # Assert
    assert "scitex-hpc" in proc.stdout


def test_help_exits_zero() -> None:
    # Arrange / Act
    proc = _run("--help")
    # Assert
    assert proc.returncode == 0


def test_help_lists_lease_group() -> None:
    # Arrange / Act
    proc = _run("--help")
    # Assert
    assert "lease" in proc.stdout
