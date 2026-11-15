"""Scheduler-output controls are synthetic examples, not live site evidence."""

from types import SimpleNamespace

import pytest

from scitex_hpc.scheduler import ComputeClient, HostProfile, JobHandle, JobState
from scitex_hpc.scheduler._states import (
    grid_engine_accounting,
    grid_engine_queue,
    slurm_accounting,
    slurm_queue,
)


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


@pytest.mark.parametrize(
    "state,expected",
    [
        ("PENDING", "queued"),
        ("RUNNING", "running"),
        ("SUSPENDED", "unknown"),
        ("COMPLETED", "unknown"),
    ],
)
def test_slurm_queue_never_invents_completion(state, expected):
    # Arrange
    text = f"123|{state}|reason"
    # Act
    actual = slurm_queue(text, "123")
    # Assert
    assert actual.state == expected


@pytest.mark.parametrize(
    "state,exit_code,expected",
    [
        ("COMPLETED", "0:0", "succeeded"),
        ("COMPLETED", "1:0", "failed"),
        ("COMPLETED", "0:9", "failed"),
        ("COMPLETED", "", "unknown"),
        ("CANCELLED by 1234", "0:15", "cancelled"),
        ("OUT_OF_MEMORY", "137:0", "failed"),
        ("FUTURE_STATE", "0:0", "unknown"),
    ],
)
def test_slurm_terminal_mapping_keeps_exit_signal_evidence(state, exit_code, expected):
    # Arrange
    text = f"123|{state}|{exit_code}"
    # Act
    actual = slurm_accounting(text, "123")
    # Assert
    assert actual.state == expected


@pytest.mark.parametrize(
    "native,expected",
    [
        ("qw", "queued"),
        ("hqw", "queued"),
        ("r", "running"),
        ("Eqw", "unknown"),
        ("dr", "unknown"),
    ],
)
def test_grid_engine_queue_preserves_unclassified_native_state(native, expected):
    # Arrange
    xml = f"<job_info><queue_info><job_list><JB_job_number>123</JB_job_number><state>{native}</state></job_list></queue_info></job_info>"
    # Act
    state = grid_engine_queue(xml, "123")
    # Assert
    assert (state.state, state.native_state) == (expected, native)


@pytest.mark.parametrize(
    "failed,exit_status,expected",
    [
        ("0", "0", "succeeded"),
        ("37 : execd problem", "0", "failed"),
        ("0", "1", "failed"),
        ("0", "undefined", "unknown"),
    ],
)
def test_grid_engine_accounting_needs_both_failed_and_exit_status(
    failed, exit_status, expected
):
    # Arrange
    text = (
        f"jobnumber 123\nfailed {failed}\nexit_status {exit_status}\ntaskid undefined"
    )
    # Act
    actual = grid_engine_accounting(text, "123")
    # Assert
    assert actual.state == expected


@pytest.mark.parametrize(
    "text",
    ["jobnumber 123\nfailed 0\nexit_status 0\ntaskid 1", "jobnumber 123\nfailed 0"],
)
def test_accounting_array_and_missing_exit_are_not_collapsed_to_success(text):
    # Arrange
    target = "123"
    # Act
    actual = grid_engine_accounting(text, target)
    # Assert
    assert actual.state == "unknown"


def test_xml_parse_failure_is_explicit():
    # Arrange
    invalid = "connection refused"
    # Act
    parse = grid_engine_queue
    # Assert
    with pytest.raises(ValueError, match="Invalid"):
        parse(invalid, "123")


@pytest.mark.parametrize(
    "parse,text",
    [
        (slurm_queue, "124|RUNNING|node"),
        (slurm_accounting, "123.batch|COMPLETED|0:0"),
        (grid_engine_accounting, "jobnumber 124\nfailed 0\nexit_status 0"),
    ],
)
def test_another_job_or_step_does_not_establish_parent_success(parse, text):
    # Arrange
    target = "123"
    # Act
    result = parse(text, target)
    # Assert
    assert result is None or result.state == JobState.UNKNOWN
