"""Primitives for the SLURM liveness instrument: states, probes, parsing.

Split out of ``_liveness.py`` (which holds the decision logic) to keep each
module focused. Everything here is deliberately *non-deciding*: it runs a
command preserving every signal, or parses text without guessing. The
ALIVE / DEAD / UNKNOWN judgement lives next door.

The one rule that governs this file: **nothing is swallowed.** No
``2>/dev/null``, no discarded exit status, no "close enough" parse. A caller
must always be able to tell "the job is not there" apart from "I could not
ask".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ._dispatch import _wrap_in_login_shell
from ._reservation import _SLURM_STATES

ALIVE = "ALIVE"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"

#: States meaning the allocation still exists (or is about to).
ACTIVE_STATES: frozenset[str] = frozenset(
    {"RUNNING", "PENDING", "CONFIGURING", "COMPLETING"}
)

#: States that positively mean the job is over.
TERMINAL_STATES: frozenset[str] = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "DEADLINE",
        "OOM",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "PREEMPTED",
        "BOOT_FAIL",
        "REVOKED",
    }
)

#: Every state token we are willing to interpret. Reuses the vocabulary
#: already curated in ``_reservation.py`` so the two stay in step. Anything
#: outside this set is an unexpected token and must yield UNKNOWN, never a
#: guess.
KNOWN_STATES: frozenset[str] = _SLURM_STATES | ACTIVE_STATES | TERMINAL_STATES

#: Substrings marking stderr as a *failure report* rather than login-shell
#: banner noise. Chatty ``.bashrc`` files write plenty to stderr on HPC login
#: nodes, so non-empty stderr is not by itself a failure — but any of these
#: means the answer cannot be trusted.
STDERR_FAILURE_MARKERS: tuple[str, ...] = (
    "slurm_load",
    "error:",
    "invalid",
    "unable to contact",
    "socket timed out",
    "command not found",
    "permission denied",
    "connection refused",
    "connection closed",
    "connection timed out",
    "no route to host",
    "authentication failed",
    "protocol error",
    "broken pipe",
    "cannot connect",
    "timed out",
)

#: How far back sacct is asked to look. Anything older is treated as outside
#: the retention window (UNKNOWN), never as DEAD.
DEFAULT_SACCT_WINDOW = "now-7days"


def squash(text: str, limit: int = 400) -> str:
    """Collapse output to one truncated line, for machine-readable logging."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def stderr_failure_marker(stderr: str) -> str | None:
    """Return the marker that makes ``stderr`` a failure report, else None."""
    low = (stderr or "").lower()
    for marker in STDERR_FAILURE_MARKERS:
        if marker in low:
            return marker
    return None


@dataclass
class Probe:
    """Outcome of one remote SLURM invocation, with nothing swallowed."""

    command: str
    returncode: int | None
    stdout: str
    stderr: str
    exception: str | None = None

    @property
    def ok(self) -> bool:
        return self.exception is None and self.returncode == 0

    def failure_reason(self) -> str | None:
        """A reason string if this probe cannot be trusted, else None.

        Three independent ways a SLURM query can be untrustworthy, all of
        which the legacy ``2>/dev/null`` call sites erase: the transport
        raised, the tool exited non-zero, or the tool exited zero while
        printing an error to stderr.
        """
        if self.exception is not None:
            return f"transport/exception: {self.exception}"
        if self.returncode != 0:
            return f"rc={self.returncode} stderr={squash(self.stderr)}"
        marker = stderr_failure_marker(self.stderr)
        if marker is not None:
            return (
                f"rc=0 but stderr indicates failure ({marker!r}): "
                f"{squash(self.stderr)}"
            )
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": squash(self.stdout),
            "stderr": squash(self.stderr),
            "exception": self.exception,
        }


def run_probe(runner: Callable[..., Any], host: str, inner: str) -> Probe:
    """Run ``inner`` on ``host`` in a login shell, preserving rc AND stderr.

    Note the conspicuous absence of ``2>/dev/null`` — that redirection is
    the exact bug this instrument exists to avoid. An exception from the
    transport is captured rather than propagated, so the caller can render
    it as UNKNOWN evidence instead of crashing.
    """
    command = _wrap_in_login_shell(inner)
    try:
        result = runner(host, command)
    except Exception as exc:  # noqa: BLE001 — every failure must become UNKNOWN
        return Probe(
            command=command,
            returncode=None,
            stdout="",
            stderr="",
            exception=f"{type(exc).__name__}: {exc}",
        )
    return Probe(
        command=command,
        returncode=getattr(result, "returncode", None),
        stdout=getattr(result, "stdout", "") or "",
        stderr=getattr(result, "stderr", "") or "",
    )


@dataclass
class Row:
    """One parsed SLURM record: ``jobid|state|nodelist|jobname``."""

    job_id: str
    state: str
    node: str
    name: str
    raw: str


def normalize_state(token: str) -> str:
    """``"CANCELLED by 12345"`` -> ``"CANCELLED"``; strips a trailing ``+``."""
    text = (token or "").strip()
    head = text.split()[0] if text else ""
    return head.rstrip("+").upper()


def base_job_id(job_id: str) -> str:
    """``"12345.batch"`` / ``"12345_7"`` -> ``"12345"``."""
    return (job_id or "").split(".", 1)[0].split("_", 1)[0]


def parse_pipe_rows(stdout: str) -> tuple[list[Row], list[str]]:
    """Parse ``jobid|state|node|name`` rows, tolerating login-shell banners.

    Chatty ``.bashrc`` files prefix real output with lines like
    ``XAUTHORITY: /home/u/.Xauthority`` or ``DISPLAY: 1.2.3.4:0``. Like
    ``_reservation._parse_squeue_state_node``, we never assume line 1 is
    data: a line counts only when its leading field is a digit job-id
    (optionally ``<id>.<step>`` / ``<id>_<arrayidx>``).

    Returns ``(rows, unparseable_data_lines)``. Lines with no ``|`` at all,
    or whose first field is not a job-id, are banner noise and are skipped
    silently. A line that *looks* like data but does not parse — wrong field
    count, or an unrecognised state token — is returned in the second list
    so the caller can answer UNKNOWN rather than silently dropping it.
    """
    rows: list[Row] = []
    bad: list[str] = []
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        parts = stripped.split("|")
        head = parts[0].strip()
        if not base_job_id(head).isdigit():
            continue
        if len(parts) < 4:
            bad.append(stripped)
            continue
        state = normalize_state(parts[1])
        if state not in KNOWN_STATES:
            bad.append(stripped)
            continue
        rows.append(
            Row(
                job_id=head,
                state=state,
                node=parts[2].strip(),
                name=parts[3].strip(),
                raw=stripped,
            )
        )
    return rows, bad
