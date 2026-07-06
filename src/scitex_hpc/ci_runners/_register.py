"""Canonical self-hosted runner *registration* — bake ``scitex-ci`` in.

Root cause (label drift, 2026-06-26)
------------------------------------
The runner fleet selects work via the ci-template default
``runs-on: [self-hosted, scitex-ci]``. A runner only matches that if it
was *registered* with the ``scitex-ci`` label. The live fleet was patched
in-place (``scitex-ci`` added to the 68 running runners via the GitHub
API) — but the label was never baked into the **registration step**
(``config.sh``). So any re-registered or newly-stood-up runner comes up
with only ``[self-hosted, Linux, X64, spartan-cpu]``, silently misses the
template default, and its repo's CI queues forever again. Band-aid (patch
the live set) vs durable (fix registration) — the constitution's exact
distinction.

The fix (this module)
---------------------
:func:`build_register_command` is the SINGLE source of truth for the
``config.sh`` invocation, with ``scitex-ci`` guaranteed in ``--labels``
(re-added even if a caller's custom label set forgot it). Every future
stand-up / reinstall goes through this command, so the label can never
drift out again. :func:`missing_required_labels` is the matching drift
*detector*: feed it the labels GitHub reports for a live runner to flag
one that missed ``scitex-ci`` at registration.

Everything here is pure string/list building — no SSH, no GitHub API, no
token generation — so it is trivially unit-testable. The CLI
(``scitex-hpc ci-runners show-register``) prints the command for the
operator to run on the cluster with a fresh registration token; this
module never executes it and never handles a real secret.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Sequence

# The custom labels every scitex-ci runner MUST register with. ``config.sh``
# auto-adds the implicit ``self-hosted,Linux,X64`` trio; these are the EXTRA
# labels. ``scitex-ci`` is the load-bearing one the ci-template's
# ``runs-on: [self-hosted, scitex-ci]`` selects on — omit it and the runner
# never matches, so the repo's CI queues forever (the 2026-06-26 drift
# outage). ``spartan-cpu`` marks the host class (kept for parity with the
# live fleet's existing labels).
DEFAULT_RUNNER_LABELS: tuple[str, ...] = ("spartan-cpu", "scitex-ci")

# The one label that MUST always be present regardless of caller input —
# build_register_command re-adds it, missing_required_labels checks for it.
REQUIRED_LABEL = "scitex-ci"


def normalize_labels(labels: Iterable[str]) -> list[str]:
    """Strip + dedupe ``labels`` (order-preserving), guaranteeing the required one.

    Blank/whitespace entries are dropped; duplicates collapse to their
    first occurrence; :data:`REQUIRED_LABEL` is appended if absent so a
    caller can never register a runner that misses ``scitex-ci``.
    """
    out: list[str] = []
    for raw in labels:
        lab = raw.strip()
        if lab and lab not in out:
            out.append(lab)
    if REQUIRED_LABEL not in out:
        out.append(REQUIRED_LABEL)
    return out


def missing_required_labels(current: Iterable[str]) -> list[str]:
    """Return the required labels absent from ``current`` (drift detector).

    Pure: feed it the labels GitHub reports for a live runner (e.g. the
    ``labels[].name`` from ``gh api repos/<repo>/actions/runners``) to
    detect a runner that missed ``scitex-ci`` at registration. Empty list
    means the runner is correctly labelled.
    """
    have = {c.strip() for c in current}
    return [] if REQUIRED_LABEL in have else [REQUIRED_LABEL]


def build_register_command(
    *,
    url: str,
    name: str,
    token: str = "<TOKEN>",
    labels: Sequence[str] = DEFAULT_RUNNER_LABELS,
    work: str | None = None,
    runner_group: str | None = None,
    replace: bool = True,
    config_sh: str = "./config.sh",
) -> str:
    """Build the ``config.sh`` registration command with ``scitex-ci`` baked in.

    ``url`` is the repo or org the runner registers to; ``name`` is the
    runner's install-dir tag; ``token`` is the short-lived registration
    token (defaults to the ``<TOKEN>`` placeholder — the operator pastes a
    fresh one from GitHub → Settings → Actions → Runners → New, this module
    never mints or handles a real secret). ``labels`` is normalized via
    :func:`normalize_labels`, so ``scitex-ci`` is always present. ``work``
    keeps ``_work`` off the home quota; ``runner_group`` and ``replace``
    map to the matching ``config.sh`` flags (``--replace`` re-registers an
    existing runner of the same name instead of erroring).

    Returns one shell-safe line, ``shlex``-quoted argument by argument.
    """
    labs = ",".join(normalize_labels(labels))
    parts: list[str] = [
        config_sh,
        "--unattended",
        "--url",
        url,
        "--token",
        token,
        "--name",
        name,
        "--labels",
        labs,
    ]
    if work:
        parts += ["--work", work]
    if runner_group:
        parts += ["--runnergroup", runner_group]
    if replace:
        parts.append("--replace")
    return " ".join(shlex.quote(p) for p in parts)
