"""End-to-end tests: real subsystems, loopback only, no network.

Gated via ``RUN_E2E=1`` — plain ``pytest`` skips this layer so unit runs
stay hermetic. Each test drives the installed ``scitex-hpc`` CLI in a
subprocess against an isolated ``SCITEX_DIR``.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e

RUN_E2E = os.environ.get("RUN_E2E") == "1"

pytestmark = [pytestmark, pytest.mark.skipif(not RUN_E2E, reason="needs RUN_E2E=1")]


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
        timeout=120,
    )


def test_dev_skills_list_roundtrip() -> None:
    # Arrange / Act — real skill-discovery subsystem, local files only.
    proc = _run("dev", "skills", "list")
    # Assert
    assert proc.returncode == 0


def test_list_python_apis_roundtrip() -> None:
    # Arrange / Act — real introspection over the installed package.
    proc = _run("list-python-apis")
    # Assert
    assert proc.returncode == 0


def test_python_module_entrypoint_parity() -> None:
    # Arrange / Act — `python -m scitex_hpc` must match the console script.
    proc = subprocess.run(
        [sys.executable, "-m", "scitex_hpc", "list-python-apis"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Assert
    assert proc.returncode == 0
