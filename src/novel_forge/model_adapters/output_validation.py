from __future__ import annotations

import json
import re
from typing import Any


class ModelOutputValidationError(ValueError):
    """Raised when a model response cannot be used as a Novel Forge contract output."""


REVIEW_RISK_LEVELS = {"low", "medium", "high"}
REVIEW_NEXT_ACTIONS = {"approve", "revise", "rewrite", "block"}


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, allowing fenced JSON responses from chat models."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelOutputValidationError(f"model response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelOutputValidationError("model response must be a JSON object")
    return data


def validate_model_output(operation: str, data: dict[str, Any]) -> dict[str, Any]:
    operation = operation.strip().lower()
    if operation in {"generate", "draft", "topic"}:
        return _validate_generate(data)
    if operation in {"analyze", "decompose"}:
        return _validate_analyze(data)
    if operation == "review":
        return _validate_review(data)
    if operation == "revise":
        return _validate_revise(data)
    if operation == "batch":
        return _validate_batch(data)
    raise ModelOutputValidationError(f"unsupported model output operation: {operation}")


def _validate_generate(data: dict[str, Any]) -> dict[str, Any]:
    text = _required_str(data, "text")
    if len(text) < 8:
        raise ModelOutputValidationError("generate.text must contain usable prose")
    return {
        **data,
        "text": text,
        "notes": _string_list(data.get("notes", [])),
        "copyright_boundary": str(data.get("copyright_boundary", "")).strip(),
    }


def _validate_analyze(data: dict[str, Any]) -> dict[str, Any]:
    summary = _required_str(data, "summary")
    word_count = data.get("word_count", 0)
    try:
        word_count = int(word_count)
    except Exception as exc:
        raise ModelOutputValidationError("analyze.word_count must be an integer") from exc
    if word_count < 0:
        raise ModelOutputValidationError("analyze.word_count must be non-negative")
    patterns = _string_list(data.get("patterns", []))
    if not patterns:
        raise ModelOutputValidationError("analyze.patterns must contain at least one item")
    return {**data, "summary": summary, "word_count": word_count, "patterns": patterns}


def _validate_review(data: dict[str, Any]) -> dict[str, Any]:
    score = data.get("score")
    try:
        score = float(score)
    except Exception as exc:
        raise ModelOutputValidationError("review.score must be a number") from exc
    if score < 0 or score > 100:
        raise ModelOutputValidationError("review.score must be between 0 and 100")
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        raise ModelOutputValidationError("review.issues must be a list")
    normalized_issues = [_issue(item) for item in issues if isinstance(item, dict)]
    risk_level = str(data.get("risk_level", "medium")).strip().lower()
    if risk_level not in REVIEW_RISK_LEVELS:
        raise ModelOutputValidationError("review.risk_level must be low, medium, or high")
    next_action = str(data.get("next_action", "revise")).strip().lower()
    if next_action not in REVIEW_NEXT_ACTIONS:
        raise ModelOutputValidationError("review.next_action must be approve, revise, rewrite, or block")
    strengths = _required_string_list(data, "strengths")
    weaknesses = _required_string_list(data, "weaknesses")
    revision_suggestions = _required_string_list(data, "revision_suggestions")
    return {
        **data,
        "score": score,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "issues": normalized_issues,
        "risk_level": risk_level,
        "revision_suggestions": revision_suggestions,
        "next_action": next_action,
    }


def _validate_revise(data: dict[str, Any]) -> dict[str, Any]:
    plan = _required_string_list(data, "plan")
    normalized = {**data, "plan": plan}
    if "target_score" in data and data["target_score"] not in {None, ""}:
        try:
            normalized["target_score"] = float(data["target_score"])
        except Exception as exc:
            raise ModelOutputValidationError("revise.target_score must be a number when provided") from exc
    return normalized


def _validate_batch(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items")
    if not isinstance(items, list):
        raise ModelOutputValidationError("batch.items must be a list")
    return {**data, "items": items}


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelOutputValidationError(f"{key} must be a non-empty string")
    return value.strip()


def _required_string_list(data: dict[str, Any], key: str) -> list[str]:
    values = _string_list(data.get(key, []))
    if not values:
        raise ModelOutputValidationError(f"{key} must contain at least one non-empty string")
    return values


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _issue(value: dict[str, Any]) -> dict[str, Any]:
    dimension = str(value.get("dimension", "general")).strip() or "general"
    severity = str(value.get("severity", "medium")).strip().lower() or "medium"
    if severity not in {"low", "medium", "high"}:
        severity = "medium"
    message = str(value.get("message", "")).strip()
    return {**value, "dimension": dimension, "severity": severity, "message": message}
