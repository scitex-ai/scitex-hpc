"""Tests for ci_runners fleet descriptors + discovery parsing."""

from __future__ import annotations

from scitex_hpc.ci_runners import (
    DEFAULT_DIAG_KEEP,
    DEFAULT_RESTART_BACKOFF_SECONDS,
    RUNNER_DIR_PREFIX,
    FleetSpec,
    RunnerSpec,
    parse_runner_dirs,
)

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"

# A realistic listing from a base that was never wrapped in the
# ``actions-runner-`` convention — measured 2026-08-23 on Spartan scratch,
# e.g. ``runner-spartan-cpu-03`` (an upstream tarball install, un-renamed).
_BARE_RUNNER_LISTING = """\
runner-spartan-cpu-01
runner-spartan-cpu-02
runner-spartan-cpu-03
runner-spartan-cpu-03.wrap.log
some-other-dir
"""

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


def test_fleet_default_diag_keep():
    # Arrange
    fleet = FleetSpec(ci_base=CI_BASE)
    # Act
    keep = fleet.diag_keep
    # Assert
    assert keep == DEFAULT_DIAG_KEEP


def test_parse_matches_bare_runner_dash_install_dirs_by_default():
    # Arrange — a realistically-named runner dir with NO "actions-" wrapper
    # (measured on Spartan 2026-08-23: runner-spartan-cpu-03). The narrow
    # RUNNER_DIR_PREFIX = "actions-runner-" default matched none of these.
    listing = _BARE_RUNNER_LISTING
    # Act
    names = [r.name for r in parse_runner_dirs(listing, ci_base=CI_BASE)]
    # Assert — sidecar .wrap.log and unrelated dirs still excluded
    assert names == ["spartan-cpu-01", "spartan-cpu-02", "spartan-cpu-03"]


def test_parse_still_matches_legacy_actions_runner_prefix_by_default():
    # Arrange — widening must not regress the existing ~79-runner legacy
    # convention documented in the package README.
    listing = _LISTING
    # Act
    names = [r.name for r in parse_runner_dirs(listing, ci_base=CI_BASE)]
    # Assert — unchanged from before the widen
    assert names == ["figrecipe", "figrecipe-02", "scitex-core", "scitex-hpc"]


def test_parse_matches_both_conventions_in_one_listing():
    # Arrange — a mixed base carrying both the legacy and bare conventions
    # side by side (the actual shape of a fleet mid-migration).
    listing = _LISTING + _BARE_RUNNER_LISTING
    # Act
    names = {r.name for r in parse_runner_dirs(listing, ci_base=CI_BASE)}
    # Assert
    assert names == {
        "figrecipe",
        "figrecipe-02",
        "scitex-core",
        "scitex-hpc",
        "spartan-cpu-01",
        "spartan-cpu-02",
        "spartan-cpu-03",
    }


def test_parse_prefix_kwarg_still_accepts_a_single_string():
    # Arrange — back-compat: a caller pinning one exact convention (the
    # pre-widen call shape) must still work with a bare string, not just
    # the new default tuple.
    listing = "actions-runner-only\nrunner-should-be-excluded\n"
    # Act
    names = [
        r.name
        for r in parse_runner_dirs(listing, ci_base=CI_BASE, prefix=RUNNER_DIR_PREFIX)
    ]
    # Assert — narrowed back to just the legacy convention
    assert names == ["only"]
