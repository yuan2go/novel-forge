from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = (
    "You are a Novel Forge production model. Use reference material only for abstract "
    "structure, rhythm, conflict mechanics, and quality review. Do not copy protected "
    "expression, character combinations, settings, or plot sequences. Return strict JSON only."
)


SCHEMA_INSTRUCTIONS = {
    "generate": {
        "text": "non-empty generated prose or planning text",
        "notes": ["brief implementation notes"],
        "copyright_boundary": "short originality and source-boundary statement",
    },
    "analyze": {
        "summary": "concise abstract summary",
        "word_count": 0,
        "patterns": ["abstract reusable pattern"],
        "commercial_patterns": ["optional commercial mechanism"],
        "narrative_patterns": ["optional narrative mechanism"],
    },
    "review": {
        "score": 0,
        "strengths": ["specific strength"],
        "weaknesses": ["specific weakness"],
        "issues": [{"dimension": "dimension", "severity": "low|medium|high", "message": "issue"}],
        "risk_level": "low|medium|high",
        "revision_suggestions": ["specific revision action"],
        "next_action": "approve|revise|rewrite|block",
    },
    "revise": {
        "plan": ["ordered revision step"],
        "target_score": 80,
        "must_preserve": ["element to preserve"],
    },
}


def build_messages(operation: str, payload: str, context: dict[str, Any] | None = None) -> list[dict[str, str]]:
    operation = _canonical_operation(operation)
    context = context or {}
    schema = SCHEMA_INSTRUCTIONS[operation]
    user_payload = {
        "operation": operation,
        "required_json_shape": schema,
        "input": payload,
        "context": context,
        "quality_rules": [
            "Return one JSON object and no surrounding prose.",
            "Keep reference-derived content abstract.",
            "For drafts, write original Chinese prose unless context explicitly asks otherwise.",
            "For review, include actionable issues with severity and dimensions.",
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    ]


def _canonical_operation(operation: str) -> str:
    value = operation.strip().lower()
    if value in {"draft", "topic", "generate"}:
        return "generate"
    if value in {"decompose", "analyze"}:
        return "analyze"
    if value in {"review", "revise"}:
        return value
    raise ValueError(f"unsupported prompt operation: {operation}")
