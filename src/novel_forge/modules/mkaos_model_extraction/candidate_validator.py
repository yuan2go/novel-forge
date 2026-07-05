from __future__ import annotations

from typing import Any

from .extraction_schema import ALLOWED_RISK_LEVELS, REQUIRED_CANDIDATE_FIELDS


def validate_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for field in REQUIRED_CANDIDATE_FIELDS:
        value = candidate.get(field)
        if value is None or value == "" or value == [] or value == {}:
            errors.append({"field": field, "message": "required field missing or empty"})
    if str(candidate.get("abstraction_level") or "") not in {"mechanism", "principle", "template", "rule"}:
        warnings.append({"field": "abstraction_level", "message": "abstraction_level should be mechanism/principle/template/rule"})
    if str(candidate.get("risk_level") or "low") not in ALLOWED_RISK_LEVELS:
        errors.append({"field": "risk_level", "message": "risk_level must be low, medium, or high"})
    if not isinstance(candidate.get("positive_usage"), list):
        errors.append({"field": "positive_usage", "message": "positive_usage must be a list"})
    if not isinstance(candidate.get("negative_usage"), list):
        errors.append({"field": "negative_usage", "message": "negative_usage must be a list"})
    if not isinstance(candidate.get("anti_patterns"), list):
        errors.append({"field": "anti_patterns", "message": "anti_patterns must be a list"})
    if not isinstance(candidate.get("applicable_flows"), list) or not candidate.get("applicable_flows"):
        errors.append({"field": "applicable_flows", "message": "applicable_flows must be a non-empty list"})
    if not isinstance(candidate.get("quality_dimensions"), dict):
        errors.append({"field": "quality_dimensions", "message": "quality_dimensions must be an object"})
    return {"valid": not errors, "errors": errors, "warnings": warnings}
