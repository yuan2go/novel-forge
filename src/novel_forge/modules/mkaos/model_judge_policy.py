from __future__ import annotations

import os
from typing import Any


def model_judge_conflict_result(payload: dict[str, Any]) -> dict[str, Any]:
    requested = bool(payload.get("enable_model_judge") or payload.get("model_judge_enabled") or payload.get("model_judge") or payload.get("model_judge_result"))
    opt_in = bool(payload.get("model_judge_opt_in") or os.environ.get("NOVEL_FORGE_MKAOS_MODEL_JUDGE") == "1")
    if not requested:
        return {"requested": False, "opt_in": False, "status": "not_requested", "conflicts": []}
    if not opt_in:
        return {
            "requested": True,
            "opt_in": False,
            "status": "opt_in_required",
            "conflicts": [],
            "provider": str(payload.get("model_judge_provider") or ""),
        }
    judge_payload = payload.get("model_judge_result") if isinstance(payload.get("model_judge_result"), dict) else {}
    conflicts = judge_payload.get("conflicts") if isinstance(judge_payload.get("conflicts"), list) else []
    return {
        "requested": True,
        "opt_in": True,
        "status": "completed" if conflicts else "no_conflict_returned",
        "provider": str(payload.get("model_judge_provider") or judge_payload.get("provider") or "mock"),
        "conflicts": _strip_source_text_fields(conflicts),
    }


def _strip_source_text_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_source_text_fields(item)
            for key, item in value.items()
            if str(key) not in {"raw_text", "clean_text", "text", "content_text", "source_text"}
        }
    if isinstance(value, list):
        return [_strip_source_text_fields(item) for item in value]
    return value
