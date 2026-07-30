"""CLI tests for the ``ci-runners exec-supervisor`` command (dry-run path).

No SSH and no SLURM: discovery is replaced with a hand-rolled fake
``_discover`` (real module-attribute mutation in a context manager — no
``monkeypatch``, no mocks), and the dry-run path never reaches
``exec_remote``. Assertions pin the generated srun invocation + body so a
regression in the launch mechanics fails loudly.
"""

from __future__ import annotations

import contextlib

from scitex_hpc._cli import main
from scitex_hpc._cli._ci_runners import _group as cli_mod
from scitex_hpc.ci_runners import FleetSpec, RunnerSpec

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"


def _fleet(*names: str) -> FleetSpec:
    runners = [
        RunnerSpec(name=n, dir=f"{CI_BASE}/actions-runner-{n}") for n in names
    ]
    return FleetSpec(ci_base=CI_BASE, runners=runners)


@contextlib.contextmanager
def _fake_discover(fleet: FleetSpec):
    """Swap module-level ``_discover`` for one returning ``fleet`` (no SSH).

    Patches ``_ci_runners._group`` — where ``_discover`` is DEFINED — and the
    command modules call it as ``_group._discover(...)`` rather than binding it
    at import. Both halves are required: when this package was split out of a
    single module, a from-import in the command modules would have captured the
    real function and left this patch silently inert. The tests would still
    have PASSED, guarding nothing.
    """
    # Arrange — real attribute mutation, restored on exit.
    prior = cli_mod._discover
    cli_mod._discover = lambda host, ci_base, exclude: fleet
    try:
        yield
    finally:
        cli_mod._discover = prior


def test_dry_run_is_default_and_does_not_launch(capsys):
    # Arrange
    fleet = _fleet("scitex-hpc")
    # Act
    with _fake_discover(fleet):
        rc = main(["ci-runners", "exec-supervisor", "--overlap-jobid", "26437532"])
    # Assert
    out = capsys.readouterr().out
    assert rc == 0 and "DRY RUN" in out


def test_dry_run_prints_overlap_srun_command(capsys):
    # Arrange
    fleet = _fleet("scitex-hpc")
    # Act
    with _fake_discover(fleet):
        main(["ci-runners", "exec-supervisor", "--overlap-jobid", "26437532"])
    # Assert — the exact srun overlap invocation is shown for review
    out = capsys.readouterr().out
    assert "--jobid=26437532 --overlap" in out


def test_dry_run_prints_the_supervisor_body(capsys):
    # Arrange
    fleet = _fleet("a", "b")
    # Act
    with _fake_discover(fleet):
        main(["ci-runners", "exec-supervisor", "--overlap-jobid", "1"])
    # Assert — same keep-alive body book-supervisor would print
    out = capsys.readouterr().out
    assert out.count("./run.sh") == 2


def test_overlap_jobid_is_required(capsys):
    # Arrange
    argv = ["ci-runners", "exec-supervisor"]
    # Act
    rc = main(argv)
    # Assert — click exits non-zero when a required option is missing
    assert rc != 0


def test_backoff_knob_flows_into_the_body(capsys):
    # Arrange
    fleet = _fleet("a")
    # Act
    with _fake_discover(fleet):
        main(
            [
                "ci-runners",
                "exec-supervisor",
                "--overlap-jobid",
                "1",
                "--backoff",
                "99",
            ]
        )
    # Assert — the shared body generator honoured the override
    out = capsys.readouterr().out
    assert "sleep 99" in out


def test_no_runners_exits_2(capsys):
    # Arrange — a fleet whose only runner is excluded leaves nothing active
    fleet = _fleet("a")
    fleet.exclude = ("a",)
    # Act
    with _fake_discover(fleet):
        rc = main(["ci-runners", "exec-supervisor", "--overlap-jobid", "1"])
    # Assert
    err = capsys.readouterr().err
    assert rc == 2 and "no runners" in err
