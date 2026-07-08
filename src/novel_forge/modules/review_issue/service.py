from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import ReviewIssue, validate_common_fields
from novel_forge.storage.local import LocalStorage

ISSUE_TYPES = {
    "mkaos_conflict",
    "canon_conflict",
    "character_drift",
    "foreshadowing_drop",
    "plot_logic_gap",
    "pacing_collapse",
    "ai_style",
    "repetition",
    "platform_policy_risk",
    "source_leakage",
    "context_budget_overflow",
    "genre_risk",
    "style_drift",
    "quality_gate",
    "canon_plugin_conflict",
    "feedback_mutation_risk",
    "reader_promise_drop",
    "chapter_economy_gap",
    "protagonist_charm_drop",
    "antagonist_pressure_drop",
    "mobile_reading_friction",
    "source_snapshot_drift",
}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
ACTIVE_STATUSES = {"open", "acknowledged", "in_revision"}
TERMINAL_STATUSES = {"resolved", "waived", "closed"}
HIGH_BLOCKING_TYPES = {
    "mkaos_conflict",
    "canon_conflict",
    "source_leakage",
    "context_budget_overflow",
    "plot_logic_gap",
    "genre_risk",
    "style_drift",
    "quality_gate",
    "canon_plugin_conflict",
    "reader_promise_drop",
    "chapter_economy_gap",
    "protagonist_charm_drop",
    "antagonist_pressure_drop",
    "mobile_reading_friction",
}
REVISION_EVIDENCE_CHAIN = [
    "revision_task_path",
    "revision_plan_path",
    "editor_patch_path",
    "draft_version_path",
    "re_review_path",
]
REVISION_STRATEGY_DEFAULT = {
    "strategy_id": "targeted_revision",
    "strategy_name": "Targeted issue repair",
    "patch_scope": "affected_span",
    "instructions": [
        "Resolve the specific ReviewIssue without changing unrelated story facts.",
        "Preserve project-owned prose, canon boundaries, and chapter hook.",
        "Record before/after evidence and send the revised draft through re-review.",
    ],
    "re_review_focus": ["issue resolved", "no new canon/style/quality regression"],
    "risk_controls": ["bounded_patch", "versioned_draft", "rollback_patch", "re_review_required"],
}
REVISION_STRATEGY_RULES = [
    {
        "strategy_id": "rewrite_opening_pressure",
        "strategy_name": "Rewrite opening pressure",
        "issue_types": {"quality_gate", "pacing_collapse"},
        "keywords": {"opening_pressure", "opening", "first 300", "开头", "压力"},
        "patch_scope": "opening_300_800_words",
        "instructions": [
            "Rewrite the opening so an event, abnormal signal, pressure, or irreversible choice appears immediately.",
            "Keep the original premise and viewpoint while replacing exposition with observable action.",
            "End the repaired opening with a question, threat, discovery, or cost that pulls the reader forward.",
        ],
        "re_review_focus": ["opening pressure", "event arrives early", "reader hook strengthened"],
        "risk_controls": ["preserve_premise", "no_raw_reference_text", "mobile_reading_check"],
    },
    {
        "strategy_id": "scene_action_rewrite",
        "strategy_name": "Convert summary into scene action",
        "issue_types": {"quality_gate", "pacing_collapse", "ai_style"},
        "keywords": {"scene_progression", "推进", "说明", "summary", "exposition"},
        "patch_scope": "stalled_scene_or_paragraphs",
        "instructions": [
            "Convert abstract explanation into concrete actions, sensory details, choices, and consequences.",
            "Ensure each repaired paragraph changes information, emotion, risk, or character position.",
            "Remove redundant summary sentences that do not alter the scene state.",
        ],
        "re_review_focus": ["scene progression", "paragraph-level state change", "reduced exposition"],
        "risk_controls": ["bounded_scene_patch", "specificity_required", "re_review_required"],
    },
    {
        "strategy_id": "raise_conflict_cost",
        "strategy_name": "Raise conflict cost and opposition",
        "issue_types": {"quality_gate", "plot_logic_gap", "pacing_collapse"},
        "keywords": {"conflict_strength", "conflict", "阻碍", "代价", "压力", "weak conflict"},
        "patch_scope": "conflict_beats",
        "instructions": [
            "Add an active obstacle, cost, or credible opponent response to the weak conflict beat.",
            "Make the protagonist choose under pressure instead of simply receiving information.",
            "Show a consequence that changes the next beat or chapter hook.",
        ],
        "re_review_focus": ["conflict intensity", "cost visible", "choice under pressure"],
        "risk_controls": ["canon_aligned_conflict", "no_deus_ex_machina", "payoff_preserved"],
    },
    {
        "strategy_id": "concretize_language",
        "strategy_name": "Concretize AI-flavored language",
        "issue_types": {"quality_gate", "ai_style", "repetition"},
        "keywords": {"ai_flavor", "ai style", "abstract", "具体", "套话", "重复"},
        "patch_scope": "abstract_or_repetitive_paragraphs",
        "instructions": [
            "Replace generic conclusion language with concrete actions, objects, reactions, and subtext.",
            "Vary sentence rhythm without imitating any reference source.",
            "Remove repeated abstract nouns unless they are carried by scene evidence.",
        ],
        "re_review_focus": ["specificity", "anti-AI style", "sentence rhythm"],
        "risk_controls": ["source_isolation", "no_reference_phrasing", "style_policy_check"],
    },
    {
        "strategy_id": "strengthen_closing_hook",
        "strategy_name": "Strengthen closing hook",
        "issue_types": {"quality_gate", "pacing_collapse"},
        "keywords": {"ending_hook", "closing hook", "结尾", "钩子", "hook"},
        "patch_scope": "last_300_words",
        "instructions": [
            "Rebuild the ending around an unresolved question, reversal, discovery, threat, or emotional debt.",
            "Tie the hook to the chapter plan payoff target instead of appending a decorative cliffhanger.",
            "Keep the reader promise visible for the next chapter.",
        ],
        "re_review_focus": ["ending hook", "next-chapter pull", "payoff promise"],
        "risk_controls": ["promise_ledger_check", "no_fake_twist", "re_review_required"],
    },
    {
        "strategy_id": "mobile_paragraph_reflow",
        "strategy_name": "Reflow for mobile reading",
        "issue_types": {"quality_gate", "mobile_reading_friction"},
        "keywords": {"mobile_rhythm", "mobile", "paragraph", "段落"},
        "patch_scope": "paragraph_layout",
        "instructions": [
            "Split oversized paragraphs and keep each mobile screen beat easy to scan.",
            "Preserve sentence meaning while improving rhythm, white space, and beat transitions.",
            "Avoid adding filler text during reflow.",
        ],
        "re_review_focus": ["mobile paragraph rhythm", "no filler", "readability"],
        "risk_controls": ["meaning_preserved", "diff_review", "re_review_required"],
    },
    {
        "strategy_id": "canon_aligned_rewrite",
        "strategy_name": "Canon-aligned rewrite",
        "issue_types": {"canon_conflict", "canon_plugin_conflict"},
        "keywords": {"canon", "continuity", "设定", "状态机", "rule"},
        "patch_scope": "canon_conflicting_span",
        "instructions": [
            "Recheck canon facts, typed graph state, and chapter state before changing prose.",
            "Rewrite only the contradictory span or update the upstream plan through an explicit approval path.",
            "Attach canon gate evidence after the repair.",
        ],
        "re_review_focus": ["canon conflict resolved", "typed graph still consistent", "no new continuity drift"],
        "risk_controls": ["canon_gate_required", "approval_for_canon_change", "rollback_patch"],
    },
    {
        "strategy_id": "restore_character_voice_motivation",
        "strategy_name": "Restore character voice and motivation",
        "issue_types": {"character_drift"},
        "keywords": {"character", "voice", "motivation", "人物", "动机", "口吻"},
        "patch_scope": "character_action_or_dialogue",
        "instructions": [
            "Compare the character state, motivation, relationship pressure, and voice profile before editing.",
            "Rewrite the action/dialogue so the choice follows current desire, fear, wound, or constraint.",
            "Show the motivation through behavior or subtext rather than explanation.",
        ],
        "re_review_focus": ["character motivation", "voice consistency", "relationship state"],
        "risk_controls": ["character_state_check", "no_personality_reset", "re_review_required"],
    },
    {
        "strategy_id": "restore_foreshadow_payoff",
        "strategy_name": "Restore foreshadow and payoff chain",
        "issue_types": {"foreshadowing_drop"},
        "keywords": {"foreshadow", "payoff", "伏笔", "回收"},
        "patch_scope": "foreshadow_or_payoff_beat",
        "instructions": [
            "Identify the missing setup, reminder, or payoff from the foreshadow ledger.",
            "Repair the beat without revealing more than the chapter plan allows.",
            "Update the payoff evidence for later longform recap.",
        ],
        "re_review_focus": ["foreshadow chain", "payoff timing", "information release"],
        "risk_controls": ["info_release_check", "ledger_update_required", "re_review_required"],
    },
    {
        "strategy_id": "restore_reader_promise_payoff",
        "strategy_name": "Restore reader promise payoff",
        "issue_types": {"reader_promise_drop"},
        "keywords": {"reader promise", "promise", "payoff", "承诺", "回收", "悬念", "断裂"},
        "patch_scope": "promise_payoff_or_reminder_beat",
        "instructions": [
            "Restore the promised question, debt, clue, threat, or emotional contract as an observable story beat.",
            "Either pay it off, reschedule it with explicit new pressure, or add a reminder that changes reader expectation.",
            "Update the reader promise ledger and send the revised draft through re-review before continuing production.",
        ],
        "re_review_focus": ["promise visible", "payoff or reschedule credible", "no new continuity contradiction"],
        "risk_controls": ["ledger_update_required", "bounded_story_patch", "re_review_required"],
    },
    {
        "strategy_id": "raise_chapter_economy",
        "strategy_name": "Raise chapter economy",
        "issue_types": {"chapter_economy_gap"},
        "keywords": {"chapter economy", "pleasure", "reward", "water", "watery", "爽点", "水文", "场景价值"},
        "patch_scope": "low_value_scene_or_payoff_chain",
        "instructions": [
            "Add or strengthen a visible reward, cost, reversal, or agency beat already supported by the chapter blueprint.",
            "Remove filler explanation that does not change plot, risk, relationship, information, or emotional state.",
            "Avoid repeating the same payoff marker from recent chapters unless the repetition escalates stakes or cost.",
        ],
        "re_review_focus": ["scene value", "pleasure/cost cadence", "water risk reduced", "no canon regression"],
        "risk_controls": ["chapter_economy_gate_required", "bounded_scene_patch", "re_review_required"],
    },
    {
        "strategy_id": "restore_character_charm_pressure",
        "strategy_name": "Restore character charm and antagonist pressure",
        "issue_types": {"protagonist_charm_drop", "antagonist_pressure_drop"},
        "keywords": {"agency", "charm", "antagonist", "villain", "pressure", "主角", "反派", "压力", "主动性"},
        "patch_scope": "character_action_or_opposition_beat",
        "instructions": [
            "Give the protagonist a visible choice, competent action, or costly value expression instead of passive observation.",
            "Make the antagonist or proxy pressure change the scene state through a move, threat, constraint, or cost.",
            "Keep the repair aligned with current character state, villain operation evidence, and canon constraints.",
        ],
        "re_review_focus": ["protagonist agency", "character charm", "antagonist pressure", "no canon regression"],
        "risk_controls": ["character_state_check", "villain_operation_check", "bounded_scene_patch", "re_review_required"],
    },
    {
        "strategy_id": "style_policy_rewrite",
        "strategy_name": "Rewrite under style policy",
        "issue_types": {"style_drift"},
        "keywords": {"style", "drift", "voice", "风格"},
        "patch_scope": "style_drift_span",
        "instructions": [
            "Use the style profile policy, not raw sample text, to rewrite the drifted span.",
            "Keep rights isolation intact and do not import sample wording into draft prose.",
            "Run style drift gate after the edit.",
        ],
        "re_review_focus": ["style drift reduced", "rights isolation preserved", "no copied sample phrasing"],
        "risk_controls": ["style_gate_required", "source_isolation", "no_raw_sample_text"],
    },
    {
        "strategy_id": "genre_promise_repair",
        "strategy_name": "Repair genre promise delivery",
        "issue_types": {"genre_risk"},
        "keywords": {"genre", "promise", "reader promise", "爽点", "题材"},
        "patch_scope": "genre_promise_beat",
        "instructions": [
            "Repair the beat against the active Genre Strategy Pack and reader promise.",
            "Make the required genre signal visible through action, conflict, reward, or threat.",
            "Avoid adding generic trope decoration that does not affect the scene.",
        ],
        "re_review_focus": ["genre promise", "reader expectation", "platform fit"],
        "risk_controls": ["genre_gate_required", "trope_fatigue_check", "re_review_required"],
    },
    {
        "strategy_id": "source_isolation_rewrite",
        "strategy_name": "Remove source leakage",
        "issue_types": {"source_leakage", "mkaos_conflict"},
        "keywords": {"source", "leakage", "raw_text", "copy", "copyright", "版权"},
        "patch_scope": "source_risk_span",
        "instructions": [
            "Remove leaked source expression and replace it with project-owned prose or abstracted structure.",
            "Keep source evidence out of the revised draft context.",
            "Run source isolation and originality risk checks before re-review.",
        ],
        "re_review_focus": ["source leakage removed", "originality boundary", "source isolation"],
        "risk_controls": ["source_isolation_gate", "originality_gate", "blocking_until_clean"],
    },
]


def create_review_issue(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    normalized = _normalize_issue_payload(storage, payload)
    existing = _find_existing_issue(storage, normalized)
    if existing:
        path, data = existing
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content.update({key: normalized[key] for key in ["severity", "blocking", "status", "message", "fix_suggestion", "revision_task_candidate"]})
        content["source_issue"] = normalized.get("source_issue", {})
        content["evidence_refs"] = _dedupe([*content.get("evidence_refs", []), *normalized.get("evidence_refs", [])])
        metadata.update({"risk_level": normalized["severity"], "blocking": normalized["blocking"]})
        data["content"] = content
        data["metadata"] = metadata
        data["updated_at"] = utc_now()
        _ensure_valid(data)
        storage.write_json(path, data)
        return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "created": False}
    asset = ReviewIssue(
        id=normalized["issue_id"],
        title=f"{normalized['issue_type']} {normalized['severity']} for {normalized['target_asset_id']}",
        source=normalized["target_asset_id"],
        tags=["review-issue", normalized["issue_type"], normalized["severity"], "blocking" if normalized["blocking"] else "nonblocking"],
        content=normalized,
        metadata={
            "project_id": normalized["project_id"],
            "workspace_path": normalized["workspace_path"],
            "target_asset_id": normalized["target_asset_id"],
            "target_asset_type": normalized["target_asset_type"],
            "review_report_id": normalized["review_report_id"],
            "review_report_path": normalized["review_report_path"],
            "risk_level": normalized["severity"],
            "blocking": normalized["blocking"],
            "asset_status": normalized["status"],
            "source_system": normalized["source_system"],
        },
        references=filter_project_safe_references(
            storage,
            normalized["project_id"],
            _dedupe([
                normalized["target_asset_id"],
                normalized["target_asset_path"],
                normalized["review_report_id"],
                normalized["review_report_path"],
                *normalized["evidence_refs"],
            ]),
        ),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("reviews", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "created": True}


def persist_review_issues_for_report(
    storage: LocalStorage,
    review_path: str | Path,
    *,
    issues: list[dict[str, Any]] | None = None,
    target_asset_path: str | Path | None = None,
) -> dict[str, Any]:
    review_file = resolve_path(storage.root, review_path)
    review = storage.read_json(review_file)
    if not isinstance(review, dict) or review.get("type") != "review_report":
        raise ValueError("review_path must point to a review_report asset")
    metadata = review.get("metadata", {}) if isinstance(review.get("metadata", {}), dict) else {}
    target_asset_id = str(review.get("source") or "")
    target_asset_type = "draft_chapter"
    target_path = str(target_asset_path or "")
    if target_asset_path:
        try:
            target = storage.read_json(resolve_path(storage.root, target_asset_path))
            if isinstance(target, dict):
                target_asset_id = str(target.get("id") or target_asset_id)
                target_asset_type = str(target.get("type") or target_asset_type)
                target_path = _display_path(storage.root, resolve_path(storage.root, target_asset_path))
        except Exception:
            pass
    rows: list[dict[str, Any]] = []
    for issue in issues if issues is not None else review.get("issues", []):
        if not isinstance(issue, dict):
            continue
        rows.append(
            create_review_issue(
                storage,
                {
                    **issue,
                    "project_id": metadata.get("project_id", ""),
                    "workspace_path": metadata.get("workspace_path", ""),
                    "target_asset_id": target_asset_id,
                    "target_asset_type": target_asset_type,
                    "target_asset_path": target_path,
                    "review_report_id": review.get("id", ""),
                    "review_report_path": _display_path(storage.root, review_file),
                    "source_system": issue.get("source_system") or "review.report",
                },
            )
        )
    _attach_issue_summary_to_review(storage, review_file, rows)
    return _issue_summary(rows)


def persist_issue_candidates(storage: LocalStorage, candidates: list[dict[str, Any]], *, source_system: str = "") -> dict[str, Any]:
    rows = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        rows.append(create_review_issue(storage, {**candidate, "source_system": candidate.get("source_system") or source_system or "review.issue_candidate"}))
    return _issue_summary(rows)


def list_review_issues(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    target_asset_id: str | None = None,
    status: str | None = None,
    blocking: bool | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("reviews")):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "review_issue":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id") or content.get("project_id") or "") != project_id:
            continue
        if target_asset_id and str(content.get("target_asset_id") or "") != target_asset_id:
            continue
        if status and str(content.get("status") or "") != status:
            continue
        if blocking is not None and bool(content.get("blocking")) is not blocking:
            continue
        rows.append(_row(storage, path, data))
    return rows


def blocking_review_issues(storage: LocalStorage, *, target_asset_id: str, project_id: str | None = None, related_asset_ids: list[str] | None = None) -> list[dict[str, Any]]:
    ids = {str(target_asset_id or "").strip(), *[str(item).strip() for item in related_asset_ids or [] if str(item).strip()]}
    ids.discard("")
    return [
        row
        for row in list_review_issues(storage, project_id=project_id, blocking=True, limit=500)
        if str(row.get("content", {}).get("status") or "open") in ACTIVE_STATUSES and str(row.get("content", {}).get("target_asset_id") or "") in ids
    ]


def assert_no_blocking_review_issues(
    storage: LocalStorage,
    *,
    target_asset_id: str,
    project_id: str | None = None,
    related_asset_ids: list[str] | None = None,
    gate: str = "gate",
) -> None:
    blocking = blocking_review_issues(storage, target_asset_id=target_asset_id, project_id=project_id, related_asset_ids=related_asset_ids)
    if blocking:
        messages = [str(row.get("content", {}).get("message") or row.get("title") or row.get("id")) for row in blocking[:5]]
        raise ValueError(f"{gate} blocked by {len(blocking)} ReviewIssue(s): {'; '.join(messages)}")


def review_issues_to_gate_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        issue_type = str(content.get("issue_type") or "review_issue")
        result.append(
            {
                "issue_id": content.get("issue_id", row.get("id", "")),
                "issue_type": issue_type,
                "dimension": str(content.get("dimension") or issue_type),
                "severity": content.get("severity", "high"),
                "blocking": bool(content.get("blocking", True)),
                "message": content.get("message", ""),
                "recommendation": content.get("fix_suggestion", ""),
                "source_system": "review_issue",
                "review_issue_path": row.get("path", ""),
            }
        )
    return result


def revision_strategy_for_issue(issue: dict[str, Any]) -> dict[str, Any]:
    content = issue.get("content", issue) if isinstance(issue.get("content", issue), dict) else {}
    issue_type = _issue_type(content)
    signal = _issue_signal(content)
    rule = next((item for item in REVISION_STRATEGY_RULES if _strategy_matches(item, issue_type, signal)), REVISION_STRATEGY_DEFAULT)
    strategy = {
        "strategy_id": rule["strategy_id"],
        "strategy_name": rule["strategy_name"],
        "issue_type": issue_type,
        "patch_scope": rule["patch_scope"],
        "instructions": list(rule["instructions"]),
        "required_inputs": ["source_draft", "review_issue", "context_bundle", "canon_state"],
        "required_output_evidence": list(REVISION_EVIDENCE_CHAIN),
        "re_review_required": True,
        "re_review_focus": list(rule["re_review_focus"]),
        "quality_gate_required": True,
        "risk_controls": list(rule["risk_controls"]),
        "selection_signal": signal[:500],
    }
    return strategy


def review_issue_to_revision_task_candidate(issue: dict[str, Any]) -> dict[str, Any]:
    content = issue.get("content", issue) if isinstance(issue.get("content", issue), dict) else {}
    strategy = revision_strategy_for_issue({"content": content})
    return {
        "revision_task_type": "fix_review_issue",
        "source_issue_id": content.get("issue_id", ""),
        "target_asset_id": content.get("target_asset_id", ""),
        "target_asset_path": content.get("target_asset_path", ""),
        "issue_type": strategy["issue_type"],
        "severity": content.get("severity", ""),
        "instructions": content.get("fix_suggestion") or content.get("message", ""),
        "blocking": bool(content.get("blocking", False)),
        "revision_strategy_id": strategy["strategy_id"],
        "revision_strategy": strategy,
        "required_output_evidence": strategy["required_output_evidence"],
        "re_review_required": strategy["re_review_required"],
        "re_review_focus": strategy["re_review_focus"],
        "quality_gate_required": strategy["quality_gate_required"],
    }


def update_review_issue_status(storage: LocalStorage, issue_ref: str | Path, *, status: str, note: str = "") -> dict[str, Any]:
    if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
        raise ValueError("invalid review issue status")
    path, data = _find_review_issue(storage, issue_ref)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content["status"] = status
    content["operator_note"] = note
    content["status_updated_at"] = utc_now()
    metadata["asset_status"] = status
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _normalize_issue_payload(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    issue_type = _issue_type(payload)
    severity = _severity(payload.get("severity"))
    blocking = bool(payload.get("blocking", False)) or severity == "critical" or (severity == "high" and issue_type in HIGH_BLOCKING_TYPES)
    status = str(payload.get("status") or "open")
    status = status if status in ACTIVE_STATUSES | TERMINAL_STATUSES else "open"
    message = str(payload.get("message") or payload.get("summary") or payload.get("description") or "Review issue requires attention").strip()
    target_asset_id = str(payload.get("target_asset_id") or payload.get("asset_id") or "").strip()
    target_asset_type = str(payload.get("target_asset_type") or payload.get("asset_type") or "artifact").strip()
    target_asset_path = str(payload.get("target_asset_path") or payload.get("asset_path") or "").strip()
    project_id = str(payload.get("project_id") or "local-system").strip()
    workspace_path = str(payload.get("workspace_path") or "").strip()
    if target_asset_path:
        try:
            data = storage.read_json(resolve_path(storage.root, target_asset_path))
            if isinstance(data, dict):
                target_asset_id = str(data.get("id") or target_asset_id)
                target_asset_type = str(data.get("type") or target_asset_type)
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
                project_id = str(payload.get("project_id") or metadata.get("project_id") or project_id)
                workspace_path = str(payload.get("workspace_path") or metadata.get("workspace_path") or workspace_path)
        except Exception:
            pass
    source_system = str(payload.get("source_system") or _source_system(payload)).strip()
    evidence_refs = _strings(payload.get("evidence_refs")) or _strings(payload.get("references"))
    issue_id = str(payload.get("issue_id") or make_id("review_issue", _issue_key(issue_type, target_asset_id, source_system, message))).strip()
    normalized = {
        "issue_id": issue_id,
        "issue_type": issue_type,
        "severity": severity,
        "blocking": blocking,
        "status": status,
        "target_asset_id": target_asset_id or "unknown-target",
        "target_asset_type": target_asset_type,
        "target_asset_path": target_asset_path,
        "source_system": source_system,
        "source_issue_id": str(payload.get("source_issue_id") or payload.get("rule_id") or payload.get("id") or ""),
        "review_report_id": str(payload.get("review_report_id") or ""),
        "review_report_path": str(payload.get("review_report_path") or ""),
        "project_id": project_id or "local-system",
        "workspace_path": workspace_path,
        "message": message,
        "fix_suggestion": str(payload.get("fix_suggestion") or payload.get("recommendation") or ""),
        "evidence_refs": evidence_refs,
        "source_issue": payload.get("source_issue") if isinstance(payload.get("source_issue"), dict) else payload,
        "created_at": str(payload.get("created_at") or utc_now()),
        "revision_task_id": str(payload.get("revision_task_id") or ""),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    normalized["revision_task_candidate"] = review_issue_to_revision_task_candidate({"content": normalized})
    return normalized


def _issue_type(payload: dict[str, Any]) -> str:
    value = str(payload.get("issue_type") or payload.get("dimension") or payload.get("rule_type") or "").strip()
    if value in ISSUE_TYPES:
        return value
    text = " ".join(str(payload.get(key) or "") for key in ["rule_name", "rule_id", "message", "dimension"]).lower()
    if "canon" in text:
        return "canon_conflict"
    if "source" in text or "raw_text" in text:
        return "source_leakage"
    if "context" in text and "budget" in text:
        return "context_budget_overflow"
    if "character" in text:
        return "character_drift"
    if "foreshadow" in text or "伏笔" in text:
        return "foreshadowing_drop"
    if "repetition" in text or "重复" in text:
        return "repetition"
    if "style" in text or "ai" in text:
        return "ai_style"
    if "pacing" in text or "节奏" in text:
        return "pacing_collapse"
    if "logic" in text or "因果" in text:
        return "plot_logic_gap"
    if str(payload.get("source_system") or "").startswith("mkaos") or "知识" in text or "百科" in text:
        return "mkaos_conflict"
    return "plot_logic_gap"


def _issue_signal(payload: dict[str, Any]) -> str:
    values = []
    for key in [
        "issue_type",
        "dimension",
        "rule_type",
        "rule_id",
        "rule_name",
        "source_system",
        "message",
        "summary",
        "description",
        "fix_suggestion",
        "recommendation",
        "source_issue_id",
    ]:
        value = payload.get(key)
        if value is not None:
            values.append(str(value))
    source_issue = payload.get("source_issue")
    if isinstance(source_issue, dict):
        for key in ["dimension", "rule_id", "rule_name", "message", "recommendation"]:
            value = source_issue.get(key)
            if value is not None:
                values.append(str(value))
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in ["dimension", "rule_id", "source_system"]:
            value = metadata.get(key)
            if value is not None:
                values.append(str(value))
    return " ".join(values).lower()


def _strategy_matches(rule: dict[str, Any], issue_type: str, signal: str) -> bool:
    issue_types = rule.get("issue_types", set())
    if issue_type not in issue_types:
        return False
    keywords = rule.get("keywords", set())
    if not keywords:
        return True
    return any(str(keyword).lower() in signal for keyword in keywords)


def _source_system(payload: dict[str, Any]) -> str:
    if payload.get("rule_id") or payload.get("rule_name"):
        return "mkaos.validation"
    return "review.report"


def _severity(value: Any) -> str:
    normalized = str(value or "medium").strip().lower()
    if normalized == "blocking":
        return "critical"
    return normalized if normalized in SEVERITIES else "medium"


def _issue_key(issue_type: str, target_asset_id: str, source_system: str, message: str) -> str:
    digest = hashlib.sha256(f"{issue_type}|{target_asset_id}|{source_system}|{message}".encode("utf-8")).hexdigest()[:16]
    return f"{issue_type}-{target_asset_id}-{digest}"


def _find_existing_issue(storage: LocalStorage, normalized: dict[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    for path in reversed(storage.list_json("reviews")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "review_issue":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("issue_id") or "") == normalized["issue_id"]:
            return path, data
    return None


def _find_review_issue(storage: LocalStorage, issue_ref: str | Path) -> tuple[Path, dict[str, Any]]:
    value = str(issue_ref)
    if "/" in value or value.endswith(".json"):
        path = resolve_path(storage.root, value)
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == "review_issue":
            return path, data
    for path in reversed(storage.list_json("reviews")):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == "review_issue" and value in {str(data.get("id", "")), str(data.get("content", {}).get("issue_id", ""))}:
            return path, data
    raise FileNotFoundError(f"review issue not found: {issue_ref}")


def _attach_issue_summary_to_review(storage: LocalStorage, review_file: Path, rows: list[dict[str, Any]]) -> None:
    review = storage.read_json(review_file)
    if not isinstance(review, dict):
        return
    metadata = review.get("metadata", {}) if isinstance(review.get("metadata", {}), dict) else {}
    content = review.get("content", {}) if isinstance(review.get("content", {}), dict) else {}
    summary = _issue_summary(rows)
    metadata["review_issue_ids"] = summary["issue_ids"]
    metadata["review_issue_paths"] = summary["issue_paths"]
    metadata["blocking_review_issue_count"] = summary["blocking_count"]
    content["review_issue_summary"] = summary
    review["metadata"] = metadata
    review["content"] = content
    review["updated_at"] = utc_now()
    storage.write_json(review_file, review)


def _issue_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    assets = [row.get("asset", {}) if isinstance(row.get("asset", {}), dict) else row for row in rows]
    contents = [asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {} for asset in assets]
    paths = [str(row.get("path", "")) for row in rows if str(row.get("path", "")).strip()]
    return {
        "issue_count": len(rows),
        "blocking_count": len([content for content in contents if content.get("blocking") and content.get("status", "open") in ACTIVE_STATUSES]),
        "issue_ids": [str(content.get("issue_id", "")) for content in contents if str(content.get("issue_id", "")).strip()],
        "issue_paths": paths,
    }


def _row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title", ""),
        "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {},
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
        "asset": data,
    }


def _ensure_valid(data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _display_path(root: Path, path: str | Path) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)
