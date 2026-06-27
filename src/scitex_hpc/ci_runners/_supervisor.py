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
# Strip inherited personal secrets. Sourcing the interactive profile above
# pulls the operator's credentials (API keys, OAuth tokens, email/SSO/Visa
# passwords) into the runner env, where EVERY CI job -- including any PR
# workflow -- could read and exfiltrate them off these shared runners. CI
# jobs get tools + PATH only; real per-job secrets must come from GitHub
# Actions secrets, never the runner profile. compgen -v is expanded once,
# so unsetting during the loop is safe.
for _name in $(compgen -v 2>/dev/null); do
  case "$_name" in
    *PASSWORD*|*PASSWD*|*TOKEN*|*SECRET*|*API_KEY*|*APIKEY*|*_KEY|*_KEYS|*BEARER*|*CREDENTIAL*|*CONSUMER_KEY*|*ACCESS_KEY*|*PRIVATE_KEY*)
      unset "$_name" 2>/dev/null || true ;;
  esac
done
unset _name
unset PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
_scrub() { echo "${1:-}" | tr ':' '\n' | grep -v easybuild | grep -v '^$' | tr '\n' ':' | sed 's/:$//'; }
export LD_LIBRARY_PATH="$(_scrub "${LD_LIBRARY_PATH:-}")"
export PATH="$(_scrub "${PATH:-}")"
export AGENT_TOOLSDIRECTORY="__TOOLCACHE__"
export RUNNER_TOOL_CACHE="__TOOLCACHE__"
mkdir -p "__WORK_ROOT__"
# Per-job _temp clear. A long-lived runner runs matrix jobs back-to-back
# without restarting; the runner's own .NET cleanup intermittently fails
# in this env, leaving _work/_temp so the next job crashes at startup
# (IOException: _temp already exists). This JOB_COMPLETED hook rm -rf's
# the temp AFTER each job (safe — the finished job's temp is gone), so
# the next job inits clean. printf (not a heredoc) to avoid nesting
# inside the body's own heredoc.
printf '%s\n' '#!/usr/bin/env bash' '[ -n "${RUNNER_TEMP:-}" ] && rm -rf "$RUNNER_TEMP" 2>/dev/null' '[ -n "${RUNNER_WORK_DIRECTORY:-}" ] && rm -rf "$RUNNER_WORK_DIRECTORY/_temp" 2>/dev/null' 'exit 0' > "__HOOK_PATH__"
chmod +x "__HOOK_PATH__"
export ACTIONS_RUNNER_HOOK_JOB_COMPLETED="__HOOK_PATH__"
"""


# Idempotent, non-fatal Python tool-cache provisioning. ``setup-python@v5``
# resolves interpreters from ``RUNNER_TOOL_CACHE``; a fresh or reinstalled
# node starts EMPTY, so a job that ``setup-python``s 3.x would fail. We lay
# down portable CPython (python-build-standalone via ``uv``) in the exact
# layout setup-python expects ($CACHE/Python/<ver>/x64 + ``x64.complete``),
# so the node SELF-HEALS instead of needing a manual cache build. Spartan is
# RHEL, which actions/python-versions has no build for (hence pbs, which is
# distro-portable). The interpreters' ``EXTERNALLY-MANAGED`` marker is KEPT:
# the cache is shared + read-only across all runners, so per-job ``venv``s do
# the installing (a stray base ``pip install`` would race the shared cache).
# Every step is guarded — a provisioning hiccup must never block runner
# launch. Runs ONCE at supervisor start, before any runner is spawned, so no
# job can be reading an interpreter while it is laid down.
_TOOLCACHE_PROVISION = r"""# --- scitex-ci Python tool-cache provisioning (idempotent) ---
_provision_toolcache() {
  local cache="__TOOLCACHE__" uvdir="__WORK_ROOT__/tooling" src="__WORK_ROOT__/hostedtoolcache-src"
  local uv="$uvdir/uv" need="" v
  for v in 3.11 3.12 3.13; do
    ls "$cache"/Python/"$v".*/x64.complete >/dev/null 2>&1 || need="$need $v"
  done
  [ -z "$need" ] && return 0
  echo "[scitex-ci] provisioning Python tool-cache:$need" >&2
  mkdir -p "$uvdir" "$src" "$cache/Python" 2>/dev/null || true
  if [ ! -x "$uv" ]; then
    curl -LsSf -m 120 https://astral.sh/uv/install.sh \
      | env UV_INSTALL_DIR="$uvdir" INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || return 0
  fi
  [ -x "$uv" ] || return 0
  UV_PYTHON_INSTALL_DIR="$src" "$uv" python install $need >/dev/null 2>&1 || return 0
  local d full dst
  for d in "$src"/cpython-3.*-linux-*-gnu; do
    [ -x "$d/bin/python3" ] || continue
    full="$("$d/bin/python3" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)" || continue
    [ -n "$full" ] || continue
    dst="$cache/Python/$full/x64"
    mkdir -p "$cache/Python/$full" 2>/dev/null || true
    rm -rf "$dst" 2>/dev/null || true
    ln -sfn "$d" "$dst"
    [ -e "$dst/bin/python" ] || ln -sfn python3 "$dst/bin/python" 2>/dev/null || true
    : > "$cache/Python/$full/x64.complete" 2>/dev/null || true
  done
}
_provision_toolcache || true
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
        # The runner IGNORES RUNNER_WORK_DIRECTORY and uses
        # <install-dir>/_work, which is on GPFS (a network FS) where the
        # _temp delete/recreate races -> startup IOException "_temp already
        # exists". Symlink _work to local xfs so the runner-side per-job
        # temp-init is atomic, eliminating the GPFS race (also fixes the
        # cancelled-job leftover case, independent of hook timing).
        # ln -sfn will NOT replace a real directory (it nests inside it),
        # and rm -rf races with a dying old runner still holding _work. mv
        # (atomic rename on the same FS) always succeeds even on a busy dir,
        # so move the real _work aside, then symlink; background-clean the
        # moved copy.
        f'  if [ ! -L "$d/_work" ]; then '
        f'mv "$d/_work" "$d/_work.gpfs-stale-$$" 2>/dev/null; '
        f'rm -rf "$d/_work.gpfs-stale-$$" 2>/dev/null & fi\n'
        f'  ln -sfn "$wd" "$d/_work"\n'
        f'  echo "PID $$ supervising {tag} on $(hostname) at $(date -u +%FT%TZ)" '
        f'> "{runner.pidfile}"\n'
        f'  while [ -f "{_sentinel()}" ]; do\n'
        f'    rm -f "$d/.needs-restart"\n'
        f'    echo "[$(date -u +%FT%TZ)] starting {tag}" >> "{runner.log}"\n'
        # Clear a stale _work/_temp left by a prior session: the GitHub
        # runner's TempDirectoryManager.InitializeTempDirectory fails at
        # startup ("_temp already exists") if it survives a restart.
        f'    rm -rf "$wd/_temp"\n'
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
        _ENV_HARDENING.replace("__TOOLCACHE__", fleet.toolcache)
        .replace("__WORK_ROOT__", fleet.work_root)
        .replace("__HOOK_PATH__", f"{fleet.work_root}/clear_temp_hook.sh")
    )
    provision = _TOOLCACHE_PROVISION.replace(
        "__TOOLCACHE__", fleet.toolcache
    ).replace("__WORK_ROOT__", fleet.work_root)
    head = (
        f"# === scitex-ci supervisor: {len(active)} runners ===\n"
        f"{env}\n"
        f"{provision}\n"
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
