#!/usr/bin/env python3
"""Guards for the pool preference.

The one that matters most is `test_module_bakes_in_no_site_ports`: the values
are a preference and belong in the user's config, not in a release. An earlier
draft of this module hardcoded one host's ports, which froze a taste into the
package and broke the rule `_config.py` already states — "No site-specific
cluster names are baked into this package."
"""

import inspect
import re

import pytest

from scitex_hpc.hoist_pool_watch import _policy
from scitex_hpc.hoist_pool_watch._policy import (
    Exclusion,
    UpstreamPolicy,
    load_policy,
    policy_from_mapping,
)

SAMPLE = {
    "expected": [18773, 18774],
    "excluded": {
        18776: {
            "reason": "A100 - too slow to be worth a slot",
            "decided_on": "2026-08-16",
            "decided_by": "operator",
            "reversible_when": "we decide otherwise",
        }
    },
}


def test_an_exclusion_without_a_reason_is_refused():
    # Arrange: a reason that is only whitespace
    blank = "   "
    # Act / Assert: an unexplained exclusion reads as an oversight, so the next
    # reader probes the port, finds it healthy, and restores it
    # Assert
    with pytest.raises(ValueError, match="stated reason"):
        Exclusion(port=1, reason=blank)


def test_module_bakes_in_no_site_ports():
    # Arrange: the operator's ruling — the exclusion is a preference, so the
    # values belong in config. Any 5-digit literal here is a site fact leaking
    # back into the package.
    src = inspect.getsource(_policy)
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    # Act
    leaked = re.findall(r"\b18\d{3}\b", code)
    # Assert
    assert leaked == []


def test_a_configured_exclusion_is_not_admitted():
    # Arrange
    policy = policy_from_mapping(SAMPLE)
    # Act
    admitted = policy.admits(18776)
    # Assert
    assert admitted is False


def test_a_configured_exclusion_reports_its_reason():
    # Arrange
    policy = policy_from_mapping(SAMPLE)
    # Act
    why = policy.why_not(18776)
    # Assert
    assert "too slow" in why


def test_a_configured_exclusion_reports_who_decided_it():
    # Arrange: a preference needs an owner, since no measurement reverses one
    policy = policy_from_mapping(SAMPLE)
    # Act
    why = policy.why_not(18776)
    # Assert
    assert "operator" in why


def test_a_declared_member_is_admitted():
    # Arrange
    policy = policy_from_mapping(SAMPLE)
    # Act
    admitted = policy.admits(18773)
    # Assert
    assert admitted is True


def test_an_admitted_member_has_no_reason_against_it():
    # Arrange
    policy = policy_from_mapping(SAMPLE)
    # Act
    why = policy.why_not(18773)
    # Assert
    assert why == ""


def test_a_bare_string_is_accepted_as_the_reason():
    # Arrange: the short form, for when the reason is the whole story
    policy = policy_from_mapping({"expected": [1, 2], "excluded": {2: "too slow"}})
    # Act
    why = policy.why_not(2)
    # Assert
    assert why == "too slow"


def test_a_malformed_exclusion_raises_rather_than_being_skipped():
    # Arrange: a pool preference that silently drops the line it could not read
    # is how an unwanted card ends up back in rotation
    bad = {"expected": [1], "excluded": {1: ["not", "a", "mapping"]}}
    # Act / Assert
    # Assert
    with pytest.raises(ValueError, match="reason string or a"):
        policy_from_mapping(bad)


def test_verdict_reports_a_forbidden_member_that_is_pooled():
    # Arrange: the fault a liveness probe cannot see — present, serving, unwanted
    policy = policy_from_mapping(SAMPLE)
    # Act
    verdict = policy.verdict([18773, 18776, 19999])
    # Assert
    assert verdict["forbidden"] == [18776]


def test_verdict_reports_an_undeclared_member_separately():
    # Arrange: a config gap to fill, not a preference breach — different remedy
    policy = policy_from_mapping(SAMPLE)
    # Act
    verdict = policy.verdict([18773, 18776, 19999])
    # Assert
    assert verdict["undeclared"] == [19999]


def test_verdict_reports_a_declared_member_that_is_absent():
    # Arrange: silent lost capacity is the harder direction to notice
    policy = policy_from_mapping(SAMPLE)
    # Act
    verdict = policy.verdict([18773])
    # Assert
    assert 18774 in verdict["missing"]


def test_verdict_does_not_report_an_excluded_member_as_missing():
    # Arrange: otherwise the alarm fires every cycle and stops being read
    policy = policy_from_mapping(SAMPLE)
    # Act
    verdict = policy.verdict([18773])
    # Assert
    assert 18776 not in verdict["missing"]


def test_policy_performs_no_network_io():
    # Arrange: if preference grows a probe, the two questions collapse into one
    # and an unwanted card becomes invisible the moment it is healthy
    src = inspect.getsource(_policy)
    forbidden = ("import socket", "import requests", "urllib.request", "subprocess")
    # Act
    offenders = [name for name in forbidden if name in src]
    # Assert
    assert offenders == []


def test_an_absent_config_yields_an_empty_policy(tmp_path):
    # Arrange
    missing = tmp_path / "nope.yaml"
    # Act
    policy = load_policy(missing)
    # Assert
    assert policy == UpstreamPolicy()


def test_an_empty_policy_treats_a_pooled_member_as_undeclared():
    # Arrange: "nothing is declared" must stay visible rather than read as
    # approval of whatever happens to be in the pool
    policy = UpstreamPolicy()
    # Act
    verdict = policy.verdict([18773])
    # Assert
    assert verdict["undeclared"] == [18773]


def test_a_config_file_is_read_from_the_hoist_pool_section(tmp_path):
    # Arrange
    cfg = tmp_path / "config.yaml"
    cfg.write_text("hoist_pool:\n  expected: [1, 2]\n  excluded:\n    2: too slow\n")
    # Act
    policy = load_policy(cfg)
    # Assert
    assert policy.admits(2) is False


def test_a_config_without_the_section_yields_an_empty_policy(tmp_path):
    # Arrange
    cfg = tmp_path / "config.yaml"
    cfg.write_text("hpc:\n  defaults:\n    cpus: 4\n")
    # Act
    policy = load_policy(cfg)
    # Assert
    assert policy.expected == ()
