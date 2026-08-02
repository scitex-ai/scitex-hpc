"""Shared presentation helper for the ``scitex-hpc lease`` command modules.

Lives in its own module so both :mod:`_lease_book` (book / adopt) and
:mod:`_lease_ops` (list / get / refresh) can serialize a
:class:`~scitex_hpc._reservation.Reservation` the SAME way, without either
importing the other and without a cycle back through :mod:`_reservations`
(which imports both to assemble the group).
"""

from __future__ import annotations

from .._reservation import Reservation


def serialize_reservation(res: Reservation) -> dict:
    """Render a reservation as the dict every ``--json`` output emits."""
    return {
        "id": res.id,
        "name": res.name,
        "host": res.host,
        "job_id": res.job_id,
        "node": res.node,
        "submitted_at": res.submitted_at,
        "walltime_end": res.walltime_end,
        "persistent": res.persistent,
    }
