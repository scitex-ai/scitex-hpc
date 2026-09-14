"""Canonical self-hosted runner registration with required CI labels.

Root cause (label drift, 2026-06-26)
------------------------------------
The runner fleet selects work via shared workflow labels including
``scitex-ci`` and ``scitex-org-cpu``. A runner only matches a workflow if it
was *registered* with every label that workflow requires. Registration used
to guarantee only ``scitex-ci``. Consequently, org workflows requiring
``scitex-org-cpu`` saturated other eligible runners while online HPC runners
remained idle. The durable fix belongs in registration, not a live API patch.

The fix (this module)
---------------------
:func:`build_register_command` is the SINGLE source of truth for the
``config.sh`` invocation, with every required label guaranteed in ``--labels``
(re-added even if a caller's custom label set forgot it). Every future
stand-up / reinstall goes through this command, so the label can never
drift out again. :func:`missing_required_labels` is the matching drift
*detector*: feed it the labels GitHub reports for a live runner to flag
any required labels missed at registration.

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
# labels. ``scitex-ci`` serves the shared CI template and ``scitex-org-cpu``
# serves org workflows. Omitting either leaves an online runner ineligible for
# part of the queue. ``spartan-cpu`` remains the existing host-class label.
REQUIRED_LABELS: tuple[str, ...] = ("scitex-ci", "scitex-org-cpu")
DEFAULT_RUNNER_LABELS: tuple[str, ...] = ("spartan-cpu", *REQUIRED_LABELS)

# Retained as the established name for the original shared-template label.
REQUIRED_LABEL = "scitex-ci"


def normalize_labels(labels: Iterable[str]) -> list[str]:
    """Strip and deduplicate labels, then append every missing required label.

    Blank/whitespace entries are dropped; duplicates collapse to their
    first occurrence. Required labels are appended in canonical order, so a
    caller cannot register a runner that is ineligible for shared CI routes.
    """
    out: list[str] = []
    for raw in labels:
        lab = raw.strip()
        if lab and lab not in out:
            out.append(lab)
    out.extend(label for label in REQUIRED_LABELS if label not in out)
    return out


def missing_required_labels(current: Iterable[str]) -> list[str]:
    """Return the required labels absent from ``current`` (drift detector).

    Pure: feed it the labels GitHub reports for a live runner (e.g. the
    ``labels[].name`` from ``gh api repos/<repo>/actions/runners``) to
    detect a runner that missed a required route label at registration.
    An empty list means the runner is correctly labelled.
    """
    have = {c.strip() for c in current}
    return [label for label in REQUIRED_LABELS if label not in have]


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
    """Build the ``config.sh`` registration command with route labels baked in.

    ``url`` is the repo or org the runner registers to; ``name`` is the
    runner's install-dir tag; ``token`` is the short-lived registration
    token (defaults to the ``<TOKEN>`` placeholder — the operator pastes a
    fresh one from GitHub → Settings → Actions → Runners → New, this module
    never mints or handles a real secret). ``labels`` is normalized via
    :func:`normalize_labels`, so every required route label is present. ``work``
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
