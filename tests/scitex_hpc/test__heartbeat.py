"""Tests for the heartbeat-liveness instrument.

Hand-rolled fakes injected through the ``runner=`` DI seam — no mocking
library, matching ``test__liveness.py`` and ``test__reservation.py``.

The UNKNOWN paths are again the point. A false STOPPED authorises starting a
replacement, and two copies of a component that read-modify-writes shared
state means last-writer-wins on fleet data while BOTH logs keep moving — so it
presents as healthy. Every failure mode is registered in :data:`UNKNOWN_CASES`
and swept by ``test_no_failure_path_ever_yields_stopped``.
"""

from __future__ import annotations

import pytest

from scitex_hpc._heartbeat import (
    ALIVE,
    STALLED,
    STOPPED,
    UNKNOWN,
    heartbeat_liveness,
)

HOST = "spartan"
NODE = "spartan-bm062"
OTHER_NODE = "spartan-login1"
LOG = "/home/u/.scitex/hpc/runtime/gitconfig-dedupe.log"
LOCK = "/home/u/.scitex/hpc/runtime/gitconfig-dedupe.lock"
PID = "143312"

#: Epoch seconds for 2026-08-03T06:15:36Z, hardcoded rather than computed so
#: the test cannot agree with the implementation by sharing its bug. Confirmed
#: against an independent clock: this session's runtime stamped a file at
#: 1785739446, and 1785739446 - 1785737736 = 1710s = 28m30s, matching the
#: observed gap between that tick and the 06:45:00Z reading beside it.
TICK_EPOCH = 1785737736
TICK_STAMP = "2026-08-03T06:15:36Z"

BANNER = "XAUTHORITY: /home/u/.Xauthority\nDISPLAY: 1.2.3.4:0\n"

START = f"2026-07-30T05:45:32Z bridge START pid={PID} host={NODE} interval=1800s"

BRIDGE_CMDLINE = (
    "/bin/bash /home/u/.scitex/hpc/runtime/gitconfig-dedupe-bridge.sh "
)

#: Keyword arguments that belong to ``heartbeat_liveness`` rather than to the
#: canned probe output.
CALL_KEYS = {"interval", "grace", "match"}

#: Observations that reach the cross-node branch, where a negative holder
#: reading must not be trusted.
FROM_ANOTHER_NODE = {"probe_host": OTHER_NODE}

NO_PID_RECORDED = {"lock_pid": None, "pid_alive": None}


class _Result:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Returns canned probe output; records every command it was given."""

    def __init__(self, *, result: _Result | None = None, raises: str = ""):
        self._result = result if result is not None else _Result()
        self._raises = raises
        self.calls: list[str] = []

    def __call__(self, host, command, *, check=False, timeout=None):
        self.calls.append(command)
        if self._raises:
            raise RuntimeError(self._raises)
        return self._result


def probe_out(
    *,
    probe_host: str = NODE,
    now: int | str = TICK_EPOCH + 300,
    log_present: str = "1",
    last: str = f"{TICK_STAMP} skip bytes=17411",
    start_last: str = START,
    lock_pid: str | None = PID,
    pid_alive: str | None = "1",
    pid_cmdline: str = BRIDGE_CMDLINE,
    flock_rc: str | None = None,
    end: bool = True,
    banner: bool = False,
) -> str:
    """Build one probe stdout block, defaulting to the healthy observation."""
    lines = [
        f"__HB__probe_host={probe_host}",
        f"__HB__now={now}",
        f"__HB__log_present={log_present}",
    ]
    if log_present == "1":
        lines += [
            f"__HB__log_mtime={now}",
            "__HB__log_lines=195",
            f"__HB__log_last={last}",
            "__HB__start_count=1",
            f"__HB__start_last={start_last}",
        ]
    lines.append("__HB__lock_present=1")
    lines.append(f"__HB__lock_pid={lock_pid if lock_pid is not None else ''}")
    if pid_alive is not None:
        lines.append(f"__HB__pid_alive={pid_alive}")
        if pid_alive == "1":
            lines.append(f"__HB__pid_cmdline={pid_cmdline}")
    if flock_rc is not None:
        lines.append(f"__HB__flock_rc={flock_rc}")
    if end:
        lines.append("__HB__end=1")
    body = "\n".join(lines) + "\n"
    return (BANNER + body) if banner else body


def check(**kw):
    """Run the instrument against one canned probe; return (result, runner)."""
    probe_kw = {k: v for k, v in kw.items() if k not in CALL_KEYS}
    call_kw = {k: v for k, v in kw.items() if k in CALL_KEYS}
    runner = FakeRunner(result=_Result(stdout=probe_out(**probe_kw)))
    result = heartbeat_liveness(HOST, log=LOG, lock=LOCK, runner=runner, **call_kw)
    return result, runner


def command_issued(**kw) -> str:
    """The single shell command the instrument sent to the runner."""
    _, runner = check(**kw)
    return runner.calls[0]


# --------------------------------------------------------------------------
# ALIVE
# --------------------------------------------------------------------------


def test_alive_when_pid_is_live_and_cadence_is_fresh():
    # Arrange: the healthy default — a live pid, last tick 300s into a 1800s
    # cadence.
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_alive_result_records_the_age():
    # Arrange
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.age_seconds == 300


def test_alive_result_records_the_interval():
    # Arrange
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.interval_seconds == 1800


def test_a_tick_not_yet_due_is_alive_not_unknown():
    # Arrange: one second short of the next scheduled tick. This is the card's
    # central requirement — 'no tick yet, within interval' is HEALTHY and must
    # not be collapsed into either pole.
    kw = {"now": TICK_EPOCH + 1799}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_alive_from_a_held_lock_when_no_pid_was_recorded():
    # Arrange: today's live bridge — a 0-byte lockfile, so flock rc=1 (held)
    # is the only holder evidence available.
    kw = dict(NO_PID_RECORDED, flock_rc="1")
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_held_lock_reason_notes_the_absent_pid():
    # Arrange
    kw = dict(NO_PID_RECORDED, flock_rc="1")
    # Act
    result, _ = check(**kw)
    # Assert
    assert "no pid recorded" in result.reason


def test_alive_survives_login_shell_banner_noise():
    # Arrange
    kw = {"banner": True}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_interval_is_read_from_the_components_own_start_line():
    # Arrange: no --interval passed; the START line carries interval=1800s.
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.interval_seconds == 1800


def test_start_line_cadence_appears_in_the_reason():
    # Arrange
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert "cadence 1800s" in result.reason


def test_explicit_interval_overrides_the_start_line():
    # Arrange
    kw = {"interval": 60}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.interval_seconds == 60


def test_explicit_interval_changes_the_verdict():
    # Arrange: a 300s age is healthy at 1800s cadence and stalled at 60s.
    kw = {"interval": 60}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == STALLED


def test_age_is_computed_in_utc_from_the_remote_clock():
    # Arrange: a stamp read as local time on a UTC+10 cluster would be 36000s
    # out, turning this healthy 300s age into STALLED. Pinning both sides to
    # the remote clock's UTC epoch is what keeps the arithmetic honest.
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.age_seconds == 300


# --------------------------------------------------------------------------
# STALLED — present but not working
# --------------------------------------------------------------------------


def test_stalled_when_holder_is_live_but_cadence_was_missed():
    # Arrange: three hours since the last tick on a 30-minute cadence.
    kw = {"now": TICK_EPOCH + 10800}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == STALLED


def test_stalled_reason_names_the_missed_cadence():
    # Arrange
    kw = {"now": TICK_EPOCH + 10800}
    # Act
    result, _ = check(**kw)
    # Assert
    assert "cadence was missed" in result.reason


def test_stalled_is_never_reported_as_alive():
    # Arrange
    kw = {"now": TICK_EPOCH + 10800}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict != ALIVE


def test_stalled_from_a_held_lock_without_a_pid():
    # Arrange
    kw = dict(NO_PID_RECORDED, flock_rc="1", now=TICK_EPOCH + 10800)
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == STALLED


def test_age_just_inside_the_grace_window_is_alive():
    # Arrange: 1800 * 1.5 = 2700s.
    kw = {"now": TICK_EPOCH + 2699}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_age_just_outside_the_grace_window_is_stalled():
    # Arrange
    kw = {"now": TICK_EPOCH + 2701}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == STALLED


# --------------------------------------------------------------------------
# STOPPED — only from a node-local negative observation
# --------------------------------------------------------------------------


def test_stopped_when_recorded_pid_is_gone_on_its_own_node():
    # Arrange
    kw = {"pid_alive": "0"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == STOPPED


def test_stopped_result_exposes_the_is_stopped_predicate():
    # Arrange
    kw = {"pid_alive": "0"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.is_stopped


def test_stopped_reason_names_the_node_that_earned_it():
    # Arrange
    kw = {"pid_alive": "0"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert "the node it started on" in result.reason


def test_stopped_when_a_nonblocking_acquire_succeeds_on_its_own_node():
    # Arrange
    kw = dict(NO_PID_RECORDED, flock_rc="0")
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == STOPPED


# --------------------------------------------------------------------------
# The node rule — the false-STOPPED guard
# --------------------------------------------------------------------------


def test_missing_proc_entry_from_another_node_is_unknown_not_stopped():
    # Arrange: /proc is node-local, so the login node cannot see a compute
    # node's processes; reading that absence as STOPPED is the false STOPPED.
    kw = dict(FROM_ANOTHER_NODE, pid_alive="0")
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == UNKNOWN


def test_cross_node_proc_reason_names_node_locality():
    # Arrange
    kw = dict(FROM_ANOTHER_NODE, pid_alive="0")
    # Act
    result, _ = check(**kw)
    # Assert
    assert "node-local" in result.reason


def test_successful_acquire_from_another_node_is_unknown_not_stopped():
    # Arrange: flock is not guaranteed cluster-coherent on shared storage.
    kw = dict(NO_PID_RECORDED, **FROM_ANOTHER_NODE, flock_rc="0")
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == UNKNOWN


def test_cross_node_acquire_reason_names_cluster_coherence():
    # Arrange
    kw = dict(NO_PID_RECORDED, **FROM_ANOTHER_NODE, flock_rc="0")
    # Act
    result, _ = check(**kw)
    # Assert
    assert "cluster-coherent" in result.reason


def test_cross_node_unknown_explains_what_it_would_have_authorised():
    # Arrange
    kw = dict(NO_PID_RECORDED, **FROM_ANOTHER_NODE, flock_rc="0")
    # Act
    result, _ = check(**kw)
    # Assert
    assert "second concurrent copy" in result.reason


def test_a_positive_holder_observation_is_trusted_from_any_node():
    # Arrange: asymmetry by design — seeing a holder is evidence wherever you
    # stand; failing to see one is only evidence where it would be visible.
    kw = dict(FROM_ANOTHER_NODE)
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_unparseable_start_host_cannot_earn_stopped():
    # Arrange: a START line with no host= field leaves same-node unprovable.
    kw = {"pid_alive": "0", "start_last": "bridge START pid=1 interval=60s"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == UNKNOWN


# --------------------------------------------------------------------------
# UNKNOWN — the sweep
# --------------------------------------------------------------------------


UNKNOWN_CASES: dict[str, tuple[dict, str]] = {
    "no_log": ({"log_present": "0"}, "absence of output is not absence"),
    "truncated_probe": ({"end": False}, "truncated read"),
    "no_holder_evidence": (
        dict(NO_PID_RECORDED, flock_rc=None),
        "no holder observation available",
    ),
    "proc_absent_wrong_node": (
        dict(FROM_ANOTHER_NODE, pid_alive="0"),
        "node-local",
    ),
    "acquired_wrong_node": (
        dict(NO_PID_RECORDED, **FROM_ANOTHER_NODE, flock_rc="0"),
        "cluster-coherent",
    ),
    "no_cadence": (
        {"start_last": "2026-07-30T05:45:32Z bridge START pid=1 host=n1"},
        "cadence unknown",
    ),
    # An unstamped log line alone is NOT this case — the mtime fallback
    # answers it, and an earlier version of this entry passed `now=0` and got
    # a healthy ALIVE with age 0. Both clocks have to be unreadable.
    "unreadable_timestamps": (
        {"last": "no stamp here", "now": "clock-unreadable"},
        "could not establish an age",
    ),
}


@pytest.mark.parametrize("label", sorted(UNKNOWN_CASES))
def test_failure_modes_yield_unknown(label):
    # Arrange
    kw, _ = UNKNOWN_CASES[label]
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == UNKNOWN


@pytest.mark.parametrize("label", sorted(UNKNOWN_CASES))
def test_unknown_reason_names_the_cause(label):
    # Arrange
    kw, fragment = UNKNOWN_CASES[label]
    # Act
    result, _ = check(**kw)
    # Assert
    assert fragment in result.reason


@pytest.mark.parametrize("label", sorted(UNKNOWN_CASES))
def test_no_failure_path_ever_yields_stopped(label):
    # Arrange: the invariant — STOPPED authorises a replacement, so no failure
    # path may reach it.
    kw, _ = UNKNOWN_CASES[label]
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict != STOPPED


def test_recycled_pid_is_unknown_not_alive():
    # Arrange
    kw = {"pid_cmdline": "/usr/bin/python3 something-else.py", "match": "bridge"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == UNKNOWN


def test_recycled_pid_reason_says_so():
    # Arrange
    kw = {"pid_cmdline": "/usr/bin/python3 something-else.py", "match": "bridge"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert "recycled" in result.reason


def test_matching_cmdline_still_reads_as_alive():
    # Arrange
    kw = {"match": "bridge"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.verdict == ALIVE


def test_transport_exception_is_unknown():
    # Arrange
    runner = FakeRunner(raises="ssh died")
    # Act
    result = heartbeat_liveness(HOST, log=LOG, lock=LOCK, runner=runner)
    # Assert
    assert result.verdict == UNKNOWN


def test_transport_exception_reason_says_the_probe_was_untrusted():
    # Arrange
    runner = FakeRunner(raises="ssh died")
    # Act
    result = heartbeat_liveness(HOST, log=LOG, lock=LOCK, runner=runner)
    # Assert
    assert "could not be trusted" in result.reason


def test_nonzero_exit_is_unknown():
    # Arrange
    runner = FakeRunner(result=_Result(returncode=255, stdout=probe_out()))
    # Act
    result = heartbeat_liveness(HOST, log=LOG, lock=LOCK, runner=runner)
    # Assert
    assert result.verdict == UNKNOWN


def test_rc_zero_with_failing_stderr_is_unknown():
    # Arrange: rc=0 alongside 'command not found' is the silent-substitution
    # shape — a plausible answer that ends the search.
    runner = FakeRunner(
        result=_Result(stdout=probe_out(), stderr="bash: flock: command not found")
    )
    # Act
    result = heartbeat_liveness(HOST, log=LOG, lock=LOCK, runner=runner)
    # Assert
    assert result.verdict == UNKNOWN


# --------------------------------------------------------------------------
# The probe itself
# --------------------------------------------------------------------------


def test_probe_guards_the_lockfile_read_on_its_existence():
    # Arrange: a probe that created the lockfile would manufacture its own
    # evidence.
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert 'if [ -e "$LOCK" ]; then' in command


def test_probe_issues_at_most_one_flock_attempt():
    # Arrange
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert command.count("flock -n") == 1


def test_probe_only_reaches_for_flock_when_no_pid_was_recorded():
    # Arrange: the pid path has no lock-holding window, so it is preferred.
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert '[ -z "$PID" ] && [ -e "$LOCK" ]' in command


def test_probe_ends_with_a_completion_marker():
    # Arrange
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert "__HB__end=1" in command


def test_probe_never_swallows_stderr_on_a_measurement():
    # Arrange: the rule _liveness.py exists to enforce — 2>/dev/null is what
    # makes "it said no" and "I could not ask" indistinguishable.
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert "2>/dev/null" not in command


def test_probe_has_exactly_one_devnull_redirect():
    # Arrange
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert command.count("/dev/null") == 1


def test_the_only_devnull_redirect_is_the_flock_capability_check():
    # Arrange: a capability probe is not a measurement, so it may be quiet.
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert "command -v flock >/dev/null 2>&1" in command


def test_probe_reads_the_last_start_line_not_the_first():
    # Arrange: a restart appends a second START; the holder is the latest.
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert 'grep START "$LOG" | tail -n 1' in command


def test_probe_follows_symlinks_when_stating():
    # Arrange: stat without -L reports the link, not the file — a measured
    # failure on this exact log's sibling.
    kw: dict = {}
    # Act
    command = command_issued(**kw)
    # Assert
    assert 'stat -L -c %Y "$LOG"' in command


def test_only_one_probe_is_issued():
    # Arrange
    kw: dict = {}
    # Act
    _, runner = check(**kw)
    # Assert
    assert len(runner.calls) == 1


# --------------------------------------------------------------------------
# Result shape
# --------------------------------------------------------------------------


def test_to_dict_carries_the_verdict():
    # Arrange
    kw: dict = {}
    # Act
    payload = check(**kw)[0].to_dict()
    # Assert
    assert payload["verdict"] == ALIVE


def test_to_dict_carries_the_paths():
    # Arrange
    kw: dict = {}
    # Act
    payload = check(**kw)[0].to_dict()
    # Assert
    assert payload["paths"] == {"log": LOG, "lock": LOCK}


def test_to_dict_carries_the_cadence():
    # Arrange
    kw: dict = {}
    # Act
    payload = check(**kw)[0].to_dict()
    # Assert
    assert payload["cadence"] == {"age_seconds": 300.0, "interval_seconds": 1800}


def test_to_dict_carries_the_parsed_probe_fields():
    # Arrange
    kw: dict = {}
    # Act
    payload = check(**kw)[0].to_dict()
    # Assert
    assert payload["evidence"]["fields"]["probe_host"] == NODE


def test_to_dict_carries_the_raw_probe_returncode():
    # Arrange
    kw: dict = {}
    # Act
    payload = check(**kw)[0].to_dict()
    # Assert
    assert payload["evidence"]["probe"]["returncode"] == 0


def test_evidence_records_which_timestamp_source_was_used():
    # Arrange
    kw: dict = {}
    # Act
    result, _ = check(**kw)
    # Assert
    assert result.evidence["stamp_source"] == "log line"


def test_mtime_fallback_is_labelled_when_the_line_has_no_stamp():
    # Arrange
    kw = {"last": "skip bytes=17411"}
    # Act
    result, _ = check(**kw)
    # Assert
    assert "file mtime" in result.evidence["stamp_source"]
