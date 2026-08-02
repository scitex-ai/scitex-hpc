"""``scitex_dev.jobs`` entry-point: the federated CI supervisor watchdog.

The scitex-dev ecosystem cron manager discovers this via the
``scitex_dev.jobs`` entry-point (registered in scitex-hpc's own pyproject)
and materialises the returned specs into its managed crontab block, so a
dead scitex-ci supervisor self-heals through the same roster as
``deploy-freshness`` / ``ecosystem-self-pull``.

``scitex_dev.jobs.JobSpec`` is **lazy-imported** inside the callable so
scitex-hpc keeps NO runtime hard-dependency on scitex-dev — the entry-point
is only imported at ``scitex-dev ecosystem cron install`` time, which is
exactly when scitex-dev is present.
"""

from __future__ import annotations


def jobs():
    """Return the scitex-hpc JobSpec roster for the ecosystem cron manager.

    One spec today: a 5-minute health watchdog that runs
    ``scitex-hpc ci-runners watch`` (resolves the live supervisor holder id,
    checks the allocation + every ``Runner.Listener``, alarms via
    ``$SCITEX_CI_ALARM_CMD`` on degradation). SoC: scitex-hpc owns this spec
    + the ``watch`` body; scitex-dev's manager owns aggregation + install.
    """
    from scitex_dev.jobs import JobSpec

    return [
        JobSpec(
            name="scitex-hpc.ci-supervisor-watch",
            kind="cron",
            schedule="*/5 * * * *",
            command="scitex-hpc ci-runners watch",
            description=(
                "Health watchdog for the self-hosted scitex-ci runner "
                "fleet: each tick resolves the live supervisor holder job "
                "id from its runtime file, checks the allocation + every "
                "Runner.Listener, and alarms via $SCITEX_CI_ALARM_CMD on "
                "degradation (exit 1) / allocation down (2) / supervisor "
                "unregistered (3)."
            ),
            timeout_sec=120,
        ),
        JobSpec(
            name="scitex-hpc.inode-quota-warn",
            kind="cron",
            schedule="*/30 * * * *",
            command="scitex-hpc quota validate",
            description=(
                "Early warning for the GPFS inode-quota wall: df -i the "
                "tracked filesets and alarm via $SCITEX_CI_ALARM_CMD (exit "
                "1) when any is at/over 90%, so a fileset is never silently "
                "exhausted (the failure mode that breaks SAC state-dbs)."
            ),
            timeout_sec=120,
        ),
    ]
