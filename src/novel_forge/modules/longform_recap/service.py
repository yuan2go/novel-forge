from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.context_builder import build_flow_context_bundle
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database
from novel_forge.modules.loop_kernel import run_loop
from novel_forge.modules.mkaos import record_review_feedback, record_usage_event
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.review_issue import create_review_issue, list_review_issues
from novel_forge.schemas import (
    ArcPlan,
    CanonPatch,
    CharacterStateLedger,
    ForeshadowingGraph,
    LongformRecapReport,
    RevisionTask,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

RECAP_TRIGGER_TYPES = {"ten_chapter_interval", "volume_end", "blocking_issue_threshold", "major_setting_change", "manual"}


def evaluate_recap_trigger(
    storage: LocalStorage,
    *,
    project_id: str,
    workspace_path: str = "",
    chapter_count: int | None = None,
    volume_end: bool = False,
    major_setting_change: bool = False,
    blocking_issue_threshold: int = 3,
) -> dict[str, Any]:
    chapters = _draft_chapters(storage, project_id=project_id, workspace_path=workspace_path)
    resolved_count = int(chapter_count if chapter_count is not None else len(chapters))
    issues = list_review_issues(storage, project_id=project_id, blocking=True, limit=500)
    active_blocking = [
        issue
        for issue in issues
        if str(issue.get("content", {}).get("status") or "open") in {"open", "acknowledged", "in_revision"}
    ]
    reasons: list[str] = []
    if resolved_count >= 10 and _latest_chapter_number(chapters) >= 10:
        reasons.append("ten_chapter_interval")
    if volume_end:
        reasons.append("volume_end")
    if len(active_blocking) >= int(blocking_issue_threshold or 3):
        reasons.append("blocking_issue_threshold")
    if major_setting_change:
        reasons.append("major_setting_change")
    return {
        "should_trigger": bool(reasons),
        "reasons": reasons,
        "chapter_count": resolved_count,
        "latest_chapter": _latest_chapter_number(chapters),
        "active_blocking_issue_count": len(active_blocking),
        "policy": {
            "every_10_chapters": True,
            "volume_end": bool(volume_end),
            "blocking_issue_threshold": int(blocking_issue_threshold or 3),
            "major_setting_change": bool(major_setting_change),
        },
    }


def run_longform_recap(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    project_id = str(payload.get("project_id") or "local-system")
    workspace_path = str(payload.get("workspace_path") or "")
    trigger = evaluate_recap_trigger(
        storage,
        project_id=project_id,
        workspace_path=workspace_path,
        chapter_count=payload.get("chapter_count") if isinstance(payload.get("chapter_count"), int) else None,
        volume_end=bool(payload.get("volume_end")),
        major_setting_change=bool(payload.get("major_setting_change")),
        blocking_issue_threshold=int(payload.get("blocking_issue_threshold", 3) or 3),
    )
    force = bool(payload.get("force", False))
    if not trigger["should_trigger"] and not force:
        return {"status": "skipped", "trigger": trigger, "reason": "recap trigger not reached"}

    chapters = _draft_chapters(storage, project_id=project_id, workspace_path=workspace_path)
    if not chapters:
        raise FileNotFoundError("no draft_chapter or draft_version assets found for longform recap")
    selected = _select_recent_chapters(chapters, limit=int(payload.get("chapter_window", 12) or 12))
    latest = selected[-1]
    latest_path = latest["path"]
    context = build_flow_context_bundle(
        storage,
        latest_path,
        flow="recap",
        project_id=project_id,
        workspace_path=workspace_path,
        chapter_id=str(latest.get("chapter", "")),
        current_goal="longform recap governance",
        token_budget=int(payload.get("token_budget", 4000) or 4000),
        source_policy={"source_chunk_raw_text_allowed": False, "runtime_assets_in_generation_rag_allowed": False},
        environment=str(payload.get("environment") or ""),
        os_envelope=payload.get("envelope") if isinstance(payload.get("envelope"), dict) else None,
    )
    loop = run_loop(
        storage,
        {
            "loop_type": "longform_recap",
            "target_path": latest_path,
            "project_id": project_id,
            "workspace_path": workspace_path,
            "context_bundle_path": context["path"],
            "budget": payload.get("budget") if isinstance(payload.get("budget"), dict) else {"max_steps": 6, "max_tokens": 4000, "max_cost": 1.0, "max_duration_seconds": 900},
            "steps": [
                {"step_type": "context_build", "operation": "recap_context_loaded", "token_estimate": 80, "cost_estimate": 0.0},
                {"step_type": "recap_scan", "operation": "scan_longform_state", "token_estimate": 160, "cost_estimate": 0.0},
                {"step_type": "recap_report", "operation": "prepare_governance_writeback", "token_estimate": 120, "cost_estimate": 0.0},
            ],
            "envelope": payload.get("envelope") if isinstance(payload.get("envelope"), dict) else None,
            "environment": str(payload.get("environment") or ""),
            "bypass_reason": str(payload.get("bypass_reason") or "longform recap local execution"),
        },
    )
    active_issues = list_review_issues(storage, project_id=project_id, limit=500)
    state = _longform_state(storage, project_id=project_id, workspace_path=workspace_path, selected_chapters=selected)
    recap_report_id = make_id("longform_recap_report", f"{project_id}-{selected[0]['chapter']}-{selected[-1]['chapter']}-{utc_now()}")
    content = _recap_content(
        recap_report_id=recap_report_id,
        project_id=project_id,
        workspace_path=workspace_path,
        trigger=trigger if trigger["should_trigger"] else {"should_trigger": True, "reasons": ["manual"], **trigger},
        chapters=selected,
        state=state,
        active_issues=active_issues,
        context=context,
        loop=loop,
    )
    asset = LongformRecapReport(
        id=recap_report_id,
        title=f"Longform recap chapters {selected[0]['chapter']}-{selected[-1]['chapter']}",
        source=str(latest.get("id") or project_id),
        tags=["longform-recap", "governance", *content["trigger"]["reasons"]],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "workflow": "longform-recap-agent",
            "latest_chapter": selected[-1]["chapter"],
            "chapter_count": len(chapters),
            "context_bundle_path": context["path"],
            "loop_run_path": loop["loop_run_path"],
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([latest.get("id", ""), latest_path, context["path"], loop["loop_run_path"], *[chapter["id"] for chapter in selected], *state["asset_paths"]]),
        ),
    )
    _ensure_valid(asset.to_dict())
    report_path = storage.write_asset_auto(asset)
    writeback = _apply_writeback(
        storage,
        report_path=_display_path(storage.root, report_path),
        report_id=recap_report_id,
        content=content,
        project_id=project_id,
        workspace_path=workspace_path,
        latest=latest,
        context=context,
    )
    _attach_writeback(storage, report_path, writeback)
    updated = storage.read_json(report_path)
    return {
        "status": "succeeded",
        "path": _display_path(storage.root, report_path),
        "asset": updated,
        "trigger": trigger,
        "context_bundle_path": context["path"],
        "loop": loop,
        "writeback": writeback,
    }


def list_longform_recap_reports(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("continuity")):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "longform_recap_report":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or "") != project_id:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return rows


def _recap_content(
    *,
    recap_report_id: str,
    project_id: str,
    workspace_path: str,
    trigger: dict[str, Any],
    chapters: list[dict[str, Any]],
    state: dict[str, Any],
    active_issues: list[dict[str, Any]],
    context: dict[str, Any],
    loop: dict[str, Any],
) -> dict[str, Any]:
    chapter_numbers = [int(chapter["chapter"]) for chapter in chapters]
    blocking_count = sum(1 for issue in active_issues if bool(issue.get("content", {}).get("blocking")))
    continuity_risks = _continuity_risks(chapters, state, active_issues)
    character_report = _character_drift_report(state)
    foreshadowing_report = _foreshadowing_report(state)
    pacing_report = _pacing_report(state)
    commercial_report = _commercial_rhythm_report(state)
    suggestions = _revision_suggestions(continuity_risks, character_report, foreshadowing_report, pacing_report, commercial_report)
    return {
        "recap_report_id": recap_report_id,
        "project_id": project_id,
        "workspace_path": workspace_path,
        "trigger": {
            "should_trigger": bool(trigger.get("should_trigger", True)),
            "reasons": trigger.get("reasons", ["manual"]),
            "chapter_count": trigger.get("chapter_count", len(chapters)),
            "latest_chapter": trigger.get("latest_chapter", chapter_numbers[-1] if chapter_numbers else 0),
        },
        "chapter_range": {"start": min(chapter_numbers), "end": max(chapter_numbers), "count": len(chapter_numbers)},
        "stage_summary": {
            "chapters_reviewed": len(chapters),
            "latest_chapter": chapter_numbers[-1] if chapter_numbers else 0,
            "active_review_issue_count": len(active_issues),
            "blocking_review_issue_count": blocking_count,
            "known_state_assets": state["counts_by_type"],
            "context_bundle_path": context.get("path", ""),
            "loop_run_path": loop.get("loop_run_path", ""),
        },
        "continuity_risks": continuity_risks,
        "character_drift_report": character_report,
        "foreshadowing_report": foreshadowing_report,
        "pacing_report": pacing_report,
        "commercial_rhythm_report": commercial_report,
        "revision_suggestions": suggestions,
        "memory_update_package": {
            "canon_updates": _canon_update_package(state, continuity_risks),
            "character_updates": character_report.get("updates", []),
            "arc_updates": _arc_update_package(state, suggestions),
            "foreshadowing_updates": foreshadowing_report.get("updates", []),
            "review_issue_updates": _review_issue_candidates(continuity_risks, character_report, foreshadowing_report, pacing_report),
            "revision_task_candidates": [{"instruction": item, "severity": "high" if index == 0 else "medium"} for index, item in enumerate(suggestions[:6])],
            "mkaos_context": _mkaos_summary(context),
        },
        "writeback": {
            "status": "pending",
            "canon_patch_path": "",
            "character_state_ledger_path": "",
            "arc_plan_path": "",
            "foreshadowing_graph_path": "",
            "review_issue_paths": [],
            "revision_task_path": "",
            "mkaos_usage_event_count": 0,
            "mkaos_feedback_paths": [],
        },
        "created_at": utc_now(),
    }


def _apply_writeback(
    storage: LocalStorage,
    *,
    report_path: str,
    report_id: str,
    content: dict[str, Any],
    project_id: str,
    workspace_path: str,
    latest: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    canon_patch = _write_canon_patch(storage, report_path=report_path, report_id=report_id, content=content, project_id=project_id, workspace_path=workspace_path, latest=latest)
    character = _write_character_ledger(storage, report_path=report_path, report_id=report_id, content=content, project_id=project_id, workspace_path=workspace_path)
    arc = _write_arc_recap(storage, report_path=report_path, report_id=report_id, content=content, project_id=project_id, workspace_path=workspace_path)
    foreshadowing = _write_foreshadowing_graph(storage, report_path=report_path, report_id=report_id, content=content, project_id=project_id, workspace_path=workspace_path)
    review_issues = _write_review_issues(storage, report_path=report_path, report_id=report_id, content=content, project_id=project_id, latest=latest)
    revision_task = _write_revision_task(storage, report_path=report_path, report_id=report_id, content=content, project_id=project_id, workspace_path=workspace_path, latest=latest, review_issue_paths=review_issues)
    mkaos = _write_mkaos_feedback(storage, report_id=report_id, project_id=project_id, workspace_path=workspace_path, context=context)
    return {
        "status": "applied",
        "canon_patch_path": canon_patch.get("path", ""),
        "character_state_ledger_path": character.get("path", ""),
        "arc_plan_path": arc.get("path", ""),
        "foreshadowing_graph_path": foreshadowing.get("path", ""),
        "review_issue_paths": review_issues,
        "revision_task_path": revision_task.get("path", ""),
        "mkaos_usage_event_count": mkaos.get("usage_event_count", 0),
        "mkaos_feedback_paths": mkaos.get("feedback_paths", []),
    }


def _write_canon_patch(storage: LocalStorage, *, report_path: str, report_id: str, content: dict[str, Any], project_id: str, workspace_path: str, latest: dict[str, Any]) -> dict[str, Any]:
    update_package = content["memory_update_package"]["canon_updates"]
    asset = CanonPatch(
        title=f"Canon recap patch {content['chapter_range']['start']}-{content['chapter_range']['end']}",
        source=report_id,
        tags=["canon", "patch", "longform-recap", "human-gated"],
        content={
            "patch_id": make_id("canon_patch", report_id),
            "target_draft_id": latest.get("id", ""),
            "target_draft_path": latest.get("path", ""),
            "chapter": latest.get("chapter", 0),
            "status": "proposed",
            "proposed_events": update_package.get("proposed_events", []),
            "entity_updates": update_package.get("entity_updates", []),
            "thread_updates": update_package.get("thread_updates", []),
            "relationship_updates": update_package.get("relationship_updates", []),
            "apply_plan": {
                "mode": "human_confirmed",
                "source_recap_report_path": report_path,
                "writes": ["canon_database.recap_history", "canon_patch.status"],
                "rollback": "reject canon_patch or restore data/backups copy before apply",
            },
            "human_gate": {"required": True, "status": "waiting_human", "instructions": "Review recap canon updates before applying."},
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "longform-recap-agent", "risk_level": "medium"},
        references=filter_project_safe_references(storage, project_id, [report_id, report_path, latest.get("id", ""), latest.get("path", "")]),
    )
    return _write(storage, asset)


def _write_character_ledger(storage: LocalStorage, *, report_path: str, report_id: str, content: dict[str, Any], project_id: str, workspace_path: str) -> dict[str, Any]:
    latest_chapter = int(content["chapter_range"]["end"])
    asset = CharacterStateLedger(
        title=f"Recap character state ledger to chapter {latest_chapter}",
        source=report_id,
        tags=["character-state", "longform-recap"],
        content={
            "ledger_id": make_id("character_state_ledger", report_id),
            "chapter_no": latest_chapter,
            "characters": content["character_drift_report"].get("characters", []),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "longform-recap-agent", "source_recap_report_path": report_path},
        references=filter_project_safe_references(storage, project_id, [report_id, report_path]),
    )
    return _write(storage, asset)


def _write_arc_recap(storage: LocalStorage, *, report_path: str, report_id: str, content: dict[str, Any], project_id: str, workspace_path: str) -> dict[str, Any]:
    latest = _latest_asset(storage, "continuity", "arc_plan", project_id=project_id)
    if latest:
        path, data = latest
        payload = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        history = payload.get("recap_history", []) if isinstance(payload.get("recap_history", []), list) else []
        history.append({"recap_report_id": report_id, "recap_report_path": report_path, "chapter_range": content["chapter_range"], "suggestions": content["revision_suggestions"][:4], "created_at": utc_now()})
        payload["recap_history"] = history[-20:]
        payload["last_recap_report_id"] = report_id
        data["content"] = payload
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        metadata["last_recap_report_path"] = report_path
        data["metadata"] = metadata
        data["updated_at"] = utc_now()
        _ensure_valid(data)
        storage.write_json(path, data)
        return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}
    return create_arc_plan(
        storage,
        arc_id=make_id("arc", report_id),
        title="Recap inferred active arc",
        chapter_range=f"{content['chapter_range']['start']}-{content['chapter_range']['end']}",
        arc_question="Recap requires operator to confirm active longform arc.",
        protagonist_goal="Stabilize next chapter continuity after recap.",
        villain_goal="Maintain coherent pressure and payoff chain.",
        required_payoffs=content["revision_suggestions"][:3],
        forbidden_expansion=["do not expand new arc before resolving recap risks"],
        project_id=project_id,
        workspace_path=workspace_path,
    )


def _write_foreshadowing_graph(storage: LocalStorage, *, report_path: str, report_id: str, content: dict[str, Any], project_id: str, workspace_path: str) -> dict[str, Any]:
    latest_chapter = int(content["chapter_range"]["end"])
    updates = content["foreshadowing_report"].get("updates", [])
    clues = [
        {
            "clue_id": make_id("recap_clue", str(item)),
            "name": str(item.get("name") or item.get("clue") or "recap clue"),
            "source_chapter": int(item.get("source_chapter", latest_chapter) or latest_chapter),
            "target_truth": str(item.get("target_truth") or "operator confirmation required"),
            "planned_payoff_chapter": int(item.get("planned_payoff_chapter", latest_chapter + 3) or latest_chapter + 3),
            "status": str(item.get("status") or "active"),
            "last_updated_chapter": latest_chapter,
        }
        for item in updates[:20]
        if isinstance(item, dict)
    ]
    asset = ForeshadowingGraph(
        title=f"Recap foreshadowing graph to chapter {latest_chapter}",
        source=report_id,
        tags=["foreshadowing", "longform-recap"],
        content={
            "graph_id": make_id("foreshadowing_graph", report_id),
            "chapter_no": latest_chapter,
            "clues": clues,
            "edges": [{"source": clue["clue_id"], "target": clue["target_truth"], "relation": "recap_points_to_truth"} for clue in clues],
            "issues": content["foreshadowing_report"].get("risks", []),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "longform-recap-agent", "source_recap_report_path": report_path},
        references=filter_project_safe_references(storage, project_id, [report_id, report_path]),
    )
    return _write(storage, asset)


def _write_review_issues(storage: LocalStorage, *, report_path: str, report_id: str, content: dict[str, Any], project_id: str, latest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for candidate in content["memory_update_package"]["review_issue_updates"][:6]:
        result = create_review_issue(
            storage,
            {
                **candidate,
                "project_id": project_id,
                "target_asset_id": latest.get("id", report_id),
                "target_asset_type": latest.get("type", "draft_chapter"),
                "target_asset_path": latest.get("path", ""),
                "evidence_refs": [report_id, report_path],
                "source_system": "longform_recap.agent",
            },
        )
        paths.append(result["path"])
    return paths


def _write_revision_task(
    storage: LocalStorage,
    *,
    report_path: str,
    report_id: str,
    content: dict[str, Any],
    project_id: str,
    workspace_path: str,
    latest: dict[str, Any],
    review_issue_paths: list[str],
) -> dict[str, Any]:
    suggestions = content.get("revision_suggestions", [])
    if not suggestions:
        return {"path": "", "asset": {}}
    issues = [
        {
            "issue_id": make_id("recap_revision_issue", f"{report_id}-{index}"),
            "issue_index": index,
            "dimension": "longform_recap",
            "severity": "high" if index == 0 else "medium",
            "message": suggestion,
            "recommendation": "turn recap suggestion into concrete revision patch",
            "status": "open",
        }
        for index, suggestion in enumerate(suggestions[:8])
    ]
    asset = RevisionTask(
        title=f"Longform recap revision task {content['chapter_range']['start']}-{content['chapter_range']['end']}",
        source=report_id,
        tags=["revision", "task", "longform-recap"],
        content={
            "task_id": make_id("revision_task", report_id),
            "review_id": report_id,
            "review_path": report_path,
            "source_draft_id": latest.get("id", ""),
            "source_draft_path": latest.get("path", ""),
            "issue_indexes": list(range(len(issues))),
            "review_issue_ids": [item["issue_id"] for item in issues],
            "issues": issues,
            "status": "open",
            "stage": "longform_recap",
            "outputs": {"review_issue_paths": review_issue_paths},
            "created_at": utc_now(),
            "updated_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": workspace_path, "workflow": "longform-recap-agent", "source_recap_report_path": report_path},
        references=filter_project_safe_references(storage, project_id, [report_id, report_path, latest.get("id", ""), latest.get("path", ""), *review_issue_paths]),
    )
    return _write(storage, asset)


def _write_mkaos_feedback(storage: LocalStorage, *, report_id: str, project_id: str, workspace_path: str, context: dict[str, Any]) -> dict[str, Any]:
    knowledge_ids = _mkaos_knowledge_ids(context)
    if not knowledge_ids:
        return {"usage_event_count": 0, "feedback_paths": []}
    usage = record_usage_event(
        storage,
        {
            "knowledge_ids": knowledge_ids,
            "knowledge_pack_id": _mkaos_pack_id(context),
            "project_id": project_id,
            "workspace_path": workspace_path,
            "flow": "review",
            "target_artifact_id": report_id,
            "agent_name": "longform-recap-agent",
            "used_as": "longform_recap_context",
            "review_result": {"recap_report_id": report_id, "used_for": "longform governance"},
        },
    )
    feedback_paths: list[str] = []
    for knowledge_id in knowledge_ids[:8]:
        result = record_review_feedback(
            storage,
            {
                "knowledge_id": knowledge_id,
                "project_id": project_id,
                "workspace_path": workspace_path,
                "flow": "review",
                "review_passed": True,
                "human_confirmed_effective": True,
                "delta": 0.01,
                "reason": "longform_recap_context_used",
            },
        )
        feedback_paths.append(result["path"])
    return {"usage_event_count": usage.get("event_count", 0), "feedback_paths": feedback_paths}


def _attach_writeback(storage: LocalStorage, report_path: Path, writeback: dict[str, Any]) -> None:
    data = storage.read_json(report_path)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    content["writeback"] = writeback
    data["content"] = content
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(report_path, data)


def _longform_state(storage: LocalStorage, *, project_id: str, workspace_path: str, selected_chapters: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for category in ["continuity", "reviews", "publishing"]:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id") or "") not in {"", project_id}:
                continue
            if workspace_path and str(metadata.get("workspace_path") or "") not in {"", workspace_path}:
                continue
            rows.append({**data, "path": _display_path(storage.root, path)})
    return {
        "assets": rows,
        "asset_paths": [row["path"] for row in rows],
        "counts_by_type": _count_by_type(rows),
        "chapter_states": [row for row in rows if row.get("type") == "chapter_state"],
        "character_ledgers": [row for row in rows if row.get("type") == "character_state_ledger"],
        "foreshadowing_graphs": [row for row in rows if row.get("type") == "foreshadowing_graph"],
        "motif_reports": [row for row in rows if row.get("type") == "motif_budget_report"],
        "fatigue_reports": [row for row in rows if row.get("type") == "reader_fatigue_report"],
        "reward_ledgers": [row for row in rows if row.get("type") == "reward_ledger"],
        "selected_chapters": selected_chapters,
    }


def _draft_chapters(storage: LocalStorage, *, project_id: str, workspace_path: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("drafts"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in {"draft_chapter", "draft_version"}:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or "") != project_id:
            continue
        if workspace_path and str(metadata.get("workspace_path") or "") not in {"", workspace_path}:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title", ""),
                "chapter": _int(content.get("chapter", content.get("chapter_no", 0))),
                "text_length": len(str(content.get("text") or "")),
                "path": _display_path(storage.root, path),
            }
        )
    return sorted(rows, key=lambda row: (int(row.get("chapter", 0) or 0), row.get("path", "")))


def _select_recent_chapters(chapters: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return chapters[-max(1, int(limit or 12)) :]


def _continuity_risks(chapters: list[dict[str, Any]], state: dict[str, Any], active_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    known_state_chapters = {_chapter_from_content(row) for row in state.get("chapter_states", [])}
    for chapter in chapters:
        if int(chapter.get("chapter", 0) or 0) not in known_state_chapters:
            risks.append({"risk_type": "missing_chapter_state", "severity": "high", "chapter": chapter.get("chapter"), "message": "chapter lacks chapter_state writeback"})
    if any(issue.get("content", {}).get("blocking") for issue in active_issues):
        risks.append({"risk_type": "active_blocking_review_issue", "severity": "high", "count": sum(1 for issue in active_issues if issue.get("content", {}).get("blocking")), "message": "active blocking ReviewIssue remains unresolved"})
    return risks[:20]


def _character_drift_report(state: dict[str, Any]) -> dict[str, Any]:
    characters: dict[str, dict[str, Any]] = {}
    risks: list[dict[str, Any]] = []
    for ledger in state.get("character_ledgers", []):
        content = ledger.get("content", {}) if isinstance(ledger.get("content", {}), dict) else {}
        for item in content.get("characters", []) if isinstance(content.get("characters", []), list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("character_id") or item.get("name") or "protagonist")
            row = characters.setdefault(name, {"character_id": name, "active_burdens": [], "risks": [], "ledger_count": 0})
            row["ledger_count"] += 1
            row["active_burdens"].extend([str(value) for value in item.get("active_burdens", []) if str(value).strip()] if isinstance(item.get("active_burdens", []), list) else [])
            row["risks"].extend([str(value) for value in item.get("risks", []) if str(value).strip()] if isinstance(item.get("risks", []), list) else [])
    for row in characters.values():
        if len(row.get("active_burdens", [])) >= 3 or len(row.get("risks", [])) >= 3:
            risks.append({"risk_type": "character_burden_accumulation", "severity": "medium", "character_id": row["character_id"], "message": "character burden/risk list needs payoff or pruning"})
    return {"characters": list(characters.values()), "risks": risks, "updates": list(characters.values())}


def _foreshadowing_report(state: dict[str, Any]) -> dict[str, Any]:
    clues: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for graph in state.get("foreshadowing_graphs", []):
        content = graph.get("content", {}) if isinstance(graph.get("content", {}), dict) else {}
        for clue in content.get("clues", []) if isinstance(content.get("clues", []), list) else []:
            if isinstance(clue, dict):
                clues.append(clue)
                if not str(clue.get("target_truth") or "").strip():
                    risks.append({"risk_type": "unbound_foreshadowing", "severity": "high", "message": f"clue lacks target truth: {clue.get('name', '')}"})
    return {"open_clue_count": len([item for item in clues if str(item.get("status") or "active") == "active"]), "risks": risks, "updates": clues[-20:]}


def _pacing_report(state: dict[str, Any]) -> dict[str, Any]:
    risks: list[dict[str, Any]] = []
    for report in state.get("motif_reports", []):
        content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
        for issue in content.get("issues", []) if isinstance(content.get("issues", []), list) else []:
            if isinstance(issue, dict) and issue.get("severity") in {"high", "critical"}:
                risks.append({"risk_type": "motif_budget", "severity": issue.get("severity"), "message": issue.get("message", "motif budget risk")})
    for report in state.get("fatigue_reports", []):
        content = report.get("content", {}) if isinstance(report.get("content", {}), dict) else {}
        if str(content.get("risk") or "") == "high":
            risks.append({"risk_type": "reader_fatigue", "severity": "high", "message": "reader fatigue risk high"})
    return {"risks": risks, "recommendation": "vary investigation method and payoff rhythm" if risks else "pacing stable"}


def _commercial_rhythm_report(state: dict[str, Any]) -> dict[str, Any]:
    reward_count = 0
    cost_count = 0
    for ledger in state.get("reward_ledgers", []):
        content = ledger.get("content", {}) if isinstance(ledger.get("content", {}), dict) else {}
        reward_count += len(content.get("rewards", []) if isinstance(content.get("rewards", []), list) else [])
        cost_count += len(content.get("costs", []) if isinstance(content.get("costs", []), list) else [])
    balance = "cost_heavy" if cost_count > reward_count * 2 and cost_count > 2 else "reward_light" if reward_count == 0 else "balanced"
    return {"reward_count": reward_count, "cost_count": cost_count, "balance": balance, "risks": [{"risk_type": "commercial_rhythm", "severity": "medium", "message": "reward/cost rhythm is cost-heavy"}] if balance == "cost_heavy" else []}


def _revision_suggestions(*reports: Any) -> list[str]:
    suggestions: list[str] = []
    for report in reports:
        if isinstance(report, list):
            for item in report:
                if isinstance(item, dict):
                    suggestions.append(str(item.get("message") or item.get("risk_type") or "resolve longform risk"))
        elif isinstance(report, dict):
            for item in report.get("risks", []) if isinstance(report.get("risks", []), list) else []:
                if isinstance(item, dict):
                    suggestions.append(str(item.get("message") or item.get("risk_type") or "resolve longform risk"))
    return _dedupe(suggestions or ["keep next chapter aligned with latest recap memory package"])


def _canon_update_package(state: dict[str, Any], risks: list[dict[str, Any]]) -> dict[str, Any]:
    latest_facts = []
    for asset in state.get("assets", []):
        if asset.get("type") == "fact_ledger":
            content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
            latest_facts.extend(content.get("facts", []) if isinstance(content.get("facts", []), list) else [])
    return {
        "proposed_events": latest_facts[-12:],
        "entity_updates": [],
        "thread_updates": [{"risk": risk.get("risk_type"), "message": risk.get("message")} for risk in risks],
        "relationship_updates": [],
    }


def _arc_update_package(state: dict[str, Any], suggestions: list[str]) -> dict[str, Any]:
    return {"recap_suggestions": suggestions[:6], "state_counts": state.get("counts_by_type", {})}


def _review_issue_candidates(continuity_risks: list[dict[str, Any]], character_report: dict[str, Any], foreshadowing_report: dict[str, Any], pacing_report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for risk in continuity_risks:
        candidates.append({"issue_type": "plot_logic_gap", "severity": risk.get("severity", "high"), "blocking": risk.get("severity") == "high", "message": risk.get("message", "continuity risk"), "fix_suggestion": "resolve longform continuity risk before publishing next package"})
    for risk in character_report.get("risks", []):
        candidates.append({"issue_type": "character_drift", "severity": risk.get("severity", "medium"), "blocking": False, "message": risk.get("message", "character drift risk"), "fix_suggestion": "pay off or prune accumulated character burden"})
    for risk in foreshadowing_report.get("risks", []):
        candidates.append({"issue_type": "foreshadowing_drop", "severity": risk.get("severity", "high"), "blocking": risk.get("severity") == "high", "message": risk.get("message", "foreshadowing risk"), "fix_suggestion": "bind clue to target truth or remove it"})
    for risk in pacing_report.get("risks", []):
        candidates.append({"issue_type": "pacing_collapse", "severity": risk.get("severity", "medium"), "blocking": False, "message": risk.get("message", "pacing risk"), "fix_suggestion": "vary chapter rhythm and payoff cadence"})
    return candidates[:12]


def _mkaos_summary(context: dict[str, Any]) -> dict[str, Any]:
    asset = context.get("asset", {}) if isinstance(context.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    pack = content.get("mkaos_pack", {}) if isinstance(content.get("mkaos_pack", {}), dict) else {}
    return {
        "knowledge_pack_id": content.get("mkaos_pack_id", ""),
        "knowledge_pack_path": content.get("mkaos_pack_path", ""),
        "knowledge_ids": _mkaos_knowledge_ids(context),
        "pack_item_count": len(pack.get("pack_items", []) if isinstance(pack.get("pack_items", []), list) else []),
    }


def _mkaos_pack_id(context: dict[str, Any]) -> str:
    asset = context.get("asset", {}) if isinstance(context.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(content.get("mkaos_pack_id") or content.get("mkaos_knowledge_pack_id") or "")


def _mkaos_knowledge_ids(context: dict[str, Any]) -> list[str]:
    asset = context.get("asset", {}) if isinstance(context.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    pack = content.get("mkaos_pack", {}) if isinstance(content.get("mkaos_pack", {}), dict) else {}
    ids: list[str] = []
    for item in pack.get("pack_items", []) if isinstance(pack.get("pack_items", []), list) else []:
        if isinstance(item, dict) and str(item.get("knowledge_id") or "").strip():
            ids.append(str(item["knowledge_id"]))
    return _dedupe(ids)


def _latest_asset(storage: LocalStorage, category: str, asset_type: str, *, project_id: str) -> tuple[Path, dict[str, Any]] | None:
    for path in reversed(storage.list_json(category)):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or "") not in {"", project_id}:
            continue
        return path, data
    return None


def _latest_chapter_number(chapters: list[dict[str, Any]]) -> int:
    return max([int(chapter.get("chapter", 0) or 0) for chapter in chapters] or [0])


def _chapter_from_content(asset: dict[str, Any]) -> int:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return _int(content.get("chapter_no", content.get("chapter", 0)))


def _count_by_type(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("type") or "")] = counts.get(str(row.get("type") or ""), 0) + 1
    return counts


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    _ensure_valid(data)
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def _ensure_valid(asset: dict[str, Any]) -> None:
    errors = validate_common_fields(asset)
    if errors:
        raise ValueError("; ".join(errors))


def _display_path(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
