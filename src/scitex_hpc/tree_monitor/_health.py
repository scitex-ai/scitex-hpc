"""Is the monitor itself still alive? — the watcher's watcher.

A monitor nobody watches is a monitor that can die silently, and this fleet
already carries a card for exactly that shape
(``gitconfig-compaction-bridge-unsupervised-invisible-20260802``: real
load-bearing mitigation running unsupervised, with nothing to report its
death). The tree monitor has the same exposure — its whole value is being
there on the day something vanishes, and a timer that stopped three weeks
ago looks identical from the outside to one that has simply seen nothing.

THREE-VALUED, FOR THE SAME REASON THE MONITOR ITSELF IS. Freshness is
FRESH, STALE, or UNKNOWN:

    FRESH    a log line newer than ``max_age_s``
    STALE    a log line older than that — the timer is not firing
    UNKNOWN  no log, unreadable log, or an unparseable last line

UNKNOWN must NOT collapse into either pole. Collapsing it into FRESH is how
a dead monitor reports healthy — the failure this module exists to prevent.
Collapsing it into STALE pages on a first run before any line is written,
which trains the reader to ignore it. So it is reported as itself, and the
caller decides.

Pure and injectable: the clock and the log reader are arguments, so tests
never touch a real filesystem or a real wall clock.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

#: Reads a path, returning its text or ``None`` if it cannot be read.
LogReader = Callable[[str], Optional[str]]

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
_STATUSES = (FRESH, STALE, UNKNOWN)


@dataclass(frozen=True)
class Freshness:
    """The answer, in a fixed shape, every time.

    Each signal is its own named field so a caller never has to guess which
    key exists on this call. ``reason`` always states WHY — an UNKNOWN that
    does not say what it could not read is half an answer.
    """

    status: str
    reason: str
    last_line: Optional[str] = None
    age_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        # Validate where it is built, not three layers downstream.
        if self.status not in _STATUSES:
            raise ValueError(
                f"status must be one of {_STATUSES}, got {self.status!r}"
            )
        if not self.reason:
            raise ValueError("reason must be non-empty — say why, not just what")
        if self.status in (FRESH, STALE) and self.age_seconds is None:
            raise ValueError(f"{self.status} requires an age_seconds measurement")

    @property
    def ok(self) -> bool:
        """True only for FRESH. UNKNOWN is not success — read ``status``."""
        return self.status == FRESH


def _default_reader(path: str) -> Optional[str]:
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def _parse_stamp(line: str) -> Optional[datetime]:
    """Parse the leading ``YYYY-MM-DDTHH:MM:SSZ`` stamp the script writes."""
    head = line.strip().split(" ", 1)[0]
    try:
        return datetime.strptime(head, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def check_freshness(
    log_path: str,
    *,
    max_age_s: float = 900.0,
    now: Optional[datetime] = None,
    reader: LogReader = _default_reader,
) -> Freshness:
    """Report whether the monitor has logged recently enough.

    ``max_age_s`` defaults to 900s — three missed 5-minute windows. One
    missed window is ordinary (systemd ``AccuracySec``, a busy node); three
    consecutive is the timer not firing.
    """
    resolved = os.path.expanduser(os.path.expandvars(log_path))
    text = reader(resolved)
    if text is None:
        return Freshness(UNKNOWN, f"cannot read log at {resolved}")

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return Freshness(UNKNOWN, f"log at {resolved} is empty — monitor may never have run")

    last = lines[-1]
    stamp = _parse_stamp(last)
    if stamp is None:
        return Freshness(
            UNKNOWN,
            f"last line of {resolved} carries no parseable UTC stamp",
            last_line=last,
        )

    current = now or datetime.now(timezone.utc)
    age = (current - stamp).total_seconds()
    if age <= max_age_s:
        return Freshness(
            FRESH,
            f"last log line {age:.0f}s old (threshold {max_age_s:.0f}s)",
            last_line=last,
            age_seconds=age,
        )
    return Freshness(
        STALE,
        f"last log line {age:.0f}s old, over the {max_age_s:.0f}s threshold — "
        "the timer is probably not firing; check "
        "`systemctl --user list-timers` and the unit's last exit status",
        last_line=last,
        age_seconds=age,
    )
