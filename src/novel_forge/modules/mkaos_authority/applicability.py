from __future__ import annotations

from typing import Any, Mapping
import math
import re

from novel_forge.modules.command_kernel.errors import KernelError


USAGE_ROLES = frozenset({"INSPIRATION", "MECHANISM", "CONSTRAINT", "REVIEW_CHECK"})
OPERATORS = frozenset({"EQ", "NE", "GT", "GTE", "LT", "LTE", "IN", "CONTAINS"})


def validate_applicability_contract(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema_version",
            "usage_role",
            "prerequisites",
            "exceptions",
            "hard_conflicts",
        }
        or value.get("schema_version") != "knowledge-applicability.v1"
        or value.get("usage_role") not in USAGE_ROLES
    ):
        raise KernelError(
            "MKAOS_APPLICABILITY_INVALID", "invalid applicability contract"
        )
    seen: set[str] = set()
    for group in ("prerequisites", "exceptions", "hard_conflicts"):
        predicates = value[group]
        if not isinstance(predicates, list) or len(predicates) > 100:
            raise KernelError(
                "MKAOS_APPLICABILITY_INVALID",
                "predicate group must contain at most 100 conditions",
            )
        for predicate in predicates:
            if not isinstance(predicate, Mapping) or set(predicate) != {
                "condition_id",
                "path",
                "operator",
                "value",
            }:
                raise KernelError(
                    "MKAOS_APPLICABILITY_INVALID", "predicate shape is invalid"
                )
            identity, path, operator = (
                predicate["condition_id"],
                predicate["path"],
                predicate["operator"],
            )
            if (
                not isinstance(identity, str)
                or not identity.strip()
                or identity in seen
                or not isinstance(path, str)
                or not path.startswith("/")
                or re.search(r"~(?![01])", path)
                or operator not in OPERATORS
            ):
                raise KernelError(
                    "MKAOS_APPLICABILITY_INVALID",
                    "predicate identity, path or operator is invalid",
                )
            expected = predicate["value"]
            if (
                isinstance(expected, dict)
                or expected is None
                or not isinstance(expected, (str, int, float, bool, list))
                or (
                    isinstance(expected, list)
                    and any(
                        not isinstance(item, (str, int, float, bool))
                        for item in expected
                    )
                )
            ):
                raise KernelError(
                    "MKAOS_APPLICABILITY_INVALID",
                    "predicate value must be a scalar or scalar list",
                )
            values = expected if isinstance(expected, list) else [expected]
            if any(
                isinstance(item, float) and not math.isfinite(item) for item in values
            ):
                raise KernelError(
                    "MKAOS_APPLICABILITY_INVALID", "predicate numbers must be finite"
                )
            seen.add(identity)
    return dict(value)


def resolve_pointer(value: Any, pointer: str) -> tuple[bool, Any]:
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        return False, None
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, Mapping) and token in value:
            value = value[token]
        elif (
            isinstance(value, (list, tuple))
            and token.isdigit()
            and int(token) < len(value)
        ):
            value = value[int(token)]
        else:
            return False, None
    return True, value


def _compare(actual: Any, operator: str, expected: Any) -> bool | None:
    if isinstance(actual, float) and not math.isfinite(actual):
        return None
    if operator in {"EQ", "NE"}:
        if type(actual) is not type(expected):
            return None
        return actual == expected if operator == "EQ" else actual != expected
    if operator in {"GT", "GTE", "LT", "LTE"}:
        if type(actual) not in {int, float} or type(expected) not in {int, float}:
            return None
        return {
            "GT": actual > expected,
            "GTE": actual >= expected,
            "LT": actual < expected,
            "LTE": actual <= expected,
        }[operator]
    if operator == "IN" and isinstance(expected, list):
        return any(type(actual) is type(item) and actual == item for item in expected)
    if operator == "CONTAINS" and isinstance(actual, (list, tuple)):
        return any(type(expected) is type(item) and expected == item for item in actual)
    return None


def assess_applicability(
    abstract: Mapping[str, Any],
    *,
    sources: Mapping[str, Any],
    hard_constraints: tuple[str, ...],
) -> dict[str, Any]:
    contract = abstract.get("applicability_contract")
    contract = (
        validate_applicability_contract(contract) if contract is not None else None
    )
    checks: list[dict[str, Any]] = []
    if contract is not None:
        for group in ("prerequisites", "exceptions", "hard_conflicts"):
            for predicate in contract[group]:
                role = (
                    predicate["path"]
                    .split("/")[1]
                    .replace("~1", "/")
                    .replace("~0", "~")
                )
                source = sources.get(role, {})
                facts = {
                    key: item.get("content", {})
                    for key, item in sources.items()
                    if isinstance(item, Mapping)
                }
                facts["hard_constraints"] = list(hard_constraints)
                found, actual = resolve_pointer(facts, predicate["path"])
                result = (
                    _compare(actual, predicate["operator"], predicate["value"])
                    if found
                    else None
                )
                checks.append(
                    {
                        **dict(predicate),
                        "group": group,
                        "result": "TRUE"
                        if result is True
                        else "FALSE"
                        if result is False
                        else "UNKNOWN",
                        "method": "DETERMINISTIC_TYPED_PREDICATE",
                        "actual_value": actual if found else None,
                        "source_asset_version_id": source.get("asset_version_id", "")
                        if isinstance(source, Mapping)
                        else "",
                        "source_content_hash": source.get("content_hash", "")
                        if isinstance(source, Mapping)
                        else "",
                        "reason": "MISSING_INPUT_OR_INCOMPARABLE_TYPES"
                        if result is None
                        else "EXACT_FROZEN_INPUT_COMPARISON",
                    }
                )
    for group, fields in (
        ("prerequisites", ("applicability", "preconditions")),
        ("exceptions", ("exceptions", "failure_conditions")),
    ):
        for field in fields:
            for index, statement in enumerate(abstract.get(field) or ()):
                checks.append(
                    {
                        "condition_id": f"semantic:{field}:{index}",
                        "group": group,
                        "statement": statement,
                        "result": "UNKNOWN",
                        "method": "SEMANTIC_UNVERIFIED",
                        "reason": "TEXT_REQUIRES_PROJECT_SPECIFIC_REVIEW",
                    }
                )
    unmet = [
        item
        for item in checks
        if item["group"] == "prerequisites" and item["result"] != "TRUE"
    ]
    exceptions = [
        item
        for item in checks
        if item["group"] in {"exceptions", "hard_conflicts"}
        and item["result"] == "TRUE"
    ]
    typed = [
        item for item in checks if item["method"] == "DETERMINISTIC_TYPED_PREDICATE"
    ]
    if exceptions:
        status = "REJECTED"
    elif not typed:
        status = "UNKNOWN"
    elif unmet or any(item["result"] == "UNKNOWN" for item in checks):
        status = "CONDITIONAL"
    else:
        status = "APPLICABLE"
    requested_role = str(
        contract["usage_role"]
        if contract
        else abstract.get("usage_role")
        or (
            "MECHANISM"
            if abstract.get("knowledge_kind") == "DOMAIN_INTELLIGENCE"
            else "INSPIRATION"
        )
    )
    if requested_role not in USAGE_ROLES:
        raise KernelError(
            "MKAOS_APPLICABILITY_INVALID", "knowledge usage role is invalid"
        )
    return {
        "schema_version": "knowledge-applicability-assessment.v1",
        "status": status,
        "usage_role": requested_role,
        "checks": checks,
        "hard_constraints": list(hard_constraints),
        "hard_constraint_semantics": "UNVERIFIED_EXCEPT_EXPLICIT_TYPED_CHECKS",
        "unmet_prerequisites": unmet,
        "exceptions": exceptions,
        "rejection_reasons": [
            f"{item['group'].upper()}:{item['condition_id']}" for item in exceptions
        ],
        "evidence_ceiling": "FROZEN_INPUT_RELATION_NOT_SEMANTIC_OR_CANON_PROOF",
    }


def prose_applicability_view(assessment: Mapping[str, Any]) -> dict[str, Any]:
    checks = []
    for item in assessment.get("checks") or ():
        check = {key: value for key, value in item.items() if key != "actual_value"}
        path = str(check.get("path") or "")
        if check.get(
            "method"
        ) == "DETERMINISTIC_TYPED_PREDICATE" and not path.startswith(
            ("/world_bible/", "/hard_constraints")
        ):
            check["result"] = "UNKNOWN"
            check["reason"] = "REQUIRES_ROLE_SCOPED_CONTEXT_VERIFICATION"
        checks.append(check)
    return {
        **dict(assessment),
        "checks": checks,
        "status": "UNKNOWN"
        if any(item["result"] == "UNKNOWN" for item in checks)
        else assessment["status"],
        "unmet_prerequisites": [
            item
            for item in checks
            if item["group"] == "prerequisites" and item["result"] != "TRUE"
        ],
        "exceptions": [
            item
            for item in checks
            if item["group"] in {"exceptions", "hard_conflicts"}
            and item["result"] == "TRUE"
        ],
        "evidence_ceiling": "ROLE_SCOPED_VERIFICATION_REQUIRED_NO_PRIVATE_STATE_VALUES",
    }
