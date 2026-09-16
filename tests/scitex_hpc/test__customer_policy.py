"""Fail-closed customer SLURM policy contract tests."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scitex_hpc import (
    AssociationPolicyEvidence,
    CustomerPolicyEvidence,
    CustomerPolicyRequirements,
    JobAllocationEvidence,
    validate_customer_policy,
)


def test_policy_is_not_ready_without_authoritative_evidence():
    # Arrange
    expected = {
        "schema_version": 1,
        "operation": "hpc.customer_policy.validate",
        "mutating": False,
        "ready": False,
        "checks": [],
        "blockers": ["runtime_evidence"],
    }
    # Act
    report = validate_customer_policy()
    # Assert
    assert report == expected


def _requirements():
    return CustomerPolicyRequirements(
        expected_uid=20_001,
        expected_gid=20_001,
        expected_account="customer-beta",
        expected_qos="customer-interactive",
        managed_uid_min=20_000,
        managed_uid_max=59_999,
        allowed_partitions=("customer",),
        cgroup_version=2,
    )


def _evidence(*, uid=20_001, enforcement=None, local_processes=0, observed_at=None):
    return CustomerPolicyEvidence(
        observed_at=observed_at or datetime.now(UTC),
        config_source="scontrol+sacctmgr",
        accounting_storage_type="accounting_storage/slurmdbd",
        accounting_storage_enforce=enforcement
        or ("associations", "limits", "qos", "safe"),
        task_plugins=("task/cgroup",),
        proctrack_plugin="proctrack/cgroup",
        cgroup_version=2,
        association=AssociationPolicyEvidence(
            account="customer-beta",
            qos=("customer-interactive",),
            max_jobs=4,
            max_submit_jobs=8,
            max_cpus=16,
            max_memory_bytes=32 * 1024**3,
            max_walltime_seconds=8 * 60 * 60,
        ),
        allocation=JobAllocationEvidence(
            source="squeue+sacct",
            job_id="123456",
            dispatch="srun",
            state="RUNNING",
            allocation_active=True,
            uid=uid,
            gid=20_001,
            account="customer-beta",
            qos="customer-interactive",
            partition="customer",
            tres={"cpu": 4, "mem": 8 * 1024**3, "node": 1},
            login_node_local_processes=local_processes,
        ),
    )


def test_complete_typed_policy_evidence_is_ready():
    # Arrange
    evidence = _evidence()
    requirements = _requirements()
    # Act
    report = validate_customer_policy(evidence, requirements)
    # Assert
    assert (report["ready"], report["blockers"]) == (True, [])


def test_mapping_cannot_self_attest_policy_readiness():
    # Arrange
    evidence = {"ready": True, "command": "srun --pty bash"}
    # Act
    report = validate_customer_policy(evidence, _requirements())
    # Assert
    assert (report["ready"], report["blockers"]) == (
        False,
        ["typed_runtime_evidence"],
    )


def test_allocation_forbids_raw_command_fields():
    # Arrange
    payload = _evidence().allocation.model_dump()
    payload["argv"] = ["srun", "bash"]
    # Act
    # Assert
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        JobAllocationEvidence.model_validate(payload)


def test_missing_accounting_enforcement_fails_closed():
    # Arrange
    evidence = _evidence(enforcement=("associations", "limits"))
    # Act
    report = validate_customer_policy(evidence, _requirements())
    # Assert
    assert report["blockers"] == ["accounting_enforcement"]


def test_job_identity_mismatch_fails_closed():
    # Arrange
    evidence = _evidence(uid=20_002)
    # Act
    report = validate_customer_policy(evidence, _requirements())
    # Assert
    assert report["blockers"] == ["allocation_identity"]


def test_login_node_local_compute_fails_closed():
    # Arrange
    evidence = _evidence(local_processes=1)
    # Act
    report = validate_customer_policy(evidence, _requirements())
    # Assert
    assert report["blockers"] == ["no_local_compute"]


def test_policy_schema_forbids_extra_properties():
    # Arrange
    expected = False
    # Act
    additional = CustomerPolicyEvidence.model_json_schema()["additionalProperties"]
    # Assert
    assert additional is expected


def test_requirements_cannot_weaken_nonnegotiable_accounting_floor():
    # Arrange
    payload = _requirements().model_dump()
    payload["required_accounting_enforcement"] = ("associations",)
    # Act
    # Assert
    with pytest.raises(ValidationError, match="non-negotiable"):
        CustomerPolicyRequirements.model_validate(payload)


def test_requirements_reject_identity_outside_managed_range():
    # Arrange
    payload = _requirements().model_dump()
    payload["expected_uid"] = 1000
    # Act
    # Assert
    with pytest.raises(ValidationError, match="managed UID/GID range"):
        CustomerPolicyRequirements.model_validate(payload)


def test_stale_policy_evidence_fails_closed():
    # Arrange
    now = datetime(2026, 9, 16, 13, 30, tzinfo=UTC)
    evidence = _evidence(observed_at=now - timedelta(minutes=10))
    # Act
    report = validate_customer_policy(evidence, _requirements(), now=now)
    # Assert
    assert report["blockers"] == ["evidence_freshness"]
