from __future__ import annotations

import hashlib
import json
from typing import Any

from .extraction_schema import FORBIDDEN_FIELDS


def sanitize_provider_output(value: Any) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    sanitized = _sanitize(value, path="", events=events)
    output_hash = hashlib.sha256(json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "sanitized": sanitized,
        "sanitizer_events": events,
        "forbidden_field_hits": [event["field"] for event in events],
        "forbidden_field_count": len(events),
        "provider_output_hash": output_hash,
        "source_isolation": {
            "raw_text_included": False,
            "clean_text_included": False,
            "source_text_included": False,
            "target_text_included": False,
            "quote_included": False,
        },
    }


def _sanitize(value: Any, *, path: str, events: list[dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}" if path else key_text
            if key_text in FORBIDDEN_FIELDS:
                events.append({"path": next_path, "field": key_text, "action": "removed"})
                continue
            result[key_text] = _sanitize(item, path=next_path, events=events)
        return result
    if isinstance(value, list):
        return [_sanitize(item, path=f"{path}[{index}]", events=events) for index, item in enumerate(value)]
    return value
