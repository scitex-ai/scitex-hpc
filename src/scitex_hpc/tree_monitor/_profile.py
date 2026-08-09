"""Configuration for the catch-it-live shared-tree deletion monitor.

The manifest used to be a heredoc inside ``check_shared_tree.sh``, which
meant adding a path was a patch to a shell script rather than a config
edit. Here it is DATA — a list on a dataclass — so the renderer templates
it in and callers can build a profile for a host whose critical paths are
not this host's.

Same convention as :mod:`scitex_hpc.tunnel_supervisor._profile`: a frozen
dataclass with an ``EXAMPLE_PROFILE`` that is also the real default, so
the rendered artifact is reproducible from the profile alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class TreeMonitorProfile:
    """Everything the monitor needs, with no host baked into the code.

    ``manifest`` entries are ABSOLUTE paths and must not contain globs.
    A glob that matches nothing is indistinguishable from a path that was
    deleted, which would turn the monitor into a false-alarm generator —
    the one failure mode that reliably trains people to ignore it.
    ``$HOME`` is the only expansion the rendered script performs.
    """

    name: str = "shared-tree-monitor"
    description: str = "Catch-it-live monitor for shared punim0264 tree deletions"
    #: Card id the units point at, so a reader of `systemctl cat` can find
    #: the reasoning rather than only the mechanism.
    documentation_card: str = "spartan-shared-tree-catch-it-live-monitor"
    manifest: tuple[str, ...] = (
        "$HOME/.scitex/hpc",
        "$HOME/.scitex/dev/containers",
        "$HOME/.scitex/dev/containers/ci-cpu.sif",
    )
    #: Regenerable local state; overridable so tests never touch a real one.
    state_dir: str = "$HOME/.scitex/hpc/runtime"
    #: Where `install` writes the rendered script.
    script_path: str = "$HOME/.scitex/hpc/scripts/check_shared_tree.sh"
    #: Identity stamped on any alarm card the monitor raises.
    agent_id: str = "scitex-hpc"
    #: Timer cadence. Short enough that the forensics stay contemporaneous
    #: with the deletion; long enough that stat-ing a few paths is free.
    interval: str = "5min"
    boot_delay: str = "2min"
    accuracy: str = "30s"
    #: Paths whose owners have NOT confirmed them. Rendered as comments in
    #: the script so the manifest's partiality is visible where someone
    #: reads it, not only in a card.
    unconfirmed_owners: tuple[str, ...] = (
        "paper-scitex-clew (for_solver roots)",
        "scitex-storage",
    )

    def with_manifest(self, *paths: str) -> "TreeMonitorProfile":
        """Return a copy carrying ``paths`` as its manifest."""
        return replace(self, manifest=tuple(paths))


EXAMPLE_PROFILE = TreeMonitorProfile()
