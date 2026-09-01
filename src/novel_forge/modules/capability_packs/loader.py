"""SECURITY: Capability Packs are loaded only from explicit local UTF-8 JSON files."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path
from typing import Any

from .errors import CapabilityPackLoadError
from .schema import CapabilityPackManifest


MAX_CAPABILITY_PACK_BYTES = 1024 * 1024


def load_capability_pack(path: str | Path) -> CapabilityPackManifest:
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise CapabilityPackLoadError(
            "CAPABILITY_PACK_JSON_INVALID", "$", f"pack file cannot be read: {exc}"
        ) from exc
    if size > MAX_CAPABILITY_PACK_BYTES:
        raise CapabilityPackLoadError(
            "CAPABILITY_PACK_FILE_TOO_LARGE",
            "$",
            f"pack file exceeds {MAX_CAPABILITY_PACK_BYTES} bytes",
        )
    try:
        # WHY: Bound the read itself as well as the preflight stat. This closes the
        # time-of-check/time-of-use window if a file grows after stat().
        with target.open("rb") as stream:
            raw = stream.read(MAX_CAPABILITY_PACK_BYTES + 1)
        if len(raw) > MAX_CAPABILITY_PACK_BYTES:
            raise CapabilityPackLoadError(
                "CAPABILITY_PACK_FILE_TOO_LARGE",
                "$",
                f"pack file exceeds {MAX_CAPABILITY_PACK_BYTES} bytes",
            )
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except CapabilityPackLoadError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CapabilityPackLoadError(
            "CAPABILITY_PACK_JSON_INVALID", "$", f"pack is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilityPackLoadError(
            "CAPABILITY_PACK_JSON_INVALID", "$", "pack root must be a JSON object"
        )
    return load_capability_pack_payload(payload)


def load_capability_pack_payload(
    payload: Mapping[str, Any],
) -> CapabilityPackManifest:
    if not isinstance(payload, Mapping):
        raise CapabilityPackLoadError(
            "CAPABILITY_PACK_JSON_INVALID", "$", "pack root must be a mapping"
        )
    try:
        normalized = _copy_json_value(payload, path="$", root=True)
    except (TypeError, ValueError) as exc:
        raise CapabilityPackLoadError(
            "CAPABILITY_PACK_JSON_INVALID", "$", f"pack payload is not JSON-compatible: {exc}"
        ) from exc
    return CapabilityPackManifest.from_dict(normalized)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CapabilityPackLoadError(
                "CAPABILITY_PACK_JSON_DUPLICATE_KEY",
                "$",
                f"duplicate JSON object key: {key}",
            )
        value[key] = item
    return value


def _copy_json_value(value: Any, *, path: str, root: bool = False) -> Any:

    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string object key")
            copied[key] = _copy_json_value(item, path=f"{path}.{key}")
        return copied
    if isinstance(value, list):
        return [
            _copy_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    kind = "root" if root else "value"
    raise TypeError(f"{path} {kind} has unsupported type {type(value).__name__}")


__all__ = [
    "MAX_CAPABILITY_PACK_BYTES",
    "load_capability_pack",
    "load_capability_pack_payload",
]
