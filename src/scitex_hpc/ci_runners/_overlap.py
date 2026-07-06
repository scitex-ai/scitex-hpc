"""Run the supervisor body inside an ALREADY-RUNNING SLURM allocation.

``book-supervisor`` books a *new* dedicated node and hosts the fleet
there. On a full partition that node may never schedule (Spartan
``cascade`` is full; the dedicated job has been PENDING for days). This
module instead launches the *exact same* supervisor body — the one
:func:`scitex_hpc.ci_runners.build_supervisor_hold_body` generates — as a
job STEP inside an allocation that is already RUNNING, via
``srun --jobid=<holder> --overlap``.

Mechanics
---------
1. The supervisor body is written to a stable path on the host
   (``~/.scitex/ci/supervisor_body.sh``) so the step has a file to
   ``bash``.
2. ``srun --jobid=<holder> --overlap bash <body>`` starts a step that
   shares the holder's existing allocation (``--overlap`` lets it run
   alongside the holder's own steps instead of waiting for resources).
3. The launch is wrapped in ``setsid nohup ... &`` so the supervisor
   survives the launching (SSH) shell exiting. The step itself stays
   alive because the body ends in ``wait`` — that blocks in the
   foreground of the step, keeping the step (and therefore every
   backgrounded keep-alive loop) running until the holder allocation
   ends.

Pure string generation — no SSH, no SLURM — so it is unit-testable: a
test asserts on the generated body path and the exact ``srun`` argv.
"""

from __future__ import annotations

# Stable on-host path for the supervisor body the step will ``bash``.
# Stable (not a temp file) so the operator can inspect / re-run it.
DEFAULT_BODY_PATH = "$HOME/.scitex/ci/supervisor_body.sh"

# Where the detached supervisor's combined stdout/stderr is captured.
DEFAULT_LOG_PATH = "/tmp/scitex-ci-supervisor.log"

# Runtime file recording the CURRENT holder job id the supervisor step runs
# under. Written at exec-supervisor launch so the health watchdog
# (``ci-runners watch``) resolves the live holder without a fragile
# squeue-by-name lookup (which false-alarms on the overlap-step deploy).
# ``runtime/`` per the registry layout = ephemeral live state.
DEFAULT_HOLDER_JOBID_PATH = "$HOME/.scitex/hpc/runtime/ci-supervisor-holder.jobid"

# Absolute srun path — the holder's job env may have scrubbed PATH, and
# the supervisor body itself purges modules, so never rely on PATH here.
SRUN_BIN = "/apps/slurm/latest/bin/srun"


def build_write_body_command(
    hold_body: str,
    *,
    body_path: str = DEFAULT_BODY_PATH,
) -> str:
    """Return a shell command that writes ``hold_body`` to ``body_path``.

    Uses a quoted heredoc (``<<'SCITEX_CI_BODY'``) so nothing in the body
    is expanded at write time — the body's own ``$HOME`` / ``$(...)`` must
    survive verbatim to be evaluated later, inside the running step. The
    parent dir is created first; the file is made executable for the
    operator's convenience (the step ``bash``-es it explicitly regardless).
    """
    return (
        f'mkdir -p "$(dirname {body_path})" && '
        f"cat > {body_path} <<'SCITEX_CI_BODY'\n"
        f"{hold_body.rstrip()}\n"
        f"SCITEX_CI_BODY\n"
        f"chmod +x {body_path}"
    )


def build_overlap_srun_command(
    overlap_jobid: str,
    *,
    body_path: str = DEFAULT_BODY_PATH,
    log_path: str = DEFAULT_LOG_PATH,
    srun_bin: str = SRUN_BIN,
) -> str:
    """Return the detached ``srun --overlap`` launch command.

    ``setsid nohup`` detaches the step from the launching (SSH) shell so
    it persists after that shell exits; redirecting both streams to
    ``log_path`` and reading stdin from ``/dev/null`` keeps it fully
    background. The step runs ``bash <body_path>``; the body's trailing
    ``wait`` blocks in the foreground of the step, so the STEP stays alive
    (and with it every keep-alive loop) until the holder allocation ends.

    The trailing ``&`` backgrounds the whole ``setsid`` invocation so the
    SSH command returns immediately instead of blocking on the long-lived
    step.
    """
    return (
        f"setsid nohup {srun_bin} "
        f"--jobid={overlap_jobid} --overlap "
        f"bash {body_path} "
        f">{log_path} 2>&1 </dev/null &"
    )


def build_exec_supervisor_script(
    hold_body: str,
    overlap_jobid: str,
    *,
    body_path: str = DEFAULT_BODY_PATH,
    log_path: str = DEFAULT_LOG_PATH,
    srun_bin: str = SRUN_BIN,
    jobid_path: str = DEFAULT_HOLDER_JOBID_PATH,
) -> str:
    """Full remote script: write the body, then launch the overlap step.

    Also records ``overlap_jobid`` to ``jobid_path`` so the health watchdog
    (``ci-runners watch``) resolves the live holder from a file instead of a
    squeue-by-name lookup. On a walltime-resubmit the holder id changes and
    exec-supervisor is re-run against the new holder, which rewrites the
    file — so the watchdog always reads the current holder.

    This is what runs over SSH on the host. It is deterministic and
    side-effect-free to *generate* (no SSH, no SLURM), so the dry-run path
    can print it verbatim and tests can assert on it.
    """
    write = build_write_body_command(hold_body, body_path=body_path)
    launch = build_overlap_srun_command(
        overlap_jobid,
        body_path=body_path,
        log_path=log_path,
        srun_bin=srun_bin,
    )
    record_jobid = (
        f'mkdir -p "$(dirname {jobid_path})" 2>/dev/null || true\n'
        f'echo "{overlap_jobid}" > {jobid_path}'
    )
    return (
        f"{write}\n"
        f'echo "[scitex-ci] wrote supervisor body to {body_path}" >&2\n'
        f"{record_jobid}\n"
        f'echo "[scitex-ci] recorded holder jobid {overlap_jobid} to '
        f'{jobid_path}" >&2\n'
        f"{launch}\n"
        f'echo "[scitex-ci] launched overlap step on jobid {overlap_jobid}; '
        f'log: {log_path}" >&2'
    )
