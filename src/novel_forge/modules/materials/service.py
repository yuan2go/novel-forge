from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous, run_metadata
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.schemas import MaterialCard, MaterialUsageEvent, validate_common_fields
from novel_forge.storage.local import LocalStorage


def build_materials(storage: LocalStorage, input_path: str | None = None, *, environment: str = "") -> Path:
    knowledge = read_previous(storage, "knowledge", input_path)
    source_eligibility = knowledge.content.get("source_eligibility", {}) if isinstance(knowledge.content, dict) and isinstance(knowledge.content.get("source_eligibility", {}), dict) else {}
    source_chunk_ids = [str(item) for item in knowledge.content.get("source_chunk_ids", []) if str(item).strip()] if isinstance(knowledge.content, dict) else []
    _enforce_material_source_eligibility(source_eligibility, source_chunk_ids=source_chunk_ids, environment=environment)
    with AgentExecutionContext(
        storage,
        agent_key="material",
        operation="build-materials",
        input_assets=[input_path or knowledge.id],
        output_types=["material_card"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        asset = MaterialCard(
            title="Suspense production material card",
            source=knowledge.id,
            tags=[
                "material",
                "suspense",
                "reusable",
                "hook",
                "conflict",
                "reader-retention",
                "chapter-ending",
            ],
            content={
                "usable_patterns": knowledge.content.get("principles", []),
                "prompt_fragments": [
                    "Design a clue that changes the protagonist's available choices.",
                    "End the chapter with a new obligation, not just a question.",
                ],
                "do_not_copy": ["names", "sentences", "unique settings", "plot sequence combinations"],
                "source_eligibility": source_eligibility or {"status": "not_required", "caller": "materials.build_materials"},
                "source_boundary": {
                    "raw_text_included": False,
                    "clean_text_included": False,
                    "inherits_knowledge_source_eligibility": bool(source_eligibility),
                },
            },
            metadata={
                "copyright_boundary": "reusable abstract production material only",
                "source_eligibility_status": source_eligibility.get("status", "not_required") if source_eligibility else "not_required",
                "source_policy_refs": source_eligibility.get("source_policy_refs", []) if source_eligibility else [],
                "source_risk_report_refs": source_eligibility.get("source_risk_report_refs", []) if source_eligibility else [],
                "use_in_generation_rag": bool(source_eligibility.get("generation_context_allowed")) and not bool(source_eligibility.get("evidence_only")) if source_eligibility else False,
                "tag_facets": {
                    "genre": ["suspense"],
                    "function": ["hook", "conflict", "reader-retention", "chapter-ending"],
                    "source_type": ["knowledge_card"],
                },
                "run_metadata": run_metadata("build-materials", knowledge, provider="local-rules", model="material-transform-v1"),
            },
            references=[knowledge.id],
        )
        run.guard("write_material_card", "material_card")
        path = storage.write_asset("materials", asset)
        run.succeed(output_assets=[str(path.relative_to(storage.root))])
        return path


def record_material_usage_event(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    material_ids = _strings(payload.get("material_ids")) or [str(payload.get("material_id") or "")]
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or "review").strip() or "review"
    events: list[dict[str, Any]] = []
    for material_id in [item for item in material_ids if item]:
        event_id = make_id("material_usage_event", f"{_short_key(material_id)}-{_short_key(str(payload.get('context_bundle_id') or ''))}-{utc_now()}")
        source_eligibility = payload.get("source_eligibility") if isinstance(payload.get("source_eligibility"), dict) else {}
        content = {
            "event_id": event_id,
            "material_id": material_id,
            "project_id": project_id,
            "flow": flow,
            "target_artifact_id": str(payload.get("target_artifact_id") or ""),
            "context_bundle_id": str(payload.get("context_bundle_id") or ""),
            "context_bundle_path": str(payload.get("context_bundle_path") or ""),
            "chapter_id": str(payload.get("chapter_id") or ""),
            "agent_name": str(payload.get("agent_name") or "context-builder"),
            "used_as": str(payload.get("used_as") or "context_bundle_selected_asset"),
            "source_eligibility": source_eligibility,
            "source_policy_refs": source_eligibility.get("source_policy_refs", []) if source_eligibility else [],
            "source_risk_report_refs": source_eligibility.get("source_risk_report_refs", []) if source_eligibility else [],
            "effect_score": _float(payload.get("effect_score"), 0.0),
            "review_result": payload.get("review_result") if isinstance(payload.get("review_result"), dict) else {},
            "created_at": utc_now(),
        }
        asset = MaterialUsageEvent(
            id=event_id,
            title=f"Material usage {material_id} in {flow}",
            source=material_id,
            tags=["material", "material-usage-event", flow],
            content=content,
            metadata={
                "project_id": project_id,
                "workspace_path": str(payload.get("workspace_path") or ""),
                "flow": flow,
                "context_bundle_id": content["context_bundle_id"],
                "use_in_generation_rag": False,
                "source_eligibility_status": source_eligibility.get("status", "") if source_eligibility else "",
                "usage_feedback_contract": "material-usage-feedback-v1",
            },
            references=_dedupe([material_id, content["target_artifact_id"], content["context_bundle_id"], content["context_bundle_path"], *_strings(payload.get("references"))]),
        )
        errors = validate_common_fields(asset.to_dict())
        if errors:
            raise ValueError("; ".join(errors))
        path = storage.write_asset("runs", asset)
        events.append({"path": _display_path(storage.root, path), "asset": storage.read_json(path)})
    return {"events": events, "event_count": len(events)}


def _enforce_material_source_eligibility(source_eligibility: dict[str, Any], *, source_chunk_ids: list[str], environment: str) -> None:
    if not is_production_environment(environment):
        return
    if not source_eligibility and source_chunk_ids:
        raise ValueError("Material source eligibility blocks production material card: missing")
    if not source_eligibility or source_eligibility.get("status") in {"not_required", "passed"}:
        return
    raise ValueError(f"Material source eligibility blocks production material card: {source_eligibility.get('status') or 'missing'}")


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _short_key(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
