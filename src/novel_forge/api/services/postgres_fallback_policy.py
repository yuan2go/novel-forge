from __future__ import annotations

from typing import Any


def postgres_asset_read_fallback_policy(settings: Any, error: Exception | None = None) -> dict[str, Any]:
    database_url = str(getattr(settings, "database_url", "") or "")
    strict = bool(getattr(settings, "postgres_write_strict", False))
    if not database_url:
        return {
            "mode": "local_only",
            "allow_local_fallback": True,
            "strict": strict,
            "http_status": 200,
            "message": "PostgreSQL is not configured; local asset index is the primary read source.",
        }
    if strict:
        return {
            "mode": "postgres_strict_fail_closed",
            "allow_local_fallback": False,
            "strict": True,
            "http_status": 503,
            "message": f"PostgreSQL asset index failed in strict mode: {error}" if error else "PostgreSQL asset index is required in strict mode.",
        }
    return {
        "mode": "postgres_read_fail_open",
        "allow_local_fallback": True,
        "strict": False,
        "http_status": 200,
        "message": f"PostgreSQL asset index failed; falling back to local asset index: {error}" if error else "PostgreSQL read fallback is allowed.",
    }

