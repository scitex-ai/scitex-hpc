"""Execute generated shell boundaries locally against inert scheduler executables."""

import json
import os
import shlex
import subprocess
import sys

import pytest

from scitex_hpc.scheduler import (
    BatchRequest,
    ComputeClient,
    HostProfile,
    JobHandle,
    ResourceBundle,
)


def no_transport(*_):
    raise RuntimeError("Planning must not contact a transport")


@pytest.fixture(params=["slurm", "grid-engine"])
def submission_case(request, tmp_path):
    scheduler = request.param
    work = tmp_path / "work ' ; touch NOT_ALLOWED"
    work.mkdir()
    scripts = tmp_path / "bin"
    scripts.mkdir()
    capture = tmp_path / "scheduler.json"
    executable = scripts / ("sbatch" if scheduler == "slurm" else "qsub")
    executable.write_text(
        "#!"
        + sys.executable
        + "\nimport os,sys,json\nfrom pathlib import Path\nPath(os.environ['CAPTURE']).write_text(json.dumps({'args':sys.argv[1:],'script':sys.stdin.read(),'inherited_gres':os.environ.get('SBATCH_GRES')}))\nsys.stdout.write('12345\\n')\n"
    )
    executable.chmod(0o700)
    hostile = "$(touch ESCAPED)\n#$ -t 1-99\n#SBATCH --gpus=99\n' ; touch ESCAPED ; '"
    result_file = work / "arguments.json"
    spec = BatchRequest(
        (
            sys.executable,
            "-c",
            "import sys,json;from pathlib import Path;Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))",
            str(result_file),
            hostile,
        ),
        str(work),
    )
    bundle = ResourceBundle("test_cpu", 4, 8192) if scheduler == "grid-engine" else None
    client = ComputeClient(
        HostProfile(
            "example",
            scheduler,
            account="test",
            bundle=bundle,
            dialect="tsubame" if scheduler == "grid-engine" else None,
        )
    )
    plan = client.plan(spec, name="safe123")
    body = shlex.split(plan.command)
    # Execute the exact command body without login startup, with owned HOME/PATH.
    env = {
        **os.environ,
        "PATH": str(scripts) + os.pathsep + os.environ["PATH"],
        "CAPTURE": str(capture),
        "HOME": str(tmp_path),
        "SBATCH_GRES": "gpu:999",
    }
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", body[2]],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    captured = json.loads(capture.read_text())
    script = work / "received.sh"
    script.write_text(captured["script"])
    subprocess.run(
        ["bash", "--noprofile", "--norc", str(script)],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    return {
        "scheduler": scheduler,
        "wrapper": body[:2],
        "plan": plan,
        "captured": captured,
        "received_argv": json.loads(result_file.read_text()),
        "hostile": hostile,
        "unexpected_files": [
            str(p) for p in [work / "ESCAPED", tmp_path / "NOT_ALLOWED"] if p.exists()
        ],
    }


def test_generated_submission_uses_login_shell_boundary(submission_case):
    # Arrange
    case = submission_case
    # Act
    wrapper = case["wrapper"]
    # Assert
    assert wrapper == ["bash", "-lc"]


def test_generated_workload_preserves_hostile_argument_literally(submission_case):
    # Arrange
    case = submission_case
    # Act
    actual = case["received_argv"]
    # Assert
    assert actual == [case["hostile"]]


def test_quoted_metadata_does_not_execute_shell_substitutions(submission_case):
    # Arrange
    case = submission_case
    # Act
    unexpected = case["unexpected_files"]
    # Assert
    assert unexpected == []


def test_plans_never_claim_actual_allocation_observation(submission_case):
    # Arrange
    plan = submission_case["plan"]
    # Act
    observed = plan.allocation_observed
    # Assert
    assert observed is False


def test_native_defaults_cannot_inject_unplanned_slurm_gpus(submission_case):
    # Arrange
    case = submission_case
    expected = None if case["scheduler"] == "slurm" else "gpu:999"
    # Act
    actual = case["captured"]["inherited_gres"]
    # Assert
    assert actual == expected


def test_grid_engine_disables_embedded_directives_and_request_defaults(submission_case):
    # Arrange
    case = submission_case
    args = case["captured"]["args"]
    # Act
    actual = (
        (args[0], args[args.index("-C") + 1])
        if case["scheduler"] == "grid-engine"
        else (args[0], args[1])
    )
    expected = (
        ("-clear", "")
        if case["scheduler"] == "grid-engine"
        else ("--parsable", "--nodes=1")
    )
    # Assert
    assert actual == expected


def test_batch_module_initialization_runs_before_workload_without_login_startup(
    tmp_path,
):
    # Arrange
    init, receipt = tmp_path / "module-init.sh", tmp_path / "module-receipt.txt"
    init.write_text("module() { export SCI_TEST_MODULE=loaded; }\n")
    spec = BatchRequest(
        (
            sys.executable,
            "-c",
            "import os,sys;from pathlib import Path;Path(sys.argv[1]).write_text(os.environ['SCI_TEST_MODULE'])",
            str(receipt),
        ),
        str(tmp_path),
    )
    client = ComputeClient(
        HostProfile("example", "slurm", module_init=str(init), modules=("Test/1.0",))
    )
    # Act
    words = shlex.split(shlex.split(client.plan(spec).command)[2])
    script = words[words.index("printf") + 2]
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", script],
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    # Assert
    assert receipt.read_text() == "loaded"


@pytest.mark.parametrize(
    "native_id", ["--user=someone", "123; touch escaped", "1_2", "123\n456", "0"]
)
def test_malicious_or_unsupported_job_identity_is_rejected(native_id):
    # Arrange
    host, scheduler = "example", "slurm"
    # Act
    construct = JobHandle
    # Assert
    with pytest.raises(ValueError, match="batch job ID"):
        construct(host, scheduler, native_id)


@pytest.mark.parametrize(
    "path", ["relative/project", "/work/../secret", "~/../secret", "/work\n#$ -q wrong"]
)
def test_unsafe_working_directory_is_rejected(path):
    # Arrange
    argv = ("hostname",)
    # Act
    construct = BatchRequest
    # Assert
    with pytest.raises(ValueError):
        construct(argv, path)


@pytest.mark.parametrize("path", ["/work/$JOB_ID", "/work/%j"])
def test_log_placeholder_paths_refused_before_submission(path):
    # Arrange
    client = ComputeClient(HostProfile("example", "slurm"), runner=no_transport)
    # Act
    spec = BatchRequest(("hostname",), path)
    # Assert
    with pytest.raises(ValueError, match="Scheduler log paths"):
        client.plan(spec)


@pytest.mark.parametrize("resource", [{"cpus": 8}, {"walltime_seconds": 61}])
def test_bundle_capacity_and_walltime_limit_refuse_without_transport(resource):
    # Arrange
    p = HostProfile(
        "example",
        "grid-engine",
        account="test",
        dialect="tsubame",
        bundle=ResourceBundle("test", 4, 8192),
        max_walltime_seconds=60,
    )
    c = ComputeClient(p, runner=no_transport)
    # Act
    spec = BatchRequest(("hostname",), "/work", **resource)
    # Assert
    with pytest.raises(ValueError):
        c.plan(spec)


def test_excess_bundle_capacity_is_visible_before_submission():
    # Arrange
    p = HostProfile(
        "example",
        "grid-engine",
        account="test",
        dialect="tsubame",
        bundle=ResourceBundle("test", 4, 8192),
    )
    # Act
    plan = ComputeClient(p).plan(BatchRequest(("hostname",), "/work"))
    # Assert
    assert (plan.planned, bool(plan.warnings), plan.allocation_observed) == (
        {"cpus": 4, "memory_mib": 8192, "gpus": 0},
        True,
        False,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scheduler": "pbs"},
        {"scheduler": "grid-engine"},
        {"scheduler": "slurm", "account": "x\n--gpus=99"},
    ],
)
def test_profiles_cannot_infer_backend_or_accept_scheduler_option_injection(kwargs):
    # Arrange
    host = "example"
    # Act
    construct = HostProfile
    # Assert
    with pytest.raises(ValueError):
        construct(host, **kwargs)


@pytest.mark.parametrize("path", ["/work/a,b", "/work/a:b"])
def test_grid_engine_native_log_path_separators_refused_before_transport(path):
    # Arrange
    profile = HostProfile(
        "example",
        "grid-engine",
        account="test",
        dialect="tsubame",
        bundle=ResourceBundle("test", 4, 8192),
    )
    client = ComputeClient(profile, runner=no_transport)
    # Act
    spec = BatchRequest(("hostname",), path)
    # Assert
    with pytest.raises(ValueError, match="Grid Engine log paths"):
        client.plan(spec)


@pytest.mark.parametrize("dialect", [None, "generic", "other-site"])
def test_grid_engine_requires_explicit_supported_site_dialect(dialect):
    # Arrange
    bundle = ResourceBundle("test", 4, 8192)
    # Act
    construct = HostProfile
    # Assert
    with pytest.raises(ValueError, match="dialect"):
        construct(
            "example", "grid-engine", account="test", bundle=bundle, dialect=dialect
        )


def test_grid_engine_plan_exposes_supported_dialect():
    # Arrange
    profile = HostProfile(
        "example",
        "grid-engine",
        account="test",
        dialect="tsubame",
        bundle=ResourceBundle("test", 4, 8192),
    )
    # Act
    plan = ComputeClient(profile).plan(BatchRequest(("hostname",), "/work"))
    # Assert
    assert plan.dialect == "tsubame"


def test_slurm_does_not_apply_grid_engine_log_path_restrictions():
    # Arrange
    client = ComputeClient(HostProfile("example", "slurm"), runner=no_transport)
    # Act
    plan = client.plan(BatchRequest(("hostname",), "/work/a,b:c"))
    # Assert
    assert plan.stdout_path.startswith("/work/a,b:c/")
