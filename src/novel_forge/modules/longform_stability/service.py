from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_governance import record_fallback_decision
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import (
    ArcPlan,
    CanonDatabase,
    ChapterPatternReport,
    ChapterStatePackage,
    CharacterStateLedger,
    FactLedger,
    ForeshadowingGraph,
    MotifBudgetReport,
    PlatformAdapterReport,
    ReaderFatigueReport,
    ReviewScoreSystemReport,
    RevisionTask,
    RewardLedger,
    SemanticExtractionReport,
    StyleControlPlan,
    VillainOperationPlan,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


META_LEAK_PATTERNS = [
    r'\{\s*"text"\s*:',
    r'"notes"\s*:',
    r'"metadata"\s*:',
    r"copyright_boundary",
    r"\bprompt\b",
    r"本章目标",
    r"写作策略",
    r"生成说明",
    r"YAML wrapper",
    r"JSON wrapper",
]

DEFAULT_MOTIF_BUDGET = {
    "paper_core_clue": 2,
    "grey_core_clue": 2,
    "tax_core_conflict": 2,
    "well_case": 1,
    "lamp_case": 1,
    "mentor_debt_trigger": 3,
    "bureau_pressure_scene": 3,
}

MOTIF_KEYWORDS = {
    "paper_core_clue": ["纸", "旧纸", "纸页", "纸灯"],
    "grey_core_clue": ["灰", "验灰", "石灰", "贝灰"],
    "tax_core_conflict": ["税", "税契", "税筹", "隐税", "课"],
    "well_case": ["井", "旧井", "井税"],
    "lamp_case": ["灯", "灯契", "灯影", "灯骨"],
    "mentor_debt_trigger": ["师父", "旧债", "债牌", "代偿", "承责", "担责", "代押"],
    "bureau_pressure_scene": ["官署", "封存", "移交", "问责", "封铺", "封桥", "城课司", "税契所"],
}

KNOWN_ORG_SUFFIXES = ("司", "所", "房", "库", "曹", "监", "局", "署", "坊", "司署")
KNOWN_PERSON_DRIFT_NAMES = {"顾砚秋", "江砚", "沈砚", "阿照", "温砚", "周照夜"}

LONGFORM_ASSET_TYPES = {
    "canon_database",
    "semantic_extraction_report",
    "chapter_state",
    "chapter_pattern_report",
    "fact_ledger",
    "arc_plan",
    "foreshadowing_graph",
    "motif_budget_report",
    "character_state_ledger",
    "villain_operation_plan",
    "reader_fatigue_report",
    "style_control_plan",
    "platform_adapter_report",
    "reward_ledger",
    "review_score_system_report",
    "longform_recap_report",
    "publish_gate_report",
    "revision_task",
    "model_call_log",
    "cost_ledger",
    "gate_result",
}


def build_default_night_archive_canon() -> list[dict[str, Any]]:
    return [
        {
            "entity_id": "azhao",
            "entity_type": "character",
            "canonical_name": "阿照",
            "aliases": [],
            "forbidden_aliases": ["顾砚秋", "江砚", "沈砚"],
            "role": "protagonist",
            "status": "active",
        },
        {
            "entity_id": "night_archive_office",
            "entity_type": "organization",
            "canonical_name": "夜档司",
            "aliases": ["巡遗司"],
            "forbidden_aliases": ["遗簿库", "北档房", "夜档库"],
            "role": "core_organization",
            "status": "active",
        },
        {
            "entity_id": "mentor_debt",
            "entity_type": "case",
            "canonical_name": "师父旧债",
            "aliases": ["旧债", "师父债"],
            "forbidden_aliases": [],
            "role": "mainline_case",
            "status": "active",
        },
    ]


def create_canon_database(
    storage: LocalStorage,
    *,
    entities: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    title: str = "Long-form canon database",
) -> dict[str, Any]:
    storage.ensure_layout()
    resolved_entities = entities if entities is not None else build_default_night_archive_canon()
    content = {
        "canon_id": make_id("canon_database", project_id or workspace_path or title),
        "project_id": project_id or "",
        "entities": resolved_entities,
        "rules": {
            "forbidden_alias_policy": "fail",
            "unregistered_core_entity_policy": "warning",
            "generated_chapters_must_reference_canon": True,
        },
        "created_at": utc_now(),
    }
    asset = CanonDatabase(
        title=title,
        tags=["canon", "longform-stability"],
        content=content,
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or "", "workflow": "longform-stability"},
    )
    return _write(storage, asset)


def create_arc_plan(
    storage: LocalStorage,
    *,
    arc_id: str,
    title: str,
    chapter_range: str,
    arc_question: str,
    protagonist_goal: str,
    villain_goal: str,
    required_payoffs: list[str] | None = None,
    forbidden_expansion: list[str] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    storage.ensure_layout()
    asset = ArcPlan(
        title=title,
        tags=["arc-plan", "longform-stability"],
        content={
            "arc_id": arc_id,
            "title": title,
            "chapter_range": chapter_range,
            "arc_question": arc_question,
            "protagonist_goal": protagonist_goal,
            "villain_goal": villain_goal,
            "required_payoffs": required_payoffs or [],
            "forbidden_expansion": forbidden_expansion or [],
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id or "", "workspace_path": workspace_path or "", "workflow": "arc-planner"},
    )
    return _write(storage, asset)


def upsert_longform_control_asset(
    storage: LocalStorage,
    *,
    asset_type: str,
    content: dict[str, Any] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    title: str = "",
) -> dict[str, Any]:
    """Create a manually editable long-form control asset.

    UI editors use this instead of writing arbitrary JSON. The service keeps
    each asset schema-backed and normalizes the minimum fields the gates need.
    """

    storage.ensure_layout()
    payload = content if isinstance(content, dict) else {}
    normalized = str(asset_type or "").strip().lower()
    metadata = {"project_id": project_id or "", "workspace_path": workspace_path or "", "workflow": "longform-control-editor"}
    if normalized == "canon_database":
        entities = payload.get("entities", []) if isinstance(payload.get("entities", []), list) else build_default_night_archive_canon()
        return create_canon_database(storage, entities=entities, project_id=project_id, workspace_path=workspace_path, title=title or "Long-form canon database")
    if normalized == "arc_plan":
        return create_arc_plan(
            storage,
            arc_id=str(payload.get("arc_id") or make_id("arc", title or project_id or "manual")),
            title=title or str(payload.get("title") or "Manual Arc Plan"),
            chapter_range=str(payload.get("chapter_range") or "1-10"),
            arc_question=str(payload.get("arc_question") or ""),
            protagonist_goal=str(payload.get("protagonist_goal") or ""),
            villain_goal=str(payload.get("villain_goal") or ""),
            required_payoffs=payload.get("required_payoffs", []) if isinstance(payload.get("required_payoffs", []), list) else [],
            forbidden_expansion=payload.get("forbidden_expansion", []) if isinstance(payload.get("forbidden_expansion", []), list) else [],
            project_id=project_id,
            workspace_path=workspace_path,
        )
    if normalized == "foreshadowing_graph":
        clues = payload.get("clues", []) if isinstance(payload.get("clues", []), list) else []
        asset = ForeshadowingGraph(
            title=title or "Manual foreshadowing graph",
            tags=["foreshadowing", "manual-control", "longform-stability"],
            content={
                "graph_id": str(payload.get("graph_id") or make_id("foreshadowing_graph", project_id or workspace_path or "manual")),
                "chapter_no": int(payload.get("chapter_no", 0) or 0),
                "clues": clues,
                "edges": payload.get("edges", []) if isinstance(payload.get("edges", []), list) else [],
                "issues": _manual_foreshadowing_issues(clues),
                "status": "active",
                "created_at": utc_now(),
            },
            metadata=metadata,
        )
        return _write(storage, asset)
    if normalized == "character_state_ledger":
        asset = CharacterStateLedger(
            title=title or "Manual character state ledger",
            tags=["character-state", "manual-control", "longform-stability"],
            content={
                "ledger_id": str(payload.get("ledger_id") or make_id("character_state_ledger", project_id or workspace_path or "manual")),
                "chapter_no": int(payload.get("chapter_no", 0) or 0),
                "characters": payload.get("characters", []) if isinstance(payload.get("characters", []), list) else [],
                "debt_policy": payload.get("debt_policy", {"new_liability_threshold": 2}) if isinstance(payload.get("debt_policy", {}), dict) else {"new_liability_threshold": 2},
                "status": "active",
                "created_at": utc_now(),
            },
            metadata=metadata,
        )
        return _write(storage, asset)
    if normalized == "villain_operation_plan":
        asset = VillainOperationPlan(
            title=title or "Manual villain operation model",
            tags=["villain-operation", "manual-control", "longform-stability"],
            content={
                "operation_id": str(payload.get("operation_id") or make_id("villain_operation_plan", project_id or workspace_path or "manual")),
                "chapter_no": int(payload.get("chapter_no", 0) or 0),
                "arc_id": str(payload.get("arc_id") or "unassigned"),
                "visible_agent": str(payload.get("visible_agent") or "unassigned"),
                "public_identity": str(payload.get("public_identity") or ""),
                "hidden_goal": str(payload.get("hidden_goal") or ""),
                "signatures": payload.get("signatures", []) if isinstance(payload.get("signatures", []), list) else [],
                "current_wins": payload.get("current_wins", []) if isinstance(payload.get("current_wins", []), list) else [],
                "operations": payload.get("operations", []) if isinstance(payload.get("operations", []), list) else [],
                "status": "active",
                "created_at": utc_now(),
            },
            metadata=metadata,
        )
        return _write(storage, asset)
    raise ValueError(f"unsupported longform control asset_type: {asset_type}")


def latest_canon_database(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any] | None:
    for path in reversed(storage.list_json("continuity")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "canon_database":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        data["_path"] = _display_path(storage.root, path)
        return data
    return None


def sanitize_chapter_text(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "")
    stripped = text.strip()
    issues: list[dict[str, Any]] = []
    sanitized = text
    extracted = False

    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except Exception as exc:
            issues.append(_issue("output_sanitizer", "high", f"chapter text starts as JSON but cannot be parsed: {exc}", "regenerate plain chapter text"))
        else:
            if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                sanitized = payload["text"]
                extracted = True
                issues.append(_issue("json_wrapper_detected", "high", "chapter body is wrapped in a JSON text field", "extract clean text and regenerate without wrappers"))
            else:
                issues.append(_issue("json_wrapper_invalid", "high", "JSON wrapper does not expose a string text field", "regenerate plain chapter text"))
            for key in ["notes", "metadata", "prompt", "copyright_boundary"]:
                if key in payload:
                    issues.append(_issue("metadata_leak", "high", f"JSON wrapper contains forbidden metadata key: {key}", "remove non-prose metadata from the chapter body"))

    if stripped.startswith("---"):
        issues.append(_issue("yaml_wrapper_detected", "high", "chapter body starts with YAML front matter", "store YAML metadata outside the draft text"))
    if stripped.startswith("```") and stripped.endswith("```"):
        issues.append(_issue("markdown_code_fence_wrapper", "medium", "chapter body is wrapped in a markdown code fence", "store only the prose body"))

    scan_text = text if not extracted else f"{text}\n{sanitized}"
    for pattern in META_LEAK_PATTERNS:
        if re.search(pattern, scan_text, flags=re.IGNORECASE):
            severity = "high" if pattern not in {r"JSON wrapper"} else "medium"
            issues.append(_issue("metadata_leak", severity, f"chapter body contains forbidden marker matching {pattern}", "remove prompt/metadata wrappers before storage"))

    deduped = _dedupe_issues(issues)
    status = "fail" if any(item.get("severity") == "high" for item in deduped) else "warning" if deduped else "pass"
    return {
        "status": status,
        "text": sanitized.strip(),
        "issues": deduped,
        "extracted_text": extracted,
        "action": "generate_revision_task" if status == "fail" else "allow_clean_text" if extracted else "none",
    }


def check_canon_consistency(text: str, canon_database: dict[str, Any] | None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not canon_database:
        return {
            "status": "fail",
            "issues": [_issue("canon_database", "high", "missing Canon Database for generated chapter", "create and bind canon_database before long-form generation")],
            "matched_entities": [],
            "drift_report": {"forbidden_alias_hits": [], "unregistered_core_entities": []},
        }
    content = canon_database.get("content", {}) if isinstance(canon_database.get("content", {}), dict) else {}
    entities = content.get("entities", []) if isinstance(content.get("entities", []), list) else []
    canonical_names = {str(item.get("canonical_name", "")).strip() for item in entities if isinstance(item, dict)}
    allowed_aliases = {
        str(alias).strip()
        for item in entities
        if isinstance(item, dict)
        for alias in item.get("aliases", [])
        if str(alias).strip()
    }
    matched: list[dict[str, Any]] = []
    forbidden_hits: list[dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        canonical = str(entity.get("canonical_name", "")).strip()
        if canonical and canonical in text:
            matched.append(
                {
                    "entity_id": entity.get("entity_id", ""),
                    "entity_type": entity.get("entity_type", ""),
                    "canonical_name": canonical,
                    "hit_type": "canonical",
                }
            )
        for alias in entity.get("aliases", []) if isinstance(entity.get("aliases", []), list) else []:
            alias_text = str(alias).strip()
            if alias_text and alias_text in text:
                matched.append(
                    {
                        "entity_id": entity.get("entity_id", ""),
                        "entity_type": entity.get("entity_type", ""),
                        "canonical_name": canonical,
                        "alias": alias_text,
                        "hit_type": "allowed_alias",
                    }
                )
        for alias in entity.get("forbidden_aliases", []) if isinstance(entity.get("forbidden_aliases", []), list) else []:
            alias_text = str(alias).strip()
            if alias_text and alias_text in text:
                hit = {
                    "entity_id": entity.get("entity_id", ""),
                    "canonical_name": canonical,
                    "forbidden_alias": alias_text,
                }
                forbidden_hits.append(hit)
                issues.append(_issue("canon_forbidden_alias", "high", f"forbidden alias appears in chapter: {alias_text}", f"replace with canonical name {canonical}"))

    unregistered = sorted(
        name
        for name in KNOWN_PERSON_DRIFT_NAMES
        if name in text and name not in canonical_names and name not in allowed_aliases and all(hit.get("forbidden_alias") != name for hit in forbidden_hits)
    )
    unregistered.extend(_unregistered_organizations(text, canonical_names | allowed_aliases))
    for name in _dedupe(unregistered):
        issues.append(_issue("canon_unregistered_entity", "medium", f"potential core entity is not registered in canon: {name}", "register the entity or revise the chapter"))

    status = "fail" if any(item.get("severity") == "high" for item in issues) else "warning" if issues else "pass"
    return {
        "status": status,
        "issues": _dedupe_issues(issues),
        "matched_entities": matched,
        "drift_report": {"forbidden_alias_hits": forbidden_hits, "unregistered_core_entities": _dedupe(unregistered)},
    }


def extract_chapter_state(
    text: str,
    *,
    chapter_no: int,
    canon_database: dict[str, Any] | None = None,
    active_arc: str = "",
) -> dict[str, Any]:
    canon = canon_database or {"content": {"entities": []}}
    content = canon.get("content", {}) if isinstance(canon.get("content", {}), dict) else {}
    entities = content.get("entities", []) if isinstance(content.get("entities", []), list) else []
    chars = _matched_entity_names(text, entities, "character")
    orgs = _matched_entity_names(text, entities, "organization")
    locations = _extract_locations(text)
    facts = _extract_fact_sentences(text)
    clues = _extract_open_clues(text)
    liabilities = _extract_liabilities(text, chapter_no=chapter_no)
    forbidden_next = _forbidden_next_from_text(text)
    return {
        "state_id": make_id("chapter_state", f"chapter-{chapter_no}-{utc_now()}"),
        "chapter_no": chapter_no,
        "active_arc": active_arc or "unassigned",
        "active_characters": chars,
        "active_organizations": orgs,
        "active_locations": locations,
        "confirmed_facts": facts,
        "open_clues": clues,
        "unresolved_debts": _debt_mentions(text),
        "character_liabilities": liabilities,
        "forbidden_next": forbidden_next,
        "created_at": utc_now(),
    }


def create_chapter_state_package(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    canon_database: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    canon = canon_database or latest_canon_database(storage, project_id=str(project.get("project_id", "")) or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path)
    arc = _latest_arc_plan(storage, project_id=str(project.get("project_id", "")) or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path)
    state = extract_chapter_state(
        _asset_text(draft),
        chapter_no=chapter_no,
        canon_database=canon,
        active_arc=str((arc or {}).get("content", {}).get("title", "")) if isinstance((arc or {}).get("content", {}), dict) else "",
    )
    asset = ChapterStatePackage(
        title=f"Chapter {chapter_no} state package",
        source=draft.id,
        tags=["chapter-state", "longform-stability"],
        content=state,
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path), str((canon or {}).get("id", ""))]),
    )
    return _write(storage, asset)


def require_chapter_state_for_generation(
    storage: LocalStorage,
    chapter_no: int,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    if int(chapter_no or 1) <= 1:
        return {"required": False, "state": {}, "path": ""}
    state = _latest_chapter_state(storage, before_chapter=chapter_no, project_id=project_id, workspace_path=workspace_path)
    if not state:
        raise ValueError("long-form continuation blocked: missing previous chapter_state package")
    return {"required": True, "state": state.get("content", {}), "path": state.get("_path", "")}


def extract_pattern_fingerprint(text: str, *, chapter_no: int) -> dict[str, Any]:
    return {
        "chapter_no": chapter_no,
        "anomaly_type": _first_matching_label(
            text,
            [
                ("旧物显字", ["显字", "字迹浮", "写着"]),
                ("旧物异动", ["自己", "响", "醒", "裂开", "爬"]),
                ("旧账复现", ["旧账", "账册", "残簿", "旧契"]),
            ],
            default="旧物异动",
        ),
        "investigation_method": _investigation_method(text),
        "pressure_type": _first_matching_label(
            text,
            [
                ("官署封存", ["封存", "移交", "封铺", "封桥"]),
                ("官署问责", ["问责", "抗令", "候问", "追责"]),
                ("民生围压", ["围观", "街坊", "铺户", "百姓", "损失"]),
            ],
            default="",
        ),
        "counterattack_type": _first_matching_label(
            text,
            [
                ("规矩反压", ["旧例", "规矩", "按例", "印令", "见证印"]),
                ("承责推进", ["承责", "担责", "赔单", "签名", "代押"]),
                ("物证反证", ["证袋", "物证", "验", "封存"]),
            ],
            default="",
        ),
        "assistant_function": _first_matching_label(text, [("吐槽/提问", ["小满", "钱小满", "阿照", "沈槐"])], default=""),
        "emotional_payoff": _first_matching_label(
            text,
            [
                ("百姓暂时获救", ["保住", "散去", "可过", "暂时"]),
                ("主角付出代价", ["承责", "担责", "旧债", "代偿", "赔单"]),
            ],
            default="",
        ),
        "ending_hook": _ending_hook(text),
    }


def create_chapter_pattern_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    fingerprint = extract_pattern_fingerprint(_asset_text(draft), chapter_no=chapter_no)
    history = _recent_pattern_fingerprints(storage, project_id=str(project.get("project_id", "")) or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path, before_chapter=chapter_no, limit=10)
    checks = _pattern_checks(history, fingerprint)
    recommendation = "block" if any(item.get("severity") == "high" for item in checks) else "revise" if checks else "pass"
    asset = ChapterPatternReport(
        title=f"Chapter {chapter_no} pattern report",
        source=draft.id,
        tags=["chapter-pattern", "longform-stability", recommendation],
        content={
            "report_id": make_id("chapter_pattern_report", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "fingerprint": fingerprint,
            "similarity_checks": checks,
            "history_window": history[-10:],
            "recommendation": recommendation,
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_fact_ledger(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    facts = _extract_fact_sentences(_asset_text(draft))
    asset = FactLedger(
        title=f"Chapter {chapter_no} fact ledger",
        source=draft.id,
        tags=["fact-ledger", "longform-stability"],
        content={
            "ledger_id": make_id("fact_ledger", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "facts": [{"fact_id": make_id("fact", item), "text": item, "source_chapter": chapter_no, "status": "confirmed"} for item in facts],
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_motif_budget_report(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    current = _motif_usage(_asset_text(draft), chapter_no=chapter_no)
    history = _recent_motif_usage(storage, project_id=str(project.get("project_id", "")) or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path, before_chapter=chapter_no, limit=9)
    issues = _motif_budget_issues([*history, current], DEFAULT_MOTIF_BUDGET)
    recommendation = "block" if any(item.get("severity") == "high" for item in issues) else "revise" if issues else "pass"
    asset = MotifBudgetReport(
        title=f"Chapter {chapter_no} motif budget report",
        source=draft.id,
        tags=["motif-budget", "longform-stability", recommendation],
        content={
            "report_id": make_id("motif_budget_report", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "motif_usage": current,
            "window_usage": _sum_motif_usage([*history, current]),
            "budget": {"per_10_chapters": DEFAULT_MOTIF_BUDGET},
            "issues": issues,
            "recommendation": recommendation,
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_character_state_ledger(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    text = _asset_text(draft)
    liabilities = _extract_liabilities(text, chapter_no=chapter_no)
    remaining = max(0, 100 - len(liabilities))
    asset = CharacterStateLedger(
        title=f"Chapter {chapter_no} character state ledger",
        source=draft.id,
        tags=["character-state", "debt-ledger", "longform-stability"],
        content={
            "ledger_id": make_id("character_state_ledger", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "characters": [
                {
                    "character_id": "azhao" if "阿照" in text else "protagonist",
                    "authority": "夜档司巡遗人" if "夜档司" in text or "巡遗司" in text else "",
                    "reputation": {},
                    "active_burdens": _debt_mentions(text),
                    "risks": [item.get("risk", "") for item in liabilities],
                    "debt_ledger": {
                        "inherited_total": 100,
                        "cleared": 100 - remaining,
                        "remaining": remaining,
                        "new_liabilities": liabilities,
                    },
                }
            ],
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_foreshadowing_graph(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    arc = _latest_arc_plan(storage, project_id=str(project.get("project_id", "")) or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path)
    target_truth = ""
    if arc and isinstance(arc.get("content", {}), dict):
        target_truth = str(arc["content"].get("arc_question", "") or arc["content"].get("title", ""))
    clues = [
        {
            "clue_id": make_id("clue", clue),
            "name": clue,
            "source_chapter": chapter_no,
            "target_truth": target_truth,
            "planned_payoff_chapter": _planned_payoff_chapter(arc, chapter_no),
            "status": "active",
            "last_updated_chapter": chapter_no,
        }
        for clue in _extract_open_clues(_asset_text(draft))
    ]
    issues = []
    for clue in clues:
        if not clue.get("target_truth"):
            issues.append(_issue("foreshadowing_target_truth", "high", f"new clue lacks target_truth: {clue.get('name')}", "bind every new clue to an arc truth before publish"))
    asset = ForeshadowingGraph(
        title=f"Chapter {chapter_no} foreshadowing graph",
        source=draft.id,
        tags=["foreshadowing", "longform-stability"],
        content={
            "graph_id": make_id("foreshadowing_graph", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "clues": clues,
            "edges": [{"source": clue["clue_id"], "target": clue.get("target_truth", ""), "relation": "points_to_truth"} for clue in clues],
            "issues": issues,
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path), str((arc or {}).get("id", ""))]),
    )
    return _write(storage, asset)


def create_villain_operation_plan(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    text = _asset_text(draft)
    arc = _latest_arc_plan(storage, project_id=str(project.get("project_id", "")) or None, workspace_path=str(project.get("workspace_path", "")) or workspace_path)
    arc_id = str((arc or {}).get("content", {}).get("arc_id", "")) if isinstance((arc or {}).get("content", {}), dict) else ""
    visible_agent = _visible_villain_agent(text)
    operations = []
    if visible_agent or "有人" in text:
        operations.append(
            {
                "chapter_no": chapter_no,
                "villain_action": _villain_action(text),
                "target": _villain_target(text),
                "gain": "obtains procedural pressure over the protagonist or civilians",
                "protagonist_loss": "forced into liability or reactive investigation" if re.search("承责|担责|代偿|旧债|师父", text) else "",
            }
        )
    asset = VillainOperationPlan(
        title=f"Chapter {chapter_no} villain operation model",
        source=draft.id,
        tags=["villain-operation", "longform-stability"],
        content={
            "operation_id": make_id("villain_operation_plan", f"{draft.id}-{chapter_no}"),
            "arc_id": arc_id or "unassigned",
            "visible_agent": visible_agent or "unassigned",
            "public_identity": "",
            "hidden_goal": "复活旧城隐税机制或迫使主角承接旧债" if "税" in text or "债" in text else "unassigned",
            "signatures": _extract_open_clues(text)[:6],
            "operations": operations,
            "current_wins": [op.get("gain", "") for op in operations if op.get("gain")],
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_reader_fatigue_report(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    text = _asset_text(draft)
    repeated_terms = [key for key, terms in MOTIF_KEYWORDS.items() if sum(text.count(term) for term in terms) >= 3]
    fatigue_score = min(100, 20 + 10 * len(repeated_terms) + (15 if "旧债" in text[-1500:] else 0) + (15 if "封存" in text else 0))
    recommendations = _fatigue_recommendations(repeated_terms)
    asset = ReaderFatigueReport(
        title=f"Chapter {chapter_no} reader fatigue report",
        source=draft.id,
        tags=["reader-fatigue", "longform-stability"],
        content={
            "report_id": make_id("reader_fatigue_report", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "fatigue_score": fatigue_score,
            "risk": "high" if fatigue_score >= 80 else "medium" if fatigue_score >= 60 else "low",
            "repeated_terms": repeated_terms,
            "recommendations": recommendations,
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_style_control_plan(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    fingerprint = extract_pattern_fingerprint(_asset_text(draft), chapter_no=chapter_no)
    chapter_function = "反派行动章" if "有人" in _asset_text(draft) else "调查章"
    asset = StyleControlPlan(
        title=f"Chapter {chapter_no} style control plan",
        source=draft.id,
        tags=["style-control", "longform-stability"],
        content={
            "plan_id": make_id("style_control_plan", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "chapter_function": chapter_function,
            "style_profile": {
                "mode": "tight_investigation" if chapter_function == "调查章" else "cold_villain_pressure",
                "sentence_rhythm": "shorter and more causal for high-pressure chapters",
            },
            "forbidden_patterns": [fingerprint.get("investigation_method", ""), fingerprint.get("ending_hook", "")],
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_platform_adapter_report(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    target_platform = ""
    config = project.get("project_config", {}) if isinstance(project.get("project_config", {}), dict) else {}
    target_platform = str(config.get("target_platform", "local_serial") or "local_serial")
    text = _asset_text(draft)
    fit = "medium"
    if any(term in target_platform for term in ["知乎", "盐言", "douban", "豆瓣", "fanqie", "番茄"]):
        fit = "high"
    elif any(term in target_platform for term in ["qidian", "起点", "飞卢"]):
        fit = "low"
    asset = PlatformAdapterReport(
        title=f"Platform adapter report for {target_platform}",
        source=draft.id,
        tags=["platform-adapter", "longform-stability"],
        content={
            "report_id": make_id("platform_adapter_report", f"{draft.id}-{target_platform}"),
            "platform_id": target_platform,
            "fit": fit,
            "adjustments": _platform_adjustments(target_platform, text),
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_reward_ledger(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    chapter_no = _chapter_no(draft.to_dict())
    text = _asset_text(draft)
    asset = RewardLedger(
        title=f"Chapter {chapter_no} reward ledger",
        source=draft.id,
        tags=["reward-ledger", "longform-stability"],
        content={
            "ledger_id": make_id("reward_ledger", f"{draft.id}-{chapter_no}"),
            "chapter_no": chapter_no,
            "rewards": _reward_events(text),
            "costs": _debt_mentions(text),
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path)]),
    )
    return _write(storage, asset)


def create_review_score_system_report(storage: LocalStorage, draft_path: str | Path, *, workspace_path: str | None = None) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    review = _latest_review_for_draft(storage, draft.id, project_id=str(project.get("project_id", "")) or None)
    score = float(review.get("score", 0.0)) if review else 0.0
    recommendation = "pass" if score >= 80 else "revise" if review else "missing_review"
    asset = ReviewScoreSystemReport(
        title=f"Review score gate for {draft.title or draft.id}",
        source=draft.id,
        tags=["review-score", "longform-stability", recommendation],
        content={
            "report_id": make_id("review_score_system_report", f"{draft.id}-{score}"),
            "target_asset_id": draft.id,
            "scores": {"review_score": score, "review_report_id": review.get("id", "") if review else ""},
            "thresholds": {"publish_minimum": 80},
            "recommendation": recommendation,
            "created_at": utc_now(),
        },
        metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "draft_path": _display_path(storage.root, path)},
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), [draft.id, _display_path(storage.root, path), str(review.get("id", "")) if review else ""]),
    )
    return _write(storage, asset)


def create_longform_artifacts_for_draft(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    results = {
        "chapter_state_path": create_chapter_state_package(storage, draft_path, workspace_path=workspace_path)["path"],
        "chapter_pattern_report_path": create_chapter_pattern_report(storage, draft_path, workspace_path=workspace_path)["path"],
        "fact_ledger_path": create_fact_ledger(storage, draft_path, workspace_path=workspace_path)["path"],
        "motif_budget_report_path": create_motif_budget_report(storage, draft_path, workspace_path=workspace_path)["path"],
        "character_state_ledger_path": create_character_state_ledger(storage, draft_path, workspace_path=workspace_path)["path"],
        "foreshadowing_graph_path": create_foreshadowing_graph(storage, draft_path, workspace_path=workspace_path)["path"],
        "villain_operation_plan_path": create_villain_operation_plan(storage, draft_path, workspace_path=workspace_path)["path"],
        "reader_fatigue_report_path": create_reader_fatigue_report(storage, draft_path, workspace_path=workspace_path)["path"],
        "style_control_plan_path": create_style_control_plan(storage, draft_path, workspace_path=workspace_path)["path"],
        "platform_adapter_report_path": create_platform_adapter_report(storage, draft_path, workspace_path=workspace_path)["path"],
        "reward_ledger_path": create_reward_ledger(storage, draft_path, workspace_path=workspace_path)["path"],
        "review_score_system_report_path": create_review_score_system_report(storage, draft_path, workspace_path=workspace_path)["path"],
    }
    _link_draft_longform_artifacts(storage, draft_path, results)
    return results


def evaluate_longform_stability_gate(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    chapter_no = _chapter_no(draft.to_dict())
    text = _asset_text(draft)
    issues: list[dict[str, Any]] = []
    reports: dict[str, str] = {}
    gates: dict[str, bool] = {}

    sanitizer = sanitize_chapter_text(text)
    gates["output_sanitizer_passed"] = sanitizer["status"] == "pass"
    issues.extend(sanitizer["issues"])

    canon = latest_canon_database(storage, project_id=project_id or None, workspace_path=workspace or None)
    gates["canon_database_present"] = bool(canon)
    canon_result = check_canon_consistency(text, canon)
    gates["canon_consistency_passed"] = canon_result["status"] == "pass"
    issues.extend(canon_result["issues"])
    canon_path = str((canon or {}).get("_path", ""))
    if canon_path:
        reports["canon_database_path"] = canon_path

    existing_state = _chapter_state_for_draft(storage, draft.id, chapter_no=chapter_no, project_id=project_id or None, workspace_path=workspace or None)
    gates["chapter_state_preexisting"] = bool(existing_state)
    if not existing_state:
        issues.append(_issue("chapter_state", "high", "draft has no chapter_state generated after drafting", "generate chapter_state before publish gate"))
    artifact_paths = create_longform_artifacts_for_draft(storage, path, workspace_path=workspace)
    reports.update(artifact_paths)

    pattern = storage.read_json(storage.root / artifact_paths["chapter_pattern_report_path"])
    pattern_content = pattern.get("content", {}) if isinstance(pattern, dict) else {}
    pattern_issues = pattern_content.get("similarity_checks", []) if isinstance(pattern_content.get("similarity_checks", []), list) else []
    gates["pattern_similarity_passed"] = not any(item.get("severity") == "high" for item in pattern_issues)
    issues.extend(pattern_issues)

    motif = storage.read_json(storage.root / artifact_paths["motif_budget_report_path"])
    motif_content = motif.get("content", {}) if isinstance(motif, dict) else {}
    motif_issues = motif_content.get("issues", []) if isinstance(motif_content.get("issues", []), list) else []
    gates["motif_budget_passed"] = not any(item.get("severity") == "high" for item in motif_issues)
    issues.extend(motif_issues)

    gates["fact_ledger_present"] = bool(artifact_paths.get("fact_ledger_path"))

    arc = _latest_arc_plan(storage, project_id=project_id or None, workspace_path=workspace or None)
    arc_issues = _arc_progress_issues(storage, chapter_no=chapter_no, arc_plan=arc, project_id=project_id or None, workspace_path=workspace or None)
    gates["arc_progress_passed"] = not any(item.get("severity") == "high" for item in arc_issues)
    issues.extend(arc_issues)

    foreshadow = storage.read_json(storage.root / artifact_paths["foreshadowing_graph_path"])
    foreshadow_content = foreshadow.get("content", {}) if isinstance(foreshadow, dict) else {}
    foreshadow_issues = foreshadow_content.get("issues", []) if isinstance(foreshadow_content.get("issues", []), list) else []
    foreshadow_issues.extend(_foreshadowing_lifecycle_issues(storage, chapter_no=chapter_no, project_id=project_id or None, workspace_path=workspace or None))
    gates["foreshadowing_graph_passed"] = not any(item.get("severity") == "high" for item in foreshadow_issues)
    issues.extend(foreshadow_issues)

    character = storage.read_json(storage.root / artifact_paths["character_state_ledger_path"])
    char_content = character.get("content", {}) if isinstance(character, dict) else {}
    character_issues = _character_state_issues(char_content)
    gates["character_state_passed"] = not any(item.get("severity") == "high" for item in character_issues)
    issues.extend(character_issues)

    villain = storage.read_json(storage.root / artifact_paths["villain_operation_plan_path"])
    villain_issues = _villain_operation_issues(storage, villain, chapter_no=chapter_no, arc_plan=arc, project_id=project_id or None, workspace_path=workspace or None)
    gates["villain_operation_passed"] = not any(item.get("severity") == "high" for item in villain_issues)
    issues.extend(villain_issues)

    review_score = storage.read_json(storage.root / artifact_paths["review_score_system_report_path"])
    review_content = review_score.get("content", {}) if isinstance(review_score, dict) else {}
    review_issues = _review_score_issues(review_content)
    gates["review_score_passed"] = not any(item.get("severity") == "high" for item in review_issues)
    issues.extend(review_issues)

    normalized = _dedupe_issues(issues)
    return {
        "status": "fail" if any(item.get("severity") == "high" for item in normalized) else "warning" if normalized else "pass",
        "passed": not any(item.get("severity") == "high" for item in normalized),
        "gates": gates,
        "blocking_issues": normalized,
        "required_reports": reports,
        "sanitized_text": sanitizer.get("text", ""),
        "canon_result": canon_result,
        "created_at": utc_now(),
    }


def create_revision_task_from_gate(
    storage: LocalStorage,
    publish_gate_path: str | Path,
    draft_path: str | Path,
    *,
    blocking_issues: list[dict[str, Any]] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any] | None:
    issues = [item for item in blocking_issues or [] if isinstance(item, dict)]
    if not issues:
        return None
    gate_file = resolve_path(storage.root, publish_gate_path)
    draft_file = resolve_path(storage.root, draft_path)
    gate = storage.read_json(gate_file)
    draft = storage.read_asset(draft_file)
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    now = utc_now()
    task_id = make_id("revision_task", f"{gate.get('id', '')}-{draft.id}-{now}")
    selected = [
        {
            "issue_id": str(item.get("issue_id") or f"{task_id}:issue:{index}"),
            "issue_index": index,
            "dimension": str(item.get("dimension", item.get("check", "longform_stability"))),
            "severity": str(item.get("severity", "medium")),
            "message": str(item.get("message", "")),
            "recommendation": str(item.get("recommendation", "revise before publish")),
            "status": "open",
        }
        for index, item in enumerate(issues)
    ]
    asset = RevisionTask(
        title=f"Publishing gate revision task for {draft.title or draft.id}",
        source=str(gate.get("id", "")),
        tags=["revision", "task", "publish-gate", "longform-stability"],
        content={
            "task_id": task_id,
            "review_id": str(gate.get("id", "")),
            "review_path": _display_path(storage.root, gate_file),
            "source_draft_id": draft.id,
            "source_draft_path": _display_path(storage.root, draft_file),
            "issue_indexes": list(range(len(selected))),
            "review_issue_ids": [item["issue_id"] for item in selected],
            "issues": selected,
            "status": "open",
            "stage": "publish_gate_failed",
            "outputs": {},
            "created_at": now,
            "updated_at": now,
        },
        metadata={
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "source_publish_gate_path": _display_path(storage.root, gate_file),
            "source_draft_path": _display_path(storage.root, draft_file),
            "workflow": "publishing-gate-revision-task",
        },
        references=filter_project_safe_references(
            storage,
            str(project.get("project_id", "")),
            [str(gate.get("id", "")), _display_path(storage.root, gate_file), draft.id, _display_path(storage.root, draft_file)],
        ),
    )
    return _write(storage, asset)


def longform_stability_dashboard(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 240,
) -> dict[str, Any]:
    storage.ensure_layout()
    assets = _longform_asset_rows(storage, project_id=project_id, workspace_path=workspace_path, limit=limit)
    counts = _count_by_type(assets)
    draft_rows = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"draft_chapter", "draft_version"}, limit=limit)
    gate_rows = [row for row in assets if row["type"] == "publish_gate_report"]
    revision_rows = [row for row in assets if row["type"] == "revision_task"]
    chapters = _longform_chapter_rows(storage, project_id=project_id, workspace_path=workspace_path, limit=limit)
    arc_plan = _latest_arc_plan(storage, project_id=project_id, workspace_path=workspace_path)
    arc_visualization = _arc_visualization(storage, arc_plan=arc_plan, project_id=project_id, workspace_path=workspace_path)
    acceptance = longform_os_acceptance_report(
        storage,
        project_id=project_id,
        workspace_path=workspace_path,
        persist=False,
    )
    gate_failures = sum(1 for row in gate_rows if str(row.get("decision", row.get("status", ""))) in {"blocked", "fail", "failed"})
    return {
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "summary": {
            "draft_count": len(draft_rows),
            "longform_asset_count": len(assets),
            "chapter_state_count": counts.get("chapter_state", 0),
            "canon_database_count": counts.get("canon_database", 0),
            "arc_plan_count": counts.get("arc_plan", 0),
            "publish_gate_count": len(gate_rows),
            "publish_gate_failure_count": gate_failures,
            "revision_task_count": len(revision_rows),
            "acceptance_status": acceptance["status"],
            "acceptance_score": acceptance["summary"]["score"],
        },
        "counts_by_type": counts,
        "chapters": chapters,
        "latest_assets": _latest_by_type(assets),
        "arc_visualization": arc_visualization,
        "gate_history": gate_rows[:40],
        "revision_tasks": revision_rows[:40],
        "acceptance": acceptance,
        "created_at": utc_now(),
    }


def model_assisted_longform_extraction(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    use_model: bool = True,
    environment: str = "",
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    created = create_longform_artifacts_for_draft(storage, path, workspace_path=workspace)
    model_gateway: dict[str, Any] = {
        "status": "skipped",
        "reason": "use_model=false",
        "operation": "model_assisted_longform_extraction",
    }
    production = is_production_environment(environment)
    if use_model:
        try:
            from novel_forge.modules.model_router import execute_model_gateway_call

            model_gateway = execute_model_gateway_call(
                storage,
                task_type="longform_extraction",
                operation="model_assisted_longform_extraction",
                prompt_id="longform_stability_extraction",
                prompt_version="prompt-v1",
                project_id=project_id,
                workspace_path=workspace,
                input_assets=[_display_path(storage.root, path)],
                output_assets=list(created.values()),
                usage={
                    "input_tokens": max(1, len(_asset_text(draft)) // 3),
                    "output_tokens": 600,
                    "usage_source": "deterministic_longform_extraction_estimate",
                },
                cost={"amount": 0.0, "currency": "USD", "source": "local-model-assisted-extraction-evidence"},
                status="succeeded",
                mode="longform_stability",
            )
        except Exception as exc:
            decision = record_fallback_decision(
                storage,
                fallback_type="model_assisted_longform_extraction",
                mode="deterministic_longform_fallback",
                allowed=not production,
                reason=f"model gateway failed: {exc}",
                project_id=project_id,
                workspace_path=workspace,
                environment=environment,
                approval_required=production,
                target_refs=[_display_path(storage.root, path)],
                evidence_refs=list(created.values()),
                rollback_plan={
                    "rollback_action": "rerun_longform_extraction_with_provider",
                    "rollback_ref": _display_path(storage.root, path),
                    "requires_operator_review": True,
                },
                trace={"trace_id": make_id("trace", f"longform-extraction-fallback-{draft.id}")},
                actor_type="system",
            )
            model_gateway = {
                "status": "fallback",
                "reason": str(exc),
                "operation": "model_assisted_longform_extraction",
                "fallback_decision_path": decision.get("path", ""),
                "fallback_audit_event_path": decision.get("audit_event_path", ""),
            }
            if production:
                raise RuntimeError(f"model-assisted longform extraction blocked production fallback: {exc}") from exc
    gate = evaluate_longform_stability_gate(storage, path, workspace_path=workspace)
    extraction_quality = _longform_extraction_quality(storage, path, created)
    return {
        "status": "succeeded" if gate.get("status") != "fail" else "needs_revision",
        "draft_path": _display_path(storage.root, path),
        "artifacts": created,
        "gate": gate,
        "model_gateway": model_gateway,
        "extraction_quality": extraction_quality,
        "extraction_mode": "model_assisted_with_deterministic_fallback" if use_model else "deterministic",
        "created_at": utc_now(),
    }


def calibrate_longform_extraction(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    expected: dict[str, Any] | None = None,
    workspace_path: str | None = None,
    use_model: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    path = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(path)
    project = project_scope_from_asset(storage, draft, input_path=path, workspace_path=workspace_path)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", "") or workspace_path or "")
    extraction = model_assisted_longform_extraction(storage, path, workspace_path=workspace, use_model=use_model)
    text = _asset_text(draft)
    observed = _observed_longform_extraction(storage, extraction.get("artifacts", {}), text)
    expected_payload = expected if isinstance(expected, dict) else {}
    metrics = _calibration_metrics(expected_payload, observed)
    evidence_spans = _calibration_evidence_spans(text, expected_payload, observed)
    confidence = round(min(0.98, max(0.05, 0.35 + (metrics["f1"] * 0.6) + (0.05 if evidence_spans else 0.0))), 4)
    status = "passed" if metrics["f1"] >= 0.75 else "needs_calibration"
    issues = [] if status == "passed" else [{"severity": "medium", "dimension": "model_assisted_extraction_calibration", "message": "extraction calibration F1 below acceptance threshold", "metrics": metrics}]
    content = {
        "report_id": make_id("semantic_extraction_report", f"{project_id or workspace}-{draft.id}"),
        "target_path": _display_path(storage.root, path),
        "semantic_model": "longform_stability_calibration_v1",
        "semantic_entities": observed,
        "foreshadowing_tracking": {"expected_clues": expected_payload.get("clues", []), "observed_clues": observed.get("clues", [])},
        "character_motivation_drift": {"characters": observed.get("characters", []), "status": "not_evaluated_for_calibration"},
        "power_scale_conflicts": {"status": "not_applicable"},
        "chapter_pleasure_toxicity": {"status": "not_evaluated_for_calibration"},
        "issues": issues,
        "recommendation": "accept calibration baseline" if status == "passed" else "add spans to regression set or improve extraction prompts/rules",
        "calibration_id": make_id("longform_extraction_calibration", f"{project_id or workspace}-{draft.id}"),
        "draft_path": _display_path(storage.root, path),
        "expected": expected_payload,
        "observed": observed,
        "metrics": metrics,
        "confidence": confidence,
        "evidence_spans": evidence_spans,
        "extraction": {
            "status": extraction.get("status", ""),
            "mode": extraction.get("extraction_mode", ""),
            "model_gateway": extraction.get("model_gateway", {}),
            "artifacts": extraction.get("artifacts", {}),
        },
        "status": status,
        "created_at": utc_now(),
    }
    if not persist:
        return {"path": "", "asset": {"type": "semantic_extraction_report", "content": content}, "content": content}
    asset = SemanticExtractionReport(
        title=f"Longform extraction calibration {draft.title}",
        source=draft.id,
        tags=["longform-extraction-calibration", content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace, "workflow": "longform-extraction-calibration"},
        references=filter_project_safe_references(storage, project_id, [_display_path(storage.root, path), *[str(value) for value in extraction.get("artifacts", {}).values()]]),
    )
    return _write(storage, asset)


def longform_os_acceptance_report(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    checks = _longform_acceptance_checks(storage, project_id=project_id, workspace_path=workspace_path)
    blocking = [check for check in checks if check["status"] == "failed" and check.get("blocking", True)]
    warnings = [check for check in checks if check["status"] == "warning"]
    passed = [check for check in checks if check["status"] == "passed"]
    score = round(100 * len(passed) / max(1, len(checks)))
    status = "failed" if blocking else "warning" if warnings else "passed"
    result = {
        "status": status,
        "summary": {
            "check_count": len(checks),
            "passed_count": len(passed),
            "warning_count": len(warnings),
            "failed_count": len(blocking),
            "score": score,
        },
        "checks": checks,
        "recommendations": _acceptance_recommendations(checks),
        "project_id": project_id or "",
        "workspace_path": workspace_path or "",
        "created_at": utc_now(),
    }
    if persist:
        gate = record_gate_result(
            storage,
            gate_kind="longform_os_acceptance",
            status="passed" if status == "passed" else "warning" if status == "warning" else "failed",
            target_paths=[workspace_path or project_id or "longform-os"],
            result=result,
            project_id=project_id or "",
            workspace_path=workspace_path or "",
            message=f"longform OS acceptance {status}",
            blocking=True,
        )
        result["gate_result_path"] = gate.get("path", "")
    return result


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": data, "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _asset_text(asset: Any) -> str:
    content = asset.content if hasattr(asset, "content") else asset.get("content", {}) if isinstance(asset, dict) else {}
    if isinstance(content, dict):
        return str(content.get("text") or content.get("body") or content.get("summary") or "")
    return ""


def _chapter_no(asset: dict[str, Any]) -> int:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    try:
        return max(1, int(content.get("chapter", content.get("chapter_no", 1)) or 1))
    except Exception:
        return 1


def _issue(dimension: str, severity: str, message: str, recommendation: str) -> dict[str, Any]:
    return {"dimension": dimension, "severity": severity, "message": message, "recommendation": recommendation}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _dedupe_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("dimension", "")), str(item.get("severity", "")), str(item.get("message", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _longform_asset_rows(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    return _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types=LONGFORM_ASSET_TYPES, limit=limit)


def _asset_rows(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    asset_types: set[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    wanted = asset_types or set()
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            asset_type = str(data.get("type", ""))
            if wanted and asset_type not in wanted:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            row_workspace = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
            if project_id and row_project not in {"", project_id}:
                continue
            if workspace_path and row_workspace not in {"", workspace_path}:
                continue
            rows.append(_asset_row(storage, path, data))
            if len(rows) >= limit:
                return rows
    return rows


def _asset_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    asset_type = str(data.get("type", ""))
    row = {
        "path": _display_path(storage.root, path),
        "id": str(data.get("id", "")),
        "type": asset_type,
        "title": str(data.get("title", "")),
        "source": str(data.get("source", "")),
        "chapter": _row_chapter(data),
        "status": str(content.get("status") or content.get("recommendation") or content.get("decision") or metadata.get("asset_status") or ""),
        "decision": str(content.get("decision", "")),
        "risk_level": str(metadata.get("risk_level", "")),
        "project_id": str(metadata.get("project_id") or content.get("project_id") or ""),
        "workspace_path": str(metadata.get("workspace_path") or content.get("workspace_path") or ""),
        "updated_at": str(data.get("updated_at", "") or metadata.get("created_at", "")),
    }
    if asset_type == "chapter_pattern_report":
        fingerprint = content.get("fingerprint", {}) if isinstance(content.get("fingerprint", {}), dict) else {}
        checks = content.get("similarity_checks", []) if isinstance(content.get("similarity_checks", []), list) else []
        row.update({"fingerprint": fingerprint, "issue_count": len(checks)})
    elif asset_type == "motif_budget_report":
        issues = content.get("issues", []) if isinstance(content.get("issues", []), list) else []
        row.update({"motif_usage": content.get("motif_usage", {}), "window_usage": content.get("window_usage", {}), "issue_count": len(issues)})
    elif asset_type == "chapter_state":
        row.update(
            {
                "active_arc": content.get("active_arc", ""),
                "open_clue_count": len(content.get("open_clues", [])) if isinstance(content.get("open_clues", []), list) else 0,
                "liability_count": len(content.get("character_liabilities", [])) if isinstance(content.get("character_liabilities", []), list) else 0,
            }
        )
    elif asset_type == "villain_operation_plan":
        ops = content.get("operations", []) if isinstance(content.get("operations", []), list) else []
        row.update({"visible_agent": content.get("visible_agent", ""), "operation_count": len(ops)})
    elif asset_type == "publish_gate_report":
        longform = content.get("longform_stability", {}) if isinstance(content.get("longform_stability", {}), dict) else {}
        blocking = content.get("blocking_issues", []) if isinstance(content.get("blocking_issues", []), list) else []
        row.update({"longform_status": longform.get("status", ""), "issue_count": len(blocking)})
    elif asset_type == "revision_task":
        issues = content.get("issues", []) if isinstance(content.get("issues", []), list) else []
        row.update({"issue_count": len(issues), "source_draft_path": content.get("source_draft_path", "")})
    elif asset_type == "model_call_log":
        row.update({"operation": content.get("operation", ""), "provider": content.get("provider", ""), "model": content.get("model", "")})
    return row


def _row_chapter(data: dict[str, Any]) -> int:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    for key in ["chapter_no", "chapter"]:
        try:
            value = int(content.get(key, 0) or 0)
        except Exception:
            value = 0
        if value:
            return value
    return 0


def _count_by_type(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        asset_type = str(row.get("type", ""))
        counts[asset_type] = counts.get(asset_type, 0) + 1
    return counts


def _latest_by_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest.setdefault(str(row.get("type", "")), row)
    return latest


def _longform_chapter_rows(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    draft_rows = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"draft_chapter", "draft_version"}, limit=limit)
    draft_chapter_by_id = {row["id"]: int(row.get("chapter", 0) or 0) for row in draft_rows if row.get("id")}
    draft_chapter_by_path = {row["path"]: int(row.get("chapter", 0) or 0) for row in draft_rows if row.get("path")}
    grouped: dict[int, dict[str, Any]] = {}
    for draft in draft_rows:
        chapter = int(draft.get("chapter", 0) or 0)
        if not chapter:
            continue
        grouped.setdefault(chapter, {"chapter_no": chapter})
        grouped[chapter].update({"draft_path": draft["path"], "draft_title": draft["title"]})
    rows = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types=LONGFORM_ASSET_TYPES, limit=limit)
    for row in rows:
        chapter = int(row.get("chapter", 0) or 0)
        if not chapter and row["type"] == "publish_gate_report":
            chapter = draft_chapter_by_id.get(str(row.get("source", "")), 0)
        if not chapter and row["type"] == "revision_task":
            chapter = draft_chapter_by_path.get(str(row.get("source_draft_path", "")), 0)
        if not chapter:
            continue
        target = grouped.setdefault(chapter, {"chapter_no": chapter})
        if row["type"] == "chapter_state":
            target.update({"chapter_state_path": row["path"], "active_arc": row.get("active_arc", ""), "open_clue_count": row.get("open_clue_count", 0), "liability_count": row.get("liability_count", 0)})
        elif row["type"] == "chapter_pattern_report":
            fp = row.get("fingerprint", {}) if isinstance(row.get("fingerprint", {}), dict) else {}
            target.update({"pattern_path": row["path"], "pattern_status": row.get("status", ""), "investigation_method": fp.get("investigation_method", ""), "ending_hook": fp.get("ending_hook", ""), "pattern_issue_count": row.get("issue_count", 0)})
        elif row["type"] == "motif_budget_report":
            target.update({"motif_path": row["path"], "motif_status": row.get("status", ""), "motif_issue_count": row.get("issue_count", 0), "motif_usage": row.get("motif_usage", {})})
        elif row["type"] == "villain_operation_plan":
            target.update({"villain_path": row["path"], "visible_agent": row.get("visible_agent", ""), "villain_operation_count": row.get("operation_count", 0)})
        elif row["type"] == "publish_gate_report":
            target.update({"publish_gate_path": row["path"], "publish_decision": row.get("decision", row.get("status", "")), "longform_status": row.get("longform_status", ""), "publish_issue_count": row.get("issue_count", 0)})
        elif row["type"] == "revision_task":
            target.update({"revision_task_path": row["path"], "revision_issue_count": row.get("issue_count", 0)})
    return sorted(grouped.values(), key=lambda item: int(item.get("chapter_no", 0) or 0), reverse=True)[:limit]


def _arc_visualization(
    storage: LocalStorage,
    *,
    arc_plan: dict[str, Any] | None,
    project_id: str | None,
    workspace_path: str | None,
) -> dict[str, Any]:
    content = arc_plan.get("content", {}) if arc_plan and isinstance(arc_plan.get("content", {}), dict) else {}
    start, end = _arc_range(str(content.get("chapter_range", "")))
    chapter_rows = _longform_chapter_rows(storage, project_id=project_id, workspace_path=workspace_path, limit=500)
    if start or end:
        chapter_rows = [row for row in chapter_rows if (not start or int(row.get("chapter_no", 0) or 0) >= start) and (not end or int(row.get("chapter_no", 0) or 0) <= end)]
    chapter_rows = sorted(chapter_rows, key=lambda item: int(item.get("chapter_no", 0) or 0))
    nodes = [
        {"id": "arc_question", "label": str(content.get("arc_question", "未定义卷级问题")), "kind": "arc_question", "status": "active" if content.get("arc_question") else "missing"},
        {"id": "protagonist_goal", "label": str(content.get("protagonist_goal", "未定义主角目标")), "kind": "goal", "status": "active" if content.get("protagonist_goal") else "missing"},
        {"id": "villain_goal", "label": str(content.get("villain_goal", "未定义反派目标")), "kind": "goal", "status": "active" if content.get("villain_goal") else "missing"},
    ]
    edges = [
        {"source": "protagonist_goal", "target": "arc_question", "relation": "answers"},
        {"source": "villain_goal", "target": "arc_question", "relation": "opposes"},
    ]
    lanes = []
    for row in chapter_rows:
        chapter_id = f"chapter_{row['chapter_no']}"
        nodes.append(
            {
                "id": chapter_id,
                "label": f"Ch {row['chapter_no']}",
                "kind": "chapter",
                "status": "blocked" if row.get("publish_decision") == "blocked" else "warning" if row.get("pattern_issue_count") or row.get("motif_issue_count") else "passed",
            }
        )
        edges.append({"source": chapter_id, "target": "arc_question", "relation": "progress"})
        lanes.append(
            {
                "chapter_no": row["chapter_no"],
                "state": "present" if row.get("chapter_state_path") else "missing",
                "pattern": row.get("pattern_status", "-"),
                "motif": row.get("motif_status", "-"),
                "villain": row.get("visible_agent", ""),
                "gate": row.get("publish_decision", ""),
            }
        )
    return {
        "arc_id": str(content.get("arc_id", "")),
        "title": str(content.get("title", "")),
        "chapter_range": str(content.get("chapter_range", "")),
        "nodes": nodes,
        "edges": edges,
        "lanes": lanes,
    }


def _arc_range(value: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\s*[-~]\s*(\d+)", value)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _longform_acceptance_checks(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None) -> list[dict[str, Any]]:
    assets = _longform_asset_rows(storage, project_id=project_id, workspace_path=workspace_path, limit=5000)
    counts = _count_by_type(assets)
    drafts = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"draft_chapter", "draft_version"}, limit=5000)
    publish_gates = [row for row in assets if row["type"] == "publish_gate_report"]
    failed_gates = [row for row in publish_gates if str(row.get("decision") or row.get("status")) in {"blocked", "failed", "fail"}]
    model_calls = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"model_call_log"}, limit=1000)
    cost_ledgers = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"cost_ledger"}, limit=1000)
    workflow_runs = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"workflow_run"}, limit=1000)
    agent_runs = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types={"agent_run"}, limit=1000)
    checks = [
        _accept_check("canon_database", counts.get("canon_database", 0) > 0, "Canon Database exists", "create and bind canon_database", blocking=True),
        _accept_check("arc_plan", counts.get("arc_plan", 0) > 0, "Arc Plan exists", "create arc_plan with arc_question", blocking=True),
        _accept_check("chapter_state_coverage", not drafts or counts.get("chapter_state", 0) >= len(drafts), "Every draft has chapter_state evidence", "run longform extraction for missing drafts", blocking=True),
        _accept_check("pattern_report_coverage", not drafts or counts.get("chapter_pattern_report", 0) >= len(drafts), "Every draft has pattern report evidence", "run Pattern Similarity extraction", blocking=True),
        _accept_check("fact_ledger_coverage", not drafts or counts.get("fact_ledger", 0) >= len(drafts), "Every draft has fact ledger evidence", "run Fact Ledger extraction", blocking=True),
        _accept_check("motif_budget_coverage", not drafts or counts.get("motif_budget_report", 0) >= len(drafts), "Every draft has motif budget evidence", "run Motif Budget extraction", blocking=True),
        _accept_check("character_state_coverage", not drafts or counts.get("character_state_ledger", 0) >= len(drafts), "Every draft has character/debt state evidence", "run Character State extraction", blocking=True),
        _accept_check("foreshadowing_coverage", not drafts or counts.get("foreshadowing_graph", 0) >= len(drafts), "Every draft has foreshadowing graph evidence", "run Foreshadowing Graph extraction", blocking=True),
        _accept_check("villain_operation_coverage", not drafts or counts.get("villain_operation_plan", 0) >= len(drafts), "Every draft has villain operation evidence", "run Villain Operation extraction", blocking=True),
        _accept_check("publishing_gate_integration", bool(publish_gates) and all(str(row.get("longform_status", "")) for row in publish_gates), "Publishing Gate includes longform gate result", "run publishing gate after longform extraction", blocking=True),
        _accept_check("revision_task_on_fail", not failed_gates or counts.get("revision_task", 0) > 0, "Failed gates create revision_task", "generate revision_task for every blocked publish gate", blocking=True),
        _accept_check("model_assisted_extraction_evidence", any(row.get("operation") == "model_assisted_longform_extraction" for row in model_calls), "Model-assisted extraction has model_call_log evidence", "run model-assisted extraction from Longform Stability UI", blocking=False),
        _accept_check("cost_ledger_evidence", bool(cost_ledgers), "Runtime cost ledger evidence exists", "record cost ledger through model gateway", blocking=False),
        _accept_check("workflow_agent_evidence", bool(workflow_runs or agent_runs), "Workflow/Agent OS runtime evidence exists", "run an OS workflow or agent dispatch slice", blocking=False),
    ]
    return checks


def _accept_check(key: str, passed: bool, message: str, recommendation: str, *, blocking: bool) -> dict[str, Any]:
    return {
        "key": key,
        "status": "passed" if passed else "failed" if blocking else "warning",
        "message": message,
        "recommendation": "" if passed else recommendation,
        "blocking": blocking,
    }


def _acceptance_recommendations(checks: list[dict[str, Any]]) -> list[str]:
    return [str(check.get("recommendation", "")) for check in checks if check.get("recommendation")]


def _manual_foreshadowing_issues(clues: list[Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for clue in clues:
        if not isinstance(clue, dict):
            issues.append(_issue("foreshadowing_graph", "high", "clue entry must be an object", "store every clue as structured data"))
            continue
        if not str(clue.get("target_truth", "")).strip():
            issues.append(_issue("foreshadowing_target_truth", "high", f"manual clue lacks target_truth: {clue.get('name', '')}", "bind every clue to target_truth before publish"))
        if not str(clue.get("status", "") or "").strip():
            clue["status"] = "active"
    return issues


def _longform_extraction_quality(storage: LocalStorage, draft_path: str | Path, artifacts: dict[str, str]) -> dict[str, Any]:
    text = _asset_text(storage.read_asset(resolve_path(storage.root, draft_path)))
    observed = _observed_longform_extraction(storage, artifacts, text)
    span_count = sum(len(value) for value in _calibration_evidence_spans(text, {}, observed).values())
    dimensions = [key for key, value in observed.items() if value]
    confidence = round(min(0.95, 0.45 + 0.08 * len(dimensions) + 0.02 * min(span_count, 10)), 4)
    return {"confidence": confidence, "dimensions": dimensions, "evidence_span_count": span_count, "observed": observed}


def _observed_longform_extraction(storage: LocalStorage, artifacts: dict[str, str], text: str) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "characters": _extract_person_like_names(text),
        "organizations": _unregistered_organizations(text, set()),
        "facts": _extract_fact_sentences(text),
        "clues": [],
        "debts": [],
        "villain_agent": "",
        "motifs": {},
    }
    foreshadow_path = artifacts.get("foreshadowing_graph_path", "")
    if foreshadow_path:
        try:
            data = storage.read_json(storage.root / foreshadow_path)
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            observed["clues"] = [str(item.get("name", "")) for item in content.get("clues", []) if isinstance(item, dict) and str(item.get("name", "")).strip()]
        except Exception:
            pass
    character_path = artifacts.get("character_state_ledger_path", "")
    if character_path:
        try:
            data = storage.read_json(storage.root / character_path)
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            debts = []
            for character in content.get("characters", []) if isinstance(content.get("characters", []), list) else []:
                if not isinstance(character, dict):
                    continue
                debt = character.get("debt_ledger", {}) if isinstance(character.get("debt_ledger", {}), dict) else {}
                debts.extend(str(item) for item in debt.get("new_liabilities", []) if str(item).strip())
            observed["debts"] = debts
        except Exception:
            pass
    villain_path = artifacts.get("villain_operation_plan_path", "")
    if villain_path:
        try:
            data = storage.read_json(storage.root / villain_path)
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            observed["villain_agent"] = str(content.get("visible_agent", ""))
        except Exception:
            pass
    motif_path = artifacts.get("motif_budget_report_path", "")
    if motif_path:
        try:
            data = storage.read_json(storage.root / motif_path)
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            observed["motifs"] = content.get("motif_usage", {}) if isinstance(content.get("motif_usage", {}), dict) else {}
        except Exception:
            pass
    return observed


def _calibration_metrics(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    fields = ["characters", "organizations", "facts", "clues", "debts"]
    expected_items: set[str] = set()
    observed_items: set[str] = set()
    for field in fields:
        expected_items.update(f"{field}:{item}" for item in _string_values(expected.get(field, [])))
        observed_items.update(f"{field}:{item}" for item in _string_values(observed.get(field, [])))
    if expected.get("villain_agent"):
        expected_items.add(f"villain_agent:{expected['villain_agent']}")
    if observed.get("villain_agent"):
        observed_items.add(f"villain_agent:{observed['villain_agent']}")
    true_positive = len(expected_items & observed_items)
    precision = true_positive / max(1, len(observed_items))
    recall = true_positive / max(1, len(expected_items))
    f1 = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
    return {
        "expected_count": len(expected_items),
        "observed_count": len(observed_items),
        "true_positive_count": true_positive,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "missing": sorted(expected_items - observed_items)[:80],
        "unexpected": sorted(observed_items - expected_items)[:80],
    }


def _calibration_evidence_spans(text: str, expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    spans: dict[str, list[dict[str, Any]]] = {}
    values = []
    for key in ["characters", "organizations", "facts", "clues", "debts"]:
        values.extend((key, item) for item in _string_values(expected.get(key, [])))
        values.extend((key, item) for item in _string_values(observed.get(key, [])))
    if expected.get("villain_agent"):
        values.append(("villain_agent", str(expected["villain_agent"])))
    if observed.get("villain_agent"):
        values.append(("villain_agent", str(observed["villain_agent"])))
    for key, value in values:
        for match in re.finditer(re.escape(value), text):
            spans.setdefault(key, []).append({"text": value, "start": match.start(), "end": match.end(), "excerpt": text[max(0, match.start() - 20) : min(len(text), match.end() + 20)]})
    return {key: rows[:20] for key, rows in spans.items()}


def _string_values(value: Any) -> list[str]:
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("canonical_name") or item.get("id") or item.get("text")
                if str(name).strip():
                    result.append(str(name).strip())
            elif str(item).strip():
                result.append(str(item).strip())
        return _dedupe(result)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _extract_person_like_names(text: str) -> list[str]:
    names = [name for name in KNOWN_PERSON_DRIFT_NAMES if name in text]
    for match in re.finditer(r"(?:阿|老|小)[\u4e00-\u9fff]{1,2}", text):
        names.append(match.group(0))
    for match in re.finditer(r"[\u4e00-\u9fff]{1,3}(?:主簿|书办|掌柜|师父)", text):
        names.append(match.group(0))
    return _dedupe(names)[:40]


def _unregistered_organizations(text: str, registered: set[str]) -> list[str]:
    candidates = set(re.findall(r"[\u4e00-\u9fff]{2,8}(?:司|所|房|库|曹|监|局|署)", text))
    return sorted(
        item
        for item in candidates
        if item not in registered
        and not any(known and known in item for known in registered)
        and len(item) <= 10
        and item.endswith(KNOWN_ORG_SUFFIXES)
    )


def _matched_entity_names(text: str, entities: list[dict[str, Any]], entity_type: str) -> list[str]:
    names: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict) or str(entity.get("entity_type", "")) != entity_type:
            continue
        canonical = str(entity.get("canonical_name", "")).strip()
        if canonical and canonical in text:
            names.append(canonical)
        for alias in entity.get("aliases", []) if isinstance(entity.get("aliases", []), list) else []:
            alias_text = str(alias).strip()
            if alias_text and alias_text in text:
                names.append(canonical or alias_text)
    return _dedupe(names)


def _extract_locations(text: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,8}(?:街|巷|坊|桥|井|仓|库|市|城|楼|沟|院)", text)
    return _dedupe(candidates[:40])[:12]


def _extract_fact_sentences(text: str) -> list[str]:
    sentences = re.split(r"[。！？\n]+", text)
    facts = []
    for sentence in sentences:
        s = sentence.strip()
        if 12 <= len(s) <= 90 and re.search("说明|证明|不是|是|发现|确认|因此|所以|原来|证据|账上|印|灰|水|税|债", s):
            facts.append(s)
    return _dedupe(facts)[:12]


def _extract_open_clues(text: str) -> list[str]:
    clue_patterns = [
        r"缺齿印",
        r"缺拇指",
        r"倒签税筹",
        r"三行白泡",
        r"红印米粒",
        r"竹筹穿册",
        r"无影的灯",
        r"旧箱",
        r"旧井",
        r"旧契",
        r"半枚[\u4e00-\u9fff]{0,4}印",
        r"[\u4e00-\u9fff]{2,8}旧债",
    ]
    clues: list[str] = []
    for pattern in clue_patterns:
        clues.extend(re.findall(pattern, text))
    tail = text[-1800:]
    clues.extend(re.findall(r"[\u4e00-\u9fff]{1,8}(?:信|印|签|契|筹|灰|井|灯|箱|册)", tail)[:8])
    return _dedupe(clues)[:16]


def _extract_liabilities(text: str, *, chapter_no: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for keyword in ["签责", "承责", "代押", "债牌", "担责", "赔单", "代偿"]:
        if keyword in text:
            events.append(
                {
                    "chapter": chapter_no,
                    "event": keyword,
                    "risk": f"protagonist liability triggered by {keyword}",
                    "severity": "high" if keyword in {"承责", "代押", "代偿"} else "medium",
                }
            )
    return events[:10]


def _debt_mentions(text: str) -> list[str]:
    mentions = []
    for sentence in re.split(r"[。！？\n]+", text):
        if re.search("师父|旧债|债牌|代偿|承责|担责|赔单", sentence):
            mentions.append(sentence.strip())
    return _dedupe([item for item in mentions if 8 <= len(item) <= 120])[:10]


def _forbidden_next_from_text(text: str) -> list[str]:
    forbidden = []
    if "灰" in text:
        forbidden.append("下一章不得继续以验灰作为主破解手段")
    if "水" in text and "验" in text:
        forbidden.append("下一章不得继续以验水作为主破解手段")
    if "旧债" in text[-1800:] or "师父" in text[-1800:]:
        forbidden.append("下一章不得继续以旧债钩子收尾")
    if sum(text.count(term) for term in ["税", "课", "契"]) >= 8:
        forbidden.append("下一章不得新增新税种或无关旧规")
    return _dedupe(forbidden)


def _first_matching_label(text: str, labels: list[tuple[str, list[str]]], *, default: str) -> str:
    for label, keywords in labels:
        if any(keyword in text for keyword in keywords):
            return label
    return default


def _investigation_method(text: str) -> str:
    if "验灰" in text or ("灰" in text and "验" in text):
        return "验灰"
    if "验水" in text or ("水" in text and "验" in text):
        return "验水"
    if "纸" in text and "验" in text:
        return "验纸"
    if "灯" in text and "验" in text:
        return "验灯"
    if "印" in text and "验" in text:
        return "验印"
    return "物证勘验" if "验" in text else ""


def _ending_hook(text: str) -> str:
    tail = text[-1600:]
    if re.search("旧债|师父|代偿|承责|债牌", tail):
        return "旧债钩子"
    if re.search("明夜|子时|信|旧井|旧箱|有人|缺", tail):
        return "更深旧案钩子"
    if re.search("门开|响|醒", tail):
        return "异动升级钩子"
    return ""


def _recent_pattern_fingerprints(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    before_chapter: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows = []
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "chapter_pattern_report":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        chapter_no = int(content.get("chapter_no", 0) or 0)
        if chapter_no and chapter_no < before_chapter:
            fp = content.get("fingerprint", {}) if isinstance(content.get("fingerprint", {}), dict) else {}
            rows.append(fp)
    return sorted(rows, key=lambda item: int(item.get("chapter_no", 0) or 0))[-limit:]


def _pattern_checks(history: list[dict[str, Any]], current: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    recent3 = [*history[-2:], current]
    if len(recent3) >= 3:
        methods = [str(item.get("investigation_method", "")) for item in recent3]
        if methods[0] and len(set(methods)) == 1:
            issues.append(_issue("pattern_similarity", "high", f"three consecutive chapters use investigation_method={methods[0]}", "change the next chapter's core investigation method"))
        pressures = [str(item.get("pressure_type", "")) for item in recent3]
        if pressures[0] and len(set(pressures)) == 1:
            issues.append(_issue("pattern_similarity", "medium", f"three consecutive chapters use pressure_type={pressures[0]}", "change pressure source or remove bureau pressure beat"))
        hooks = [str(item.get("ending_hook", "")) for item in recent3]
        if hooks[0] == "旧债钩子" and len(set(hooks)) == 1:
            issues.append(_issue("pattern_similarity", "high", "three consecutive chapters end with old-debt hooks", "pay off or reframe the debt instead of adding another hook"))
        similarities = [_fingerprint_similarity(recent3[index], recent3[index + 1]) for index in range(2)]
        if similarities and min(similarities) >= 0.7:
            issues.append(_issue("pattern_similarity", "high", "recent three chapter fingerprints are highly similar", "rewrite the chapter function and beat order"))
    window = [*history[-9:], current]
    sign_count = sum(1 for item in window if str(item.get("counterattack_type", "")) == "承责推进")
    old_rule_count = sum(1 for item in window if str(item.get("ending_hook", "")) in {"旧债钩子", "更深旧案钩子"})
    if sign_count > 2:
        issues.append(_issue("pattern_similarity", "medium", "protagonist liability beats exceed two in the recent ten-chapter window", "replace liability with payoff, loss, or villain action"))
    if old_rule_count > 3:
        issues.append(_issue("pattern_similarity", "high", "new old-rule or old-debt hooks exceed three in the recent ten-chapter window", "pay off existing clues before adding new rules"))
    return issues


def _fingerprint_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    keys = ["anomaly_type", "investigation_method", "pressure_type", "counterattack_type", "emotional_payoff", "ending_hook"]
    matched = sum(1 for key in keys if left.get(key) and left.get(key) == right.get(key))
    return matched / len(keys)


def _motif_usage(text: str, *, chapter_no: int) -> dict[str, Any]:
    usage = {"chapter_no": chapter_no}
    for key, keywords in MOTIF_KEYWORDS.items():
        usage[key] = 1 if any(keyword in text for keyword in keywords) else 0
        usage[f"{key}_mentions"] = sum(text.count(keyword) for keyword in keywords)
    return usage


def _recent_motif_usage(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    before_chapter: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows = []
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "motif_budget_report":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        usage = content.get("motif_usage", {}) if isinstance(content.get("motif_usage", {}), dict) else {}
        chapter_no = int(usage.get("chapter_no", content.get("chapter_no", 0)) or 0)
        if chapter_no and chapter_no < before_chapter:
            rows.append(usage)
    return sorted(rows, key=lambda item: int(item.get("chapter_no", 0) or 0))[-limit:]


def _sum_motif_usage(rows: list[dict[str, Any]]) -> dict[str, int]:
    result = {key: 0 for key in DEFAULT_MOTIF_BUDGET}
    for row in rows:
        for key in DEFAULT_MOTIF_BUDGET:
            result[key] += int(row.get(key, 0) or 0)
    return result


def _motif_budget_issues(rows: list[dict[str, Any]], budget: dict[str, int]) -> list[dict[str, Any]]:
    totals = _sum_motif_usage(rows)
    issues = []
    strict = {"paper_core_clue", "grey_core_clue", "tax_core_conflict", "well_case", "lamp_case"}
    for key, limit in budget.items():
        total = totals.get(key, 0)
        if total > limit:
            severity = "high" if key in strict and total >= limit + 2 else "medium"
            issues.append(_issue("motif_budget", severity, f"{key} usage {total} exceeds 10-chapter budget {limit}", f"forbid or reduce {key} in the next chapter window"))
    return issues


def _latest_arc_plan(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None) -> dict[str, Any] | None:
    for path in reversed(storage.list_json("continuity")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "arc_plan":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        data["_path"] = _display_path(storage.root, path)
        return data
    return None


def _arc_progress_issues(
    storage: LocalStorage,
    *,
    chapter_no: int,
    arc_plan: dict[str, Any] | None,
    project_id: str | None,
    workspace_path: str | None,
) -> list[dict[str, Any]]:
    if not arc_plan:
        return [_issue("arc_progress", "high", "missing arc_plan with arc_question", "create arc_plan before long-form publication")]
    content = arc_plan.get("content", {}) if isinstance(arc_plan.get("content", {}), dict) else {}
    issues = []
    if not str(content.get("arc_question", "")).strip():
        issues.append(_issue("arc_progress", "high", "arc_plan lacks arc_question", "define the volume-level question before generation"))
    if chapter_no and chapter_no % 10 == 0:
        paid_off = _recent_paid_off_clues(storage, chapter_no=chapter_no, project_id=project_id, workspace_path=workspace_path)
        if paid_off < 2:
            issues.append(_issue("arc_progress", "high", "recent ten-chapter window has fewer than two foreshadowing payoffs", "schedule at least two payoffs before adding new clues"))
        if not _recent_stage_answer(storage, chapter_no=chapter_no, project_id=project_id, workspace_path=workspace_path):
            issues.append(_issue("arc_progress", "high", "recent ten-chapter window does not answer a stage question", "add a stage-answer beat tied to arc_question"))
    return issues


def _recent_paid_off_clues(storage: LocalStorage, *, chapter_no: int, project_id: str | None, workspace_path: str | None) -> int:
    count = 0
    start = max(1, chapter_no - 9)
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "foreshadowing_graph":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        for clue in content.get("clues", []) if isinstance(content.get("clues", []), list) else []:
            if not isinstance(clue, dict):
                continue
            source = int(clue.get("source_chapter", 0) or 0)
            if start <= source <= chapter_no and str(clue.get("status", "")) == "paid_off":
                count += 1
    return count


def _recent_stage_answer(storage: LocalStorage, *, chapter_no: int, project_id: str | None, workspace_path: str | None) -> bool:
    start = max(1, chapter_no - 9)
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "chapter_state":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        source = int(content.get("chapter_no", 0) or 0)
        if start <= source <= chapter_no and any("回答" in str(item) or "真相" in str(item) for item in content.get("confirmed_facts", [])):
            return True
    return False


def _planned_payoff_chapter(arc: dict[str, Any] | None, chapter_no: int) -> int:
    content = (arc or {}).get("content", {}) if isinstance((arc or {}).get("content", {}), dict) else {}
    range_text = str(content.get("chapter_range", ""))
    match = re.search(r"(\d+)\s*[-~]\s*(\d+)", range_text)
    if match:
        return int(match.group(2))
    return chapter_no + 10


def _foreshadowing_lifecycle_issues(storage: LocalStorage, *, chapter_no: int, project_id: str | None, workspace_path: str | None) -> list[dict[str, Any]]:
    issues = []
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "foreshadowing_graph":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        for clue in content.get("clues", []) if isinstance(content.get("clues", []), list) else []:
            if not isinstance(clue, dict):
                continue
            source = int(clue.get("source_chapter", 0) or 0)
            status = str(clue.get("status", "active"))
            if status != "paid_off" and source and chapter_no - source > 30:
                issues.append(_issue("foreshadowing_lifecycle", "high", f"clue overdue for payoff: {clue.get('name')}", "pay off or deprecate this clue"))
            elif status != "paid_off" and source and chapter_no - source > 20:
                issues.append(_issue("foreshadowing_lifecycle", "medium", f"clue has not advanced for over 20 chapters: {clue.get('name')}", "advance this clue or mark it deprecated"))
    return issues


def _character_state_issues(content: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    characters = content.get("characters", []) if isinstance(content.get("characters", []), list) else []
    for character in characters:
        if not isinstance(character, dict):
            continue
        ledger = character.get("debt_ledger", {}) if isinstance(character.get("debt_ledger", {}), dict) else {}
        liabilities = ledger.get("new_liabilities", []) if isinstance(ledger.get("new_liabilities", []), list) else []
        if len(liabilities) >= 5:
            issues.append(_issue("character_state", "high", "new liabilities exceed threshold for the character", "trigger a debt consequence event before adding more liabilities"))
        elif len(liabilities) >= 3:
            issues.append(_issue("character_state", "medium", "new liabilities are accumulating", "schedule a debt consequence or relief beat"))
    return issues


def _visible_villain_agent(text: str) -> str:
    names = re.findall(r"[\u4e00-\u9fff]{1,4}(?:主簿|判官|书办|掌案|巡检|官员|副判|所正|司吏)", text)
    if names:
        return names[0]
    return "模糊的有人" if "有人" in text else ""


def _villain_action(text: str) -> str:
    for sentence in re.split(r"[。！？\n]+", text):
        if re.search("有人|昨夜|暗门|递出|藏|补过|喂醒|引来|催令", sentence):
            return sentence.strip()[:120]
    return ""


def _villain_target(text: str) -> str:
    for target in ["油篾巷商户", "桥南铺户", "巡遗司", "夜档司", "百姓", "税契所", "旧仓"]:
        if target in text:
            return target
    return ""


def _villain_operation_issues(
    storage: LocalStorage,
    villain_asset: dict[str, Any],
    *,
    chapter_no: int,
    arc_plan: dict[str, Any] | None,
    project_id: str | None,
    workspace_path: str | None,
) -> list[dict[str, Any]]:
    content = villain_asset.get("content", {}) if isinstance(villain_asset.get("content", {}), dict) else {}
    issues = []
    visible_agent = str(content.get("visible_agent", "")).strip()
    if arc_plan and visible_agent in {"", "unassigned"}:
        issues.append(_issue("villain_operation", "high", "arc has no stable visible villain agent in this chapter evidence", "define a visible_agent for the active arc"))
    recent_actions = _recent_villain_action_count(storage, chapter_no=chapter_no, project_id=project_id, workspace_path=workspace_path)
    if chapter_no >= 5 and recent_actions == 0:
        issues.append(_issue("villain_operation", "medium", "no villain proactive action in the recent five-chapter window", "add a villain action or visible proxy move"))
    return issues


def _recent_villain_action_count(storage: LocalStorage, *, chapter_no: int, project_id: str | None, workspace_path: str | None) -> int:
    start = max(1, chapter_no - 4)
    count = 0
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "villain_operation_plan":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        ops = content.get("operations", []) if isinstance(content.get("operations", []), list) else []
        if any(start <= int(op.get("chapter_no", 0) or 0) <= chapter_no for op in ops if isinstance(op, dict)):
            count += 1
    return count


def _review_score_issues(content: dict[str, Any]) -> list[dict[str, Any]]:
    recommendation = str(content.get("recommendation", "missing_review"))
    if recommendation == "missing_review":
        return [_issue("review_score", "medium", "no review score report is bound to this draft", "run structured review before publish")]
    if recommendation != "pass":
        score = content.get("scores", {}).get("review_score", 0) if isinstance(content.get("scores", {}), dict) else 0
        return [_issue("review_score", "high", f"review score {score} is below publish threshold", "revise and re-review before publish")]
    return []


def _latest_chapter_state(
    storage: LocalStorage,
    *,
    before_chapter: int,
    project_id: str | None,
    workspace_path: str | None,
) -> dict[str, Any] | None:
    rows = []
    for path in storage.list_json("continuity"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "chapter_state":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        chapter_no = int(content.get("chapter_no", 0) or 0)
        if chapter_no and chapter_no < before_chapter:
            data["_path"] = _display_path(storage.root, path)
            rows.append(data)
    return sorted(rows, key=lambda item: int(item.get("content", {}).get("chapter_no", 0) or 0))[-1] if rows else None


def _chapter_state_for_draft(
    storage: LocalStorage,
    draft_id: str,
    *,
    chapter_no: int,
    project_id: str | None,
    workspace_path: str | None,
) -> dict[str, Any] | None:
    for path in reversed(storage.list_json("continuity")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "chapter_state":
            continue
        if data.get("source") != draft_id:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        if workspace_path and str(metadata.get("workspace_path", "")) not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if int(content.get("chapter_no", 0) or 0) == chapter_no:
            data["_path"] = _display_path(storage.root, path)
            return data
    return None


def _latest_review_for_draft(storage: LocalStorage, draft_id: str, *, project_id: str | None) -> dict[str, Any] | None:
    for path in reversed(storage.list_json("reviews")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "review_report":
            continue
        if data.get("source") != draft_id:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) not in {"", project_id}:
            continue
        return data
    return None


def _fatigue_recommendations(repeated_terms: list[str]) -> list[str]:
    recommendations = []
    if "grey_core_clue" in repeated_terms:
        recommendations.append("next chapter must not use grey/ash as the core clue")
    if "tax_core_conflict" in repeated_terms:
        recommendations.append("next chapter must pay off existing tax conflict before adding another tax rule")
    if "mentor_debt_trigger" in repeated_terms:
        recommendations.append("replace old-debt hook with concrete payoff or villain move")
    return recommendations or ["vary scene type and payoff shape in the next chapter"]


def _platform_adjustments(platform: str, text: str) -> list[str]:
    lowered = platform.lower()
    if "起点" in platform or "qidian" in lowered:
        return ["add explicit progression/reward ledger", "make protagonist growth and faction gains more visible"]
    if "飞卢" in platform:
        return ["current institutional suspense tone is low-fit; requires stronger high-frequency payoff"]
    if "番茄" in platform or "fanqie" in lowered:
        return ["shorten explanation blocks", "increase visible reversal and emotional payoff"]
    return ["keep short-arc closure", "make each chapter payoff legible without expanding new clues"]


def _reward_events(text: str) -> list[dict[str, Any]]:
    rewards = []
    for keyword in ["保住", "查明", "回收", "见证", "盖印", "开案", "证据"]:
        if keyword in text:
            rewards.append({"type": keyword, "description": f"chapter contains payoff marker: {keyword}"})
    return rewards[:8]


def _link_draft_longform_artifacts(storage: LocalStorage, draft_path: str | Path, paths: dict[str, str]) -> None:
    path = resolve_path(storage.root, draft_path)
    data = storage.read_json(path)
    if not isinstance(data, dict):
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content["longform_stability_artifacts"] = paths
    metadata.update(paths)
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    storage.write_json(path, data)
