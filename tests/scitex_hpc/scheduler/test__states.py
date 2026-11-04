"""Scheduler-output controls are synthetic examples, not live site evidence."""

import pytest

from scitex_hpc.scheduler import JobState
from scitex_hpc.scheduler._states import (
    grid_engine_accounting,
    grid_engine_queue,
    slurm_accounting,
    slurm_queue,
)


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
