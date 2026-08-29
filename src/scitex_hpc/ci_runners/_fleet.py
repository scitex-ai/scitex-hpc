"""Fleet + runner descriptors and discovery helpers.

A :class:`RunnerSpec` describes one self-hosted runner install dir; a
:class:`FleetSpec` describes the whole set plus the shared environment
hardening every runner needs (the same env scrubbing the old band-aids
did, captured once instead of copy-pasted across five scripts).

Everything here is pure data + parsing — no SSH, no SLURM — so it is
trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Install dirs are named ``actions-runner-<name>`` under the CI base dir —
# the convention the original 72-runner band-aid used and the one most of
# the fleet's ~79 legacy per-repo installs still carry.
RUNNER_DIR_PREFIX = "actions-runner-"

# But it is not the only convention actually on disk. Measured 2026-08-23:
# a runner installed straight from the upstream tarball (no wrapper script
# renaming it) is named ``runner-<label>`` — e.g. ``runner-spartan-cpu-03``
# — and does not start with ``actions-runner-`` at all. Across four
# candidate CI bases every ``ls`` total was nonzero (146 / 13 / 3 / 388)
# while every ``RUNNER_DIR_PREFIX`` match was 0: the narrow default wasn't
# protecting against noise, it was blind to real install dirs.
#
# There is no deliberate convention behind the single narrow prefix — it
# is an assumption that hardened, not a decision (see PR that introduced
# this constant, and the fleet-ci-runners-missing-work-dir-20260720 /
# spartan-cpu-runners-offline-payload-pins-dead-jobid-20260823 incidents
# it left blind). Renaming the on-disk dirs to fit the constant was
# rejected: it strands paths the LAUNCHER side owns (the keep-alive
# payload, `.runner` workFolder entries) — a rename that fixes this
# constant by breaking those files is a transfer, not a fix. Widening the
# accepted set is the fix; :func:`parse_runner_dirs` already took a
# ``prefix`` keyword, so the seam existed — only the default was narrow.
RUNNER_DIR_PREFIXES: tuple[str, ...] = (RUNNER_DIR_PREFIX, "runner-")

# How long the keep-alive loop waits before relaunching a runner whose
# ``run.sh`` just exited. Long enough to avoid a hot crash-loop hammering
# GitHub, short enough that a transient blip self-heals within a minute.
DEFAULT_RESTART_BACKOFF_SECONDS = 15

# How many of each runner ``_diag`` log kind (Worker_*, Runner_*) to keep,
# and how often the supervisor prunes the rest. 20 keeps enough recent
# history to debug a failure while bounding the inode footprint; hourly is
# frequent enough that a busy runner's per-job logs never pile up for long.
DEFAULT_DIAG_KEEP = 20
DEFAULT_DIAG_PRUNE_INTERVAL_SECONDS = 3600

# A self-hosted runner install dir must contain ``run.sh`` to be a valid
# launch target. We also tolerate dirs that only have ``config.sh`` (not
# yet started) but skip them at launch — surfaced, not silently dropped.
_LAUNCH_MARKER = "run.sh"


@dataclass(frozen=True)
class RunnerSpec:
    """One self-hosted runner install directory.

    ``name`` is the human tag (e.g. ``scitex-hpc``); ``dir`` is the
    absolute install path; ``log`` is the per-runner supervisor log that
    the keep-alive loop writes (distinct from the runner's own
    ``runner.log`` so the supervisor's restart history is never clobbered
    by the runner rotating its log).
    """

    name: str
    dir: str

    @property
    def log(self) -> str:
        """Per-runner supervisor keep-alive log path."""
        return f"{self.dir}/keepalive.log"

    @property
    def pidfile(self) -> str:
        """Per-runner pidfile written by the keep-alive loop."""
        return f"{self.dir}/keepalive.pid"


@dataclass
class FleetSpec:
    """The whole runner fleet plus shared hardening.

    ``ci_base`` is the directory holding the ``actions-runner-*`` install
    dirs. ``runners`` is the resolved list (use :func:`parse_runner_dirs`
    to build it from a remote ``ls`` listing). ``exclude`` names are
    dropped (e.g. a runner the operator is migrating or retiring).

    ``toolcache`` / ``work_root`` mirror the env the band-aids set so the
    runners resolve the same Python/Node toolchain and keep ``_work`` off
    the home quota.
    """

    ci_base: str
    runners: list[RunnerSpec] = field(default_factory=list)
    exclude: tuple[str, ...] = ()
    toolcache: str = "$HOME/.runner-toolcache"
    work_root: str = "/tmp/scitex-ci-runner-work"
    restart_backoff: int = DEFAULT_RESTART_BACKOFF_SECONDS
    # Bound each runner's ``_diag`` log dir. The GitHub runner writes a
    # ``Worker_*.log`` per job plus rotating ``Runner_*.log`` into
    # ``<install>/_diag`` (on GPFS); across a long-lived session these grow
    # unbounded and consume shared-fileset inodes — a contributor to the
    # 2026-07-06 punim0264 inode wall that took CI down. The supervisor runs
    # a periodic pruner keeping only the newest ``diag_keep`` of each kind.
    diag_keep: int = DEFAULT_DIAG_KEEP
    diag_prune_interval: int = DEFAULT_DIAG_PRUNE_INTERVAL_SECONDS

    def active(self) -> list[RunnerSpec]:
        """Runners that should be launched (excludes filtered out)."""
        ex = set(self.exclude)
        return [r for r in self.runners if r.name not in ex]


def parse_runner_dirs(
    listing: str,
    *,
    ci_base: str,
    prefix: str | tuple[str, ...] = RUNNER_DIR_PREFIXES,
) -> list[RunnerSpec]:
    """Parse a plain ``ls`` listing of the CI base dir into RunnerSpecs.

    Accepts the output of ``ls <ci_base>`` (one entry per line). Keeps
    only entries that start with one of ``prefix`` and have no extra
    suffix that marks them as a non-runner artifact (``.log``,
    ``.wrap.log``, etc.). Deterministic: sorted by name, deduplicated.

    ``prefix`` may be a single string (back-compat with earlier callers
    that pinned one convention) or a tuple of acceptable prefixes — the
    default, :data:`RUNNER_DIR_PREFIXES`, already covers the two
    conventions actually seen on disk. Widen it further per-call (e.g. a
    caller that knows its own fleet's naming) without touching this
    default.

    This deliberately takes a *string* rather than doing the ``ls``
    itself so it is pure and unit-testable; the CLI feeds it a real
    remote listing.
    """
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    seen: dict[str, RunnerSpec] = {}
    for raw in listing.splitlines():
        entry = raw.strip()
        if not entry:
            continue
        matched = next((p for p in prefixes if entry.startswith(p)), None)
        if matched is None:
            continue
        # Skip sidecar artifacts the old scripts dropped next to the
        # install dirs (e.g. ``actions-runner-foo.wrap.log``). A real
        # install dir name has no dot after the prefix.
        tail = entry[len(matched) :]
        if not tail or "." in tail or "/" in tail:
            continue
        name = tail
        spec = RunnerSpec(name=name, dir=f"{ci_base.rstrip('/')}/{entry}")
        seen[name] = spec
    return [seen[k] for k in sorted(seen)]
