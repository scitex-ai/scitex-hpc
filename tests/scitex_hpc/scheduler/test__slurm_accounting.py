"""Slurm accounting evidence controls; all transport is an owned recorder."""

from types import SimpleNamespace

import pytest

from scitex_hpc.scheduler import ComputeClient, HostProfile, JobHandle
from scitex_hpc.scheduler._states import slurm_accounting


class _OwnedRunner:
    def __init__(self, text):
        self.results = ["", text]
        self.calls = []

    def __call__(self, host, command):
        self.calls.append((host, command))
        if not self.results:
            raise AssertionError("Unexpected extra transport call")
        return SimpleNamespace(stdout=self.results.pop(0), returncode=0)


def _status(text, through_client):
    runner = _OwnedRunner(text)
    if through_client:
        client = ComputeClient(HostProfile("owned-cluster", "slurm"), runner=runner)
        status = client.status(JobHandle("owned-cluster", "slurm", "123"))
    else:
        status = slurm_accounting(text, "123")
    return status, len(runner.calls)


_SUCCESS = "123|COMPLETED|0:0"
_FAILED = "123|FAILED|1:0"
_RESIZING = "123|RESIZING|0:0"
_UNCERTAIN = [
    (_SUCCESS + "\n" + _FAILED, "multiple"),
    (_FAILED + "\n" + _SUCCESS, "multiple"),
    (_SUCCESS + "\n" + _RESIZING, "multiple"),
    (_RESIZING + "\n" + _SUCCESS, "multiple"),
    (_SUCCESS + "\n" + _SUCCESS, "multiple"),
    (_FAILED + "\n" + _FAILED, "multiple"),
    (_SUCCESS + "\n123|FAILED", "multiple"),
    ("123|FAILED\n" + _SUCCESS, "multiple"),
    ("123||0:0", "state"),
    ("123|   |0:0", "state"),
    ("123|\t|0:0", "state"),
    ("123", "incomplete"),
    ("123|COMPLETED", "incomplete"),
]


@pytest.mark.parametrize("through_client", [False, True])
@pytest.mark.parametrize("text,diagnostic", _UNCERTAIN)
def test_uncertain_slurm_accounting_preserves_unknown(text, diagnostic, through_client):
    # Arrange
    expected_calls = 2 if through_client else 0
    # Act
    status, calls = _status(text, through_client)
    # Assert
    assert (status.state, status.exit_code, diagnostic in status.reason.lower(), calls) == (
        "unknown", None, True, expected_calls,
    )


@pytest.mark.parametrize("through_client", [False, True])
@pytest.mark.parametrize("text,state,exit_code", [
    (_SUCCESS, "succeeded", 0),
    (_FAILED, "failed", 1),
    ("123|COMPLETED|0:9", "failed", 0),
    ("123|CANCELLED by 456|0:15", "cancelled", 0),
    (_SUCCESS + "\n123.batch|FAILED|1:0", "succeeded", 0),
    ("424|FAILED|1:0\n" + _SUCCESS, "succeeded", 0),
    (_RESIZING, "unknown", 0),
])
def test_single_allocation_and_exit_signal_controls(text, state, exit_code, through_client):
    # Arrange
    expected_calls = 2 if through_client else 0
    # Act
    status, calls = _status(text, through_client)
    # Assert
    assert (status.state, status.exit_code, calls) == (state, exit_code, expected_calls)
