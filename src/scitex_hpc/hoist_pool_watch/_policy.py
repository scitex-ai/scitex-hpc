#!/usr/bin/env python3
"""Which upstreams the hoist pool MAY contain — a preference, read from config.

The drift watcher beside this module answers "is a pooled member serving?".
That is one of two questions. The other is "should this member be pooled at
all?", and no probe can answer it: a card can be reachable, healthy, and still
one we would rather not use.

WHY THIS IS CONFIG AND NOT CODE. Operator, 2026-09-03:
「A100除外については、たまたま私たちの趣味趣向ですので、コンフィグファイルにして
ください」「ただ、A100だと遅いからって言うだけです」「H100でも遅いのに、A100で
使ってられるかってことです」 — the exclusion is our taste, not a law of the
world, and the reason is simply that the card is slow. An earlier draft of this
module baked compute-04's port numbers in as a constant. That was wrong twice
over: it froze a preference into a release, and it broke this package's own
standing rule, stated in ``_config.py`` — "No site-specific cluster names are
baked into this package."

So the TYPES live here and the VALUES live in
``~/.scitex/hpc/config.yaml`` under ``hoist_pool:``, resolved through the same
``local_state`` cascade every other setting in this package uses.

Nothing here probes anything. Compose it with the watcher: config says what we
are willing to use, the probe says what is alive, and drift is the disagreement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from scitex_config._ecosystem import local_state

__all__ = ["Exclusion", "UpstreamPolicy", "load_policy", "config_candidates"]


@dataclass(frozen=True)
class Exclusion:
    """A member we keep out of the pool, and why.

    The reason is required and is the whole point of the type. An excluded
    member with no stated reason is indistinguishable from an oversight, and the
    next reader probes it, finds it healthy, and puts it back.
    """

    port: int
    reason: str
    decided_on: str = ""
    decided_by: str = ""
    reversible_when: str = ""

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                f"exclusion of port {self.port} needs a stated reason; an "
                "unexplained exclusion is re-added by the next person who probes it"
            )


@dataclass(frozen=True)
class UpstreamPolicy:
    """The pool one host is willing to route to."""

    expected: tuple[int, ...] = ()
    excluded: Mapping[int, Exclusion] = field(default_factory=dict)

    def admits(self, port: int) -> bool:
        return port in self.expected and port not in self.excluded

    def why_not(self, port: int) -> str:
        """Empty string when the port is admissible; otherwise the reason."""
        exc = self.excluded.get(port)
        if exc is not None:
            decided = ""
            if exc.decided_on or exc.decided_by:
                decided = f" (decided {exc.decided_on or '?'} by {exc.decided_by or '?'})"
            return f"{exc.reason}{decided}"
        if port not in self.expected:
            return (
                f"port {port} is not listed under hoist_pool.expected; add it to "
                "the config before it can be pooled"
            )
        return ""

    def verdict(self, pooled: Iterable[int]) -> dict[str, list[int]]:
        """Compare a live pool against the configured preference.

        ``forbidden`` is the case the drift watcher cannot see on its own: a
        member that is present and serving and that we did not want.
        """
        pooled = list(pooled)
        return {
            "forbidden": [p for p in pooled if p in self.excluded],
            # An excluded member is NOT undeclared. We named it and said no, so
            # reporting it under both headings would make one fault look like
            # two and send the reader to fill a config gap that is not there.
            "undeclared": [
                p for p in pooled if p not in self.expected and p not in self.excluded
            ],
            "missing": [
                p for p in self.expected if p not in pooled and p not in self.excluded
            ],
        }


def config_candidates() -> tuple[Path, ...]:
    """Where the pool preference is read from, in order.

    Resolved at call time, not import time, so ``$SCITEX_DIR`` relocates them
    the same way it does for every other setting in this package.
    """
    return (
        local_state.path("hpc", "config.yaml"),
        local_state.path("dev", "config.yaml"),
    )


def policy_from_mapping(data: Mapping[str, Any]) -> UpstreamPolicy:
    """Build a policy from an already-parsed ``hoist_pool`` mapping.

    Shape::

        hoist_pool:
          expected: [8001, 8002]
          excluded:
            8003:
              reason: "too slow to be worth a slot"
              decided_on: "2026-01-01"
              decided_by: operator
              reversible_when: "we decide otherwise"

    Ports here are illustrative. Real ones belong in the user's config, never in
    this file — see config.example.yaml.

    A malformed entry RAISES rather than being skipped. A pool preference that
    silently drops the line it could not read is how a card nobody wants ends up
    back in rotation.
    """
    expected = tuple(int(p) for p in (data.get("expected") or ()))
    excluded: dict[int, Exclusion] = {}
    for raw_port, spec in (data.get("excluded") or {}).items():
        port = int(raw_port)
        if isinstance(spec, str):
            spec = {"reason": spec}
        if not isinstance(spec, Mapping):
            raise ValueError(
                f"hoist_pool.excluded.{raw_port} must be a reason string or a "
                f"mapping, got {type(spec).__name__}"
            )
        excluded[port] = Exclusion(
            port=port,
            reason=str(spec.get("reason", "")),
            decided_on=str(spec.get("decided_on", "")),
            decided_by=str(spec.get("decided_by", "")),
            reversible_when=str(spec.get("reversible_when", "")),
        )
    return UpstreamPolicy(expected=expected, excluded=excluded)


def load_policy(path: Path | None = None) -> UpstreamPolicy:
    """Read the pool preference from user config.

    Returns an EMPTY policy when no config declares one. Empty means "nothing is
    declared", which ``verdict`` reports as every pooled member being
    undeclared — visible, and not mistaken for approval.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return UpstreamPolicy()
    paths = (path,) if path is not None else config_candidates()
    for candidate in paths:
        if candidate is None or not candidate.exists():
            continue
        data = yaml.safe_load(candidate.read_text()) or {}
        if not isinstance(data, dict):
            continue
        section = data.get("hoist_pool")
        if isinstance(section, Mapping):
            return policy_from_mapping(section)
    return UpstreamPolicy()
