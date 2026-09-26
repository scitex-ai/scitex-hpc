#!/usr/bin/env python3
"""Locate the alarm rail's own files, from the installed package.

The README used to tell an operator to ``cp`` a path they had to know. That
is how the rail ended up on one host and not the other: the instruction
carried a location instead of a lookup, so it could only be followed by
someone who already knew where the files were.

Asking the imported package where its files live works the same on a wheel,
on an editable install, and in a checkout -- and it is the same discipline
:mod:`scitex_hpc.ci_runners._deploy` uses to find the running code.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["SINK_NAME", "sink_path", "unit_template_path", "dropin_path"]

#: Extensionless on purpose: it is exec'd as a command, never sourced.
SINK_NAME = "scitex-ci-alarm"

#: ``%n`` already carries ``.service``, so the live instance name DOUBLES the
#: suffix. Querying the single-suffix name returns a nonexistent unit whose
#: defaults (Result=success, ExecMainStatus=0) look exactly like a clean run.
UNIT_TEMPLATE_NAME = "scitex-unit-failed@.service"

DROPIN_NAME = "onfailure.conf"


def _here() -> Path:
    return Path(__file__).resolve().parent


def sink_path() -> Path:
    """Absolute path to the alarm sink shipped with this package."""
    return _here() / SINK_NAME


def unit_template_path() -> Path:
    """Absolute path to the ``OnFailure=`` target template."""
    return _here() / UNIT_TEMPLATE_NAME


def dropin_path() -> Path:
    """Absolute path to the drop-in that wires a unit to the rail."""
    return _here() / DROPIN_NAME

# EOF
