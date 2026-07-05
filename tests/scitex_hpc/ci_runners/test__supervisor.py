"""Tests for the supervisor hold-body generator."""

from __future__ import annotations

import subprocess

import pytest

from scitex_hpc.ci_runners import (
    FleetSpec,
    RunnerSpec,
    build_supervisor_hold_body,
    runner_keepalive_fragment,
)

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


def test_body_ends_with_wait():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — the supervisor blocks on wait as the job's main process
    assert body.rstrip().endswith("wait")


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


def test_body_scrub_covers_data_pattern():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — app-data junk (the MNE_DATA incident) is stripped pattern-wise
    assert "*_DATA" in body


def test_body_scrub_covers_data_dir_pattern():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — e.g. FOO_DATA_DIR-style vars from the same profile
    assert "*_DATA_DIR" in body


def test_body_scrub_covers_cache_dir_pattern():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — app-cache dir vars from the same profile
    assert "*_CACHE_DIR" in body


def test_body_scrub_covers_config_dir_pattern():
    # Arrange
    fleet = _fleet("a")
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert — app-config dir vars from the same profile
    assert "*_CONFIG_DIR" in body


def _extract_scrub_loop(body: str) -> str:
    """Pull the ``for _name in $(compgen -v ...) ... unset _name`` block
    out of the generated body so the test exercises the ACTUAL scrub logic
    shipped to the runner, not a hand-duplicated copy that could drift."""
    start = body.index("for _name in $(compgen -v")
    end = body.index("unset _name", start) + len("unset _name")
    return body[start:end]


_PROBE_VARS = {
    "PATH": "/usr/bin",
    "HOME": "/home/x",
    "TMPDIR": "/tmp/x",
    "CI": "true",
    "RUNNER_TOOL_CACHE": "/tc",
    "AGENT_TOOLSDIRECTORY": "/tc",
    "GITHUB_SHA": "abc123",
    "ACTIONS_RUNTIME_URL": "https://example.invalid",
    "MNE_DATA": "/nonexistent/mne",
    "FOO_DATA_DIR": "/nonexistent/foo",
}


@pytest.fixture(scope="module")
def scrubbed_probe_env() -> dict[str, str]:
    """Run the ACTUAL generated scrub loop against a synthetic env mixing
    vars a runner legitimately needs with app-data/app-config junk that
    leaks in from the sourced .bashrc, and return what survived."""
    fleet = _fleet("a")
    body = build_supervisor_hold_body(fleet)
    loop = _extract_scrub_loop(body)
    script = loop + "\n" + "\n".join(
        f'echo "{v}=${{{v}:-<unset>}}"' for v in _PROBE_VARS
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env=dict(_PROBE_VARS),
        capture_output=True,
        text=True,
        timeout=10,
    )
    survivors: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, value = line.partition("=")
        survivors[name] = value
    return survivors


def test_scrub_keeps_path(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — PATH must survive the scrub untouched
    assert scrubbed_probe_env["PATH"] == "/usr/bin"


def test_scrub_keeps_home(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — HOME must survive the scrub untouched
    assert scrubbed_probe_env["HOME"] == "/home/x"


def test_scrub_keeps_tmpdir(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — TMPDIR must survive the scrub untouched
    assert scrubbed_probe_env["TMPDIR"] == "/tmp/x"


def test_scrub_keeps_ci(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — CI must survive the scrub untouched
    assert scrubbed_probe_env["CI"] == "true"


def test_scrub_keeps_runner_tool_cache(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — RUNNER_TOOL_CACHE must survive the scrub untouched
    assert scrubbed_probe_env["RUNNER_TOOL_CACHE"] == "/tc"


def test_scrub_keeps_agent_toolsdirectory(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — AGENT_TOOLSDIRECTORY must survive the scrub untouched
    assert scrubbed_probe_env["AGENT_TOOLSDIRECTORY"] == "/tc"


def test_scrub_keeps_github_prefixed_vars(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — GITHUB_* vars must survive the scrub untouched
    assert scrubbed_probe_env["GITHUB_SHA"] == "abc123"


def test_scrub_keeps_actions_prefixed_vars(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — ACTIONS_* vars must survive the scrub untouched
    assert scrubbed_probe_env["ACTIONS_RUNTIME_URL"] == "https://example.invalid"


def test_scrub_removes_mne_data(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — MNE_DATA (the reported incident var) must be stripped
    assert scrubbed_probe_env["MNE_DATA"] == "<unset>"


def test_scrub_removes_invented_data_dir_var(scrubbed_probe_env):
    # Arrange — scrubbed_probe_env fixture ran the real scrub loop
    # Act — n/a, fixture already produced the survivor snapshot
    # Assert — a sibling *_DATA_DIR-style var must be stripped too
    assert scrubbed_probe_env["FOO_DATA_DIR"] == "<unset>"
