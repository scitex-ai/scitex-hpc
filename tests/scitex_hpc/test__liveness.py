"""Tests for the SLURM job-liveness instrument.

Hand-rolled fakes injected through the ``runner=`` DI seam — no mocking
library anywhere, matching the convention in ``test__reservation.py``.

The UNKNOWN paths are the point of this suite. A false DEAD would let
``sac db reconcile-remote`` tombstone a LIVE agent's row, so every failure
mode is registered in :data:`UNKNOWN_CASES` and swept by
``test_no_failure_path_ever_yields_dead``.
"""

from __future__ import annotations

import json

import pytest

from scitex_hpc._liveness import (
    ACTIVE_STATES,
    ALIVE,
    DEAD,
    TERMINAL_STATES,
    UNKNOWN,
    job_liveness,
)

HOST = "spartan"
NAME = "spartan-cpu-agent"
JOB = "24386489"

# A chatty HPC login shell prefixes real output with banner lines; every
# parser here must scan past them rather than assuming line 1 is data.
BANNER = "XAUTHORITY: /home/u/.Xauthority\nDISPLAY: 1.2.3.4:0\n"


# ---------------------------------------------------------------------------
# Real fakes (hand-rolled, not mocks)
# ---------------------------------------------------------------------------


class _Result:
    """Hand-rolled fake for the scitex_ssh.SSHResult / CompletedProcess shape."""

    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _res(**kwargs) -> _Result:
    return _Result(**kwargs)


class FakeRunner:
    """Fake ``exec_remote`` routing by which SLURM tool the command names.

    Real behaviour, not a mock: it inspects the command string the way the
    remote shell would, so a test can script squeue, sacct, and the sacct
    witness query independently.
    """

    def __init__(self, *, squeue=None, sacct=None, witness=None, raises=None):
        self.calls: list[tuple[str, str]] = []
        self._squeue = squeue if squeue is not None else _res()
        self._sacct = sacct
        self._witness = witness
        self._raises = raises

    def __call__(self, host, command, *, check=False, timeout=None):
        self.calls.append((host, command))
        if self._raises is not None:
            raise self._raises
        if "squeue" in command:
            return self._squeue
        if "sacct" in command:
            # The witness query is the one scoped to the whole user, with
            # neither --jobs nor --name narrowing it.
            is_witness = "--jobs=" not in command and "--name=" not in command
            if is_witness and self._witness is not None:
                return self._witness
            return self._sacct if self._sacct is not None else _res()
        raise AssertionError(f"unexpected command: {command}")

    @property
    def commands(self) -> list[str]:
        return [c for _, c in self.calls]


def _squeue_out(*rows: str) -> str:
    return BANNER + "".join(row + "\n" for row in rows)


def _row(job_id=JOB, state="RUNNING", node="spartan-bm021", name=NAME) -> str:
    return f"{job_id}|{state}|{node}|{name}"


# ---------------------------------------------------------------------------
# ALIVE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", sorted(ACTIVE_STATES))
def test_alive_verdict_for_every_active_state(state):
    # Arrange
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row(state=state))))
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert result.verdict == ALIVE


@pytest.mark.parametrize("state", sorted(ACTIVE_STATES))
def test_alive_reason_names_the_observed_state(state):
    # Arrange
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row(state=state))))
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert state in result.reason


def test_alive_is_settled_by_squeue_without_consulting_sacct():
    # Arrange
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row())))
    # Act
    job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert not any("sacct" in command for command in runner.commands)


def test_alive_when_identified_by_name_alone():
    # Arrange
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row())))
    # Act
    result = job_liveness(HOST, name=NAME, runner=runner)
    # Assert
    assert result.verdict == ALIVE


def test_name_only_lookup_does_not_invent_a_job_id():
    # Arrange
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row())))
    # Act
    result = job_liveness(HOST, name=NAME, runner=runner)
    # Assert
    assert result.job_id is None


def test_alive_survives_login_shell_banner_noise():
    """Banner lines must not shift the parse — the 2026-04-28 Spartan bug."""
    # Arrange
    stdout = "XAUTHORITY: /home/u/.Xauthority\nDISPLAY: 1.2.3.4:0\n" + _row() + "\n"
    runner = FakeRunner(squeue=_res(stdout=stdout))
    # Act
    result = job_liveness(HOST, job_id=JOB, runner=runner)
    # Assert
    assert result.verdict == ALIVE


def test_no_issued_command_ever_discards_stderr():
    """The premise of the whole module: nothing is redirected to /dev/null."""
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER),
        sacct=_res(stdout=BANNER + _row(state="COMPLETED") + "\n"),
    )
    # Act
    job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert runner.commands and all(
        "2>/dev/null" not in command for command in runner.commands
    )


# ---------------------------------------------------------------------------
# DEAD — only with positive evidence from both tools
# ---------------------------------------------------------------------------

_TERMINAL_SAMPLE = [
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "DEADLINE",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "PREEMPTED",
    "BOOT_FAIL",
    "REVOKED",
]


@pytest.mark.parametrize("state", _TERMINAL_SAMPLE)
def test_dead_when_absent_from_squeue_and_sacct_reports_terminal(state):
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER),  # the queue has no such job
        sacct=_res(stdout=BANNER + _row(state=state) + "\n"),
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert result.verdict == DEAD


@pytest.mark.parametrize("state", _TERMINAL_SAMPLE)
def test_dead_reason_records_the_terminal_state(state):
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER),
        sacct=_res(stdout=BANNER + _row(state=state) + "\n"),
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert state in result.reason


def test_dead_normalizes_sacct_cancelled_by_uid_suffix():
    """sacct renders cancellation as ``CANCELLED by 12345``."""
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER),
        sacct=_res(stdout=f"{JOB}|CANCELLED by 12345|None assigned|{NAME}\n"),
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert result.verdict == DEAD


def test_dead_when_absence_is_confirmed_by_both_tools():
    """Absent from squeue AND sacct, with the window provably populated."""
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER),
        sacct=_res(stdout=BANNER),  # no row for our target
        witness=_res(stdout=BANNER + _row(job_id="999", state="COMPLETED") + "\n"),
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, runner=runner)
    # Assert
    assert result.verdict == DEAD


def test_absence_dead_reason_cites_the_witness_query():
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER),
        sacct=_res(stdout=BANNER),
        witness=_res(stdout=_row(job_id="999", state="COMPLETED") + "\n"),
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, runner=runner)
    # Assert
    assert "witness" in result.reason


def test_dead_verdict_ignores_sacct_job_step_rows():
    """``.batch`` / ``.extern`` step rows must not be read as the job itself."""
    # Arrange
    stdout = (
        f"{JOB}|COMPLETED|spartan-bm021|{NAME}\n"
        f"{JOB}.batch|COMPLETED|spartan-bm021|batch\n"
        f"{JOB}.extern|COMPLETED|spartan-bm021|extern\n"
    )
    runner = FakeRunner(squeue=_res(stdout=BANNER), sacct=_res(stdout=stdout))
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert result.verdict == DEAD


def test_terminal_state_seen_in_squeue_still_consults_sacct():
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=_squeue_out(_row(state="COMPLETED"))),
        sacct=_res(stdout=_row(state="COMPLETED") + "\n"),
    )
    # Act
    job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert any("sacct" in command for command in runner.commands)


def test_terminal_state_seen_in_squeue_is_dead_once_sacct_confirms():
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=_squeue_out(_row(state="COMPLETED"))),
        sacct=_res(stdout=_row(state="COMPLETED") + "\n"),
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, name=NAME, runner=runner)
    # Assert
    assert result.verdict == DEAD


# ---------------------------------------------------------------------------
# UNKNOWN — every way a query can fail to be trustworthy
# ---------------------------------------------------------------------------


def _unknown_cases() -> dict[str, tuple[FakeRunner, dict, str]]:
    """label -> (fresh runner, call kwargs, substring the reason must carry).

    One registry, three tests: the verdict is UNKNOWN, the reason names the
    cause, and — the safety-critical one — none of them is ever DEAD.
    """
    both = {"job_id": JOB, "name": NAME}
    by_id = {"job_id": JOB}
    by_name = {"name": NAME}
    return {
        "squeue_non_zero_exit": (
            FakeRunner(
                squeue=_res(
                    returncode=1, stderr="slurm_load_jobs error: Unable to contact"
                )
            ),
            both,
            "rc=1",
        ),
        "squeue_module_not_loaded": (
            FakeRunner(
                squeue=_res(returncode=127, stderr="bash: squeue: command not found")
            ),
            both,
            "rc=127",
        ),
        "squeue_rc_zero_but_stderr_reports_failure": (
            FakeRunner(
                squeue=_res(
                    returncode=0,
                    stdout="",
                    stderr="slurm_load_jobs error: Socket timed out",
                )
            ),
            both,
            "stderr indicates failure",
        ),
        "ssh_transport_raises": (
            FakeRunner(raises=OSError("ssh: connect to host spartan: no route")),
            both,
            "OSError",
        ),
        "squeue_unparseable_state_token": (
            FakeRunner(squeue=_res(stdout=f"{JOB}|NOT_A_STATE|node|{NAME}\n")),
            both,
            "unparseable",
        ),
        "squeue_truncated_row": (
            FakeRunner(squeue=_res(stdout=f"{JOB}|RUNNING\n")),
            both,
            "unparseable",
        ),
        "name_collision_two_jobs": (
            FakeRunner(
                squeue=_res(stdout=_squeue_out(_row(job_id="111"), _row(job_id="222")))
            ),
            by_name,
            "collision",
        ),
        "recycled_job_id_name_mismatch": (
            FakeRunner(squeue=_res(stdout=_squeue_out(_row(name="someone-else")))),
            both,
            "recycled",
        ),
        "node_mismatch": (
            FakeRunner(squeue=_res(stdout=_squeue_out(_row(node="spartan-bm099")))),
            {"job_id": JOB, "name": NAME, "node": "spartan-bm021"},
            "identity mismatch",
        ),
        "non_committal_squeue_state": (
            FakeRunner(squeue=_res(stdout=_squeue_out(_row(state="SUSPENDED")))),
            both,
            "non-committal",
        ),
        "sacct_missing": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(returncode=127, stderr="bash: sacct: command not found"),
            ),
            both,
            "sacct could not be trusted",
        ),
        "sacct_not_permitted": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(returncode=1, stderr="sacct: error: Permission denied"),
            ),
            both,
            "sacct could not be trusted",
        ),
        "sacct_unparseable_output": (
            FakeRunner(
                squeue=_res(stdout=BANNER), sacct=_res(stdout=f"{JOB}|WAT|n|{NAME}\n")
            ),
            both,
            "unparseable",
        ),
        "sacct_name_collision": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(
                    stdout=_row(job_id="111", state="COMPLETED")
                    + "\n"
                    + _row(job_id="222", state="FAILED")
                    + "\n"
                ),
            ),
            by_name,
            "collision",
        ),
        "sacct_recycled_job_id": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(stdout=_row(state="COMPLETED", name="someone-else") + "\n"),
            ),
            both,
            "recycled",
        ),
        "job_id_outside_sacct_retention_window": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(stdout=""),
                witness=_res(stdout=""),
            ),
            by_id,
            "retention window",
        ),
        "sacct_witness_query_fails": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(stdout=""),
                witness=_res(
                    returncode=1, stderr="sacct: error: Unable to contact slurmdbd"
                ),
            ),
            by_id,
            "witness query could not be trusted",
        ),
        "squeue_absent_but_sacct_says_running": (
            FakeRunner(
                squeue=_res(stdout=BANNER),
                sacct=_res(stdout=_row(state="RUNNING") + "\n"),
            ),
            by_id,
            "contradiction",
        ),
    }


UNKNOWN_CASES = sorted(_unknown_cases())


@pytest.mark.parametrize("label", UNKNOWN_CASES)
def test_untrustworthy_query_yields_unknown(label):
    # Arrange
    runner, kwargs, _substring = _unknown_cases()[label]
    # Act
    result = job_liveness(HOST, runner=runner, **kwargs)
    # Assert
    assert result.verdict == UNKNOWN


@pytest.mark.parametrize("label", UNKNOWN_CASES)
def test_unknown_reason_names_the_cause(label):
    """Machine-readable evidence: the consumer must be able to log WHY."""
    # Arrange
    runner, kwargs, substring = _unknown_cases()[label]
    # Act
    result = job_liveness(HOST, runner=runner, **kwargs)
    # Assert
    assert substring in result.reason


@pytest.mark.parametrize("label", UNKNOWN_CASES)
def test_no_failure_path_ever_yields_dead(label):
    """The safety-critical invariant: DEAD must be EARNED, never defaulted."""
    # Arrange
    runner, kwargs, _substring = _unknown_cases()[label]
    # Act
    result = job_liveness(HOST, runner=runner, **kwargs)
    # Assert
    assert result.verdict != DEAD, f"{label} produced DEAD: {result.reason}"


def test_untrustworthy_squeue_does_not_proceed_to_sacct():
    """Absence is not evidence when the first query did not provably run."""
    # Arrange
    runner = FakeRunner(squeue=_res(returncode=1, stderr="slurm_load_jobs error"))
    # Act
    job_liveness(HOST, job_id=JOB, runner=runner)
    # Assert
    assert not any("sacct" in command for command in runner.commands)


def test_name_collision_reason_lists_every_matching_job_id():
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=_squeue_out(_row(job_id="111"), _row(job_id="222")))
    )
    # Act
    result = job_liveness(HOST, name=NAME, runner=runner)
    # Assert
    assert "111" in result.reason and "222" in result.reason


def test_unknown_without_any_identifier():
    # Arrange
    runner = FakeRunner()
    # Act
    result = job_liveness(HOST, node="spartan-bm021", runner=runner)
    # Assert
    assert result.verdict == UNKNOWN


def test_missing_identifier_asks_slurm_nothing():
    # Arrange
    runner = FakeRunner()
    # Act
    job_liveness(HOST, node="spartan-bm021", runner=runner)
    # Assert
    assert runner.calls == []


# ---------------------------------------------------------------------------
# Result shape / consumer contract
# ---------------------------------------------------------------------------


def _alive_result():
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row()), stderr="DISPLAY: :0"))
    return job_liveness(
        HOST, job_id=JOB, name=NAME, node="spartan-bm021", runner=runner
    )


def test_result_round_trips_through_json():
    # Arrange
    result = _alive_result()
    # Act
    payload = json.loads(json.dumps(result.to_dict()))
    # Assert
    assert payload["verdict"] == ALIVE


def test_result_reports_every_identifier_it_was_given():
    # Arrange
    result = _alive_result()
    # Act
    payload = result.to_dict()
    # Assert
    assert payload["identifiers"] == {
        "job_id": JOB,
        "name": NAME,
        "node": "spartan-bm021",
    }


def test_evidence_records_the_squeue_exit_status():
    # Arrange
    result = _alive_result()
    # Act
    payload = result.to_dict()
    # Assert
    assert payload["evidence"]["squeue"]["returncode"] == 0


def test_evidence_preserves_stderr_rather_than_discarding_it():
    # Arrange
    result = _alive_result()
    # Act
    payload = result.to_dict()
    # Assert
    assert "DISPLAY" in payload["evidence"]["squeue"]["stderr"]


def test_is_dead_property_is_true_for_a_dead_verdict():
    # Arrange
    runner = FakeRunner(
        squeue=_res(stdout=BANNER), sacct=_res(stdout=_row(state="FAILED") + "\n")
    )
    # Act
    result = job_liveness(HOST, job_id=JOB, runner=runner)
    # Assert
    assert result.is_dead is True


def test_is_dead_property_is_false_for_a_live_verdict():
    # Arrange
    runner = FakeRunner(squeue=_res(stdout=_squeue_out(_row())))
    # Act
    result = job_liveness(HOST, job_id=JOB, runner=runner)
    # Assert
    assert result.is_dead is False


def test_active_and_terminal_state_sets_are_disjoint():
    # Arrange
    active, terminal = ACTIVE_STATES, TERMINAL_STATES
    # Act
    overlap = active & terminal
    # Assert
    assert overlap == frozenset()
