"""Tests for ci_runners fleet descriptors + discovery parsing."""

from __future__ import annotations

from scitex_hpc.ci_runners import (
    DEFAULT_RESTART_BACKOFF_SECONDS,
    FleetSpec,
    RunnerSpec,
    parse_runner_dirs,
)

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"

# A realistic ls listing: real install dirs + sidecar artifacts the old
# band-aids dropped (.wrap.log), which must be filtered out.
_LISTING = """\
actions-runner-scitex-hpc
actions-runner-scitex-core
actions-runner-scitex-core.wrap.log
actions-runner-figrecipe
actions-runner-figrecipe-02
actions-runner-02.wrap.log
crossref-local-notes.txt
.hidden
"""


def test_parse_keeps_only_real_runner_dirs():
    # Arrange
    listing = _LISTING
    # Act
    names = [r.name for r in parse_runner_dirs(listing, ci_base=CI_BASE)]
    # Assert — sidecar logs and non-runner entries excluded
    assert names == ["figrecipe", "figrecipe-02", "scitex-core", "scitex-hpc"]


def test_parse_builds_absolute_dirs():
    # Arrange
    listing = _LISTING
    # Act
    runners = parse_runner_dirs(listing, ci_base=CI_BASE)
    # Assert
    assert next(r for r in runners if r.name == "scitex-hpc").dir == (
        f"{CI_BASE}/actions-runner-scitex-hpc"
    )


def test_parse_dedupes_and_sorts():
    # Arrange
    listing = "actions-runner-b\nactions-runner-a\nactions-runner-a\n"
    # Act
    names = [r.name for r in parse_runner_dirs(listing, ci_base=CI_BASE)]
    # Assert
    assert names == ["a", "b"]


def test_runner_spec_log_path_is_per_dir():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    log = r.log
    # Assert
    assert log == f"{r.dir}/keepalive.log"


def test_runner_spec_pidfile_path_is_per_dir():
    # Arrange
    r = RunnerSpec(name="scitex-hpc", dir=f"{CI_BASE}/actions-runner-scitex-hpc")
    # Act
    pidfile = r.pidfile
    # Assert
    assert pidfile == f"{r.dir}/keepalive.pid"


def test_fleet_active_applies_exclude():
    # Arrange
    runners = parse_runner_dirs(_LISTING, ci_base=CI_BASE)
    fleet = FleetSpec(ci_base=CI_BASE, runners=runners, exclude=("figrecipe-02",))
    # Act
    active_names = [r.name for r in fleet.active()]
    # Assert
    assert "figrecipe-02" not in active_names


def test_fleet_default_backoff():
    # Arrange
    fleet = FleetSpec(ci_base=CI_BASE)
    # Act
    backoff = fleet.restart_backoff
    # Assert
    assert backoff == DEFAULT_RESTART_BACKOFF_SECONDS
