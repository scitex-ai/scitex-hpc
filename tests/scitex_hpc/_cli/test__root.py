"""Smoke tests for the scitex-hpc CLI (click plumbing + JSON output).

Exercises the primary ``lease`` command group. The deprecated
``reservations`` alias is covered separately in ``TestDeprecatedAlias``
(it must resolve to the same command objects and emit a one-line stderr
notice).

Uses ``Reservation._override_defaults`` (real module-attribute mutation in
a context manager) to inject hand-rolled fake runners — no ``monkeypatch``
fixture, no mocks.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from scitex_hpc import Reservation
from scitex_hpc import _reservation as resmod
from scitex_hpc._cli import main

# ---------------------------------------------------------------------------
# Hand-rolled fakes
# ---------------------------------------------------------------------------


@dataclass
class _Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class _FakeRunner:
    """Records every (host, command) call and returns scripted results.

    ``dispatcher(command) -> _Result`` lets tests vary the answer based on
    the command body (e.g. ``sbatch`` vs ``squeue`` vs ``scancel``). When
    no dispatcher is given, every call returns ``default``.
    """

    def __init__(self, *, default: _Result | None = None, dispatcher=None):
        self.calls: list[tuple[str, str]] = []
        self._default = default if default is not None else _Result()
        self._dispatcher = dispatcher

    def __call__(self, host, command, *, check=False, timeout=None):
        self.calls.append((host, command))
        if self._dispatcher is not None:
            return self._dispatcher(command)
        return self._default

    @property
    def commands(self) -> list[str]:
        return [c for _, c in self.calls]


def _noop_sleep(_seconds):
    """Real no-op callable for the sleep seam — not a mock."""
    return None


# ---------------------------------------------------------------------------
# Fixtures (real env-var mutation, yield-based teardown — no monkeypatch)
# ---------------------------------------------------------------------------


@pytest.fixture
def lease_dir(tmp_path: Path):
    """Isolate ``SCITEX_HPC_LEASE_DIR`` per test via real env-var mutation."""
    # Arrange
    d = tmp_path / "leases"
    key = "SCITEX_HPC_LEASE_DIR"
    prior = os.environ.get(key)
    os.environ[key] = str(d)
    try:
        # Act / Assert — yielded to the test body.
        yield d
    finally:
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


# ---------------------------------------------------------------------------
# `reservations list`
# ---------------------------------------------------------------------------


class TestList:
    def test_list_emits_empty_marker_when_no_leases(self, lease_dir, capsys):
        # Arrange
        # (lease_dir is empty)
        # Act
        rc = main(["lease", "list"])
        # Assert
        assert rc == 0 and "(no reservations)" in capsys.readouterr().out

    def test_list_json_emits_saved_lease(self, lease_dir, capsys):
        # Arrange
        Reservation(
            id="spartan-foo",
            name="foo",
            host="spartan",
            job_id="42",
            node="spartan-bm022.hpc",
        ).save()
        # Act
        main(["lease", "list", "--json"])
        # Assert
        out = json.loads(capsys.readouterr().out)
        assert out[0]["id"] == "spartan-foo" and out[0]["job_id"] == "42"

    def test_list_table_shows_persistent_column(self, lease_dir, capsys):
        # Arrange
        Reservation(
            id="spartan-foo",
            name="foo",
            host="spartan",
            job_id="42",
            node="n1",
            persistent=True,
        ).save()
        # Act
        main(["lease", "list"])
        # Assert
        out = capsys.readouterr().out
        assert "spartan-foo" in out and "yes" in out


# ---------------------------------------------------------------------------
# `reservations get`
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_returns_2_when_lease_is_missing(self, lease_dir):
        # Arrange
        # (lease_dir is empty)
        # Act
        rc = main(["lease", "get", "nope"])
        # Assert
        assert rc == 2

    def test_get_emits_json_for_saved_lease(self, lease_dir, capsys):
        # Arrange
        Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
        # Act
        rc = main(["lease", "get", "spartan-foo"])
        # Assert
        assert rc == 0 and json.loads(capsys.readouterr().out)["job_id"] == "42"


# ---------------------------------------------------------------------------
# `reservations exec`
# ---------------------------------------------------------------------------


class TestExec:
    def test_exec_propagates_remote_returncode(self, lease_dir, capsys):
        # Arrange
        Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
        runner = _FakeRunner(
            default=_Result(returncode=7, stdout="hi\n", stderr="err\n")
        )
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(["lease", "exec", "spartan-foo", "echo hi"])
        # Assert
        captured = capsys.readouterr()
        assert rc == 7 and "hi" in captured.out and "err" in captured.err


# ---------------------------------------------------------------------------
# `reservations release / cancel`
# ---------------------------------------------------------------------------


class TestRelease:
    def test_release_missing_lease_is_idempotent(self, lease_dir):
        # Arrange
        # (lease_dir is empty)
        # Act
        rc = main(["lease", "release", "nope"])
        # Assert
        assert rc == 0

    def test_release_invokes_scancel_with_job_id(self, lease_dir):
        # Arrange
        Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
        runner = _FakeRunner(default=_Result(returncode=0))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(["lease", "release", "spartan-foo"])
        # Assert
        assert rc == 0 and any("scancel 42" in c for c in runner.commands)


# ---------------------------------------------------------------------------
# `reservations book` smoke
# ---------------------------------------------------------------------------


class TestBookSmoke:
    def test_book_subcommand_returns_job_id_and_node(self, lease_dir, capsys):
        # Arrange
        def dispatch(command: str) -> _Result:
            if "sbatch" in command:
                return _Result(stdout="Submitted batch job 99\n")
            return _Result(stdout="RUNNING n1\n")

        runner = _FakeRunner(dispatcher=dispatch)
        # Act
        with resmod._override_defaults(
            runner=runner, sleep=_noop_sleep, monotonic=lambda: 0.0
        ):
            rc = main(
                [
                    "lease",
                    "book",
                    "dev-pool",
                    "--host",
                    "spartan",
                    "--cpus",
                    "4",
                    "--time",
                    "1-0",
                    "--mem",
                    "8G",
                    "--json",
                ]
            )
        # Assert
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["job_id"] == "99" and out["node"] == "n1"


# ---------------------------------------------------------------------------
# `reservations book --tmux-server`
# ---------------------------------------------------------------------------


class TestBookTmuxServer:
    """`--tmux-server` flag wires through to ``Reservation.book``."""

    def test_book_tmux_server_flag_appears_in_sbatch_script(self, lease_dir, capsys):
        # Arrange
        captured_commands: list[str] = []

        def dispatch(command: str) -> _Result:
            captured_commands.append(command)
            if "sbatch" in command:
                return _Result(stdout="Submitted batch job 42\n")
            return _Result(stdout="RUNNING n1\n")

        runner = _FakeRunner(dispatcher=dispatch)
        # Act
        with resmod._override_defaults(
            runner=runner, sleep=_noop_sleep, monotonic=lambda: 0.0
        ):
            rc = main(
                [
                    "lease",
                    "book",
                    "test",
                    "--host",
                    "spartan",
                    "--tmux-server",
                    "sac",
                ]
            )
        # Assert
        sbatch_calls = [c for c in captured_commands if "sbatch" in c]
        assert rc == 0 and any("tmux -L sac" in c for c in sbatch_calls)

    def test_book_without_tmux_server_omits_tmux_bootstrap(self, lease_dir, capsys):
        # Arrange
        captured_commands: list[str] = []

        def dispatch(command: str) -> _Result:
            captured_commands.append(command)
            if "sbatch" in command:
                return _Result(stdout="Submitted batch job 42\n")
            return _Result(stdout="RUNNING n1\n")

        runner = _FakeRunner(dispatcher=dispatch)
        # Act
        with resmod._override_defaults(
            runner=runner, sleep=_noop_sleep, monotonic=lambda: 0.0
        ):
            main(["lease", "book", "test", "--host", "spartan"])
        # Assert
        sbatch_calls = [c for c in captured_commands if "sbatch" in c]
        assert all("tmux -L" not in c for c in sbatch_calls)


# ---------------------------------------------------------------------------
# `reservations refresh`
# ---------------------------------------------------------------------------


class TestRefresh:
    """`reservations refresh` re-discovers job_id by friendly name."""

    def test_refresh_picks_up_new_jobid_via_squeue(self, lease_dir, capsys):
        # Arrange
        Reservation(
            id="spartan-foo",
            name="foo",
            host="spartan",
            job_id="100",
            node="bm022",
        ).save()
        runner = _FakeRunner(default=_Result(stdout="200 RUNNING bm175\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(["lease", "refresh", "spartan-foo", "--json"])
        # Assert
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["job_id"] == "200" and out["node"] == "bm175"

    def test_refresh_returns_2_when_no_live_job_in_queue(self, lease_dir, capsys):
        # Arrange
        Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
        runner = _FakeRunner(default=_Result(stdout=""))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(["lease", "refresh", "spartan-foo"])
        # Assert
        captured = capsys.readouterr()
        assert rc == 2 and "no live job found" in captured.err

    def test_refresh_raises_keyerror_when_lease_missing(self, lease_dir):
        # Arrange
        # (lease_dir is empty)
        # Act
        action = lambda: main(["lease", "refresh", "nonexistent"])
        # Assert
        with pytest.raises(KeyError, match="no reservation"):
            action()


# ---------------------------------------------------------------------------
# `lease adopt` — register an EXISTING running job (no sbatch)
# ---------------------------------------------------------------------------


class TestAdopt:
    """`lease adopt` registers an already-running SLURM job as a lease.

    The whole point is honoring "never request a new node": adopt writes
    the SAME lease state `book` writes but submits NO sbatch. After adopt,
    `get` and `refresh` resolve the lease, and `refresh` re-discovers the
    job_id by NAME via squeue (surviving a future re-key).
    """

    def test_adopt_writes_lease_state_to_disk(self, lease_dir, capsys):
        # Arrange
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                ]
            )
        # Assert
        assert rc == 0 and (lease_dir / "spartan-ci-perm.json").is_file()

    def test_adopt_submits_no_sbatch(self, lease_dir):
        # Arrange
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                ]
            )
        # Assert — the whole point: NO node requested.
        assert not any("sbatch" in c for c in runner.commands)

    def test_adopt_records_supplied_job_id(self, lease_dir, capsys):
        # Arrange
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                    "--json",
                ]
            )
        # Assert
        assert json.loads(capsys.readouterr().out)["job_id"] == "26332626"

    def test_adopt_populates_node_via_squeue_probe(self, lease_dir, capsys):
        # Arrange — from_jobid's refresh_node probe parses `%T %N`.
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                    "--json",
                ]
            )
        # Assert
        assert json.loads(capsys.readouterr().out)["node"] == "spartan-bm207"

    def test_adopt_marks_persistent_when_flag_set(self, lease_dir, capsys):
        # Arrange
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                    "--persistent",
                    "--json",
                ]
            )
        # Assert
        assert json.loads(capsys.readouterr().out)["persistent"] is True

    def test_get_resolves_lease_after_adopt(self, lease_dir, capsys):
        # Arrange
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                ]
            )
        capsys.readouterr()  # drain the adopt line
        # Act
        rc = main(["lease", "get", "spartan-ci-perm"])
        # Assert
        assert rc == 0 and json.loads(capsys.readouterr().out)["job_id"] == "26332626"

    def test_refresh_rediscovers_job_id_after_adopt(self, lease_dir, capsys):
        # Arrange — adopt (probe: `%T %N`), then refresh (query: `%i %T %N`).
        def dispatch(command: str) -> _Result:
            if "--name=" in command:  # refresh query
                return _Result(stdout="26332626 RUNNING spartan-bm207\n")
            return _Result(stdout="RUNNING spartan-bm207\n")  # adopt probe

        runner = _FakeRunner(dispatcher=dispatch)
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                ]
            )
            capsys.readouterr()  # drain
            # Act
            rc = main(["lease", "refresh", "spartan-ci-perm", "--json"])
        # Assert
        out = json.loads(capsys.readouterr().out)
        assert (
            rc == 0 and out["job_id"] == "26332626" and out["node"] == "spartan-bm207"
        )

    def test_adopt_refuses_to_overwrite_existing_lease(self, lease_dir, capsys):
        # Arrange
        Reservation(
            id="spartan-ci-perm", name="ci-perm", host="spartan", job_id="1"
        ).save()
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(
                [
                    "lease",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                ]
            )
        # Assert
        assert rc == 1 and "already exists" in capsys.readouterr().err

    def test_adopt_requires_job_id(self, lease_dir):
        # Arrange
        argv = ["lease", "adopt", "ci-perm", "--host", "spartan"]
        # Act — click rejects the missing required option.
        rc = main(argv)
        # Assert
        assert rc != 0

    def test_alias_adopt_routes_through_to_real_adopt(self, lease_dir, capsys):
        # Arrange — the deprecated `reservations` alias must expose `adopt` too.
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            rc = main(
                [
                    "reservations",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                    "--json",
                ]
            )
        out = json.loads(capsys.readouterr().out)
        # Assert — routed through to the real adopt (job_id parsed).
        assert rc == 0 and out["job_id"] == "26332626"

    def test_alias_adopt_submits_no_sbatch(self, lease_dir, capsys):
        # Arrange — adopting via the alias must also never request a node.
        runner = _FakeRunner(default=_Result(stdout="RUNNING spartan-bm207\n"))
        # Act
        with resmod._override_defaults(runner=runner, sleep=_noop_sleep):
            main(
                [
                    "reservations",
                    "adopt",
                    "ci-perm",
                    "--job-id",
                    "26332626",
                    "--host",
                    "spartan",
                ]
            )
        # Assert
        assert not any("sbatch" in c for c in runner.commands)


# ---------------------------------------------------------------------------
# Deprecated `reservations` alias → `lease`
# ---------------------------------------------------------------------------


class TestDeprecatedAlias:
    """`reservations` is a deprecated alias that forwards to `lease`.

    It must (a) expose the *same command objects* (DRY — no duplicated
    bodies), (b) keep behaving/exiting identically to `lease`, and
    (c) emit a one-line deprecation notice to stderr. One assertion per
    test so a single failing line names the broken behaviour.
    """

    def test_alias_exposes_the_same_subcommand_names_as_lease(self):
        # Arrange
        import click

        from scitex_hpc._cli._reservations import lease, reservations

        ctx = click.Context(lease)
        # Act
        names = (
            sorted(reservations.list_commands(ctx)),
            sorted(lease.list_commands(ctx)),
        )
        # Assert
        assert names[0] == names[1]

    def test_alias_reuses_the_same_command_objects_as_lease(self):
        # Arrange
        import click

        from scitex_hpc._cli._reservations import lease, reservations

        ctx = click.Context(lease)
        # Act
        same_objects = all(
            reservations.get_command(ctx, n) is lease.get_command(ctx, n)
            for n in lease.list_commands(ctx)
        )
        # Assert
        assert same_objects is True

    def test_alias_help_emits_deprecation_notice_on_stderr(self, capsys):
        # Arrange
        argv = ["reservations", "--help"]
        # Act
        rc = main(argv)
        err = capsys.readouterr().err
        # Assert
        assert rc == 0 and "deprecated" in err and "lease" in err

    def test_alias_help_still_lists_subcommands_on_stdout(self, capsys):
        # Arrange
        argv = ["reservations", "--help"]
        # Act
        main(argv)
        out = capsys.readouterr().out
        # Assert
        assert "book" in out and "cancel" in out

    def test_alias_list_yields_identical_stdout_to_lease(self, lease_dir, capsys):
        # Arrange
        Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
        # Act
        main(["lease", "list", "--json"])
        lease_out = capsys.readouterr().out
        main(["reservations", "list", "--json"])
        alias_out = capsys.readouterr().out
        # Assert
        assert json.loads(alias_out) == json.loads(lease_out)

    def test_alias_list_warns_on_stderr(self, lease_dir, capsys):
        # Arrange
        Reservation(id="spartan-foo", name="foo", host="spartan", job_id="42").save()
        # Act
        rc = main(["reservations", "list", "--json"])
        err = capsys.readouterr().err
        # Assert
        assert rc == 0 and "deprecated" in err

    def test_alias_book_routes_through_to_the_real_book_command(
        self, lease_dir, capsys
    ):
        # Arrange
        def dispatch(command: str) -> _Result:
            if "sbatch" in command:
                return _Result(stdout="Submitted batch job 99\n")
            return _Result(stdout="RUNNING n1\n")

        runner = _FakeRunner(dispatcher=dispatch)
        # Act
        with resmod._override_defaults(
            runner=runner, sleep=_noop_sleep, monotonic=lambda: 0.0
        ):
            rc = main(
                [
                    "reservations",
                    "book",
                    "dev-pool",
                    "--host",
                    "spartan",
                    "--cpus",
                    "4",
                    "--time",
                    "1-0",
                    "--mem",
                    "8G",
                    "--json",
                ]
            )
        out = json.loads(capsys.readouterr().out)
        # Assert
        assert rc == 0 and out["job_id"] == "99" and out["node"] == "n1"
