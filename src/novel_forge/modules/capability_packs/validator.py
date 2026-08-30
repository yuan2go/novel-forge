"""INVARIANT: Static, fail-closed Capability Pack protocol validation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any

from novel_forge.modules.production_execution.capability_registry import (
    CapabilityRegistry,
    default_capability_registry,
)
from novel_forge.modules.production_execution.capabilities import CapabilityDefinition
from novel_forge.modules.production_execution.security import assert_no_inline_secrets
from .artifacts import is_floating_version
from .operation_catalog import governed_workflow_binding_catalog
from .type_catalog import (
    CapabilityTypePolicy,
    conservative_capability_type_policy,
    default_capability_type_catalog,
    default_tool_definition_catalog,
)

from .errors import CapabilityPackValidationIssue, CapabilityPackValidationReport
from .protocol import validate_protocol_contract
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
_PROTOCOL_VERSION = re.compile(r"^novelos\.capability_pack\.v([1-9][0-9]*)$")
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
_EXTENSION_NAMESPACES = frozenset({"ui", "enterprise", "experiments", "vendor"})
_RAW_SOURCE_TYPES = frozenset({"raw_source_document", "raw_source_chunk"})
_TOOL_PERMISSIONS = frozenset({"READ", "WRITE", "EXECUTE", "QUERY"})
_EXTERNAL_EFFECT_TOOL_REFS = frozenset({"model.provider.invoke", "storage.object.put"})
_SOURCE_ISOLATION_MODES = frozenset(
    {"ABSTRACT_ASSETS_ONLY", "FROZEN_ASSETS_ONLY", "RAW_ALLOWED_WITH_APPROVAL"}
)
_RUNTIME_PROFILES = frozenset({"development", "test", "validation", "production"})
_COMMIT_AUTHORITIES = frozenset(
    {
        "BOOK_DESIGN_AUTHORITY",
        "STORY_DESIGN_AUTHORITY",
        "HIERARCHICAL_PLANNING_AUTHORITY",
        "CHAPTER_AUTHORITY",
        "READER_JUDGE_AUTHORITY",
        "BOOK_FOLLOWUP_AUTHORITY",
        "PLAN_CHANGE_AUTHORITY",
        "AGENT_RUNTIME_AUTHORITY",
    }
)
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
_LOCAL_ABSOLUTE_PATH = re.compile(r"^(?:/Users/|/home/|/tmp/|[A-Za-z]:[\\/]Users[\\/])")


class _IssueCollector:
    def __init__(self) -> None:
        self.errors: list[CapabilityPackValidationIssue] = []
        self.warnings: list[CapabilityPackValidationIssue] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append(CapabilityPackValidationIssue(code, path, message, "ERROR"))

    def warning(self, code: str, path: str, message: str) -> None:
        self.warnings.append(
            CapabilityPackValidationIssue(code, path, message, "WARNING")
        )

    def extend_errors(self, values: tuple[CapabilityPackValidationIssue, ...]) -> None:
        self.errors.extend(values)


def validate_capability_pack(
    manifest: CapabilityPackManifest,
    *,
    capability_registry: CapabilityRegistry | None = None,
) -> CapabilityPackValidationReport:
    registry = capability_registry or default_capability_registry()
    issues = _IssueCollector()
    resolved: set[str] = set()
    payload = manifest.to_dict()
    try:
        capability_type_policy = default_capability_type_catalog().resolve(
            str(manifest.identity.capability_type)
        )
    except KeyError:
        capability_type_policy = conservative_capability_type_policy(
            str(manifest.identity.capability_type)
        )

    issues.extend_errors(validate_protocol_contract(payload))
    _validate_schema_version(manifest, issues)
    _validate_identity(manifest, issues)
    _validate_lifecycle_policy(manifest, issues)
    _validate_compatibility(manifest, registry, resolved, issues)
    _validate_role(manifest, issues)
    _validate_skills(manifest, issues)
    _validate_prompt(manifest, issues)
    _validate_workflow(manifest, registry, resolved, issues)
    _validate_context(manifest, capability_type_policy, issues)
    _validate_tools(manifest, capability_type_policy, issues)
    _validate_assets(manifest, capability_type_policy, issues)
    _validate_evaluation(manifest, registry, resolved, issues)
    _validate_capability_declarations(manifest, issues)
    _validate_runtime(manifest, capability_type_policy, issues)
    _validate_governance_and_audit(manifest, issues)
    _validate_extensions(payload.get("ext"), issues)
    _validate_stable_identity_inputs(payload, issues)
    _validate_floating_references(payload, issues)
    try:
        assert_no_inline_secrets(payload, label="CapabilityPackManifest")
    except ValueError as exc:
        issues.error("CAPABILITY_PACK_INLINE_SECRET_FORBIDDEN", "$", str(exc))

    return CapabilityPackValidationReport(
        ok=not issues.errors,
        pack_id=(
            manifest.identity.pack_id
            if isinstance(manifest.identity.pack_id, str)
            else ""
        ),
        version=(
            manifest.identity.version
            if isinstance(manifest.identity.version, str)
            else ""
        ),
        manifest_hash=manifest.manifest_hash,
        errors=tuple(issues.errors),
        warnings=tuple(issues.warnings),
        resolved_capabilities=tuple(sorted(resolved)),
    )


def _validate_schema_version(
    manifest: CapabilityPackManifest,
    issues: _IssueCollector,
) -> None:
    if manifest.schema_version != CAPABILITY_PACK_SCHEMA_VERSION:
        issues.error(
            "CAPABILITY_PACK_SCHEMA_VERSION_UNSUPPORTED",
            "$.schema_version",
            f"schema_version must be {CAPABILITY_PACK_SCHEMA_VERSION}",
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
    try:
        default_capability_type_catalog().resolve(str(identity.capability_type))
    except KeyError:
        issues.error(
            "CAPABILITY_PACK_CAPABILITY_TYPE_UNKNOWN",
            "$.identity.capability_type",
            "capability_type is not present in the governed policy catalog",
        )
        issues.error(
            "CAPABILITY_PACK_IDENTITY_INVALID",
            "$.identity.capability_type",
            "capability_type is not supported by the Capability Type policy catalog",
        )


def _resolve_capability(
    capability_id: Any,
    *,
    path: str,
    code: str,
    registry: CapabilityRegistry,
    resolved: set[str],
    issues: _IssueCollector,
) -> CapabilityDefinition | None:
    if not isinstance(capability_id, str) or not capability_id:
        issues.error(code, path, "capability ID must be a non-empty string")
        return None
    try:
        definition = registry.resolve(capability_id)
    except ValueError as exc:
        issues.error(code, path, str(exc))
        return None
    else:
        resolved.add(definition.capability_id.value)
        return definition


def _validate_lifecycle_policy(
    manifest: CapabilityPackManifest, issues: _IssueCollector
) -> None:
    try:
        policy = default_capability_type_catalog().resolve(
            str(manifest.identity.capability_type)
        )
    except KeyError:
        return  # identity validation already reports the unknown type
    triple = (
        str(manifest.identity.status),
        str(manifest.identity.lifecycle),
        str(manifest.governance.release_channel),
    )
    if triple not in policy.allowed_status_lifecycle_channels:
        issues.error(
            "CAPABILITY_PACK_LIFECYCLE_CONFLICT",
            "$.identity",
            "status, lifecycle, and release_channel are not a governed combination",
        )


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
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"$.compatibility.{field}",
                f"{field} must be a non-empty string",
            )
    for field, value in (
        ("novel_forge_max_version", compatibility.novel_forge_max_version),
        ("protocol_max_version", compatibility.protocol_max_version),
    ):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"$.compatibility.{field}",
                f"{field} must be null or a non-empty string",
            )
    for index, capability_id in enumerate(compatibility.required_capabilities):
        _resolve_capability(
            capability_id,
            path=f"$.compatibility.required_capabilities[{index}]",
            code="CAPABILITY_PACK_CAPABILITY_UNKNOWN",
            registry=registry,
            resolved=resolved,
            issues=issues,
        )
    required_capabilities = tuple(
        value for value in compatibility.required_capabilities if isinstance(value, str)
    )
    if len(required_capabilities) != len(set(required_capabilities)):
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.required_capabilities",
            "required capabilities must be unique",
        )
    for field, values in (
        ("required_schema_versions", compatibility.required_schema_versions),
        ("incompatible_packs", compatibility.incompatible_packs),
        ("compatible_runtime_profiles", compatibility.compatible_runtime_profiles),
    ):
        strings = tuple(value for value in values if isinstance(value, str))
        if len(strings) != len(set(strings)):
            issues.error(
                "CAPABILITY_PACK_COMPATIBILITY_INVALID",
                f"$.compatibility.{field}",
                f"{field} entries must be unique",
            )
    profiles = {
        value
        for value in compatibility.compatible_runtime_profiles
        if isinstance(value, str)
    }
    unsupported_profiles = sorted(profiles - _RUNTIME_PROFILES)
    if unsupported_profiles:
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.compatible_runtime_profiles",
            "unsupported runtime profiles: " + ", ".join(unsupported_profiles),
        )
    if (
        isinstance(manifest.identity.pack_id, str)
        and manifest.identity.pack_id in compatibility.incompatible_packs
    ):
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.incompatible_packs",
            "pack cannot declare itself incompatible",
        )
    _validate_version_range(compatibility, issues)


def _validate_version_range(compatibility: Any, issues: _IssueCollector) -> None:
    minimum = _parse_semver(compatibility.novel_forge_min_version)
    maximum = _parse_semver(compatibility.novel_forge_max_version)
    if minimum is None:
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.novel_forge_min_version",
            "minimum Novel Forge version must be SemVer",
        )
    if compatibility.novel_forge_max_version is not None and maximum is None:
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.novel_forge_max_version",
            "maximum Novel Forge version must be null or SemVer",
        )
    if minimum is not None and maximum is not None and minimum > maximum:
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility",
            "Novel Forge minimum version exceeds maximum version",
        )
    protocol_minimum = _parse_protocol_version(compatibility.protocol_min_version)
    protocol_maximum = _parse_protocol_version(compatibility.protocol_max_version)
    if protocol_minimum is None:
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.protocol_min_version",
            "minimum protocol version is invalid",
        )
    if compatibility.protocol_max_version is not None and protocol_maximum is None:
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility.protocol_max_version",
            "maximum protocol version is invalid",
        )
    current = _parse_protocol_version(CAPABILITY_PACK_SCHEMA_VERSION)
    if (
        current is not None
        and protocol_minimum is not None
        and current < protocol_minimum
    ) or (
        current is not None
        and protocol_maximum is not None
        and current > protocol_maximum
    ):
        issues.error(
            "CAPABILITY_PACK_COMPATIBILITY_INVALID",
            "$.compatibility",
            "current protocol version is outside the declared compatibility range",
        )


def _parse_semver(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _SEMVER.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _parse_protocol_version(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _PROTOCOL_VERSION.fullmatch(value)
    return int(match.group(1)) if match is not None else None


def _validate_role(manifest: CapabilityPackManifest, issues: _IssueCollector) -> None:
    role = manifest.role
    if not isinstance(role.role_type, str) or role.role_type not in _ROLE_TYPES:
        issues.error(
            "CAPABILITY_PACK_ROLE_INVALID",
            "$.role.role_type",
            "role_type is not supported",
        )
    for field, value in (
        ("role_name", role.role_name),
        ("authority_level", role.authority_level),
    ):
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
    dependency_graph: dict[str, tuple[str, ...]] = {}
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
                issues.error(
                    "CAPABILITY_PACK_SKILL_POLICY_INVALID",
                    f"{path}.{field}",
                    f"{field} must be a non-empty string",
                )
        if not isinstance(skill.required, bool):
            issues.error(
                "CAPABILITY_PACK_SKILL_POLICY_INVALID",
                f"{path}.required",
                "required must be boolean",
            )
        if isinstance(skill.skill_ref, str) and skill.skill_ref in seen:
            issues.error(
                "CAPABILITY_PACK_SKILL_DUPLICATE",
                f"{path}.skill_ref",
                f"duplicate skill_ref: {skill.skill_ref}",
            )
        if isinstance(skill.skill_ref, str):
            seen.add(skill.skill_ref)
            dependency_graph.setdefault(skill.skill_ref, skill.depends_on)
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
        if (
            not isinstance(skill.max_invocations_per_run, int)
            or isinstance(skill.max_invocations_per_run, bool)
            or skill.max_invocations_per_run <= 0
        ):
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
    for field in (
        "duplicate_skill_refs_forbidden",
        "unbound_skill_forbidden",
        "dynamic_selection_requires_policy",
    ):
        if anti_drift.get(field) is not True:
            issues.error(
                "CAPABILITY_PACK_SKILL_POLICY_INVALID",
                f"$.skill_binding.anti_drift.{field}",
                f"{field} must be true",
            )
    if _has_cycle(dependency_graph):
        issues.error(
            "CAPABILITY_PACK_SKILL_DEPENDENCY_CYCLE",
            "$.skill_binding.skills",
            "skill dependency graph contains a cycle",
        )


def _validate_prompt(manifest: CapabilityPackManifest, issues: _IssueCollector) -> None:
    prompt = manifest.prompt_binding
    for field, value in (
        ("prompt_bundle_type", prompt.prompt_bundle_type),
        ("system_instruction_ref", prompt.system_instruction_ref),
        ("system_instruction_version", prompt.system_instruction_version),
        ("template_ref", prompt.template_ref),
        ("template_version", prompt.template_version),
        ("compiler_version", prompt.compiler_version),
        ("input_schema_ref", prompt.input_schema_ref),
        ("output_schema_ref", prompt.output_schema_ref),
    ):
        if not isinstance(value, str) or not value.strip():
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"$.prompt_binding.{field}",
                f"{field} must be a non-empty string",
            )
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
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"$.workflow_template.{field}",
                f"{field} must be a non-empty string",
            )
    if not isinstance(workflow.workflow_version, str) or not _SEMVER.fullmatch(
        workflow.workflow_version
    ):
        issues.error(
            "CAPABILITY_PACK_PROTOCOL_INVALID",
            "$.workflow_template.workflow_version",
            "workflow_version must be SemVer MAJOR.MINOR.PATCH",
        )
    if workflow.execution_mode != "SAGA":
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
            "$.workflow_template.execution_mode",
            "production_workflow requires SAGA execution_mode in P0",
        )
    if not workflow.nodes:
        issues.error(
            "CAPABILITY_PACK_PROTOCOL_INVALID",
            "$.workflow_template.nodes",
            "workflow requires at least one node",
        )
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
            ("operation_definition_hash", node.operation_definition_hash),
            ("handler_key", node.handler_key),
            ("stage", node.stage),
            ("capability_id", node.capability_id),
            ("timeout_policy_ref", node.timeout_policy_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.error(
                    "CAPABILITY_PACK_PROTOCOL_INVALID",
                    f"{path}.{field}",
                    f"{field} must be a non-empty string",
                )
        if isinstance(node.node_id, str) and node.node_id in seen:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_NODE_DUPLICATE",
                f"{path}.node_id",
                f"duplicate node_id: {node.node_id}",
            )
        if isinstance(node.node_id, str):
            seen.add(node.node_id)
            graph.setdefault(node.node_id, node.depends_on)
        capability = _resolve_capability(
            node.capability_id,
            path=f"{path}.capability_id",
            code="CAPABILITY_PACK_CAPABILITY_UNKNOWN",
            registry=registry,
            resolved=resolved,
            issues=issues,
        )
        if node.commit_authority not in _COMMIT_AUTHORITIES:
            issues.error(
                "CAPABILITY_PACK_COMMIT_AUTHORITY_INVALID",
                f"{path}.commit_authority",
                "commit_authority must name an allowed Domain Authority",
            )
        if (
            capability is not None
            and node.timeout_policy_ref != capability.timeout_policy_ref
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                f"{path}.timeout_policy_ref",
                "timeout policy differs from the governed Capability Definition",
            )
        dependencies = tuple(
            value for value in node.depends_on if isinstance(value, str)
        )
        if len(dependencies) != len(set(dependencies)):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_DEPENDENCY_UNKNOWN",
                f"{path}.depends_on",
                "workflow dependencies must be unique",
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
            for value in (
                node.operation_name,
                node.operation_definition_ref,
                node.handler_key,
            )
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                path,
                "workflow nodes require operation and handler bindings",
            )
        if not _valid_hash(node.operation_definition_hash):
            issues.error(
                "CAPABILITY_PACK_HASH_INVALID",
                f"{path}.operation_definition_hash",
                "operation_definition_hash must be sha256:<64 lowercase hex>",
            )
        _validate_operation_binding(manifest, node, path, issues)
        if node.approval.get("required") is True and not _non_empty(
            node.approval.get("policy_ref")
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                f"{path}.approval.policy_ref",
                "required approval requires policy_ref",
            )
        if node.compensation.get("supported") is True and not _non_empty(
            node.compensation.get("policy_ref")
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                f"{path}.compensation.policy_ref",
                "supported compensation requires policy_ref",
            )
    if _has_cycle(graph):
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_CYCLE",
            "$.workflow_template.nodes",
            "workflow dependency graph contains a cycle",
        )
    try:
        governed_workflow = governed_workflow_binding_catalog(
            str(workflow.workflow_id), str(workflow.workflow_version)
        )
    except KeyError:
        governed_workflow = None
    if governed_workflow is not None:
        governed_nodes = {item.node_id for item in governed_workflow.bindings()}
        if known != governed_nodes:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                "$.workflow_template.nodes",
                "workflow node set differs from the governed Authority graph",
            )
    for index, terminal in enumerate(workflow.completion.required_terminal_nodes):
        if isinstance(terminal, str) and terminal not in known:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN",
                f"$.workflow_template.completion.required_terminal_nodes[{index}]",
                f"unknown completion terminal node: {terminal}",
            )
        elif isinstance(terminal, str) and any(
            terminal in dependencies for dependencies in graph.values()
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN",
                f"$.workflow_template.completion.required_terminal_nodes[{index}]",
                f"declared completion node is not terminal: {terminal}",
            )
    if not workflow.completion.required_terminal_nodes:
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN",
            "$.workflow_template.completion.required_terminal_nodes",
            "at least one completion terminal node is required",
        )
    produced_assets = {
        asset_type
        for node in workflow.nodes
        for asset_type in node.output_asset_types
        if isinstance(asset_type, str)
    }
    missing_outputs = sorted(
        {
            value
            for value in workflow.completion.required_output_asset_types
            if isinstance(value, str)
        }
        - produced_assets
    )
    if missing_outputs:
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
            "$.workflow_template.completion.required_output_asset_types",
            "completion requires outputs not produced by the workflow: "
            + ", ".join(missing_outputs),
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


def _validate_operation_binding(
    manifest: CapabilityPackManifest,
    node: Any,
    path: str,
    issues: _IssueCollector,
) -> None:
    if isinstance(node.operation_definition_ref, str):
        operation_name, separator, version = node.operation_definition_ref.rpartition(
            "@"
        )
        if (
            separator != "@"
            or operation_name != node.operation_name
            or _SEMVER.fullmatch(version) is None
        ):
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                f"{path}.operation_definition_ref",
                "operation definition ref must bind operation_name to a SemVer version",
            )
    workflow = manifest.workflow_template
    try:
        catalog = governed_workflow_binding_catalog(
            str(workflow.workflow_id), str(workflow.workflow_version)
        )
    except KeyError:
        return
    try:
        binding = catalog.resolve(str(node.node_id))
    except KeyError:
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_BINDING_UNKNOWN",
            f"{path}.node_id",
            "node is not in the governed Authority workflow binding catalog",
        )
        return
    expectations = (
        ("operation_name", binding.operation_name, node.operation_name),
        ("handler_key", binding.handler_key, node.handler_key),
        ("stage", binding.stage, node.stage),
        ("capability_id", binding.capability_id, node.capability_id),
        ("depends_on", binding.depends_on, node.depends_on),
    )
    for field, expected, actual in expectations:
        if actual != expected:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
                f"{path}.{field}",
                "workflow binding differs from the governed Authority/Scheduler contract",
            )
    if (
        binding.primary_output_asset_type
        and binding.primary_output_asset_type not in node.output_asset_types
    ):
        issues.error(
            "CAPABILITY_PACK_WORKFLOW_BINDING_INVALID",
            f"{path}.output_asset_types",
            "workflow binding omits the governed primary output asset",
        )


def _validate_context(
    manifest: CapabilityPackManifest,
    capability_type_policy: CapabilityTypePolicy,
    issues: _IssueCollector,
) -> None:
    context = manifest.context_sources
    if not isinstance(context.policy_id, str) or not context.policy_id.strip():
        issues.error(
            "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            "$.context_sources.policy_id",
            "policy_id must be a non-empty string",
        )
    if (
        not isinstance(context.source_isolation, str)
        or context.source_isolation not in _SOURCE_ISOLATION_MODES
    ):
        issues.error(
            "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            "$.context_sources.source_isolation",
            "source_isolation is not supported",
        )
    if (
        not isinstance(context.max_tokens, int)
        or isinstance(context.max_tokens, bool)
        or context.max_tokens <= 0
    ):
        issues.error(
            "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            "$.context_sources.max_tokens",
            "max_tokens must be a positive integer",
        )
    allowed = {value for value in context.allowed_asset_types if isinstance(value, str)}
    forbidden = {
        value for value in context.forbidden_asset_types if isinstance(value, str)
    }
    for field, values in (
        ("allowed_asset_types", context.allowed_asset_types),
        ("forbidden_asset_types", context.forbidden_asset_types),
        ("required_version_refs", context.required_version_refs),
        ("priority", context.priority),
    ):
        strings = tuple(value for value in values if isinstance(value, str))
        if len(strings) != len(set(strings)):
            issues.error(
                "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
                f"$.context_sources.{field}",
                f"{field} entries must be unique",
            )
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
    latest_refs = sorted(
        value
        for value in context.required_version_refs
        if isinstance(value, str) and is_floating_version(value)
    )
    if latest_refs:
        issues.error(
            "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            "$.context_sources.required_version_refs",
            "required version refs cannot use floating aliases: "
            + ", ".join(latest_refs),
        )
    for field, value in context.longform_bindings.items():
        if not isinstance(value, str) or value not in {
            "required",
            "optional",
            "forbidden",
        }:
            issues.error(
                "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
                f"$.context_sources.longform_bindings.{field}",
                "longform binding must be required, optional, or forbidden",
            )
    if (
        _is_production_pack(manifest)
        and context.source_isolation == "RAW_ALLOWED_WITH_APPROVAL"
    ):
        issues.error(
            "CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN",
            "$.context_sources.source_isolation",
            "production packs cannot admit raw source context with approval",
        )
    if capability_type_policy.generation:
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
    capability_type_policy: CapabilityTypePolicy,
    issues: _IssueCollector,
) -> None:
    permissions = manifest.tool_permissions
    if not isinstance(permissions.policy_id, str) or not permissions.policy_id.strip():
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.tool_permissions.policy_id",
            "tool policy_id must be a non-empty string",
        )
    if permissions.default != "DENY":
        issues.error(
            "CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN",
            "$.tool_permissions.default",
            "tool policy default must be DENY",
        )
    workflow_nodes = {
        node.node_id
        for node in manifest.workflow_template.nodes
        if isinstance(node.node_id, str)
    }
    seen_tools: set[str] = set()
    for index, tool in enumerate(permissions.tools):
        path = f"$.tool_permissions.tools[{index}]"
        for field, value in (
            ("tool_ref", tool.tool_ref),
            ("budget_policy_ref", tool.budget_policy_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.error(
                    "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                    f"{path}.{field}",
                    f"{field} must be a non-empty string",
                )
        if isinstance(tool.tool_ref, str):
            if tool.tool_ref in seen_tools:
                issues.error(
                    "CAPABILITY_PACK_TOOL_DUPLICATE",
                    f"{path}.tool_ref",
                    f"duplicate tool_ref: {tool.tool_ref}",
                )
                issues.error(
                    "CAPABILITY_PACK_TOOL_BINDING_DUPLICATE",
                    f"{path}.tool_ref",
                    f"duplicate tool_ref: {tool.tool_ref}",
                )
            seen_tools.add(tool.tool_ref)
        if (
            not isinstance(tool.permission, str)
            or tool.permission not in _TOOL_PERMISSIONS
        ):
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.permission",
                "tool permission is not supported",
            )
        if not tool.allowed_operations:
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.allowed_operations",
                "tool requires at least one allowed operation",
            )
        operation_names = tuple(
            value for value in tool.allowed_operations if isinstance(value, str)
        )
        if len(operation_names) != len(set(operation_names)):
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.allowed_operations",
                "allowed operations must be unique",
            )
        unknown_operations = sorted(set(operation_names) - workflow_nodes)
        if unknown_operations:
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.allowed_operations",
                "tool references unknown workflow nodes: "
                + ", ".join(unknown_operations),
            )
            issues.error(
                "CAPABILITY_PACK_TOOL_OPERATION_UNKNOWN",
                f"{path}.allowed_operations",
                "tool references unknown workflow nodes: "
                + ", ".join(unknown_operations),
            )
        if not isinstance(tool.approval_required, bool):
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.approval_required",
                "approval_required must be boolean",
            )
        if not isinstance(tool.audit_required, bool):
            issues.error(
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
                f"{path}.audit_required",
                "audit_required must be boolean",
            )
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
        try:
            governed = default_tool_definition_catalog().resolve(str(tool.tool_ref))
        except KeyError:
            issues.error(
                "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
                f"{path}.tool_ref",
                "tool is not present in the governed ToolDefinition catalog",
            )
        else:
            rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
            if rank.get(risk, -1) < rank[governed.minimum_risk_class]:
                issues.error(
                    "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
                    f"{path}.risk_class",
                    "tool risk is lower than its governed minimum",
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
            if _is_production_pack(manifest) and not (
                posix.is_absolute() or windows.is_absolute()
            ):
                issues.error(
                    "CAPABILITY_PACK_FILE_ROOT_INVALID",
                    f"$.tool_permissions.files.allowed_roots[{index}]",
                    "production file roots must be absolute",
                )
    database_allowed = {
        value
        for value in _json_items(permissions.database.get("allowed_tables"))
        if isinstance(value, str)
    }
    database_forbidden = {
        value
        for value in _json_items(permissions.database.get("forbidden_tables"))
        if isinstance(value, str)
    }
    table_overlap = sorted(database_allowed & database_forbidden)
    if table_overlap:
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.tool_permissions.database",
            "database tables cannot be both allowed and forbidden: "
            + ", ".join(table_overlap),
        )
    if (
        permissions.database.get("read_allowed") is True
        or permissions.database.get("write_allowed") is True
    ) and not database_allowed:
        issues.error(
            "CAPABILITY_PACK_PERMISSION_ALLOWLIST_EMPTY",
            "$.tool_permissions.database.allowed_tables",
            "enabled database access with an empty allowlist is fail-closed DENY_ALL",
        )
    if (
        permissions.files.get("read_allowed") is True
        or permissions.files.get("write_allowed") is True
    ) and not roots:
        issues.error(
            "CAPABILITY_PACK_PERMISSION_ALLOWLIST_EMPTY",
            "$.tool_permissions.files.allowed_roots",
            "enabled file access with an empty allowlist is fail-closed DENY_ALL",
        )
    if (
        "model.provider.invoke" in seen_tools
        and permissions.external_models.get("allowed") is not True
    ):
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.tool_permissions.external_models.allowed",
            "model provider tool requires external model permission",
        )
    if permissions.external_models.get("allowed") is True and not _non_empty(
        permissions.external_models.get("route_policy_ref")
    ):
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.tool_permissions.external_models.route_policy_ref",
            "external model permission requires route_policy_ref",
        )
    if permissions.retrieval.get("allowed") is True and not _non_empty(
        permissions.retrieval.get("source_policy_ref")
    ):
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.tool_permissions.retrieval.source_policy_ref",
            "retrieval permission requires source_policy_ref",
        )
    if (
        seen_tools & _EXTERNAL_EFFECT_TOOL_REFS
        and manifest.runtime_contract.execution.get("external_effects_allowed")
        is not True
    ):
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.runtime_contract.execution.external_effects_allowed",
            "declared external-effect tools require runtime permission",
        )
    if (
        seen_tools & _EXTERNAL_EFFECT_TOOL_REFS
        and not capability_type_policy.allows_external_effects
    ):
        issues.error(
            "CAPABILITY_PACK_POLICY_BINDING_INVALID",
            "$.tool_permissions.tools",
            "Capability Type policy forbids external-effect tools",
        )
    if roots and not (
        permissions.files.get("read_allowed") is True
        or permissions.files.get("write_allowed") is True
    ):
        issues.error(
            "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            "$.tool_permissions.files.allowed_roots",
            "file roots require read or write permission",
        )


def _validate_assets(
    manifest: CapabilityPackManifest,
    capability_type_policy: CapabilityTypePolicy,
    issues: _IssueCollector,
) -> None:
    seen_rules: set[str] = set()
    for index, rule in enumerate(manifest.assets.rules):
        rule_ref = rule.get("rule_ref")
        path = f"$.assets.rules[{index}]"
        if not _non_empty(rule_ref):
            issues.error(
                "CAPABILITY_PACK_ASSET_POLICY_INVALID",
                f"{path}.rule_ref",
                "rule_ref must be a non-empty string",
            )
        elif rule_ref in seen_rules:
            issues.error(
                "CAPABILITY_PACK_ASSET_POLICY_INVALID",
                f"{path}.rule_ref",
                f"duplicate rule_ref: {rule_ref}",
            )
        else:
            seen_rules.add(rule_ref)
    if not capability_type_policy.generation:
        return
    knowledge = manifest.assets.knowledge
    project_pack = knowledge.get("project_knowledge_pack")
    if not isinstance(project_pack, Mapping):
        issues.error(
            "CAPABILITY_PACK_KNOWLEDGE_POLICY_REQUIRED",
            "$.assets.knowledge.project_knowledge_pack",
            "generation packs must declare the project Knowledge Pack policy",
        )
    else:
        default_requirement = project_pack.get("default_requirement")
        if not isinstance(default_requirement, str) or default_requirement not in {
            "OPTIONAL",
            "REQUIRED",
        }:
            issues.error(
                "CAPABILITY_PACK_KNOWLEDGE_POLICY_INVALID",
                "$.assets.knowledge.project_knowledge_pack.default_requirement",
                "default_requirement must be OPTIONAL or REQUIRED",
            )
        stages = {
            str(value) for value in _json_items(project_pack.get("required_stages"))
        }
        capability_ids = {
            str(value)
            for value in _json_items(project_pack.get("required_capability_ids"))
        }
        known_stages = {str(node.stage) for node in manifest.workflow_template.nodes}
        known_capabilities = {
            str(node.capability_id) for node in manifest.workflow_template.nodes
        }
        if not stages.issubset(known_stages):
            issues.error(
                "CAPABILITY_PACK_KNOWLEDGE_POLICY_INVALID",
                "$.assets.knowledge.project_knowledge_pack.required_stages",
                "required_stages must reference Pack workflow stages",
            )
        if not capability_ids.issubset(known_capabilities):
            issues.error(
                "CAPABILITY_PACK_KNOWLEDGE_POLICY_INVALID",
                "$.assets.knowledge.project_knowledge_pack.required_capability_ids",
                "required_capability_ids must reference Pack workflow capabilities",
            )
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
    eligibility = {
        value
        for value in _json_items(source.get("allowed_eligibility"))
        if isinstance(value, str)
    }
    governed_eligibility = {"PRODUCTION_ELIGIBLE", "NOT_SOURCE_DERIVED"}
    if not eligibility or not eligibility.issubset(governed_eligibility):
        issues.error(
            "CAPABILITY_PACK_SOURCE_POLICY_INVALID",
            "$.assets.source_policy.allowed_eligibility",
            "generation source eligibility must use the governed production-safe set",
        )


def _validate_evaluation(
    manifest: CapabilityPackManifest,
    registry: CapabilityRegistry,
    resolved: set[str],
    issues: _IssueCollector,
) -> None:
    if (
        not isinstance(manifest.evaluation.evaluation_id, str)
        or not manifest.evaluation.evaluation_id.strip()
    ):
        issues.error(
            "CAPABILITY_PACK_EVALUATION_INVALID",
            "$.evaluation.evaluation_id",
            "evaluation_id must be a non-empty string",
        )
    if (
        manifest.identity.capability_type == "production_workflow"
        and not manifest.evaluation.required_gates
    ):
        issues.error(
            "CAPABILITY_PACK_EVALUATION_INVALID",
            "$.evaluation.required_gates",
            "at least one evaluation gate is required",
        )
    seen_gates: set[str] = set()
    for index, gate in enumerate(manifest.evaluation.required_gates):
        path = f"$.evaluation.required_gates[{index}]"
        if not isinstance(gate.gate_id, str) or not gate.gate_id.strip():
            issues.error(
                "CAPABILITY_PACK_EVALUATION_INVALID",
                f"{path}.gate_id",
                "gate_id must be a non-empty string",
            )
        elif gate.gate_id in seen_gates:
            issues.error(
                "CAPABILITY_PACK_EVALUATION_GATE_DUPLICATE",
                f"{path}.gate_id",
                f"duplicate gate_id: {gate.gate_id}",
            )
        else:
            seen_gates.add(gate.gate_id)
        if not isinstance(gate.blocking, bool):
            issues.error(
                "CAPABILITY_PACK_EVALUATION_INVALID",
                f"{path}.blocking",
                "blocking must be boolean",
            )
        if not gate.required_evidence:
            issues.error(
                "CAPABILITY_PACK_EVALUATION_INVALID",
                f"{path}.required_evidence",
                "evaluation gate requires evidence",
            )
        judge = _resolve_capability(
            gate.judge_capability_id,
            path=f"$.evaluation.required_gates[{index}].judge_capability_id",
            code="CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN",
            registry=registry,
            resolved=resolved,
            issues=issues,
        )
        if judge is not None and not judge.capability_id.value.endswith(".judge"):
            issues.error(
                "CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN",
                f"{path}.judge_capability_id",
                "evaluation gate capability is registered but is not a Judge capability",
            )
    if manifest.identity.capability_type == "production_workflow" and not any(
        gate.blocking is True
        and gate.judge_capability_id == "quality.originality.judge"
        for gate in manifest.evaluation.required_gates
    ):
        issues.error(
            "CAPABILITY_PACK_SOURCE_ISOLATION_GATE_REQUIRED",
            "$.evaluation.required_gates",
            "production generation requires a blocking originality/source-isolation gate",
        )
    seen_metrics: set[str] = set()
    for index, metric in enumerate(manifest.evaluation.metrics):
        metric_id = metric.get("metric_id")
        path = f"$.evaluation.metrics[{index}].metric_id"
        if not isinstance(metric_id, str) or not metric_id.strip():
            issues.error(
                "CAPABILITY_PACK_EVALUATION_INVALID",
                path,
                "metric_id must be a non-empty string",
            )
        elif metric_id in seen_metrics:
            issues.error(
                "CAPABILITY_PACK_EVALUATION_INVALID",
                path,
                f"duplicate metric_id: {metric_id}",
            )
        else:
            seen_metrics.add(metric_id)
    failure_sets = {
        field: {
            value
            for value in _json_items(manifest.evaluation.failure_policy.get(field))
            if isinstance(value, str)
        }
        for field in (
            "acceptable_failures",
            "retryable_failures",
            "terminal_failures",
        )
    }
    overlap = sorted(
        (failure_sets["acceptable_failures"] & failure_sets["retryable_failures"])
        | (failure_sets["acceptable_failures"] & failure_sets["terminal_failures"])
        | (failure_sets["retryable_failures"] & failure_sets["terminal_failures"])
    )
    if overlap:
        issues.error(
            "CAPABILITY_PACK_EVALUATION_INVALID",
            "$.evaluation.failure_policy",
            "failure classes must be disjoint: " + ", ".join(overlap),
        )


def _validate_capability_declarations(
    manifest: CapabilityPackManifest, issues: _IssueCollector
) -> None:
    declared = {
        value
        for value in manifest.compatibility.required_capabilities
        if isinstance(value, str)
    }
    referenced: dict[str, list[str]] = {}
    for index, node in enumerate(manifest.workflow_template.nodes):
        if isinstance(node.capability_id, str):
            referenced.setdefault(node.capability_id, []).append(
                f"$.workflow_template.nodes[{index}].capability_id"
            )
    for index, gate in enumerate(manifest.evaluation.required_gates):
        if isinstance(gate.judge_capability_id, str):
            referenced.setdefault(gate.judge_capability_id, []).append(
                f"$.evaluation.required_gates[{index}].judge_capability_id"
            )
    for capability_id in sorted(set(referenced) - declared):
        issues.error(
            "CAPABILITY_PACK_CAPABILITY_DECLARATION_MISSING",
            referenced[capability_id][0],
            f"referenced capability is absent from compatibility.required_capabilities: {capability_id}",
        )


def _validate_runtime(
    manifest: CapabilityPackManifest,
    capability_type_policy: CapabilityTypePolicy,
    issues: _IssueCollector,
) -> None:
    runtime = manifest.runtime_contract
    for field in (
        "input_protocol_ref",
        "output_protocol_ref",
        "error_protocol_ref",
        "state_protocol_ref",
        "event_protocol_ref",
        "audit_protocol_ref",
        "rollback_protocol_ref",
        "commit_policy_ref",
        "validation_policy_ref",
    ):
        value = getattr(runtime, field)
        if not isinstance(value, str) or not value.strip():
            issues.error(
                "CAPABILITY_PACK_PROTOCOL_INVALID",
                f"$.runtime_contract.{field}",
                f"{field} must be a non-empty string",
            )
    execution = manifest.runtime_contract.execution
    if (
        capability_type_policy.requires_authority_operation
        or capability_type_policy.requires_attempt_fence
        or capability_type_policy.generation
        or _is_production_pack(manifest)
    ) and (
        execution.get("binds_authority_operation") is not True
        or execution.get("binds_attempt_fence") is not True
        or execution.get("synchronous_fixture_allowed") is not False
    ):
        issues.error(
            "CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED",
            "$.runtime_contract.execution",
            "generation/production packs require Authority Operation and Attempt Fence binding and prohibit synchronous fixtures",
        )

    if (
        execution.get("external_effects_allowed") is True
        and not capability_type_policy.allows_external_effects
    ):
        issues.error(
            "CAPABILITY_PACK_POLICY_BINDING_INVALID",
            "$.runtime_contract.execution.external_effects_allowed",
            "Capability Type policy forbids external effects",
        )


def _is_production_pack(manifest: CapabilityPackManifest) -> bool:
    return (
        manifest.identity.lifecycle == "PRODUCTION"
        or manifest.governance.release_channel == "PRODUCTION"
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
    if (
        not isinstance(manifest.governance.approval_policy_ref, str)
        or not manifest.governance.approval_policy_ref.strip()
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.approval_policy_ref",
            "approval_policy_ref must be a non-empty string",
        )
    governance = manifest.governance
    canary_percent = governance.rollout.get("canary_percent")
    if (
        not isinstance(canary_percent, int)
        or isinstance(canary_percent, bool)
        or not 0 <= canary_percent <= 100
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.rollout.canary_percent",
            "canary_percent must be an integer from 0 through 100",
        )
    rollout_mode = governance.rollout.get("mode")
    if not isinstance(rollout_mode, str) or rollout_mode not in {
        "OFF",
        "CANARY",
        "FULL",
    }:
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.rollout.mode",
            "rollout mode must be OFF, CANARY, or FULL",
        )
    if rollout_mode == "OFF" and canary_percent != 0:
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.rollout",
            "OFF rollout requires canary_percent=0",
        )
    if rollout_mode == "CANARY" and (
        not isinstance(canary_percent, int)
        or isinstance(canary_percent, bool)
        or not 1 <= canary_percent <= 99
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.rollout",
            "CANARY rollout requires canary_percent from 1 through 99",
        )
    if governance.versioning.get("migration_required") is True and not _non_empty(
        governance.versioning.get("migration_policy_ref")
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.versioning.migration_policy_ref",
            "migration_required requires migration_policy_ref",
        )
    if governance.rollback.get("allowed") is True and not _non_empty(
        governance.rollback.get("policy_ref")
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.rollback.policy_ref",
            "allowed rollback requires policy_ref",
        )
    if governance.cost_tracking.get("required") is True and not _non_empty(
        governance.cost_tracking.get("budget_policy_ref")
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.cost_tracking.budget_policy_ref",
            "required cost tracking requires budget_policy_ref",
        )
    if governance.quality_tracking.get("required") is True and not _json_items(
        governance.quality_tracking.get("report_refs")
    ):
        issues.error(
            "CAPABILITY_PACK_GOVERNANCE_INVALID",
            "$.governance.quality_tracking.report_refs",
            "required quality tracking requires report refs",
        )
    audit = manifest.audit
    if not isinstance(audit.audit_level, str) or not audit.audit_level.strip():
        issues.error(
            "CAPABILITY_PACK_AUDIT_INVALID",
            "$.audit.audit_level",
            "audit_level must be a non-empty string",
        )
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
        elif (
            manifest.identity.capability_type == "production_workflow"
            and value is not True
        ):
            issues.error(
                "CAPABILITY_PACK_AUDIT_INVALID",
                f"$.audit.{field}",
                "production_workflow requires complete audit evidence",
            )


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _json_items(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _validate_stable_identity_inputs(
    payload: Mapping[str, Any], issues: _IssueCollector
) -> None:

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip(
                    "_"
                )
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
        overridden = sorted(_find_core_overrides(extension))
        if overridden:
            issues.error(
                "CAPABILITY_PACK_EXTENSION_INVALID",
                f"$.ext.{namespace}",
                "extension cannot shadow core fields: " + ", ".join(overridden),
            )


def _validate_floating_references(
    payload: Mapping[str, Any], issues: _IssueCollector
) -> None:
    def visit(value: Any, path: str, field: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, f"{path}.{key}", str(key))
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]", field)
            return
        if (
            isinstance(value, str)
            and ("ref" in field.lower() or "version" in field.lower())
            and is_floating_version(value)
        ):
            issues.error(
                "CAPABILITY_PACK_FLOATING_VERSION_FORBIDDEN",
                path,
                "floating version aliases are forbidden",
            )

    visit(payload, "$", "")


def _find_core_overrides(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _TOP_LEVEL_FIELDS:
                found.add(key)
            found.update(_find_core_overrides(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_core_overrides(item))
    return found


__all__ = ["validate_capability_pack"]
