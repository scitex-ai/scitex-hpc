"""Tests for canonical runner registration — the scitex-ci label bake-in."""

from __future__ import annotations

from scitex_hpc.ci_runners import (
    DEFAULT_RUNNER_LABELS,
    REQUIRED_LABEL,
    build_register_command,
    missing_required_labels,
    normalize_labels,
)

URL = "https://github.com/ywatanabe1989/scitex-hpc"


def test_default_labels_include_scitex_ci():
    # Arrange
    labels = DEFAULT_RUNNER_LABELS
    # Act
    present = REQUIRED_LABEL in labels
    # Assert
    assert present is True


def test_normalize_appends_required_when_missing():
    # Arrange
    labels = ["spartan-cpu"]
    # Act
    out = normalize_labels(labels)
    # Assert
    assert out == ["spartan-cpu", "scitex-ci"]


def test_normalize_dedupes_and_strips_order_preserving():
    # Arrange
    labels = [" spartan-cpu ", "scitex-ci", "spartan-cpu", "", "gpu"]
    # Act
    out = normalize_labels(labels)
    # Assert
    assert out == ["spartan-cpu", "scitex-ci", "gpu"]


def test_normalize_keeps_required_present_only_once():
    # Arrange
    labels = ["scitex-ci", "spartan-cpu"]
    # Act
    out = normalize_labels(labels)
    # Assert
    assert out == ["scitex-ci", "spartan-cpu"]


def test_missing_required_flags_drifted_runner():
    # Arrange
    current = ["self-hosted", "Linux", "X64", "spartan-cpu"]
    # Act
    missing = missing_required_labels(current)
    # Assert
    assert missing == [REQUIRED_LABEL]


def test_missing_required_empty_for_correct_runner():
    # Arrange
    current = ["self-hosted", "Linux", "X64", "spartan-cpu", "scitex-ci"]
    # Act
    missing = missing_required_labels(current)
    # Assert
    assert missing == []


def test_build_command_bakes_scitex_ci_into_labels():
    # Arrange
    expected = "--labels spartan-cpu,scitex-ci"
    # Act
    cmd = build_register_command(url=URL, name="scitex-hpc")
    # Assert
    assert expected in cmd


def test_build_command_forces_label_even_if_caller_omits_it():
    # Arrange
    labels = ("spartan-cpu",)
    # Act
    cmd = build_register_command(url=URL, name="x", labels=labels)
    # Assert
    assert "--labels spartan-cpu,scitex-ci" in cmd


def test_build_command_starts_with_unattended_config():
    # Arrange
    prefix = "./config.sh --unattended"
    # Act
    cmd = build_register_command(url=URL, name="scitex-hpc", token="TT")
    # Assert
    assert cmd.startswith(prefix)


def test_build_command_includes_url():
    # Arrange
    expected = f"--url {URL}"
    # Act
    cmd = build_register_command(url=URL, name="scitex-hpc", token="TT")
    # Assert
    assert expected in cmd


def test_build_command_includes_token():
    # Arrange
    expected = "--token TT"
    # Act
    cmd = build_register_command(url=URL, name="scitex-hpc", token="TT")
    # Assert
    assert expected in cmd


def test_build_command_includes_name():
    # Arrange
    expected = "--name scitex-hpc"
    # Act
    cmd = build_register_command(url=URL, name="scitex-hpc", token="TT")
    # Assert
    assert expected in cmd


def test_build_command_ends_with_replace_by_default():
    # Arrange
    suffix = "--replace"
    # Act
    cmd = build_register_command(url=URL, name="scitex-hpc", token="TT")
    # Assert
    assert cmd.endswith(suffix)


def test_build_command_default_token_is_placeholder():
    # Arrange
    placeholder = "<TOKEN>"
    # Act
    cmd = build_register_command(url=URL, name="x")
    # Assert
    assert placeholder in cmd


def test_build_command_includes_work_dir_when_given():
    # Arrange
    work = "/tmp/w"
    # Act
    cmd = build_register_command(url=URL, name="x", work=work)
    # Assert
    assert "--work /tmp/w" in cmd


def test_build_command_includes_runner_group_when_given():
    # Arrange
    group = "scitex"
    # Act
    cmd = build_register_command(url=URL, name="x", runner_group=group)
    # Assert
    assert "--runnergroup scitex" in cmd


def test_build_command_no_replace_omits_flag():
    # Arrange
    replace = False
    # Act
    cmd = build_register_command(url=URL, name="x", replace=replace)
    # Assert
    assert "--replace" not in cmd
