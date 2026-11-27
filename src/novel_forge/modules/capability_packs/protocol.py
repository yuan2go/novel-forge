"""CONSTRAINT: parsing accepts an exact JSON object before validation so one validation pass can report every authoring error."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .errors import CapabilityPackValidationIssue


class JsonKind(StrEnum):
    ANY = "any"
    ARRAY = "array"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    OBJECT = "object"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class JsonContract:
    kind: JsonKind
    nullable: bool = False
    properties: Mapping[str, "JsonContract"] = field(default_factory=dict)
    required: frozenset[str] = frozenset()
    items: "JsonContract | None" = None
    allow_unknown: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", MappingProxyType(dict(self.properties)))


def _value(kind: JsonKind, *, nullable: bool = False) -> JsonContract:
    return JsonContract(kind=kind, nullable=nullable)


def _array(items: JsonContract) -> JsonContract:
    return JsonContract(kind=JsonKind.ARRAY, items=items)


def _object(
    properties: Mapping[str, JsonContract] | None = None,
    *,
    required: frozenset[str] | None = None,
    allow_unknown: bool = False,
) -> JsonContract:
    fields = dict(properties or {})
    return JsonContract(
        kind=JsonKind.OBJECT,
        properties=fields,
        required=frozenset(fields) if required is None else required,
        allow_unknown=allow_unknown,
    )


ANY = _value(JsonKind.ANY)
BOOLEAN = _value(JsonKind.BOOLEAN)
INTEGER = _value(JsonKind.INTEGER)
NUMBER = _value(JsonKind.NUMBER)
STRING = _value(JsonKind.STRING)
NULLABLE_STRING = _value(JsonKind.STRING, nullable=True)
STRING_ARRAY = _array(STRING)
OPEN_OBJECT = _object(allow_unknown=True)


SKILL = _object(
    {
        "skill_ref": STRING,
        "version": STRING,
        "content_hash": STRING,
        "required": BOOLEAN,
        "input_contract_ref": STRING,
        "output_contract_ref": STRING,
        "preconditions": STRING_ARRAY,
        "postconditions": STRING_ARRAY,
        "depends_on": STRING_ARRAY,
        "max_invocations_per_run": INTEGER,
        "drift_policy": STRING,
    }
)

RETRY_POLICY = _object(
    {
        "max_attempts": INTEGER,
        "retryable_errors": STRING_ARRAY,
        "dead_letter_on_exhausted": BOOLEAN,
    }
)

APPROVAL = _object({"required": BOOLEAN, "policy_ref": NULLABLE_STRING})
COMPENSATION = _object({"supported": BOOLEAN, "policy_ref": NULLABLE_STRING})

WORKFLOW_NODE = _object(
    {
        "node_id": STRING,
        "operation_name": STRING,
        "operation_definition_ref": STRING,
        "operation_definition_hash": STRING,
        "handler_key": STRING,
        "stage": STRING,
        "capability_id": STRING,
        "agent_definition_ref": STRING,
        "input_asset_types": STRING_ARRAY,
        "output_asset_types": STRING_ARRAY,
        "depends_on": STRING_ARRAY,
        "retry_policy": RETRY_POLICY,
        "timeout_policy_ref": STRING,
        "approval": APPROVAL,
        "compensation": COMPENSATION,
        "commit_authority": STRING,
    },
    required=frozenset(
        {
            "node_id",
            "operation_name",
            "operation_definition_ref",
            "operation_definition_hash",
            "handler_key",
            "stage",
            "capability_id",
            "input_asset_types",
            "output_asset_types",
            "depends_on",
            "retry_policy",
            "timeout_policy_ref",
            "approval",
            "compensation",
        }
    ),
)

TOOL = _object(
    {
        "tool_ref": STRING,
        "permission": STRING,
        "allowed_operations": STRING_ARRAY,
        "risk_class": STRING,
        "approval_required": BOOLEAN,
        "audit_required": BOOLEAN,
        "budget_policy_ref": STRING,
    }
)

RULE_ASSET = _object(
    {
        "rule_ref": STRING,
        "version": STRING,
        "severity": STRING,
        "hard_constraint": BOOLEAN,
    }
)

EVALUATION_GATE = _object(
    {
        "gate_id": STRING,
        "judge_capability_id": STRING,
        "blocking": BOOLEAN,
        "threshold": NUMBER,
        "required_evidence": STRING_ARRAY,
    }
)

EVALUATION_METRIC = _object(
    {
        "metric_id": STRING,
        "type": STRING,
        "target": ANY,
        "aggregation": STRING,
    }
)

LONGFORM_BINDINGS = _object(
    {
        "book": STRING,
        "volume": STRING,
        "arc": STRING,
        "chapter_group": STRING,
        "chapter": STRING,
        "canon": STRING,
        "story_bible": STRING,
        "reader_feedback": STRING,
    },
    required=frozenset(),
)

CAPABILITY_PACK_V1_CONTRACT = _object(
    {
        "schema_version": STRING,
        "identity": _object(
            {
                "pack_id": STRING,
                "name": STRING,
                "domain": STRING,
                "capability_type": STRING,
                "version": STRING,
                "owner": STRING,
                "status": STRING,
                "lifecycle": STRING,
                "description": STRING,
            }
        ),
        "compatibility": _object(
            {
                "novel_forge_min_version": STRING,
                "novel_forge_max_version": NULLABLE_STRING,
                "protocol_min_version": STRING,
                "protocol_max_version": NULLABLE_STRING,
                "required_capabilities": STRING_ARRAY,
                "required_schema_versions": STRING_ARRAY,
                "incompatible_packs": STRING_ARRAY,
                "compatible_runtime_profiles": STRING_ARRAY,
            }
        ),
        "role": _object(
            {
                "role_type": STRING,
                "role_name": STRING,
                "responsibilities": STRING_ARRAY,
                "boundaries": STRING_ARRAY,
                "forbidden_actions": STRING_ARRAY,
                "upstream_packs": STRING_ARRAY,
                "downstream_packs": STRING_ARRAY,
                "authority_level": STRING,
            }
        ),
        "skill_binding": _object(
            {
                "mode": STRING,
                "selection_policy_ref": NULLABLE_STRING,
                "skills": _array(SKILL),
                "anti_drift": _object(
                    {
                        "duplicate_skill_refs_forbidden": BOOLEAN,
                        "unbound_skill_forbidden": BOOLEAN,
                        "dynamic_selection_requires_policy": BOOLEAN,
                    }
                ),
            },
            required=frozenset({"mode", "skills", "anti_drift"}),
        ),
        "prompt_binding": _object(
            {
                "prompt_bundle_type": STRING,
                "system_instruction_ref": STRING,
                "system_instruction_version": STRING,
                "system_instruction_hash": STRING,
                "template_ref": STRING,
                "template_version": STRING,
                "template_hash": STRING,
                "compiler_version": STRING,
                "input_schema_ref": STRING,
                "output_schema_ref": STRING,
            }
        ),
        "workflow_template": _object(
            {
                "workflow_id": STRING,
                "workflow_version": STRING,
                "execution_mode": STRING,
                "idempotency_scope": STRING,
                "nodes": _array(WORKFLOW_NODE),
                "completion": _object(
                    {
                        "required_terminal_nodes": STRING_ARRAY,
                        "required_evidence": STRING_ARRAY,
                        "required_output_asset_types": STRING_ARRAY,
                    }
                ),
            }
        ),
        "context_sources": _object(
            {
                "policy_id": STRING,
                "max_tokens": INTEGER,
                "planning_task_token_budget": INTEGER,
                "capacity_policy": STRING,
                "context_substage_method": STRING,
                "capacity_history_exact_chapters": INTEGER,
                "source_isolation": STRING,
                "allowed_asset_types": STRING_ARRAY,
                "forbidden_asset_types": STRING_ARRAY,
                "required_version_refs": STRING_ARRAY,
                "priority": STRING_ARRAY,
                "freshness": _object(
                    {
                        "reject_stale": BOOLEAN,
                        "reject_cross_project": BOOLEAN,
                        "reject_unqualified": BOOLEAN,
                    }
                ),
                "longform_bindings": LONGFORM_BINDINGS,
            },
            required=frozenset({"policy_id", "max_tokens", "source_isolation", "allowed_asset_types",
                "forbidden_asset_types", "required_version_refs", "priority", "freshness", "longform_bindings"}),
        ),
        "tool_permissions": _object(
            {
                "policy_id": STRING,
                "default": STRING,
                "tools": _array(TOOL),
                "database": _object(
                    {
                        "read_allowed": BOOLEAN,
                        "write_allowed": BOOLEAN,
                        "allowed_tables": STRING_ARRAY,
                        "forbidden_tables": STRING_ARRAY,
                    }
                ),
                "files": _object(
                    {
                        "read_allowed": BOOLEAN,
                        "write_allowed": BOOLEAN,
                        "allowed_roots": STRING_ARRAY,
                    }
                ),
                "external_models": _object(
                    {"allowed": BOOLEAN, "route_policy_ref": NULLABLE_STRING,
                     "context_substages": STRING_ARRAY},
                    required=frozenset({"allowed", "route_policy_ref"}),
                ),
                "retrieval": _object(
                    {"allowed": BOOLEAN, "source_policy_ref": NULLABLE_STRING}
                ),
            }
        ),
        "assets": _object(
            {
                "knowledge": _object(
                    {
                        "required_packs": STRING_ARRAY,
                        "allowed_usage_roles": STRING_ARRAY,
                        "project_knowledge_pack": _object(
                            {
                                "default_requirement": STRING,
                                "required_stages": STRING_ARRAY,
                                "required_capability_ids": STRING_ARRAY,
                            }
                        ),
                    }
                ),
                "rules": _array(RULE_ASSET),
                "templates": _array(OPEN_OBJECT),
                "source_policy": _object(
                    {
                        "allowed_eligibility": STRING_ARRAY,
                        "raw_source_expression_allowed": BOOLEAN,
                        "requires_lineage": BOOLEAN,
                    }
                ),
            }
        ),
        "evaluation": _object(
            {
                "evaluation_id": STRING,
                "required_gates": _array(EVALUATION_GATE),
                "metrics": _array(EVALUATION_METRIC),
                "failure_policy": _object(
                    {
                        "acceptable_failures": STRING_ARRAY,
                        "retryable_failures": STRING_ARRAY,
                        "terminal_failures": STRING_ARRAY,
                    }
                ),
            }
        ),
        "runtime_contract": _object(
            {
                "input_protocol_ref": STRING,
                "output_protocol_ref": STRING,
                "error_protocol_ref": STRING,
                "state_protocol_ref": STRING,
                "event_protocol_ref": STRING,
                "audit_protocol_ref": STRING,
                "rollback_protocol_ref": STRING,
                "commit_policy_ref": STRING,
                "validation_policy_ref": STRING,
                "execution": _object(
                    {
                        "binds_authority_operation": BOOLEAN,
                        "binds_attempt_fence": BOOLEAN,
                        "external_effects_allowed": BOOLEAN,
                        "synchronous_fixture_allowed": BOOLEAN,
                    }
                ),
            }
        ),
        "governance": _object(
            {
                "release_channel": STRING,
                "approval_policy_ref": STRING,
                "versioning": _object(
                    {
                        "compatibility": STRING,
                        "migration_required": BOOLEAN,
                        "migration_policy_ref": NULLABLE_STRING,
                    }
                ),
                "rollout": _object({"mode": STRING, "canary_percent": INTEGER}),
                "rollback": _object(
                    {"allowed": BOOLEAN, "policy_ref": NULLABLE_STRING}
                ),
                "cost_tracking": _object(
                    {"required": BOOLEAN, "budget_policy_ref": NULLABLE_STRING}
                ),
                "quality_tracking": _object(
                    {"required": BOOLEAN, "report_refs": STRING_ARRAY}
                ),
                "deprecation": _object(
                    {
                        "replacement_pack_id": NULLABLE_STRING,
                        "retirement_deadline": NULLABLE_STRING,
                    }
                ),
            }
        ),
        "audit": _object(
            {
                "audit_level": STRING,
                "record_operation_snapshot": BOOLEAN,
                "record_pack_manifest_hash": BOOLEAN,
                "record_input_manifest": BOOLEAN,
                "record_route_snapshot": BOOLEAN,
                "record_tool_calls": BOOLEAN,
                "record_cost_receipts": BOOLEAN,
                "record_evaluation_results": BOOLEAN,
            }
        ),
        "ext": _object(
            {
                "ui": OPEN_OBJECT,
                "enterprise": OPEN_OBJECT,
                "experiments": OPEN_OBJECT,
                "vendor": OPEN_OBJECT,
            },
            required=frozenset(),
        ),
    }
)


def validate_protocol_contract(
    payload: Mapping[str, Any],
) -> tuple[CapabilityPackValidationIssue, ...]:
    issues: list[CapabilityPackValidationIssue] = []
    _validate_value(payload, CAPABILITY_PACK_V1_CONTRACT, "$", issues)
    return tuple(issues)


def _validate_value(
    value: Any,
    contract: JsonContract,
    path: str,
    issues: list[CapabilityPackValidationIssue],
) -> None:
    if value is None and contract.nullable:
        return
    if contract.kind is JsonKind.ANY:
        return
    if not _matches_kind(value, contract.kind):
        issues.append(
            CapabilityPackValidationIssue(
                code="CAPABILITY_PACK_PROTOCOL_INVALID",
                path=path,
                message=f"field must be {contract.kind.value}",
                severity="ERROR",
            )
        )
        return
    if contract.kind is JsonKind.OBJECT:
        _validate_object(value, contract, path, issues)
    elif contract.kind is JsonKind.ARRAY and contract.items is not None:
        for index, item in enumerate(value):
            _validate_value(item, contract.items, f"{path}[{index}]", issues)


def _validate_object(
    value: Mapping[str, Any],
    contract: JsonContract,
    path: str,
    issues: list[CapabilityPackValidationIssue],
) -> None:
    for field_name in sorted(contract.required - set(value)):
        issues.append(
            CapabilityPackValidationIssue(
                code="CAPABILITY_PACK_REQUIRED_FIELD_MISSING",
                path=f"{path}.{field_name}",
                message="required protocol field is missing",
                severity="ERROR",
            )
        )
    if not contract.allow_unknown:
        for field_name in sorted(set(value) - set(contract.properties)):
            issues.append(
                CapabilityPackValidationIssue(
                    code="CAPABILITY_PACK_PROTOCOL_INVALID",
                    path=f"{path}.{field_name}",
                    message="unknown core protocol field must use an ext namespace",
                    severity="ERROR",
                )
            )
    for field_name, field_contract in contract.properties.items():
        if field_name in value:
            _validate_value(
                value[field_name],
                field_contract,
                f"{path}.{field_name}",
                issues,
            )


def _matches_kind(value: Any, kind: JsonKind) -> bool:
    if kind is JsonKind.OBJECT:
        return isinstance(value, dict)
    if kind is JsonKind.ARRAY:
        return isinstance(value, list)
    if kind is JsonKind.STRING:
        return isinstance(value, str)
    if kind is JsonKind.BOOLEAN:
        return isinstance(value, bool)
    if kind is JsonKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is JsonKind.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


__all__ = [
    "CAPABILITY_PACK_V1_CONTRACT",
    "JsonContract",
    "JsonKind",
    "validate_protocol_contract",
]
