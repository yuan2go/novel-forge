from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import AntagonistPressureReport, ProtagonistCharmReport, RevisionTask, validate_common_fields
from novel_forge.storage.local import LocalStorage


AGENCY_MARKERS = ["决定", "选择", "拒绝", "查明", "出手", "逼", "赌", "质问", "保住", "证明", "承担", "抬头", "塞", "听见", "decides", "chooses", "forces", "refuses"]
CHARM_MARKERS = ["保护", "救", "承责", "担责", "保住", "破解", "查明", "证明", "代价", "不退", "competent", "protects"]
PRESSURE_MARKERS = ["官署", "封存", "问责", "威胁", "追", "逼近", "有人", "敌", "反派", "黑手", "杀", "扣押", "threat", "villain", "enemy"]
COST_MARKERS = ["代价", "失去", "承责", "担责", "旧债", "师父", "问责", "扣押", "loss", "cost"]


def create_character_pressure_reports(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    character_state_ledger_path: str | Path | None = None,
    villain_operation_plan_path: str | Path | None = None,
    workspace_path: str | None = None,
    persist_issues: bool = True,
) -> dict[str, Any]:
    draft_file = resolve_path(storage.root, draft_path)
    draft = storage.read_asset(draft_file)
    draft_content = draft.content if isinstance(draft.content, dict) else {}
    draft_metadata = draft.metadata if isinstance(draft.metadata, dict) else {}
    project = project_scope_from_asset(storage, draft, input_path=draft_file, workspace_path=workspace_path)
    project_id = str(project.get("project_id") or draft_metadata.get("project_id") or draft_content.get("project_id") or "local-system")
    workspace = str(project.get("workspace_path") or workspace_path or draft_metadata.get("workspace_path") or draft_content.get("workspace_path") or "")
    chapter_no = _chapter_no(draft.to_dict())
    text = str(draft_content.get("text") or "")
    character_ledger, character_ref = _asset_content(storage, character_state_ledger_path)
    villain_plan, villain_ref = _asset_content(storage, villain_operation_plan_path)
    agency = _signals(text, AGENCY_MARKERS)
    charm = _signals(text, CHARM_MARKERS)
    pressure = _signals(text, PRESSURE_MARKERS)
    cost = _signals(text, COST_MARKERS)
    character_rows = character_ledger.get("characters", []) if isinstance(character_ledger.get("characters", []), list) else []
    operations = villain_plan.get("operations", []) if isinstance(villain_plan.get("operations", []), list) else []
    visible_agent = str(villain_plan.get("visible_agent") or ("external_pressure" if pressure else "unassigned"))
    active_move = str((operations[0] or {}).get("villain_action") if operations and isinstance(operations[0], dict) else "")
    protagonist_cost = str((operations[0] or {}).get("protagonist_loss") if operations and isinstance(operations[0], dict) else _sentence_with(text, cost[0]) if cost else "")
    agency_score = _score(30.0, agency, character_rows, extra=len(cost))
    charm_score = _score(34.0, charm, character_rows, extra=len(agency))
    pressure_score = _pressure_score(pressure, visible_agent=visible_agent, active_move=active_move, protagonist_cost=protagonist_cost)
    charm_issues = _charm_issues(agency_score=agency_score, charm_score=charm_score, agency=agency, charm=charm)
    pressure_issues = _pressure_issues(pressure_score=pressure_score, pressure=pressure, visible_agent=visible_agent, active_move=active_move)
    protagonist = ProtagonistCharmReport(
        title=f"Chapter {chapter_no} protagonist charm report",
        source=draft.id,
        tags=["protagonist-charm", _recommendation(charm_issues)],
        content={
            "report_id": make_id("protagonist_charm_report", f"{draft.id}:{chapter_no}:{utc_now()}"),
            "project_id": project_id,
            "workspace_path": workspace,
            "chapter_no": chapter_no,
            "target_asset_id": draft.id,
            "target_asset_path": _display_path(storage.root, draft_file),
            "character_state_ledger_path": character_ref,
            "agency_score": agency_score,
            "charm_score": charm_score,
            "agency_signals": agency,
            "charm_signals": charm,
            "evidence": [_sentence_with(text, signal) for signal in [*agency, *charm][:8]],
            "issues": charm_issues,
            "blocking": any(item.get("blocking") for item in charm_issues),
            "recommendation": _recommendation(charm_issues),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace, "draft_path": _display_path(storage.root, draft_file), "source_system": "character_pressure.gate", "blocking": any(item.get("blocking") for item in charm_issues)},
        references=filter_project_safe_references(storage, project_id, [_display_path(storage.root, draft_file), character_ref]),
    )
    protagonist_result = _write(storage, protagonist)
    antagonist = AntagonistPressureReport(
        title=f"Chapter {chapter_no} antagonist pressure report",
        source=draft.id,
        tags=["antagonist-pressure", _recommendation(pressure_issues)],
        content={
            "report_id": make_id("antagonist_pressure_report", f"{draft.id}:{chapter_no}:{utc_now()}"),
            "project_id": project_id,
            "workspace_path": workspace,
            "chapter_no": chapter_no,
            "target_asset_id": draft.id,
            "target_asset_path": _display_path(storage.root, draft_file),
            "villain_operation_plan_path": villain_ref,
            "pressure_score": pressure_score,
            "visible_agent": visible_agent,
            "active_move": active_move or (_sentence_with(text, pressure[0]) if pressure else "not_detected"),
            "protagonist_cost": protagonist_cost or "not_detected",
            "pressure_signals": pressure,
            "cost_signals": cost,
            "issues": pressure_issues,
            "blocking": any(item.get("blocking") for item in pressure_issues),
            "recommendation": _recommendation(pressure_issues),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace, "draft_path": _display_path(storage.root, draft_file), "source_system": "character_pressure.gate", "blocking": any(item.get("blocking") for item in pressure_issues)},
        references=filter_project_safe_references(storage, project_id, [_display_path(storage.root, draft_file), villain_ref]),
    )
    antagonist_result = _write(storage, antagonist)
    issues = [*charm_issues, *pressure_issues]
    review_issue_paths: list[str] = []
    revision_task_path = ""
    if persist_issues and issues:
        review_issue_paths = _persist_review_issues(
            storage,
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            report_paths=[protagonist_result["path"], antagonist_result["path"]],
            issues=issues,
        )
        revision_task_path = _write_revision_task(
            storage,
            draft_path=_display_path(storage.root, draft_file),
            project_id=project_id,
            workspace_path=workspace,
            report_paths=[protagonist_result["path"], antagonist_result["path"]],
            issues=issues,
            review_issue_paths=review_issue_paths,
        )
    status = "blocked" if any(item.get("blocking") for item in issues) else "needs_revision" if issues else "passed"
    return {
        "status": status,
        "path": protagonist_result["path"],
        "protagonist_charm_report_path": protagonist_result["path"],
        "antagonist_pressure_report_path": antagonist_result["path"],
        "paths": [protagonist_result["path"], antagonist_result["path"]],
        "asset": protagonist_result["asset"],
        "protagonist_charm_report": protagonist_result["asset"],
        "antagonist_pressure_report": antagonist_result["asset"],
        "review_issues": review_issue_paths,
        "revision_task_path": revision_task_path,
    }


def _charm_issues(*, agency_score: float, charm_score: float, agency: list[str], charm: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if agency_score < 40:
        issues.append({"issue_type": "protagonist_charm_drop", "dimension": "agency_score", "severity": "high", "blocking": True, "message": f"protagonist agency score {agency_score} is below threshold", "recommendation": "give protagonist a visible choice or competent action"})
    elif agency_score < 60:
        issues.append({"issue_type": "protagonist_charm_drop", "dimension": "agency_score", "severity": "medium", "blocking": False, "message": f"protagonist agency score {agency_score} is weak", "recommendation": "make protagonist decision pressure explicit"})
    if charm_score < 45 and not charm:
        issues.append({"issue_type": "protagonist_charm_drop", "dimension": "charm_score", "severity": "medium", "blocking": False, "message": "protagonist lacks visible competence, care, or value expression", "recommendation": "add a charm beat through action, protection, competence, or cost"})
    return issues


def _pressure_issues(*, pressure_score: float, pressure: list[str], visible_agent: str, active_move: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if pressure_score < 35:
        issues.append({"issue_type": "antagonist_pressure_drop", "dimension": "pressure_score", "severity": "high", "blocking": True, "message": f"antagonist pressure score {pressure_score} is below threshold", "recommendation": "add an antagonist/proxy move that changes risk, cost, or available choices"})
    elif pressure_score < 58:
        issues.append({"issue_type": "antagonist_pressure_drop", "dimension": "pressure_score", "severity": "medium", "blocking": False, "message": f"antagonist pressure score {pressure_score} is weak", "recommendation": "make opposition pressure visible before the hook"})
    if visible_agent == "unassigned" and not pressure:
        issues.append({"issue_type": "antagonist_pressure_drop", "dimension": "visible_agent", "severity": "medium", "blocking": False, "message": "no visible antagonist, proxy, institution, or pressure source", "recommendation": "define an opposition source for the chapter"})
    if not active_move and pressure_score < 58:
        issues.append({"issue_type": "antagonist_pressure_drop", "dimension": "active_move", "severity": "medium", "blocking": False, "message": "opposition pressure has no active move", "recommendation": "show what the antagonist/proxy does, not only that danger exists"})
    return issues


def _persist_review_issues(
    storage: LocalStorage,
    *,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    report_paths: list[str],
    issues: list[dict[str, Any]],
) -> list[str]:
    paths: list[str] = []
    for index, issue in enumerate(issues):
        result = create_review_issue(
            storage,
            {
                "issue_type": issue["issue_type"],
                "severity": issue["severity"],
                "blocking": bool(issue.get("blocking")),
                "status": "open",
                "target_asset_path": draft_path,
                "target_asset_type": "draft_chapter",
                "project_id": project_id,
                "workspace_path": workspace_path,
                "source_system": "character_pressure.gate",
                "source_issue_id": f"{issue.get('dimension')}:{index}",
                "review_report_path": report_paths[0],
                "message": str(issue.get("message") or ""),
                "fix_suggestion": str(issue.get("recommendation") or ""),
                "location": {"dimension": issue.get("dimension", ""), "scope": "chapter"},
                "evidence_refs": [draft_path, *report_paths],
                "confidence": 0.72,
            },
        )
        if result.get("path"):
            paths.append(str(result["path"]))
    return _dedupe(paths)


def _write_revision_task(
    storage: LocalStorage,
    *,
    draft_path: str,
    project_id: str,
    workspace_path: str,
    report_paths: list[str],
    issues: list[dict[str, Any]],
    review_issue_paths: list[str],
) -> str:
    now = utc_now()
    task = RevisionTask(
        title="Repair character charm and antagonist pressure",
        source=report_paths[0],
        tags=["revision", "character-pressure", "protagonist-charm", "antagonist-pressure"],
        content={
            "task_id": make_id("revision_task", f"character-pressure:{draft_path}:{now}"),
            "review_path": report_paths[0],
            "source_draft_path": draft_path,
            "issue_indexes": list(range(len(issues))),
            "review_issue_ids": [str(item.get("dimension") or index) for index, item in enumerate(issues)],
            "issues": [
                {
                    "issue_index": index,
                    "issue_type": str(issue.get("issue_type") or ""),
                    "severity": str(issue.get("severity") or "medium"),
                    "blocking": bool(issue.get("blocking")),
                    "message": str(issue.get("message") or ""),
                    "recommendation": str(issue.get("recommendation") or ""),
                    "status": "open",
                }
                for index, issue in enumerate(issues)
            ],
            "revision_strategy_plan": {
                "strategy_ids": ["restore_character_charm_pressure"],
                "required_output_evidence": ["protagonist_charm_report_path", "antagonist_pressure_report_path", "re_review_path"],
                "re_review_required": True,
                "quality_gate_required": True,
            },
            "status": "open",
            "stage": "character_pressure_repair_required",
            "outputs": {"review_issue_paths": review_issue_paths},
            "created_at": now,
            "updated_at": now,
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "source_system": "character_pressure.gate"},
        references=filter_project_safe_references(storage, project_id, [draft_path, *report_paths, *review_issue_paths]),
    )
    return _write(storage, task)["path"]


def _signals(text: str, markers: list[str]) -> list[str]:
    lowered = text.lower()
    return _dedupe([marker for marker in markers if marker.lower() in lowered and f"没有{marker}" not in text and f"无{marker}" not in text])


def _score(base: float, signals: list[str], character_rows: list[Any], *, extra: int = 0) -> float:
    return round(min(100.0, base + len(signals) * 12.0 + min(14.0, len(character_rows) * 4.0) + min(12.0, extra * 3.0)), 2)


def _pressure_score(pressure: list[str], *, visible_agent: str, active_move: str, protagonist_cost: str) -> float:
    score = 24.0 + len(pressure) * 12.0
    if visible_agent and visible_agent != "unassigned":
        score += 16.0
    if active_move:
        score += 16.0
    if protagonist_cost:
        score += 12.0
    return round(min(100.0, score), 2)


def _recommendation(issues: list[dict[str, Any]]) -> str:
    if any(item.get("blocking") for item in issues):
        return "blocked"
    return "needs_revision" if issues else "passed"


def _asset_content(storage: LocalStorage, ref: str | Path | None) -> tuple[dict[str, Any], str]:
    if not ref:
        return {}, ""
    path = resolve_path(storage.root, ref)
    data = storage.read_json(path)
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content"), dict) else {}
    return content, _display_path(storage.root, path)


def _chapter_no(asset: dict[str, Any]) -> int:
    content = asset.get("content", {}) if isinstance(asset.get("content"), dict) else {}
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    try:
        return max(1, int(content.get("chapter") or content.get("chapter_no") or metadata.get("chapter") or metadata.get("chapter_no") or 1))
    except (TypeError, ValueError):
        return 1


def _sentence_with(text: str, signal: str) -> str:
    for sentence in re.split(r"[。！？!?；;\n]+", text):
        if signal and signal.lower() in sentence.lower():
            return sentence.strip()[:160]
    return signal[:160]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
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
