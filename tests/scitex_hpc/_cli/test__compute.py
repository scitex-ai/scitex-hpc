import json

import pytest
from click.testing import CliRunner

from scitex_hpc._cli import cli


@pytest.fixture
def request_files(tmp_path):
    config, spec, handle = (
        tmp_path / name for name in ["config.yaml", "request.json", "handle.json"]
    )
    config.write_text(
        "profiles:\n  example:\n    host: example\n    scheduler: slurm\n"
    )
    spec.write_text(json.dumps({"argv": ["hostname"], "working_directory": "/work"}))
    handle.write_text(
        json.dumps({"host": "example", "scheduler": "slurm", "native_id": "123"})
    )
    return config, spec, handle


def test_compute_plan_emits_honest_json_without_ssh(request_files):
    # Arrange
    config, spec, _ = request_files
    args = [
        "compute",
        "plan",
        "--profile",
        "example",
        "--config",
        str(config),
        "--spec",
        str(spec),
    ]
    # Act
    result = CliRunner().invoke(cli, args)
    plan = json.loads(result.output)
    # Assert
    assert (result.exit_code, plan["scheduler"], plan["allocation_observed"]) == (
        0,
        "slurm",
        False,
    )


@pytest.mark.parametrize("operation", ["submit", "cancel"])
def test_cli_cannot_mutate_without_explicit_yes(request_files, operation):
    # Arrange
    config, spec, handle = request_files
    argument = (
        ["--spec", str(spec)]
        if operation == "submit"
        else ["--job-handle", str(handle)]
    )
    # Act
    result = CliRunner().invoke(
        cli,
        [
            "compute",
            operation,
            "--profile",
            "example",
            "--config",
            str(config),
            *argument,
        ],
    )
    # Assert
    assert (result.exit_code != 0, "--yes" in result.output) == (True, True)


@pytest.mark.parametrize("operation", ["plan", "submit", "status", "cancel"])
def test_cli_exposes_scheduler_neutral_operations(operation):
    # Arrange
    args = ["compute", operation, "--help"]
    # Act
    result = CliRunner().invoke(cli, args)
    # Assert
    assert result.exit_code == 0
