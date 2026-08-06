"""Immutable contracts for the unified Agent Runtime.

The runtime deliberately has no lifecycle aggregate of its own.  A run is the
projection of an Authority Operation, its real Attempt/Lease/Fence, a frozen
work order and execution binding, PEP evidence, and the accepting Domain
Authority's records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any


_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELEASE_SHA = re.compile(r"^[0-9a-f]{40,64}$")


class AgentRunStatus(StrEnum):
    """Truthful presentation state derived from Command Kernel facts."""

    ADMITTED = "ADMITTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    WAITING_EXTERNAL_RESULT = "WAITING_EXTERNAL_RESULT"
    WAITING_GATE = "WAITING_GATE"
    WAITING_CHILDREN = "WAITING_CHILDREN"
    RETRYABLE = "RETRYABLE"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    COMPENSATING = "COMPENSATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"


class AgentDefinitionActivationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class AgentExecutionEmbedding(StrEnum):
    """Evidence about where the Agent turn is embedded, not lifecycle state."""

    EMBEDDED_DOMAIN_ATTEMPT = "EMBEDDED_DOMAIN_ATTEMPT"
    STANDALONE_CANDIDATE_OPERATION = "STANDALONE_CANDIDATE_OPERATION"


class AgentSchedulingAuthority(StrEnum):
    CHAPTER_AUTHORITY = "CHAPTER_AUTHORITY"
    AGENT_RUNTIME_AUTHORITY = "AGENT_RUNTIME_AUTHORITY"


class AgentDomainCommitStatus(StrEnum):
    """Query-only status derived from Candidate, Decision, and Commit facts."""

    NOT_REQUESTED = "NOT_REQUESTED"
    DOMAIN_DECISION_PENDING = "DOMAIN_DECISION_PENDING"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REJECTED = "REJECTED"
    DOMAIN_COMMITTED = "DOMAIN_COMMITTED"


@dataclass(frozen=True, slots=True)
class AgentCapabilityExecutionMapping:
    """One-to-one mapping to the existing PEP Capability Registry."""

    capability_id: str
    capability_version: int
    execution_capability_id: str
    execution_capability_hash: str
    created_by_operation_id: str

    def __post_init__(self) -> None:
        if (
            self.capability_version <= 0
            or not self.capability_id.strip()
            or not self.execution_capability_id.strip()
            or not self.created_by_operation_id.strip()
        ):
            raise ValueError("AgentCapabilityExecutionMapping is incomplete")
        _require_hashes(execution_capability_hash=self.execution_capability_hash)

    @property
    def mapping_hash(self) -> str:
        return _hash(
            {
                "capability_id": self.capability_id,
                "capability_version": self.capability_version,
                "execution_capability_id": self.execution_capability_id,
                "execution_capability_hash": self.execution_capability_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class AgentDefinitionRuntimeContract:
    """Content-addressed production extension of an AgentDefinition version."""

    agent_id: str
    definition_version: int
    capability_pack_ref: str
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_policy_ref: str
    tool_policy_hash: str
    context_policy_ref: str
    context_policy_hash: str
    definition_source: str
    created_by_operation_id: str

    def __post_init__(self) -> None:
        required = (
            self.agent_id,
            self.capability_pack_ref,
            self.prompt_bundle_ref,
            self.skill_bundle_ref,
            self.tool_policy_ref,
            self.context_policy_ref,
            self.definition_source,
            self.created_by_operation_id,
        )
        if self.definition_version <= 0 or any(not item.strip() for item in required):
            raise ValueError("AgentDefinitionRuntimeContract is incomplete")
        _require_hashes(
            prompt_bundle_hash=self.prompt_bundle_hash,
            skill_bundle_hash=self.skill_bundle_hash,
            tool_policy_hash=self.tool_policy_hash,
            context_policy_hash=self.context_policy_hash,
        )
        if self.definition_source not in {
            "POSTGRES_AUTHORITY",
            "BOOTSTRAP_ADAPTER",
            "LEGACY_MIGRATION",
        }:
            raise ValueError("Agent Definition source is invalid")

    @property
    def runtime_contract_hash(self) -> str:
        payload = asdict(self)
        payload.pop("created_by_operation_id")
        return _hash(payload)


@dataclass(frozen=True, slots=True)
class AgentDefinitionActivation:
    agent_id: str
    definition_version: int
    status: AgentDefinitionActivationStatus
    activation_version: int
    reason: str
    activated_by: str
    activated_by_operation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", AgentDefinitionActivationStatus(self.status)
        )
        if (
            self.definition_version <= 0
            or self.activation_version <= 0
            or any(
                not value.strip()
                for value in (
                    self.agent_id,
                    self.reason,
                    self.activated_by,
                    self.activated_by_operation_id,
                )
            )
        ):
            raise ValueError("AgentDefinitionActivation is incomplete")


_OPERATION_STATUS_MAP = {
    "ADMITTED": AgentRunStatus.ADMITTED,
    "WAITING_APPROVAL": AgentRunStatus.WAITING_APPROVAL,
    "READY": AgentRunStatus.QUEUED,
    "EXECUTING": AgentRunStatus.RUNNING,
    "WAITING_CHILDREN": AgentRunStatus.WAITING_CHILDREN,
    "WAITING_EXTERNAL_RESULT": AgentRunStatus.WAITING_EXTERNAL_RESULT,
    "WAITING_GATE": AgentRunStatus.WAITING_GATE,
    "FAILED_RETRYABLE": AgentRunStatus.RETRYABLE,
    "FAILED_FINAL": AgentRunStatus.FAILED,
    "CANCELLATION_REQUESTED": AgentRunStatus.CANCELLATION_REQUESTED,
    "RECONCILIATION_REQUIRED": AgentRunStatus.RECONCILIATION_REQUIRED,
    "COMPENSATION_REQUIRED": AgentRunStatus.COMPENSATING,
    "COMPENSATING": AgentRunStatus.COMPENSATING,
    "COMPENSATED": AgentRunStatus.FAILED,
    "COMPENSATION_FAILED": AgentRunStatus.FAILED,
    "SUCCEEDED": AgentRunStatus.SUCCEEDED,
    "CANCELLED": AgentRunStatus.CANCELLED,
    "DEAD_LETTER": AgentRunStatus.DEAD_LETTER,
}

_ATTEMPT_STATUS_MAP = {
    "CREATED": AgentRunStatus.ADMITTED,
    "QUEUED": AgentRunStatus.QUEUED,
    "LEASED": AgentRunStatus.LEASED,
    "RUNNING": AgentRunStatus.RUNNING,
    "CHECKPOINTED": AgentRunStatus.CHECKPOINTED,
    "RESULT_SUBMITTED": AgentRunStatus.WAITING_GATE,
    "SUCCEEDED": AgentRunStatus.SUCCEEDED,
    "FAILED_RETRYABLE": AgentRunStatus.RETRYABLE,
    "FAILED_FINAL": AgentRunStatus.FAILED,
    "TIMED_OUT": AgentRunStatus.RETRYABLE,
    "LEASE_LOST": AgentRunStatus.RETRYABLE,
    "SUPERSEDED": AgentRunStatus.CANCELLED,
    "LATE_RESULT_REJECTED": AgentRunStatus.RECONCILIATION_REQUIRED,
    "CANCELLED": AgentRunStatus.CANCELLED,
}


def derive_agent_run_status(
    *,
    operation_status: str,
    attempt_status: str = "",
    lease_status: str = "",
    external_effect_status: str = "",
) -> AgentRunStatus:
    """Derive an Agent Run status without persisting a duplicate lifecycle."""

    operation = str(operation_status).strip().upper()
    attempt = str(attempt_status).strip().upper()
    lease = str(lease_status).strip().upper()
    effect = str(external_effect_status).strip().upper()
    if operation not in _OPERATION_STATUS_MAP:
        raise ValueError(f"unknown Authority Operation status: {operation_status}")
    if attempt and attempt not in _ATTEMPT_STATUS_MAP:
        raise ValueError(f"unknown Authority Attempt status: {attempt_status}")

    if effect in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
        return AgentRunStatus.RECONCILIATION_REQUIRED
    if (
        operation == "EXECUTING"
        and attempt in {"LEASED", "RUNNING", "CHECKPOINTED"}
        and lease in {"EXPIRED", "RELEASED", "CANCELLED"}
    ):
        return AgentRunStatus.RECONCILIATION_REQUIRED
    if operation in {
        "SUCCEEDED",
        "CANCELLED",
        "FAILED_FINAL",
        "DEAD_LETTER",
        "RECONCILIATION_REQUIRED",
        "COMPENSATION_REQUIRED",
        "COMPENSATING",
        "COMPENSATED",
        "COMPENSATION_FAILED",
        "CANCELLATION_REQUESTED",
        "WAITING_EXTERNAL_RESULT",
        "WAITING_APPROVAL",
        "WAITING_CHILDREN",
        "WAITING_GATE",
        "FAILED_RETRYABLE",
    }:
        return _OPERATION_STATUS_MAP[operation]
    if attempt:
        return _ATTEMPT_STATUS_MAP[attempt]
    return _OPERATION_STATUS_MAP[operation]


@dataclass(frozen=True, slots=True)
class ChapterNodeExecutionBinding:
    """Versioned Authority binding from a Chapter node to a candidate Agent."""

    binding_id: str
    binding_version: int
    workflow_definition_ref: str
    workflow_node_id: str
    operation_definition_ref: str
    operation_definition_hash: str
    agent_definition_ref: str
    agent_definition_hash: str
    capability_ref: str
    capability_hash: str
    execution_capability_id: str
    capability_pack_ref: str
    capability_pack_compilation_hash: str
    input_contract_ref: str
    output_contract_ref: str
    domain_acceptance_policy_ref: str
    commit_authority: str
    status: str
    release_sha: str
    created_by_operation_id: str

    def __post_init__(self) -> None:
        required = (
            self.binding_id,
            self.workflow_definition_ref,
            self.workflow_node_id,
            self.operation_definition_ref,
            self.agent_definition_ref,
            self.capability_ref,
            self.execution_capability_id,
            self.capability_pack_ref,
            self.input_contract_ref,
            self.output_contract_ref,
            self.domain_acceptance_policy_ref,
            self.commit_authority,
            self.status,
            self.created_by_operation_id,
        )
        if self.binding_version <= 0 or any(not item.strip() for item in required):
            raise ValueError("ChapterNodeExecutionBinding is incomplete")
        _require_hashes(
            operation_definition_hash=self.operation_definition_hash,
            agent_definition_hash=self.agent_definition_hash,
            capability_hash=self.capability_hash,
            capability_pack_compilation_hash=(
                self.capability_pack_compilation_hash
            ),
        )
        _require_release_sha(self.release_sha)
        if self.status not in {"CANDIDATE", "ACTIVE", "RETIRED"}:
            raise ValueError("ChapterNodeExecutionBinding status is invalid")
        if not self.commit_authority.endswith("_AUTHORITY"):
            raise ValueError("Agent candidate commit must remain with a Domain Authority")

    @property
    def binding_hash(self) -> str:
        return _hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentRuntimeBinding:
    """Frozen execution evidence bound to a real Authority Attempt and fence."""

    binding_id: str
    project_id: str
    workspace_id: str
    book_id: str
    workflow_definition_ref: str
    workflow_node_id: str
    operation_definition_ref: str
    operation_definition_hash: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    work_order_id: str
    agent_id: str
    agent_definition_version: int
    agent_definition_hash: str
    capability_id: str
    capability_version: int
    capability_hash: str
    execution_capability_id: str
    chapter_node_binding_ref: str
    capability_pack_ref: str
    capability_pack_compilation_hash: str
    context_bundle_asset_version_id: str
    context_bundle_hash: str
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_policy_ref: str
    tool_policy_hash: str
    tool_permission_snapshot_ref: str
    tool_permission_snapshot_hash: str
    context_policy_ref: str
    context_policy_hash: str
    route_snapshot_ref: str
    route_snapshot_hash: str
    input_manifest_ref: str
    input_manifest_hash: str
    budget_policy_ref: str
    timeout_policy_ref: str
    approval_policy_ref: str
    validation_policy_ref: str
    commit_policy_ref: str
    commit_authority: str
    release_sha: str
    capability_pack_deployment_id: str = ""
    capability_pack_activation_version: int = 0
    capability_pack_binding_set_id: str = ""
    capability_pack_binding_set_hash: str = ""
    capability_pack_scope_type: str = ""
    capability_pack_assignment_ref: str = ""
    capability_pack_attempt_snapshot_id: str = ""
    capability_pack_attempt_snapshot_hash: str = ""

    def __post_init__(self) -> None:
        pack_snapshot_fields = {
            "capability_pack_deployment_id",
            "capability_pack_activation_version",
            "capability_pack_binding_set_id",
            "capability_pack_binding_set_hash",
            "capability_pack_scope_type",
            "capability_pack_assignment_ref",
            "capability_pack_attempt_snapshot_id",
            "capability_pack_attempt_snapshot_hash",
        }
        pack_snapshot_present = any(
            bool(getattr(self, name)) for name in pack_snapshot_fields
        )
        if pack_snapshot_present and not all(
            bool(getattr(self, name)) for name in pack_snapshot_fields
        ):
            raise ValueError("Capability Pack runtime snapshot is incomplete")
        required = tuple(
            value
            for name, value in asdict(self).items()
            if name
            not in {
                "fencing_token",
                "agent_definition_version",
                "capability_version",
                *pack_snapshot_fields,
            }
            and not name.endswith("_hash")
        )
        if any(not str(item).strip() for item in required):
            raise ValueError("AgentRuntimeBinding is incomplete")
        if (
            self.fencing_token <= 0
            or self.agent_definition_version <= 0
            or self.capability_version <= 0
        ):
            raise ValueError("AgentRuntimeBinding Authority identities are invalid")
        _require_hashes(
            operation_definition_hash=self.operation_definition_hash,
            agent_definition_hash=self.agent_definition_hash,
            capability_hash=self.capability_hash,
            capability_pack_compilation_hash=(
                self.capability_pack_compilation_hash
            ),
            context_bundle_hash=self.context_bundle_hash,
            prompt_bundle_hash=self.prompt_bundle_hash,
            skill_bundle_hash=self.skill_bundle_hash,
            tool_policy_hash=self.tool_policy_hash,
            tool_permission_snapshot_hash=self.tool_permission_snapshot_hash,
            context_policy_hash=self.context_policy_hash,
            route_snapshot_hash=self.route_snapshot_hash,
            input_manifest_hash=self.input_manifest_hash,
            **(
                {
                    "capability_pack_binding_set_hash": (
                        self.capability_pack_binding_set_hash
                    ),
                    "capability_pack_attempt_snapshot_id": (
                        self.capability_pack_attempt_snapshot_id
                    ),
                    "capability_pack_attempt_snapshot_hash": (
                        self.capability_pack_attempt_snapshot_hash
                    ),
                }
                if pack_snapshot_present
                else {}
            ),
        )
        _require_release_sha(self.release_sha)
        if pack_snapshot_present:
            if self.capability_pack_activation_version <= 0:
                raise ValueError("Capability Pack activation version must be positive")
            if self.capability_pack_scope_type not in {
                "SYSTEM",
                "PROJECT",
                "WORKSPACE",
                "BOOK",
            }:
                raise ValueError("Capability Pack scope type is invalid")
        if not self.commit_authority.endswith("_AUTHORITY"):
            raise ValueError("Agent output must be committed by a Domain Authority")

    @property
    def binding_hash(self) -> str:
        return _hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_hashes(**values: str) -> None:
    invalid = [name for name, value in values.items() if not _CONTENT_HASH.fullmatch(value)]
    if invalid:
        raise ValueError("invalid or missing content hash: " + ", ".join(invalid))


def _require_release_sha(value: str) -> None:
    if not _RELEASE_SHA.fullmatch(value):
        raise ValueError("release_sha must be a full immutable Git SHA")


def _hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AgentDomainCommitStatus",
    "AgentExecutionEmbedding",
    "AgentSchedulingAuthority",
    "AgentCapabilityExecutionMapping",
    "AgentDefinitionActivation",
    "AgentDefinitionActivationStatus",
    "AgentDefinitionRuntimeContract",
    "AgentRunStatus",
    "AgentRuntimeBinding",
    "ChapterNodeExecutionBinding",
    "derive_agent_run_status",
]
