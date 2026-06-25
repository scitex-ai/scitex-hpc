"""Tests for the supervisor hold-body generator."""

from __future__ import annotations

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


def test_body_respects_exclude():
    # Arrange
    fleet = _fleet("a", "b")
    fleet.exclude = ("b",)
    # Act
    body = build_supervisor_hold_body(fleet)
    # Assert
    assert "actions-runner-b" not in body
