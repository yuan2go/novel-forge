from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionPort,
    DomainModelOperation,
    execute_domain_candidate,
)
from novel_forge.storage.local import LocalStorage


def review_handoff_output_quality_with_model(
    storage: LocalStorage,
    *,
    handoff: dict[str, Any],
    handoff_path: Path,
    output: dict[str, Any],
    rubric: list[str],
    minimum_score: int,
    execution_port: DomainExecutionPort | None = None,
    environment: str = "",
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
        prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        candidate = execute_domain_candidate(
            capability="quality.intrinsic.judge",
            operation=DomainModelOperation.REVIEW,
            candidate_kind=CandidateKind.JUDGE,
            prompt=prompt,
            context={
                **payload,
                "handoff_ref": str(handoff_path),
            },
            execution_port=execution_port,
            legacy_model_role="review",
            environment=environment,
        )
        review = dict(candidate.raw_output)
        review["execution_evidence"] = candidate.evidence.to_dict()
        score = float(review.get("score", 0))
        issues = review.get("issues", []) if isinstance(review.get("issues", []), list) else []
        return {
            "ok": score >= minimum_score,
            "score": score,
            "minimum_score": minimum_score,
            "provider": review.get(
                "provider", candidate.evidence.backend_id
            ),
            "model": review.get("model", candidate.evidence.backend_id),
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
