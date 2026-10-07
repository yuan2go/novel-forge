from __future__ import annotations

import json


def codex_protocol_failure(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                continue
            message = event.get("message") if event.get("type") == "error" else None
            detail = json.loads(message) if isinstance(message, str) else {}
            if (isinstance(detail, dict) and detail.get("status", 400) == 400
                and isinstance(detail.get("error"), dict)
                and detail["error"].get("code") == "invalid_json_schema"):
                return "PROVIDER_SCHEMA_REJECTED"
        except (ValueError, TypeError):
            continue
    return None

