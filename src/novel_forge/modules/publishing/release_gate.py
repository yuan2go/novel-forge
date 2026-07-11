from __future__ import annotations

from typing import Any


def release_package_gate_evidence(gate: dict[str, Any], *, production: bool) -> dict[str, Any]:
    content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    gate_specs = [
        ("production_governance", "path", "passed"),
        ("evaluation_gate", "path", "passed"),
        ("provider_runtime_gate", "", "passed"),
        ("platform_strategy_gate", "platform_strategy_pack_path", "passed"),
        ("context_governance_gate", "gate_result_path", "passed"),
        ("source_governance_gate", "gate_result_path", "passed"),
    ]
    for dimension, path_field, expected_status in gate_specs:
        payload = content.get(dimension, {}) if isinstance(content.get(dimension, {}), dict) else {}
        status = str(payload.get("status") or "missing")
        path_value = str(payload.get(path_field) or "") if path_field else ""
        blocking = bool(payload.get("blocking")) or status != expected_status
        missing_path = bool(production and path_field and not path_value)
        checks.append(
            {
                "dimension": dimension,
                "status": status,
                "expected_status": expected_status,
                "path_field": path_field,
                "path": path_value,
                "blocking": bool(blocking or missing_path),
            }
        )
        if production and (blocking or missing_path):
            issues.append(
                {
                    "dimension": dimension,
                    "severity": "critical" if dimension == "provider_runtime_gate" else "high",
                    "message": f"production release requires {dimension} status {expected_status} with durable evidence",
                    "current_status": status,
                    "path": path_value,
                    "recommendation": f"rerun or repair {dimension} before creating the release package",
                }
            )
    release_quality = content.get("release_quality", {}) if isinstance(content.get("release_quality", {}), dict) else {}
    for dimension in ["asset_integrity", "content_quality"]:
        payload = release_quality.get(dimension, {}) if isinstance(release_quality.get(dimension, {}), dict) else {}
        status = str(payload.get("status") or "missing")
        path_value = str(payload.get("path") or "")
        blocking = bool(payload.get("blocking")) or status != "passed" or not path_value
        checks.append({"dimension": f"release_{dimension}", "status": status, "expected_status": "passed", "path_field": "path", "path": path_value, "blocking": blocking})
        if production and blocking:
            issues.append({"dimension": f"release_{dimension}", "severity": "high", "message": f"production release requires passed {dimension} evidence", "current_status": status, "path": path_value, "recommendation": "repair the candidate and rerun release quality gates"})
    return {
        "publish_gate_report_id": _asset_id(gate),
        "publish_gate_decision": content.get("decision", "blocked"),
        "checks": checks,
        "blocking": bool(issues),
        "blocking_issues": issues,
    }


def _asset_id(data: dict[str, Any]) -> str:
    return str(data.get("id") or data.get("asset_id") or "")
