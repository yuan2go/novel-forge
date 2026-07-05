from __future__ import annotations

from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import run_metadata
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

from .extraction_schema import FORBIDDEN_FIELDS, default_candidate_schema


DEFAULT_PROMPTS: dict[str, dict[str, Any]] = {
    "classical_text": {"prompt_id": "classical_text_extraction_v1", "instruction": "Extract abstract order, ritual, duty, pressure, and choice mechanisms from classical text summaries."},
    "webnovel_analysis": {"prompt_id": "webnovel_extraction_v1", "instruction": "Extract reusable hook, payoff, rhythm, identity gap, and retention mechanisms from webnovel analysis summaries."},
    "professional_book": {"prompt_id": "professional_book_extraction_v1", "instruction": "Extract transferable professional causal mechanisms and convert them into narrative constraints and review rules."},
    "mystery": {"prompt_id": "mystery_extraction_v1", "instruction": "Extract fair clue, misdirection, evidence chain, suspect pressure, and reveal timing mechanisms."},
    "platform_rule": {"prompt_id": "platform_rule_extraction_v1", "instruction": "Extract platform rhythm, opening, chapter, retention, and compliance mechanisms."},
    "training": {"prompt_id": "training_extraction_v1", "instruction": "Extract writing/reading training mechanisms, answer templates, and evaluation criteria."},
}


def ensure_default_prompt_versions(storage: LocalStorage, *, project_id: str = "local-system") -> list[dict[str, Any]]:
    existing = list_prompt_versions(storage, project_id=project_id, limit=1000)
    existing_ids = {row["content"].get("prompt_id") for row in existing}
    created: list[dict[str, Any]] = []
    for source_type, spec in DEFAULT_PROMPTS.items():
        if spec["prompt_id"] in existing_ids:
            continue
        created.append(create_prompt_version(storage, {**spec, "source_type": source_type, "project_id": project_id, "status": "active"}))
    return [*existing, *created]


def list_prompt_versions(storage: LocalStorage, *, project_id: str | None = None, source_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("knowledge")):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "mkaos_extraction_prompt_version":
            continue
        content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") != project_id:
            continue
        if source_type and str(content.get("source_type") or "") != source_type:
            continue
        rows.append({"path": _display_path(storage, path), "id": data.get("id", ""), "type": data.get("type", ""), "title": data.get("title", ""), "content": content, "metadata": metadata, "asset": data, "updated_at": data.get("updated_at", "")})
    return rows


def create_prompt_version(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    source_type = str(payload.get("source_type") or "professional_book")
    prompt_id = str(payload.get("prompt_id") or f"{source_type}_extraction_v1")
    content = {
        "prompt_id": prompt_id,
        "project_id": project_id,
        "source_type": source_type,
        "instruction": str(payload.get("instruction") or DEFAULT_PROMPTS.get(source_type, DEFAULT_PROMPTS["professional_book"])["instruction"]),
        "required_schema": payload.get("required_schema") if isinstance(payload.get("required_schema"), dict) else default_candidate_schema(),
        "forbidden_fields": sorted(FORBIDDEN_FIELDS),
        "examples": payload.get("examples") if isinstance(payload.get("examples"), list) else [],
        "source_isolation_policy": {"raw_source_text_allowed": False, "provider_output_raw_text_stored": False},
        "output_quality_rules": ["mechanism-level abstraction", "evidence refs required", "creative usability required", "no source expression"],
        "version": str(payload.get("version") or "v1"),
        "status": str(payload.get("status") or "draft"),
        "benchmark_score": float(payload.get("benchmark_score", 0.0) or 0.0),
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        id=make_id("mkaos_extraction_prompt_version", prompt_id),
        type="mkaos_extraction_prompt_version",
        title=prompt_id,
        source="mkaos-model-extraction",
        tags=["mkaos", "model-extraction", "prompt", source_type, content["status"]],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, "run_metadata": run_metadata("mkaos.model_extraction.prompt", BaseAsset(title="prompt", content={}))},
        references=[],
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), "content": content, "id": asset.id}


def _display_path(storage: LocalStorage, path: str | Any) -> str:
    p = path if hasattr(path, "is_absolute") else storage.root / str(path)
    return str(p.relative_to(storage.root)) if p.is_absolute() and p.is_relative_to(storage.root) else str(p)
