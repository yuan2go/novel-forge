"""Storage-free grouped quality evidence for the Chapter Authority Saga.

Deterministic checks only decide properties they can actually observe.  Semantic
dimensions require a versioned calibrated evidence asset and otherwise fail
closed with an explicit non-passing status.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

from .longitudinal import (
    READER_OUTCOME_DIMENSIONS,
    REPETITION_DIMENSIONS,
    build_arc_quality_evaluation,
    build_longitudinal_quality_evidence,
    build_volume_slice_quality_evaluation,
)


QUALITY_GROUPS: dict[str, tuple[str, ...]] = {
    "structural": (
        "readability",
        "mobile_reading",
        "chapter_economy",
        "basic_prose_integrity",
        "scene_completeness",
        "dialogue_narration_balance",
        "paragraph_structure",
        "repetition",
        "summary_like_prose",
    ),
    "commercial": (
        "golden_opening",
        "reader_promise",
        "reward",
        "protagonist_charm",
        "antagonist_pressure",
        "toxic_point",
        "chapter_hook",
        "suspense_progression",
        "emotional_curve",
        "serialization_function",
    ),
    "source_originality": (
        "source_leakage",
        "originality",
        "anti_ai",
        "style_drift",
        "copyright_boundary",
    ),
    "longform": (
        "canon_consistency",
        "character_motivation_drift",
        "relationship_continuity",
        "timeline_consistency",
        "foreshadow_status",
        "promise_payoff_debt",
        "world_rule_conflict",
        "power_state_conflict",
        "narrative_pattern_repetition",
        "arc_progress",
    ),
    "platform": (
        "chapter_length",
        "format",
        "sensitive_content",
        "ai_content_policy",
        "opening_expectations",
        "platform_rhythm",
        "publish_metadata",
    ),
}
QUALITY_DIMENSIONS = tuple(
    item for values in QUALITY_GROUPS.values() for item in values
)
QUALITY_EVIDENCE_STATUSES = frozenset(
    {
        "PASSED",
        "PASSED_WITH_WARNINGS",
        "PASSED_WITH_UNCALIBRATED",
        "FAILED",
        "UNCALIBRATED",
        "INSUFFICIENT_EVIDENCE",
        "REQUIRES_PROVIDER_JUDGE",
        "REQUIRES_HUMAN_REVIEW",
        "WAIVED_BY_APPROVAL",
    }
)
BLOCKING_DIMENSIONS = frozenset(
    {
        "readability",
        "basic_prose_integrity",
        "source_leakage",
        "originality",
        "anti_ai",
        "copyright_boundary",
        "canon_consistency",
        "timeline_consistency",
        "world_rule_conflict",
        "power_state_conflict",
        "chapter_length",
        "format",
        "sensitive_content",
        "ai_content_policy",
        "publish_metadata",
    }
)
LONGITUDINAL_QUALITY_DIMENSIONS = (
    "arc_dormancy",
    "hook_repetition",
    "character_disappearance",
    "payoff_density",
    "narrative_debt",
    "world_expansion_rate",
    "style_prose_drift",
    "reader_reward_rhythm",
)
QUALITY_SCALES = ("BOOK", "VOLUME", "ARC", "SEGMENT", "CHAPTER", "SCENE")


def build_quality_group_evidence(
    *,
    group: str,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle: dict[str, Any],
    canon: dict[str, Any],
    fixture: bool,
) -> dict[str, Any]:
    if group not in QUALITY_GROUPS:
        raise KernelError("QUALITY_GROUP_INVALID", f"unknown quality group: {group}")
    text = str(revision.get("text") or "").strip()
    if not all((project_id, revision_asset_version_id, text)):
        raise KernelError(
            "QUALITY_EVIDENCE_INPUT_INVALID", "quality target lineage is incomplete"
        )
    metrics = _structural_metrics(text)
    segments = tuple(context_bundle.get("context_segments", ()))
    profile_ids = _profile_ids(context_bundle)
    reports = [
        _evaluate(
            group=group,
            dimension=dimension,
            project_id=project_id,
            target=revision_asset_version_id,
            metrics=metrics,
            segments=segments,
            context_bundle=context_bundle,
            canon=canon,
            fixture=fixture,
            profile_ids=profile_ids,
        )
        for dimension in QUALITY_GROUPS[group]
    ]
    blocked = [
        item
        for item in reports
        if item["blocking"]
        and item["gate_status"]
        not in {
            "PASSED",
            "PASSED_WITH_WARNINGS",
            "PASSED_WITH_UNCALIBRATED",
            "WAIVED_BY_APPROVAL",
        }
    ]
    group_status = (
        "FAILED"
        if any(item["gate_status"] == "FAILED" for item in blocked)
        else (
            "INSUFFICIENT_EVIDENCE"
            if blocked
            else "PASSED_WITH_WARNINGS"
            if any(item["gate_status"] != "PASSED" for item in reports)
            else "PASSED"
        )
    )
    return {
        "type": "ChapterQualityGroupReport",
        "group": group,
        "project_id": project_id,
        "target_asset_version_id": revision_asset_version_id,
        **profile_ids,
        "gate_status": group_status,
        "blocking_dimension_codes": [item["dimension"] for item in blocked],
        "dimensions": reports,
        "fixture": fixture,
        "production_verified": False,
        "provider_verified": any(item["provider_verified"] for item in reports),
        "human_verified": any(item["human_verified"] for item in reports),
        "contract_version": "chapter-quality-group-v2",
    }


def build_chapter_quality_evidence(**kwargs: Any) -> list[dict[str, Any]]:
    """Compatibility aggregate used by legacy callers; it preserves honest statuses."""
    return [
        item
        for group in QUALITY_GROUPS
        for item in build_quality_group_evidence(group=group, **kwargs)["dimensions"]
    ]


def build_multiscale_quality_report(
    *,
    project_id: str,
    book_id: str,
    context_bundle: dict[str, Any],
    accepted_through_chapter: int,
    source_asset_version_ids: Iterable[str],
) -> dict[str, Any]:
    """Project bounded longitudinal quality from accepted-only observations.

    The Chapter runtime consumes compact observation projections, never full
    historical prose.  Every usable row must name its Acceptance and accepted
    outcome AssetVersion; unbound or future rows fail closed.
    """

    observations = _accepted_quality_observations(
        context_bundle,
        project_id=project_id,
        book_id=book_id,
        accepted_through_chapter=accepted_through_chapter,
    )
    windows = {
        "LAST_10_CHAPTERS": observations[-10:],
        "LAST_30_CHAPTERS": observations[-30:],
    }
    current_volume = (
        str(observations[-1].get("volume_id") or "") if observations else ""
    )
    windows["CURRENT_VOLUME"] = [
        item
        for item in observations
        if current_volume and item.get("volume_id") == current_volume
    ]
    scope_reports: list[dict[str, Any]] = [
        _quality_scope("BOOK", book_id, observations)
    ]
    for scale, field in (
        ("VOLUME", "volume_id"),
        ("ARC", "active_arc_ids"),
        ("SEGMENT", "segment_ids"),
        ("CHAPTER", "chapter_number"),
        ("SCENE", "scene_ids"),
    ):
        scope_reports.extend(_grouped_quality_scopes(scale, field, observations))
    window_reports = [
        {
            "window": window,
            "chapter_count": len(rows),
            "chapter_range": (
                [int(rows[0]["chapter_number"]), int(rows[-1]["chapter_number"])]
                if rows
                else []
            ),
            "dimensions": _longitudinal_dimensions(rows),
        }
        for window, rows in windows.items()
    ]
    observed = bool(observations)
    canonical = build_longitudinal_quality_evidence(observations)
    arc_ids = sorted(
        {
            str(item.get("arc_plan_version_id") or "")
            for observation in observations
            for item in observation.get("arc_evidence") or ()
            if isinstance(item, Mapping)
            and str(item.get("arc_plan_version_id") or "")
        }
    )
    arc_evaluations = tuple(
        build_arc_quality_evaluation(
            observations, arc_plan_version_id=arc_plan_version_id
        )
        for arc_plan_version_id in arc_ids
    )
    volume_evaluation = build_volume_slice_quality_evaluation(
        observations,
        arc_evaluations=arc_evaluations,
        volume_scope_id=current_volume or f"{book_id}:accepted-slice",
    )
    return {
        "type": "MultiScaleNarrativeQualityReport",
        "contract_version": "multiscale-narrative-quality-v2",
        "project_id": project_id,
        "book_id": book_id,
        "accepted_through_chapter": accepted_through_chapter,
        "accepted_observation_count": len(observations),
        "observation_status": "MEASURED" if observed else "NOT_OBSERVED",
        "scales": list(QUALITY_SCALES),
        "dimensions": list(LONGITUDINAL_QUALITY_DIMENSIONS),
        "scope_reports": scope_reports,
        "window_reports": window_reports,
        "canonical_longitudinal_evidence": canonical.to_dict(),
        "arc_evaluations": [item.to_dict() for item in arc_evaluations],
        "bounded_volume_evaluation": volume_evaluation.to_dict(),
        "canonical_dimension_families": [
            "momentum",
            "promise_payoff",
            *REPETITION_DIMENSIONS,
            *READER_OUTCOME_DIMENSIONS,
        ],
        "compatibility_projection": {
            "status": "DEPRECATED_NON_CANONICAL",
            "dimensions": list(LONGITUDINAL_QUALITY_DIMENSIONS),
            "reason": (
                "legacy query consumers require scope/window fields; Arc and "
                "Volume qualification use causal accepted evidence above"
            ),
        },
        "source_acceptance_ids": sorted(
            {str(item["acceptance_id"]) for item in observations}
        ),
        "source_accepted_asset_version_ids": sorted(
            {str(item["accepted_asset_version_id"]) for item in observations}
        ),
        "source_asset_version_ids": sorted(
            {str(item) for item in source_asset_version_ids if str(item)}
        ),
        "accepted_history_only": True,
        "provider_verified": False,
        "production_verified": False,
    }


def _accepted_quality_observations(
    context_bundle: dict[str, Any],
    *,
    project_id: str,
    book_id: str,
    accepted_through_chapter: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in context_bundle.get("context_segments") or []:
        for fact in segment.get("structured_facts") or []:
            if str(fact.get("key") or "") != "accepted_quality_observations":
                continue
            value = fact.get("value")
            if not isinstance(value, list):
                raise KernelError(
                    "LONGITUDINAL_QUALITY_INPUT_INVALID",
                    "accepted quality observations must be an array",
                )
            for item in value:
                if not isinstance(item, dict):
                    raise KernelError(
                        "LONGITUDINAL_QUALITY_INPUT_INVALID",
                        "accepted quality observations must be objects",
                    )
                chapter = item.get("chapter_number")
                valid = (
                    item.get("project_id") == project_id
                    and item.get("book_id") == book_id
                    and isinstance(chapter, int)
                    and not isinstance(chapter, bool)
                    and 0 < chapter <= accepted_through_chapter
                    and bool(str(item.get("acceptance_id") or ""))
                    and bool(str(item.get("accepted_asset_version_id") or ""))
                    and item.get("acceptance_status") == "COMMITTED"
                )
                if not valid:
                    raise KernelError(
                        "LONGITUDINAL_QUALITY_ACCEPTED_LINEAGE_REQUIRED",
                        "longitudinal quality can consume only exact accepted lineage",
                    )
                rows.append(dict(item))
    by_chapter: dict[int, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(item["chapter_number"])):
        chapter = int(row["chapter_number"])
        previous = by_chapter.get(chapter)
        if previous is not None and previous != row:
            raise KernelError(
                "LONGITUDINAL_QUALITY_DUPLICATE_CHAPTER",
                "accepted quality history contains conflicting chapter projections",
            )
        by_chapter[chapter] = row
    return list(by_chapter.values())


def _grouped_quality_scopes(
    scale: str, field: str, observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        raw = row.get(field)
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            identity = str(value or "")
            if identity:
                grouped.setdefault(identity, []).append(row)
    return [
        _quality_scope(scale, identity, rows)
        for identity, rows in sorted(grouped.items())
    ]


def _quality_scope(
    scale: str, identity: str, observations: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "scale": scale,
        "scope_id": identity,
        "chapter_count": len(observations),
        "dimensions": _longitudinal_dimensions(observations),
    }


def _longitudinal_dimensions(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not observations:
        return [
            _longitudinal_result(dimension, "NOT_OBSERVED", None, 0, {})
            for dimension in LONGITUDINAL_QUALITY_DIMENSIONS
        ]
    chapters = [int(item["chapter_number"]) for item in observations]
    arc_gaps = _arc_max_gaps(observations)
    character_gaps = _identity_max_gap(observations, "character_ids")
    hooks = [str(item.get("hook_signature") or "") for item in observations]
    hooks = [item for item in hooks if item]
    hook_ratio = max(Counter(hooks).values()) / len(hooks) if hooks else None
    payoff_count = sum(int(item.get("payoff_count") or 0) for item in observations)
    payoff_density = payoff_count / len(observations)
    debt_values = [
        float(item["narrative_debt_score"])
        for item in observations
        if isinstance(item.get("narrative_debt_score"), (int, float))
        and not isinstance(item.get("narrative_debt_score"), bool)
    ]
    world_load = [len(item.get("new_world_concept_ids") or []) for item in observations]
    style_values = [
        float(item["average_sentence_length"])
        for item in observations
        if isinstance(item.get("average_sentence_length"), (int, float))
        and not isinstance(item.get("average_sentence_length"), bool)
    ]
    drift = _relative_half_drift(style_values)
    reward_chapters = [
        int(item["chapter_number"])
        for item in observations
        if int(item.get("reader_reward_count") or 0) > 0
    ]
    reward_gap = _max_gap(reward_chapters, boundary=chapters)
    values = {
        "arc_dormancy": (max(arc_gaps.values(), default=0), 10, arc_gaps),
        "hook_repetition": (hook_ratio, 0.4, {"hook_count": len(hooks)}),
        "character_disappearance": (
            max(character_gaps.values(), default=0),
            10,
            character_gaps,
        ),
        "payoff_density": (payoff_density, 0.1, {"payoff_count": payoff_count}),
        "narrative_debt": (
            debt_values[-1] if debt_values else None,
            10.0,
            {"peak": max(debt_values) if debt_values else None},
        ),
        "world_expansion_rate": (
            sum(world_load) / len(world_load),
            3.0,
            {"new_concepts": sum(world_load)},
        ),
        "style_prose_drift": (drift, 0.3, {"sample_size": len(style_values)}),
        "reader_reward_rhythm": (reward_gap, 5, {"reward_chapters": reward_chapters}),
    }
    reports: list[dict[str, Any]] = []
    for dimension in LONGITUDINAL_QUALITY_DIMENSIONS:
        value, threshold, evidence = values[dimension]
        if value is None:
            status = "NOT_OBSERVED"
        elif dimension == "payoff_density":
            status = "PASSED" if float(value) >= float(threshold) else "WARNING"
        else:
            status = "PASSED" if float(value) <= float(threshold) else "WARNING"
        reports.append(
            _longitudinal_result(
                dimension,
                status,
                value,
                len(observations),
                {**evidence, "threshold": threshold},
            )
        )
    return reports


def _identity_max_gap(observations: list[dict[str, Any]], field: str) -> dict[str, int]:
    appearances: dict[str, list[int]] = {}
    for row in observations:
        for identity in row.get(field) or []:
            appearances.setdefault(str(identity), []).append(int(row["chapter_number"]))
    bounds = [int(item["chapter_number"]) for item in observations]
    return {
        identity: _max_gap(chapters, boundary=bounds)
        for identity, chapters in appearances.items()
    }


def _arc_max_gaps(observations: list[dict[str, Any]]) -> dict[str, int]:
    identities = {
        str(identity)
        for row in observations
        for field in ("open_arc_ids", "active_arc_ids")
        for identity in row.get(field) or []
        if str(identity)
    }
    appearances = {
        identity: [
            int(row["chapter_number"])
            for row in observations
            if identity in {str(item) for item in row.get("active_arc_ids") or []}
        ]
        for identity in identities
    }
    bounds = [int(item["chapter_number"]) for item in observations]
    return {
        identity: _max_gap(chapters, boundary=bounds)
        for identity, chapters in appearances.items()
    }


def _max_gap(chapters: list[int], *, boundary: list[int]) -> int:
    if not boundary:
        return 0
    points = [boundary[0] - 1, *sorted(set(chapters)), boundary[-1] + 1]
    return max((right - left - 1 for left, right in zip(points, points[1:])), default=0)


def _relative_half_drift(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    midpoint = len(values) // 2
    baseline = sum(values[:midpoint]) / midpoint
    recent = sum(values[midpoint:]) / (len(values) - midpoint)
    return abs(recent - baseline) / max(abs(baseline), 1.0)


def _longitudinal_result(
    dimension: str,
    status: str,
    value: Any,
    sample_size: int,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "status": status,
        "value": value,
        "sample_size": sample_size,
        "evidence": evidence,
        "deterministic": True,
    }


def _evaluate(
    *,
    group: str,
    dimension: str,
    project_id: str,
    target: str,
    metrics: dict[str, Any],
    segments: tuple[dict[str, Any], ...],
    context_bundle: dict[str, Any],
    canon: dict[str, Any],
    fixture: bool,
    profile_ids: dict[str, str],
) -> dict[str, Any]:
    calibrated = _calibrated_evidence(
        dimension, segments, target_asset_version_id=target, fixture=fixture
    )
    if calibrated is not None:
        status = str(calibrated.get("gate_status") or "INSUFFICIENT_EVIDENCE").upper()
        if status not in QUALITY_EVIDENCE_STATUSES:
            raise KernelError(
                "QUALITY_EVIDENCE_STATUS_INVALID",
                f"invalid {dimension} evidence status",
            )
        waiver = None
        if status == "WAIVED_BY_APPROVAL":
            waiver = _approved_fixture_waiver(
                dimension,
                segments,
                project_id=project_id,
                target_asset_version_id=target,
            )
            if waiver is None:
                raise KernelError(
                    "QUALITY_FIXTURE_WAIVER_INVALID",
                    f"{dimension} waiver lacks a current scoped approval",
                )
        elif fixture and status == "PASSED_WITH_UNCALIBRATED":
            # A fixture Provider result remains non-production evidence.  It
            # may close an internal corrective loop only through the exact,
            # frozen operator waiver; a failed result is never converted.
            waiver = _approved_fixture_waiver(
                dimension,
                segments,
                project_id=project_id,
                target_asset_version_id=target,
            )
            if waiver is not None:
                status = "WAIVED_BY_APPROVAL"
        report = _report(
            group,
            dimension,
            project_id,
            target,
            status,
            score=calibrated.get("score"),
            calibration=str(calibrated["calibration_status"]),
            source=str(calibrated.get("evidence_source") or "authority_asset"),
            locations=list(calibrated.get("evidence_locations") or []),
            fixture=fixture,
            profile_ids=profile_ids,
            provider_verified=bool(calibrated.get("provider_verified")),
            human_verified=bool(calibrated.get("human_verified")),
        )
        if waiver is not None:
            report["waiver"] = waiver
        return report

    source_clear = bool(
        context_bundle.get("source_isolation_result", {}).get("passed")
    ) and all(
        not segment.get("source_expression_included", True) for segment in segments
    )
    if dimension in {"source_leakage", "copyright_boundary"}:
        passed = (
            source_clear
            and context_bundle.get("copyright_boundary")
            == "abstract_or_project_owned_only"
        )
        return _report(
            group,
            dimension,
            project_id,
            target,
            "PASSED" if passed else "FAILED",
            score=None,
            calibration="DETERMINISTIC",
            source="context_source_isolation",
            locations=[
                {
                    "source_clear": source_clear,
                    "copyright_boundary": context_bundle.get("copyright_boundary"),
                }
            ],
            fixture=fixture,
            profile_ids=profile_ids,
        )
    if dimension == "readability":
        average = float(metrics["average_sentence"])
        score = round(max(0.0, min(100.0, 100.0 - max(0.0, average - 36.0) * 2.0)), 2)
        return _report(
            group,
            dimension,
            project_id,
            target,
            "PASSED" if score >= 70 else "FAILED",
            score=score,
            calibration="DETERMINISTIC",
            source="readability_metrics",
            locations=[{"average_sentence_length": average}],
            fixture=fixture,
            profile_ids=profile_ids,
        )
    if dimension in {"mobile_reading", "paragraph_structure"}:
        average = float(metrics["average_paragraph"])
        status = "PASSED" if average <= 270 else "FAILED"
        return _report(
            group,
            dimension,
            project_id,
            target,
            status,
            score=None,
            calibration="DETERMINISTIC",
            source="mobile_paragraph_metrics",
            locations=[{"average_paragraph_length": average}],
            fixture=fixture,
            profile_ids=profile_ids,
        )
    if dimension == "basic_prose_integrity":
        passed = metrics["sentences"] >= 2 and metrics["characters"] >= 80
        return _report(
            group,
            dimension,
            project_id,
            target,
            "PASSED" if passed else "FAILED",
            score=None,
            calibration="DETERMINISTIC",
            source="prose_integrity_metrics",
            locations=[metrics],
            fixture=fixture,
            profile_ids=profile_ids,
        )
    if dimension == "repetition":
        ratio = float(metrics["duplicate_sentence_ratio"])
        return _report(
            group,
            dimension,
            project_id,
            target,
            "PASSED" if ratio <= 0.25 else "FAILED",
            score=None,
            calibration="DETERMINISTIC",
            source="repetition_metrics",
            locations=[{"duplicate_sentence_ratio": ratio}],
            fixture=fixture,
            profile_ids=profile_ids,
        )
    if dimension == "canon_consistency":
        conflicts = list(canon.get("conflicts") or [])
        return _report(
            group,
            dimension,
            project_id,
            target,
            "PASSED" if not conflicts else "FAILED",
            score=None,
            calibration="DETERMINISTIC",
            source="canon_reduction",
            locations=[{"conflict_count": len(conflicts)}],
            fixture=fixture,
            profile_ids=profile_ids,
        )
    # Profile existence is deterministic; profile-specific compliance is not.
    if group == "platform" and not profile_ids["platform_profile_version_id"]:
        status = "INSUFFICIENT_EVIDENCE"
    elif group in {"commercial", "source_originality"}:
        status = "REQUIRES_PROVIDER_JUDGE"
    else:
        status = "INSUFFICIENT_EVIDENCE"
    return _report(
        group,
        dimension,
        project_id,
        target,
        status,
        score=None,
        calibration="FIXTURE_UNCALIBRATED" if fixture else "PROVIDER_UNCALIBRATED",
        source="none",
        locations=[],
        fixture=fixture,
        profile_ids=profile_ids,
    )


def _calibrated_evidence(
    dimension: str,
    segments: Iterable[dict[str, Any]],
    *,
    target_asset_version_id: str,
    fixture: bool,
) -> dict[str, Any] | None:
    for segment in segments:
        facts = {
            str(item.get("key")): item.get("value")
            for item in segment.get("structured_facts", [])
        }
        entries = list(facts.get("dimension_evidence") or [])
        entries.append(facts)
        for entry in entries:
            if (
                str(entry.get("dimension") or segment.get("narrative_function") or "")
                != dimension
            ):
                continue
            target = str(entry.get("target_asset_version_id") or "")
            fixture_protocol = fixture and entry.get("fixture_protocol_only") is True
            if target != target_asset_version_id and not fixture_protocol:
                continue
            calibration = str(entry.get("calibration_status") or "").upper()
            human = entry.get("human_verified") is True
            provider = entry.get("provider_verified") is True
            qualified = (
                calibration
                in {
                    "HUMAN_CALIBRATED",
                    "GOLDEN_SET_CALIBRATED",
                }
                and not fixture_protocol
            )
            real_provider_uncalibrated = (
                not fixture and provider and calibration == "PROVIDER_UNCALIBRATED"
            )
            if (
                not qualified
                and not fixture_protocol
                and not real_provider_uncalibrated
            ):
                continue
            gate_status = entry.get("gate_status")
            if fixture_protocol and str(gate_status).upper() == "PASSED":
                gate_status = "PASSED_WITH_UNCALIBRATED"
            if real_provider_uncalibrated and str(gate_status).upper() == "PASSED":
                gate_status = "PASSED_WITH_UNCALIBRATED"
            return {
                "gate_status": gate_status,
                "score": entry.get("score"),
                "calibration_status": (
                    "FIXTURE_UNCALIBRATED"
                    if fixture_protocol
                    else calibration or "PROVIDER_UNCALIBRATED"
                ),
                "human_verified": human,
                "provider_verified": provider,
                "evidence_source": segment.get("asset_version_id"),
                "evidence_locations": entry.get("evidence_locations") or [],
                "fixture_protocol_only": fixture_protocol,
            }
    return None


def _approved_fixture_waiver(
    dimension: str,
    segments: Iterable[dict[str, Any]],
    *,
    project_id: str,
    target_asset_version_id: str,
) -> dict[str, Any] | None:
    by_type = {str(item.get("asset_type")): item for item in segments}
    checklist = by_type.get("operator_checklist", {})
    approval = by_type.get("approval_decision") or by_type.get("operator_approval", {})
    checklist_facts = {
        str(item.get("key")): item.get("value")
        for item in checklist.get("structured_facts", [])
    }
    approval_facts = {
        str(item.get("key")): item.get("value")
        for item in approval.get("structured_facts", [])
    }
    scope = approval_facts.get("scope")
    dimensions = approval_facts.get("waived_dimensions")
    expiry = str(approval_facts.get("expiry") or "")
    try:
        expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return None
    if expires_at.tzinfo is None:
        return None
    valid = (
        bool(checklist.get("asset_version_id"))
        and checklist_facts.get("completed") is True
        and checklist_facts.get("contract_version") == "fixture-waiver-checklist-v1"
        and bool(approval.get("asset_version_id"))
        and approval_facts.get("contract_version") == "fixture-waiver-approval-v1"
        and approval_facts.get("decision") == "APPROVED"
        and approval_facts.get("fixture_protocol_only") is True
        and bool(str(approval_facts.get("waiver_reason") or "").strip())
        and isinstance(dimensions, list)
        and dimension in dimensions
        and isinstance(scope, dict)
        and scope.get("project_id") == project_id
        and scope.get("scope_type") == "PROJECT_FIXTURE"
        and scope.get("release_readiness") == "INTERNAL_REVIEW_RELEASE"
        and expires_at > datetime.now(timezone.utc)
    )
    if not valid:
        return None
    return {
        "approval_asset_version_id": approval["asset_version_id"],
        "checklist_asset_version_id": checklist["asset_version_id"],
        "reason": approval_facts["waiver_reason"],
        "dimension": dimension,
        "scope": scope,
        "target_asset_version_id": target_asset_version_id,
        "expiry": expiry,
        "fixture_protocol_only": True,
        "production_verified": False,
        "contract_version": "fixture-quality-waiver-v1",
    }


def _report(
    group: str,
    dimension: str,
    project_id: str,
    target: str,
    status: str,
    *,
    score: Any,
    calibration: str,
    source: str,
    locations: list[dict[str, Any]],
    fixture: bool,
    profile_ids: dict[str, str],
    provider_verified: bool = False,
    human_verified: bool = False,
) -> dict[str, Any]:
    return {
        "type": "ChapterQualityEvidence",
        "group": group,
        "project_id": project_id,
        "target_asset_version_id": target,
        "dimension": dimension,
        "gate_type": f"{group}_quality_gate",
        "score": score,
        "threshold": 70.0 if score is not None else None,
        "gate_status": status,
        "blocking": dimension in BLOCKING_DIMENSIONS,
        "weight": 1.0 if score is not None else 0.0,
        "calibration_status": calibration,
        "source": source,
        "evidence_locations": locations,
        "revision_strategy": []
        if status in {"PASSED", "PASSED_WITH_WARNINGS", "PASSED_WITH_UNCALIBRATED"}
        else [f"obtain or repair {dimension} evidence"],
        "confidence": 1.0 if calibration == "DETERMINISTIC" else 0.5,
        **profile_ids,
        "fixture": fixture,
        "production_verified": False,
        "provider_verified": provider_verified,
        "human_verified": human_verified,
        "contract_version": "chapter-quality-evidence-v2",
    }


def _profile_ids(context_bundle: dict[str, Any]) -> dict[str, str]:
    manifest = context_bundle.get("production_input_manifest", {})
    return {
        "quality_profile_version_id": str(
            manifest.get("quality_profile_version_id")
            or context_bundle.get("quality_profile_version")
            or ""
        ),
        "platform_profile_version_id": str(
            manifest.get("platform_profile_version_id")
            or context_bundle.get("platform_profile_version")
            or ""
        ),
    }


def _structural_metrics(text: str) -> dict[str, Any]:
    paragraphs = [item.strip() for item in re.split(r"\n+", text) if item.strip()]
    sentences = [
        item.strip() for item in re.split(r"[。！？!?\.]+", text) if item.strip()
    ]
    units = [len(item.split()) if " " in item else len(item) for item in sentences]
    normalized = [re.sub(r"\s+", " ", item.lower()) for item in sentences]
    return {
        "characters": len(text),
        "paragraphs": len(paragraphs) or 1,
        "sentences": len(sentences) or 1,
        "average_sentence": sum(units) / max(len(units), 1),
        "average_paragraph": len(text) / max(len(paragraphs), 1),
        "duplicate_sentence_ratio": (len(normalized) - len(set(normalized)))
        / max(len(normalized), 1),
    }


__all__ = [
    "BLOCKING_DIMENSIONS",
    "LONGITUDINAL_QUALITY_DIMENSIONS",
    "QUALITY_DIMENSIONS",
    "QUALITY_EVIDENCE_STATUSES",
    "QUALITY_GROUPS",
    "QUALITY_SCALES",
    "build_chapter_quality_evidence",
    "build_multiscale_quality_report",
    "build_quality_group_evidence",
]
