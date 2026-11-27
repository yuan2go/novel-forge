"""CONSTRAINT: parsing retains the original JSON object for canonical hashing; validation, not parsing, aggregates authoring errors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Any


CAPABILITY_PACK_SCHEMA_VERSION = "novelos.capability_pack.v1"


class PackStatus(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    DISABLED = "DISABLED"


class PackLifecycle(StrEnum):
    DESIGN = "DESIGN"
    VALIDATION = "VALIDATION"
    PRODUCTION = "PRODUCTION"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class PackRoleType(StrEnum):
    AGENT = "AGENT"
    WORKER = "WORKER"
    REVIEWER = "REVIEWER"
    JUDGE = "JUDGE"
    AUTHORITY = "AUTHORITY"
    COORDINATOR = "COORDINATOR"


class SkillBindingMode(StrEnum):
    STATIC = "STATIC"
    DYNAMIC_ALLOWED = "DYNAMIC_ALLOWED"


class SkillDriftPolicy(StrEnum):
    FAIL_CLOSED = "FAIL_CLOSED"
    REQUIRE_REVALIDATION = "REQUIRE_REVALIDATION"


class ToolRiskClass(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReleaseChannel(StrEnum):
    DEV = "DEV"
    VALIDATION = "VALIDATION"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _object(value: Any) -> Mapping[str, Any]:
    return _freeze_json(value) if isinstance(value, Mapping) else MappingProxyType({})


def _items(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _strings(value: Any) -> tuple[Any, ...]:
    # WHY: Preserve invalid elements for the structured Validator. Silently
    # filtering them would repair author input and could bypass fail-closed
    # capability, dependency, or source-isolation checks.
    return _items(value)


@dataclass(frozen=True, slots=True)
class PackIdentity:
    pack_id: Any
    name: Any
    domain: Any
    capability_type: Any
    version: Any
    owner: Any
    status: Any
    lifecycle: Any
    description: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PackIdentity":
        return cls(*(payload.get(name) for name in cls.__dataclass_fields__))


@dataclass(frozen=True, slots=True)
class PackCompatibility:
    novel_forge_min_version: Any
    novel_forge_max_version: Any
    protocol_min_version: Any
    protocol_max_version: Any
    required_capabilities: tuple[str, ...]
    required_schema_versions: tuple[str, ...]
    incompatible_packs: tuple[str, ...]
    compatible_runtime_profiles: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PackCompatibility":
        return cls(
            payload.get("novel_forge_min_version"),
            payload.get("novel_forge_max_version"),
            payload.get("protocol_min_version"),
            payload.get("protocol_max_version"),
            _strings(payload.get("required_capabilities")),
            _strings(payload.get("required_schema_versions")),
            _strings(payload.get("incompatible_packs")),
            _strings(payload.get("compatible_runtime_profiles")),
        )


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    role_type: Any
    role_name: Any
    responsibilities: tuple[str, ...]
    boundaries: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    upstream_packs: tuple[str, ...]
    downstream_packs: tuple[str, ...]
    authority_level: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RoleDefinition":
        return cls(
            payload.get("role_type"),
            payload.get("role_name"),
            _strings(payload.get("responsibilities")),
            _strings(payload.get("boundaries")),
            _strings(payload.get("forbidden_actions")),
            _strings(payload.get("upstream_packs")),
            _strings(payload.get("downstream_packs")),
            payload.get("authority_level"),
        )


@dataclass(frozen=True, slots=True)
class BoundSkill:
    skill_ref: Any
    version: Any
    content_hash: Any
    required: Any
    input_contract_ref: Any
    output_contract_ref: Any
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    depends_on: tuple[str, ...]
    max_invocations_per_run: Any
    drift_policy: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BoundSkill":
        return cls(
            payload.get("skill_ref"),
            payload.get("version"),
            payload.get("content_hash"),
            payload.get("required"),
            payload.get("input_contract_ref"),
            payload.get("output_contract_ref"),
            _strings(payload.get("preconditions")),
            _strings(payload.get("postconditions")),
            _strings(payload.get("depends_on")),
            payload.get("max_invocations_per_run"),
            payload.get("drift_policy"),
        )


@dataclass(frozen=True, slots=True)
class SkillBinding:
    mode: Any
    selection_policy_ref: Any
    skills: tuple[BoundSkill, ...]
    anti_drift: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SkillBinding":
        return cls(
            payload.get("mode"),
            payload.get("selection_policy_ref"),
            tuple(
                BoundSkill.from_dict(_object(item))
                for item in _items(payload.get("skills"))
            ),
            _object(payload.get("anti_drift")),
        )


@dataclass(frozen=True, slots=True)
class PromptBinding:
    prompt_bundle_type: Any
    system_instruction_ref: Any
    system_instruction_version: Any
    system_instruction_hash: Any
    template_ref: Any
    template_version: Any
    template_hash: Any
    compiler_version: Any
    input_schema_ref: Any
    output_schema_ref: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromptBinding":
        return cls(*(payload.get(name) for name in cls.__dataclass_fields__))


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: Any
    retryable_errors: tuple[str, ...]
    dead_letter_on_exhausted: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RetryPolicy":
        return cls(
            payload.get("max_attempts"),
            _strings(payload.get("retryable_errors")),
            payload.get("dead_letter_on_exhausted"),
        )


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    node_id: Any
    operation_name: Any
    operation_definition_ref: Any
    operation_definition_hash: Any
    handler_key: Any
    stage: Any
    capability_id: Any
    agent_definition_ref: Any
    input_asset_types: tuple[str, ...]
    output_asset_types: tuple[str, ...]
    depends_on: tuple[str, ...]
    retry_policy: RetryPolicy
    timeout_policy_ref: Any
    approval: Mapping[str, Any]
    compensation: Mapping[str, Any]
    commit_authority: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowNode":
        return cls(
            payload.get("node_id"),
            payload.get("operation_name"),
            payload.get("operation_definition_ref"),
            payload.get("operation_definition_hash"),
            payload.get("handler_key"),
            payload.get("stage"),
            payload.get("capability_id"),
            payload.get("agent_definition_ref"),
            _strings(payload.get("input_asset_types")),
            _strings(payload.get("output_asset_types")),
            _strings(payload.get("depends_on")),
            RetryPolicy.from_dict(_object(payload.get("retry_policy"))),
            payload.get("timeout_policy_ref"),
            _object(payload.get("approval")),
            _object(payload.get("compensation")),
            payload.get("commit_authority", "CHAPTER_AUTHORITY"),
        )


@dataclass(frozen=True, slots=True)
class WorkflowCompletion:
    required_terminal_nodes: tuple[str, ...]
    required_evidence: tuple[str, ...]
    required_output_asset_types: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowCompletion":
        return cls(
            _strings(payload.get("required_terminal_nodes")),
            _strings(payload.get("required_evidence")),
            _strings(payload.get("required_output_asset_types")),
        )


@dataclass(frozen=True, slots=True)
class WorkflowTemplate:
    workflow_id: Any
    workflow_version: Any
    execution_mode: Any
    idempotency_scope: Any
    nodes: tuple[WorkflowNode, ...]
    completion: WorkflowCompletion

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowTemplate":
        return cls(
            payload.get("workflow_id"),
            payload.get("workflow_version"),
            payload.get("execution_mode"),
            payload.get("idempotency_scope"),
            tuple(
                WorkflowNode.from_dict(_object(item))
                for item in _items(payload.get("nodes"))
            ),
            WorkflowCompletion.from_dict(_object(payload.get("completion"))),
        )


@dataclass(frozen=True, slots=True)
class ContextSources:
    policy_id: Any
    max_tokens: Any
    source_isolation: Any
    allowed_asset_types: tuple[str, ...]
    forbidden_asset_types: tuple[str, ...]
    required_version_refs: tuple[str, ...]
    priority: tuple[str, ...]
    freshness: Mapping[str, Any]
    longform_bindings: Mapping[str, Any]
    planning_task_token_budget: Any = None
    capacity_policy: str = ""
    context_substage_method: str = ""
    capacity_history_exact_chapters: Any = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextSources":
        return cls(
            payload.get("policy_id"),
            payload.get("max_tokens"),
            payload.get("source_isolation"),
            _strings(payload.get("allowed_asset_types")),
            _strings(payload.get("forbidden_asset_types")),
            _strings(payload.get("required_version_refs")),
            _strings(payload.get("priority")),
            _object(payload.get("freshness")),
            _object(payload.get("longform_bindings")),
            payload.get("planning_task_token_budget"),
            str(payload.get("capacity_policy") or ""),
            str(payload.get("context_substage_method") or ""),
            payload.get("capacity_history_exact_chapters"),
        )


@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_ref: Any
    permission: Any
    allowed_operations: tuple[str, ...]
    risk_class: Any
    approval_required: Any
    audit_required: Any
    budget_policy_ref: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolBinding":
        return cls(
            payload.get("tool_ref"),
            payload.get("permission"),
            _strings(payload.get("allowed_operations")),
            payload.get("risk_class"),
            payload.get("approval_required"),
            payload.get("audit_required"),
            payload.get("budget_policy_ref"),
        )


@dataclass(frozen=True, slots=True)
class ToolPermissions:
    policy_id: Any
    default: Any
    tools: tuple[ToolBinding, ...]
    database: Mapping[str, Any]
    files: Mapping[str, Any]
    external_models: Mapping[str, Any]
    retrieval: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolPermissions":
        return cls(
            payload.get("policy_id"),
            payload.get("default"),
            tuple(
                ToolBinding.from_dict(_object(item))
                for item in _items(payload.get("tools"))
            ),
            _object(payload.get("database")),
            _object(payload.get("files")),
            _object(payload.get("external_models")),
            _object(payload.get("retrieval")),
        )


@dataclass(frozen=True, slots=True)
class PackAssets:
    knowledge: Mapping[str, Any]
    rules: tuple[Mapping[str, Any], ...]
    templates: tuple[Mapping[str, Any], ...]
    source_policy: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PackAssets":
        return cls(
            _object(payload.get("knowledge")),
            tuple(_object(item) for item in _items(payload.get("rules"))),
            tuple(_object(item) for item in _items(payload.get("templates"))),
            _object(payload.get("source_policy")),
        )


@dataclass(frozen=True, slots=True)
class EvaluationGate:
    gate_id: Any
    judge_capability_id: Any
    blocking: Any
    threshold: Any
    required_evidence: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationGate":
        return cls(
            payload.get("gate_id"),
            payload.get("judge_capability_id"),
            payload.get("blocking"),
            payload.get("threshold"),
            _strings(payload.get("required_evidence")),
        )


@dataclass(frozen=True, slots=True)
class EvaluationDefinition:
    evaluation_id: Any
    required_gates: tuple[EvaluationGate, ...]
    metrics: tuple[Mapping[str, Any], ...]
    failure_policy: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationDefinition":
        return cls(
            payload.get("evaluation_id"),
            tuple(
                EvaluationGate.from_dict(_object(item))
                for item in _items(payload.get("required_gates"))
            ),
            tuple(_object(item) for item in _items(payload.get("metrics"))),
            _object(payload.get("failure_policy")),
        )


@dataclass(frozen=True, slots=True)
class RuntimeContract:
    input_protocol_ref: Any
    output_protocol_ref: Any
    error_protocol_ref: Any
    state_protocol_ref: Any
    event_protocol_ref: Any
    audit_protocol_ref: Any
    rollback_protocol_ref: Any
    commit_policy_ref: Any
    validation_policy_ref: Any
    execution: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeContract":
        return cls(
            *(payload.get(name) for name in tuple(cls.__dataclass_fields__)[:-1]),
            _object(payload.get("execution")),
        )


@dataclass(frozen=True, slots=True)
class GovernanceDefinition:
    release_channel: Any
    approval_policy_ref: Any
    versioning: Mapping[str, Any]
    rollout: Mapping[str, Any]
    rollback: Mapping[str, Any]
    cost_tracking: Mapping[str, Any]
    quality_tracking: Mapping[str, Any]
    deprecation: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GovernanceDefinition":
        return cls(
            payload.get("release_channel"),
            payload.get("approval_policy_ref"),
            *(
                _object(payload.get(name))
                for name in tuple(cls.__dataclass_fields__)[2:]
            ),
        )


@dataclass(frozen=True, slots=True)
class AuditDefinition:
    audit_level: Any
    record_operation_snapshot: Any
    record_pack_manifest_hash: Any
    record_input_manifest: Any
    record_route_snapshot: Any
    record_tool_calls: Any
    record_cost_receipts: Any
    record_evaluation_results: Any

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AuditDefinition":
        return cls(*(payload.get(name) for name in cls.__dataclass_fields__))


@dataclass(frozen=True, slots=True)
class CapabilityPackManifest:
    schema_version: Any
    identity: PackIdentity
    compatibility: PackCompatibility
    role: RoleDefinition
    skill_binding: SkillBinding
    prompt_binding: PromptBinding
    workflow_template: WorkflowTemplate
    context_sources: ContextSources
    tool_permissions: ToolPermissions
    assets: PackAssets
    evaluation: EvaluationDefinition
    runtime_contract: RuntimeContract
    governance: GovernanceDefinition
    audit: AuditDefinition
    ext: Mapping[str, Any]
    _source_payload: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CapabilityPackManifest":
        source = _freeze_json(payload)
        return cls(
            source.get("schema_version"),
            PackIdentity.from_dict(_object(source.get("identity"))),
            PackCompatibility.from_dict(_object(source.get("compatibility"))),
            RoleDefinition.from_dict(_object(source.get("role"))),
            SkillBinding.from_dict(_object(source.get("skill_binding"))),
            PromptBinding.from_dict(_object(source.get("prompt_binding"))),
            WorkflowTemplate.from_dict(_object(source.get("workflow_template"))),
            ContextSources.from_dict(_object(source.get("context_sources"))),
            ToolPermissions.from_dict(_object(source.get("tool_permissions"))),
            PackAssets.from_dict(_object(source.get("assets"))),
            EvaluationDefinition.from_dict(_object(source.get("evaluation"))),
            RuntimeContract.from_dict(_object(source.get("runtime_contract"))),
            GovernanceDefinition.from_dict(_object(source.get("governance"))),
            AuditDefinition.from_dict(_object(source.get("audit"))),
            _object(source.get("ext")),
            source,
        )

    def to_dict(self) -> dict[str, Any]:
        # WHY: JSON round-trip produces a detached standard-library-only object while
        # retaining the exact JSON value model used to compute the identity.
        return _plain_json(self._source_payload)

    @property
    def manifest_hash(self) -> str:
        encoded = canonical_json(self._source_payload).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        _plain_json(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "CAPABILITY_PACK_SCHEMA_VERSION",
    "AuditDefinition",
    "BoundSkill",
    "CapabilityPackManifest",
    "ContextSources",
    "EvaluationDefinition",
    "EvaluationGate",
    "GovernanceDefinition",
    "PackAssets",
    "PackCompatibility",
    "PackIdentity",
    "PackLifecycle",
    "PackRoleType",
    "PackStatus",
    "ReleaseChannel",
    "SkillBindingMode",
    "SkillDriftPolicy",
    "ToolRiskClass",
    "PromptBinding",
    "RoleDefinition",
    "SkillBinding",
    "ToolBinding",
    "ToolPermissions",
    "WorkflowNode",
    "WorkflowTemplate",
    "canonical_json",
]
