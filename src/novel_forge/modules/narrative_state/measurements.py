"""Deterministic, non-promotional Narrative Proof instrumentation."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


_TERMINAL_OBLIGATION_STATUSES = {"FULFILLED", "CANCELLED"}
_MEASURED = "MEASURED"
_NOT_OBSERVED = "NOT_OBSERVED"
_NOT_AVAILABLE = "NOT_AVAILABLE"
_NOT_APPLICABLE = "NOT_APPLICABLE"


def project_narrative_load(*, story_state: Mapping[str, Any]) -> dict[str, Any]:
    """Project queryable load/debt from accepted Narrative State only."""

    chapter = int(story_state.get("accepted_through_chapter") or 0)
    current = dict(story_state.get("current_state") or {})
    state_observed = "current_state" in story_state
    arcs = [
        entry
        for kind in ("arc_state", "character_arc", "plot_thread")
        for entry in current.get(kind) or ()
        if isinstance(entry, Mapping)
    ]
    active_arcs = [
        entry
        for entry in arcs
        if str((entry.get("state") or {}).get("status") or "ACTIVE").upper()
        not in {"CLOSED", "RESOLVED", "FULFILLED", "CANCELLED"}
    ]
    dormant_ages = [
        max(
            0,
            chapter
            - int(
                (entry.get("state") or {}).get("last_advanced_chapter")
                or entry.get("effective_from_chapter")
                or chapter
            ),
        )
        for entry in active_arcs
    ]
    obligations = [
        entry
        for entry in current.get("narrative_obligation") or ()
        if isinstance(entry, Mapping)
    ]
    open_obligations = [
        entry
        for entry in obligations
        if str((entry.get("state") or {}).get("status") or "").upper()
        not in _TERMINAL_OBLIGATION_STATUSES
    ]
    overdue = [
        entry
        for entry in open_obligations
        if str((entry.get("state") or {}).get("target_window", {}).get("status"))
        == "SCHEDULED"
        and int(
            (entry.get("state") or {}).get("target_window", {}).get("to_chapter") or 0
        )
        < chapter
    ]
    open_obligation_ids = sorted(
        {_obligation_identity(entry) for entry in open_obligations}
    )
    overdue_obligation_ids = sorted({_obligation_identity(entry) for entry in overdue})
    if "" in open_obligation_ids or "" in overdue_obligation_ids:
        raise ValueError(
            "accepted Narrative Obligation state requires a stable obligation identity"
        )
    payoff_congestion = [
        entry
        for entry in open_obligations
        if 0
        < int(
            (entry.get("state") or {}).get("target_window", {}).get("to_chapter") or 0
        )
        <= chapter + 3
    ]
    characters = [
        entry
        for entry in current.get("character_state") or ()
        if isinstance(entry, Mapping)
    ]
    appearance_gaps = [
        max(
            0,
            chapter
            - int(
                (entry.get("state") or {}).get("last_appearance_chapter")
                or entry.get("effective_from_chapter")
                or chapter
            ),
        )
        for entry in characters
    ]
    debt_entries = [
        entry
        for entry in current.get("narrative_debt") or ()
        if isinstance(entry, Mapping)
    ]
    debt_score = sum(
        int((entry.get("state") or {}).get("weight") or 1)
        for entry in debt_entries
        if str((entry.get("state") or {}).get("status") or "OPEN").upper()
        not in {"CLOSED", "RESOLVED", "CANCELLED"}
    )
    metrics = {
        "active_arc_count": len(active_arcs),
        "dormant_arc_max_age": max(dormant_ages, default=0),
        "open_obligation_count": len(open_obligations),
        "overdue_obligation_count": len(overdue),
        "payoff_congestion_count": len(payoff_congestion),
        "character_appearance_max_gap": max(appearance_gaps, default=0),
        "narrative_debt_score": debt_score + len(overdue) * 5,
    }
    return {
        "type": "NarrativeLoadProjection",
        "contract_version": "narrative-load-projection-v2",
        "accepted_through_chapter": chapter,
        "status": _MEASURED if state_observed else _NOT_OBSERVED,
        "metrics": metrics if state_observed else {key: None for key in metrics},
        "open_obligation_ids": open_obligation_ids if state_observed else [],
        "overdue_obligation_ids": overdue_obligation_ids if state_observed else [],
    }


def _obligation_identity(entry: Mapping[str, Any]) -> str:
    state = entry.get("state")
    state_mapping = state if isinstance(state, Mapping) else {}
    identity = str(state_mapping.get("obligation_id") or "")
    if identity:
        return identity
    entity_key = str(entry.get("entity_key") or "")
    if entity_key.startswith("obligation_id="):
        return entity_key.removeprefix("obligation_id=")
    return entity_key


def measure_narrative_runtime(
    *,
    story_state: Mapping[str, Any],
    context_bundle: Mapping[str, Any],
    planning_candidate: Mapping[str, Any] | None = None,
    quality_decision: Mapping[str, Any] | None = None,
    mkaos_usage_records: Iterable[Mapping[str, Any]] | None = None,
    provider_usage_records: Iterable[Mapping[str, Any]] | None = None,
    expected_context_asset_version_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build an observation while preserving zero-versus-missing semantics."""
    manifest = dict(context_bundle.get("context_manifest") or {})
    position = dict(manifest.get("narrative_position") or {})
    chapter = int(
        position.get("chapter") or story_state.get("accepted_through_chapter") or 0
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
    temporal_state_observed = "current_state" in story_state or bool(entries)
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
            (entry.get("state") or {}).get("target_window", {}).get("to_chapter") or 0
        )
        < chapter
    ]
    terminal_without_payoff = [
        entry
        for entry in obligation_entries
        if str((entry.get("state") or {}).get("status") or "").upper() == "FULFILLED"
        and not dict((entry.get("state") or {}).get("payoff_evidence") or {})
    ]

    context_observed = bool(manifest)
    context_segments_observed = "context_segments" in context_bundle
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
    long_distance_selected = [
        fact
        for segment in context_bundle.get("context_segments") or []
        for fact in segment.get("structured_facts") or []
        if int(fact.get("source_chapter") or chapter) > 0
        and chapter - int(fact.get("source_chapter") or chapter) >= 20
    ]
    expected_context = (
        None
        if expected_context_asset_version_ids is None
        else {
            str(item)
            for item in expected_context_asset_version_ids
            if str(item).strip()
        }
    )
    retrieved_context = {
        str(item.get("asset_version_id") or "")
        for item in selected_inputs
        if str(item.get("asset_version_id") or "")
    }
    expected_context_status = (
        _NOT_OBSERVED
        if expected_context is None
        else _NOT_APPLICABLE
        if not expected_context
        else _MEASURED
    )
    context_recall = (
        round(len(expected_context & retrieved_context) / len(expected_context), 6)
        if expected_context
        else None
    )
    context_precision = (
        round(len(expected_context & retrieved_context) / len(retrieved_context), 6)
        if expected_context and retrieved_context
        else None
    )

    quality = dict(quality_decision or {})
    actions = list(quality.get("required_actions") or [])
    open_actions = [item for item in actions if item.get("status", "OPEN") != "CLOSED"]
    issues = [
        item.get("issue") or item for item in actions if isinstance(item, Mapping)
    ]
    planning = dict(planning_candidate or {})
    envelope = dict(planning.get("constraint_envelope") or {})
    planning_drift = list(planning.get("constraint_violations") or [])
    mkaos_usage = None if mkaos_usage_records is None else list(mkaos_usage_records)
    mkaos_available = (
        None
        if mkaos_usage is None
        else all(
            str(item.get("availability") or _MEASURED) == _MEASURED
            for item in mkaos_usage
        )
    )
    provider_usage = (
        None if provider_usage_records is None else list(provider_usage_records)
    )
    token_missing = (
        None
        if provider_usage is None
        else [
            item
            for item in provider_usage
            if item.get("total_tokens", item.get("token_count")) is None
        ]
    )
    cost_missing = (
        None
        if provider_usage is None
        else [
            item
            for item in provider_usage
            if item.get("cost", item.get("amount")) is None
        ]
    )
    token_count = (
        None
        if provider_usage is None or token_missing
        else sum(
            int(item.get("total_tokens", item.get("token_count")))
            for item in provider_usage
        )
    )
    cost = (
        None
        if provider_usage is None or cost_missing
        else sum(float(item.get("cost", item.get("amount"))) for item in provider_usage)
    )
    trace_missing = (
        None
        if provider_usage is None
        else [item for item in provider_usage if not str(item.get("trace_id") or "")]
    )
    usage_receipt_missing = (
        None
        if provider_usage is None
        else [
            item
            for item in provider_usage
            if not str(item.get("usage_receipt_ref") or "")
        ]
    )
    cost_receipt_missing = (
        None
        if provider_usage is None
        else [
            item
            for item in provider_usage
            if not str(item.get("cost_receipt_ref") or "")
        ]
    )
    retry_count = (
        None
        if provider_usage is None
        else sum(
            int(item.get("retry_count") or 0)
            + max(0, int(item.get("dispatch_count") or 1) - 1)
            for item in provider_usage
        )
    )
    canon_issues = [item for item in issues if "CANON" in str(item.get("code") or "")]
    relationship_issues = [
        item for item in issues if "RELATIONSHIP" in str(item.get("code") or "")
    ]
    world_issues = [item for item in issues if "WORLD" in str(item.get("code") or "")]

    load = project_narrative_load(story_state=story_state)
    metrics: dict[str, Any] = {
        "future_knowledge_leakage_count": (
            len(future_knowledge) if context_segments_observed else None
        ),
        "canon_contradiction_count": (
            len(canon_issues) if quality_decision is not None else None
        ),
        "temporal_state_contradiction_count": (
            len(temporal_contradictions) if temporal_state_observed else None
        ),
        "relationship_inconsistency_count": (
            len(relationship_issues) if quality_decision is not None else None
        ),
        "world_state_inconsistency_count": (
            len(world_issues) if quality_decision is not None else None
        ),
        "obligation_unresolved_count": (
            len(unresolved) if temporal_state_observed else None
        ),
        "obligation_overdue_count": (len(overdue) if temporal_state_observed else None),
        "obligation_terminal_without_payoff_count": (
            len(terminal_without_payoff) if temporal_state_observed else None
        ),
        "long_distance_context_selected_count": (
            len(long_distance_selected) if context_segments_observed else None
        ),
        "context_selected_count": len(selected_inputs) if context_observed else None,
        "context_irrelevant_heuristic_count": len(irrelevant)
        if context_observed
        else None,
        "context_relevance_heuristic_precision": (
            round((len(selected_inputs) - len(irrelevant)) / len(selected_inputs), 6)
            if selected_inputs
            else None
        ),
        "context_retrieval_recall": context_recall,
        "context_retrieval_precision": context_precision,
        "planning_constraint_envelope_present": (
            bool(envelope) if planning_candidate is not None else None
        ),
        "planning_drift_count": (
            len(planning_drift) if planning_candidate is not None else None
        ),
        "revision_or_replan_open_action_count": (
            len(open_actions) if quality_decision is not None else None
        ),
        "mkaos_consumption_count": (len(mkaos_usage) if mkaos_available else None),
        "provider_call_count": (
            len(provider_usage) if provider_usage is not None else None
        ),
        "provider_token_count": token_count,
        "provider_cost": round(cost, 8) if cost is not None else None,
        "provider_trace_missing_count": (
            len(trace_missing) if trace_missing is not None else None
        ),
        "provider_retry_count": retry_count,
        **{
            key: value
            for key, value in load["metrics"].items()
            if key not in {"open_obligation_count", "overdue_obligation_count"}
        },
    }
    observations = {
        "context": _observation_status(
            _MEASURED if context_observed else _NOT_OBSERVED,
            len(selected_inputs),
        ),
        "context_segments": _observation_status(
            _MEASURED
            if context_segments_observed
            else _NOT_AVAILABLE
            if context_observed
            else _NOT_OBSERVED,
            len(context_bundle.get("context_segments") or ()),
        ),
        "temporal_state": _observation_status(
            _MEASURED
            if temporal_state_observed
            else _NOT_APPLICABLE
            if chapter <= 1
            else _NOT_AVAILABLE
            if story_state or context_observed
            else _NOT_OBSERVED,
            len(entries) if temporal_state_observed else 0,
        ),
        "narrative_load": _observation_status(
            str(load["status"]),
            sum(value is not None for value in load["metrics"].values()),
        ),
        "expected_context": _observation_status(
            expected_context_status,
            len(expected_context or ()),
        ),
        "planning": _observation_status(
            _MEASURED if planning_candidate is not None else _NOT_OBSERVED,
            len(planning_drift) if planning_candidate is not None else 0,
        ),
        "quality": _observation_status(
            _MEASURED if quality_decision is not None else _NOT_OBSERVED,
            len(actions) if quality_decision is not None else 0,
        ),
        "mkaos_consumption": _observation_status(
            _NOT_OBSERVED
            if mkaos_usage is None
            else _MEASURED
            if mkaos_available
            else _NOT_AVAILABLE,
            len(mkaos_usage or ()) if mkaos_available else 0,
        ),
        "provider_usage": _observation_status(
            _MEASURED if provider_usage is not None else _NOT_OBSERVED,
            len(provider_usage or ()),
        ),
        "provider_tokens": _availability_status(provider_usage, token_missing),
        "provider_cost": _availability_status(provider_usage, cost_missing),
        "provider_trace": _availability_status(provider_usage, trace_missing),
        "provider_usage_receipt": _availability_status(
            provider_usage, usage_receipt_missing
        ),
        "provider_cost_receipt": _availability_status(
            provider_usage, cost_receipt_missing
        ),
    }
    proof_status = (
        "MEASURED_NOT_QUALIFIED"
        if any(item["status"] == _MEASURED for item in observations.values())
        else "NOT_OBSERVED_NOT_QUALIFIED"
    )
    return {
        "type": "NarrativeRuntimeMeasurement",
        "contract_version": "narrative-runtime-measurement-v2",
        "chapter": chapter,
        "proof_status": proof_status,
        "metrics": metrics,
        "observations": observations,
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
                    for item in mkaos_usage or ()
                    if str(item.get("result_asset_version_id") or "")
                }
            ),
            "provider_external_effect_ids": sorted(
                {
                    str(item.get("external_effect_id") or "")
                    for item in provider_usage or ()
                    if str(item.get("external_effect_id") or "")
                }
            ),
            "provider_usage_receipt_refs": sorted(
                {
                    str(item.get("usage_receipt_ref") or "")
                    for item in provider_usage or ()
                    if str(item.get("usage_receipt_ref") or "")
                }
            ),
            "provider_cost_receipt_refs": sorted(
                {
                    str(item.get("cost_receipt_ref") or "")
                    for item in provider_usage or ()
                    if str(item.get("cost_receipt_ref") or "")
                }
            ),
        },
        "qualification": {
            "longform_proven": False,
            "multibook_proven": False,
            "production_proven": False,
        },
    }


def _observation_status(status: str, evidence_count: int) -> dict[str, Any]:
    return {"status": status, "evidence_count": evidence_count}


def _availability_status(
    records: list[Mapping[str, Any]] | None,
    missing: list[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if records is None:
        return _observation_status(_NOT_OBSERVED, 0)
    available_count = len(records) - len(missing or ())
    return _observation_status(
        _MEASURED if not missing else _NOT_AVAILABLE,
        available_count,
    )


__all__ = ["measure_narrative_runtime", "project_narrative_load"]
