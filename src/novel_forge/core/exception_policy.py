from __future__ import annotations

import json
from typing import Any


RECOVERABLE_ASSET_SCAN_ERRORS = (
    FileNotFoundError,
    json.JSONDecodeError,
    UnicodeDecodeError,
)


def is_recoverable_asset_scan_error(exc: BaseException) -> bool:
    if isinstance(exc, RECOVERABLE_ASSET_SCAN_ERRORS):
        return True
    if isinstance(exc, ValueError):
        message = str(exc).lower()
        return "asset json must be an object" in message
    return False


def require_recoverable_asset_scan_error(exc: BaseException, *, context: str = "asset scan") -> None:
    if is_recoverable_asset_scan_error(exc):
        return
    raise RuntimeError(f"unexpected exception during {context}: {exc}") from exc


def recoverable_asset_scan_error(exc: BaseException, *, path: Any = "") -> dict[str, str]:
    return {
        "path": str(path or ""),
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
