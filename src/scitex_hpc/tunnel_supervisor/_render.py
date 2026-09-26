"""Render the tunnel-supervisor shell script from a :class:`TunnelProfile`.

Like ``ci_runners`` (generates its supervisor hold-body from Python) and
``login_guard`` (generates its guard shell from a ``GuardProfile``), this
module GENERATES the supervisor script from the profile rather than
shipping a static ``.sh``. The generated script implements, in order:

  1. ``flock`` single-instance semantics — a second invocation for the
     same lockfile exits immediately instead of double-launching.
  2. The sentinel + keep-alive loop:
     ``while [ -f SENTINEL ]; do <command>; sleep BACKOFF; done`` —
     deleting the sentinel file is the clean-shutdown signal.
  3. A timestamped heartbeat log line on every loop iteration (start
     attempt, exit/restart events).
  4. An optional background health-check watcher that polls the
     configured endpoint (NOT just the wrapped process's PID) and kills
     the command (triggering a restart) after ``unhealthy_threshold``
     consecutive failures.

Pure string generation — no SSH, no process launch — fully unit-testable
by asserting on the rendered text (same convention as
``ci_runners/_supervisor.py`` and ``login_guard/_render.py``).
"""

from __future__ import annotations

from ._profile import EXAMPLE_PROFILE, TunnelProfile


def _safe_ident(name: str) -> str:
    """Sanitise a profile name into a shell-identifier-safe stem."""
    import re

    ident = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not ident or ident[0].isdigit():
        ident = f"_{ident}"
    return ident


def render_supervisor(profile: TunnelProfile = EXAMPLE_PROFILE) -> str:
    """Return the supervisor shell text generated from ``profile``.

    Templates every profile value (sentinel/lock/log paths, the wrapped
    command, health-check URL + interval + timeout + threshold, poll
    interval, restart backoff) into a single, self-contained script safe
    to install as a cron entry, a systemd-user unit ``ExecStart``, or an
    sbatch-launchable artifact.
    """
    ident = _safe_ident(profile.name)
    loop_fn = f"_{ident}_keepalive"
    health_fn = f"_{ident}_healthwatch"

    sentinel = profile.sentinel_path
    lockfile = profile.lockfile_path
    log = profile.log_path
    command = profile.command
    backoff = profile.restart_backoff
    poll = profile.poll_interval

    health_block = ""
    if profile.health_check_url:
        health_block = f"""
# --- endpoint health-check watcher (backgrounded per keep-alive attempt) ---
# Health-checks the ENDPOINT through the tunnel, not the process's PID — a
# hung tunnel with a live PID but a dead endpoint still counts unhealthy
# and triggers a restart (kill the foreground command; the outer loop
# relaunches it after {backoff}s).
{health_fn}() {{
  local pid_to_kill="$1"
  local fails=0
  while kill -0 "$pid_to_kill" 2>/dev/null; do
    sleep {profile.health_check_interval}
    if curl -fsS --max-time {profile.health_check_timeout} \\
        "{profile.health_check_url}" >/dev/null 2>&1; then
      fails=0
    else
      fails=$((fails + 1))
      echo "[$(date -u +%FT%TZ)] {profile.name} health-check failed ($fails/{profile.unhealthy_threshold})" >> "{log}"
      if [ "$fails" -ge {profile.unhealthy_threshold} ]; then
        echo "[$(date -u +%FT%TZ)] {profile.name} endpoint unhealthy; killing pid $pid_to_kill for restart" >> "{log}"
        kill "$pid_to_kill" 2>/dev/null
        return 0
      fi
    fi
  done
}}
"""

    health_watch_call = (
        f'{health_fn} "$cmd_pid" &'
        if profile.health_check_url
        else ": # no health-check configured"
    )

    return f"""#!/usr/bin/env bash
# ============================================================================
# Tunnel/service keep-alive supervisor  (scitex-hpc, profile: {profile.name})
# [GENERATED — edit the profile + renderer, not this artifact]
# ----------------------------------------------------------------------------
# Restarts `{command}` every time it exits, for as long as the sentinel
# file `{sentinel}` exists. Deleting the sentinel is the clean-shutdown
# signal — the loop checks it each iteration and exits once it's gone.
# `flock` on `{lockfile}` enforces single-instance semantics: a second
# invocation for this lockfile exits immediately without double-launching.
# ============================================================================
set -u

SENTINEL="{sentinel}"
LOCKFILE="{lockfile}"
LOG="{log}"

mkdir -p "$(dirname "$LOCKFILE")" "$(dirname "$LOG")" "$(dirname "$SENTINEL")" 2>/dev/null || true

# --- flock single-instance guard ---
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "[$(date -u +%FT%TZ)] {profile.name} supervisor already running (lock held on $LOCKFILE); exiting" >&2
  exit 1
fi

# Sentinel marks "supervisor should keep running"; create it if absent so
# a fresh invocation starts supervising immediately.
[ -f "$SENTINEL" ] || : > "$SENTINEL"

{health_block}
{loop_fn}() {{
  while [ -f "$SENTINEL" ]; do
    echo "[$(date -u +%FT%TZ)] {profile.name} starting: {command}" >> "$LOG"
    ( {command} ) &
    local cmd_pid=$!
    {health_watch_call}
    wait "$cmd_pid"
    local rc=$?
    echo "[$(date -u +%FT%TZ)] {profile.name} exited rc=$rc; restart in {backoff}s" >> "$LOG"
    [ -f "$SENTINEL" ] || break
    sleep {backoff}
  done
  echo "[$(date -u +%FT%TZ)] {profile.name} keep-alive loop exiting (sentinel removed)" >> "$LOG"
}}

{loop_fn}
"""


def render_install_script(profile: TunnelProfile = EXAMPLE_PROFILE) -> str:
    """Return a small wrapper script that writes the supervisor + chmod +x's it.

    Pure string generation (no filesystem access, no SSH) so it stays
    unit-testable like :func:`render_supervisor`; :mod:`._install` is what
    actually writes bytes to disk.
    """
    body = render_supervisor(profile)
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'TARGET="${{1:?usage: install.sh <target-path>}}"\n'
        'mkdir -p "$(dirname "$TARGET")"\n'
        f'cat > "$TARGET" <<\'__SCITEX_TUNNEL_SUPERVISOR_EOF__\'\n'
        f"{body}__SCITEX_TUNNEL_SUPERVISOR_EOF__\n"
        'chmod +x "$TARGET"\n'
        'echo "installed tunnel-supervisor -> $TARGET"\n'
    )
