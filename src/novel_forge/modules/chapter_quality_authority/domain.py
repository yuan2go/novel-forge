from __future__ import annotations

import re
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


QUALITY_DIMENSIONS = (
    "readability",
    "golden_opening",
    "chapter_economy",
    "reader_promise",
    "reward",
    "toxic_point",
    "protagonist_charm",
    "antagonist_pressure",
    "mobile_reading",
    "style_drift",
    "originality",
    "source_leakage",
    "anti_ai",
    "platform_rules",
    "longform_stability",
)

GATE_TYPES = {
    "readability": "commercial_readability_gate",
    "golden_opening": "commercial_readability_gate",
    "chapter_economy": "commercial_readability_gate",
    "reader_promise": "semantic_quality_gate",
    "reward": "commercial_readability_gate",
    "toxic_point": "semantic_quality_gate",
    "protagonist_charm": "semantic_quality_gate",
    "antagonist_pressure": "semantic_quality_gate",
    "mobile_reading": "commercial_readability_gate",
    "style_drift": "semantic_quality_gate",
    "originality": "source_originality_gate",
    "source_leakage": "source_originality_gate",
    "anti_ai": "source_originality_gate",
    "platform_rules": "commercial_readability_gate",
    "longform_stability": "longform_stability_gate",
}

BLOCKING_DIMENSIONS = frozenset(
    {"readability", "source_leakage", "originality", "anti_ai", "platform_rules"}
)


def build_chapter_quality_evidence(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle: dict[str, Any],
    canon: dict[str, Any],
    fixture: bool,
) -> list[dict[str, Any]]:
    text = str(revision.get("text") or "").strip()
    if not all((project_id, revision_asset_version_id, text)):
        raise KernelError("QUALITY_EVIDENCE_INPUT_INVALID", "quality target lineage is incomplete")
    metrics = _structural_metrics(text)
    source_clear = bool(context_bundle.get("source_isolation_result", {}).get("passed")) and all(
        not segment.get("source_expression_included", True)
        for segment in context_bundle.get("context_segments", [])
    )
    reports: list[dict[str, Any]] = []
    for dimension in QUALITY_DIMENSIONS:
        score, status, calibration, source, locations, strategy = _evaluate_dimension(
            dimension,
            metrics=metrics,
            source_clear=source_clear,
            canon=canon,
            fixture=fixture,
        )
        reports.append(
            {
                "type": "ChapterQualityEvidence",
                "project_id": project_id,
                "target_asset_version_id": revision_asset_version_id,
                "dimension": dimension,
                "gate_type": GATE_TYPES[dimension],
                "score": score,
                "threshold": 70.0 if score is not None else None,
                "gate_status": status,
                "blocking": dimension in BLOCKING_DIMENSIONS,
                "weight": 1.0 if score is not None else 0.0,
                "calibration_status": calibration,
                "source": source,
                "provider_evidence": {},
                "evidence_locations": locations,
                "revision_strategy": strategy,
                "confidence": 1.0 if calibration == "DETERMINISTIC" else 0.5,
                "contract_version": "chapter-quality-evidence-v1",
                "fixture": fixture,
                "production_verified": False,
            }
        )
    return reports


def _structural_metrics(text: str) -> dict[str, Any]:
    paragraphs = [item.strip() for item in re.split(r"\n+", text) if item.strip()]
    sentences = [item.strip() for item in re.split(r"[。！？!?]+", text) if item.strip()]
    sentence_units = [
        len(item.split()) if " " in item else len(item)
        for item in sentences
    ]
    return {
        "characters": len(text),
        "paragraphs": len(paragraphs) or 1,
        "sentences": len(sentences) or 1,
        "average_sentence": sum(sentence_units) / max(len(sentence_units), 1),
        "average_paragraph": len(text) / max(len(paragraphs), 1),
        "dialogue_marks": text.count("“") + text.count('"'),
        "cost_terms": sum(text.lower().count(term) for term in ("cost", "lose", "surrender", "代价", "失去")),
        "action_terms": sum(text.lower().count(term) for term in ("choice", "decide", "acts", "选择", "决定")),
        "hook_terms": sum(text.lower().count(term) for term in ("but", "however", "yet", "却", "然而")),
    }


def _evaluate_dimension(
    dimension: str,
    *,
    metrics: dict[str, Any],
    source_clear: bool,
    canon: dict[str, Any],
    fixture: bool,
) -> tuple[float | None, str, str, str, list[dict[str, Any]], list[str]]:
    if dimension == "source_leakage":
        return (
            None,
            "PASSED" if source_clear else "FAILED",
            "DETERMINISTIC",
            "deterministic_extractor",
            [{"kind": "context_source_isolation", "passed": source_clear}],
            [] if source_clear else ["remove ineligible or source-expression context segments"],
        )
    if dimension == "readability":
        average = float(metrics["average_sentence"])
        score = max(0.0, min(100.0, 100.0 - max(0.0, average - 36.0) * 2.0))
        return (
            round(score, 2),
            "PASSED" if score >= 70 else "FAILED",
            "DETERMINISTIC",
            "deterministic_extractor",
            [{"kind": "average_sentence_length", "value": average}],
            [] if score >= 70 else ["split long sentences and restore action clarity"],
        )
    if dimension == "mobile_reading":
        average = float(metrics["average_paragraph"])
        score = max(0.0, min(100.0, 100.0 - max(0.0, average - 180.0) / 3.0))
        return (
            round(score, 2),
            "PASSED" if score >= 70 else "PASSED_WITH_WARNINGS",
            "DETERMINISTIC",
            "deterministic_extractor",
            [{"kind": "average_paragraph_length", "value": average}],
            [] if score >= 70 else ["shorten dense mobile paragraphs"],
        )
    if dimension == "longform_stability":
        conflicts = list(canon.get("conflicts", []))
        status = "FAILED" if conflicts else "PASSED"
        return (
            None,
            status,
            "DETERMINISTIC",
            "deterministic_extractor",
            [{"kind": "canon_conflicts", "count": len(conflicts)}],
            [] if not conflicts else ["resolve Canon conflicts before release"],
        )
    # These dimensions require Provider or human calibration for semantic quality.
    # A deterministic fixture may prove the evidence plumbing, never production quality.
    heuristic = {
        "golden_opening": metrics["hook_terms"],
        "chapter_economy": metrics["action_terms"] + metrics["cost_terms"],
        "reader_promise": metrics["cost_terms"],
        "reward": metrics["cost_terms"],
        "toxic_point": 1,
        "protagonist_charm": metrics["action_terms"],
        "antagonist_pressure": metrics["cost_terms"],
        "style_drift": 1,
        "originality": 1 if source_clear else 0,
        "anti_ai": 1,
        "platform_rules": 1,
    }.get(dimension, 0)
    status = "PASSED" if fixture and heuristic else "UNCALIBRATED"
    return (
        None,
        status,
        "FIXTURE_UNCALIBRATED" if fixture else "PROVIDER_UNCALIBRATED",
        "fixture" if fixture else "none",
        [{"kind": "heuristic_signal_count", "value": heuristic}],
        [] if status == "PASSED" else [f"obtain calibrated {dimension} evidence"],
    )
