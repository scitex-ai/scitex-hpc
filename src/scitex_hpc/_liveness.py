"""SLURM job-liveness instrument — the authoritative *dead* signal.

Once a SLURM allocation is gone, ``pam_slurm_adopt`` refuses login->compute
ssh, so a tmux/ssh probe against the compute node can only ever answer
UNKNOWN. SLURM itself, queried from the login node, is the only tool that
can positively say a job is over. ``sac db reconcile-remote`` consumes this
as ``INSTRUMENT_SLURM_JOB`` when deciding whether a stale remote agent row
may be tombstoned.

**A false DEAD tombstones a LIVE agent's row.** That is the failure mode
this module exists to prevent, and it drives every decision below.

The trap this module deliberately does NOT reuse
------------------------------------------------

``_reservation.py``'s ``_squeue_state()`` / ``refresh()`` run::

    squeue --jobs=<id> --noheader --format='%T %N' 2>/dev/null

Both swallow stderr *and* ignore the exit status, then hand empty stdout
onward. "Job not in the queue" and "squeue failed / SLURM unreachable /
module not loaded / ssh died" are therefore indistinguishable — each is an
empty string. A thin wrapper over that helper would report DEAD on a query
error, i.e. exactly the false DEAD forbidden here. Those helpers remain
correct for their own callers (they poll a job they just submitted) and are
left untouched; this module issues its **own** SLURM calls, never redirects
stderr, and always inspects the exit status.

Decision contract
-----------------

======== ====================================================================
ALIVE    ``squeue`` exited 0 **and** the job is present with a state in
         ``ACTIVE_STATES`` (RUNNING, PENDING, CONFIGURING, COMPLETING).
DEAD     Requires POSITIVE evidence, reachable only when the queries
         PROVABLY ran: ``squeue`` exited 0 with the job absent, **and**
         ``sacct`` exited 0 and either reports a state in
         ``TERMINAL_STATES``, or confirms the absence while a witness query
         proves sacct is recording within the window.
UNKNOWN  EVERYTHING else. Non-zero exit from either tool; stderr indicating
         failure; ssh/transport failure; an exception; unparseable output; a
         job-id outside the sacct retention window; sacct missing or not
         permitted; a name matching MORE THAN ONE job (collision — never
         "pick the first"); a recycled job-id whose name does not match.
======== ====================================================================

Two invariants, asserted by the test-suite:

1. Absence is only evidence when the query PROVABLY ran. The default is
   UNKNOWN; DEAD must be EARNED.
2. No failure path — parse failure, unexpected token, transport error — may
   ever produce DEAD.

Every verdict carries a machine-readable ``reason`` and an ``evidence``
mapping recording each probe, so a consumer can log *why* and tell "no"
apart from "couldn't ask".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from scitex_ssh import exec_remote

from ._dispatch import _quote
from ._liveness_probe import (
    ACTIVE_STATES,
    ALIVE,
    DEAD,
    DEFAULT_SACCT_WINDOW,
    TERMINAL_STATES,
    UNKNOWN,
    Row,
    base_job_id,
    parse_pipe_rows,
    run_probe,
    squash,
)

__all__ = [
    "ACTIVE_STATES",
    "TERMINAL_STATES",
    "ALIVE",
    "DEAD",
    "UNKNOWN",
    "DEFAULT_SACCT_WINDOW",
    "LivenessResult",
    "job_liveness",
]

_SACCT_FORMAT = "--noheader --parsable2 --format=JobID,State,NodeList,JobName"


@dataclass
class LivenessResult:
    """A verdict plus the evidence that produced it."""

    verdict: str
    reason: str
    host: str = ""
    job_id: str | None = None
    name: str | None = None
    node: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_dead(self) -> bool:
        return self.verdict == DEAD

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "host": self.host,
            "identifiers": {
                "job_id": self.job_id,
                "name": self.name,
                "node": self.node,
            },
            "evidence": self.evidence,
        }


def _unknown(reason: str, **kw: Any) -> LivenessResult:
    return LivenessResult(verdict=UNKNOWN, reason=reason, **kw)


def _identity_mismatch(row: Row, *, name: str | None, node: str | None) -> str | None:
    """Guard against a RECYCLED job-id now pointing at a different job."""
    if name and row.name and row.name != name:
        return f"job {row.job_id} is named {row.name!r}, asked about {name!r}"
    if node and row.node and node not in row.node:
        return f"job {row.job_id} runs on {row.node!r}, asked about {node!r}"
    return None


def job_liveness(
    host: str,
    *,
    job_id: str | None = None,
    name: str | None = None,
    node: str | None = None,
    sacct_window: str = DEFAULT_SACCT_WINDOW,
    runner: Callable[..., Any] | None = None,
) -> LivenessResult:
    """Decide ALIVE / DEAD / UNKNOWN for a SLURM job on ``host``.

    At least one of ``job_id`` / ``name`` is required (``node`` alone cannot
    identify a job; supplied alongside another identifier it acts as an
    extra cross-check, and a mismatch yields UNKNOWN).

    ``runner`` is the dependency-injection seam, matching the ``runner=``
    convention of ``_dispatch.py`` / ``_reservation.py`` / ``_walltime.py``:
    a callable shaped like
    ``exec_remote(host, command) -> result(returncode, stdout, stderr)``.
    Defaults to :func:`scitex_ssh.exec_remote`.
    """
    run = runner if runner is not None else exec_remote
    ids: dict[str, Any] = {"job_id": job_id, "name": name, "node": node}
    evidence: dict[str, Any] = {"identifiers": dict(ids)}

    if not job_id and not name:
        return _unknown(
            "no usable identifier: at least one of job_id / name is required "
            "(node alone cannot identify a job)",
            host=host,
            evidence=evidence,
            **ids,
        )

    # -- Step 1: the user's whole queue. -----------------------------------
    # Deliberately NOT ``squeue --jobs=<id>``: squeue exits non-zero with
    # "Invalid job id specified" once a job has left the queue, conflating
    # "finished" with "query failed". Listing the user's entire queue exits 0
    # whether or not our job is in it, so absence becomes a trustworthy
    # observation instead of an error code we would have to second-guess.
    probe = run_probe(run, host, "squeue --user=$USER --noheader --format='%i|%T|%N|%j'")
    evidence["squeue"] = probe.summary()

    failure = probe.failure_reason()
    if failure is not None:
        return _unknown(
            f"squeue could not be trusted ({failure}); absence is not evidence "
            "when the query did not provably run",
            host=host,
            evidence=evidence,
            **ids,
        )

    rows, bad = parse_pipe_rows(probe.stdout)
    if bad:
        return _unknown(
            f"squeue output had {len(bad)} unparseable data line(s), "
            f"first={squash(bad[0], 120)!r}",
            host=host,
            evidence=evidence,
            **ids,
        )

    if job_id:
        matches = [r for r in rows if base_job_id(r.job_id) == base_job_id(job_id)]
    else:
        matches = [r for r in rows if r.name == name]
    evidence["squeue_matches"] = [r.raw for r in matches]

    distinct = sorted({base_job_id(r.job_id) for r in matches})
    if len(distinct) > 1:
        return _unknown(
            f"name collision: {len(distinct)} distinct jobs matched "
            f"({', '.join(distinct)}); refusing to pick one",
            host=host,
            evidence=evidence,
            **ids,
        )

    if matches:
        row = matches[0]
        mismatch = _identity_mismatch(row, name=name, node=node)
        if mismatch is not None:
            return _unknown(
                f"identity mismatch (possible recycled job-id): {mismatch}",
                host=host,
                evidence=evidence,
                **ids,
            )
        if row.state in ACTIVE_STATES:
            return LivenessResult(
                verdict=ALIVE,
                reason=f"squeue rc=0, job {row.job_id} present with state={row.state}",
                host=host,
                evidence=evidence,
                **ids,
            )
        if row.state not in TERMINAL_STATES:
            # SUSPENDED / RESIZING / REQUEUED — real SLURM states we refuse
            # to read as either alive or over.
            return _unknown(
                f"job {row.job_id} present in squeue with non-committal "
                f"state={row.state or '(empty)'}",
                host=host,
                evidence=evidence,
                **ids,
            )
        # Terminal state still visible in squeue (the brief post-exit
        # window). sacct must still confirm before we say DEAD.
        evidence["squeue_terminal_state"] = row.state
        if not job_id:
            job_id = base_job_id(row.job_id)
            ids["job_id"] = job_id

    # -- Step 2: sacct. Absence from squeue alone is never enough. ---------
    return _confirm_dead_via_sacct(
        run,
        host,
        job_id=job_id,
        name=name,
        sacct_window=sacct_window,
        evidence=evidence,
        ids=ids,
    )


def _confirm_dead_via_sacct(
    run: Callable[..., Any],
    host: str,
    *,
    job_id: str | None,
    name: str | None,
    sacct_window: str,
    evidence: dict[str, Any],
    ids: Mapping[str, Any],
) -> LivenessResult:
    """Independent second confirmation. Only this can earn a DEAD verdict."""
    ids = dict(ids)
    if job_id:
        scope = f"--jobs={_quote(base_job_id(job_id))}"
    else:
        scope = f"--user=$USER --name={_quote(str(name))}"
    inner = f"sacct {scope} --starttime={_quote(sacct_window)} {_SACCT_FORMAT}"

    probe = run_probe(run, host, inner)
    evidence["sacct"] = probe.summary()

    failure = probe.failure_reason()
    if failure is not None:
        return _unknown(
            f"sacct could not be trusted ({failure}); squeue-absence alone is "
            "not positive evidence of death",
            host=host,
            evidence=evidence,
            **ids,
        )

    rows, bad = parse_pipe_rows(probe.stdout)
    if bad:
        return _unknown(
            f"sacct output had {len(bad)} unparseable data line(s), "
            f"first={squash(bad[0], 120)!r}",
            host=host,
            evidence=evidence,
            **ids,
        )

    # Drop job steps (``12345.batch`` / ``12345.extern``); only the parent
    # allocation's row describes the job as a whole.
    rows = [r for r in rows if "." not in r.job_id]

    if job_id:
        matches = [r for r in rows if base_job_id(r.job_id) == base_job_id(job_id)]
    else:
        matches = [r for r in rows if r.name == name]
    evidence["sacct_matches"] = [r.raw for r in matches]

    distinct = sorted({base_job_id(r.job_id) for r in matches})
    if len(distinct) > 1:
        return _unknown(
            f"name collision in sacct: {len(distinct)} distinct jobs matched "
            f"({', '.join(distinct)}); refusing to pick one",
            host=host,
            evidence=evidence,
            **ids,
        )

    if matches:
        return _verdict_from_sacct_row(
            matches[0], name=name, host=host, evidence=evidence, ids=ids
        )

    return _verdict_from_sacct_absence(
        run,
        host,
        sacct_window=sacct_window,
        evidence=evidence,
        ids=ids,
    )


def _verdict_from_sacct_row(
    row: Row,
    *,
    name: str | None,
    host: str,
    evidence: dict[str, Any],
    ids: Mapping[str, Any],
) -> LivenessResult:
    ids = dict(ids)
    if name and row.name and row.name != name:
        return _unknown(
            "identity mismatch (possible recycled job-id): sacct job "
            f"{row.job_id} is named {row.name!r}, asked about {name!r}",
            host=host,
            evidence=evidence,
            **ids,
        )
    if row.state in TERMINAL_STATES:
        return LivenessResult(
            verdict=DEAD,
            reason=(
                "squeue rc=0 and job absent from the queue; sacct rc=0 "
                f"terminal={row.state} for job {row.job_id}"
            ),
            host=host,
            evidence=evidence,
            **ids,
        )
    if row.state in ACTIVE_STATES:
        return _unknown(
            f"contradiction: job absent from squeue but sacct reports "
            f"state={row.state}; refusing to call it dead",
            host=host,
            evidence=evidence,
            **ids,
        )
    return _unknown(
        f"sacct state={row.state or '(empty)'} is neither active nor terminal; "
        "refusing to guess",
        host=host,
        evidence=evidence,
        **ids,
    )


def _verdict_from_sacct_absence(
    run: Callable[..., Any],
    host: str,
    *,
    sacct_window: str,
    evidence: dict[str, Any],
    ids: Mapping[str, Any],
) -> LivenessResult:
    """No sacct row for the target — is that death, or a blind spot?

    Three readings: the job finished and simply has no row we matched; the
    job-id predates the accounting retention window; or sacct is not
    recording at all. A witness query settles it — if sacct returns *other*
    jobs for this user in the same window, the window is provably populated
    and the absence is real evidence. Otherwise we cannot tell, so UNKNOWN.
    """
    ids = dict(ids)
    witness = run_probe(
        run,
        host,
        f"sacct --user=$USER --starttime={_quote(sacct_window)} {_SACCT_FORMAT}",
    )
    evidence["sacct_witness"] = witness.summary()

    failure = witness.failure_reason()
    if failure is not None:
        return _unknown(
            f"sacct returned no row for the target and the witness query could "
            f"not be trusted ({failure}); cannot distinguish a finished job "
            "from one outside the retention window",
            host=host,
            evidence=evidence,
            **ids,
        )

    witness_rows, witness_bad = parse_pipe_rows(witness.stdout)
    if witness_bad:
        return _unknown(
            f"sacct witness output had {len(witness_bad)} unparseable data "
            "line(s); cannot confirm the retention window is populated",
            host=host,
            evidence=evidence,
            **ids,
        )
    witness_rows = [r for r in witness_rows if "." not in r.job_id]

    if not witness_rows:
        return _unknown(
            f"sacct rc=0 but returned no rows at all for --starttime="
            f"{sacct_window}: the job-id may be outside the accounting "
            "retention window, or sacct may not be recording. Absence here is "
            "not evidence.",
            host=host,
            evidence=evidence,
            **ids,
        )

    return LivenessResult(
        verdict=DEAD,
        reason=(
            "absence confirmed by both tools: squeue rc=0 without the job, "
            "sacct rc=0 without the job, and the sacct witness query returned "
            f"{len(witness_rows)} row(s) proving the window is populated"
        ),
        host=host,
        evidence=evidence,
        **ids,
    )
