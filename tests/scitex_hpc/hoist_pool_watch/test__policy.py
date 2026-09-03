#!/usr/bin/env python3
"""The guard the incidents in INCIDENTS.md would have needed.

Each test names the failure it covers. The one that matters most is
`test_a100_is_not_admitted_although_reachable`: reachability cannot express an
operator ruling, and that exclusion has already been re-derived wrongly once, by
grepping agent specs instead of reading the live pool.
"""

import inspect

import pytest

from scitex_hpc.hoist_pool_watch import _policy
from scitex_hpc.hoist_pool_watch._policy import FLEET_POLICY, Exclusion, UpstreamPolicy


def test_an_exclusion_without_a_reason_is_refused():
    # Arrange: an exclusion whose reason is only whitespace
    blank = "   "
    # Act / Assert: an unexplained exclusion is indistinguishable from an
    # oversight, so the next reader probes the port, finds it healthy and
    # restores it. The type refuses to record one.
    # Assert
    with pytest.raises(ValueError, match="stated reason"):
        Exclusion(port=1, reason=blank, decided_on="2026-01-01", decided_by="nobody")


def test_a100_is_not_admitted_although_reachable():
    # Arrange: 2026-08-16, the A100 answers probes and is forbidden by ruling
    port = 18776
    # Act
    admitted = FLEET_POLICY.admits(port)
    # Assert
    assert admitted is False


def test_a100_exclusion_names_the_operator_as_the_decider():
    # Arrange: no measurement reverses this one, so the decider must be recorded
    port = 18776
    # Act
    why = FLEET_POLICY.why_not(port)
    # Assert
    assert "operator" in why


def test_a100_exclusion_carries_the_date_it_was_decided():
    # Arrange
    port = 18776
    # Act
    why = FLEET_POLICY.why_not(port)
    # Assert
    assert "2026-08-16" in why


def test_the_dead_member_is_not_admitted():
    # Arrange: 2026-08-28, 18775 stopped listening and stayed in the pool
    port = 18775
    # Act
    admitted = FLEET_POLICY.admits(port)
    # Assert
    assert admitted is False


def test_the_dead_member_records_how_its_exclusion_reverses():
    # Arrange: unlike the A100 this is a capacity loss, not a policy, so the
    # restoration must not be held by whoever remembers
    port = 18775
    # Act
    reversible = FLEET_POLICY.excluded[port].reversible_when
    # Assert
    assert "serves again" in reversible


def test_a_healthy_declared_member_is_admitted():
    # Arrange
    port = 18773
    # Act
    admitted = FLEET_POLICY.admits(port)
    # Assert
    assert admitted is True


def test_an_admitted_member_has_no_reason_against_it():
    # Arrange
    port = 18773
    # Act
    why = FLEET_POLICY.why_not(port)
    # Assert
    assert why == ""


def test_verdict_reports_a_forbidden_member_that_is_pooled():
    # Arrange: the fault a liveness probe cannot see — present, serving, and
    # not allowed to be
    pooled = [18773, 18776, 19999]
    # Act
    verdict = FLEET_POLICY.verdict(pooled)
    # Assert
    assert verdict["forbidden"] == [18776]


def test_verdict_reports_an_undeclared_member_separately():
    # Arrange: a policy GAP to fill, not a breach to remove — different remedy
    pooled = [18773, 18776, 19999]
    # Act
    verdict = FLEET_POLICY.verdict(pooled)
    # Assert
    assert verdict["undeclared"] == [19999]


def test_verdict_reports_a_declared_member_that_is_absent():
    # Arrange: 2026-08-15, silent lost capacity is the harder direction to notice
    pooled = [18773]
    # Act
    verdict = FLEET_POLICY.verdict(pooled)
    # Assert
    assert 18774 in verdict["missing"]


def test_verdict_does_not_report_an_excluded_member_as_missing():
    # Arrange: otherwise the alarm cries wolf every cycle and stops being read
    pooled = [18773]
    # Act
    verdict = FLEET_POLICY.verdict(pooled)
    # Assert
    assert 18776 not in verdict["missing"]


def test_an_empty_pool_reports_every_admissible_member_missing():
    # Arrange: 2026-08-15, the pool held one member and four GPUs behaved as one
    pooled = []
    # Act
    verdict = FLEET_POLICY.verdict(pooled)
    # Assert
    assert verdict["missing"] == [18773, 18774]


def test_policy_performs_no_network_io():
    # Arrange: if policy ever grows a probe, the two questions collapse into one
    # and the A100 becomes invisible again the moment it is healthy
    src = inspect.getsource(_policy)
    forbidden = ("import socket", "import requests", "urllib.request", "subprocess")
    # Act
    offenders = [name for name in forbidden if name in src]
    # Assert
    assert offenders == []


def test_a_custom_policy_refuses_a_port_it_never_declared():
    # Arrange
    policy = UpstreamPolicy(expected=(1, 2))
    # Act
    why = policy.why_not(3)
    # Assert
    assert "not declared" in why
