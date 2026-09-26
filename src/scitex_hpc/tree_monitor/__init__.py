"""Catch-it-live monitor for shared-tree deletions.

WHY IT EXISTS: ``~/.scitex/hpc/``, ``~/.scitex/dev/containers/`` and the
clew ``for_solver`` roots have vanished before, and every post-hoc attempt
to identify the deleter failed — crontab disabled, systemd --user swept
twice, own SLURM history clean, four concrete leads closed with hard
evidence. Forensics after the fact are exhausted. This catches the NEXT one
while it is happening.

Shape (mirrors :mod:`scitex_hpc.tunnel_supervisor`): a
:class:`TreeMonitorProfile` supplies every site-specific value — the
manifest, the state directory, the script target, the timer cadence — with
no host baked into the code. The primitive RENDERS the monitor shell and
both systemd units from that profile (:mod:`._render`, pure string
generation), INSTALLS them as an explicit step (:mod:`._install`), and can
report whether the installed monitor is still alive (:mod:`._health`).

PR #83 put the monitor under version control, which closed the hazard that
it existed only inside the tree it guards. This module closes the second
half: it was still three ``scp`` lines and a ``systemctl`` invocation
transcribed from a README.

Core guarantees, none of them new — they are the shell script's, preserved:

  * **Three-valued by construction.** A path is PRESENT, MISSING or
    UNKNOWN, and only a PRESENT->MISSING transition alarms. A stat failure
    is UNKNOWN, never MISSING, and an UNKNOWN never overwrites a PRESENT
    baseline — so a real deletion during an unreadable window is still
    caught on the next good run.
  * **Alarms through the shared board, not only a local log.** A local log
    is exactly what a deleter could also remove; the card is the rail that
    survives the host.
  * **Rehearsable.** ``SCITEX_TREE_MONITOR_DRYRUN=1`` exercises the alarm
    branch without writing a card — see :func:`rehearse_command`. An alarm
    path that cannot be rehearsed safely either goes untested or teaches
    everyone to ignore its cards.

And one guarantee that is new here: the monitor's OWN liveness is
three-valued too (:func:`check_freshness`). A monitor whose health check
collapses "cannot tell" into "fine" is how a dead monitor reports healthy.
"""

from __future__ import annotations

from ._health import (
    FRESH,
    STALE,
    UNKNOWN,
    Freshness,
    LogReader,
    check_freshness,
)
from ._install import (
    enable_commands,
    install,
    rehearse_command,
    write_check_script,
    write_units,
)
from ._profile import EXAMPLE_PROFILE, TreeMonitorProfile
from ._render import (
    render_check_script,
    render_manifest_block,
    render_service_unit,
    render_timer_unit,
)

__all__ = [
    "EXAMPLE_PROFILE",
    "FRESH",
    "Freshness",
    "LogReader",
    "STALE",
    "TreeMonitorProfile",
    "UNKNOWN",
    "check_freshness",
    "enable_commands",
    "install",
    "rehearse_command",
    "render_check_script",
    "render_manifest_block",
    "render_service_unit",
    "render_timer_unit",
    "write_check_script",
    "write_units",
]
