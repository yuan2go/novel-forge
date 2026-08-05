"""Static, fail-closed Capability Pack P0 validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any

from novel_forge.modules.production_execution.capability_registry import (
    CapabilityRegistry,
    default_capability_registry,
)
from novel_forge.modules.production_execution.security import assert_no_inline_secrets
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
)

from .errors import CapabilityPackValidationIssue, CapabilityPackValidationReport
from .schema import (
    CAPABILITY_PACK_SCHEMA_VERSION,
    CapabilityPackManifest,
    PackLifecycle,
    PackRoleType,
    PackStatus,
    ReleaseChannel,
    SkillBindingMode,
    SkillDriftPolicy,
    ToolRiskClass,
)


_PACK_ID = re.compile(r"^[a-z][a-z0-9_.-]*$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_STATUSES = frozenset(item.value for item in PackStatus)
_LIFECYCLES = frozenset(item.value for item in PackLifecycle)
_ROLE_TYPES = frozenset(item.value for item in PackRoleType)
_SKILL_BINDING_MODES = frozenset(item.value for item in SkillBindingMode)
_SKILL_DRIFT_POLICIES = frozenset(item.value for item in SkillDriftPolicy)
_TOOL_RISK_CLASSES = frozenset(item.value for item in ToolRiskClass)
_RELEASE_CHANNELS = frozenset(item.value for item in ReleaseChannel)
_TOP_LEVEL_FIELDS = (
    "schema_version",
    "identity",
    "compatibility",
    "role",
    "skill_binding",
    "prompt_binding",
    "workflow_template",
    "context_sources",
    "tool_permissions",
    "assets",
    "evaluation",
    "runtime_contract",
    "governance",
    "audit",
    "ext",
)
_TOP_LEVEL_OBJECTS = _TOP_LEVEL_FIELDS[1:]
_EXTENSION_NAMESPACES = frozenset({"ui", "enterprise", "experiments", "vendor"})
_RAW_SOURCE_TYPES = frozenset({"raw_source_document", "raw_source_chunk"})
_TOOL_PERMISSIONS = frozenset({"READ", "WRITE", "EXECUTE", "QUERY"})
_SOURCE_ISOLATION_MODES = frozenset(
    {"ABSTRACT_ASSETS_ONLY", "FROZEN_ASSETS_ONLY", "RAW_ALLOWED_WITH_APPROVAL"}
)
_CAPABILITY_TYPES = frozenset({"production_workflow"})
_VOLATILE_IDENTITY_KEYS = frozenset(
    {
        "current_timestamp",
        "current_time",
        "created_at",
        "generated_at",
        "generated_uuid",
        "latest_alias_resolution_result",
        "run_id",
        "run_result",
        "runtime_result",
        "timestamp",
        "updated_at",
        "validated_at",
        "validation_run_id",
    }
)
_UUID_VALUE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LOCAL_ABSOLUTE_PATH = re.compile(
    r"^(?:/Users/|/home/|/tmp/|[A-Za-z]:[\\/]Users[\\/])"
)
_WORKFLOW_BINDINGS = {
    f"{node.definition_name}@{CHAPTER_MODEL_EFFECT_DEFINITION_VERSION}": {
        "operation_name": node.definition_name,
        "handler_key": node.handler_key,
        "stage": node.value,
        "output_asset_types": (node.asset_type,),
    }
    for node in ChapterNode
}


@dataclass(frozen=True, slots=True)
class _PackPolicyClass:
    generation: bool
    production: bool

    @classmethod
    def derive(cls, manifest: CapabilityPackManifest) -> "_PackPolicyClass":
        capability_type = manifest.identity.capability_type
        recognized = (
            isinstance(capability_type, str)
            and capability_type in _CAPABILITY_TYPES
        )
        generation = (
            capability_type == "production_workflow"
            or not recognized
        )
        production = (
            manifest.identity.lifecycle == "PRODUCTION"
            or manifest.governance.release_channel == "PRODUCTION"
        )
        return cls(generation=generation, production=production)


class _IssueCollector:
    def __init__(self) -> None:
        self.errors: list[CapabilityPackValidationIssue] = []
        self.warnings: list[CapabilityPackValidationIssue] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append(
            CapabilityPackValidationIssue(code, path, message, "ERROR")
        )

    def warning(self, code: str, path: str, message: str) -> None:
        self.warnings.append(
            CapabilityPackValidationIssue(code, path, message, "WARNING")
        )


def validate_capability_pack(
    manifest: CapabilityPackManifest,
    *,
    capability_registry: CapabilityRegistry | None = None,
) -> CapabilityPackValidationReport:
    registry = capability_registry or default_capability_registry()
    issues = _IssueCollector()
    resolved: set[str] = set()
    payload = manifest.to_dict()
    policy_class = _PackPolicyClass.derive(manifest)

    _validate_top_level(payload, manifest, issues)
    _validate_required_protocol_fields(payload, issues)
    _validate_protocol_types(payload, issues)
    _validate_identity(manifest, issues)
    _validate_compatibility(manifest, registry, resolved, issues)
    _validate_role(manifest, issues)
    _validate_skills(manifest, issues)
    _validate_prompt(manifest, issues)
    _validate_workflow(manifest, registry, resolved, issues)
    _validate_context(manifest, policy_class, issues)
    _validate_tools(manifest, policy_class, issues)
    _validate_assets(manifest, policy_class, issues)
    _validate_evaluation(manifest, registry, resolved, issues)
    _validate_runtime(manifest, policy_class, issues)
    _validate_governance_and_audit(manifest, issues)
    _validate_extensions(payload.get("ext"), issues)
    _validate_stable_identity_inputs(payload, issues)
    try:
        assert_no_inline_secrets(payload, label="CapabilityPackManifest")
    except ValueError as exc:
        issues.error(
            "CAPABILITY_PACK_INLINE_SECRET_FORBIDDEN", "$", str(exc)
        )

    return CapabilityPackValidationReport(
        ok=not issues.errors,
        pack_id=(manifest.identity.pack_id if isinstance(manifest.identity.pack_id, str) else ""),
        version=(manifest.identity.version if isinstance(manifest.identity.version, str) else ""),
        manifest_hash=manifest.manifest_hash,
        errors=tuple(issues.errors),
        warnings=tuple(issues.warnings),
        resolved_capabilities=tuple(sorted(resolved)),
    )


def _validate_top_level(
    payload: Mapping[str, Any],
    manifest: CapabilityPackManifest,
    issues: _IssueCollector,
) -> None:
    if manifest.schema_version != CAPABILITY_PACK_SCHEMA_VERSION:
        issues.error(
            "CAPABILITY_PACK_SCHEMA_VERSION_UNSUPPORTED",
            "$.schema_version",
            f"schema_version must be {CAPABILITY_PACK_SCHEMA_VERSION}",
        )
    for field in _TOP_LEVEL_FIELDS:
        if field not in payload:
            issues.error(
                "CAPABILITY_PACK_REQUIRED_FIELD_MISSING",
                f"$.{field}",
                "required top-level field is missing",
            )
    for field in sorted(set(payload) - set(_TOP_LEVEL_FIELDS)):
        issues.error(
            "CAPABILITY_PACK_PROTOCOL_INVALID",
            f"$.{field}",
            "unknown top-level fields must be placed under an allowed ext namespace",
        )
    for field in _TOP_LEVEL_OBJECTS:
        if field in payload and not isinstance(payload[field], dict):
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"$.{field}",
                "top-level section must be an object",
            )


def _validate_required_protocol_fields(
    payload: Mapping[str, Any], issues: _IssueCollector
) -> None:
    sections: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("identity", ("pack_id", "name", "domain", "capability_type", "version", "owner", "status", "lifecycle", "description")),
        ("compatibility", ("novel_forge_min_version", "novel_forge_max_version", "protocol_min_version", "protocol_max_version", "required_capabilities", "required_schema_versions", "incompatible_packs", "compatible_runtime_profiles")),
        ("role", ("role_type", "role_name", "responsibilities", "boundaries", "forbidden_actions", "upstream_packs", "downstream_packs", "authority_level")),
        ("skill_binding", ("mode", "skills", "anti_drift")),
        ("prompt_binding", ("prompt_bundle_type", "system_instruction_hash", "template_hash", "compiler_version", "input_schema_ref", "output_schema_ref")),
        ("workflow_template", ("workflow_id", "workflow_version", "execution_mode", "idempotency_scope", "nodes", "completion")),
        ("context_sources", ("policy_id", "max_tokens", "source_isolation", "allowed_asset_types", "forbidden_asset_types", "required_version_refs", "priority", "freshness", "longform_bindings")),
        ("tool_permissions", ("policy_id", "default", "tools", "database", "files", "external_models", "retrieval")),
        ("assets", ("knowledge", "rules", "templates", "source_policy")),
        ("evaluation", ("evaluation_id", "required_gates", "metrics", "failure_policy")),
        ("runtime_contract", ("input_protocol_ref", "output_protocol_ref", "error_protocol_ref", "state_protocol_ref", "event_protocol_ref", "audit_protocol_ref", "rollback_protocol_ref", "commit_policy_ref", "validation_policy_ref", "execution")),
        ("governance", ("release_channel", "approval_policy_ref", "versioning", "rollout", "rollback", "cost_tracking", "quality_tracking", "deprecation")),
        ("audit", ("audit_level", "record_operation_snapshot", "record_pack_manifest_hash", "record_input_manifest", "record_route_snapshot", "record_tool_calls", "record_cost_receipts", "record_evaluation_results")),
    )
    for section, required in sections:
        value = payload.get(section)
        if isinstance(value, dict):
            _require_keys(value, required, f"$.{section}", issues)

    skill_binding = payload.get("skill_binding")
    if isinstance(skill_binding, dict):
        for index, skill in enumerate(_array(skill_binding.get("skills"))):
            if isinstance(skill, dict):
                _require_keys(
                    skill,
                    ("skill_ref", "version", "content_hash", "required", "input_contract_ref", "output_contract_ref", "preconditions", "postconditions", "depends_on", "max_invocations_per_run", "drift_policy"),
                    f"$.skill_binding.skills[{index}]",
                    issues,
                )
    workflow = payload.get("workflow_template")
    if isinstance(workflow, dict):
        for index, node in enumerate(_array(workflow.get("nodes"))):
            if not isinstance(node, dict):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.workflow_template.nodes[{index}]", "workflow node must be an object")
                continue
            node_path = f"$.workflow_template.nodes[{index}]"
            _require_keys(node, ("node_id", "operation_name", "operation_definition_ref", "handler_key", "stage", "capability_id", "input_asset_types", "output_asset_types", "depends_on", "retry_policy", "timeout_policy_ref", "approval", "compensation"), node_path, issues)
            retry = node.get("retry_policy")
            if isinstance(retry, dict):
                _require_keys(retry, ("max_attempts", "retryable_errors", "dead_letter_on_exhausted"), f"{node_path}.retry_policy", issues)
        completion = workflow.get("completion")
        if isinstance(completion, dict):
            _require_keys(completion, ("required_terminal_nodes", "required_evidence", "required_output_asset_types"), "$.workflow_template.completion", issues)
    tool_permissions = payload.get("tool_permissions")
    if isinstance(tool_permissions, dict):
        for index, tool in enumerate(_array(tool_permissions.get("tools"))):
            if isinstance(tool, dict):
                _require_keys(tool, ("tool_ref", "permission", "allowed_operations", "risk_class", "approval_required", "audit_required", "budget_policy_ref"), f"$.tool_permissions.tools[{index}]", issues)
    evaluation = payload.get("evaluation")
    if isinstance(evaluation, dict):
        for index, gate in enumerate(_array(evaluation.get("required_gates"))):
            if isinstance(gate, dict):
                _require_keys(gate, ("gate_id", "judge_capability_id", "blocking", "threshold", "required_evidence"), f"$.evaluation.required_gates[{index}]", issues)


def _array(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _require_keys(
    value: Mapping[str, Any],
    required: tuple[str, ...],
    path: str,
    issues: _IssueCollector,
) -> None:
    for field in required:
        if field not in value:
            issues.error(
                "CAPABILITY_PACK_REQUIRED_FIELD_MISSING",
                f"{path}.{field}",
                "required protocol field is missing",
            )


def _validate_protocol_types(
    payload: Mapping[str, Any], issues: _IssueCollector
) -> None:
    array_fields = {
        "$.compatibility": ("required_capabilities", "required_schema_versions", "incompatible_packs", "compatible_runtime_profiles"),
        "$.role": ("responsibilities", "boundaries", "forbidden_actions", "upstream_packs", "downstream_packs"),
        "$.context_sources": ("allowed_asset_types", "forbidden_asset_types", "required_version_refs", "priority"),
        "$.assets": ("rules", "templates"),
        "$.evaluation": ("required_gates", "metrics"),
    }
    object_fields = {
        "$.skill_binding": ("anti_drift",),
        "$.workflow_template": ("completion",),
        "$.context_sources": ("freshness", "longform_bindings"),
        "$.tool_permissions": ("database", "files", "external_models", "retrieval"),
        "$.assets": ("knowledge", "source_policy"),
        "$.evaluation": ("failure_policy",),
        "$.runtime_contract": ("execution",),
        "$.governance": ("versioning", "rollout", "rollback", "cost_tracking", "quality_tracking", "deprecation"),
    }
    for path, fields in array_fields.items():
        section = payload.get(path.removeprefix("$."))
        if not isinstance(section, dict):
            continue
        for field in fields:
            if field in section and not isinstance(section[field], list):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"{path}.{field}", "field must be an array")
    for path, fields in object_fields.items():
        section = payload.get(path.removeprefix("$."))
        if not isinstance(section, dict):
            continue
        for field in fields:
            if field in section and not isinstance(section[field], dict):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"{path}.{field}", "field must be an object")
    for section_name, list_name in (("skill_binding", "skills"), ("workflow_template", "nodes"), ("tool_permissions", "tools")):
        section = payload.get(section_name)
        if isinstance(section, dict) and list_name in section and not isinstance(section[list_name], list):
            issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.{section_name}.{list_name}", "field must be an array")

    string_arrays = {
        "compatibility": ("required_capabilities", "required_schema_versions", "incompatible_packs", "compatible_runtime_profiles"),
        "role": ("responsibilities", "boundaries", "forbidden_actions", "upstream_packs", "downstream_packs"),
        "context_sources": ("allowed_asset_types", "forbidden_asset_types", "required_version_refs", "priority"),
    }
    for section_name, fields in string_arrays.items():
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for field in fields:
            value = section.get(field)
            if isinstance(value, list):
                _require_string_items(value, f"$.{section_name}.{field}", issues)

    skill_binding = payload.get("skill_binding")
    if isinstance(skill_binding, dict):
        for index, skill in enumerate(_array(skill_binding.get("skills"))):
            if not isinstance(skill, dict):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.skill_binding.skills[{index}]", "skill binding must be an object")
                continue
            for field in ("preconditions", "postconditions", "depends_on"):
                if field in skill and not isinstance(skill[field], list):
                    issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.skill_binding.skills[{index}].{field}", "field must be an array")
                elif isinstance(skill.get(field), list):
                    _require_string_items(skill[field], f"$.skill_binding.skills[{index}].{field}", issues)
            if "required" in skill and not isinstance(skill["required"], bool):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.skill_binding.skills[{index}].required", "required must be boolean")
    workflow = payload.get("workflow_template")
    if isinstance(workflow, dict):
        for index, node in enumerate(_array(workflow.get("nodes"))):
            if not isinstance(node, dict):
                continue
            for field in ("input_asset_types", "output_asset_types", "depends_on"):
                if field in node and not isinstance(node[field], list):
                    issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.workflow_template.nodes[{index}].{field}", "field must be an array")
                elif isinstance(node.get(field), list):
                    _require_string_items(node[field], f"$.workflow_template.nodes[{index}].{field}", issues)
            for field in ("retry_policy", "approval", "compensation"):
                if field in node and not isinstance(node[field], dict):
                    issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.workflow_template.nodes[{index}].{field}", "field must be an object")
            retry = node.get("retry_policy")
            if isinstance(retry, dict):
                _validate_string_array_value(retry, "retryable_errors", f"$.workflow_template.nodes[{index}].retry_policy", issues)
                _require_boolean_value(retry, "dead_letter_on_exhausted", f"$.workflow_template.nodes[{index}].retry_policy", issues)
            approval = node.get("approval")
            if isinstance(approval, dict):
                _require_boolean_value(approval, "required", f"$.workflow_template.nodes[{index}].approval", issues)
            compensation = node.get("compensation")
            if isinstance(compensation, dict):
                _require_boolean_value(compensation, "supported", f"$.workflow_template.nodes[{index}].compensation", issues)
        completion = workflow.get("completion")
        if isinstance(completion, dict):
            for field in ("required_terminal_nodes", "required_evidence", "required_output_asset_types"):
                _validate_string_array_value(completion, field, "$.workflow_template.completion", issues)

    tool_permissions = payload.get("tool_permissions")
    if isinstance(tool_permissions, dict):
        for index, tool in enumerate(_array(tool_permissions.get("tools"))):
            if not isinstance(tool, dict):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.tool_permissions.tools[{index}]", "tool binding must be an object")
                continue
            path = f"$.tool_permissions.tools[{index}]"
            _validate_string_array_value(tool, "allowed_operations", path, issues)
            _require_boolean_value(tool, "approval_required", path, issues)
            _require_boolean_value(tool, "audit_required", path, issues)
        for section_name in ("database", "files", "external_models", "retrieval"):
            section = tool_permissions.get(section_name)
            if not isinstance(section, dict):
                continue
            path = f"$.tool_permissions.{section_name}"
            for field in {
                "database": ("read_allowed", "write_allowed"),
                "files": ("read_allowed", "write_allowed"),
                "external_models": ("allowed",),
                "retrieval": ("allowed",),
            }[section_name]:
                _require_boolean_value(section, field, path, issues)
            for field in {
                "database": ("allowed_tables", "forbidden_tables"),
                "files": ("allowed_roots",),
                "external_models": (),
                "retrieval": (),
            }[section_name]:
                _validate_string_array_value(section, field, path, issues)

    evaluation = payload.get("evaluation")
    if isinstance(evaluation, dict):
        for index, gate in enumerate(_array(evaluation.get("required_gates"))):
            if not isinstance(gate, dict):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.evaluation.required_gates[{index}]", "evaluation gate must be an object")
                continue
            path = f"$.evaluation.required_gates[{index}]"
            _require_boolean_value(gate, "blocking", path, issues)
            threshold = gate.get("threshold")
            if "threshold" in gate and (not isinstance(threshold, (int, float)) or isinstance(threshold, bool)):
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"{path}.threshold", "threshold must be numeric")
            _validate_string_array_value(gate, "required_evidence", path, issues)
        failure_policy = evaluation.get("failure_policy")
        if isinstance(failure_policy, dict):
            for field in ("acceptable_failures", "retryable_failures", "terminal_failures"):
                _validate_string_array_value(failure_policy, field, "$.evaluation.failure_policy", issues)

    assets = payload.get("assets")
    if isinstance(assets, dict):
        knowledge = assets.get("knowledge")
        if isinstance(knowledge, dict):
            for field in ("required_packs", "allowed_usage_roles"):
                _validate_string_array_value(knowledge, field, "$.assets.knowledge", issues)
        source_policy = assets.get("source_policy")
        if isinstance(source_policy, dict):
            _validate_string_array_value(source_policy, "allowed_eligibility", "$.assets.source_policy", issues)
            for field in ("raw_source_expression_allowed", "requires_lineage"):
                _require_boolean_value(source_policy, field, "$.assets.source_policy", issues)

    runtime = payload.get("runtime_contract")
    if isinstance(runtime, dict) and isinstance(runtime.get("execution"), dict):
        for field in ("binds_authority_operation", "binds_attempt_fence", "external_effects_allowed", "synchronous_fixture_allowed"):
            _require_boolean_value(runtime["execution"], field, "$.runtime_contract.execution", issues)

    audit = payload.get("audit")
    if isinstance(audit, dict):
        for field in ("record_operation_snapshot", "record_pack_manifest_hash", "record_input_manifest", "record_route_snapshot", "record_tool_calls", "record_cost_receipts", "record_evaluation_results"):
            _require_boolean_value(audit, field, "$.audit", issues)


def _require_string_items(
    values: list[Any], path: str, issues: _IssueCollector
) -> None:
    for index, item in enumerate(values):
        if not isinstance(item, str):
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"{path}[{index}]",
                "array item must be a string",
            )


def _validate_string_array_value(
    mapping: Mapping[str, Any],
    field: str,
    path: str,
    issues: _IssueCollector,
) -> None:
    if field not in mapping:
        return
    value = mapping[field]
    if not isinstance(value, list):
        issues.error(
            "CAPABILITY_PACK_PROTOCOL_INVALID",
            f"{path}.{field}",
            "field must be an array",
        )
        return
    _require_string_items(value, f"{path}.{field}", issues)


def _require_boolean_value(
    mapping: Mapping[str, Any],
    field: str,
    path: str,
    issues: _IssueCollector,
) -> None:
    if field in mapping and not isinstance(mapping[field], bool):
        issues.error(
            "CAPABILITY_PACK_PROTOCOL_INVALID",
            f"{path}.{field}",
            "field must be boolean",
        )


def _validate_identity(
    manifest: CapabilityPackManifest, issues: _IssueCollector
) -> None:
    identity = manifest.identity
    required = {
        "pack_id": identity.pack_id,
        "name": identity.name,
        "domain": identity.domain,
        "capability_type": identity.capability_type,
        "version": identity.version,
        "owner": identity.owner,
        "status": identity.status,
        "lifecycle": identity.lifecycle,
        "description": identity.description,
    }
    for field, value in required.items():
        if not isinstance(value, str) or not value.strip():
            issues.error(
                "CAPABILITY_PACK_IDENTITY_INVALID",
                f"$.identity.{field}",
                "identity field must be a non-empty string",
            )
    if isinstance(identity.pack_id, str) and not _PACK_ID.fullmatch(identity.pack_id):
        issues.error(
            "CAPABILITY_PACK_IDENTITY_INVALID",
            "$.identity.pack_id",
            "pack_id does not match ^[a-z][a-z0-9_.-]*$",
        )
    if isinstance(identity.version, str) and not _SEMVER.fullmatch(identity.version):
        issues.error(
            "CAPABILITY_PACK_IDENTITY_INVALID",
            "$.identity.version",
            "version must be SemVer MAJOR.MINOR.PATCH",
        )
    if not isinstance(identity.status, str) or identity.status not in _STATUSES:
        issues.error(
            "CAPABILITY_PACK_IDENTITY_INVALID",
            "$.identity.status",
            "status is not supported",
        )
    if not isinstance(identity.lifecycle, str) or identity.lifecycle not in _LIFECYCLES:
        issues.error(
            "CAPABILITY_PACK_IDENTITY_INVALID",
            "$.identity.lifecycle",
            "lifecycle is not supported",
        )
    if (
        not isinstance(identity.capability_type, str)
        or identity.capability_type not in _CAPABILITY_TYPES
    ):
        issues.error(
            "CAPABILITY_PACK_IDENTITY_INVALID",
            "$.identity.capability_type",
            "capability_type is not supported by the P0 policy catalog",
        )


def _resolve_capability(
    capability_id: Any,
    *,
    path: str,
    code: str,
    registry: CapabilityRegistry,
    resolved: set[str],
    issues: _IssueCollector,
) -> None:
    if not isinstance(capability_id, str) or not capability_id:
        issues.error(code, path, "capability ID must be a non-empty string")
        return
    try:
        definition = registry.resolve(capability_id)
    except ValueError as exc:
        issues.error(code, path, str(exc))
    else:
        resolved.add(definition.capability_id.value)


def _validate_compatibility(
    manifest: CapabilityPackManifest,
    registry: CapabilityRegistry,
    resolved: set[str],
    issues: _IssueCollector,
) -> None:
    compatibility = manifest.compatibility
    for field, value in (
        ("novel_forge_min_version", compatibility.novel_forge_min_version),
        ("protocol_min_version", compatibility.protocol_min_version),
    ):
        if not isinstance(value, str) or not value.strip():
            issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.compatibility.{field}", f"{field} must be a non-empty string")
    for field, value in (
        ("novel_forge_max_version", compatibility.novel_forge_max_version),
        ("protocol_max_version", compatibility.protocol_max_version),
    ):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.compatibility.{field}", f"{field} must be null or a non-empty string")
    for index, capability_id in enumerate(compatibility.required_capabilities):
        _resolve_capability(
            capability_id,
            path=f"$.compatibility.required_capabilities[{index}]",
            code="CAPABILITY_PACK_CAPABILITY_UNKNOWN",
            registry=registry,
            resolved=resolved,
            issues=issues,
        )


def _validate_role(manifest: CapabilityPackManifest, issues: _IssueCollector) -> None:
    role = manifest.role
    if not isinstance(role.role_type, str) or role.role_type not in _ROLE_TYPES:
        issues.error(
            "CAPABILITY_PACK_ROLE_INVALID",
            "$.role.role_type",
            "role_type is not supported",
        )
    for field, value in (("role_name", role.role_name), ("authority_level", role.authority_level)):
        if not isinstance(value, str) or not value.strip():
            issues.error(
                "CAPABILITY_PACK_ROLE_INVALID",
                f"$.role.{field}",
                f"{field} must be a non-empty string",
            )


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def _validate_skills(manifest: CapabilityPackManifest, issues: _IssueCollector) -> None:
    binding = manifest.skill_binding
    refs = [skill.skill_ref for skill in binding.skills]
    known = {value for value in refs if isinstance(value, str) and value}
    seen: set[str] = set()
    if not isinstance(binding.mode, str) or binding.mode not in _SKILL_BINDING_MODES:
        issues.error(
            "CAPABILITY_PACK_SKILL_POLICY_INVALID",
            "$.skill_binding.mode",
            "skill binding mode is not supported",
        )
    for index, skill in enumerate(binding.skills):
        path = f"$.skill_binding.skills[{index}]"
        for field, value in (
            ("skill_ref", skill.skill_ref),
            ("version", skill.version),
            ("input_contract_ref", skill.input_contract_ref),
            ("output_contract_ref", skill.output_contract_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.error("CAPABILITY_PACK_SKILL_POLICY_INVALID", f"{path}.{field}", f"{field} must be a non-empty string")
        if not isinstance(skill.required, bool):
            issues.error("CAPABILITY_PACK_SKILL_POLICY_INVALID", f"{path}.required", "required must be boolean")
        if isinstance(skill.skill_ref, str) and skill.skill_ref in seen:
            issues.error(
                "CAPABILITY_PACK_SKILL_DUPLICATE",
                f"{path}.skill_ref",
                f"duplicate skill_ref: {skill.skill_ref}",
            )
        if isinstance(skill.skill_ref, str):
            seen.add(skill.skill_ref)
        if not _valid_hash(skill.content_hash):
            issues.error(
                "CAPABILITY_PACK_HASH_INVALID",
                f"{path}.content_hash",
                "skill content_hash must be sha256:<64 lowercase hex>",
            )
        if (
            not isinstance(skill.drift_policy, str)
            or skill.drift_policy not in _SKILL_DRIFT_POLICIES
        ):
            issues.error(
                "CAPABILITY_PACK_SKILL_POLICY_INVALID",
                f"{path}.drift_policy",
                "skill drift_policy is not supported",
            )
        if not isinstance(skill.max_invocations_per_run, int) or isinstance(
            skill.max_invocations_per_run, bool
        ) or skill.max_invocations_per_run <= 0:
            issues.error(
                "CAPABILITY_PACK_SKILL_POLICY_INVALID",
                f"{path}.max_invocations_per_run",
                "max_invocations_per_run must be a positive integer",
            )
        for dependency in skill.depends_on:
            if isinstance(dependency, str) and dependency not in known:
                issues.error(
                    "CAPABILITY_PACK_SKILL_DEPENDENCY_UNKNOWN",
                    f"{path}.depends_on",
                    f"unknown skill dependency: {dependency}",
                )
    if binding.mode == "DYNAMIC_ALLOWED" and not (
        isinstance(binding.selection_policy_ref, str)
        and binding.selection_policy_ref.strip()
    ):
        issues.error(
            "CAPABILITY_PACK_SKILL_POLICY_INVALID",
            "$.skill_binding.selection_policy_ref",
            "dynamic selection requires an explicit selection policy",
        )
    anti_drift = binding.anti_drift
    if anti_drift.get("unbound_skill_forbidden") is not True:
        issues.error(
            "CAPABILITY_PACK_SKILL_POLICY_INVALID",
            "$.skill_binding.anti_drift.unbound_skill_forbidden",
            "unbound runtime skill invocation must be forbidden",
        )


def _validate_prompt(manifest: CapabilityPackManifest, issues: _IssueCollector) -> None:
    prompt = manifest.prompt_binding
    for field, value in (
        ("prompt_bundle_type", prompt.prompt_bundle_type),
        ("compiler_version", prompt.compiler_version),
        ("input_schema_ref", prompt.input_schema_ref),
        ("output_schema_ref", prompt.output_schema_ref),
    ):
        if not isinstance(value, str) or not value.strip():
            issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.prompt_binding.{field}", f"{field} must be a non-empty string")
    for field, value in (
        ("system_instruction_hash", prompt.system_instruction_hash),
        ("template_hash", prompt.template_hash),
    ):
        if not _valid_hash(value):
            issues.error(
                "CAPABILITY_PACK_HASH_INVALID",
                f"$.prompt_binding.{field}",
                f"{field} must be sha256:<64 lowercase hex>",
            )


def _validate_workflow(
    manifest: CapabilityPackManifest,
    registry: CapabilityRegistry,
    resolved: set[str],
    issues: _IssueCollector,
) -> None:
    workflow = manifest.workflow_template
    for field, value in (
        ("workflow_id", workflow.workflow_id),
        ("execution_mode", workflow.execution_mode),
        ("idempotency_scope", workflow.idempotency_scope),
    ):
        if not isinstance(value, str) or not value.strip():
            issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.workflow_template.{field}", f"{field} must be a non-empty string")
    if not isinstance(workflow.workflow_version, str) or not _SEMVER.fullmatch(workflow.workflow_version):
        issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", "$.workflow_template.workflow_version", "workflow_version must be SemVer MAJOR.MINOR.PATCH")
    if not workflow.nodes:
        issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", "$.workflow_template.nodes", "workflow requires at least one node")
    node_ids = [node.node_id for node in workflow.nodes]
    known = {value for value in node_ids if isinstance(value, str) and value}
    seen: set[str] = set()
    graph: dict[str, tuple[str, ...]] = {}
    for index, node in enumerate(workflow.nodes):
        path = f"$.workflow_template.nodes[{index}]"
        for field, value in (
            ("node_id", node.node_id),
            ("operation_name", node.operation_name),
            ("operation_definition_ref", node.operation_definition_ref),
            ("handler_key", node.handler_key),
            ("stage", node.stage),
            ("capability_id", node.capability_id),
            ("timeout_policy_ref", node.timeout_policy_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"{path}.{field}", f"{field} must be a non-empty string")
        if isinstance(node.node_id, str) and node.node_id in seen:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_NODE_DUPLICATE",
                f"{path}.node_id",
                f"duplicate node_id: {node.node_id}",
            )
        if isinstance(node.node_id, str):
            seen.add(node.node_id)
            graph.setdefault(node.node_id, node.depends_on)
        _resolve_capability(
            node.capability_id,
            path=f"{path}.capability_id",
            code="CAPABILITY_PACK_CAPABILITY_UNKNOWN",
            registry=registry,
            resolved=resolved,
            issues=issues,
        )
        for dependency in node.depends_on:
            if isinstance(dependency, str) and dependency not in known:
                issues.error(
                    "CAPABILITY_PACK_WORKFLOW_DEPENDENCY_UNKNOWN",
                    f"{path}.depends_on",
                    f"unknown workflow dependency: {dependency}",
                )
        attempts = node.retry_policy.max_attempts
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts <= 0:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_RETRY_INVALID",
                f"{path}.retry_policy.max_attempts",
                "max_attempts must be a positive integer",
            )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (node.operation_name, node.operation_definition_ref, node.handler_key)
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                path,
                "workflow nodes require operation and handler bindings",
            )
        _validate_known_workflow_binding(node, path, issues)
    if _has_cycle(graph):
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_CYCLE",
            "$.workflow_template.nodes",
            "workflow dependency graph contains a cycle",
        )
    for index, terminal in enumerate(workflow.completion.required_terminal_nodes):
        if isinstance(terminal, str) and terminal not in known:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN",
                f"$.workflow_template.completion.required_terminal_nodes[{index}]",
                f"unknown completion terminal node: {terminal}",
            )
    if not workflow.completion.required_terminal_nodes:
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN",
            "$.workflow_template.completion.required_terminal_nodes",
            "at least one completion terminal node is required",
        )


def _has_cycle(graph: Mapping[str, tuple[str, ...]]) -> bool:
    # Deterministic Kahn traversal. Unknown edges are reported separately and
    # omitted here so a missing reference is not misreported as a cycle.
    indegree = {node: 0 for node in graph}
    outgoing = {node: [] for node in graph}
    for node in sorted(graph):
        for dependency in sorted(
            value for value in graph[node] if isinstance(value, str)
        ):
            if dependency in graph:
                indegree[node] += 1
                outgoing[dependency].append(node)
    ready = sorted(node for node, count in indegree.items() if count == 0)
    visited = 0
    while ready:
        node = ready.pop(0)
        visited += 1
        for child in sorted(outgoing[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    return visited != len(graph)


def _validate_known_workflow_binding(
    node: Any, path: str, issues: _IssueCollector
) -> None:
    binding = _WORKFLOW_BINDINGS.get(node.operation_definition_ref)
    if binding is None:
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_BINDING_UNKNOWN",
            f"{path}.operation_definition_ref",
            "operation definition is not in the P0 static binding allowlist",
        )
        return
    actual = {
        "operation_name": node.operation_name,
        "handler_key": node.handler_key,
        "stage": node.stage,
        "output_asset_types": node.output_asset_types,
    }
    for field, expected in binding.items():
        if actual[field] != expected:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                f"{path}.{field}",
                "workflow binding differs from the registered P0 Operation contract",
            )


def _validate_context(
    manifest: CapabilityPackManifest,
    policy_class: _PackPolicyClass,
    issues: _IssueCollector,
) -> None:
    context = manifest.context_sources
    if not isinstance(context.policy_id, str) or not context.policy_id.strip():
        issues.error("CAPABILITY_PACK_CONTEXT_POLICY_INVALID", "$.context_sources.policy_id", "policy_id must be a non-empty string")
    if (
        not isinstance(context.source_isolation, str)
        or context.source_isolation not in _SOURCE_ISOLATION_MODES
    ):
        issues.error("CAPABILITY_PACK_CONTEXT_POLICY_INVALID", "$.context_sources.source_isolation", "source_isolation is not supported")
    if not isinstance(context.max_tokens, int) or isinstance(context.max_tokens, bool) or context.max_tokens <= 0:
        issues.error(
            "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            "$.context_sources.max_tokens",
            "max_tokens must be a positive integer",
        )
    allowed = {value for value in context.allowed_asset_types if isinstance(value, str)}
    forbidden = {value for value in context.forbidden_asset_types if isinstance(value, str)}
    overlap = sorted(allowed & forbidden)
    if overlap:
        issues.error(
            "CAPABILITY_PACK_CONTEXT_ASSET_OVERLAP",
            "$.context_sources",
            "allowed and forbidden asset types overlap: " + ", ".join(overlap),
        )
    if context.freshness.get("reject_cross_project") is not True:
        issues.error(
            "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            "$.context_sources.freshness.reject_cross_project",
            "cross-project context must be rejected",
        )
    if policy_class.production and context.source_isolation == "RAW_ALLOWED_WITH_APPROVAL":
        issues.error(
            "CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN",
            "$.context_sources.source_isolation",
            "production packs cannot admit raw source context with approval",
        )
    if policy_class.generation:
        missing = sorted(_RAW_SOURCE_TYPES - forbidden)
        admitted = sorted(_RAW_SOURCE_TYPES & allowed)
        if missing or admitted:
            issues.error(
                "CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN",
                "$.context_sources",
                "generation packs must explicitly forbid raw_source_document and raw_source_chunk",
            )


def _validate_tools(
    manifest: CapabilityPackManifest,
    policy_class: _PackPolicyClass,
    issues: _IssueCollector,
) -> None:
    permissions = manifest.tool_permissions
    if permissions.default != "DENY":
        issues.error(
            "CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN",
            "$.tool_permissions.default",
            "tool policy default must be DENY",
        )
    for index, tool in enumerate(permissions.tools):
        path = f"$.tool_permissions.tools[{index}]"
        for field, value in (("tool_ref", tool.tool_ref), ("budget_policy_ref", tool.budget_policy_ref)):
            if not isinstance(value, str) or not value.strip():
                issues.error("CAPABILITY_PACK_TOOL_POLICY_INVALID", f"{path}.{field}", f"{field} must be a non-empty string")
        if not isinstance(tool.permission, str) or tool.permission not in _TOOL_PERMISSIONS:
            issues.error("CAPABILITY_PACK_TOOL_POLICY_INVALID", f"{path}.permission", "tool permission is not supported")
        if not tool.allowed_operations:
            issues.error("CAPABILITY_PACK_TOOL_POLICY_INVALID", f"{path}.allowed_operations", "tool requires at least one allowed operation")
        if not isinstance(tool.approval_required, bool):
            issues.error("CAPABILITY_PACK_TOOL_POLICY_INVALID", f"{path}.approval_required", "approval_required must be boolean")
        if not isinstance(tool.audit_required, bool):
            issues.error("CAPABILITY_PACK_TOOL_POLICY_INVALID", f"{path}.audit_required", "audit_required must be boolean")
        risk = tool.risk_class if isinstance(tool.risk_class, str) else ""
        if risk not in _TOOL_RISK_CLASSES:
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.risk_class",
                "tool risk_class is not supported",
            )
        if risk in {"HIGH", "CRITICAL"} and tool.audit_required is not True:
            issues.error(
                "CAPABILITY_PACK_HIGH_RISK_TOOL_AUDIT_REQUIRED",
                f"{path}.audit_required",
                f"{risk} tools require audit",
            )
        if risk == "CRITICAL" and tool.approval_required is not True:
            issues.error(
                "CAPABILITY_PACK_CRITICAL_TOOL_APPROVAL_REQUIRED",
                f"{path}.approval_required",
                "CRITICAL tools require approval in P0",
            )
    roots = permissions.files.get("allowed_roots")
    if isinstance(roots, (list, tuple)):
        for index, root in enumerate(roots):
            if not isinstance(root, str):
                issues.error(
                    "CAPABILITY_PACK_FILE_ROOT_INVALID",
                    f"$.tool_permissions.files.allowed_roots[{index}]",
                    "file root must be a string",
                )
                continue
            posix = PurePosixPath(root)
            windows = PureWindowsPath(root)
            if ".." in posix.parts or ".." in windows.parts:
                issues.error(
                    "CAPABILITY_PACK_FILE_ROOT_INVALID",
                    f"$.tool_permissions.files.allowed_roots[{index}]",
                    "file root cannot contain ..",
                )
            if policy_class.production and not (posix.is_absolute() or windows.is_absolute()):
                issues.error(
                    "CAPABILITY_PACK_FILE_ROOT_INVALID",
                    f"$.tool_permissions.files.allowed_roots[{index}]",
                    "production file roots must be absolute",
                )


def _validate_assets(
    manifest: CapabilityPackManifest,
    policy_class: _PackPolicyClass,
    issues: _IssueCollector,
) -> None:
    if not policy_class.generation:
        return
    source = manifest.assets.source_policy
    if source.get("raw_source_expression_allowed") is not False:
        issues.error(
            "CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN",
            "$.assets.source_policy.raw_source_expression_allowed",
            "generation packs cannot allow raw source expression",
        )
    if source.get("requires_lineage") is not True:
        issues.error(
            "CAPABILITY_PACK_SOURCE_LINEAGE_REQUIRED",
            "$.assets.source_policy.requires_lineage",
            "generation packs require source lineage",
        )


def _validate_evaluation(
    manifest: CapabilityPackManifest,
    registry: CapabilityRegistry,
    resolved: set[str],
    issues: _IssueCollector,
) -> None:
    if not isinstance(manifest.evaluation.evaluation_id, str) or not manifest.evaluation.evaluation_id.strip():
        issues.error("CAPABILITY_PACK_EVALUATION_INVALID", "$.evaluation.evaluation_id", "evaluation_id must be a non-empty string")
    if not manifest.evaluation.required_gates:
        issues.error("CAPABILITY_PACK_EVALUATION_INVALID", "$.evaluation.required_gates", "at least one evaluation gate is required")
    for index, gate in enumerate(manifest.evaluation.required_gates):
        path = f"$.evaluation.required_gates[{index}]"
        if not isinstance(gate.gate_id, str) or not gate.gate_id.strip():
            issues.error("CAPABILITY_PACK_EVALUATION_INVALID", f"{path}.gate_id", "gate_id must be a non-empty string")
        if not isinstance(gate.blocking, bool):
            issues.error("CAPABILITY_PACK_EVALUATION_INVALID", f"{path}.blocking", "blocking must be boolean")
        if not gate.required_evidence:
            issues.error("CAPABILITY_PACK_EVALUATION_INVALID", f"{path}.required_evidence", "evaluation gate requires evidence")
        _resolve_capability(
            gate.judge_capability_id,
            path=f"$.evaluation.required_gates[{index}].judge_capability_id",
            code="CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN",
            registry=registry,
            resolved=resolved,
            issues=issues,
        )


def _validate_runtime(
    manifest: CapabilityPackManifest,
    policy_class: _PackPolicyClass,
    issues: _IssueCollector,
) -> None:
    runtime = manifest.runtime_contract
    for field in (
        "input_protocol_ref", "output_protocol_ref", "error_protocol_ref",
        "state_protocol_ref", "event_protocol_ref", "audit_protocol_ref",
        "rollback_protocol_ref", "commit_policy_ref", "validation_policy_ref",
    ):
        value = getattr(runtime, field)
        if not isinstance(value, str) or not value.strip():
            issues.error("CAPABILITY_PACK_PROTOCOL_INVALID", f"$.runtime_contract.{field}", f"{field} must be a non-empty string")
    execution = manifest.runtime_contract.execution
    if (policy_class.generation or policy_class.production) and (
        execution.get("binds_authority_operation") is not True
        or execution.get("binds_attempt_fence") is not True
        or execution.get("synchronous_fixture_allowed") is not False
    ):
        issues.error(
            "CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED",
            "$.runtime_contract.execution",
            "generation/production packs require Authority Operation and Attempt Fence binding and prohibit synchronous fixtures",
        )


def _validate_governance_and_audit(
    manifest: CapabilityPackManifest, issues: _IssueCollector
) -> None:
    if (
        not isinstance(manifest.governance.release_channel, str)
        or manifest.governance.release_channel not in _RELEASE_CHANNELS
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.release_channel",
            "release_channel is not supported",
        )
    if not isinstance(manifest.governance.approval_policy_ref, str) or not manifest.governance.approval_policy_ref.strip():
        issues.error("CAPABILITY_PACK_GOVERNANCE_INVALID", "$.governance.approval_policy_ref", "approval_policy_ref must be a non-empty string")
    audit = manifest.audit
    if not isinstance(audit.audit_level, str) or not audit.audit_level.strip():
        issues.error("CAPABILITY_PACK_AUDIT_INVALID", "$.audit.audit_level", "audit_level must be a non-empty string")
    required_audit_flags = {
        "record_operation_snapshot": audit.record_operation_snapshot,
        "record_pack_manifest_hash": audit.record_pack_manifest_hash,
        "record_input_manifest": audit.record_input_manifest,
        "record_route_snapshot": audit.record_route_snapshot,
        "record_tool_calls": audit.record_tool_calls,
        "record_cost_receipts": audit.record_cost_receipts,
        "record_evaluation_results": audit.record_evaluation_results,
    }
    for field, value in required_audit_flags.items():
        if not isinstance(value, bool):
            issues.error(
                "CAPABILITY_PACK_AUDIT_INVALID",
                f"$.audit.{field}",
                "audit recording flag must be boolean",
            )


def _validate_stable_identity_inputs(
    payload: Mapping[str, Any], issues: _IssueCollector
) -> None:
    """Reject machine- and run-specific values from a valid manifest identity."""

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = re.sub(
                    r"[^a-z0-9]+", "_", str(key).strip().lower()
                ).strip("_")
                child_path = f"{path}.{key}"
                if normalized in _VOLATILE_IDENTITY_KEYS:
                    issues.error(
                        "CAPABILITY_PACK_MANIFEST_IDENTITY_VOLATILE",
                        child_path,
                        "run- or machine-specific field cannot participate in manifest identity",
                    )
                visit(item, child_path)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        if _UUID_VALUE.fullmatch(value):
            issues.error(
                "CAPABILITY_PACK_MANIFEST_IDENTITY_VOLATILE",
                path,
                "generated UUID cannot participate in manifest identity",
            )
        if _LOCAL_ABSOLUTE_PATH.match(value):
            issues.error(
                "CAPABILITY_PACK_MANIFEST_IDENTITY_VOLATILE",
                path,
                "local absolute workspace path cannot participate in manifest identity",
            )

    visit(payload, "$")


def _validate_extensions(value: Any, issues: _IssueCollector) -> None:
    if not isinstance(value, dict):
        issues.error(
            "CAPABILITY_PACK_EXTENSION_INVALID", "$.ext", "ext must be an object"
        )
        return
    for namespace, extension in value.items():
        if namespace not in _EXTENSION_NAMESPACES:
            issues.error(
                "CAPABILITY_PACK_EXTENSION_INVALID",
                f"$.ext.{namespace}",
                "extension key is not an allowed namespace",
            )
            continue
        if not isinstance(extension, dict):
            issues.error(
                "CAPABILITY_PACK_EXTENSION_INVALID",
                f"$.ext.{namespace}",
                "extension namespace must contain an object",
            )
            continue
        overridden = sorted(set(extension) & set(_TOP_LEVEL_FIELDS))
        if overridden:
            issues.error(
                "CAPABILITY_PACK_EXTENSION_INVALID",
                f"$.ext.{namespace}",
                "extension cannot override core fields: " + ", ".join(overridden),
            )


__all__ = ["validate_capability_pack"]
