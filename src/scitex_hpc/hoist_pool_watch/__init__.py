"""Detect drift between the hoist proxy's ROUTED pool and what is actually SERVING.

Both directions matter and both have happened on compute-04:

* POOLED but NOT SERVING — measured 2026-08-28, 18775 sat in the pool while not
  listening and "roughly 1 request in 3 returned 502 ... which killed a working
  agent mid-task". A 3-member pool with one dead member does not degrade to 2/3
  throughput; it fails 1/3 of requests outright.
* SERVING but NOT POOLED — silent lost capacity. 18775 was removed with the note
  "Restore it here the moment 18775 serves again", and that restoration is held
  by whoever remembers.

The second case is why this exists. A trigger held by a sentence in a config file
is the shape qwen-horizon.sh was written to replace ("The deadline was being held
by a sentence in a card. Nothing performed that check.").

DETECTION ONLY — it never edits the drop-in. Every agent reaches the models
through this proxy, so changing its membership is a deliberate act, not something
a timer does at 03:00.

Reads systemd's RESOLVED HOIST_UPSTREAM, never the unit file: the main unit's own
line 7 says "THIS LINE IS A FALLBACK, NOT THE LIVE VALUE", and reading the file
instead of the resolution is the exact misread that unit records on 2026-08-18
and that recurred 2026-08-29.

Proof of "serving" is /v1/models returning a model id. A TCP connect is not
proof: a dead-but-listening forward accepts the connection and returns nothing,
rendering identically to a refused one (both HTTP 000).

Drift is only half the question. The watcher asks "is a pooled member serving?";
`_policy` answers "may this member be pooled at all?", which no probe can decide
— the A100 at 18776 is reachable, healthy and forbidden by an operator ruling.
Keep the two apart: policy states what is allowed, the probe states what is
alive, and drift is where they disagree. INCIDENTS.md holds the measurements
behind each entry.
"""

from ._policy import FLEET_POLICY, Exclusion, UpstreamPolicy

__all__ = ["FLEET_POLICY", "Exclusion", "UpstreamPolicy"]
