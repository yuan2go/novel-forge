from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


_RELATIONSHIP_KINDS = frozenset({"relationship_state", "character_relationship"})
_CHOICE_KINDS = frozenset(
    {"timeline_event", "character_state", "character_belief", "character_arc"}
)
_CONSEQUENCE_KINDS = frozenset(
    {"consequence_state", "resource_state", "power_state", "world_state"}
)


def build_recent_trail_entry(
    *,
    accepted_boundary: Mapping[str, Any],
    chapter_outcome: Mapping[str, Any],
) -> dict[str, Any]:

    chapter = int(accepted_boundary.get("chapter_number") or 0)
    outcome_chapter = int(chapter_outcome.get("chapter_number") or 0)
    if chapter <= 0 or chapter != outcome_chapter:
        raise ValueError("Recent Trail requires one matching accepted chapter boundary")
    outcome_version = str(
        accepted_boundary.get("chapter_outcome_asset_version_id") or ""
    )
    acceptance_operation = str(accepted_boundary.get("acceptance_operation_id") or "")
    if not outcome_version or not acceptance_operation:
        raise ValueError("Recent Trail requires immutable acceptance identities")

    events = [
        dict(item)
        for item in chapter_outcome.get("state_events") or ()
        if isinstance(item, Mapping)
    ]
    scenes = [
        dict(item)
        for item in chapter_outcome.get("scene_outcomes") or ()
        if isinstance(item, Mapping)
    ]
    reader = [
        dict(item)
        for item in chapter_outcome.get("reader_state_observations") or ()
        if isinstance(item, Mapping)
    ]
    relationship = _event_summaries(events, _RELATIONSHIP_KINDS)
    choices = _event_summaries(events, _CHOICE_KINDS)
    consequences = list(
        dict.fromkeys(
            [
                *_event_summaries(events, _CONSEQUENCE_KINDS),
                *(
                    str(value)
                    for arc in chapter_outcome.get("arc_evidence") or ()
                    if isinstance(arc, Mapping)
                    for value in arc.get("actual_consequences") or ()
                    if str(value)
                ),
            ]
        )
    )
    observed = _merge_observations(reader, scenes)
    arc_movements = [
        {
            "arc_plan_version_id": str(item.get("arc_plan_version_id") or ""),
            "observation_status": str(item.get("observation_status") or "UNKNOWN"),
            "contribution_kind": str(item.get("contribution_kind") or "UNKNOWN"),
            "progress_units": int(item.get("progress_units") or 0),
            "effect_dimensions": list(item.get("effect_dimensions") or ()),
        }
        for item in chapter_outcome.get("arc_evidence") or ()
        if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
    ]
    footprint_values = [
        str(value)
        for item in (*reader, *scenes)
        for key in ("repetition_key", "pattern_key", "scene_type", "chapter_type")
        if (value := item.get(key)) not in {None, ""}
    ]
    payload: dict[str, Any] = {
        "type": "RecentTrailEntry",
        "contract_version": "recent-trail-entry-v1",
        "authority": "NONE_PROJECTION_ONLY",
        "source_authority": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
        "accepted_boundary": dict(accepted_boundary),
        "chapter_number": chapter,
        "title": str(observed.get("title") or ""),
        "opening_pattern": str(observed.get("opening_pattern") or "UNOBSERVED"),
        "ending_pattern": str(observed.get("ending_pattern") or "UNOBSERVED"),
        "mood": str(observed.get("mood") or "UNOBSERVED"),
        "pacing": str(observed.get("pacing") or "UNOBSERVED"),
        "chapter_type": str(observed.get("chapter_type") or "UNOBSERVED"),
        "scene_rhythm": [
            {
                "scene_id": str(item.get("scene_id") or ""),
                "scene_type": str(item.get("scene_type") or "UNOBSERVED"),
                "turn": str(item.get("turn") or item.get("outcome") or ""),
            }
            for item in scenes
        ],
        "relationship_movement": relationship,
        "major_choices": choices,
        "accepted_consequences": consequences,
        "arc_movement": arc_movements,
        "repetition_footprint": list(dict.fromkeys(footprint_values)),
        "unobserved_fields_are_not_inferred": True,
        "source_asset_version_ids": list(
            dict.fromkeys(
                value
                for value in (
                    outcome_version,
                    str(chapter_outcome.get("accepted_draft_asset_version_id") or ""),
                )
                if value
            )
        ),
    }
    payload["projection_hash"] = _projection_hash(payload)
    return payload


def build_hook_debt_projection(
    *,
    accepted_boundary: Mapping[str, Any],
    obligation_states: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:

    chapter = int(accepted_boundary.get("chapter_number") or 0)
    story_state_version = str(
        accepted_boundary.get("story_state_asset_version_id") or ""
    )
    acceptance_operation = str(accepted_boundary.get("acceptance_operation_id") or "")
    if chapter <= 0 or not story_state_version or not acceptance_operation:
        raise ValueError("Hook Debt requires a complete accepted boundary")
    items: list[dict[str, Any]] = []
    for entry_value in obligation_states:
        entry = dict(entry_value)
        state = dict(entry.get("state") or {})
        obligation_id = str(state.get("obligation_id") or entry.get("entity_key") or "")
        if not obligation_id:
            continue
        evaluation = dict(state.get("accepted_evaluation") or {})
        history_chapters = [
            int(item.get("chapter") or 0)
            for item in state.get("development_history") or ()
            if isinstance(item, Mapping) and int(item.get("chapter") or 0) > 0
        ]
        opened = int(state.get("opened_chapter") or 0)
        last_advanced = max([opened, *history_chapters], default=0)
        lifecycle = str(evaluation.get("lifecycle") or state.get("status") or "UNKNOWN")
        priority = str(state.get("priority") or "NORMAL").upper()
        urgency = (
            "CRITICAL"
            if lifecycle in {"OVERDUE", "VIOLATED"}
            else "HIGH"
            if lifecycle in {"DUE", "STALE"} or priority in {"HIGH", "CRITICAL"}
            else "NORMAL"
        )
        target_window = dict(state.get("target_window") or {})
        items.append(
            {
                "obligation_id": obligation_id,
                "obligation_type": str(state.get("obligation_type") or "UNKNOWN"),
                "setup": str(state.get("setup") or state.get("setup_summary") or ""),
                "promise": str(
                    state.get("promise") or state.get("reader_promise") or ""
                ),
                "foreshadow": str(state.get("foreshadow") or ""),
                "unresolved_question": str(state.get("unresolved_question") or ""),
                "expected_payoff": str(state.get("expected_payoff") or ""),
                "first_introduced_chapter": opened,
                "last_advanced_chapter": last_advanced,
                "age_chapters": max(0, chapter - opened) if opened else 0,
                "silence_chapters": max(0, chapter - last_advanced)
                if last_advanced
                else 0,
                "target_window": target_window,
                "urgency": urgency,
                "dependency_state": str(
                    evaluation.get("dependency_state") or "UNKNOWN"
                ),
                "dependency_ids": list(state.get("dependencies") or ()),
                "linked_arc_ids": list(state.get("linked_arc_ids") or ()),
                "reader_promise": str(state.get("reader_promise") or ""),
                "status": lifecycle,
                "accepted_evaluation": evaluation,
                "source_event_id": str(entry.get("source_event_id") or ""),
            }
        )
    status_order = {
        "VIOLATED": 0,
        "OVERDUE": 1,
        "STALE": 2,
        "DUE": 3,
        "OPEN": 4,
        "UNKNOWN": 5,
        "FULFILLED": 6,
    }
    items.sort(
        key=lambda item: (
            status_order.get(str(item["status"]), 5),
            -int(item["silence_chapters"]),
            str(item["obligation_id"]),
        )
    )
    payload: dict[str, Any] = {
        "type": "HookDebtProjection",
        "contract_version": "hook-debt-projection-v1",
        "authority": "NONE_PROJECTION_ONLY",
        "source_authority": "ACCEPTED_NARRATIVE_OBLIGATION_STATE",
        "accepted_boundary": dict(accepted_boundary),
        "items": items,
        "summary": {
            status: sum(item["status"] == status for item in items)
            for status in (
                "OPEN",
                "DUE",
                "OVERDUE",
                "STALE",
                "VIOLATED",
                "FULFILLED",
                "UNKNOWN",
            )
        },
        "source_asset_version_ids": [story_state_version],
    }
    payload["projection_hash"] = _projection_hash(payload)
    return payload


def build_chapter_transaction_workspace(
    *,
    chapter_run: Mapping[str, Any],
    accepted_evidence: Mapping[str, Any] | None,
    followup_evidence: Iterable[Mapping[str, Any]] = (),
    recent_trail: Mapping[str, Any] | None = None,
    hook_debt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:

    outputs = [dict(item) for item in chapter_run.get("outputs") or ()]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in outputs:
        by_type.setdefault(str(item.get("asset_type") or "unknown"), []).append(
            _asset_reference(item)
        )
    plan = _latest_content(outputs, "chapter_plan")
    intent = _latest_content(outputs, "chapter_execution_intent")
    mission = dict(intent.get("chapter_mission") or intent.get("mission") or {})
    context = _latest_content(outputs, "context_bundle")
    comparison = _latest_content(outputs, "candidate_comparison")
    quality = _latest_content(outputs, "quality_score_report")
    canon = _latest_content(outputs, "canon_patch")
    accepted = dict(accepted_evidence or {})
    recent = dict(recent_trail or {})
    debt = dict(hook_debt or {})
    manifest = dict(context.get("context_manifest") or {})
    payload = {
        "type": "ChapterTransactionWorkspace",
        "contract_version": "chapter-transaction-workspace-v1",
        "authority": "NONE_READ_MODEL",
        "root_operation_id": str(chapter_run.get("root_operation_id") or ""),
        "project_id": str(chapter_run.get("project_id") or ""),
        "workspace_id": str(chapter_run.get("workspace_id") or ""),
        "chapter_number": int((chapter_run.get("command") or {}).get("chapter") or 0),
        "run_status": str(chapter_run.get("status") or ""),
        "trace_id": str(chapter_run.get("trace_id") or ""),
        "author_brief": {
            "why_this_chapter_exists": str(
                mission.get("why_this_chapter_exists")
                or plan.get("chapter_purpose")
                or plan.get("objective")
                or ""
            ),
            "what_must_change": list(
                mission.get("required_outcomes") or plan.get("required_outcomes") or ()
            ),
            "active_arc_contributions": list(
                mission.get("arc_contributions")
                or mission.get("required_arc_contributions")
                or plan.get("required_arc_contributions")
                or ()
            ),
        },
        "protected_facts": list(manifest.get("protected_context") or ()),
        "recent_trail": recent,
        "recent_repetition_risk": sorted(
            {
                str(key)
                for entry in recent.get("entries") or ()
                if isinstance(entry, Mapping)
                for key in entry.get("repetition_footprint") or ()
                if str(key)
            }
        ),
        "hook_debt": debt,
        "active_hook_debt": [
            dict(item)
            for item in debt.get("items") or ()
            if isinstance(item, Mapping)
            and str(item.get("status") or "")
            not in {"FULFILLED", "RESOLVED", "CANCELLED"}
        ],
        "context_inspector": {
            "context_bundle_asset_versions": by_type.get("context_bundle", []),
            "selected": list(manifest.get("selected_inputs") or ()),
            "omitted": list(manifest.get("rejected_inputs") or ()),
            "compression": list(manifest.get("compression_trace") or ()),
            "token_budget": dict(manifest.get("token_budget") or {}),
        },
        "artifacts": {
            "plan": by_type.get("chapter_plan", []),
            "intent": by_type.get("chapter_execution_intent", []),
            "memo": by_type.get("chapter_memo", []),
            "retrieval": by_type.get("retrieval_result", []),
            "context": by_type.get("context_bundle", []),
            "draft_candidates": [
                *by_type.get("draft_chapter", []),
                *by_type.get("draft_version", []),
                *by_type.get("best_draft_candidate", []),
            ],
            "reviews": [
                *by_type.get("review_report", []),
                *by_type.get("re_review_report", []),
            ],
            "candidate_comparison": by_type.get("candidate_comparison", []),
            "best_candidate": by_type.get("best_candidate_snapshot", []),
            "canon_and_state_proposals": [
                *by_type.get("canon_extraction", []),
                *by_type.get("canon_change_proposal", []),
                *by_type.get("canon_patch", []),
            ],
            "quality": [
                *by_type.get("chapter_quality_group_report", []),
                *by_type.get("quality_score_report", []),
                *by_type.get("publish_gate_report", []),
                *by_type.get("final_release_gate_report", []),
            ],
        },
        "candidate_decision": {
            "selected_asset_version_id": str(
                comparison.get("selected_asset_version_id") or ""
            ),
            "stop_reason": str(comparison.get("stop_reason") or ""),
            "net_improvement": comparison.get("net_improvement"),
            "minimum_net_improvement": comparison.get("minimum_net_improvement"),
            "new_blocker_codes": list(comparison.get("new_blocker_codes") or ()),
            "resolved_blocker_codes": list(
                comparison.get("resolved_blocker_codes") or ()
            ),
        },
        "quality_decision": {
            "accepted_candidate": quality.get("accepted_candidate"),
            "decision": str(quality.get("decision") or quality.get("gate") or ""),
            "required_actions": list(quality.get("required_actions") or ()),
        },
        "canon_state_change": {
            "canon_patch_asset_versions": by_type.get("canon_patch", []),
            "state_change_kinds": sorted(
                str(key) for key in (canon.get("state_changes") or {})
            ),
            "acceptance": accepted,
        },
        "stale_future_impact": [dict(item) for item in followup_evidence],
        "operations": list(chapter_run.get("operations") or ()),
        "model_effects": list(chapter_run.get("model_effects") or ()),
        "immutable_asset_references_only": True,
        "activation_permissions": [],
    }
    payload["workspace_projection_hash"] = _projection_hash(payload)
    return payload


def _event_summaries(
    events: Iterable[Mapping[str, Any]], kinds: frozenset[str]
) -> list[str]:
    values: list[str] = []
    for event in events:
        if str(event.get("state_kind") or "") not in kinds:
            continue
        mutation = dict(event.get("mutation") or {})
        payload = dict(mutation.get("payload") or {})
        summary = next(
            (
                str(payload[key])
                for key in ("summary", "choice", "consequence", "movement", "status")
                if payload.get(key) not in {None, ""}
            ),
            str((event.get("identity") or {}).get("entity_key") or ""),
        )
        if summary:
            values.append(summary)
    return list(dict.fromkeys(values))


def _merge_observations(*groups: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    allowed = {
        "title",
        "opening_pattern",
        "ending_pattern",
        "mood",
        "pacing",
        "chapter_type",
    }
    for group in groups:
        for value in group:
            for key in allowed:
                if key not in result and value.get(key) not in {None, ""}:
                    result[key] = value[key]
    return result


def _latest_content(
    outputs: Iterable[Mapping[str, Any]], asset_type: str
) -> dict[str, Any]:
    matches = [
        dict(item.get("content") or {})
        for item in outputs
        if str(item.get("asset_type") or "") == asset_type
    ]
    return matches[-1] if matches else {}


def _asset_reference(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "asset_type",
            "asset_id",
            "asset_version_id",
            "content_hash",
            "output_key",
            "role",
            "lifecycle",
            "eligibility",
            "governance",
            "operation_id",
        )
        if item.get(key) not in {None, ""}
    }


def _projection_hash(payload: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


__all__ = [
    "build_chapter_transaction_workspace",
    "build_hook_debt_projection",
    "build_recent_trail_entry",
]
