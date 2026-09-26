#!/usr/bin/env python3
"""Tests for scitex-hpc's periodic job roster.

Constitution §6 (operator ruling 2026-08-20) retires cron and puts every
SciTeX periodic job through the supervisor via scitex-dev, with no second
place. §7 says prefer a mechanical barrier to a written warning, so the
retirement is asserted here rather than left as a comment someone re-reads.

These build REAL ``scitex_dev.jobs.JobSpec`` objects — the validator is part
of the contract under test, so a spec that would be rejected by the real
manager must be rejected here too.
"""

from __future__ import annotations

from scitex_hpc.ci_runners._jobs import jobs


def test_the_roster_declares_jobs():
    # Arrange
    roster = jobs()
    # Act
    count = len(roster)
    # Assert — a control: an empty roster would satisfy every rule below
    # while declaring nothing, which is the gate-that-cannot-fail shape
    assert count > 0


def test_no_job_asks_for_a_crontab_entry():
    # Arrange — cron is RETIRED, not discouraged (operator, 2026-08-20), and
    # `ecosystem up` now REMOVES the managed crontab block rather than
    # writing it; a spec asking for one asks for the artifact the reconcile
    # exists to delete
    roster = jobs()
    # Act
    cron_kinds = [j.name for j in roster if j.kind == "cron"]
    # Assert
    assert cron_kinds == []


def test_every_job_carries_the_package_prefix():
    # Arrange — `scitex-<pkg>-<name>` is the canonical id (PS-227)
    roster = jobs()
    # Act
    unprefixed = [j.name for j in roster if not j.name.startswith("scitex-hpc-")]
    # Assert
    assert unprefixed == []


def test_no_job_name_contains_a_dot():
    # Arrange — systemd_unit_name derives the unit FILENAME verbatim, so a
    # dot silently installs a SECOND unit instead of adopting the intended one
    roster = jobs()
    # Act
    dotted = [j.name for j in roster if "." in j.name]
    # Assert
    assert dotted == []


def test_job_names_are_lowercase_hyphenated():
    # Arrange — hyphens only: no underscores, no uppercase (PS-226)
    roster = jobs()
    # Act
    malformed = [
        j.name
        for j in roster
        if "_" in j.name or j.name != j.name.lower()
    ]
    # Assert
    assert malformed == []


def test_every_job_bounds_its_runtime():
    # Arrange — an unbounded periodic job can overlap itself indefinitely
    roster = jobs()
    # Act
    unbounded = [j.name for j in roster if not j.timeout_sec]
    # Assert
    assert unbounded == []


def test_the_watchdog_description_states_current_exit_codes():
    # Arrange — this description said "1 / 2 / 3" while the monitor exited
    # 10/11/12/13, the same staleness `watch --help` carried until #106
    roster = jobs()
    watch = next(j for j in roster if j.name.endswith("ci-supervisor-watch"))
    # Act
    detail = watch.description
    # Assert
    assert "10" in detail and "1 / 2 / 3" not in detail


def test_the_deploy_audit_is_declared_here_too():
    # Arrange — it was installed by hand as a systemd timer on 2026-08-30;
    # the declaration is what makes this file the single surface
    roster = jobs()
    # Act
    names = [j.name for j in roster]
    # Assert
    assert "scitex-hpc-deploy-audit" in names

# EOF
