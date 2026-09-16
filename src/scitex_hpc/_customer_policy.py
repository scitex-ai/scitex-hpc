"""Typed, read-only customer SLURM policy validation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_COMPONENT = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?\Z"
)
_JOB_ID = re.compile(r"[0-9]+(?:_[0-9]+)?\Z")
_SAFE_ACCOUNTING_BACKENDS = frozenset({"accounting_storage/slurmdbd"})
_ACCOUNTING_FLOOR = frozenset({"associations", "limits", "qos", "safe"})
_TRES_FLOOR = frozenset({"cpu", "mem", "node"})


def _require_token(value: str, name: str) -> str:
    if not _TOKEN.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{name} must be an opaque SLURM identifier")
    return value


def _require_component(value: str, name: str) -> str:
    if not _COMPONENT.fullmatch(value):
        raise ValueError(f"{name} must be a named SLURM component")
    return value


class _PolicyModel(BaseModel):
    """Strict immutable Pydantic model shared by policy calculations."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
        revalidate_instances="always",
    )


class TresValue(_PolicyModel):
    """One deeply immutable allocated or expected TRES quantity."""

    name: str
    amount: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_token(value, "TRES name")


class CustomerPolicyRequirements(_PolicyModel):
    """Hub-authoritative customer identity and required SLURM controls."""

    expected_uid: int = Field(gt=0)
    expected_gid: int = Field(gt=0)
    managed_uid_min: int = Field(gt=0)
    managed_uid_max: int = Field(gt=0)
    expected_account: str
    expected_qos: str
    expected_user: str
    expected_cluster: str
    expected_partition: str
    expected_job_id: str
    expected_job_name: str
    expected_dispatch: Literal["srun", "sbatch"]
    expected_tres: tuple[TresValue, ...]
    allowed_partitions: tuple[str, ...]
    cgroup_version: Literal[1, 2]
    max_evidence_age_seconds: int = Field(default=120, gt=0, le=300)
    allowed_accounting_storage_types: tuple[str, ...] = (
        "accounting_storage/slurmdbd",
    )
    required_accounting_enforcement: tuple[str, ...] = (
        "associations",
        "limits",
        "qos",
        "safe",
    )
    required_task_plugins: tuple[str, ...] = ("task/cgroup",)
    required_proctrack_plugin: str = "proctrack/cgroup"
    required_tres: tuple[str, ...] = ("cpu", "mem", "node")

    @field_validator(
        "expected_account",
        "expected_qos",
        "expected_user",
        "expected_cluster",
        "expected_partition",
        "expected_job_name",
    )
    @classmethod
    def _validate_token(cls, value: str, info) -> str:
        return _require_token(value, info.field_name)

    @field_validator("expected_job_id")
    @classmethod
    def _validate_expected_job_id(cls, value: str) -> str:
        if not _JOB_ID.fullmatch(value):
            raise ValueError("expected_job_id must be a numeric SLURM allocation id")
        return value

    @field_validator("expected_tres")
    @classmethod
    def _validate_expected_tres(
        cls, values: tuple[TresValue, ...]
    ) -> tuple[TresValue, ...]:
        names = [item.name for item in values]
        if not names or len(names) != len(set(names)):
            raise ValueError("expected_tres must be non-empty and unique")
        return values

    @field_validator("required_proctrack_plugin")
    @classmethod
    def _validate_component(cls, value: str) -> str:
        return _require_component(value, "required_proctrack_plugin")

    @field_validator(
        "allowed_partitions",
        "allowed_accounting_storage_types",
        "required_accounting_enforcement",
        "required_task_plugins",
        "required_tres",
    )
    @classmethod
    def _validate_nonempty_tuple(cls, values: tuple[str, ...], info):
        if not values or len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must be non-empty and unique")
        component_fields = {
            "allowed_accounting_storage_types",
            "required_task_plugins",
        }
        checker = (
            _require_component
            if info.field_name in component_fields
            else _require_token
        )
        for value in values:
            checker(value, info.field_name)
        return values

    @model_validator(mode="after")
    def _enforce_security_floor(self):
        managed_range_ok = (
            self.managed_uid_min <= self.managed_uid_max
            and self.managed_uid_min <= self.expected_uid <= self.managed_uid_max
            and self.managed_uid_min <= self.expected_gid <= self.managed_uid_max
        )
        if not managed_range_ok:
            raise ValueError("identity is outside the managed UID/GID range")
        backends = set(self.allowed_accounting_storage_types)
        enforcement = set(self.required_accounting_enforcement)
        task_plugins = set(self.required_task_plugins)
        required_tres = set(self.required_tres)
        secure = (
            backends <= _SAFE_ACCOUNTING_BACKENDS
            and _ACCOUNTING_FLOOR <= enforcement
            and "task/cgroup" in task_plugins
            and self.required_proctrack_plugin == "proctrack/cgroup"
            and _TRES_FLOOR <= required_tres
            and self.expected_partition in self.allowed_partitions
            and _TRES_FLOOR <= {item.name for item in self.expected_tres}
        )
        if not secure:
            raise ValueError("requirements weaken the non-negotiable SLURM floor")
        return self


class AssociationPolicyEvidence(_PolicyModel):
    """Read-only sacctmgr association/QoS limits for one customer."""

    user_name: str
    cluster: str
    partition: str
    account: str
    qos: tuple[str, ...]
    max_jobs: int = Field(gt=0)
    max_submit_jobs: int = Field(gt=0)
    max_cpus: int = Field(gt=0)
    max_memory_bytes: int = Field(gt=0)
    max_walltime_seconds: int = Field(gt=0)

    @field_validator("user_name", "cluster", "partition", "account")
    @classmethod
    def _validate_identity_token(cls, value: str, info) -> str:
        return _require_token(value, info.field_name)

    @field_validator("qos")
    @classmethod
    def _validate_qos(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("qos must be non-empty and unique")
        for value in values:
            _require_token(value, "qos")
        return values


class QosPolicyEvidence(_PolicyModel):
    """Effective finite limits for the selected customer QoS."""

    name: str
    max_jobs_per_user: int = Field(gt=0)
    max_cpus_per_user: int = Field(gt=0)
    max_memory_bytes: int = Field(gt=0)
    max_walltime_seconds: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_token(value, "QoS name")


class JobAllocationEvidence(_PolicyModel):
    """Read-only squeue/sacct evidence for one active SLURM allocation."""

    source: Literal["squeue+sacct"]
    job_id: str
    job_name: str
    dispatch: Literal["srun", "sbatch"]
    state: Literal["RUNNING"]
    allocation_active: bool
    uid: int = Field(gt=0)
    gid: int = Field(gt=0)
    account: str
    qos: str
    partition: str
    tres: tuple[TresValue, ...]
    login_node_local_processes: int = Field(ge=0)

    @field_validator("job_id")
    @classmethod
    def _validate_job_id(cls, value: str) -> str:
        if not _JOB_ID.fullmatch(value):
            raise ValueError("job_id must be a numeric SLURM allocation id")
        return value

    @field_validator("job_name", "account", "qos", "partition")
    @classmethod
    def _validate_token(cls, value: str, info) -> str:
        return _require_token(value, info.field_name)

    @field_validator("tres")
    @classmethod
    def _validate_tres(
        cls, values: tuple[TresValue, ...]
    ) -> tuple[TresValue, ...]:
        names = [item.name for item in values]
        if not names or len(names) != len(set(names)):
            raise ValueError("TRES values must be non-empty and unique")
        return values


class CustomerPolicyEvidence(_PolicyModel):
    """Authoritative read-only SLURM configuration and allocation evidence."""

    observed_at: datetime
    config_source: Literal["scontrol+sacctmgr"]
    accounting_storage_type: str
    accounting_storage_enforce: tuple[str, ...]
    task_plugins: tuple[str, ...]
    proctrack_plugin: str
    cgroup_version: Literal[1, 2]
    association: AssociationPolicyEvidence
    qos_policy: QosPolicyEvidence
    allocation: JobAllocationEvidence

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value

    @field_validator("accounting_storage_type", "proctrack_plugin")
    @classmethod
    def _validate_component(cls, value: str, info) -> str:
        return _require_component(value, info.field_name)

    @field_validator("accounting_storage_enforce", "task_plugins")
    @classmethod
    def _validate_tokens(cls, values: tuple[str, ...], info) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must be non-empty and unique")
        checker = (
            _require_component
            if info.field_name == "task_plugins"
            else _require_token
        )
        for value in values:
            checker(value, info.field_name)
        return values


def validate_customer_policy(
    evidence: CustomerPolicyEvidence | object | None = None,
    requirements: CustomerPolicyRequirements | object | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a fail-closed verdict; never query or mutate SLURM itself."""
    if evidence is None:
        return {
            "schema_version": 1,
            "operation": "hpc.customer_policy.validate",
            "mutating": False,
            "ready": False,
            "checks": [],
            "blockers": ["runtime_evidence"],
        }
    if not isinstance(evidence, CustomerPolicyEvidence):
        return {
            "schema_version": 1,
            "operation": "hpc.customer_policy.validate",
            "mutating": False,
            "ready": False,
            "checks": [],
            "blockers": ["typed_runtime_evidence"],
        }
    if not isinstance(requirements, CustomerPolicyRequirements):
        return {
            "schema_version": 1,
            "operation": "hpc.customer_policy.validate",
            "mutating": False,
            "ready": False,
            "checks": [],
            "blockers": ["typed_policy_requirements"],
        }
    try:
        requirements = CustomerPolicyRequirements.model_validate(
            requirements.model_dump()
        )
    except (ValidationError, ValueError):
        return {
            "schema_version": 1,
            "operation": "hpc.customer_policy.validate",
            "mutating": False,
            "ready": False,
            "checks": [],
            "blockers": ["typed_policy_requirements"],
        }
    try:
        evidence = CustomerPolicyEvidence.model_validate(evidence.model_dump())
    except (ValidationError, ValueError):
        return {
            "schema_version": 1,
            "operation": "hpc.customer_policy.validate",
            "mutating": False,
            "ready": False,
            "checks": [],
            "blockers": ["typed_runtime_evidence"],
        }

    enforcement = set(evidence.accounting_storage_enforce)
    required_enforcement = set(requirements.required_accounting_enforcement)
    task_plugins = set(evidence.task_plugins)
    required_task_plugins = set(requirements.required_task_plugins)
    allocation = evidence.allocation
    association = evidence.association
    qos_policy = evidence.qos_policy
    clock = now or datetime.now(timezone.utc)
    clock_aware = clock.tzinfo is not None and clock.utcoffset() is not None
    age_seconds = (
        (clock - evidence.observed_at).total_seconds() if clock_aware else float("inf")
    )
    evidence_fresh = -5 <= age_seconds <= requirements.max_evidence_age_seconds
    expected_tres = {item.name: item.amount for item in requirements.expected_tres}
    observed_tres = {item.name: item.amount for item in allocation.tres}
    observed = (
        ("evidence_freshness", evidence_fresh),
        (
            "accounting_backend",
            evidence.accounting_storage_type
            in requirements.allowed_accounting_storage_types,
        ),
        ("accounting_enforcement", required_enforcement <= enforcement),
        ("task_cgroup", required_task_plugins <= task_plugins),
        (
            "proctrack_cgroup",
            evidence.proctrack_plugin == requirements.required_proctrack_plugin,
        ),
        ("cgroup_version", evidence.cgroup_version == requirements.cgroup_version),
        (
            "association_identity",
            association.user_name == requirements.expected_user
            and association.cluster == requirements.expected_cluster
            and association.partition == requirements.expected_partition
            and association.account == requirements.expected_account
            and requirements.expected_qos in association.qos,
        ),
        ("qos_limits", qos_policy.name == requirements.expected_qos),
        (
            "allocation_active",
            allocation.allocation_active is True and allocation.state == "RUNNING",
        ),
        (
            "allocation_identity",
            allocation.uid == requirements.expected_uid
            and allocation.gid == requirements.expected_gid
            and allocation.account == requirements.expected_account
            and allocation.qos == requirements.expected_qos,
        ),
        (
            "allocation_partition",
            allocation.partition == requirements.expected_partition
            and allocation.partition in requirements.allowed_partitions,
        ),
        (
            "allocation_tres",
            observed_tres == expected_tres,
        ),
        (
            "allocation_binding",
            allocation.job_id == requirements.expected_job_id
            and allocation.job_name == requirements.expected_job_name
            and allocation.dispatch == requirements.expected_dispatch,
        ),
        ("no_local_compute", allocation.login_node_local_processes == 0),
    )
    checks = [
        {"name": name, "ok": ok, "observed": ok, "expected": True}
        for name, ok in observed
    ]
    blockers = [name for name, ok in observed if not ok]
    blockers.append("trusted_runtime_collector")
    return {
        "schema_version": 1,
        "operation": "hpc.customer_policy.validate",
        "mutating": False,
        "ready": False,
        "checks": checks,
        "blockers": blockers,
    }
