"""Generate the sbatch *hold body* that supervises the runner fleet.

The supervisor runs as the sbatch job's main process on ONE dedicated
compute node. For every runner it spawns a **keep-alive loop**:

    while job alive:
        ./run.sh            # the GitHub Actions runner (blocks)
        # run.sh exited (crash, deregister, transient network death)
        log the exit, sleep <backoff>, loop -> relaunch

so a runner that dies is back within ``<backoff>`` seconds without any
human or cron involvement. The supervisor then ``wait``s on all loops;
when SLURM signals the job (walltime, scancel) every loop is torn down
with its cgroup.

This body is handed to :meth:`scitex_hpc.Reservation.book` as
``hold_body`` together with ``persistent=True``; the Reservation layer
wraps it with the SIGUSR1 walltime-resubmit trap, so the fleet survives
the cluster walltime cap indefinitely.

Pure string generation — no SSH, no SLURM, fully unit-testable.
"""

from __future__ import annotations

from ._fleet import FleetSpec, RunnerSpec

# Environment hardening every runner needs, captured ONCE here instead of
# copy-pasted across the five band-aid scripts. Scrubs the EasyBuild
# module env (which broke runner Python/Node resolution), pins a
# user-site-free interpreter, and keeps ``_work`` off the home quota.
_ENV_HARDENING = r"""# --- scitex-ci shared runner env hardening ---
source "$HOME/.bashrc" 2>/dev/null || true
module purge 2>/dev/null || true
unset PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
_scrub() { echo "${1:-}" | tr ':' '\n' | grep -v easybuild | grep -v '^$' | tr '\n' ':' | sed 's/:$//'; }
export LD_LIBRARY_PATH="$(_scrub "${LD_LIBRARY_PATH:-}")"
export PATH="$(_scrub "${PATH:-}")"
export AGENT_TOOLSDIRECTORY="__TOOLCACHE__"
export RUNNER_TOOL_CACHE="__TOOLCACHE__"
mkdir -p "__WORK_ROOT__"
"""


def runner_keepalive_fragment(
    runner: RunnerSpec,
    *,
    toolcache: str,
    work_root: str,
    backoff: int,
) -> str:
    """Return the shell for ONE runner's keep-alive loop (backgrounded).

    The loop:
      * cd's into the install dir with a per-runner ``_work`` dir off the
        home quota and the runner's ``shims`` on PATH,
      * runs ``./run.sh`` in the foreground (it blocks while connected),
      * on exit, appends a timestamped restart line to ``keepalive.log``
        and sleeps ``backoff`` before relaunching,
      * exits cleanly only when the supervisor is being torn down (a
        sentinel file the supervisor removes on shutdown), so SLURM
        teardown doesn't trigger a pointless final relaunch.
    """
    tag = runner.name
    work = f"{work_root}/{tag}"
    # ``$$`` here is the supervisor PID, shared across loops — fine, each
    # loop gets its own ``_work`` subdir by tag so they never collide.
    return (
        f"_keepalive_{_safe(tag)}() {{\n"
        f'  local d="{runner.dir}"\n'
        f'  local wd="{work}"\n'
        f'  mkdir -p "$wd"\n'
        f'  echo "PID $$ supervising {tag} on $(hostname) at $(date -u +%FT%TZ)" '
        f'> "{runner.pidfile}"\n'
        f'  while [ -f "{_sentinel()}" ]; do\n'
        f'    rm -f "$d/.needs-restart"\n'
        f'    echo "[$(date -u +%FT%TZ)] starting {tag}" >> "{runner.log}"\n'
        f'    ( cd "$d" \\\n'
        f'        && RUNNER_WORK_DIRECTORY="$wd" \\\n'
        f'           PATH="$d/shims:$HOME/.cargo/bin:$HOME/.local/bin:$PATH" \\\n'
        f'           ./run.sh ) >> "{runner.log}" 2>&1\n'
        f'    rc=$?\n'
        f'    echo "[$(date -u +%FT%TZ)] {tag} run.sh exited rc=$rc; '
        f'restart in {backoff}s" >> "{runner.log}"\n'
        f'    [ -f "{_sentinel()}" ] || break\n'
        f"    sleep {backoff}\n"
        f"  done\n"
        f'  echo "[$(date -u +%FT%TZ)] {tag} keep-alive loop exiting" '
        f'>> "{runner.log}"\n'
        f"}}\n"
        f"_keepalive_{_safe(tag)} &\n"
    )


def build_supervisor_hold_body(fleet: FleetSpec) -> str:
    """Assemble the full sbatch hold body that supervises ``fleet``.

    Layout of the generated body:

      1. env hardening (shared)
      2. a sentinel file marking "supervisor live" (loops watch it)
      3. one backgrounded keep-alive loop per active runner
      4. a SIGTERM/SIGINT trap that removes the sentinel so loops exit
         cleanly on scancel
      5. ``wait`` — block as the job's main process until SLURM tears
         the job down (or the resubmit trap fires, added by Reservation)

    The returned string is the ``hold_body`` argument for
    ``Reservation.book(..., persistent=True, hold_body=<this>)``.
    """
    active = fleet.active()
    env = (
        _ENV_HARDENING.replace("__TOOLCACHE__", fleet.toolcache).replace(
            "__WORK_ROOT__", fleet.work_root
        )
    )
    head = (
        f"# === scitex-ci supervisor: {len(active)} runners ===\n"
        f"{env}\n"
        f'mkdir -p "$(dirname {_sentinel()})"\n'
        f'echo "$(date -u +%FT%TZ) $(hostname)" > {_sentinel()}\n'
        f"_scitex_ci_shutdown() {{ rm -f {_sentinel()}; }}\n"
        f"trap _scitex_ci_shutdown TERM INT\n"
        f'echo "[scitex-ci] supervisor up on $(hostname); launching '
        f'{len(active)} runners" >&2\n'
    )
    loops = "".join(
        runner_keepalive_fragment(
            r,
            toolcache=fleet.toolcache,
            work_root=fleet.work_root,
            backoff=fleet.restart_backoff,
        )
        for r in active
    )
    tail = (
        '\necho "[scitex-ci] all keep-alive loops launched; supervising" >&2\n'
        "# Block as the job's main process. Reservation(persistent=True)\n"
        "# wraps this body with a SIGUSR1 walltime-resubmit trap; on\n"
        "# resubmit a fresh supervisor takes over the new allocation.\n"
        "wait\n"
    )
    return head + loops + tail


def _sentinel() -> str:
    """Path to the supervisor-live sentinel (per-node, in /tmp)."""
    return "/tmp/scitex-ci-supervisor.alive"


def _safe(name: str) -> str:
    """Make a runner name safe as a shell function-name suffix."""
    return "".join(c if c.isalnum() else "_" for c in name)
