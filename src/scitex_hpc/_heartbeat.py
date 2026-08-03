"""Heartbeat-liveness instrument — is a cadenced background loop still running?

``_liveness.py`` answers that question for SLURM *jobs*, where SLURM itself is
the authority. This module answers it for the other class of thing we run: a
bare loop on a node, holding a lockfile and appending a line to a log on a
fixed cadence. The gitconfig compaction bridge is the motivating case, but
nothing here is specific to it.

**A false STOPPED is the failure mode this module exists to prevent.** STOPPED
is what authorises *starting a replacement*, and for a component that
read-modify-writes shared state, two live copies means last-writer-wins on
fleet-wide data while both logs keep moving — the component presents as
healthy precisely because it is broken twice. So STOPPED must be EARNED from a
positive, node-local observation, exactly as DEAD is in ``_liveness.py``.

Decision contract
-----------------

======== =====================================================================
ALIVE    A holder is observed (a live PID whose cmdline matches, or the lock
         held against a non-blocking acquire) **and** the last heartbeat is
         within ``interval * grace``.
STALLED  A holder is observed but the cadence has been missed. The process
         exists and is not doing its job — never report this as ALIVE.
STOPPED  Positive, node-local evidence of *no holder*: the recorded PID is
         gone, or a non-blocking acquire of the lockfile SUCCEEDED, and the
         probe ran on the same node the component recorded at start.
UNKNOWN  Everything else. Transport failure, a truncated probe, no log, no
         known cadence, a PID whose cmdline does not match (recycled), or —
         importantly — any negative lock observation made from a DIFFERENT
         node than the holder's.
======== =====================================================================

Three traps this module encodes mechanically, each from a measured failure:

1. **Wrong node.** ``flock(2)`` is not guaranteed cluster-coherent on GPFS, and
   ``/proc`` is node-local by construction. A probe run on the login node
   against a compute-node holder can acquire a lock that is genuinely held —
   a false STOPPED. So a *negative* holder observation is only trusted when
   ``probe_host`` matches the host the component recorded in its START line.
   A *positive* one (lock held, PID alive) is safe from anywhere it is seen.
2. **Absent output read as absence in the world.** No log means UNKNOWN — "the
   path is wrong" and "it never started" are indistinguishable from here.
3. **Truncation read as data.** The probe emits ``__HB__end=1`` last; without
   it the output was cut short (SIGPIPE, a killed shell, a full pipe) and the
   verdict is UNKNOWN rather than a decision on a partial read.

Timestamps are taken from the REMOTE clock (``date -u +%s``) and compared to
the component's own UTC log stamps, so no local timezone ever enters the
arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from scitex_ssh import exec_remote

from ._dispatch import _quote
from ._liveness_probe import ALIVE, UNKNOWN, run_probe, squash

STALLED = "STALLED"
STOPPED = "STOPPED"

__all__ = [
    "ALIVE",
    "STALLED",
    "STOPPED",
    "UNKNOWN",
    "DEFAULT_GRACE",
    "HeartbeatResult",
    "heartbeat_liveness",
]

#: Multiplier applied to the cadence before a missed tick counts as STALLED.
#: 1.5 gives a half-interval of scheduling slack, which is generous for a
#: ``sleep``-driven loop and still catches a stopped one within one interval.
DEFAULT_GRACE = 1.5

#: Sentinel prefixing every key the probe emits. Login shells on HPC nodes
#: print banners (``XAUTHORITY: ...``, module-load chatter) that a bare
#: ``key=value`` parse would happily absorb; the sentinel makes probe output
#: unambiguous without having to enumerate the noise.
_K = "__HB__"

_STAMP_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z\b")
_INTERVAL_RE = re.compile(r"\binterval=(\d+)s?\b")
_PID_RE = re.compile(r"\bpid=(\d+)\b")
_HOST_RE = re.compile(r"\bhost=(\S+)")

#: Keys the probe must have emitted for any verdict other than UNKNOWN.
_REQUIRED = ("probe_host", "now", "log_present", "end")


@dataclass
class HeartbeatResult:
    """A verdict plus every observation that produced it."""

    verdict: str
    reason: str
    host: str = ""
    log: str = ""
    lock: str = ""
    age_seconds: float | None = None
    interval_seconds: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_stopped(self) -> bool:
        return self.verdict == STOPPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "host": self.host,
            "paths": {"log": self.log, "lock": self.lock},
            "cadence": {
                "age_seconds": self.age_seconds,
                "interval_seconds": self.interval_seconds,
            },
            "evidence": self.evidence,
        }


def _probe_script(log: str, lock: str) -> str:
    """Emit one sentinel-prefixed key=value block describing log and lock.

    Deliberately side-effect-free on the happy path: the lockfile is probed
    only when it already exists, so the probe never creates the very artifact
    whose absence it is reporting.

    One honest caveat, stated rather than engineered away: the ``flock``
    fallback holds the lock for the microseconds it takes to run ``true``, so
    a component starting in exactly that window would find the lock busy and
    exit. The PID path below is checked first precisely because it has no such
    window; the flock probe only runs when no PID was recorded.
    """
    lg, lk = _quote(log), _quote(lock)
    return f"""
LOG={lg}; LOCK={lk}
printf '{_K}probe_host=%s\\n' "$(hostname -s)"
printf '{_K}now=%s\\n' "$(date -u +%s)"
if [ -f "$LOG" ]; then
  printf '{_K}log_present=1\\n'
  printf '{_K}log_mtime=%s\\n' "$(stat -L -c %Y "$LOG")"
  printf '{_K}log_lines=%s\\n' "$(wc -l < "$LOG")"
  printf '{_K}log_last=%s\\n' "$(tail -n 1 "$LOG")"
  printf '{_K}start_count=%s\\n' "$(grep -c START "$LOG")"
  printf '{_K}start_last=%s\\n' "$(grep START "$LOG" | tail -n 1)"
else
  printf '{_K}log_present=0\\n'
fi
PID=""
if [ -e "$LOCK" ]; then
  printf '{_K}lock_present=1\\n'
  printf '{_K}lock_size=%s\\n' "$(stat -L -c %s "$LOCK")"
  PID=$(head -c 64 "$LOCK" | tr -dc '0-9')
  printf '{_K}lock_pid=%s\\n' "$PID"
else
  printf '{_K}lock_present=0\\n'
fi
if [ -n "$PID" ] && [ -r "/proc/$PID/cmdline" ]; then
  printf '{_K}pid_alive=1\\n'
  printf '{_K}pid_cmdline=%s\\n' "$(tr '\\0' ' ' < "/proc/$PID/cmdline")"
elif [ -n "$PID" ]; then
  printf '{_K}pid_alive=0\\n'
fi
if [ -z "$PID" ] && [ -e "$LOCK" ] && command -v flock >/dev/null 2>&1; then
  flock -n "$LOCK" true
  printf '{_K}flock_rc=%s\\n' "$?"
fi
printf '{_K}end=1\\n'
exit 0
""".strip()


def _parse(stdout: str) -> dict[str, str]:
    """Collect ``__HB__key=value`` lines; everything else is banner noise."""
    out: dict[str, str] = {}
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith(_K) or "=" not in stripped:
            continue
        key, _, value = stripped[len(_K) :].partition("=")
        out[key.strip()] = value.strip()
    return out


def _epoch(stamp: str) -> float | None:
    """``2026-08-03T06:15:36Z`` -> epoch seconds, or None if unparseable."""
    match = _STAMP_RE.search(stamp or "")
    if match is None:
        return None
    parsed = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def _int(fields: dict[str, str], key: str) -> int | None:
    raw = fields.get(key, "")
    return int(raw) if raw.isdigit() else None


def heartbeat_liveness(
    host: str,
    *,
    log: str,
    lock: str = "",
    interval: int | None = None,
    grace: float = DEFAULT_GRACE,
    match: str = "",
    runner: Callable[..., Any] | None = None,
) -> HeartbeatResult:
    """Decide ALIVE / STALLED / STOPPED / UNKNOWN for a heartbeat loop.

    ``interval`` overrides the cadence; when omitted it is read from the
    component's own START line (``interval=1800s``). ``match`` is a substring
    the holder's ``/proc/<pid>/cmdline`` must contain — the guard against a
    recycled PID, mirroring the recycled-job-id check in ``_liveness.py``.

    ``runner`` is the dependency-injection seam used package-wide: a callable
    shaped like ``exec_remote(host, command) -> result(returncode, stdout,
    stderr)``.
    """
    run = runner if runner is not None else exec_remote
    probe = run_probe(run, host, _probe_script(log, lock))
    evidence: dict[str, Any] = {"probe": probe.summary()}
    base = {"host": host, "log": log, "lock": lock, "evidence": evidence}

    failure = probe.failure_reason()
    if failure is not None:
        return HeartbeatResult(
            UNKNOWN, f"probe could not be trusted ({failure})", **base
        )

    fields = _parse(probe.stdout)
    evidence["fields"] = dict(fields)
    missing = [key for key in _REQUIRED if key not in fields]
    if missing:
        return HeartbeatResult(
            UNKNOWN,
            f"probe output incomplete, missing {missing!r} — a truncated read "
            "must not become a verdict",
            **base,
        )

    if fields["log_present"] != "1":
        return HeartbeatResult(
            UNKNOWN,
            f"no log at {log!r} — 'never started' and 'wrong path' are "
            "indistinguishable from here; absence of output is not absence "
            "in the world",
            **base,
        )

    start_last = fields.get("start_last", "")
    interval_s = interval
    if interval_s is None:
        found = _INTERVAL_RE.search(start_last)
        interval_s = int(found.group(1)) if found else None
    if not interval_s:
        return HeartbeatResult(
            UNKNOWN,
            "cadence unknown: no --interval given and no 'interval=<n>s' in "
            f"the START line ({squash(start_last, 120)!r}); an age alone "
            "cannot decide whether a tick was missed",
            **base,
            interval_seconds=interval_s,
        )

    now = _int(fields, "now")
    last_epoch = _epoch(fields.get("log_last", ""))
    stamp_source = "log line"
    if last_epoch is None:
        last_epoch = _int(fields, "log_mtime")
        stamp_source = "file mtime (last line carried no UTC stamp)"
    if now is None or last_epoch is None:
        return HeartbeatResult(
            UNKNOWN,
            "could not establish an age: remote clock or last-tick timestamp "
            "unreadable",
            **base,
            interval_seconds=interval_s,
        )

    age = float(now - last_epoch)
    fresh = age <= interval_s * grace
    evidence["stamp_source"] = stamp_source
    common = dict(base, age_seconds=age, interval_seconds=interval_s)
    cadence = (
        f"last tick {age:.0f}s ago via {stamp_source}, cadence {interval_s}s "
        f"(grace x{grace})"
    )
    return _verdict(fields, common, cadence=cadence, fresh=fresh, match=match)


def _verdict(
    fields: dict[str, str],
    common: dict[str, Any],
    *,
    cadence: str,
    fresh: bool,
    match: str,
) -> HeartbeatResult:
    """Combine the holder observation with the cadence observation.

    Split out so the node-trust rule sits in one place: a POSITIVE holder
    observation is trusted from anywhere, a NEGATIVE one only from the node
    the component recorded at start.
    """
    probe_host = fields.get("probe_host", "")
    found = _HOST_RE.search(fields.get("start_last", ""))
    start_host = found.group(1) if found else ""
    same_node = bool(start_host) and probe_host == start_host
    where = f"probed on {probe_host!r}, component started on {start_host or '?'!r}"

    cmdline = fields.get("pid_cmdline", "")
    pid = fields.get("lock_pid", "")
    if fields.get("pid_alive") == "1":
        if match and match not in cmdline:
            return HeartbeatResult(
                UNKNOWN,
                f"pid {pid} is alive but its cmdline does not contain "
                f"{match!r} ({squash(cmdline, 120)!r}) — possible recycled "
                "pid; refusing to read it as the holder",
                **common,
            )
        verdict = ALIVE if fresh else STALLED
        held = f"pid {pid} alive"
        return HeartbeatResult(
            verdict,
            f"{held} and {cadence}"
            if fresh
            else f"{held} but the cadence was missed: {cadence}",
            **common,
        )

    if fields.get("pid_alive") == "0":
        if not same_node:
            return HeartbeatResult(
                UNKNOWN,
                f"pid {pid} has no /proc entry, but /proc is node-local and "
                f"{where}; a negative holder observation from the wrong node "
                "cannot earn STOPPED",
                **common,
            )
        return HeartbeatResult(
            STOPPED,
            f"pid {pid} recorded in the lockfile has no /proc entry on "
            f"{probe_host} (the node it started on); {cadence}",
            **common,
        )

    flock_rc = fields.get("flock_rc")
    if flock_rc == "0":
        if not same_node:
            return HeartbeatResult(
                UNKNOWN,
                "a non-blocking acquire of the lockfile SUCCEEDED, but "
                f"{where} and flock is not guaranteed cluster-coherent on "
                "shared storage; refusing a STOPPED that could authorise a "
                "second concurrent copy",
                **common,
            )
        return HeartbeatResult(
            STOPPED,
            f"non-blocking acquire of the lockfile succeeded on {probe_host} "
            f"(the node it started on) — no holder; {cadence}",
            **common,
        )
    if flock_rc is not None:
        verdict = ALIVE if fresh else STALLED
        held = f"lockfile is held (flock rc={flock_rc}, no pid recorded)"
        return HeartbeatResult(
            verdict,
            f"{held} and {cadence}"
            if fresh
            else f"{held} but the cadence was missed: {cadence}",
            **common,
        )

    return HeartbeatResult(
        UNKNOWN,
        "no holder observation available: the lockfile carries no pid and "
        f"flock could not be used ({where}); cadence says {cadence}, which "
        "alone cannot distinguish a live loop from a dead one that stopped "
        "less than one interval ago",
        **common,
    )
