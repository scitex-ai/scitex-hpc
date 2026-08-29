"""CLI tests for the ``ci-runners exec-supervisor`` command (dry-run path).

No SSH and no SLURM: discovery is replaced with a hand-rolled fake
``discover_fleet`` (real module-attribute mutation in a context manager — no
``monkeypatch``, no mocks), and the dry-run path never reaches
``exec_remote``. Assertions pin the generated srun invocation + body so a
regression in the launch mechanics fails loudly.

The swap targets :mod:`scitex_hpc._cli._ci_runners_common` — the ONE module
that reads the cluster. Every ``ci-runners`` command calls it as
``_common.discover_fleet(...)``, so this single seam covers commands in both
``_ci_runners`` and ``_ci_runners_supervisor``.
"""

from __future__ import annotations

import contextlib

from scitex_hpc._cli import _ci_runners_common as cli_mod
from scitex_hpc._cli import main
from scitex_hpc.ci_runners import FleetSpec, RunnerSpec

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"


def _fleet(*names: str) -> FleetSpec:
    runners = [
        RunnerSpec(name=n, dir=f"{CI_BASE}/actions-runner-{n}") for n in names
    ]
    return FleetSpec(ci_base=CI_BASE, runners=runners)


@contextlib.contextmanager
def _fake_discover(fleet: FleetSpec):
    """Swap ``discover_fleet`` for one returning ``fleet`` (no SSH)."""
    # Arrange — real attribute mutation, restored on exit.
    prior = cli_mod.discover_fleet
    cli_mod.discover_fleet = lambda host, ci_base, exclude: fleet
    try:
        yield
    finally:
        cli_mod.discover_fleet = prior


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


def test_book_supervisor_no_runners_exits_2_naming_ci_base(capsys):
    # Arrange — an empty FleetSpec (e.g. ci_base resolved to the wrong dir,
    # or the fleet's naming convention isn't one parse_runner_dirs knows).
    fleet = FleetSpec(ci_base=CI_BASE, runners=[])
    # Act
    with _fake_discover(fleet):
        rc = main(["ci-runners", "book-supervisor"])
    # Assert — fails loudly and names the base it searched, rather than
    # reporting a dry-run "plan" for zero runners.
    err = capsys.readouterr().err
    assert rc == 2 and "no runners" in err and CI_BASE in err


def test_show_monitor_no_runners_exits_2_naming_ci_base(capsys):
    # Arrange — an EMPTY FleetSpec. Before this fix, show-monitor happily
    # emitted a monitor script watching zero runners (always reports "OK").
    fleet = FleetSpec(ci_base=CI_BASE, runners=[])
    # Act
    with _fake_discover(fleet):
        rc = main(["ci-runners", "show-monitor"])
    # Assert
    err = capsys.readouterr().err
    assert rc == 2 and "no runners" in err and CI_BASE in err


def test_watch_no_runners_exits_2_naming_ci_base(capsys):
    # Arrange — an EMPTY FleetSpec on the actual cron watchdog entrypoint.
    # Before this fix, `watch` ran a generated monitor script with zero
    # runners to check, no matter why the fleet was empty. On a real host
    # with reachable SSH it reports "OK runners=0" and exits 0 — a green
    # that cannot go red, having supervised nothing. Here (no real SSH)
    # the downstream script instead fails for an UNRELATED reason (holder
    # jobid resolution) with an unrelated exit code — which makes the same
    # point from the other side: without an explicit empty-fleet check,
    # what "watch" reports depends on incidental downstream conditions
    # rather than deterministically naming the actual problem.
    fleet = FleetSpec(ci_base=CI_BASE, runners=[])
    # Act
    with _fake_discover(fleet):
        rc = main(["ci-runners", "watch"])
    # Assert — fails BEFORE the monitor script is even generated/run
    err = capsys.readouterr().err
    assert rc == 2 and "no runners" in err and CI_BASE in err


def test_show_register_bakes_scitex_ci_label(capsys):
    # Arrange
    argv = [
        "ci-runners",
        "show-register",
        "--url",
        "https://github.com/ywatanabe1989/scitex-hpc",
        "--name",
        "scitex-hpc",
    ]
    # Act
    rc = main(argv)
    # Assert — the label the ci-template selects on is always emitted
    out = capsys.readouterr().out
    assert rc == 0 and "--labels spartan-cpu,scitex-ci" in out


def test_show_register_requires_url(capsys):
    # Arrange — --url is a required option
    argv = ["ci-runners", "show-register", "--name", "scitex-hpc"]
    # Act
    rc = main(argv)
    # Assert
    assert rc != 0


def test_show_register_json_emits_command_key(capsys):
    # Arrange
    argv = [
        "ci-runners",
        "show-register",
        "--url",
        "https://github.com/ywatanabe1989/scitex-hpc",
        "--name",
        "x",
        "--json",
    ]
    # Act
    main(argv)
    # Assert
    out = capsys.readouterr().out
    assert '"command"' in out
