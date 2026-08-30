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
            "agent_definition_ref",
            "agent_definition_hash",
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
        if bool(self.agent_definition_ref) != bool(self.agent_definition_hash):
            raise ValueError(
                "agent_definition_ref and agent_definition_hash must be supplied together"
            )
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
        if self.agent_definition_hash and not _CONTENT_HASH.fullmatch(
            self.agent_definition_hash
        ):
            raise ValueError("agent_definition_hash must be a SHA-256 content hash")
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


@dataclass(frozen=True, slots=True)
class CapabilityPackAttemptSnapshot:

    snapshot_id: str
    operation_id: str
    attempt_id: str
    execution_fencing_token: int
    snapshot_creation_fencing_token: int
    snapshot_hash: str
    trace_id: str
    span_id: str
    execution_snapshot: CapabilityPackExecutionSnapshot

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.snapshot_id,
                self.operation_id,
                self.attempt_id,
                self.trace_id,
                self.span_id,
            )
        ):
            raise ValueError("Capability Pack Attempt Snapshot identity is incomplete")
        if self.execution_fencing_token <= 0:
            raise ValueError("Attempt Snapshot execution fence must be positive")
        if self.snapshot_creation_fencing_token <= 0:
            raise ValueError("Attempt Snapshot creation fence must be positive")
        if not _CONTENT_HASH.fullmatch(self.snapshot_id):
            raise ValueError("Attempt Snapshot id must be content-addressed")
        if self.snapshot_hash != self.execution_snapshot.snapshot_hash:
            raise ValueError("Attempt Snapshot hash differs from frozen execution content")


@dataclass(frozen=True, slots=True)
class MaterializedCapabilityArtifact:

    kind: str
    ref: str
    version: str
    content_hash: str
    content_json: str
    source_identity: str

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.kind,
                self.ref,
                self.version,
                self.content_hash,
                self.content_json,
                self.source_identity,
            )
        ):
            raise ValueError("materialized Capability Artifact is incomplete")
        if not _CONTENT_HASH.fullmatch(self.content_hash):
            raise ValueError("materialized Capability Artifact hash is invalid")
        content = json.loads(self.content_json)
        if canonical_hash(content) != self.content_hash:
            raise ValueError("materialized Capability Artifact content hash drift")

    @property
    def content(self) -> Any:
        return json.loads(self.content_json)

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        value = {
            "kind": self.kind,
            "ref": self.ref,
            "version": self.version,
            "content_hash": self.content_hash,
            "source_identity": self.source_identity,
        }
        if include_content:
            value["content"] = self.content
        return value


@dataclass(frozen=True, slots=True)
class CapabilityPackArtifactMaterialization:

    pack_id: str
    pack_version: str
    manifest_hash: str
    artifact_catalog_hash: str
    system_instruction: MaterializedCapabilityArtifact
    prompt_template: MaterializedCapabilityArtifact
    skill: MaterializedCapabilityArtifact
    context_policy: MaterializedCapabilityArtifact
    tool_policy: MaterializedCapabilityArtifact
    input_schema: MaterializedCapabilityArtifact
    output_schema: MaterializedCapabilityArtifact
    required_knowledge: tuple[MaterializedCapabilityArtifact, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.pack_id,
                self.pack_version,
                self.manifest_hash,
                self.artifact_catalog_hash,
            )
        ):
            raise ValueError("Capability Pack materialization identity is incomplete")
        require_content_hashes(
            {
                "manifest_hash": self.manifest_hash,
                "artifact_catalog_hash": self.artifact_catalog_hash,
            }
        )

    @property
    def materialization_hash(self) -> str:
        return canonical_hash(self.to_dict(include_content=True))

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "manifest_hash": self.manifest_hash,
            "artifact_catalog_hash": self.artifact_catalog_hash,
            "system_instruction": self.system_instruction.to_dict(
                include_content=include_content
            ),
            "prompt_template": self.prompt_template.to_dict(
                include_content=include_content
            ),
            "skill": self.skill.to_dict(include_content=include_content),
            "context_policy": self.context_policy.to_dict(
                include_content=include_content
            ),
            "tool_policy": self.tool_policy.to_dict(include_content=include_content),
            "input_schema": self.input_schema.to_dict(
                include_content=include_content
            ),
            "output_schema": self.output_schema.to_dict(
                include_content=include_content
            ),
            "required_knowledge": [
                item.to_dict(include_content=include_content)
                for item in self.required_knowledge
            ],
        }

def require_content_hashes(values: Mapping[str, str]) -> None:
    invalid = [
        name for name, value in values.items() if not _CONTENT_HASH.fullmatch(value)
    ]
    if invalid:
        raise ValueError("invalid content hash: " + ", ".join(invalid))


__all__ = [
    "ApprovalDecision",
    "CapabilityPackAttemptSnapshot",
    "CapabilityPackArtifactMaterialization",
    "CapabilityPackExecutionSnapshot",
    "CapabilityPackScope",
    "DeploymentStatus",
    "DriftClassification",
    "RolloutStatus",
    "ScopeType",
    "MaterializedCapabilityArtifact",
    "canonical_hash",
    "canonical_json",
    "require_content_hashes",
    "stable_rollout_bucket",
]
