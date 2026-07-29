"""``scitex-hpc ci-runners`` group — durable self-hosted runner fleet.

Thin orchestrator. The group and its shared helpers live in ``_group``;
the command bodies live in the sibling modules and register themselves on
the group at import time, so importing this package is what wires the CLI
up. Public API is unchanged: ``from ._ci_runners import ci_runners``.

Subcommands:

  * ``discover`` — list the runner install dirs found under the CI base.
  * ``book-supervisor`` — book a dedicated long-walltime CPU allocation
    and host the whole runner fleet on it under auto-restart keep-alive
    loops. Default ``--dry-run`` prints the plan; pass ``--confirm`` to
    actually submit (never on import, never implicitly).
  * ``exec-supervisor`` — run the SAME supervisor body inside an
    ALREADY-RUNNING allocation via ``srun --jobid=<holder> --overlap``,
    for when a dedicated node won't schedule. Same ``--confirm`` gate.
  * ``watch`` — one health-check tick; the cron watchdog entrypoint.
  * ``show-monitor`` — emit the cron-driven health-monitor script.
  * ``show-register`` — print the ``config.sh`` command that registers a
    runner WITH the ``scitex-ci`` label baked in (closes label drift at
    the source, so a re-registered runner never queues its repo's CI).
  * ``show-archive`` — emit a script that archives the old ``~`` band-aid
    scripts to ``.old/<timestamp>/`` on the cluster (the operator runs it
    AFTER cutover; live runners still depend on the band-aids until then).

The CLI only ever *reads* the cluster (discover) or *prints plans /
scripts* — submission and archival are explicit operator actions guarded
behind ``--confirm`` / hand-running the generated scripts.
"""

from __future__ import annotations

from ._group import ci_runners

# Importing these modules registers their commands on the group above.
from . import _discover as _discover_cmds  # noqa: F401,E402
from . import _show as _show_cmds  # noqa: F401,E402
from . import _supervisor as _supervisor_cmds  # noqa: F401,E402

__all__ = ["ci_runners"]
