from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
from typing import Any

from novel_forge.modules.production_execution.capability_registry import (
    CapabilityRegistry,
)

from .artifacts import (
    ArtifactKind,
    ArtifactResolver,
    ResolvedArtifact,
    exact_ref_version,
)
from .errors import CapabilityPackCompilationIssue, CapabilityPackResolutionReport
from .operation_catalog import (
    OperationDefinitionCatalog,
    ResolvedOperationDefinition,
    WorkflowBindingCatalog,
)
from .schema import CapabilityPackManifest
from .type_catalog import (
    CapabilityTypePolicyCatalog,
    ToolDefinitionCatalog,
)


_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass(frozen=True, slots=True)
class SemanticResolution:
    report: CapabilityPackResolutionReport
    operations: tuple[ResolvedOperationDefinition, ...]
    artifacts: tuple[ResolvedArtifact, ...]
    capability_ids: tuple[str, ...]


class _Issues:
    def __init__(self) -> None:
        self.errors: list[CapabilityPackCompilationIssue] = []
        self.warnings: list[CapabilityPackCompilationIssue] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append(CapabilityPackCompilationIssue(code, path, message))

    def warning(self, code: str, path: str, message: str) -> None:
        self.warnings.append(
            CapabilityPackCompilationIssue(code, path, message, "WARNING")
        )


def validate_capability_pack_semantics(
    manifest: CapabilityPackManifest,
    *,
    capability_registry: CapabilityRegistry,
    capability_type_catalog: CapabilityTypePolicyCatalog,
    operation_catalog: OperationDefinitionCatalog,
    workflow_catalog: WorkflowBindingCatalog,
    artifact_resolver: ArtifactResolver,
    tool_catalog: ToolDefinitionCatalog,
) -> SemanticResolution:
    issues = _Issues()
    operations: dict[tuple[str, str], ResolvedOperationDefinition] = {}
    artifacts: dict[tuple[str, str, str], ResolvedArtifact] = {}
    capabilities: dict[str, Any] = {}

    try:
        type_policy = capability_type_catalog.resolve(
            str(manifest.identity.capability_type)
        )
    except KeyError as exc:
        issues.error(
            "CAPABILITY_PACK_CAPABILITY_TYPE_UNKNOWN",
            "$.identity.capability_type",
            str(exc),
        )
        type_policy = None
    if type_policy is not None:
        triple = (
            str(manifest.identity.status),
            str(manifest.identity.lifecycle),
            str(manifest.governance.release_channel),
        )
        if triple not in type_policy.allowed_status_lifecycle_channels:
            issues.error(
                "CAPABILITY_PACK_LIFECYCLE_CONFLICT",
                "$.identity",
                "status, lifecycle, and release_channel are not a governed combination",
            )
        execution = manifest.runtime_contract.execution
        if (
            type_policy.requires_authority_operation
            and execution.get("binds_authority_operation") is not True
        ):
            issues.error(
                "CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED",
                "$.runtime_contract.execution.binds_authority_operation",
                "capability type requires Authority Operation binding",
            )
        if (
            type_policy.requires_attempt_fence
            and execution.get("binds_attempt_fence") is not True
        ):
            issues.error(
                "CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED",
                "$.runtime_contract.execution.binds_attempt_fence",
                "capability type requires Attempt fencing",
            )
        if manifest.audit.audit_level != type_policy.required_audit_level:
            issues.error(
                "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                "$.audit.audit_level",
                "audit level is weaker than the Capability Type policy",
            )

    if (
        manifest.workflow_template.workflow_id != workflow_catalog.workflow_id
        or manifest.workflow_template.workflow_version
        != workflow_catalog.workflow_version
    ):
        issues.error(
            "CAPABILITY_PACK_OPERATION_DEFINITION_NOT_FOUND",
            "$.workflow_template",
            "workflow identity has no governed Authority binding",
        )
    actual_node_ids = {str(node.node_id) for node in manifest.workflow_template.nodes}
    governed_node_ids = {item.node_id for item in workflow_catalog.bindings()}
    if actual_node_ids != governed_node_ids:
        issues.error(
            "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
            "$.workflow_template.nodes",
            "workflow nodes differ from the governed Authority graph",
        )

    operation_by_node: dict[str, ResolvedOperationDefinition] = {}
    authoritative_outputs: dict[str, set[str]] = {}
    for index, node in enumerate(manifest.workflow_template.nodes):
        path = f"$.workflow_template.nodes[{index}]"
        ref = str(node.operation_definition_ref)
        name, separator, version = ref.rpartition("@")
        if not separator:
            issues.error(
                "CAPABILITY_PACK_OPERATION_DEFINITION_NOT_FOUND",
                f"{path}.operation_definition_ref",
                "operation definition ref is not exact",
            )
            continue
        try:
            operation = operation_catalog.resolve(name, version)
        except KeyError as exc:
            issues.error(
                "CAPABILITY_PACK_OPERATION_DEFINITION_NOT_FOUND",
                f"{path}.operation_definition_ref",
                str(exc),
            )
            continue
        operations[(operation.definition_name, operation.definition_version)] = (
            operation
        )
        operation_by_node[str(node.node_id)] = operation
        if not operation.enabled:
            issues.error(
                "CAPABILITY_PACK_OPERATION_DEFINITION_DISABLED",
                f"{path}.operation_definition_ref",
                "disabled OperationDefinition cannot be compiled",
            )
        if operation.definition_hash != node.operation_definition_hash:
            issues.error(
                "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
                f"{path}.operation_definition_hash",
                "Authority OperationDefinition content hash differs from the Manifest constraint",
            )
        try:
            binding = workflow_catalog.resolve(str(node.node_id))
        except KeyError as exc:
            issues.error(
                "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
                f"{path}.node_id",
                str(exc),
            )
            continue
        expected = {
            "operation_name": binding.operation_name,
            "stage": binding.stage,
            "handler_key": binding.handler_key,
            "capability_id": binding.capability_id,
            "depends_on": binding.depends_on,
        }
        actual = {
            "operation_name": node.operation_name,
            "stage": node.stage,
            "handler_key": node.handler_key,
            "capability_id": node.capability_id,
            "depends_on": node.depends_on,
        }
        for field, expected_value in expected.items():
            if actual[field] != expected_value:
                issues.error(
                    "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
                    f"{path}.{field}",
                    "Manifest binding differs from the current Authority/Scheduler contract",
                )
        retry = json.loads(operation.retry_policy_json)
        if (
            node.retry_policy.max_attempts != retry.get("max_attempts")
            or node.retry_policy.retryable_errors
            or node.retry_policy.dead_letter_on_exhausted is not True
        ):
            issues.error(
                "CAPABILITY_PACK_OPERATION_POLICY_CONFLICT",
                f"{path}.retry_policy",
                "Manifest retry constraints differ from the Authority retry policy",
            )
        approval = json.loads(operation.approval_policy_json)
        if node.approval.get("required") is not approval.get("required"):
            issues.error(
                "CAPABILITY_PACK_OPERATION_POLICY_CONFLICT",
                f"{path}.approval.required",
                "Manifest admission approval differs from OperationDefinition",
            )
        compensation = json.loads(operation.compensation_policy_json)
        if node.compensation.get("supported") is not compensation.get("supported"):
            issues.error(
                "CAPABILITY_PACK_OPERATION_POLICY_CONFLICT",
                f"{path}.compensation.supported",
                "Manifest compensation differs from OperationDefinition",
            )
        completion = json.loads(operation.completion_contract_json)
        selectors = {
            str(item.get("selector"))
            for item in completion.get("required_asset_selectors", [])
            if isinstance(item, dict) and item.get("selector")
        }
        authoritative_outputs[str(node.node_id)] = selectors
        if binding.primary_output_asset_type and (
            binding.primary_output_asset_type not in node.output_asset_types
            or binding.primary_output_asset_type not in selectors
        ):
            issues.error(
                "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
                f"{path}.output_asset_types",
                "primary output differs from Authority completion selectors",
            )

    required_capabilities = {
        str(item) for item in manifest.compatibility.required_capabilities
    }
    used_capabilities = {
        str(node.capability_id) for node in manifest.workflow_template.nodes
    } | {str(gate.judge_capability_id) for gate in manifest.evaluation.required_gates}
    missing_capabilities = sorted(used_capabilities - required_capabilities)
    if missing_capabilities:
        issues.error(
            "CAPABILITY_PACK_CAPABILITY_SET_INCOMPLETE",
            "$.compatibility.required_capabilities",
            "required_capabilities omits used capabilities: "
            + ", ".join(missing_capabilities),
        )
    unused_capabilities = sorted(required_capabilities - used_capabilities)
    if unused_capabilities:
        issues.warning(
            "CAPABILITY_PACK_CAPABILITY_SET_UNUSED",
            "$.compatibility.required_capabilities",
            "declared capabilities are unused: " + ", ".join(unused_capabilities),
        )
    for capability_id in sorted(required_capabilities | used_capabilities):
        try:
            capabilities[capability_id] = capability_registry.resolve(capability_id)
        except ValueError as exc:
            issues.error(
                "CAPABILITY_PACK_CAPABILITY_UNKNOWN",
                "$.compatibility.required_capabilities",
                str(exc),
            )

    _validate_asset_flow(manifest, authoritative_outputs, issues)
    _validate_tools(manifest, operation_by_node, tool_catalog, issues)

    def resolve(
        kind: ArtifactKind, ref: str, version: str | None = None, path: str = "$"
    ) -> ResolvedArtifact | None:
        try:
            resolved = artifact_resolver.resolve(
                kind, ref, version or exact_ref_version(ref)
            )
        except ValueError as exc:
            issues.error("CAPABILITY_PACK_FLOATING_VERSION_FORBIDDEN", path, str(exc))
            return None
        except TypeError as exc:
            issues.error("CAPABILITY_PACK_ARTIFACT_KIND_MISMATCH", path, str(exc))
            return None
        except KeyError as exc:
            issues.error("CAPABILITY_PACK_ARTIFACT_NOT_FOUND", path, str(exc))
            return None
        except LookupError as exc:
            issues.error("CAPABILITY_PACK_ARTIFACT_VERSION_UNRESOLVED", path, str(exc))
            return None
        artifacts[(kind.value, ref, resolved.version)] = resolved
        return resolved

    for index, skill in enumerate(manifest.skill_binding.skills):
        item = resolve(
            ArtifactKind.SKILL,
            str(skill.skill_ref),
            str(skill.version),
            f"$.skill_binding.skills[{index}]",
        )
        if item is not None and item.content_hash != skill.content_hash:
            issues.error(
                "CAPABILITY_PACK_ARTIFACT_HASH_MISMATCH",
                f"$.skill_binding.skills[{index}].content_hash",
                "Skill content hash differs from the resolved repository file",
            )
        resolve(
            ArtifactKind.SCHEMA,
            str(skill.input_contract_ref),
            path=f"$.skill_binding.skills[{index}].input_contract_ref",
        )
        resolve(
            ArtifactKind.SCHEMA,
            str(skill.output_contract_ref),
            path=f"$.skill_binding.skills[{index}].output_contract_ref",
        )
    prompt = manifest.prompt_binding
    system = resolve(
        ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
        str(prompt.system_instruction_ref),
        str(prompt.system_instruction_version),
        "$.prompt_binding.system_instruction_ref",
    )
    template = resolve(
        ArtifactKind.PROMPT_TEMPLATE,
        str(prompt.template_ref),
        str(prompt.template_version),
        "$.prompt_binding.template_ref",
    )
    if system is not None and system.content_hash != prompt.system_instruction_hash:
        issues.error(
            "CAPABILITY_PACK_ARTIFACT_HASH_MISMATCH",
            "$.prompt_binding.system_instruction_hash",
            "system instruction hash differs from resolved content",
        )
    if template is not None and template.content_hash != prompt.template_hash:
        issues.error(
            "CAPABILITY_PACK_ARTIFACT_HASH_MISMATCH",
            "$.prompt_binding.template_hash",
            "template hash differs from resolved content",
        )
    resolve(
        ArtifactKind.SCHEMA,
        str(prompt.input_schema_ref),
        path="$.prompt_binding.input_schema_ref",
    )
    resolve(
        ArtifactKind.SCHEMA,
        str(prompt.output_schema_ref),
        path="$.prompt_binding.output_schema_ref",
    )

    for ref in manifest.compatibility.required_schema_versions:
        resolve(
            ArtifactKind.SCHEMA,
            str(ref),
            path="$.compatibility.required_schema_versions",
        )
    context_policy = resolve(
        ArtifactKind.CONTEXT_POLICY,
        str(manifest.context_sources.policy_id),
        path="$.context_sources.policy_id",
    )
    if context_policy is not None:
        policy_content = json.loads(context_policy.content_json)
        context_expectations = {
            "max_tokens": manifest.context_sources.max_tokens,
            "source_isolation": manifest.context_sources.source_isolation,
            "reject_cross_project": manifest.context_sources.freshness.get(
                "reject_cross_project"
            ),
        }
        target = manifest.context_sources.planning_task_token_budget
        history_exact = manifest.context_sources.capacity_history_exact_chapters
        if history_exact is not None:
            context_expectations["capacity_history_exact_chapters"] = history_exact
        for field in ("capacity_policy", "context_substage_method"):
            value = getattr(manifest.context_sources, field)
            if value:
                context_expectations[field] = value
        if target is not None:
            if type(target) is not int or type(manifest.context_sources.max_tokens) is not int or not 0 < target <= min(512000, manifest.context_sources.max_tokens):
                issues.error("CAPABILITY_PACK_CONTEXT_TARGET_INVALID", "$.context_sources.planning_task_token_budget", "Planning Context target must be bounded by the system ceiling")
            context_expectations["planning_task_token_budget"] = target
        for field, expected in context_expectations.items():
            if policy_content.get(field) != expected:
                issues.error(
                    "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                    f"$.context_sources.{field}",
                    "Manifest context constraint differs from the resolved policy",
                )
        for field, expected in (
            ("allowed_asset_types", manifest.context_sources.allowed_asset_types),
            ("forbidden_asset_types", manifest.context_sources.forbidden_asset_types),
            ("required_version_refs", manifest.context_sources.required_version_refs),
        ):
            if sorted(str(item) for item in policy_content.get(field, ())) != sorted(
                str(item) for item in expected
            ):
                issues.error(
                    "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                    f"$.context_sources.{field}",
                    "Manifest context set differs from the resolved policy",
                )
    tool_policy = resolve(
        ArtifactKind.TOOL_POLICY,
        str(manifest.tool_permissions.policy_id),
        path="$.tool_permissions.policy_id",
    )
    if tool_policy is not None:
        policy_content = json.loads(tool_policy.content_json)
        if policy_content.get("default") != manifest.tool_permissions.default:
            issues.error(
                "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                "$.tool_permissions.default",
                "Manifest tool default differs from the resolved policy",
            )
        if sorted(policy_content.get("explicit_tool_refs", ())) != sorted(
            str(tool.tool_ref) for tool in manifest.tool_permissions.tools
        ):
            issues.error(
                "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                "$.tool_permissions.tools",
                "Manifest Tool bindings differ from the resolved policy",
            )
    for index, tool in enumerate(manifest.tool_permissions.tools):
        resolve(
            ArtifactKind.BUDGET_POLICY,
            str(tool.budget_policy_ref),
            path=f"$.tool_permissions.tools[{index}].budget_policy_ref",
        )
    if manifest.tool_permissions.external_models.get("allowed") is True:
        resolve(
            ArtifactKind.APPROVAL_POLICY,
            str(manifest.tool_permissions.external_models.get("route_policy_ref")),
            path="$.tool_permissions.external_models.route_policy_ref",
        )
    if manifest.tool_permissions.retrieval.get("allowed") is True:
        source_policy = resolve(
            ArtifactKind.SOURCE_POLICY,
            str(manifest.tool_permissions.retrieval.get("source_policy_ref")),
            path="$.tool_permissions.retrieval.source_policy_ref",
        )
        if source_policy is not None:
            policy_content = json.loads(source_policy.content_json)
            source_expectations = {
                "raw_source_expression_allowed": manifest.assets.source_policy.get(
                    "raw_source_expression_allowed"
                ),
                "requires_lineage": manifest.assets.source_policy.get(
                    "requires_lineage"
                ),
            }
            for field, expected in source_expectations.items():
                if policy_content.get(field) != expected:
                    issues.error(
                        "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                        f"$.assets.source_policy.{field}",
                        "Manifest source constraint differs from the resolved policy",
                    )
            if sorted(policy_content.get("allowed_eligibility", ())) != sorted(
                str(item)
                for item in manifest.assets.source_policy.get("allowed_eligibility", ())
            ):
                issues.error(
                    "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                    "$.assets.source_policy.allowed_eligibility",
                    "Manifest source eligibility differs from the resolved policy",
                )
    for index, node in enumerate(manifest.workflow_template.nodes):
        path = f"$.workflow_template.nodes[{index}]"
        timeout_artifact = resolve(
            ArtifactKind.TIMEOUT_POLICY,
            str(node.timeout_policy_ref),
            path=f"{path}.timeout_policy_ref",
        )
        approval_artifact = resolve(
            ArtifactKind.APPROVAL_POLICY,
            str(node.approval.get("policy_ref")),
            path=f"{path}.approval.policy_ref",
        )
        compensation_artifact = resolve(
            ArtifactKind.COMPENSATION_POLICY,
            str(node.compensation.get("policy_ref")),
            path=f"{path}.compensation.policy_ref",
        )
        operation = operation_by_node.get(str(node.node_id))
        if operation is not None and timeout_artifact is not None:
            if json.loads(timeout_artifact.content_json).get(
                "operation_timeout_seconds"
            ) != json.loads(operation.timeout_policy_json).get(
                "operation_timeout_seconds"
            ):
                issues.error(
                    "CAPABILITY_PACK_OPERATION_POLICY_CONFLICT",
                    f"{path}.timeout_policy_ref",
                    "resolved timeout policy differs from OperationDefinition",
                )
        if operation is not None and approval_artifact is not None:
            if json.loads(approval_artifact.content_json).get(
                "operation_admission_approval_required"
            ) is not json.loads(operation.approval_policy_json).get("required"):
                issues.error(
                    "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                    f"{path}.approval.policy_ref",
                    "resolved approval policy differs from OperationDefinition",
                )
        if operation is not None and compensation_artifact is not None:
            if json.loads(compensation_artifact.content_json).get(
                "supported"
            ) is not json.loads(operation.compensation_policy_json).get("supported"):
                issues.error(
                    "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                    f"{path}.compensation.policy_ref",
                    "resolved compensation policy differs from OperationDefinition",
                )
    runtime = manifest.runtime_contract
    for field in (
        "input_protocol_ref",
        "output_protocol_ref",
        "error_protocol_ref",
        "state_protocol_ref",
        "event_protocol_ref",
        "audit_protocol_ref",
        "rollback_protocol_ref",
    ):
        resolve(
            ArtifactKind.PROTOCOL,
            str(getattr(runtime, field)),
            path=f"$.runtime_contract.{field}",
        )
    resolve(
        ArtifactKind.COMMIT_POLICY,
        str(runtime.commit_policy_ref),
        path="$.runtime_contract.commit_policy_ref",
    )
    resolve(
        ArtifactKind.VALIDATION_POLICY,
        str(runtime.validation_policy_ref),
        path="$.runtime_contract.validation_policy_ref",
    )
    resolve(
        ArtifactKind.APPROVAL_POLICY,
        str(manifest.governance.approval_policy_ref),
        path="$.governance.approval_policy_ref",
    )
    resolve(
        ArtifactKind.COMPENSATION_POLICY,
        str(manifest.governance.rollback.get("policy_ref")),
        path="$.governance.rollback.policy_ref",
    )
    resolve(
        ArtifactKind.BUDGET_POLICY,
        str(manifest.governance.cost_tracking.get("budget_policy_ref")),
        path="$.governance.cost_tracking.budget_policy_ref",
    )
    for index, rule in enumerate(manifest.assets.rules):
        rule_artifact = resolve(
            ArtifactKind.RULE,
            f"{rule.get('rule_ref')}:{rule.get('version')}",
            path=f"$.assets.rules[{index}]",
        )
        if rule_artifact is not None:
            rule_content = json.loads(rule_artifact.content_json)
            if rule_content.get("severity") != rule.get("severity") or rule_content.get(
                "hard_constraint"
            ) is not rule.get("hard_constraint"):
                issues.error(
                    "CAPABILITY_PACK_POLICY_BINDING_INVALID",
                    f"$.assets.rules[{index}]",
                    "Manifest Rule binding differs from the resolved rule",
                )
    for index, pack_ref in enumerate(
        manifest.assets.knowledge.get("required_packs") or ()
    ):
        resolve(
            ArtifactKind.KNOWLEDGE,
            str(pack_ref),
            path=f"$.assets.knowledge.required_packs[{index}]",
        )
    for index, template_binding in enumerate(manifest.assets.templates):
        ref = str(template_binding.get("template_ref") or "")
        version = str(template_binding.get("version") or "")
        resolve(
            ArtifactKind.TEMPLATE,
            ref,
            version,
            path=f"$.assets.templates[{index}]",
        )

    report = CapabilityPackResolutionReport(
        ok=not issues.errors,
        pack_id=str(manifest.identity.pack_id),
        version=str(manifest.identity.version),
        manifest_hash=manifest.manifest_hash,
        errors=tuple(issues.errors),
        warnings=tuple(issues.warnings),
        resolved_artifacts=tuple(
            sorted(f"{key[0]}:{key[1]}@{key[2]}" for key in artifacts)
        ),
        resolved_operations=tuple(
            f"{name}@{version}" for name, version in sorted(operations)
        ),
        resolved_capabilities=tuple(sorted(capabilities)),
    )
    return SemanticResolution(
        report,
        tuple(operations[key] for key in sorted(operations)),
        tuple(artifacts[key] for key in sorted(artifacts)),
        tuple(sorted(capabilities)),
    )


def _validate_asset_flow(
    manifest: CapabilityPackManifest,
    authoritative_outputs: dict[str, set[str]],
    issues: _Issues,
) -> None:
    nodes = {str(node.node_id): node for node in manifest.workflow_template.nodes}
    external = {str(item) for item in manifest.context_sources.allowed_asset_types}
    ancestors: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def collect(node_id: str) -> set[str]:
        if node_id in ancestors:
            return ancestors[node_id]
        if node_id in visiting:
            return set()  # WHY: the static DAG validator reports the cycle
        visiting.add(node_id)
        value: set[str] = set()
        for dependency in nodes[node_id].depends_on:
            if str(dependency) in nodes:
                value.add(str(dependency))
                value.update(collect(str(dependency)))
        visiting.remove(node_id)
        ancestors[node_id] = value
        return value

    for node_id, node in nodes.items():
        available = set(external)
        for ancestor in collect(node_id):
            available.update(authoritative_outputs.get(ancestor, set()))
        missing = sorted(set(str(item) for item in node.input_asset_types) - available)
        if missing:
            issues.error(
                "CAPABILITY_PACK_WORKFLOW_INPUT_UNSATISFIED",
                f"workflow:{node_id}.input_asset_types",
                "workflow inputs have no ancestor or external producer: "
                + ", ".join(missing),
            )
    produced = (
        set().union(*authoritative_outputs.values()) if authoritative_outputs else set()
    )
    missing_outputs = sorted(
        set(
            str(item)
            for item in manifest.workflow_template.completion.required_output_asset_types
        )
        - produced
    )
    if missing_outputs:
        issues.error(
            "CAPABILITY_PACK_COMPLETION_OUTPUT_UNPRODUCED",
            "$.workflow_template.completion.required_output_asset_types",
            "completion output has no Authority producer: "
            + ", ".join(missing_outputs),
        )
    generic_evidence = {"trace", "audit"}
    for index, gate in enumerate(manifest.evaluation.required_gates):
        missing = sorted(
            set(str(item) for item in gate.required_evidence)
            - produced
            - generic_evidence
        )
        if missing:
            issues.error(
                "CAPABILITY_PACK_EVALUATION_EVIDENCE_UNPRODUCED",
                f"$.evaluation.required_gates[{index}].required_evidence",
                "evaluation evidence has no Authority producer: " + ", ".join(missing),
            )
        if gate.blocking is True:
            completion_chain = set(
                str(item)
                for item in manifest.workflow_template.completion.required_evidence
            ) | set(
                str(item)
                for item in manifest.workflow_template.completion.required_output_asset_types
            )
            consumed = {
                str(item) for node in nodes.values() for item in node.input_asset_types
            }
            if not set(str(item) for item in gate.required_evidence) & (
                completion_chain | consumed
            ):
                issues.error(
                    "CAPABILITY_PACK_EVALUATION_EVIDENCE_UNPRODUCED",
                    f"$.evaluation.required_gates[{index}]",
                    "blocking gate is not connected to completion or a downstream decision",
                )


def _validate_tools(
    manifest: CapabilityPackManifest,
    operation_by_node: dict[str, ResolvedOperationDefinition],
    tool_catalog: ToolDefinitionCatalog,
    issues: _Issues,
) -> None:
    covered_external_capabilities: set[tuple[str, str]] = set()
    for index, tool in enumerate(manifest.tool_permissions.tools):
        path = f"$.tool_permissions.tools[{index}]"
        try:
            definition = tool_catalog.resolve(str(tool.tool_ref))
        except KeyError as exc:
            issues.error(
                "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT", f"{path}.tool_ref", str(exc)
            )
            continue
        if (
            _RISK_ORDER.get(str(tool.risk_class), -1)
            < _RISK_ORDER[definition.minimum_risk_class]
        ):
            issues.error(
                "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
                f"{path}.risk_class",
                "tool risk is lower than the governed ToolDefinition",
            )
        if str(tool.permission) not in definition.allowed_permissions:
            issues.error(
                "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
                f"{path}.permission",
                "tool action is not authorized by the governed ToolDefinition",
            )
        if definition.audit_required and tool.audit_required is not True:
            issues.error(
                "CAPABILITY_PACK_HIGH_RISK_TOOL_AUDIT_REQUIRED",
                f"{path}.audit_required",
                "ToolDefinition requires audit",
            )
        if definition.approval_required and tool.approval_required is not True:
            issues.error(
                "CAPABILITY_PACK_CRITICAL_TOOL_APPROVAL_REQUIRED",
                f"{path}.approval_required",
                "ToolDefinition requires approval",
            )
        for node_id in tool.allowed_operations:
            operation = operation_by_node.get(str(node_id))
            if operation is None:
                issues.error(
                    "CAPABILITY_PACK_TOOL_OPERATION_UNKNOWN",
                    f"{path}.allowed_operations",
                    f"tool operation is not resolved: {node_id}",
                )
                continue
            if not any(
                fnmatch.fnmatch(capability, pattern)
                for capability in operation.external_capabilities
                for pattern in definition.external_capability_patterns
            ):
                issues.error(
                    "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
                    f"{path}.allowed_operations",
                    f"OperationDefinition does not authorize {tool.tool_ref}: {node_id}",
                )
            else:
                covered_external_capabilities.update(
                    (str(node_id), capability)
                    for capability in operation.external_capabilities
                    if any(
                        fnmatch.fnmatch(capability, pattern)
                        for pattern in definition.external_capability_patterns
                    )
                )
    for node_id, operation in sorted(operation_by_node.items()):
        missing = sorted(
            capability
            for capability in operation.external_capabilities
            if (node_id, capability) not in covered_external_capabilities
        )
        if missing:
            issues.error(
                "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
                f"workflow:{node_id}.external_capabilities",
                "OperationDefinition external capabilities have no explicit Tool binding: "
                + ", ".join(missing),
            )


__all__ = ["SemanticResolution", "validate_capability_pack_semantics"]
