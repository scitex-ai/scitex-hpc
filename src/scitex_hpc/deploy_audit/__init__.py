#!/usr/bin/env python3
"""Audit every EDITABLE install in a venv for deploy drift.

``scitex_hpc.ci_runners._deploy`` answers "is the package I am running the
merged one?" for ONE package -- whichever one's ``watch`` is executing. This
package answers it for the whole venv, because the answer turned out not to
generalise from a sample of one.

Measured on spartan-login1, 2026-08-30, across 62 editable distributions::

    current            12
    BEHIND             38      scitex_cloud 470, scitex_hub 470, scitex_ui 187
    DIVERGED            2      58 commits existing on no remote
    source path gone    9      5 of which cannot be imported at all
    no upstream         1      detached HEAD
    not-a-checkout      1

An editable install makes a working TREE the artifact: there is no build step
whose absence anyone would notice, so "merged" silently reads as "deployed".
Nothing in that venv complains, and none of the four failure modes above is
visible from the outside -- everything imports, or appears to.

The four are deliberately kept distinct because they call for different
actions: BEHIND wants a pull, DIVERGED cannot fast-forward and needs a human,
a MISSING SOURCE is a broken install rather than a stale one, and UNKNOWN is
the check admitting it could not look.
"""

from ._audit import (
    DEFAULT_STATE_PATH,
    InstallRow,
    actionable_signature,
    audit_venv,
    editable_installs,
    read_previous_signature,
    summarize,
    write_signature,
)

__all__ = [
    "DEFAULT_STATE_PATH",
    "InstallRow",
    "actionable_signature",
    "audit_venv",
    "editable_installs",
    "read_previous_signature",
    "summarize",
    "write_signature",
]

# EOF
