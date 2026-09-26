"""``scitex_dev.jobs`` entry-point: scitex-hpc's periodic job roster.

Constitution §6 (operator ruling 2026-08-20): every SciTeX periodic job runs
through the supervisor via scitex-dev, and there is NO SECOND PLACE to put
one. This file is that one place for scitex-hpc. ``discover_jobs()`` finds it
through the ``scitex_dev.jobs`` entry-point declared in our pyproject.

``scitex_dev.jobs.JobSpec`` is **lazy-imported** inside the callable so
scitex-hpc keeps NO runtime hard-dependency on scitex-dev — the entry-point is
imported only when scitex-dev is doing the aggregating, which is exactly when
scitex-dev is present.

TWO SURFACES EXIST ON spartan-login1 TODAY, AND THIS ONE IS AUTHORITATIVE.
Measured 2026-08-30 on that host: no scitex-dev supervisor unit, no unit for
any job below, and an EMPTY crontab (0 lines) — so every spec here is
DECLARED AND MATERIALISED NOWHERE. The watchdog that is actually running is a
hand-installed systemd timer (``spartan-ci-fleet-watch.timer``), and the
deploy audit likewise (``deploy-audit.timer``).

Those hand-installed units are deliberately NOT removed yet: deleting the only
thing currently watching, in favour of a declaration nothing materialises,
would leave the fleet unwatched — trading a working second surface for a first
surface that does not run. §6's corollary is explicit that when the old
surface cannot leave in the same change, you say out loud that both exist and
which is authoritative, "because until you do, both are". So: THIS FILE IS
AUTHORITATIVE; the hand-installed timers are a stopgap and must be removed the
moment a supervisor on spartan-login1 materialises these specs. Tracked on
card spartan-two-periodic-job-surfaces-20260830.
"""

from __future__ import annotations


def jobs():
    """Return the scitex-hpc JobSpec roster for the ecosystem job manager.

    SoC: scitex-hpc owns these specs and the command bodies they invoke;
    scitex-dev's manager owns aggregation, placement and installation.
    """
    from scitex_dev.jobs import JobSpec

    return [
        JobSpec(
            name="scitex-hpc-ci-supervisor-watch",
            # kind="cron" until 2026-08-30. Cron is RETIRED by the operator's
            # 2026-08-20 ruling (§6) -- not discouraged, retired -- and
            # `ecosystem up` now REMOVES the managed crontab block rather than
            # writing it. A spec still asking for a crontab entry is asking
            # for the artifact the reconcile exists to delete.
            kind="timer",
            schedule="*/5 * * * *",
            command="scitex-hpc ci-runners watch",
            on_boot_sec="5min",
            on_unit_active_sec="5min",
            description=(
                "Health watchdog for the self-hosted scitex-ci runner fleet: "
                "each tick resolves the live supervisor holder job id from "
                "its runtime file, checks the allocation and every "
                "Runner.Listener, and alarms via $SCITEX_CI_ALARM_CMD. "
                "Exits 10 degraded / 11 allocation down / 12 supervisor "
                "unregistered / 13 out of inodes / 14 deploy drift."
            ),
            timeout_sec=120,
        ),
        JobSpec(
            name="scitex-hpc-inode-quota-warn",
            kind="timer",
            schedule="*/30 * * * *",
            command="scitex-hpc quota validate",
            on_boot_sec="10min",
            on_unit_active_sec="30min",
            description=(
                "Early warning for the GPFS inode-quota wall: df -i the "
                "tracked filesets and alarm via $SCITEX_CI_ALARM_CMD (exit "
                "1) when any is at/over 90%, so a fileset is never silently "
                "exhausted (the failure mode that breaks SAC state stores)."
            ),
            timeout_sec=120,
        ),
        JobSpec(
            name="scitex-hpc-deploy-audit",
            kind="timer",
            schedule="17 * * * *",
            command="scitex-hpc audit-deploys --quiet --on-change",
            on_boot_sec="10min",
            on_unit_active_sec="1h",
            description=(
                "Audit every EDITABLE install in the venv for deploy drift. "
                "An editable install makes a working TREE the artifact, so "
                "'merged' silently reads as 'deployed' while the deployed "
                "bytes never move. Exits 20 drift / 21 broken (a source "
                "directory that is GONE, which may not import at all). "
                "--on-change reports only when the actionable set CHANGES: "
                "a standing condition that already reached a human must not "
                "re-page every tick."
            ),
            timeout_sec=900,
        ),
    ]

# EOF
