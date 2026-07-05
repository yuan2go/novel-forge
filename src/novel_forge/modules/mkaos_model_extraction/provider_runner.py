from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.model_adapters.selection import model_from_env


def run_provider(payload: dict[str, Any], prompt: dict[str, Any]) -> dict[str, Any]:
    provider_mode = str(payload.get("provider_mode") or "disabled").strip().lower()
    provider = str(payload.get("provider") or payload.get("model_provider") or os.environ.get("NOVEL_FORGE_MKAOS_EXTRACTION_PROVIDER", "")).strip().lower()
    if provider_mode in {"disabled", "off", "false"} and not provider:
        return {"provider_mode": "disabled", "model": "", "output": {"candidates": []}, "provider_output_hash": "", "warnings": ["provider disabled"]}
    adapter = MockModelAdapter() if provider_mode in {"mock", "local", "offline"} or provider in {"", "mock", "local", "offline"} else model_from_env("analyze", env={**os.environ, "NOVEL_FORGE_ANALYZE_PROVIDER": provider})
    input_text = _safe_provider_input(payload)
    context = {
        "prompt_id": prompt.get("prompt_id", ""),
        "source_type": payload.get("source_type", ""),
        "schema": prompt.get("required_schema", {}),
        "forbidden_fields": prompt.get("forbidden_fields", []),
        "evidence_refs": payload.get("evidence_refs", []),
        "runtime_policy": payload.get("runtime_policy", {}),
    }
    result = adapter.analyze(input_text, context)
    output_hash = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {"provider_mode": provider_mode or provider or "mock", "model": str(result.get("model") or getattr(adapter, "name", "")), "output": result, "provider_output_hash": output_hash, "warnings": []}


def _safe_provider_input(payload: dict[str, Any]) -> str:
    if bool(payload.get("allow_evidence_text")):
        return str(payload.get("input_summary") or payload.get("text") or payload.get("summary") or "")[:4000]
    return str(payload.get("input_summary") or payload.get("summary") or payload.get("abstract_preview") or payload.get("title") or "")[:1600]
