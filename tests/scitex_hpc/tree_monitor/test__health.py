"""Freshness must stay THREE-valued, and UNKNOWN must not become success.

The point of these tests is not that the happy path returns FRESH. It is
that each of the three states is reachable FOR THE REASON IT NAMES, and
that the two collapses which would make this module useless are impossible:

    UNKNOWN -> FRESH   a dead monitor reporting healthy
    UNKNOWN -> STALE   an alarm on a first run, training people to ignore it

Every case injects both the clock and the reader, so nothing here touches a
real filesystem or a real wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scitex_hpc.tree_monitor import FRESH, STALE, UNKNOWN, Freshness, check_freshness

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


def _reader(text):
    """Return a reader yielding ``text`` (or None) regardless of path."""
    return lambda _path: text


def _line(when: datetime, msg: str = "ok 3 path(s) checked") -> str:
    return f"{when.strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"


# --------------------------------------------------------------------------
# FRESH
# --------------------------------------------------------------------------
def test_recent_line_reports_fresh():
    # Arrange
    reader = _reader(_line(NOW - timedelta(seconds=60)))
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert res.status == FRESH


def test_recent_line_is_ok():
    # Arrange
    reader = _reader(_line(NOW - timedelta(seconds=60)))
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert res.ok is True


def test_fresh_carries_the_measured_age():
    # Arrange
    reader = _reader(_line(NOW - timedelta(seconds=60)))
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert res.age_seconds == pytest.approx(60, abs=1)


def test_exactly_at_threshold_is_still_fresh():
    """Boundary is inclusive — one missed window must not alarm."""
    # Arrange
    reader = _reader(_line(NOW - timedelta(seconds=900)))
    # Act
    res = check_freshness("/nonexistent", max_age_s=900, now=NOW, reader=reader)
    # Assert
    assert res.status == FRESH


# --------------------------------------------------------------------------
# STALE — reachable, or the FRESH assertions above prove nothing
# --------------------------------------------------------------------------
def test_one_second_past_threshold_is_stale():
    # Arrange
    reader = _reader(_line(NOW - timedelta(seconds=901)))
    # Act
    res = check_freshness("/nonexistent", max_age_s=900, now=NOW, reader=reader)
    # Assert
    assert res.status == STALE


def test_stale_is_not_ok():
    # Arrange
    reader = _reader(_line(NOW - timedelta(seconds=901)))
    # Act
    res = check_freshness("/nonexistent", max_age_s=900, now=NOW, reader=reader)
    # Assert
    assert res.ok is False


def test_stale_reason_names_the_next_step():
    """An error that only states what broke is half-written."""
    # Arrange
    reader = _reader(_line(NOW - timedelta(hours=3)))
    # Act
    res = check_freshness("/nonexistent", max_age_s=60, now=NOW, reader=reader)
    # Assert
    assert "systemctl" in res.reason


# --------------------------------------------------------------------------
# UNKNOWN — three routes in, none collapsing to a pole
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [None, "", "   \n\n", "no stamp here at all", "2026-13-45 broken stamp"],
)
def test_unreadable_or_unparseable_log_is_unknown(text):
    # Arrange
    reader = _reader(text)
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert res.status == UNKNOWN


def test_missing_log_reason_says_it_could_not_read():
    # Arrange
    reader = _reader(None)
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert "cannot read" in res.reason


def test_empty_log_reason_says_it_may_never_have_run():
    # Arrange
    reader = _reader("")
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert "may never have run" in res.reason


def test_unstamped_line_reason_names_the_missing_stamp():
    # Arrange
    reader = _reader("no stamp here at all")
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert "no parseable UTC stamp" in res.reason


def test_unknown_is_not_ok():
    """The collapse that would make a dead monitor report healthy."""
    # Arrange
    reader = _reader(None)
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert res.ok is False


def test_unknown_carries_no_fabricated_age():
    # Arrange
    reader = _reader(None)
    # Act
    res = check_freshness("/nonexistent", now=NOW, reader=reader)
    # Assert
    assert res.age_seconds is None


# --------------------------------------------------------------------------
# The last line decides
# --------------------------------------------------------------------------
def test_last_line_decides_not_the_first():
    # Arrange
    reader = _reader(
        "\n".join(
            [_line(NOW - timedelta(seconds=10)), _line(NOW - timedelta(days=30))]
        )
    )
    # Act
    res = check_freshness("/nonexistent", max_age_s=900, now=NOW, reader=reader)
    # Assert
    assert res.status == STALE


# --------------------------------------------------------------------------
# The validator fires where the answer is BUILT, not downstream
# --------------------------------------------------------------------------
def test_bogus_status_is_rejected_at_construction():
    # Arrange
    made_up = "PROBABLY_FINE"
    # Act / Assert is a single raises block per TQ007
    # Assert
    with pytest.raises(ValueError, match="status must be one of"):
        Freshness(made_up, "made up")


def test_reason_may_not_be_empty():
    # Arrange
    no_reason = ""
    # Act
    # Assert
    with pytest.raises(ValueError, match="say why"):
        Freshness(UNKNOWN, no_reason)


def test_fresh_without_a_measurement_is_rejected():
    """FRESH is a claim about elapsed time; it must carry the measurement."""
    # Arrange
    unmeasured = None
    # Act
    # Assert
    with pytest.raises(ValueError, match="requires an age_seconds"):
        Freshness(FRESH, "trust me", age_seconds=unmeasured)
