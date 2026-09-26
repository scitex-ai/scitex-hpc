"""Tests for the supervisor hold-body generator."""

from __future__ import annotations

import os
import subprocess
import sys

from scitex_hpc.ci_runners import (
    DEFAULT_DIAG_KEEP,
    FleetSpec,
    RunnerSpec,
    build_supervisor_hold_body,
    diag_pruner_fragment,
    runner_keepalive_fragment,
)
from scitex_hpc.ci_runners._supervisor import _TOOLCACHE_PROVISION

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"


def _fleet(*names: str) -> FleetSpec:
    runners = [
        RunnerSpec(name=n, dir=f"{CI_BASE}/actions-runner-{n}") for n in names
    ]
    return FleetSpec(ci_base=CI_BASE, runners=runners)


def test_fragment_runs_run_sh():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert
    assert "./run.sh" in frag


def test_fragment_clears_stale_temp_before_restart():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — a stale _work/_temp would crash the runner at startup
    assert 'rm -rf "$wd/_temp"' in frag


def test_fragment_symlinks_work_to_local_disk():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — _work must point at local xfs (GPFS races break temp-init)
    assert 'ln -sfn "$wd" "$d/_work"' in frag


def test_fragment_moves_real_work_aside_before_symlink():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — mv (atomic, busy-safe) so ln -sfn replaces a real _work dir
    assert 'mv "$d/_work"' in frag


def test_fragment_path_includes_user_bin():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — ~/.bin holds gh; non-interactive shells skip .bashrc's PATH add
    assert "$HOME/.bin:" in frag


def test_fragment_sets_per_runner_git_config_global():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — the whole fleet shares one $HOME and ~/.gitconfig is a symlink
    # into the dotfiles SSoT, so checkout's `git config --global --add
    # safe.directory` accumulated 35,327 entries (206 unique) in a 4.3 MB file
    # by 2026-07-29. Each --add is a read-modify-write of the WHOLE file under
    # .gitconfig.lock, so collisions COMPOUND as it grows.
    assert 'GIT_CONFIG_GLOBAL="$wd/.gitconfig"' in frag


def test_fragment_seeds_git_config_with_include_of_real_config():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — GIT_CONFIG_GLOBAL REPLACES the global config, so without an
    # include the runner loses user.name/user.email and commits break.
    assert '"[include]\\npath = %s\\n" "$HOME/.gitconfig"' in frag


def test_fragment_writes_seeded_config_to_the_per_runner_path():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — the seed must land on the runner's own node-local file, which is
    # what gives each runner its own .gitconfig.lock instead of one shared lock.
    assert '> "$wd/.gitconfig"' in frag


def test_fragment_seeds_git_config_before_launching_run_sh():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — seeding must happen INSIDE the restart loop and before run.sh,
    # otherwise a restarted runner inherits the previous session's accumulated
    # safe.directory entries and the growth resumes per-runner.
    assert frag.index('> "$wd/.gitconfig"') < frag.index("./run.sh")


def test_fragment_sets_per_runner_tool_cache():
    """`$cache/uv/` was written by JOBS, racing on one shared path.

    The supervisor provisions only Python, once, before any runner exists --
    so the module's "shared + read-only across all runners" invariant has
    never covered uv. setup-uv writes it at job runtime, and uv shipped 12
    releases in ~5 weeks, so each new version misses the cache and the first
    jobs to want it install concurrently into the same file (exit 127 on
    07-23 and again on 07-29).
    """
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert
    assert 'RUNNER_TOOL_CACHE="$wd/toolcache"' in frag


def test_fragment_keeps_the_python_toolcache_shared_by_symlink():
    # Arrange — 3 interpreters x 80 runners is pure duplication against an
    # inode quota already at ~93%, and nothing writes Python at job time.
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert
    assert 'ln -sfn "$HOME/tc/Python" "$wd/toolcache/Python"' in frag


def test_fragment_tool_cache_is_set_for_the_run_sh_invocation():
    # Arrange — setting it anywhere but the run.sh env would leave the
    # runner's own child processes reading the shared cache.
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert
    assert frag.index('RUNNER_TOOL_CACHE="$wd/toolcache"') < frag.index("./run.sh")


def test_fragment_sets_per_runner_gh_config_dir():
    """Third face of the shared-$HOME class, and the last one still live.

    `gh` parses ~/.config/gh/config.yml at STARTUP, before it consults any
    token, so the operator's corrupt copy aborts it before authentication —
    no secret can rescue that. It has blocked scitex-logging PR #24 since
    2026-07-12 while the same class was patched repo-by-repo (scitex-ui#68,
    scitex-math#5) rather than at the launcher.
    """
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert
    assert 'GH_CONFIG_DIR="$wd/gh"' in frag


def test_fragment_does_not_seed_gh_config_from_the_shared_one():
    """FORWARD guard only — it does NOT verify the GH_CONFIG_DIR change.

    Checked against the unfixed generator and it PASSES there too, because
    that generator never mentioned the shared gh config either. So this
    asserts nothing about the current diff; keeping it anyway, correctly
    labelled, because it pins a DECISION that a later change could quietly
    undo.

    The decision: unlike GIT_CONFIG_GLOBAL (seeded via ``include.path`` so
    user.name/user.email still resolve), the gh config dir is deliberately
    left EMPTY. Seeding it would copy in the corrupt config that IS the
    defect -- gh parses config.yml at startup, before any token, and aborts.
    CI auth comes from GH_TOKEN in Actions secrets, which needs no file. A
    future "make it consistent with the git one" edit would look like a
    tidy-up and would restore the bug; this fails if that happens.
    """
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert
    assert "$HOME/.config/gh" not in frag


def test_fragment_loops_for_restart():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=15)
    # Assert — a while loop is what gives auto-restart
    assert "while [ -f" in frag


def test_fragment_uses_backoff_value():
    # Arrange
    r = RunnerSpec(name="x", dir=f"{CI_BASE}/actions-runner-x")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=42)
    # Assert
    assert "sleep 42" in frag


def test_fragment_backgrounds_the_loop():
    # Arrange
    r = RunnerSpec(name="x", dir=f"{CI_BASE}/actions-runner-x")
    # Act
    frag = runner_keepalive_fragment(r, toolcache="$HOME/tc", work_root="/tmp/w", backoff=1)
    # Assert — trailing ` &` backgrounds the keep-alive function
    assert frag.rstrip().endswith("&")


def test_body_includes_every_runner():
    # Arrange
    fleet = _fleet("a", "b", "c")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert
    assert body.count("./run.sh") == 3


def test_body_blocks_as_the_jobs_main_process():
    """Was ``test_body_ends_with_wait``, which asserted the DEFECT.

    The intent was right -- the supervisor must block as the job's main process
    -- but pinning it to a body ENDING in ``wait`` encoded the bug as the
    contract: a bare ``wait`` returns when the SIGUSR1 resubmit trap fires, so
    the job exits ~1h early and the successor queues with no runner online
    (16h03m dark on hop 27331011; 27709706 never backfilled). Anyone fixing the
    defect saw a red suite and could reasonably conclude they had broken
    something. Re-pointed at the property actually wanted -- blocking that
    SURVIVES the trap -- rather than the shape that used to implement it.
    """
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert
    assert "wait || true" in body


def test_body_never_ends_on_a_bare_wait():
    """Regression guard for the ~1h early surrender. See the test above."""
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert
    assert [ln for ln in body.splitlines() if ln.strip() == "wait"] == []


def test_body_ends_on_the_closed_wait_loop_not_a_fallthrough():
    """Asserted on the LAST line, not on the presence of the sentinel loop.

    Every per-runner keep-alive fragment already contains
    ``while [ -f <sentinel> ]``, so a substring check for it PASSES against the
    unfixed body and guards nothing -- verified by running it against the old
    code. This keys on the one thing the defect changes: where control flow
    ends.
    """
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert
    assert body.rstrip().splitlines()[-1] == "done"


def test_body_scrubs_easybuild_env():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — env hardening removes the easybuild module paths
    assert "grep -v easybuild" in body


def test_body_sets_job_completed_hook():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — per-job hook so back-to-back jobs don't collide on stale _temp
    assert "ACTIONS_RUNNER_HOOK_JOB_COMPLETED" in body


def test_body_hook_clears_runner_temp():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — the hook rm -rf's the finished job's temp
    assert 'rm -rf "$RUNNER_TEMP"' in body


def test_body_respects_exclude():
    # Arrange
    fleet = _fleet("a", "b")
    fleet.exclude = ("b",)
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert
    assert "actions-runner-b" not in body


def test_body_provisions_toolcache():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — a fresh node self-heals the setup-python interpreter cache
    assert "_provision_toolcache" in body


def test_body_provision_writes_complete_marker():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — interpreters laid out in setup-python's $CACHE/<ver>/x64 layout
    assert "x64.complete" in body


def test_body_provision_is_non_fatal():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — a provisioning hiccup must never block runner launch
    assert "_provision_toolcache || true" in body


def test_body_provision_substitutes_toolcache_placeholder():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — no unsubstituted template tokens leak into the shell body
    assert "__TOOLCACHE__" not in body


def test_body_provision_checks_interpreter_resolves_not_just_marker():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — detection runs the interpreter (dangling-symlink safe), not
    # merely an ``ls`` of the x64.complete marker
    assert "x64/bin/python3" in body


# ---------------------------------------------------------------------------
# _provision_toolcache detection — behavioral (real bash over a synthetic cache)
# ---------------------------------------------------------------------------


def _seed_healthy(cache: str, full: str) -> None:
    """Lay a resolvable interpreter + marker at $cache/Python/<full>/x64."""
    binroot = os.path.join(cache, "Python", full, "x64", "bin")
    os.makedirs(binroot)
    os.symlink(sys.executable, os.path.join(binroot, "python3"))
    open(os.path.join(cache, "Python", full, "x64.complete"), "w").close()


def _run_provision(cache: str, work: str) -> str:
    """Run the real provisioning fragment; return its stderr.

    A no-op fake ``uv`` is seeded so the re-provision path never touches the
    network — the assertions only look at which versions the detection flags
    for provisioning (echoed to stderr before any uv/install work).
    """
    os.makedirs(os.path.join(work, "tooling"))
    uv = os.path.join(work, "tooling", "uv")
    with open(uv, "w") as fh:
        fh.write("#!/bin/bash\nexit 0\n")
    os.chmod(uv, 0o755)
    frag = _TOOLCACHE_PROVISION.replace("__TOOLCACHE__", cache).replace(
        "__WORK_ROOT__", work
    )
    proc = subprocess.run(["bash", "-c", frag], capture_output=True, text=True)
    return proc.stderr


def test_provision_is_noop_when_all_interpreters_resolve(tmp_path):
    # Arrange
    cache = str(tmp_path / "tc")
    for full in ("3.11.15", "3.12.13", "3.13.14"):
        _seed_healthy(cache, full)
    # Act
    stderr = _run_provision(cache, str(tmp_path / "work"))
    # Assert — a healthy cache does not re-provision
    assert "provisioning" not in stderr


def test_provision_reprovisions_on_dangling_symlink_despite_marker(tmp_path):
    # Arrange — 3.11 + 3.13 healthy; 3.12 has its marker but a DANGLING x64
    cache = str(tmp_path / "tc")
    for full in ("3.11.15", "3.13.14"):
        _seed_healthy(cache, full)
    os.makedirs(os.path.join(cache, "Python", "3.12.13"))
    os.symlink("/nonexistent-toolcache-src", os.path.join(cache, "Python", "3.12.13", "x64"))
    open(os.path.join(cache, "Python", "3.12.13", "x64.complete"), "w").close()
    # Act
    stderr = _run_provision(cache, str(tmp_path / "work"))
    # Assert — the dead 3.12 link is detected and re-provisioned
    assert "3.12" in stderr


def test_body_overrides_tmpdir_to_local_disk():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — CI tmp on node-local disk under work_root, not under $HOME
    assert f'export TMPDIR="{fleet.work_root}/tmp"' in body


def test_body_tmpdir_override_comes_after_bashrc_source():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — the override must win over the profile's TMPDIR=$HOME/.cache/tmp
    assert body.index('source "$HOME/.bashrc"') < body.index("export TMPDIR=")


def test_body_path_prepends_user_bin():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — release-tail gh (in ~/.bin) must resolve in the non-interactive
    # supervisor; ~/.bashrc only adds ~/.bin for interactive shells
    assert 'export PATH="$HOME/.bin:$HOME/.local/bin:$HOME/.cargo/bin:' in body


def test_body_scrubs_inherited_secret_env_vars():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — a loop over the env unsets secret-pattern vars the profile leaked
    assert "compgen -v" in body


def test_body_scrub_covers_password_pattern():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — passwords (email/SSO/Visa) must be stripped from the job env
    assert "*PASSWORD*" in body


def test_body_scrub_covers_token_pattern():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — OAuth/bearer tokens must be stripped from the job env
    assert "*TOKEN*" in body


def test_body_scopes_git_config_global_off_home(tmp_path):
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — actions/checkout's unchecked safe.directory adds must land
    # in a scratch file, never the operator's real ~/.gitconfig (dotfiles SSoT)
    assert f'export GIT_CONFIG_GLOBAL="{fleet.work_root}/git-config-global-ci.ini"' in body


def test_git_config_global_seeded_from_real_gitconfig_once(tmp_path):
    # Arrange — a real ~/.gitconfig with a marker line, no scratch copy yet
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[user]\n\tname = marker\n")
    work = tmp_path / "work"
    work.mkdir()
    fleet = _fleet("a")
    fleet.work_root = str(work)
    body = build_supervisor_hold_body(fleet)
    # Act — run just the seeding line for real, with HOME pointed at the fixture
    seed_line = next(
        ln for ln in body.splitlines() if ln.startswith("[ -f \"$GIT_CONFIG_GLOBAL\" ]")
    )
    subprocess.run(
        ["bash", "-c", f'export GIT_CONFIG_GLOBAL="{work}/git-config-global-ci.ini"\n{seed_line}'],
        env={**os.environ, "HOME": str(home)},
        check=True,
    )
    # Assert — the scratch copy carries the real identity forward
    assert "marker" in (work / "git-config-global-ci.ini").read_text()


# ---------------------------------------------------------------------------
# _diag log pruner — bounds each runner's _diag inode footprint
# ---------------------------------------------------------------------------


def test_pruner_bounds_worker_logs_to_diag_keep():
    # Arrange
    fleet = _fleet("scitex-hpc")
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert — keep newest DEFAULT_DIAG_KEEP, delete the rest (tail -n +N+1)
    assert f'ls -t "$d"/_diag/Worker_*.log 2>/dev/null | tail -n +{DEFAULT_DIAG_KEEP + 1}' in frag


def test_pruner_bounds_runner_logs_too():
    # Arrange
    fleet = _fleet("scitex-hpc")
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert
    assert '/_diag/Runner_*.log 2>/dev/null | tail -n +' in frag


def test_pruner_loops_on_the_supervisor_sentinel():
    # Arrange
    fleet = _fleet("a")
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert — the pruner exits when the supervisor removes the sentinel
    assert "while [ -f /tmp/scitex-ci-supervisor.alive ]; do" in frag


def test_pruner_honours_diag_keep_override():
    # Arrange
    fleet = _fleet("a")
    fleet.diag_keep = 5
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert
    assert "tail -n +6" in frag


def test_pruner_honours_prune_interval_override():
    # Arrange
    fleet = _fleet("a")
    fleet.diag_prune_interval = 111
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert
    assert "sleep 111" in frag


def test_pruner_iterates_only_active_runners():
    # Arrange — exclude one runner; it must not appear in the prune loop
    fleet = _fleet("a", "b")
    fleet.exclude = ("b",)
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert
    assert "actions-runner-b" not in frag


def test_pruner_deletes_only_via_rm_f_of_older_logs():
    # Arrange
    fleet = _fleet("a")
    # Act
    frag = diag_pruner_fragment(fleet)
    # Assert — pure log hygiene: only ever xargs rm -f the tail (older) logs
    assert "xargs -r rm -f" in frag


def test_body_launches_the_diag_pruner():
    # Arrange
    fleet = _fleet("a", "b")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — the supervisor body backgrounds the pruner loop
    assert "_scitex_ci_diag_pruner &" in body
