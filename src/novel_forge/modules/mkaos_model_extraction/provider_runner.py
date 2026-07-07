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
    production = _is_production(payload)
    mock_route = provider_mode in {"mock", "local", "offline"} or provider in {"", "mock", "local", "offline"}
    approval_evidence = _approval_evidence(payload, provider_mode=provider_mode, provider=provider, mock_route=mock_route)
    if provider_mode in {"disabled", "off", "false"} and not provider:
        return {
            "provider_mode": "disabled",
            "model": "",
            "output": {"candidates": []},
            "provider_output_hash": "",
            "warnings": ["provider disabled"],
            "provider_approval_evidence": approval_evidence,
            "provider_runtime_gate": {"status": "skipped", "blocking": False, "reason": "provider disabled"},
        }
    if production and mock_route and not approval_evidence["mock_fixture_allowed"]:
        return {
            "provider_mode": provider_mode or provider or "mock",
            "model": "",
            "output": {"candidates": []},
            "provider_output_hash": "",
            "warnings": ["mock/local/offline provider denied in production without explicit fixture mode"],
            "provider_approval_evidence": approval_evidence,
            "provider_runtime_gate": {
                "status": "blocked",
                "blocking": True,
                "reason": "production provider route resolved to mock/local/offline without explicit fixture approval",
                "provider_mode": provider_mode,
                "provider": provider,
            },
        }
    adapter = MockModelAdapter() if mock_route else model_from_env("analyze", env={**os.environ, "NOVEL_FORGE_ANALYZE_PROVIDER": provider})
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
    return {
        "provider_mode": provider_mode or provider or "mock",
        "model": str(result.get("model") or getattr(adapter, "name", "")),
        "output": result,
        "provider_output_hash": output_hash,
        "warnings": [],
        "provider_approval_evidence": approval_evidence,
        "provider_runtime_gate": {"status": "passed", "blocking": False, "provider_mode": provider_mode, "provider": provider},
    }


def _safe_provider_input(payload: dict[str, Any]) -> str:
    if bool(payload.get("allow_evidence_text")):
        return str(payload.get("text") or payload.get("source_excerpt") or payload.get("input_summary") or payload.get("summary") or "")[:4000]
    return str(payload.get("input_summary") or payload.get("summary") or payload.get("abstract_preview") or payload.get("title") or "")[:1600]


def _is_production(payload: dict[str, Any]) -> bool:
    return str(payload.get("environment") or "").strip().lower() in {"production", "strict", "operating_system"}


def _approval_evidence(payload: dict[str, Any], *, provider_mode: str, provider: str, mock_route: bool) -> dict[str, Any]:
    runtime_policy = payload.get("runtime_policy") if isinstance(payload.get("runtime_policy"), dict) else {}
    mock_fixture_allowed = bool(
        payload.get("allow_mock_provider_fixture")
        or payload.get("explicit_fixture_mode")
        or runtime_policy.get("allow_mock_provider_fixture")
        or runtime_policy.get("explicit_fixture_mode")
    )
    return {
        "provider_mode": provider_mode,
        "provider": provider,
        "mock_route": bool(mock_route),
        "mock_fixture_allowed": mock_fixture_allowed,
        "approval_ref": str(payload.get("provider_approval_ref") or runtime_policy.get("provider_approval_ref") or ""),
        "route_resolution": "mock_or_local" if mock_route else "configured_provider",
    }
