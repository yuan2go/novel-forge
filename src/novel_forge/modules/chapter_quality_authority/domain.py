"""Storage-free grouped quality evidence for the Chapter Authority Saga.

Deterministic checks only decide properties they can actually observe.  Semantic
dimensions require a versioned calibrated evidence asset and otherwise fail
closed with an explicit non-passing status.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


QUALITY_GROUPS: dict[str, tuple[str, ...]] = {
    "structural": (
        "readability", "mobile_reading", "chapter_economy", "basic_prose_integrity",
        "scene_completeness", "dialogue_narration_balance", "paragraph_structure",
        "repetition", "summary_like_prose",
    ),
    "commercial": (
        "golden_opening", "reader_promise", "reward", "protagonist_charm",
        "antagonist_pressure", "toxic_point", "chapter_hook", "suspense_progression",
        "emotional_curve", "serialization_function",
    ),
    "source_originality": (
        "source_leakage", "originality", "anti_ai", "style_drift", "copyright_boundary",
    ),
    "longform": (
        "canon_consistency", "character_motivation_drift", "relationship_continuity",
        "timeline_consistency", "foreshadow_status", "promise_payoff_debt",
        "world_rule_conflict", "power_state_conflict", "narrative_pattern_repetition",
        "arc_progress",
    ),
    "platform": (
        "chapter_length", "format", "sensitive_content", "ai_content_policy",
        "opening_expectations", "platform_rhythm", "publish_metadata",
    ),
}
QUALITY_DIMENSIONS = tuple(item for values in QUALITY_GROUPS.values() for item in values)
QUALITY_EVIDENCE_STATUSES = frozenset({
    "PASSED", "PASSED_WITH_WARNINGS", "PASSED_WITH_UNCALIBRATED", "FAILED", "UNCALIBRATED",
    "INSUFFICIENT_EVIDENCE", "REQUIRES_PROVIDER_JUDGE", "REQUIRES_HUMAN_REVIEW",
    "WAIVED_BY_APPROVAL",
})
BLOCKING_DIMENSIONS = frozenset({
    "readability", "basic_prose_integrity", "source_leakage", "originality", "anti_ai",
    "copyright_boundary", "canon_consistency", "timeline_consistency", "world_rule_conflict",
    "power_state_conflict", "chapter_length", "format", "sensitive_content",
    "ai_content_policy", "publish_metadata",
})


def build_quality_group_evidence(
    *, group: str, project_id: str, revision: dict[str, Any],
    revision_asset_version_id: str, context_bundle: dict[str, Any],
    canon: dict[str, Any], fixture: bool,
) -> dict[str, Any]:
    if group not in QUALITY_GROUPS:
        raise KernelError("QUALITY_GROUP_INVALID", f"unknown quality group: {group}")
    text = str(revision.get("text") or "").strip()
    if not all((project_id, revision_asset_version_id, text)):
        raise KernelError("QUALITY_EVIDENCE_INPUT_INVALID", "quality target lineage is incomplete")
    metrics = _structural_metrics(text)
    segments = tuple(context_bundle.get("context_segments", ()))
    profile_ids = _profile_ids(context_bundle)
    reports = [
        _evaluate(
            group=group, dimension=dimension, project_id=project_id,
            target=revision_asset_version_id, metrics=metrics, segments=segments,
            context_bundle=context_bundle, canon=canon, fixture=fixture,
            profile_ids=profile_ids,
        )
        for dimension in QUALITY_GROUPS[group]
    ]
    blocked = [item for item in reports if item["blocking"] and item["gate_status"] not in {"PASSED", "PASSED_WITH_WARNINGS", "PASSED_WITH_UNCALIBRATED", "WAIVED_BY_APPROVAL"}]
    group_status = "FAILED" if any(item["gate_status"] == "FAILED" for item in blocked) else (
        "INSUFFICIENT_EVIDENCE" if blocked else
        "PASSED_WITH_WARNINGS" if any(item["gate_status"] != "PASSED" for item in reports) else "PASSED"
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


def _evaluate(
    *, group: str, dimension: str, project_id: str, target: str,
    metrics: dict[str, Any], segments: tuple[dict[str, Any], ...],
    context_bundle: dict[str, Any], canon: dict[str, Any], fixture: bool,
    profile_ids: dict[str, str],
) -> dict[str, Any]:
    calibrated = _calibrated_evidence(
        dimension, segments, target_asset_version_id=target, fixture=fixture
    )
    if calibrated is not None:
        status = str(calibrated.get("gate_status") or "INSUFFICIENT_EVIDENCE").upper()
        if status not in QUALITY_EVIDENCE_STATUSES:
            raise KernelError("QUALITY_EVIDENCE_STATUS_INVALID", f"invalid {dimension} evidence status")
        return _report(
            group, dimension, project_id, target, status,
            score=calibrated.get("score"), calibration=str(calibrated["calibration_status"]),
            source=str(calibrated.get("evidence_source") or "authority_asset"),
            locations=list(calibrated.get("evidence_locations") or []),
            fixture=fixture, profile_ids=profile_ids,
            provider_verified=bool(calibrated.get("provider_verified")),
            human_verified=bool(calibrated.get("human_verified")),
        )

    source_clear = bool(context_bundle.get("source_isolation_result", {}).get("passed")) and all(
        not segment.get("source_expression_included", True) for segment in segments
    )
    if dimension in {"source_leakage", "copyright_boundary"}:
        passed = source_clear and context_bundle.get("copyright_boundary") == "abstract_or_project_owned_only"
        return _report(group, dimension, project_id, target, "PASSED" if passed else "FAILED", score=None, calibration="DETERMINISTIC", source="context_source_isolation", locations=[{"source_clear": source_clear, "copyright_boundary": context_bundle.get("copyright_boundary")}], fixture=fixture, profile_ids=profile_ids)
    if dimension == "readability":
        average = float(metrics["average_sentence"])
        score = round(max(0.0, min(100.0, 100.0 - max(0.0, average - 36.0) * 2.0)), 2)
        return _report(group, dimension, project_id, target, "PASSED" if score >= 70 else "FAILED", score=score, calibration="DETERMINISTIC", source="readability_metrics", locations=[{"average_sentence_length": average}], fixture=fixture, profile_ids=profile_ids)
    if dimension in {"mobile_reading", "paragraph_structure"}:
        average = float(metrics["average_paragraph"])
        status = "PASSED" if average <= 270 else "FAILED"
        return _report(group, dimension, project_id, target, status, score=None, calibration="DETERMINISTIC", source="mobile_paragraph_metrics", locations=[{"average_paragraph_length": average}], fixture=fixture, profile_ids=profile_ids)
    if dimension == "basic_prose_integrity":
        passed = metrics["sentences"] >= 2 and metrics["characters"] >= 80
        return _report(group, dimension, project_id, target, "PASSED" if passed else "FAILED", score=None, calibration="DETERMINISTIC", source="prose_integrity_metrics", locations=[metrics], fixture=fixture, profile_ids=profile_ids)
    if dimension == "repetition":
        ratio = float(metrics["duplicate_sentence_ratio"])
        return _report(group, dimension, project_id, target, "PASSED" if ratio <= .25 else "FAILED", score=None, calibration="DETERMINISTIC", source="repetition_metrics", locations=[{"duplicate_sentence_ratio": ratio}], fixture=fixture, profile_ids=profile_ids)
    if dimension == "canon_consistency":
        conflicts = list(canon.get("conflicts") or [])
        return _report(group, dimension, project_id, target, "PASSED" if not conflicts else "FAILED", score=None, calibration="DETERMINISTIC", source="canon_reduction", locations=[{"conflict_count": len(conflicts)}], fixture=fixture, profile_ids=profile_ids)
    # Profile existence is deterministic; profile-specific compliance is not.
    if group == "platform" and not profile_ids["platform_profile_version_id"]:
        status = "INSUFFICIENT_EVIDENCE"
    elif group in {"commercial", "source_originality"}:
        status = "REQUIRES_PROVIDER_JUDGE"
    else:
        status = "INSUFFICIENT_EVIDENCE"
    return _report(group, dimension, project_id, target, status, score=None, calibration="FIXTURE_UNCALIBRATED" if fixture else "PROVIDER_UNCALIBRATED", source="none", locations=[], fixture=fixture, profile_ids=profile_ids)


def _calibrated_evidence(
    dimension: str,
    segments: Iterable[dict[str, Any]],
    *,
    target_asset_version_id: str,
    fixture: bool,
) -> dict[str, Any] | None:
    for segment in segments:
        facts = {str(item.get("key")): item.get("value") for item in segment.get("structured_facts", [])}
        entries = list(facts.get("dimension_evidence") or [])
        entries.append(facts)
        for entry in entries:
            if str(entry.get("dimension") or segment.get("narrative_function") or "") != dimension:
                continue
            target = str(entry.get("target_asset_version_id") or "")
            fixture_protocol = fixture and entry.get("fixture_protocol_only") is True
            if target != target_asset_version_id and not fixture_protocol:
                continue
            calibration = str(entry.get("calibration_status") or "").upper()
            human = entry.get("human_verified") is True
            provider = entry.get("provider_verified") is True
            qualified = calibration in {
                "HUMAN_CALIBRATED",
                "GOLDEN_SET_CALIBRATED",
            } and not fixture_protocol
            if not qualified and not fixture_protocol:
                continue
            gate_status = entry.get("gate_status")
            if fixture_protocol and str(gate_status).upper() == "PASSED":
                gate_status = "PASSED_WITH_UNCALIBRATED"
            return {
                "gate_status": gate_status, "score": entry.get("score"),
                "calibration_status": (
                    "FIXTURE_UNCALIBRATED"
                    if fixture_protocol
                    else calibration or "PROVIDER_UNCALIBRATED"
                ),
                "human_verified": human, "provider_verified": provider,
                "evidence_source": segment.get("asset_version_id"),
                "evidence_locations": entry.get("evidence_locations") or [],
                "fixture_protocol_only": fixture_protocol,
            }
    return None


def _report(group: str, dimension: str, project_id: str, target: str, status: str, *, score: Any, calibration: str, source: str, locations: list[dict[str, Any]], fixture: bool, profile_ids: dict[str, str], provider_verified: bool = False, human_verified: bool = False) -> dict[str, Any]:
    return {
        "type": "ChapterQualityEvidence", "group": group, "project_id": project_id,
        "target_asset_version_id": target, "dimension": dimension,
        "gate_type": f"{group}_quality_gate", "score": score,
        "threshold": 70.0 if score is not None else None, "gate_status": status,
        "blocking": dimension in BLOCKING_DIMENSIONS, "weight": 1.0 if score is not None else 0.0,
        "calibration_status": calibration, "source": source,
        "evidence_locations": locations, "revision_strategy": [] if status in {"PASSED", "PASSED_WITH_WARNINGS", "PASSED_WITH_UNCALIBRATED"} else [f"obtain or repair {dimension} evidence"],
        "confidence": 1.0 if calibration == "DETERMINISTIC" else .5,
        **profile_ids, "fixture": fixture, "production_verified": False,
        "provider_verified": provider_verified, "human_verified": human_verified,
        "contract_version": "chapter-quality-evidence-v2",
    }


def _profile_ids(context_bundle: dict[str, Any]) -> dict[str, str]:
    manifest = context_bundle.get("production_input_manifest", {})
    return {
        "quality_profile_version_id": str(manifest.get("quality_profile_version_id") or context_bundle.get("quality_profile_version") or ""),
        "platform_profile_version_id": str(manifest.get("platform_profile_version_id") or context_bundle.get("platform_profile_version") or ""),
    }


def _structural_metrics(text: str) -> dict[str, Any]:
    paragraphs = [item.strip() for item in re.split(r"\n+", text) if item.strip()]
    sentences = [item.strip() for item in re.split(r"[。！？!?\.]+", text) if item.strip()]
    units = [len(item.split()) if " " in item else len(item) for item in sentences]
    normalized = [re.sub(r"\s+", " ", item.lower()) for item in sentences]
    return {
        "characters": len(text), "paragraphs": len(paragraphs) or 1,
        "sentences": len(sentences) or 1,
        "average_sentence": sum(units) / max(len(units), 1),
        "average_paragraph": len(text) / max(len(paragraphs), 1),
        "duplicate_sentence_ratio": (len(normalized) - len(set(normalized))) / max(len(normalized), 1),
    }


__all__ = ["BLOCKING_DIMENSIONS", "QUALITY_DIMENSIONS", "QUALITY_EVIDENCE_STATUSES", "QUALITY_GROUPS", "build_chapter_quality_evidence", "build_quality_group_evidence"]
