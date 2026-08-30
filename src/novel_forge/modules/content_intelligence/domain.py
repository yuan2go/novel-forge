"""INVARIANT: raw text patterns cannot establish Canon or semantic quality."""

from __future__ import annotations

from datetime import datetime
from statistics import fmean
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


HOOK_HORIZONS = {
    "IMMEDIATE",
    "CHAPTER",
    "MINI_ARC",
    "ARC",
    "VOLUME",
    "BOOK",
    "UNSPECIFIED",
}

PACING_METRICS = (
    "event_density",
    "conflict_density",
    "information_density",
    "setup_density",
    "payoff_density",
    "reward_density",
    "emotional_intensity",
    "emotional_variance",
    "dialogue_ratio",
    "action_ratio",
    "reflection_ratio",
    "exposition_ratio",
    "hook_strength",
    "cliffhanger_strength",
    "open_promises",
    "promise_debt",
    "foreshadow_debt",
    "state_change_magnitude",
    "arc_progress",
)


def build_hook_analysis(
    *,
    project_id: str,
    chapter: int,
    chapter_plan: dict[str, Any],
    provider_dimensions: Iterable[dict[str, Any]],
    target_asset_version_id: str,
    chapter_plan_asset_version_id: str,
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    _require_scope(project_id, chapter)
    horizon = str(chapter_plan.get("hook_horizon") or "UNSPECIFIED").upper()
    if horizon not in HOOK_HORIZONS:
        raise KernelError(
            "HOOK_HORIZON_INVALID",
            f"unsupported hook horizon {horizon}",
        )
    dimensions = {
        str(item.get("dimension") or ""): dict(item)
        for item in provider_dimensions
        if isinstance(item, dict)
    }
    relevant = [
        dimensions[name]
        for name in (
            "golden_opening",
            "reader_promise",
            "chapter_hook",
            "suspense_progression",
            "serialization_function",
        )
        if name in dimensions
    ]
    evidence_spans = [
        {
            **dict(location),
            "dimension": str(item.get("dimension") or ""),
            "target_asset_version_id": target_asset_version_id,
        }
        for item in relevant
        for location in item.get("evidence_locations", [])
        if isinstance(location, dict)
    ]
    promises = [
        item
        for item in chapter_plan.get("reader_promise_actions", [])
        if isinstance(item, dict)
    ]
    issues = sorted(
        {
            str(code)
            for item in relevant
            for code in item.get("issue_codes", [])
            if str(code)
        }
    )
    revision_actions = [
        str(action)
        for item in relevant
        for action in item.get("revision_strategies", [])
        if str(action)
    ]
    real_provider = provider_evidence.get("real_model_call") is True
    confidence_values = [
        float(item["confidence"])
        for item in relevant
        if item.get("confidence") is not None
    ]
    return {
        "type": "HookAnalysis",
        "project_id": project_id,
        "chapter": chapter,
        "opening_hook": str(chapter_plan.get("opening_hook") or ""),
        "opening_hook_type": (
            "SEMANTIC_PROVIDER_OBSERVATION"
            if "golden_opening" in dimensions
            else "PLAN_DECLARATION"
            if chapter_plan.get("opening_hook")
            else "UNOBSERVED"
        ),
        "information_gap": str(chapter_plan.get("information_gap") or ""),
        "immediate_conflict": str(chapter_plan.get("immediate_conflict") or ""),
        "reader_question": str(chapter_plan.get("reader_question") or ""),
        "ending_hook": str(chapter_plan.get("chapter_hook") or ""),
        "ending_hook_type": (
            "SEMANTIC_PROVIDER_OBSERVATION"
            if "chapter_hook" in dimensions
            else "PLAN_DECLARATION"
            if chapter_plan.get("chapter_hook")
            else "UNOBSERVED"
        ),
        "unresolved_tension": str(chapter_plan.get("unresolved_tension") or ""),
        "next_chapter_pull": str(chapter_plan.get("next_chapter_bridge") or ""),
        "promise_id": str(promises[0].get("promise_id") or "") if promises else "",
        "hook_horizon": horizon,
        "evidence_spans": evidence_spans,
        "confidence": max(confidence_values, default=0.0),
        "issues": issues,
        "revision_actions": revision_actions,
        "target_asset_version_id": target_asset_version_id,
        "chapter_plan_asset_version_id": chapter_plan_asset_version_id,
        "provider_evidence": dict(provider_evidence),
        "real_provider_observed": real_provider,
        "qualification": (
            "PROVIDER_UNCALIBRATED"
            if real_provider
            else "FIXTURE_UNCALIBRATED"
            if relevant
            else "INSUFFICIENT_EVIDENCE"
        ),
        "commercial_quality_dimensions_reused": sorted(dimensions),
        "contract_version": "hook-analysis-v1",
    }


def build_pacing_observation(
    *,
    project_id: str,
    chapter: int,
    revision: dict[str, Any],
    chapter_plan: dict[str, Any],
    canon: dict[str, Any],
    provider_dimensions: Iterable[dict[str, Any]],
    target_asset_version_id: str,
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    _require_scope(project_id, chapter)
    state_changes = canon.get("state_changes")
    if isinstance(state_changes, dict):
        snapshots = {
            str(state_kind): [
                dict(item) for item in items if isinstance(item, dict)
            ]
            for state_kind, items in state_changes.items()
            if isinstance(items, list)
        }
    else:
        # Compatibility patches remain readable during deterministic rebuild;
        # current production Canon emits only ``state_changes``.
        snapshots = {
            str(item.get("state_kind") or ""): list(item.get("changes") or [])
            for item in canon.get("snapshot_candidates", [])
            if isinstance(item, dict)
        }
    open_promises = sum(
        1
        for item in snapshots.get("reader_promise", [])
        if str(item.get("status") or "OPEN").upper()
        in {"OPEN", "PLANTED", "PROMISED", "ACTIVE", "DEFERRED"}
    )
    foreshadow_debt = sum(
        1
        for item in snapshots.get("foreshadow_state", [])
        if str(item.get("status") or "OPEN").upper()
        in {"OPEN", "PLANTED", "ACTIVE", "DEFERRED"}
    )
    state_change_magnitude = sum(len(items) for items in snapshots.values())
    deterministic = {
        "open_promises": open_promises,
        "promise_debt": open_promises,
        "foreshadow_debt": foreshadow_debt,
        "state_change_magnitude": state_change_magnitude,
    }
    metrics = {
        name: (
            {
                "value": deterministic[name],
                "status": "MEASURED",
                "measurement_type": "DETERMINISTIC",
                "evidence": "typed Canon state changes",
            }
            if name in deterministic
            else {
                "value": None,
                "status": "REQUIRES_PROVIDER_JUDGE",
                "measurement_type": "SEMANTIC",
                "evidence": "",
            }
        )
        for name in PACING_METRICS
    }
    if isinstance(chapter_plan.get("arc_progress"), (int, float)):
        metrics["arc_progress"] = {
            "value": float(chapter_plan["arc_progress"]),
            "status": "DECLARED",
            "measurement_type": "DETERMINISTIC_DECLARATION",
            "evidence": "ChapterPlan.arc_progress",
        }
    semantic_observations = [
        {
            "dimension": str(item.get("dimension") or ""),
            "gate_status": str(item.get("gate_status") or ""),
            "score": item.get("score"),
            "confidence": item.get("confidence"),
            "evidence_locations": list(item.get("evidence_locations") or []),
            "qualification": (
                "PROVIDER_UNCALIBRATED"
                if provider_evidence.get("real_model_call") is True
                else "FIXTURE_UNCALIBRATED"
            ),
        }
        for item in provider_dimensions
        if isinstance(item, dict)
        and str(item.get("dimension") or "")
        in {
            "reward",
            "chapter_hook",
            "suspense_progression",
            "emotional_curve",
            "serialization_function",
            "arc_progress",
        }
    ]
    return {
        "type": "PacingObservation",
        "project_id": project_id,
        "chapter": chapter,
        "source_asset_version_id": target_asset_version_id,
        "scene_count": len(chapter_plan.get("scene_sequence", [])),
        "metrics": metrics,
        "semantic_observations": semantic_observations,
        "provider_evidence": dict(provider_evidence),
        "qualification": (
            "PROVIDER_UNCALIBRATED"
            if provider_evidence.get("real_model_call") is True
            else "FIXTURE_UNCALIBRATED"
            if semantic_observations
            else "INSUFFICIENT_EVIDENCE"
        ),
        "deterministic_and_semantic_separated": True,
        "used_keyword_or_regex_heuristics": False,
        "raw_text_used_for_metric_inference": False,
        "contract_version": "pacing-observation-v1",
    }


def aggregate_pacing_windows(
    *,
    project_id: str,
    as_of_chapter: int,
    observations: Iterable[dict[str, Any]],
    scopes: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    _require_scope(project_id, as_of_chapter)
    rows = [dict(item) for item in observations]
    if any(item.get("project_id") != project_id for item in rows):
        raise KernelError(
            "CROSS_PROJECT_REFERENCE",
            "Pacing observations cross Project authority scope",
        )
    future_excluded = any(int(item.get("chapter", 0)) > as_of_chapter for item in rows)
    visible = sorted(
        (item for item in rows if 0 < int(item.get("chapter", 0)) <= as_of_chapter),
        key=lambda item: int(item["chapter"]),
    )
    requested = {
        "SCENE": (as_of_chapter, as_of_chapter),
        "CHAPTER": (as_of_chapter, as_of_chapter),
        "3_CHAPTER_WINDOW": (max(1, as_of_chapter - 2), as_of_chapter),
        "10_CHAPTER_WINDOW": (max(1, as_of_chapter - 9), as_of_chapter),
        "CHAPTER_GROUP": (as_of_chapter, as_of_chapter),
        **(scopes or {}),
    }
    for scale in ("ARC", "VOLUME", "BOOK"):
        requested.setdefault(scale, (as_of_chapter, as_of_chapter))
    aggregates = [
        _aggregate_window(
            scale,
            visible,
            start=max(1, int(boundary[0])),
            end=min(as_of_chapter, int(boundary[1])),
            available=(scale != "SCENE"),
        )
        for scale, boundary in requested.items()
    ]
    return {
        "type": "PacingWindowAggregateSet",
        "project_id": project_id,
        "as_of_chapter": as_of_chapter,
        "boundary": "INCLUSIVE",
        "accepted_state_only": True,
        "future_observations_excluded": future_excluded,
        "aggregates": aggregates,
        "contract_version": "pacing-window-aggregate-v1",
    }


def _aggregate_window(
    scale: str,
    observations: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    available: bool,
) -> dict[str, Any]:
    selected = [item for item in observations if start <= int(item["chapter"]) <= end]
    values: dict[str, list[float]] = {}
    for item in selected:
        for name, metric in dict(item.get("metrics") or {}).items():
            value = metric.get("value") if isinstance(metric, dict) else None
            if isinstance(value, (int, float)):
                values.setdefault(str(name), []).append(float(value))
    return {
        "type": "PacingWindowAggregate",
        "scale": scale,
        "chapter_from": start,
        "chapter_to": end,
        "chapters": [int(item["chapter"]) for item in selected] if available else [],
        "status": "MEASURED"
        if selected and available
        else "NOT_AVAILABLE_AUTHORITY_DATA",
        "metric_means": {
            name: round(fmean(items), 6) for name, items in sorted(values.items())
        }
        if available
        else {},
        "source_asset_version_ids": [
            str(item.get("source_asset_version_id") or "") for item in selected
        ]
        if available
        else [],
    }


def build_world_consequence_candidate(
    *,
    project_id: str,
    world_bible_asset_version_id: str,
    world_rules: Iterable[dict[str, Any]],
    provider_consequences: Iterable[dict[str, Any]],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not project_id or not world_bible_asset_version_id:
        raise ValueError("project and WorldBible lineage are required")
    rules = {str(item.get("rule_id") or ""): dict(item) for item in world_rules}
    rules.pop("", None)
    consequences = []
    node_by_id: dict[str, dict[str, Any]] = {
        rule_id: {"node_id": rule_id, "node_type": "WorldRule"}
        for rule_id in sorted(rules)
    }
    edges: list[dict[str, str]] = []
    affected_group_node_ids: set[str] = set()

    def add_node(node_id: str, node_type: str, value: str) -> None:
        existing = node_by_id.get(node_id)
        candidate = {"node_id": node_id, "node_type": node_type, "value": value}
        if existing is not None and existing != candidate:
            raise KernelError(
                "WORLD_CONSEQUENCE_GRAPH_ID_COLLISION",
                "World consequence graph node identity is not stable",
            )
        node_by_id[node_id] = candidate

    def add_edge(source_id: str, target_id: str, edge_type: str) -> None:
        edge = {
            "source_id": source_id,
            "target_id": target_id,
            "edge_type": edge_type,
        }
        if edge not in edges:
            edges.append(edge)

    for item in provider_consequences:
        consequence = dict(item)
        if consequence.get("project_id") not in (None, "", project_id):
            raise KernelError(
                "CROSS_PROJECT_REFERENCE",
                "World consequence belongs to another Project",
            )
        rule_id = str(consequence.get("rule_id") or "")
        consequence_id = str(consequence.get("consequence_id") or "")
        if rule_id not in rules:
            raise KernelError(
                "WORLD_CONSEQUENCE_RULE_UNKNOWN",
                "World consequence does not reference an input WorldRule",
            )
        if not consequence_id:
            raise KernelError(
                "WORLD_CONSEQUENCE_ID_INVALID",
                "World consequence requires a stable consequence_id",
            )
        direct = str(consequence.get("direct_consequence") or "").strip()
        affected_groups = _graph_values(consequence.get("affected_groups"))
        if not direct or not affected_groups:
            raise KernelError(
                "WORLD_CONSEQUENCE_GRAPH_INCOMPLETE",
                "World consequence requires a direct consequence and affected group",
            )
        consequences.append({**consequence, "project_id": project_id})
        add_node(consequence_id, "DirectConsequenceCandidate", direct)
        add_edge(rule_id, consequence_id, "DIRECT_CONSEQUENCE")
        causal_anchor = consequence_id

        systemic = str(consequence.get("systemic_consequence") or "").strip()
        if systemic:
            systemic_id = f"{consequence_id}:systemic"
            add_node(systemic_id, "SystemicConsequenceCandidate", systemic)
            add_edge(causal_anchor, systemic_id, "SYSTEMIC_CONSEQUENCE")
            causal_anchor = systemic_id

        cultural = str(consequence.get("cultural_consequence") or "").strip()
        if cultural:
            cultural_id = f"{consequence_id}:cultural"
            add_node(cultural_id, "CulturalConsequenceCandidate", cultural)
            add_edge(causal_anchor, cultural_id, "CULTURAL_CONSEQUENCE")
            causal_anchor = cultural_id

        group_ids = []
        for group in affected_groups:
            group_id = f"affected_group:{group}"
            add_node(group_id, "AffectedGroup", group)
            add_edge(causal_anchor, group_id, "AFFECTS")
            affected_group_node_ids.add(group_id)
            group_ids.append(group_id)

        adaptations = _graph_values(
            consequence.get("institutional_adaptations")
            or consequence.get("institutional_adaptation")
        )
        for adaptation in adaptations:
            adaptation_id = f"institutional_adaptation:{adaptation}"
            add_node(adaptation_id, "InstitutionalAdaptationCandidate", adaptation)
            for group_id in group_ids:
                add_edge(group_id, adaptation_id, "ADAPTS")

        for index, contradiction in enumerate(
            _graph_values(consequence.get("contradictions"))
        ):
            contradiction_id = f"{consequence_id}:contradiction:{index}"
            add_node(contradiction_id, "ContradictionCandidate", contradiction)
            add_edge(causal_anchor, contradiction_id, "CONTRADICTS")

        for index, opportunity in enumerate(
            _graph_values(consequence.get("story_opportunities"))
        ):
            opportunity_id = f"{consequence_id}:story_opportunity:{index}"
            add_node(opportunity_id, "StoryOpportunityCandidate", opportunity)
            add_edge(causal_anchor, opportunity_id, "ENABLES_STORY")

    nodes = [node_by_id[node_id] for node_id in sorted(node_by_id)]
    if any(
        edge["source_id"] not in node_by_id or edge["target_id"] not in node_by_id
        for edge in edges
    ):
        raise KernelError(
            "WORLD_CONSEQUENCE_GRAPH_INTEGRITY_INVALID",
            "World consequence graph contains a dangling edge",
        )
    return {
        "type": "WorldConsequenceGraph",
        "project_id": project_id,
        "world_bible_asset_version_id": world_bible_asset_version_id,
        "status": "CANDIDATE",
        "accepted_canon": False,
        "canon_mutation": "FORBIDDEN",
        "consequences": consequences,
        "nodes": nodes,
        "edges": edges,
        "affected_group_node_ids": sorted(affected_group_node_ids),
        "graph_integrity": "PASSED",
        "provider_evidence": dict(provider_evidence),
        "activation_requirement": "STORY_DESIGN_AUTHORITY_DECISION",
        "contract_version": "world-consequence-graph-v1",
    }


def verify_claim(
    *,
    claim: dict[str, Any],
    evidence: Iterable[dict[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    _require_timezone(as_of)
    project_id = str(claim.get("project_id") or "")
    claim_id = str(claim.get("claim_id") or "")
    if not project_id or not claim_id or not str(claim.get("statement") or ""):
        raise KernelError(
            "FACT_CLAIM_INVALID", "Claim identity and statement are required"
        )
    rows = [dict(item) for item in evidence]
    if any(str(item.get("project_id") or "") != project_id for item in rows):
        raise KernelError(
            "CROSS_PROJECT_REFERENCE",
            "Claim evidence crosses Project authority scope",
        )
    qualified = [
        item
        for item in rows
        if item.get("qualified") is True
        and item.get("evidence_span_id")
        and item.get("source_document_id")
    ]
    valid_to = _datetime_or_none(claim.get("temporal_valid_to"))
    current: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    not_yet_valid: list[dict[str, Any]] = []
    for item in qualified:
        evidence_valid_from = _datetime_or_none(item.get("temporal_valid_from"))
        evidence_valid_to = _datetime_or_none(item.get("temporal_valid_to"))
        if evidence_valid_to is not None and as_of > evidence_valid_to:
            expired.append(item)
        elif evidence_valid_from is not None and as_of < evidence_valid_from:
            not_yet_valid.append(item)
        else:
            current.append(item)
    if valid_to is not None and as_of > valid_to:
        status = "OUTDATED"
    elif not current and expired:
        status = "OUTDATED"
    elif not current:
        status = "INSUFFICIENT_EVIDENCE"
    elif any(
        str(item.get("stance") or "").upper() == "CONTRADICTS" for item in current
    ):
        status = "DISPUTED"
    elif any(str(item.get("stance") or "").upper() == "SUPPORTS" for item in current):
        status = "VERIFIED"
    else:
        status = "UNSUPPORTED"
    confidences = [float(item.get("confidence") or 0.0) for item in current]
    refs = [str(item["evidence_span_id"]) for item in qualified]
    return {
        "type": "ClaimVerificationDecision",
        "claim_id": claim_id,
        "project_id": project_id,
        "status": status,
        "evidence_refs": refs,
        "source_document_ids": sorted(
            {str(item["source_document_id"]) for item in qualified}
        ),
        "confidence": min(confidences, default=0.0),
        "gate_result": "PASSED" if status == "VERIFIED" else "BLOCKED",
        "as_of": as_of.isoformat(),
        "freshness": {
            "current_evidence_count": len(current),
            "expired_evidence_count": len(expired),
            "not_yet_valid_evidence_count": len(not_yet_valid),
            "explicit_temporal_boundaries_only": True,
        },
        "fail_closed": True,
        "contract_version": "claim-verification-v1",
    }


def _datetime_or_none(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _require_timezone(value)
    try:
        return _require_timezone(
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except ValueError as exc:
        raise KernelError(
            "FACT_CLAIM_TEMPORAL_BOUNDARY_INVALID",
            "Claim temporal_valid_to must be an ISO-8601 timestamp",
        ) from exc


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise KernelError(
            "FACT_CLAIM_TIMEZONE_REQUIRED",
            "Claim and evidence temporal boundaries require an explicit timezone",
        )
    return value


def _graph_values(value: Any) -> list[str]:
    values = (
        value if isinstance(value, list) else [value] if value not in (None, "") else []
    )
    normalized: list[str] = []
    for item in values:
        if isinstance(item, dict):
            text = str(
                item.get("group_id")
                or item.get("adaptation_id")
                or item.get("name")
                or item.get("statement")
                or item.get("value")
                or ""
            ).strip()
        else:
            text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _require_scope(project_id: str, chapter: int) -> None:
    if not project_id.strip() or chapter <= 0:
        raise ValueError("project_id and a positive chapter are required")
