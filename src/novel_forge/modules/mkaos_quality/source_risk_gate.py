from __future__ import annotations

from typing import Any


def check_source_risk(payload: dict[str, Any]) -> dict[str, Any]:
    policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    high_risk = bool(policy.get("raw_text_allowed_for_prose")) or bool(policy.get("allow_downstream_generation"))
    return {
        "passed": not high_risk,
        "risk_level": "critical" if high_risk else str(policy.get("risk_level") or "low"),
        "source_policy": {
            "raw_source_text_allowed": False,
            "source_chunk_raw_text_allowed": False,
            "parallel_pair_text_allowed": False,
            "generation_rag_allowed": False,
        },
    }
