from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.model_adapters.selection import model_from_env


FORBIDDEN_PROVIDER_FIELDS = {"raw_text", "clean_text", "source_text", "target_text", "quote", "quotation", "excerpt"}


def provider_extraction_enabled(payload: dict[str, Any]) -> bool:
    provider_mode = str(payload.get("provider_mode") or "").strip().lower()
    provider = str(payload.get("provider") or payload.get("model_provider") or os.environ.get("NOVEL_FORGE_MKAOS_EXTRACTION_PROVIDER", "")).strip().lower()
    return bool(payload.get("enable_provider_extraction") or provider_mode in {"mock", "local", "offline", "model", "external"} or provider)


def provider_extract_candidates(source_type: str, payload: dict[str, Any], deterministic_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not provider_extraction_enabled(payload):
        return deterministic_candidates
    text = str(payload.get("text") or payload.get("clean_text") or payload.get("summary") or "")
    adapter = _adapter(payload)
    context = {
        "task": "mkaos_creative_knowledge_extraction",
        "source_type": source_type,
        "required_output": "abstract creative mechanisms only; no source quotes",
        "forbidden_fields": sorted(FORBIDDEN_PROVIDER_FIELDS),
        "evidence_refs": [str(item) for item in payload.get("evidence_refs") or [] if str(item).strip()],
    }
    result = adapter.analyze(text, context)
    parsed = _parse_provider_candidates(result)
    base = deterministic_candidates or []
    if not parsed:
        return [_merge_provider_metadata(candidate, result, mode=_provider_mode(payload), parsed_count=0) for candidate in base]
    merged: list[dict[str, Any]] = []
    for index, candidate in enumerate(parsed):
        seed = dict(base[index % len(base)]) if base else {}
        seed.update(_sanitize_provider_candidate(candidate))
        merged.append(_merge_provider_metadata(seed, result, mode=_provider_mode(payload), parsed_count=len(parsed)))
    return merged


def _adapter(payload: dict[str, Any]) -> Any:
    mode = str(payload.get("provider_mode") or "").strip().lower()
    provider = str(payload.get("provider") or payload.get("model_provider") or os.environ.get("NOVEL_FORGE_MKAOS_EXTRACTION_PROVIDER", "")).strip().lower()
    if mode in {"", "mock", "local", "offline"} and not provider:
        return MockModelAdapter()
    if provider in {"", "mock", "local", "offline"}:
        return MockModelAdapter()
    env = {**os.environ, "NOVEL_FORGE_ANALYZE_PROVIDER": provider}
    if payload.get("model_name"):
        env["NOVEL_FORGE_MODEL_NAME"] = str(payload.get("model_name"))
    return model_from_env("analyze", env=env)


def _provider_mode(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("provider_mode") or "").strip().lower()
    provider = str(payload.get("provider") or payload.get("model_provider") or os.environ.get("NOVEL_FORGE_MKAOS_EXTRACTION_PROVIDER", "")).strip().lower()
    if provider and provider not in {"mock", "local", "offline"}:
        return "model_opt_in"
    if explicit:
        return f"{explicit}_opt_in"
    return "mock_opt_in"


def _parse_provider_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else None
    if candidates:
        return [item for item in candidates if isinstance(item, dict)]
    text = str(result.get("text") or result.get("summary") or "")
    match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except Exception:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        nested = parsed.get("candidates")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        return [parsed]
    return []


def _sanitize_provider_candidate(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_provider_candidate(item) for key, item in value.items() if str(key) not in FORBIDDEN_PROVIDER_FIELDS}
    if isinstance(value, list):
        return [_sanitize_provider_candidate(item) for item in value]
    return value


def _merge_provider_metadata(candidate: dict[str, Any], result: dict[str, Any], *, mode: str, parsed_count: int) -> dict[str, Any]:
    sanitized = _sanitize_provider_candidate(candidate)
    metadata = sanitized.get("metadata") if isinstance(sanitized.get("metadata"), dict) else {}
    output_hash = hashlib.sha256(json.dumps(_sanitize_provider_candidate(result), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    sanitized["metadata"] = {
        **metadata,
        "provider_mode": mode,
        "provider_model": str(result.get("model") or result.get("provider") or ""),
        "provider_output_hash": output_hash,
        "provider_output_keys": sorted(str(key) for key in result.keys()),
        "provider_candidate_count": parsed_count,
        "provider_output_source_text_included": False,
    }
    quality = sanitized.get("quality_dimensions") if isinstance(sanitized.get("quality_dimensions"), dict) else {}
    if mode.endswith("_opt_in"):
        quality["creative_usability_score"] = max(float(quality.get("creative_usability_score", 0.78)), 0.8)
        quality["abstraction_score"] = max(float(quality.get("abstraction_score", 0.78)), 0.8)
    sanitized["quality_dimensions"] = quality
    return sanitized
