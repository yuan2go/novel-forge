from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_quality_authority.context_views import ConservativeTokenEstimator
from .diagnostics import prose_hash, validate_location


WINDOW_CONTRACT = "cross-chapter-review-window.v2"
WINDOW_POLICY = "accepted-prose-neighbours.v1"
COVERAGE_POLICY = "whole-paragraph-ending.v1"
CROSS_CHAPTER_CATEGORIES = frozenset(
    {
        "REDUNDANT_RETELLING",
        "CAUSAL_CARRYOVER",
        "SPATIAL_ACTION_CONTINUITY",
        "MOTIVATION_CONTINUITY",
        "RELATIONSHIP_CONTINUITY",
        "VOICE_DRIFT",
    }
)
PRESERVATION_DIMENSIONS = (
    "CHAPTER_MISSION",
    "REQUIRED_EVENTS",
    "CHARACTER_KNOWLEDGE",
    "POV",
    "VOICE",
    "FACTS",
    "SCENE_CAUSALITY",
    "KNOWLEDGE_MECHANISMS",
    "RESOLVED_ISSUES",
)


def digest(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )


def window_policy(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("version") != WINDOW_POLICY:
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_POLICY_INVALID", "unknown accepted prose policy"
        )
    count = value.get("maximum_previous_chapters", 2)
    budget = value.get("source_token_budget")
    if type(count) is not int or count < 1 or type(budget) is not int or budget <= 0:
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_POLICY_INVALID",
            "positive source count and bounded budget required",
        )
    return {
        "version": WINDOW_POLICY,
        "maximum_previous_chapters": count,
        "source_token_budget": budget,
        "coverage_policy": COVERAGE_POLICY,
    }


def validate_source_snapshot(snapshot: dict[str, Any]) -> None:
    body = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if snapshot.get("contract_version") != "accepted-prose-snapshot.v1" or snapshot.get(
        "snapshot_hash"
    ) != digest(body):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_SOURCE_INVALID", "source snapshot identity changed"
        )
    if any(
        not snapshot.get(key)
        for key in ("project_id", "workspace_id", "book_id", "book_run_id")
    ):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_SOURCE_INVALID", "Book scope is required"
        )
    frontier, target = (
        snapshot.get("accepted_through_chapter"),
        snapshot.get("target_chapter_number"),
    )
    if (
        type(frontier) is not int
        or type(target) is not int
        or target < 1
        or frontier != target - 1
    ):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_SOURCE_INVALID",
            "accepted frontier must precede the target",
        )
    policy = window_policy(snapshot["window_policy"])
    expected = list(range(max(1, target - policy["maximum_previous_chapters"]), target))
    sources = snapshot.get("sources")
    if (
        not isinstance(sources, list)
        or [source.get("chapter_number") for source in sources] != expected
    ):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_SOURCE_INVALID",
            "ordered accepted neighbour coverage is incomplete",
        )
    for source in sources:
        if (
            any(
                source.get(key) != snapshot[key]
                for key in ("project_id", "workspace_id", "book_id", "book_run_id")
            )
            or not source.get("asset_version_id")
            or not source.get("content_hash")
            or not source.get("acceptance_operation_id")
            or source.get("acceptance_status") != "COMMITTED"
            or not isinstance(source.get("text"), str)
            or not source["text"]
            or source.get("text_hash") != prose_hash(source["text"])
        ):
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_SOURCE_INVALID",
                "source is not exact accepted prose in this Book",
            )


def freeze_review_window(
    snapshot: dict[str, Any],
    *,
    candidate_id: str,
    text: str,
    context_token_budget: int,
    protected_context: dict[str, Any],
    required_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_source_snapshot(snapshot)
    if not candidate_id or not text:
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_TARGET_INVALID", "exact current candidate required"
        )
    policy = snapshot["window_policy"]
    meter = ConservativeTokenEstimator()
    safety_margin = 256
    required_cost = meter.estimate(
        json.dumps(
            {
                "text": text,
                "preservation": protected_context,
                "context": required_context or {},
            },
            ensure_ascii=False,
        )
    )
    remaining = min(policy["source_token_budget"], context_token_budget - required_cost - safety_margin)
    if remaining < 0:
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_CONTEXT_INSUFFICIENT",
            "required target and preservation exceed Context budget",
        )
    sources = []
    for source in reversed(snapshot["sources"]):
        prose = source["text"]
        ranges = [(0, len(prose))]
        coverage, reason = "FULL", "FULL_PROSE_FITS"
        if meter.estimate(prose) > remaining:
            paragraphs = list(re.finditer(r"[^\n]+(?:\n+|$)", prose))
            start = paragraphs[max(0, len(paragraphs) - 2)].start() if paragraphs else 0
            ranges = [(start, len(prose))]
            coverage, reason = "EXCERPT", "ONLY_COMPLETE_ENDING_PARAGRAPHS_FIT"
            if meter.estimate(prose[start:]) > remaining:
                if source["chapter_number"] == snapshot["accepted_through_chapter"]:
                    raise KernelError(
                        "CROSS_CHAPTER_REVIEW_CONTEXT_INSUFFICIENT",
                        "previous ending cannot be included without cutting its paragraph boundary",
                    )
                ranges, coverage, reason = [], "NOT_INCLUDED", "SOURCE_BUDGET_EXHAUSTED"
        excerpts = [
            {"start": start, "end": end, "text": prose[start:end]}
            for start, end in ranges
        ]
        remaining -= sum(meter.estimate(item["text"]) for item in excerpts)
        exclusions = (
            []
            if coverage == "FULL"
            else [{"start": 0, "end": ranges[0][0] if ranges else len(prose)}]
        )
        sources.append(
            {
                **{key: value for key, value in source.items() if key != "text"},
                "text_length": len(prose),
                "coverage": coverage,
                "coverage_reason": reason,
                "excerpts": excerpts,
                "excluded_ranges": exclusions,
            }
        )
    window = {
        **{key: deepcopy(value) for key, value in snapshot.items() if key != "sources"},
        "contract_version": WINDOW_CONTRACT,
        "sources": list(reversed(sources)),
        "target_candidate_asset_version_id": candidate_id,
        "target_candidate_text_hash": prose_hash(text),
        "coverage_policy": COVERAGE_POLICY,
        "context_token_budget": context_token_budget,
        "selection_accounting": "CONTEXT_TOKEN_ESTIMATE_V1",
        "selection_meter": {
            "identity": "ConservativeTokenEstimator",
            "version": "utf8-third-ceiling.v1",
            "precision": "ESTIMATE_ONLY",
            "model_policy": "MODEL_INDEPENDENT_SELECTION_ONLY",
            "safety_margin_tokens": safety_margin,
            "required_context_tokens": required_cost,
            "source_tokens": sum(meter.estimate(part["text"]) for source in sources for part in source["excerpts"]),
            "complete_request_admission": "FROZEN_ROUTE_METER_INCLUDING_PROMPT_SCHEMA_OUTPUT_RESERVE",
        },
        "provider_admission": "EXISTING_COMPLETE_REQUEST_TOKEN_ACCOUNTING_REQUIRED",
        "preservation_requirements": deepcopy(protected_context),
    }
    window["source_window_hash"] = digest(window)
    return window


def validate_window(window: dict[str, Any]) -> None:
    if window.get("contract_version") not in {WINDOW_CONTRACT, "cross-chapter-review-window.v1"} or window.get(
        "source_window_hash"
    ) != digest({k: v for k, v in window.items() if k != "source_window_hash"}):
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_WINDOW_INVALID",
            "frozen review window identity changed",
        )


def validate_support(evidence: Any, window: dict[str, Any]) -> list[dict[str, Any]]:
    validate_window(window)
    if not isinstance(evidence, list) or not evidence:
        raise KernelError(
            "CROSS_CHAPTER_REVIEW_EVIDENCE_REQUIRED",
            "cross-chapter diagnosis requires accepted supporting prose",
        )
    allowed = {source["asset_version_id"]: source for source in window["sources"]}
    normalized = []
    for item in evidence:
        source = (
            allowed.get(item.get("asset_version_id"))
            if isinstance(item, dict)
            else None
        )
        if (
            source is None
            or any(
                item.get(key) != source.get(key)
                for key in ("chapter_number", "content_hash", "text_hash")
            )
            or not str(item.get("relation_to_issue") or "").strip()
        ):
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_EVIDENCE_INVALID",
                "support must name an exact frozen accepted source",
            )
        start, end = item.get("start"), item.get("end")
        if type(start) is not int or type(end) is not int:
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_EVIDENCE_INVALID",
                "Unicode source offsets required",
            )
        excerpt = next(
            (
                part
                for part in source["excerpts"]
                if part["start"] <= start < end <= part["end"]
            ),
            None,
        )
        if excerpt is None:
            raise KernelError(
                "CROSS_CHAPTER_REVIEW_EVIDENCE_INVALID",
                "source span is outside reviewed coverage",
            )
        validated = validate_location(
            {
                "start": start - excerpt["start"],
                "end": end - excerpt["start"],
                "quote": item.get("quote"),
            },
            excerpt["text"],
        )
        normalized.append(
            {
                **item,
                "offset_unit": validated["offset_unit"],
                "excerpt_digest": validated["excerpt_digest"],
            }
        )
    return normalized


def coverage_report(window: dict[str, Any]) -> dict[str, Any]:
    validate_window(window)
    return {
        "source_window_hash": window["source_window_hash"],
        "reviewed_sources": [
            deepcopy(source)
            for source in window["sources"]
            if source["coverage"] != "NOT_INCLUDED"
        ],
        "excluded_sources": [
            deepcopy(source)
            for source in window["sources"]
            if source["coverage"] == "NOT_INCLUDED"
        ],
        "coverage_reason": "No conclusion about excluded ranges; exact accepted prose only.",
    }
