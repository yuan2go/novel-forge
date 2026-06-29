from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import SemanticExtractionReport, validate_common_fields
from novel_forge.storage.local import LocalStorage

SEMANTIC_REVIEW_VERSION = "semantic-enhancement-0.1.0"
SEMANTIC_KG_TYPES = {
    "character_card",
    "world_bible",
    "continuity_bible",
    "foreshadowing_thread",
    "power_scale_rule",
    "platform_profile",
    "genre_market_profile",
    "creative_strategy_profile",
    "quality_standard_profile",
    "review_rule_pack",
    "outline",
    "chapter_plan",
    "chapter_plan_version",
    "draft_chapter",
    "draft_version",
}


def analyze_story_semantics(
    storage: LocalStorage,
    *,
    target_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    production_context: dict[str, Any] | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    storage.ensure_layout()
    assets = _load_semantic_assets(storage, project_id=project_id, workspace_path=workspace_path, target_path=target_path, limit=limit)
    target = _target_asset_row(storage, target_path)
    return analyze_semantic_assets(
        assets,
        target=target,
        project_id=project_id,
        workspace_path=workspace_path,
        production_context=production_context,
    )


def create_semantic_extraction_report(
    storage: LocalStorage,
    *,
    target_path: str | Path | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    production_context: dict[str, Any] | None = None,
    extractor_model: dict[str, Any] | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    storage.ensure_layout()
    analysis = analyze_story_semantics(
        storage,
        target_path=target_path,
        project_id=project_id,
        workspace_path=workspace_path,
        production_context=production_context,
        limit=limit,
    )
    semantic_model = dict(analysis.get("semantic_model", {}) if isinstance(analysis.get("semantic_model", {}), dict) else {})
    model_assisted = _validated_model_assisted_extraction(extractor_model or {}, analysis)
    if extractor_model:
        semantic_model.update({"assisted_by": extractor_model, "mode": "model_assisted_with_local_validation"})
    target_display = str(analysis.get("target_path") or target_path or "")
    report_id = make_id("semantic_extraction_report", f"{project_id or workspace_path or target_display or utc_now()}")
    content = {
        "report_id": report_id,
        "target_path": target_display,
        "semantic_model": semantic_model,
        "semantic_entities": _merge_semantic_entities(analysis.get("semantic_entities", []), model_assisted.get("entities", [])),
        "model_assisted_extraction": model_assisted,
        "foreshadowing_tracking": analysis.get("foreshadowing_tracking", {}),
        "character_motivation_drift": analysis.get("character_motivation_drift", {}),
        "power_scale_conflicts": analysis.get("power_scale_conflicts", {}),
        "chapter_pleasure_toxicity": analysis.get("chapter_pleasure_toxicity", {}),
        "platform_adaptation_review": analysis.get("platform_adaptation_review", {}),
        "issues": analysis.get("issues", []),
        "risk_level": analysis.get("risk_level", ""),
        "recommendation": analysis.get("recommendation", ""),
        "summary": analysis.get("summary", {}),
        "created_at": utc_now(),
    }
    content["summary"] = {
        **(content["summary"] if isinstance(content.get("summary", {}), dict) else {}),
        "model_assisted_entity_count": len(model_assisted.get("entities", [])),
        "model_assisted_relation_count": len(model_assisted.get("relations", [])),
        "model_assisted_event_count": len(model_assisted.get("events", [])),
        "model_assisted_status": model_assisted.get("status", "not_requested"),
    }
    references = _semantic_references(content, target_display)
    asset = SemanticExtractionReport(
        title=f"Semantic extraction: {target_display or project_id or 'global'}",
        source=target_display or project_id or workspace_path or report_id,
        tags=["semantic-extraction", str(content["recommendation"] or "review"), str(content["risk_level"] or "unknown")],
        content=content,
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or ""},
        references=filter_project_safe_references(storage, project_id or "", references),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "analysis": analysis}


def analyze_semantic_assets(
    assets: list[dict[str, Any]],
    *,
    target: dict[str, Any] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    production_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [row for row in assets if isinstance(row, dict) and isinstance(row.get("data", {}), dict)]
    target_row = target if isinstance(target, dict) and isinstance(target.get("data", {}), dict) else _last_draft_or_plan(rows)
    target_text = _asset_text(target_row.get("data", {}) if target_row else {})
    corpus_text = "\n".join(_asset_text(row.get("data", {})) for row in rows)
    known = _known_semantic_inventory(rows)
    semantic_entities = _semantic_entities(rows, known)
    foreshadowing = _foreshadowing_tracking(rows, target_text, corpus_text)
    motivation = _motivation_drift(rows, target_text)
    power = _power_scale_conflicts(rows, target_text)
    chapter = _chapter_pleasure_toxicity(target_text, motivation=motivation, power=power)
    platform = _platform_adaptation_review(target_text, production_context or {}, chapter)
    issues = _semantic_issues(motivation, power, chapter, platform, foreshadowing)
    recommendation = "block" if any(item.get("severity") == "high" for item in issues) else "revise" if issues else "pass"
    return {
        "version": SEMANTIC_REVIEW_VERSION,
        "semantic_model": {
            "provider": "local-semantic-rubric",
            "model": "deterministic-story-semantics-v1",
            "mode": "hybrid_extraction_ready",
            "generated_at": utc_now(),
        },
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "target_path": str(target_row.get("path", "")) if target_row else "",
        "semantic_entities": semantic_entities,
        "foreshadowing_tracking": foreshadowing,
        "character_motivation_drift": motivation,
        "power_scale_conflicts": power,
        "chapter_pleasure_toxicity": chapter,
        "platform_adaptation_review": platform,
        "issues": issues,
        "risk_level": "high" if recommendation == "block" else "medium" if recommendation == "revise" else "low",
        "recommendation": recommendation,
        "summary": {
            "entity_count": len(semantic_entities),
            "foreshadowing_warning_count": len([item for item in foreshadowing.get("threads", []) if item.get("status") not in {"tracked", "payoff_ready"}]),
            "motivation_drift_count": len(motivation.get("drift_issues", [])),
            "power_conflict_count": len(power.get("conflicts", [])),
            "semantic_issue_count": len(issues),
            "pleasure_score": chapter.get("pleasure_score", 0),
            "toxicity_score": chapter.get("toxicity_score", 0),
            "platform_score": platform.get("score", 0),
        },
    }


def _load_semantic_assets(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    target_path: str | Path | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target_display = ""
    if target_path:
        path = resolve_path(storage.root, target_path)
        target_display = _display_path(storage.root, path)
        try:
            data = storage.read_json(path)
            if isinstance(data, dict):
                rows.append({"path": target_display, "data": data, "target": True})
        except Exception:
            pass
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            if len(rows) >= max(1, int(limit or 500)):
                return rows
            display = _display_path(storage.root, path)
            if display == target_display:
                continue
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in SEMANTIC_KG_TYPES:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            row_project = str(metadata.get("project_id", ""))
            row_workspace = str(metadata.get("workspace_path", ""))
            if project_id and row_project and row_project != project_id:
                continue
            if workspace_path and row_workspace and row_workspace != workspace_path:
                continue
            rows.append({"path": display, "data": data})
    return rows


def _semantic_references(content: dict[str, Any], target_display: str) -> list[str]:
    refs = [target_display]
    for item in content.get("semantic_entities", []) if isinstance(content.get("semantic_entities", []), list) else []:
        if isinstance(item, dict):
            refs.extend([str(item.get("source_path", "")), str(item.get("source_asset_id", ""))])
            for span in item.get("evidence_spans", []) if isinstance(item.get("evidence_spans", []), list) else []:
                if isinstance(span, dict):
                    refs.append(str(span.get("path", "")))
    return _dedupe(refs)


def _validated_model_assisted_extraction(extractor_model: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    if not extractor_model:
        return {"status": "not_requested", "entities": [], "relations": [], "events": [], "issues": []}
    raw_entities = extractor_model.get("entities", extractor_model.get("semantic_entities", []))
    raw_relations = extractor_model.get("relations", [])
    raw_events = extractor_model.get("events", [])
    issues: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    for item in raw_entities if isinstance(raw_entities, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            issues.append({"severity": "medium", "message": "model-assisted entity missing name", "item": item})
            continue
        confidence = _bounded_float(item.get("confidence", 0.72), default=0.72)
        entities.append(
            {
                "id": str(item.get("id") or make_id("kg_model_entity", name)),
                "name": name,
                "entity_type": str(item.get("entity_type") or item.get("type") or "entity"),
                "aliases": _dedupe([name, *[str(alias) for alias in item.get("aliases", []) if str(alias).strip()]]) if isinstance(item.get("aliases", []), list) else [name],
                "confidence": confidence,
                "source": "model_assisted_extraction",
                "requires_human_gate": confidence < 0.85,
                "evidence_spans": item.get("evidence_spans", []) if isinstance(item.get("evidence_spans", []), list) else [],
            }
        )
    relations = [_validated_semantic_edge(item, "relation", issues) for item in raw_relations if isinstance(item, dict)] if isinstance(raw_relations, list) else []
    events = [_validated_semantic_edge(item, "event", issues) for item in raw_events if isinstance(item, dict)] if isinstance(raw_events, list) else []
    relations = [item for item in relations if item]
    events = [item for item in events if item]
    return {
        "status": "validated" if not issues else "needs_review",
        "provider": str(extractor_model.get("provider", "")),
        "model": str(extractor_model.get("model", "")),
        "entities": entities,
        "relations": relations,
        "events": events,
        "issues": issues,
        "local_crosscheck": {
            "local_entity_count": len(analysis.get("semantic_entities", [])) if isinstance(analysis.get("semantic_entities", []), list) else 0,
            "model_entity_count": len(entities),
        },
    }


def _validated_semantic_edge(item: dict[str, Any], kind: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    source = str(item.get("source") or item.get("from") or item.get("subject") or "").strip()
    target = str(item.get("target") or item.get("to") or item.get("object") or "").strip()
    if not source or not target:
        issues.append({"severity": "medium", "message": f"model-assisted {kind} missing source or target", "item": item})
        return {}
    confidence = _bounded_float(item.get("confidence", 0.7), default=0.7)
    return {
        "id": str(item.get("id") or make_id(f"kg_model_{kind}", f"{source}-{target}-{item.get('type', kind)}")),
        "kind": kind,
        "source": source,
        "target": target,
        "relation_type": str(item.get("relation_type") or item.get("type") or kind),
        "confidence": confidence,
        "requires_human_gate": confidence < 0.85,
        "evidence_spans": item.get("evidence_spans", []) if isinstance(item.get("evidence_spans", []), list) else [],
    }


def _merge_semantic_entities(local_entities: Any, assisted_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(local_entities if isinstance(local_entities, list) else []) + list(assisted_entities):
        if not isinstance(item, dict):
            continue
        key = str(item.get("name", item.get("id", ""))).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def _target_asset_row(storage: LocalStorage, target_path: str | Path | None) -> dict[str, Any]:
    if not target_path:
        return {}
    path = resolve_path(storage.root, target_path)
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return {"path": _display_path(storage.root, path), "data": data} if isinstance(data, dict) else {}


def _known_semantic_inventory(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    inventory = {"characters": [], "factions": [], "locations": [], "props": [], "rules": [], "foreshadowing": [], "power_scales": []}
    for row in rows:
        data = row.get("data", {})
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        asset_type = str(data.get("type", ""))
        if asset_type == "character_card":
            name = str(content.get("name") or data.get("title") or "").strip()
            if name:
                inventory["characters"].append({"name": name, "aliases": _aliases(content, name), "asset": row, "content": content})
        if asset_type in {"world_bible", "continuity_bible"}:
            inventory["factions"].extend(_named_inventory(content, ["factions", "forces", "organizations", "sects"], row))
            inventory["locations"].extend(_named_inventory(content, ["locations", "places", "regions"], row))
            inventory["props"].extend(_named_inventory(content, ["props", "items", "artifacts", "resources", "entities"], row))
            inventory["rules"].extend({"text": str(item), "asset": row} for item in _list_items(_first_value(content, ["rules", "worldview_rules", "constraints"])))
        if asset_type == "foreshadowing_thread":
            inventory["foreshadowing"].append({"asset": row, "content": content})
        if asset_type == "power_scale_rule":
            inventory["power_scales"].append({"asset": row, "content": content})
    return inventory


def _semantic_entities(rows: list[dict[str, Any]], known: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    known_groups = [
        ("character", known.get("characters", [])),
        ("faction", known.get("factions", [])),
        ("location", known.get("locations", [])),
        ("prop", known.get("props", [])),
    ]
    for entity_type, items in known_groups:
        for item in items:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            row = item.get("asset", {}) if isinstance(item.get("asset", {}), dict) else {}
            data = row.get("data", {}) if isinstance(row.get("data", {}), dict) else {}
            aliases = _dedupe([name, *[str(alias) for alias in item.get("aliases", []) if str(alias).strip()]])
            _upsert_entity(candidates, name, entity_type, data, str(row.get("path", "")), aliases, confidence=0.94, evidence_spans=_known_entity_spans(rows, aliases, str(row.get("path", ""))))
    for row in rows:
        data = row.get("data", {})
        text = _asset_text(data)
        if not text:
            continue
        for name in _capitalized_terms(text):
            entity_type = _classify_term(name, text)
            span = _first_span(text, name, str(row.get("path", "")), "semantic_term")
            _upsert_entity(candidates, name, entity_type, data, str(row.get("path", "")), [name], confidence=0.68, evidence_spans=[span] if span else [])
    rows_out = list(candidates.values())
    rows_out.sort(key=lambda item: (-float(item.get("confidence", 0)), str(item.get("name", ""))))
    return rows_out[:120]


def _foreshadowing_tracking(rows: list[dict[str, Any]], target_text: str, corpus_text: str) -> dict[str, Any]:
    threads: list[dict[str, Any]] = []
    for row in rows:
        data = row.get("data", {})
        if data.get("type") != "foreshadowing_thread":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        setup = str(content.get("setup") or content.get("seed") or "").strip()
        payoff = str(content.get("payoff_plan") or content.get("payoff") or "").strip()
        declared = str(content.get("status") or "planned").lower()
        setup_hit = _phrase_hit(target_text, setup) or _phrase_hit(corpus_text, setup)
        payoff_hit = _phrase_hit(target_text, payoff) or _phrase_hit(corpus_text, payoff)
        status = "tracked"
        severity = "low"
        if payoff_hit and not setup_hit:
            status = "payoff_without_setup"
            severity = "high"
        elif declared in {"planned", "open"} and not setup_hit:
            status = "setup_missing"
            severity = "medium"
        elif setup_hit and not payoff_hit:
            status = "setup_active"
        elif payoff_hit:
            status = "payoff_ready"
        threads.append(
            {
                "thread_id": str(content.get("thread_id") or data.get("title") or data.get("id")),
                "declared_status": declared,
                "status": status,
                "severity": severity,
                "setup": setup,
                "payoff_plan": payoff,
                "evidence": {
                    "setup_seen": bool(setup_hit),
                    "payoff_seen": bool(payoff_hit),
                    "source_path": str(row.get("path", "")),
                },
            }
        )
    return {"threads": threads, "status": "warning" if any(item.get("severity") in {"medium", "high"} for item in threads) else "passed"}


def _motivation_drift(rows: list[dict[str, Any]], target_text: str) -> dict[str, Any]:
    drift: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    lowered = target_text.lower()
    for row in rows:
        data = row.get("data", {})
        if data.get("type") != "character_card":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        name = str(content.get("name") or data.get("title") or "").strip()
        goals = _dedupe([str(content.get("external_goal") or ""), str(content.get("internal_need") or ""), *[str(item) for item in _list_items(content.get("motivation_chain"))]])
        if not name or not goals:
            continue
        goal_hits = [goal for goal in goals if _soft_terms_hit(lowered, goal)]
        agency_hit = any(term in target_text for term in ["决定", "选择", "必须", "想要", "为了", "宁愿", "refuse", "choose", "must", "wants", "because"])
        status = "aligned" if goal_hits and agency_hit else "weak_signal" if goal_hits or agency_hit else "drift"
        checked.append({"character": name, "status": status, "matched_goals": goal_hits, "expected_goals": goals})
        if status == "drift":
            drift.append({"dimension": "character_motivation_drift", "severity": "high", "character": name, "message": f"{name} appears without visible goal/need signal", "recommendation": "make the character goal, cost, and decision pressure explicit"})
        elif status == "weak_signal":
            drift.append({"dimension": "character_motivation_drift", "severity": "medium", "character": name, "message": f"{name} has partial motivation signal", "recommendation": "strengthen causal wording around choice, need, and cost"})
    score = max(35.0, 100.0 - 25.0 * len([item for item in drift if item.get("severity") == "high"]) - 12.0 * len([item for item in drift if item.get("severity") == "medium"]))
    return {"score": score, "checked_characters": checked, "drift_issues": drift, "status": "blocked" if any(item.get("severity") == "high" for item in drift) else "warning" if drift else "passed"}


def _power_scale_conflicts(rows: list[dict[str, Any]], target_text: str) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    lowered = target_text.lower()
    for row in rows:
        data = row.get("data", {})
        if data.get("type") != "power_scale_rule":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        scale_id = str(content.get("scale_id") or data.get("title") or data.get("id"))
        for check in _list_items(content.get("violation_checks")):
            check_text = str(check).strip()
            if check_text and _soft_terms_hit(lowered, check_text):
                conflicts.append({"dimension": "power_scale_conflict", "severity": "high", "scale_id": scale_id, "message": f"power-scale violation appears: {check_text}", "recommendation": "rewrite the scene so power use pays the declared cost", "evidence": {"source_path": row.get("path", ""), "violation_check": check_text}})
        constraints = " ".join(str(item) for item in _list_items(content.get("constraints")))
        if constraints and _cost_bypass_signal(lowered, constraints):
            conflicts.append({"dimension": "power_scale_conflict", "severity": "high", "scale_id": scale_id, "message": "draft implies power use bypasses declared cost", "recommendation": "add sacrifice, cooldown, failure risk, or explicit limitation"})
    score = max(30.0, 100.0 - 35.0 * len(conflicts))
    return {"score": score, "conflicts": conflicts, "status": "blocked" if conflicts else "passed"}


def _chapter_pleasure_toxicity(target_text: str, *, motivation: dict[str, Any], power: dict[str, Any]) -> dict[str, Any]:
    clean = target_text.strip()
    lowered = clean.lower()
    pleasure_points: list[dict[str, Any]] = []
    toxic_points: list[dict[str, Any]] = []
    if any(term in clean for term in ["忽然", "秘密", "线索", "门", "钥匙", "钟声", "hook", "reveal", "mystery"]):
        pleasure_points.append({"kind": "hook_or_mystery", "score": 18, "evidence": "chapter contains reveal/mystery signal"})
    if any(term in clean for term in ["选择", "代价", "牺牲", "成本", "cost", "sacrifice", "risk"]):
        pleasure_points.append({"kind": "costly_choice", "score": 20, "evidence": "visible cost/choice signal"})
    if any(term in clean for term in ["却", "但是", "然而", "反而", "suddenly", "but", "instead"]):
        pleasure_points.append({"kind": "reversal", "score": 14, "evidence": "reversal marker present"})
    if any(term in clean for term in ["必须", "决定", "追", "挡", "推开", "拒绝", "choose", "must", "fight"]):
        pleasure_points.append({"kind": "agency", "score": 18, "evidence": "character agency marker present"})
    if len(clean) < 80:
        toxic_points.append({"kind": "thin_chapter", "severity": "medium", "score": 18, "message": "chapter is too short for reliable payoff"})
    if motivation.get("status") != "passed":
        toxic_points.extend({**item, "kind": "motivation_drift", "score": 25 if item.get("severity") == "high" else 12} for item in motivation.get("drift_issues", []))
    if power.get("status") == "blocked":
        toxic_points.extend({**item, "kind": "power_scale_conflict", "score": 30} for item in power.get("conflicts", []))
    if not any(point.get("kind") == "agency" for point in pleasure_points):
        toxic_points.append({"kind": "low_agency", "severity": "medium", "score": 12, "message": "chapter lacks visible protagonist action/decision"})
    pleasure_score = min(100.0, 35.0 + sum(float(item.get("score", 0)) for item in pleasure_points))
    toxicity_score = min(100.0, sum(float(item.get("score", 0)) for item in toxic_points))
    return {
        "pleasure_score": pleasure_score,
        "toxicity_score": toxicity_score,
        "net_score": max(0.0, pleasure_score - toxicity_score * 0.55),
        "pleasure_points": pleasure_points,
        "toxic_points": toxic_points,
        "status": "blocked" if any(item.get("severity") == "high" for item in toxic_points) else "warning" if toxic_points else "passed",
    }


def _platform_adaptation_review(target_text: str, context: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    platform = profiles.get("platform_profile", {}) if isinstance(profiles.get("platform_profile", {}), dict) else {}
    platform_content = platform.get("content", {}) if isinstance(platform.get("content", {}), dict) else {}
    issues: list[dict[str, Any]] = []
    if not platform:
        issues.append({"dimension": "platform_semantic_fit", "severity": "medium", "message": "platform_profile is not bound", "recommendation": "bind platform_profile before final publish gate"})
    target_hook_floor = float(platform_content.get("semantic_hook_floor", 55.0) or 55.0)
    if float(chapter.get("pleasure_score", 0) or 0) < target_hook_floor:
        issues.append({"dimension": "platform_semantic_fit", "severity": "medium", "message": "chapter hook/pleasure signal is below platform target", "recommendation": "increase hook, reversal, agency, or paid-off curiosity"})
    risk_terms = platform_content.get("review_risks", []) if isinstance(platform_content.get("review_risks", []), list) else []
    lowered = target_text.lower()
    for term in risk_terms:
        value = str(term).strip().lower()
        if value and value in lowered:
            issues.append({"dimension": "platform_semantic_fit", "severity": "medium", "message": f"platform-sensitive semantic term appears: {term}", "recommendation": "revise or route through human platform review"})
    score = max(45.0, 100.0 - 15.0 * len(issues) - max(0.0, 60.0 - float(chapter.get("pleasure_score", 0) or 0)) * 0.3)
    return {"score": round(score, 2), "passed": not any(item.get("severity") == "high" for item in issues), "issues": issues}


def _semantic_issues(motivation: dict[str, Any], power: dict[str, Any], chapter: dict[str, Any], platform: dict[str, Any], foreshadowing: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(motivation.get("drift_issues", []) if isinstance(motivation.get("drift_issues", []), list) else [])
    issues.extend(power.get("conflicts", []) if isinstance(power.get("conflicts", []), list) else [])
    issues.extend(chapter.get("toxic_points", []) if isinstance(chapter.get("toxic_points", []), list) else [])
    issues.extend(platform.get("issues", []) if isinstance(platform.get("issues", []), list) else [])
    for item in foreshadowing.get("threads", []) if isinstance(foreshadowing.get("threads", []), list) else []:
        if item.get("severity") in {"medium", "high"}:
            issues.append({"dimension": "foreshadowing_lifecycle", "severity": item.get("severity", "medium"), "message": f"foreshadowing thread {item.get('thread_id')} status is {item.get('status')}", "recommendation": "add setup/payoff evidence or update thread lifecycle", "evidence": item.get("evidence", {})})
    return _dedupe_issue_rows(issues)


def _upsert_entity(
    rows: dict[str, dict[str, Any]],
    name: str,
    entity_type: str,
    data: dict[str, Any],
    source_path: str,
    aliases: list[str],
    *,
    confidence: float,
    evidence_spans: list[dict[str, Any]],
) -> None:
    clean = str(name).strip()
    if not clean or len(clean) > 80:
        return
    key = f"{entity_type}:{_normalize(clean)}"
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    existing = rows.get(key, {})
    rows[key] = {
        "id": existing.get("id") or f"semantic-entity-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}",
        "name": clean,
        "entity_type": entity_type,
        "aliases": _dedupe([*existing.get("aliases", []), *aliases]) if existing else _dedupe(aliases),
        "source_asset_id": existing.get("source_asset_id") or data.get("id", ""),
        "source_asset_type": existing.get("source_asset_type") or data.get("type", ""),
        "source_path": existing.get("source_path") or source_path,
        "project_id": existing.get("project_id") or metadata.get("project_id", ""),
        "workspace_path": existing.get("workspace_path") or metadata.get("workspace_path", ""),
        "confidence": max(float(existing.get("confidence", 0) or 0), confidence),
        "evidence_spans": _dedupe_spans([*existing.get("evidence_spans", []), *evidence_spans]) if existing else evidence_spans,
        "attributes": {"semantic_extraction": True, "extractor": "semantic-enhancement-v1"},
    }


def _known_entity_spans(rows: list[dict[str, Any]], aliases: list[str], fallback_path: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for row in rows:
        text = _asset_text(row.get("data", {}))
        for alias in aliases:
            span = _first_span(text, alias, str(row.get("path", fallback_path)), "known_alias")
            if span:
                spans.append(span)
                break
    return _dedupe_spans(spans)[:5]


def _named_inventory(content: dict[str, Any], keys: list[str], row: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in _list_items(_first_value(content, keys)):
        if isinstance(value, dict):
            name = str(value.get("name") or value.get("title") or value.get("id") or "").strip()
            aliases = _aliases(value, name)
        else:
            name = str(value).strip()
            aliases = [name]
        if name:
            items.append({"name": name, "aliases": aliases, "asset": row})
    return items


def _capitalized_terms(text: str) -> list[str]:
    terms = re.findall(r"\b(?:[A-Z][a-zA-Z0-9]+(?:[ \t]+[A-Z][a-zA-Z0-9]+){0,3})\b", text)
    cjk_terms = re.findall(r"(?:人物|角色|地点|势力|道具|线索|钥匙|钟楼|北塔|公会|宗门|家族)[:：]?\s*([\u4e00-\u9fffA-Za-z0-9 ]{2,24})", text)
    blocked = {"The", "A", "An", "I"}
    return _dedupe([term.strip() for term in [*terms, *cjk_terms] if term.strip() and term.strip() not in blocked])


def _classify_term(term: str, text: str) -> str:
    lowered = term.lower()
    if any(word in lowered for word in ["guild", "sect", "clan", "order", "agency", "faction"]):
        return "faction"
    if any(word in lowered for word in ["tower", "city", "room", "gate", "valley", "north", "south"]):
        return "location"
    if any(word in lowered for word in ["key", "sword", "bell", "ring", "artifact", "token"]):
        return "prop"
    window = text[max(0, text.find(term) - 20) : text.find(term) + len(term) + 20] if term in text else ""
    if any(word in window for word in ["她", "他", "protagonist", "主角", "人物", "角色"]):
        return "character"
    return "semantic_entity"


def _cost_bypass_signal(lowered_text: str, constraints: str) -> bool:
    if not constraints:
        return False
    cost_words = ["cost", "sacrifice", "memory", "代价", "牺牲", "记忆", "成本"]
    bypass_words = ["free", "without", "no cost", "无需", "不用", "免费", "没有代价", "不付出"]
    return any(word in constraints.lower() for word in cost_words) and any(word in lowered_text for word in bypass_words)


def _soft_terms_hit(text: str, phrase: str) -> bool:
    phrase = str(phrase or "").strip()
    if not phrase:
        return False
    lowered = text.lower()
    terms = [item for item in re.split(r"[\s,，;；。:：/]+", phrase.lower()) if len(item) >= 2]
    if not terms:
        return phrase.lower() in lowered
    hits = sum(1 for term in terms if term in lowered)
    return hits >= max(1, min(2, len(terms)))


def _phrase_hit(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return _soft_terms_hit(text, phrase)


def _asset_text(data: dict[str, Any]) -> str:
    values: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data.get("content", {}) if isinstance(data, dict) else {})
    if isinstance(data, dict):
        values.extend([str(data.get("title", "")), str(data.get("name", ""))])
    return "\n".join(item for item in values if item)


def _last_draft_or_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for asset_type in ["draft_version", "draft_chapter", "chapter_plan_version", "chapter_plan"]:
        for row in reversed(rows):
            if row.get("data", {}).get("type") == asset_type:
                return row
    return rows[-1] if rows else {}


def _aliases(content: dict[str, Any], name: str) -> list[str]:
    aliases = [name]
    for key in ["aliases", "alias", "nicknames", "names"]:
        value = content.get(key)
        if isinstance(value, list):
            aliases.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            aliases.append(value)
    return _dedupe(aliases)


def _first_value(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return []


def _list_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()] or [value]
    return [value]


def _first_span(text: str, needle: str, source_path: str, extractor: str) -> dict[str, Any]:
    if not text or not needle:
        return {}
    index = text.lower().find(str(needle).lower())
    if index < 0:
        return {}
    end = index + len(str(needle))
    return {
        "source_path": source_path,
        "field": "content",
        "start": index,
        "end": end,
        "text": text[index:end],
        "context": text[max(0, index - 40) : min(len(text), end + 40)],
        "extractor": extractor,
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        value = str(value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        rows.append(value)
    return rows


def _dedupe_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for span in spans:
        key = f"{span.get('source_path')}:{span.get('start')}:{span.get('end')}:{span.get('text')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(span)
    return rows


def _dedupe_issue_rows(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in issues:
        key = f"{item.get('dimension')}:{item.get('severity')}:{item.get('message')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
