#!/usr/bin/env python3
"""Is the code this process is RUNNING the code that was merged?

An **editable** install (``__editable__.*.pth``) makes a working tree the
artifact. There is no build step, so "merged" quietly reads as "deployed"
while the deployed bytes never move — and nothing ever says otherwise.

Measured on Spartan, 2026-08-30::

    /home/ywatanabe/.venv/bin/scitex-hpc
      -> __editable__.scitex_hpc-0.8.3.pth
      -> /data/gpfs/projects/punim0264/ywatanabe/scitex-hpc

That checkout sat 19 commits behind ``origin/develop``, back at PR #64, with
a clean tree and no local commits. It had simply never been pulled.

WHY THIS IS A GATE AND NOT A NOTE. The CI health watchdog was fixed in #104
and #105, verified green from the repo we edit, and installed as a systemd
timer — whereupon it fired a CRITICAL saying the supervisor was unregistered
while the holder file plainly existed and the job was RUNNING. The deployed
copy still contained the exact bug that had been fixed. So the danger is not
stale code; it is that a gate can be built, verified, and armed entirely
against a copy that is not the one under the alarm. The alarm then pages with
a verdict sourced from code that was already correct.

The check answers "did the fix ARRIVE", which is the hop nobody instruments:
merged != pulled != deployed.

SCOPE. This inspects the checkout backing the *invoking* install, which is
the deployed one exactly when the watchdog runs where it is deployed (the
systemd timer on spartan-login1 — the case that failed). Run by hand from a
workstation it grades that workstation, so read the ``root`` it reports
rather than assuming which machine it spoke about.

A non-checkout install (a real wheel) is ``not-a-checkout``: nothing to
compare, and NOT a fault. An unreachable origin is ``unknown``, never an
alarm — a network blip must not page anyone about deployment.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DeployState", "inspect_deploy", "inspect_checkout"]

#: Never let a hung git hold the watchdog tick open.
_GIT_TIMEOUT_S = 30


@dataclass(frozen=True)
class DeployState:
    """What the running code is, relative to what was merged."""

    state: str
    detail: str
    root: str | None = None
    branch: str | None = None
    ahead: int = 0
    behind: int = 0

    @property
    def is_drift(self) -> bool:
        """True only for states an operator must ACT on.

        ``unknown`` and ``not-a-checkout`` are deliberately excluded: a
        check that cannot see is not a check that failed, and conflating
        the two is how an alarm rail loses its credibility.
        """
        return self.state in ("behind", "diverged")


def _git(root: str | Path, *args: str, runner=subprocess.run):
    """Run one git command. ``-C`` is always explicit (never a chdir)."""
    return runner(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
    )


def inspect_deploy(
    module_file: str | Path,
    *,
    remote: str = "origin",
    fetch: bool = True,
    runner=subprocess.run,
) -> DeployState:
    """Grade the checkout that provides ``module_file`` (see inspect_checkout)."""
    return inspect_checkout(
        Path(module_file).resolve().parent,
        remote=remote,
        fetch=fetch,
        runner=runner,
    )


def inspect_checkout(
    start: str | Path,
    *,
    remote: str = "origin",
    fetch: bool = True,
    runner=subprocess.run,
) -> DeployState:
    """Grade the git checkout containing ``start`` (a directory or a file).

    :func:`inspect_deploy` is the front door for the common case: pass a
    module's ``__file__`` so the code is located by asking the *imported
    module* where it lives, never by guessing a path — guessing is what the
    editable indirection defeats.

    This lower-level form exists for auditing checkouts nobody imported,
    e.g. every editable install in a venv (:mod:`scitex_hpc.deploy_audit`),
    where the source directory comes from ``direct_url.json`` rather than
    from an import.
    """
    start = Path(start).resolve()
    try:
        top = _git(start, "rev-parse", "--show-toplevel", runner=runner)
    except (OSError, subprocess.SubprocessError) as exc:
        return DeployState("unknown", f"git unavailable: {exc}")

    if top.returncode != 0:
        return DeployState(
            "not-a-checkout",
            f"{start} is not inside a git checkout (installed as a built "
            "artifact) — nothing to compare, and nothing wrong",
        )
    root = top.stdout.strip()

    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD", runner=runner)
    branch = head.stdout.strip()
    if head.returncode != 0 or not branch or branch == "HEAD":
        return DeployState(
            "unknown",
            "detached HEAD or unreadable branch — no upstream to compare",
            root=root,
        )

    # Ask git what this branch TRACKS rather than assuming
    # ``origin/<same-name>``. A deploy site pinned to a differently-named
    # upstream would otherwise grade "unknown" and go silently blind --
    # which is the one outcome this module exists to prevent.
    up = _git(
        root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        runner=runner,
    )
    if up.returncode == 0 and up.stdout.strip():
        upstream = up.stdout.strip()
    else:
        upstream = f"{remote}/{branch}"

    fetch_remote, _, fetch_branch = upstream.partition("/")
    if fetch:
        # A failure here is NOT an alarm; we fall through and compare against
        # whatever ref we already have, then say so.
        try:
            _git(root, "fetch", "--quiet", fetch_remote, fetch_branch, runner=runner)
        except (OSError, subprocess.SubprocessError):
            pass

    counts = _git(
        root,
        "rev-list",
        "--left-right",
        "--count",
        f"HEAD...{upstream}",
        runner=runner,
    )
    if counts.returncode != 0:
        return DeployState(
            "unknown",
            f"no {upstream} to compare against -- this checkout tracks "
            "nothing reachable, so deploy drift CANNOT be detected here",
            root=root,
            branch=branch,
        )

    parts = counts.stdout.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return DeployState(
            "unknown",
            f"unparseable rev-list output: {counts.stdout!r}",
            root=root,
            branch=branch,
        )
    ahead, behind = int(parts[0]), int(parts[1])

    # Both directions, always. "behind" and "diverged" look identical from
    # one side, and they call for different actions (pull vs. reconcile).
    if behind and ahead:
        state = "diverged"
        detail = (
            f"{root} is {behind} commit(s) behind AND {ahead} ahead of "
            f"{upstream} — a plain pull will NOT fast-forward"
        )
    elif behind:
        state = "behind"
        detail = (
            f"{root} is {behind} commit(s) behind {upstream} — the running "
            f"code is not the merged code. Deploy: git -C {root} pull "
            "--ff-only"
        )
    else:
        state = "current"
        detail = f"{root} matches {upstream}" + (
            f" ({ahead} local commit(s) ahead)" if ahead else ""
        )

    return DeployState(
        state, detail, root=root, branch=branch, ahead=ahead, behind=behind
    )

# EOF
