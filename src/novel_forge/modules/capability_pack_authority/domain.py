"""Immutable Capability Pack Authority contracts.

This module contains configuration/deployment facts only.  Command Kernel
Operation, Attempt, Lease, Fence, retry, compensation, and ExternalEffect
state remain owned by their existing authorities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping


_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELEASE_SHA = re.compile(r"^[0-9a-f]{40,64}$")


class ScopeType(StrEnum):
    SYSTEM = "SYSTEM"
    PROJECT = "PROJECT"
    WORKSPACE = "WORKSPACE"
    BOOK = "BOOK"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class DeploymentStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"


class RolloutStatus(StrEnum):
    OFF = "OFF"
    CANARY = "CANARY"
    PERCENTAGE = "PERCENTAGE"
    FULL = "FULL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"


class DriftClassification(StrEnum):
    CLEAN = "CLEAN"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    NEW_ADMISSION_BLOCKED = "NEW_ADMISSION_BLOCKED"
    ROLLBACK_RECOMMENDED = "ROLLBACK_RECOMMENDED"
    REVOKED = "REVOKED"


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def stable_rollout_bucket(rollout_id: str, subject_key: str) -> int:
    """Return an immutable 0..9999 canary bucket for one subject."""

    if not rollout_id.strip() or not subject_key.strip():
        raise ValueError("rollout_id and subject_key are required")
    digest = hashlib.sha256(
        f"{rollout_id}\x1f{subject_key}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


@dataclass(frozen=True, slots=True)
class CapabilityPackScope:
    scope_type: ScopeType
    project_id: str = ""
    workspace_id: str = ""
    book_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_type", ScopeType(self.scope_type))
        if self.scope_type is ScopeType.SYSTEM:
            if self.project_id or self.workspace_id or self.book_id:
                raise ValueError("SYSTEM scope cannot contain project identifiers")
        elif self.scope_type is ScopeType.PROJECT:
            if not self.project_id or self.workspace_id or self.book_id:
                raise ValueError("PROJECT scope requires only project_id")
        elif self.scope_type is ScopeType.WORKSPACE:
            if not self.project_id or not self.workspace_id or self.book_id:
                raise ValueError(
                    "WORKSPACE scope requires project_id and workspace_id"
                )
        elif (
            not self.project_id or not self.workspace_id or not self.book_id
        ):
            raise ValueError(
                "BOOK scope requires project_id, workspace_id, and book_id"
            )

    @property
    def scope_key(self) -> str:
        return canonical_hash(
            {
                "scope_type": self.scope_type.value,
                "project_id": self.project_id,
                "workspace_id": self.workspace_id,
                "book_id": self.book_id,
            }
        )

    @property
    def subject_key(self) -> str:
        if self.scope_type is ScopeType.SYSTEM:
            return "system"
        if self.scope_type is ScopeType.PROJECT:
            return self.project_id
        if self.scope_type is ScopeType.WORKSPACE:
            return f"{self.project_id}:{self.workspace_id}"
        return self.book_id


@dataclass(frozen=True, slots=True)
class CapabilityPackExecutionSnapshot:
    deployment_id: str
    activation_version: int
    selected_scope_type: ScopeType
    selection_reason: str
    pack_id: str
    pack_version: str
    manifest_hash: str
    compilation_id: str
    compilation_hash: str
    catalog_snapshot_hash: str
    binding_set_id: str
    binding_set_hash: str
    workflow_definition_ref: str
    workflow_node_id: str
    operation_definition_ref: str
    operation_definition_hash: str
    agent_definition_ref: str
    agent_definition_hash: str
    capability_ref: str
    capability_hash: str
    execution_capability_id: str
    execution_capability_hash: str
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_policy_ref: str
    tool_policy_hash: str
    context_policy_ref: str
    context_policy_hash: str
    evaluation_policy_ref: str
    evaluation_policy_hash: str
    route_policy_ref: str
    route_policy_hash: str
    approval_policy_ref: str
    approval_policy_hash: str
    budget_policy_ref: str
    budget_policy_hash: str
    input_contract_ref: str
    output_contract_ref: str
    domain_acceptance_policy_ref: str
    commit_authority: str
    release_sha: str
    rollout_id: str = ""
    assignment_ref: str = ""
    prompt_system_instruction_ref: str = ""
    prompt_system_instruction_hash: str = ""
    prompt_template_ref: str = ""
    prompt_template_hash: str = ""
    prompt_compiler_version: str = ""
    skill_ref: str = ""
    skill_version: str = ""
    skill_content_hash: str = ""
    context_policy_payload_json: str = ""
    tool_policy_payload_json: str = ""
    evaluation_policy_payload_json: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "selected_scope_type", ScopeType(self.selected_scope_type)
        )
        if self.activation_version <= 0:
            raise ValueError("activation_version must be positive")
        optional = {
            "rollout_id",
            "assignment_ref",
            "prompt_system_instruction_ref",
            "prompt_system_instruction_hash",
            "prompt_template_ref",
            "prompt_template_hash",
            "prompt_compiler_version",
            "skill_ref",
            "skill_version",
            "skill_content_hash",
            "context_policy_payload_json",
            "tool_policy_payload_json",
            "evaluation_policy_payload_json",
        }
        for name, value in asdict(self).items():
            if name in optional or name == "activation_version":
                continue
            if not str(value).strip():
                raise ValueError(f"{name} is required")
        hash_fields = (
            "manifest_hash",
            "compilation_hash",
            "catalog_snapshot_hash",
            "binding_set_hash",
            "operation_definition_hash",
            "agent_definition_hash",
            "capability_hash",
            "execution_capability_hash",
            "prompt_bundle_hash",
            "skill_bundle_hash",
            "tool_policy_hash",
            "context_policy_hash",
            "evaluation_policy_hash",
            "route_policy_hash",
            "approval_policy_hash",
            "budget_policy_hash",
        )
        for name in hash_fields:
            if not _CONTENT_HASH.fullmatch(str(getattr(self, name))):
                raise ValueError(f"{name} must be a SHA-256 content hash")
        for name in (
            "prompt_system_instruction_hash",
            "prompt_template_hash",
            "skill_content_hash",
        ):
            value = str(getattr(self, name))
            if value and not _CONTENT_HASH.fullmatch(value):
                raise ValueError(f"{name} must be a SHA-256 content hash")
        if not _RELEASE_SHA.fullmatch(self.release_sha):
            raise ValueError("release_sha must be a full immutable Git SHA")
        if not self.commit_authority.endswith("_AUTHORITY"):
            raise ValueError("commit_authority must remain a Domain Authority")

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["selected_scope_type"] = self.selected_scope_type.value
        return value


def require_content_hashes(values: Mapping[str, str]) -> None:
    invalid = [
        name for name, value in values.items() if not _CONTENT_HASH.fullmatch(value)
    ]
    if invalid:
        raise ValueError("invalid content hash: " + ", ".join(invalid))


__all__ = [
    "ApprovalDecision",
    "CapabilityPackExecutionSnapshot",
    "CapabilityPackScope",
    "DeploymentStatus",
    "DriftClassification",
    "RolloutStatus",
    "ScopeType",
    "canonical_hash",
    "canonical_json",
    "require_content_hashes",
    "stable_rollout_bucket",
]
