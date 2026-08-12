"""Deterministic instrumentation for Narrative Proof Engineering.

Measurements expose observable gaps from immutable runtime artifacts.  They do
not promote a project, provider, reader model, or long-form capability.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


_TERMINAL_OBLIGATION_STATUSES = {"FULFILLED", "CANCELLED"}


def measure_narrative_runtime(
    *,
    story_state: Mapping[str, Any],
    context_bundle: Mapping[str, Any],
    planning_candidate: Mapping[str, Any] | None = None,
    quality_decision: Mapping[str, Any] | None = None,
    mkaos_usage_records: Iterable[Mapping[str, Any]] = (),
    provider_usage_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a reproducible observation without claiming proof qualification."""
    manifest = dict(context_bundle.get("context_manifest") or {})
    position = dict(manifest.get("narrative_position") or {})
    chapter = int(
        position.get("chapter")
        or story_state.get("accepted_through_chapter")
        or 0
    )
    current = dict(story_state.get("current_state") or {})
    if not current:
        for segment in context_bundle.get("context_segments") or []:
            for fact in segment.get("structured_facts") or []:
                kind = str(fact.get("state_kind") or "")
                if kind:
                    current.setdefault(kind, []).append(dict(fact))
    entries = [
        entry
        for values in current.values()
        for entry in values
        if isinstance(entry, Mapping)
    ]
    temporal_contradictions = [
        entry
        for entry in entries
        if int(entry.get("effective_from_chapter") or 0) > chapter
        or (
            int(entry.get("effective_to_chapter") or 0) > 0
            and int(entry.get("effective_to_chapter") or 0)
            < int(entry.get("effective_from_chapter") or 0)
        )
    ]
    obligation_entries = [
        entry
        for entry in current.get("narrative_obligation") or []
        if isinstance(entry, Mapping)
    ]
    unresolved = [
        entry
        for entry in obligation_entries
        if str((entry.get("state") or {}).get("status") or "").upper()
        not in _TERMINAL_OBLIGATION_STATUSES
    ]
    overdue = [
        entry
        for entry in unresolved
        if str((entry.get("state") or {}).get("target_window", {}).get("status"))
        == "SCHEDULED"
        and int(
            (entry.get("state") or {})
            .get("target_window", {})
            .get("to_chapter")
            or 0
        )
        < chapter
    ]
    terminal_without_payoff = [
        entry
        for entry in obligation_entries
        if str((entry.get("state") or {}).get("status") or "").upper()
        == "FULFILLED"
        and not dict((entry.get("state") or {}).get("payoff_evidence") or {})
    ]
    selected_inputs = list(manifest.get("selected_inputs") or [])
    irrelevant = [
        item
        for item in selected_inputs
        if float(item.get("relevance_score") or 0.0) < 0.25
        and item.get("inclusion_reason") != "REQUIRED_BY_CONTEXT_PROFILE"
    ]
    future_knowledge = [
        fact
        for segment in context_bundle.get("context_segments") or []
        for fact in segment.get("structured_facts") or []
        if str(fact.get("state_kind") or "") == "character_knowledge"
        and int(fact.get("effective_from_chapter") or 0) > chapter
    ]
    long_distance_recall = [
        fact
        for segment in context_bundle.get("context_segments") or []
        for fact in segment.get("structured_facts") or []
        if int(fact.get("source_chapter") or chapter) > 0
        and chapter - int(fact.get("source_chapter") or chapter) >= 20
    ]
    quality = dict(quality_decision or {})
    actions = list(quality.get("required_actions") or [])
    open_actions = [item for item in actions if item.get("status", "OPEN") != "CLOSED"]
    issues = [
        item.get("issue") or item
        for item in actions
        if isinstance(item, Mapping)
    ]
    planning = dict(planning_candidate or {})
    envelope = dict(planning.get("constraint_envelope") or {})
    planning_drift = list(planning.get("constraint_violations") or [])
    mkaos_usage = list(mkaos_usage_records)
    provider_usage = list(provider_usage_records)
    token_count = sum(int(item.get("token_count") or 0) for item in provider_usage)
    cost = sum(float(item.get("cost") or 0.0) for item in provider_usage)
    trace_missing = [
        item for item in provider_usage if not str(item.get("trace_id") or "")
    ]
    canon_issues = [item for item in issues if "CANON" in str(item.get("code") or "")]
    relationship_issues = [
        item for item in issues if "RELATIONSHIP" in str(item.get("code") or "")
    ]
    world_issues = [item for item in issues if "WORLD" in str(item.get("code") or "")]
    return {
        "type": "NarrativeRuntimeMeasurement",
        "contract_version": "narrative-runtime-measurement-v1",
        "chapter": chapter,
        "proof_status": "MEASURED_NOT_QUALIFIED",
        "metrics": {
            "future_knowledge_leakage_count": len(future_knowledge),
            "canon_contradiction_count": len(canon_issues),
            "temporal_state_contradiction_count": len(temporal_contradictions),
            "relationship_inconsistency_count": len(relationship_issues),
            "world_state_inconsistency_count": len(world_issues),
            "obligation_unresolved_count": len(unresolved),
            "obligation_overdue_count": len(overdue),
            "obligation_terminal_without_payoff_count": len(terminal_without_payoff),
            "long_distance_context_recall_count": len(long_distance_recall),
            "context_selected_count": len(selected_inputs),
            "context_irrelevant_count": len(irrelevant),
            "context_precision": (
                round((len(selected_inputs) - len(irrelevant)) / len(selected_inputs), 6)
                if selected_inputs
                else None
            ),
            "planning_constraint_envelope_present": bool(envelope),
            "planning_drift_count": len(planning_drift),
            "revision_or_replan_open_action_count": len(open_actions),
            "mkaos_consumption_count": len(mkaos_usage),
            "provider_call_count": len(provider_usage),
            "provider_token_count": token_count,
            "provider_cost": round(cost, 8),
            "provider_trace_missing_count": len(trace_missing),
        },
        "evidence": {
            "story_state_hash": str(story_state.get("state_hash") or ""),
            "context_digest": str(context_bundle.get("actual_context_digest") or ""),
            "context_replay_input_digest": str(
                (manifest.get("replay") or {}).get("input_digest") or ""
            ),
            "planning_constraint_envelope_digest": str(
                envelope.get("envelope_digest") or ""
            ),
            "mkaos_usage_result_asset_version_ids": sorted(
                {
                    str(item.get("result_asset_version_id") or "")
                    for item in mkaos_usage
                    if str(item.get("result_asset_version_id") or "")
                }
            ),
        },
        "qualification": {
            "longform_proven": False,
            "multibook_proven": False,
            "production_proven": False,
        },
    }


__all__ = ["measure_narrative_runtime"]
