"""Offline lifecycle regressions; no SSH connections or scheduler resources."""

import os
import shlex
import subprocess
from dataclasses import dataclass

import pytest

from scitex_hpc.scheduler import (
    BatchRequest,
    ComputeClient,
    HostProfile,
    JobHandle,
    ResourceBundle,
    SubmissionError,
)


@dataclass
class Result:
    stdout: str = ""
    returncode: int = 0


class Runner:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, host, command):
        if not self.results:
            pytest.fail(
                "Unexpected transport call: no retry or extra query was expected"
            )
        self.calls.append((host, command))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def profile(scheduler):
    if scheduler == "slurm":
        return HostProfile("cluster", scheduler)
    return HostProfile(
        "cluster",
        scheduler,
        account="example",
        dialect="tsubame",
        bundle=ResourceBundle("cpu_test", 4, 8192),
    )


def no_transport(*_):
    raise RuntimeError("This validation case must not contact a transport")


@pytest.mark.parametrize("scheduler", ["slurm", "grid-engine"])
def test_batch_submission_returns_host_scoped_identity(scheduler):
    # Arrange
    runner = Runner(Result("login message\n12345\n"))
    client = ComputeClient(profile(scheduler), runner=runner)
    # Act
    handle = client.submit(
        BatchRequest(("python", "analysis.py"), "~/project"), name="correlation123"
    )
    # Assert
    assert handle == JobHandle("cluster", scheduler, "12345")


@pytest.mark.parametrize(
    "result,outcome",
    [
        (Result("", 255), "unknown"),
        (Result("", -15), "unknown"),
        (Result("", -9), "unknown"),
        (Result("", 137), "unknown"),
        (Result("", 143), "unknown"),
        (Result("", 1), "rejected"),
        (Result("ambiguous success", 0), "unknown"),
        (Result("12345.1-10:1", 0), "unknown"),
        (TimeoutError("SSH deadline"), "unknown"),
    ],
)
def test_uncertain_submission_never_retries_and_retains_correlation(result, outcome):
    # Arrange
    runner = Runner(result)
    client = ComputeClient(profile("grid-engine"), runner=runner)
    spec = BatchRequest(("hostname",), "/work")
    # Act
    submit = client.submit
    # Assert
    with pytest.raises(
        SubmissionError, match=f"outcome={outcome}, job_name=known-correlation"
    ):
        submit(spec, name="known-correlation")


@pytest.mark.parametrize("scheduler", ["slurm", "grid-engine"])
@pytest.mark.parametrize("result", [Result("", 1), TimeoutError("offline")])
def test_failed_queue_query_is_unknown_not_dead_or_completed(scheduler, result):
    # Arrange
    runner = Runner(result)
    client = ComputeClient(profile(scheduler), runner=runner)
    # Act
    status = client.status(JobHandle("cluster", scheduler, "123"))
    # Assert
    assert (status.state, status.exit_code) == ("unknown", None)


@pytest.mark.parametrize(
    "scheduler,queue,accounting",
    [
        ("slurm", "", "123|COMPLETED|0:0\n123.batch|COMPLETED|0:0"),
        (
            "grid-engine",
            "<job_info/>",
            "jobnumber 123\nfailed 0\nexit_status 0\ntaskid undefined",
        ),
    ],
)
def test_completion_requires_matching_accounting_and_exit_evidence(
    scheduler, queue, accounting
):
    # Arrange
    runner = Runner(Result(queue), Result(accounting))
    client = ComputeClient(profile(scheduler), runner=runner)
    # Act
    status = client.status(JobHandle("cluster", scheduler, "123"))
    # Assert
    assert (status.state, status.exit_code) == ("succeeded", 0)


@pytest.mark.parametrize(
    "scheduler,queue", [("slurm", ""), ("grid-engine", "<job_info/>")]
)
def test_accounting_delay_does_not_imply_success(scheduler, queue):
    # Arrange
    client = ComputeClient(
        profile(scheduler), runner=Runner(Result(queue), Result("", 1))
    )
    # Act
    status = client.status(JobHandle("cluster", scheduler, "123"))
    # Assert
    assert status.state == "unknown"


@pytest.mark.parametrize("operation", ["status", "cancel"])
def test_wrong_host_handle_refused_before_any_transport(operation):
    # Arrange
    client = ComputeClient(
        profile("slurm"),
        runner=no_transport,
    )
    foreign = JobHandle("another-cluster", "slurm", "123")
    # Act
    call = getattr(client, operation)
    # Assert
    with pytest.raises(ValueError, match="another host"):
        call(foreign)


@pytest.mark.parametrize(
    "scheduler,native_command", [("slurm", "scancel"), ("grid-engine", "qdel")]
)
def test_cancel_acknowledgment_only_targets_the_identified_job(
    scheduler, native_command
):
    # Arrange
    runner = Runner(Result())
    client = ComputeClient(profile(scheduler), runner=runner)
    # Act
    client.cancel(JobHandle("cluster", scheduler, "123"))
    # Assert
    assert runner.calls == [("cluster", f"bash -lc '{native_command} 123'")]


def test_slurm_parsable_cluster_suffix_is_preserved_in_job_identity():
    # Arrange
    client = ComputeClient(profile("slurm"), runner=Runner(Result("12345;compute-a\n")))
    # Act
    handle = client.submit(BatchRequest(("hostname",), "/work"))
    # Assert
    assert handle == JobHandle("cluster", "slurm", "12345", cluster="compute-a")


@pytest.mark.parametrize("operation", ["status", "cancel"])
def test_slurm_cluster_identity_scopes_queries_and_cancel(operation):
    # Arrange
    runner = Runner(Result("12345|RUNNING|node1\n"))
    client = ComputeClient(profile("slurm"), runner=runner)
    job = JobHandle("cluster", "slurm", "12345", cluster="compute-a")
    # Act
    getattr(client, operation)(job)
    # Assert
    assert "--clusters=compute-a" in runner.calls[0][1]


def test_signal_after_simulated_acceptance_preserves_unknown_outcome(tmp_path):
    # Arrange
    work = tmp_path / "work"
    work.mkdir()
    scripts = tmp_path / "bin"
    scripts.mkdir()
    accepted = tmp_path / "accepted"
    qsub = scripts / "qsub"
    qsub.write_text(
        "#!/bin/sh\nprintf accepted > "
        + shlex.quote(str(accepted))
        + "\nkill -TERM $$\n"
    )
    qsub.chmod(0o700)
    calls = []
    codes = []

    def run_owned_command(host, command):
        calls.append(host)
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", shlex.split(command)[2]],
            env={
                **os.environ,
                "PATH": str(scripts) + os.pathsep + os.environ["PATH"],
                "HOME": str(tmp_path),
            },
            capture_output=True,
            text=True,
            timeout=15,
        )
        codes.append(result.returncode)
        return result

    client = ComputeClient(profile("grid-engine"), runner=run_owned_command)
    # Act
    try:
        client.submit(BatchRequest(("hostname",), str(work)), name="signal-check")
        observed = ("success", accepted.exists(), len(calls), codes)
    except SubmissionError as exc:
        observed = (exc.outcome, accepted.exists(), len(calls), codes)
    # Assert
    assert observed == ("unknown", True, 1, [143])
