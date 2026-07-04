from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules import mkaos as mkaos_service
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

from .anti_exposition_gate import check_anti_exposition
from .creative_usability_gate import evaluate_creative_usability
from .extraction_report import build_extraction_report_payload
from .quote_leakage_detector import check_quote_leakage
from .source_risk_gate import check_source_risk


FORBIDDEN_CONTEXT_KEYS = {"raw_text", "clean_text", "source_text", "target_text"}
CRITICAL_FLOWS = {"prose", "publish", "recap", "review", "revision"}


def evaluate_extraction_quality(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    knowledge_cards = _knowledge_cards(storage, payload)
    creative_assets = _creative_assets(storage, payload)
    report = build_extraction_report_payload(payload, knowledge_cards, creative_assets)
    card_gate_issues: list[dict[str, Any]] = []
    for card in knowledge_cards:
        gate = evaluate_creative_usability(card)
        if not gate["passed"]:
            card_gate_issues.extend([{**issue, "knowledge_id": card.get("id", ""), "target_asset_id": card.get("id", "")} for issue in gate["issues"]])
        anti = check_anti_exposition({"text": json.dumps(card.get("content", {}), ensure_ascii=False)})
        if not anti["passed"]:
            card_gate_issues.append({"issue_type": "anti_encyclopedia", "severity": "high", "blocking": True, "knowledge_id": card.get("id", ""), "target_asset_id": card.get("id", ""), "message": "creative knowledge still reads like exposition"})
    blocking = [issue for issue in card_gate_issues if issue.get("blocking")]
    persisted = _persist_issues(storage, project_id, blocking, source_system="mkaos.extraction_quality") if blocking else {"created_count": 0, "rows": []}
    content = {**report, "project_id": project_id, "issues": card_gate_issues, "review_issue_summary": persisted, "source_policy": _source_policy()}
    asset = BaseAsset(id=make_id("mkaos_extraction_report", f"{project_id} {utc_now()}"), type="mkaos_extraction_report", title="MKAOS Extraction Report", source="mkaos-quality", tags=["mkaos", "quality", "extraction-report"], content=content, metadata=_metadata(project_id, payload), references=[str(card.get("id") or "") for card in knowledge_cards])
    path = _write(storage, "runs", asset)
    if _is_production(payload) and blocking:
        raise ValueError("MKAOS extraction quality gate blocked production path")
    return {"path": _display_path(storage, path), "asset": storage.read_json(path), **content}


def gate_knowledge_pack(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("mkaos_flow") or "prose")
    pack_payload = _pack_payload(storage, payload)
    forbidden = _find_forbidden_fields(pack_payload)
    source_risk = check_source_risk(payload)
    issues: list[dict[str, Any]] = []
    if forbidden:
        issues.append({"issue_type": "source_leakage", "severity": "critical", "blocking": True, "message": "KnowledgePack contains forbidden source text fields", "forbidden_fields": forbidden})
    if not source_risk["passed"]:
        issues.append({"issue_type": "source_leakage", "severity": "critical", "blocking": True, "message": "Source policy permits downstream raw source usage"})
    empty_pack = not _pack_items(pack_payload)
    if empty_pack and flow in CRITICAL_FLOWS:
        issues.append({"issue_type": "mkaos_conflict", "severity": "high", "blocking": True, "message": f"{flow} KnowledgePack must not be empty"})
    persisted = _persist_issues(storage, project_id, issues, source_system="mkaos.pack_gate") if issues else {"created_count": 0, "rows": []}
    result = {
        "passed": not issues,
        "project_id": project_id,
        "flow": flow,
        "empty_pack": empty_pack,
        "issues": issues,
        "review_issue_summary": persisted,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "parallel_pair_text_included": False, "forbidden_field_count": len(forbidden)},
    }
    if _is_production(payload) and issues:
        raise ValueError("MKAOS KnowledgePack gate blocked production path")
    return result


def _knowledge_cards(storage: LocalStorage, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref in payload.get("knowledge_ids") or []:
        rows.append(_find_asset(storage, str(ref), "knowledge_card", ["knowledge"]))
    if not rows:
        candidates = mkaos_service.list_knowledge_cards(storage, project_id=str(payload.get("project_id") or "") or None, limit=500)
        rows = [row.get("asset", row) for row in candidates if row.get("metadata", {}).get("knowledge_subtype") == "creative_knowledge_card" or row.get("content", {}).get("knowledge_subtype") == "creative_knowledge_card"]
    return rows


def _creative_assets(storage: LocalStorage, payload: dict[str, Any]) -> list[dict[str, Any]]:
    types = {"genre_seed_card", "world_rule_card", "character_archetype_card", "conflict_pattern_card", "scene_material_card", "plot_template_card", "chapter_hook_card", "review_rule_card", "style_rule_card"}
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("knowledge")):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") in types:
            if payload.get("project_id") and str(data.get("metadata", {}).get("project_id") or data.get("content", {}).get("project_id") or "") != str(payload.get("project_id")):
                continue
            rows.append(data)
    return rows[: int(payload.get("limit", 500) or 500)]


def _pack_payload(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("knowledge_pack"), dict):
        return payload["knowledge_pack"]
    pack_id = str(payload.get("pack_id") or payload.get("knowledge_pack_id") or "")
    if pack_id:
        return _find_asset(storage, pack_id, "knowledge_pack", ["contexts"])
    return payload


def _find_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_CONTEXT_KEYS:
                hits.append(path)
            hits.extend(_find_forbidden_fields(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_find_forbidden_fields(item, f"{prefix}[{index}]"))
    return hits


def _pack_items(pack: dict[str, Any]) -> list[Any]:
    content = pack.get("content", {}) if isinstance(pack.get("content", {}), dict) else pack
    for key in ("pack_items", "items", "selected_items"):
        if isinstance(content.get(key), list):
            return content[key]
    grouped = content.get("grouped_items") if isinstance(content.get("grouped_items"), dict) else {}
    items: list[Any] = []
    for value in grouped.values():
        if isinstance(value, list):
            items.extend(value)
    return items


def _persist_issues(storage: LocalStorage, project_id: str, issues: list[dict[str, Any]], *, source_system: str) -> dict[str, Any]:
    rows = []
    for issue in issues:
        rows.append(
            create_review_issue(
                storage,
                {
                    "project_id": project_id,
                    "issue_type": issue.get("issue_type", "mkaos_conflict"),
                    "severity": issue.get("severity", "high"),
                    "blocking": bool(issue.get("blocking", True)),
                    "message": issue.get("message", "MKAOS quality gate issue"),
                    "fix_suggestion": "Review source isolation, abstraction quality, and knowledge applicability before production use.",
                    "target_asset_id": str(issue.get("target_asset_id") or issue.get("knowledge_id") or project_id),
                    "target_asset_type": str(issue.get("target_asset_type") or "mkaos_asset"),
                    "evidence_refs": [str(item) for item in issue.get("evidence_refs") or [] if str(item).strip()],
                    "source_issue": issue,
                    "source_system": source_system,
                },
            )
        )
    return {"created_count": len(rows), "rows": rows}


def _find_asset(storage: LocalStorage, ref: str, asset_type: str, categories: list[str]) -> dict[str, Any]:
    if "/" in ref or ref.endswith(".json"):
        data = storage.read_json(resolve_path(storage.root, ref))
        if data.get("type") == asset_type:
            return data
    for category in categories:
        for path in reversed(storage.list_json(category)):
            data = storage.read_json(path)
            if isinstance(data, dict) and data.get("type") == asset_type and ref in {str(data.get("id") or ""), str(path.relative_to(storage.root))}:
                return data
    raise FileNotFoundError(ref)


def _write(storage: LocalStorage, category: str, asset: BaseAsset) -> Path:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return storage.write_asset(category, asset)


def _metadata(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, "trace_id": str(payload.get("trace_id") or ""), "os_envelope": payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else {}, "run_metadata": run_metadata("mkaos.quality", BaseAsset(title="mkaos-quality", content={}))}


def _source_policy() -> dict[str, bool]:
    return {"raw_source_text_allowed": False, "source_chunk_raw_text_allowed": False, "parallel_pair_text_allowed": False, "generation_rag_allowed": False}


def _is_production(payload: dict[str, Any]) -> bool:
    return str(payload.get("environment") or "").strip().lower() in {"production", "strict", "operating_system"}


def _display_path(storage: LocalStorage, path: str | Path) -> str:
    p = Path(path)
    return str(p.relative_to(storage.root)) if p.is_absolute() and p.is_relative_to(storage.root) else str(p)
