"""Read-only census of stale ``.git/index.lock`` across the Spartan repo estate.

59 of 108 Spartan repos were found write-locked by 0-byte ``index.lock`` on
2026-08-15, laid in batches by a recurring nightly process that has still not
been identified. Clearing them destroyed their mtimes — the only evidence that
could have named the cause.

This monitor removes nothing. It records ``mtime_epoch`` for every lock it
finds, so the next occurrence can be correlated against ``sacct --format=End``
in epoch seconds before anyone clears anything.

See README.md for why a stale lock is invisible to every read-only check, and
for the three design choices (realpath dedup, loud zero-scan failure, interval
rather than calendar) that are responses to specific measured mistakes.
"""

from __future__ import annotations

from pathlib import Path

#: Directory holding the census script and its systemd units.
PACKAGE_DIR = Path(__file__).resolve().parent

#: The census itself. Read-only; exits 1 when locks are present, 2 when it
#: scanned nothing (a failed look, which must not read as a clean estate).
CENSUS_SCRIPT = PACKAGE_DIR / "index-lock-census.sh"

#: systemd user units. The service excludes exit 2 from SuccessExitStatus on
#: purpose, so a failed look renders as a failure while a true detection does
#: not.
SERVICE_UNIT = PACKAGE_DIR / "index-lock-census.service"
TIMER_UNIT = PACKAGE_DIR / "index-lock-census.timer"

__all__ = ["PACKAGE_DIR", "CENSUS_SCRIPT", "SERVICE_UNIT", "TIMER_UNIT"]
