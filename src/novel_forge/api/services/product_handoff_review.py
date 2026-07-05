from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.model_adapters import estimate_usage_from_text, model_from_env, validate_model_output
from novel_forge.modules.model_router import call_model_via_router
from novel_forge.storage.local import LocalStorage


def review_handoff_output_quality_with_model(
    storage: LocalStorage,
    *,
    handoff: dict[str, Any],
    handoff_path: Path,
    output: dict[str, Any],
    rubric: list[str],
    minimum_score: int,
) -> dict[str, Any]:
    handoff_content = handoff.get("content", {}) if isinstance(handoff.get("content", {}), dict) else {}
    output_content = output.get("content", {}) if isinstance(output.get("content", {}), dict) else {}
    output_metadata = output.get("metadata", {}) if isinstance(output.get("metadata", {}), dict) else {}
    payload = {
        "handoff": {
            "operation": handoff_content.get("operation", ""),
            "expected_output_type": handoff_content.get("expected_output_type", ""),
            "acceptance_checks": handoff_content.get("acceptance_checks", []),
            "instructions": handoff_content.get("instructions", ""),
        },
        "output": {
            "id": output.get("id", ""),
            "type": output.get("type", ""),
            "title": output.get("title") or output.get("name", ""),
            "content": output_content,
            "metadata": output_metadata,
            "references": output.get("references", []),
        },
        "rubric": rubric,
        "minimum_score": minimum_score,
    }
    try:
        adapter = model_from_env("review")
        prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        trace = {
            "trace_id": str(handoff.get("id", "")) or "handoff-review",
            "parent_span_id": str(handoff.get("id", "")) or "handoff-review",
        }
        review = validate_model_output(
            "review",
            call_model_via_router(
                storage,
                adapter=adapter,
                operation="handoff_review",
                payload=prompt,
                context=payload,
                task_type="review",
                input_assets=[handoff_path],
                trace=trace,
            ),
        )
        usage = review.get("usage") if isinstance(review.get("usage"), dict) else estimate_usage_from_text(
            prompt,
            json.dumps(review, ensure_ascii=False),
            usage_source="handoff_review_estimated",
        )
        review.setdefault("usage", usage)
        review.setdefault("cost", {"amount": 0.0, "currency": "USD", "source": "handoff_review"})
        score = float(review.get("score", 0))
        issues = review.get("issues", []) if isinstance(review.get("issues", []), list) else []
        return {
            "ok": score >= minimum_score,
            "score": score,
            "minimum_score": minimum_score,
            "provider": review.get("provider", getattr(adapter, "name", "")),
            "model": review.get("model", getattr(adapter, "name", "")),
            "summary": str(review.get("summary", "")),
            "issues": issues,
            "suggestions": review.get("revision_suggestions", []),
            "rubric": rubric,
            "checked_at": utc_now(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "score": 0,
            "minimum_score": minimum_score,
            "provider": "",
            "model": "",
            "summary": "semantic review provider failed",
            "issues": [],
            "suggestions": [],
            "rubric": rubric,
            "error": str(exc),
            "checked_at": utc_now(),
        }
