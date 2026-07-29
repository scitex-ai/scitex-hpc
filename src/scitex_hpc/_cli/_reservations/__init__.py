"""``scitex-hpc lease`` group — book / list / get / exec / refresh / attach / cancel.

``lease`` is the primary, documented command name. ``reservations`` is kept as
a **deprecated alias** that delegates to the same subcommands so existing
callers keep working; it prints a one-line deprecation notice to stderr.

``cancel`` is the canonical verb for tearing down a lease (``scancel`` + lease
cleanup); the legacy ``release`` spelling is kept as a hidden alias for one
minor-version cycle.

Thin orchestrator: importing the command modules is what registers them on
the group. Public API unchanged — ``from ._reservations import lease,
reservations`` still resolves, which the root tests rely on.
"""

from __future__ import annotations

from ._group import lease, reservations

from . import _book as _book_cmds  # noqa: F401,E402
from . import _ops as _ops_cmds  # noqa: F401,E402
from . import _query as _query_cmds  # noqa: F401,E402

__all__ = ["lease", "reservations"]
