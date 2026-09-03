#!/usr/bin/env python3
"""Which upstreams the hoist pool MAY contain, as data rather than as prose.

The drift watcher beside this module answers "is a pooled member serving?" That
is one of two questions. The other is "should this member be pooled at all?",
and no probe can answer it: the A100 at 18776 is reachable, healthy, and
forbidden by an operator ruling. A liveness check asked about it returns True.

Until now that ruling existed only as a comment in
``~/.config/systemd/user/anthropic-system-hoist-proxy.service.d/upstream.conf``
-- one file, on one host, outside version control. Two agents have already
reported the exclusion handled after grepping agent SPECS and finding no
reference to 18776. The grep was accurate and the answer was wrong: traffic
reaches the models through the proxy's pool, not through the path a spec names.
That is what this module exists to prevent, so the reasons travel with the data.

Membership here is a POLICY, not an observation. Nothing in this file probes
anything. Compose it with the watcher: policy says what is allowed, the probe
says what is alive, and drift is the disagreement between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

__all__ = ["Exclusion", "UpstreamPolicy", "FLEET_POLICY"]


@dataclass(frozen=True)
class Exclusion:
    """A member kept out of the pool, and WHY.

    The reason is required and is the whole point of the type. An excluded port
    with no stated reason is indistinguishable from an oversight, and the next
    reader -- human or agent -- will probe it, find it healthy, and put it back.
    """

    port: int
    reason: str
    decided_on: str
    decided_by: str
    reversible_when: str = ""

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                f"exclusion of port {self.port} needs a stated reason; an "
                "unexplained exclusion is re-added by the next person who probes it"
            )


@dataclass(frozen=True)
class UpstreamPolicy:
    """The admissible pool for one host's hoist proxy."""

    expected: tuple[int, ...]
    excluded: Mapping[int, Exclusion] = field(default_factory=dict)

    def admits(self, port: int) -> bool:
        return port in self.expected and port not in self.excluded

    def why_not(self, port: int) -> str:
        """Empty string when the port is admissible; otherwise the reason."""
        exc = self.excluded.get(port)
        if exc is not None:
            return f"{exc.reason} (decided {exc.decided_on} by {exc.decided_by})"
        if port not in self.expected:
            return (
                f"port {port} is not declared in this policy; add it to `expected` "
                "before it can be pooled"
            )
        return ""

    def verdict(self, pooled: Iterable[int]) -> dict[str, list[int]]:
        """Compare a live pool against the policy.

        ``forbidden`` is the case the drift watcher cannot see on its own: a
        member that is present and serving and should not be there.
        """
        pooled = list(pooled)
        return {
            "forbidden": [p for p in pooled if p in self.excluded],
            "undeclared": [p for p in pooled if p not in self.expected],
            "missing": [p for p in self.expected if p not in pooled and p not in self.excluded],
        }


# The compute-04 pool, transcribed from upstream.conf on 2026-09-03. Every entry
# below is a decision someone made after an incident; INCIDENTS.md in this
# directory carries the measurements those decisions were made from.
FLEET_POLICY = UpstreamPolicy(
    expected=(18773, 18774, 18775, 18776),
    excluded={
        18775: Exclusion(
            port=18775,
            reason=(
                "not listening. A dead member of a fan-out pool is not resilience: "
                "roughly one request in three returned 502 and killed a working "
                "agent mid-task"
            ),
            decided_on="2026-08-28",
            decided_by="sac (measured)",
            reversible_when="18775 serves again; this is a capacity loss, not a policy",
        ),
        18776: Exclusion(
            port=18776,
            reason=(
                "the A100, held out of the Qwen pool by operator instruction. It is "
                "LIVE and answers probes, so reachability will never exclude it. It "
                "is also a magnet under least-loaded selection: at ~8.7x slower than "
                "an H100 (73.1s mean TTFT against 8.4s) it drains its queue and so "
                "keeps looking least-loaded, which is correct policy for a "
                "homogeneous pool and wrong for this one"
            ),
            decided_on="2026-08-16",
            decided_by="operator (「A100はさしあたりQwenに使うのはやめましょう」)",
            reversible_when="the operator says so; no measurement reverses this one",
        ),
    },
)
