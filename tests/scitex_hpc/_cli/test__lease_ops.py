"""``lease sync-state --dry-run`` — the mutating-verb contract.

``sync-state`` rewrites the local lease record, so it carries ``--dry-run``
like every other mutating verb in this CLI. The dry run is the REAL answer
withheld, not a description of one: it runs the same squeue query and prints
the record it would have saved, then leaves the stored lease untouched.

No SSH and no SLURM — the runner seam is replaced with a scripted fake, and
``SCITEX_HPC_LEASE_DIR`` is redirected per test.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from scitex_hpc import _reservation as resmod
from scitex_hpc._cli import main
from scitex_hpc._reservation import Reservation


@dataclass
class _Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class _FakeRunner:
    """Returns one scripted result for every call — no SSH."""

    def __init__(self, stdout: str = ""):
        self._result = _Result(stdout=stdout)

    def __call__(self, host, command, *, check=False, timeout=None):
        return self._result


def _noop_sleep(_seconds):
    """Real no-op callable for the sleep seam — not a mock."""
    return None


@pytest.fixture
def lease_dir(tmp_path: Path):
    """Isolate ``SCITEX_HPC_LEASE_DIR`` per test via real env-var mutation."""
    # Arrange
    key = "SCITEX_HPC_LEASE_DIR"
    prior = os.environ.get(key)
    os.environ[key] = str(tmp_path / "leases")
    try:
        yield tmp_path / "leases"
    finally:
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


@pytest.fixture
def stale_lease(lease_dir):
    """A saved lease whose job_id squeue will contradict."""
    # Arrange
    Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
    return "spartan-foo"


def test_dry_run_reports_the_job_id_it_would_write(stale_lease, capsys):
    # Arrange
    runner = _FakeRunner(stdout="200 RUNNING bm175\n")
    # Act
    with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
        main(["lease", "sync-state", stale_lease, "--dry-run", "--json"])
    # Assert — the real squeue answer, not a summary
    assert json.loads(capsys.readouterr().out)["would_write"]["job_id"] == "200"


def test_dry_run_reports_the_value_it_would_replace(stale_lease, capsys):
    # Arrange
    runner = _FakeRunner(stdout="200 RUNNING bm175\n")
    # Act
    with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
        main(["lease", "sync-state", stale_lease, "--dry-run", "--json"])
    # Assert — before AND after, so the blast radius is visible
    assert json.loads(capsys.readouterr().out)["before"]["job_id"] == "42"


def test_dry_run_does_not_persist_the_new_state(stale_lease, capsys):
    # Arrange
    runner = _FakeRunner(stdout="200 RUNNING bm175\n")
    # Act
    with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
        main(["lease", "sync-state", stale_lease, "--dry-run", "--json"])
    # Assert — reloaded from disk, the stored lease is untouched
    assert Reservation.get(stale_lease).job_id == "42"


def test_dry_run_marks_the_fields_that_would_change(stale_lease, capsys):
    # Arrange
    runner = _FakeRunner(stdout="200 RUNNING bm175\n")
    # Act
    with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
        main(["lease", "sync-state", stale_lease, "--dry-run"])
    # Assert — a changed field is starred so the edge is spottable
    assert "* job_id: '42' -> '200'" in capsys.readouterr().out


def test_a_real_run_does_persist_the_new_state(stale_lease, capsys):
    # Arrange
    runner = _FakeRunner(stdout="200 RUNNING bm175\n")
    # Act
    with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
        main(["lease", "sync-state", stale_lease, "--json"])
    # Assert — the control for the three dry-run tests above
    assert Reservation.get(stale_lease).job_id == "200"
