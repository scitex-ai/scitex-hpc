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

# Install dirs are named ``actions-runner-<name>`` under the CI base dir.
RUNNER_DIR_PREFIX = "actions-runner-"

# How long the keep-alive loop waits before relaunching a runner whose
# ``run.sh`` just exited. Long enough to avoid a hot crash-loop hammering
# GitHub, short enough that a transient blip self-heals within a minute.
DEFAULT_RESTART_BACKOFF_SECONDS = 15

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

    def active(self) -> list[RunnerSpec]:
        """Runners that should be launched (excludes filtered out)."""
        ex = set(self.exclude)
        return [r for r in self.runners if r.name not in ex]


def parse_runner_dirs(
    listing: str,
    *,
    ci_base: str,
    prefix: str = RUNNER_DIR_PREFIX,
) -> list[RunnerSpec]:
    """Parse a plain ``ls`` listing of the CI base dir into RunnerSpecs.

    Accepts the output of ``ls <ci_base>`` (one entry per line). Keeps
    only entries that start with ``prefix`` and have no extra suffix that
    marks them as a non-runner artifact (``.log``, ``.wrap.log``, etc.).
    Deterministic: sorted by name, deduplicated.

    This deliberately takes a *string* rather than doing the ``ls``
    itself so it is pure and unit-testable; the CLI feeds it a real
    remote listing.
    """
    seen: dict[str, RunnerSpec] = {}
    for raw in listing.splitlines():
        entry = raw.strip()
        if not entry or not entry.startswith(prefix):
            continue
        # Skip sidecar artifacts the old scripts dropped next to the
        # install dirs (e.g. ``actions-runner-foo.wrap.log``). A real
        # install dir name has no dot after the prefix.
        tail = entry[len(prefix) :]
        if not tail or "." in tail or "/" in tail:
            continue
        name = tail
        spec = RunnerSpec(name=name, dir=f"{ci_base.rstrip('/')}/{entry}")
        seen[name] = spec
    return [seen[k] for k in sorted(seen)]
