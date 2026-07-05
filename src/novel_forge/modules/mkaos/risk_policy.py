from __future__ import annotations

from typing import Any


RISK_LEVELS = {"low", "medium", "high", "critical"}
SEVERITY_PENALTIES = {"critical": 45, "high": 25, "medium": 12, "low": 5, "info": 1}


def normalize_risk_level(value: str) -> str:
    normalized = str(value or "low").strip().lower()
    return normalized if normalized in RISK_LEVELS else "low"


def severity_penalty(severity: str) -> int:
    return SEVERITY_PENALTIES.get(str(severity), 5)


def risk_reasons(row: dict[str, Any], risky_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    if content.get("status") == "deprecated" or metadata.get("asset_status") == "deprecated":
        reasons.append("deprecated")
    if content.get("status") == "needs_review" or metadata.get("asset_status") == "needs_review":
        reasons.append("needs_review")
    if content.get("risk_level") in {"high", "critical"} or metadata.get("risk_level") in {"high", "critical"}:
        reasons.append("high_risk")
    if row.get("id") in risky_ids:
        reasons.append("review_hit")
    return reasons

