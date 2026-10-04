from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate

from .writer_projection import WRITER_PROSE_TYPES, project_writer_history

STORY_PROJECTION_VERSION = "accepted-writer-history.v2"
QUALITY_STAGES = frozenset({"review", "rereview", "longform_prose_review", "narrative_semantic_evaluation"})
HISTORY_FIELDS = frozenset({
    "selected_review", "candidate_comparison", "best_candidate_snapshot",
    "provider_evidence", "rejected_revision_check", "rejected_revision_checks",
    "revision_checks", "validation_evidence", "model_call_log", "cost_ledger",
    "context_bundle_id", "context_bundle_content_hash", "context_fingerprint",
    "retrieval_result_asset_version_id", "retrieval_result_fingerprint",
    "created_by_operation_id",
})


def visible_business_data(value: Any, *, stage: str, history: bool = False) -> Any:
    if stage in QUALITY_STAGES or stage.startswith("quality_") or stage == "reference_analysis":
        return deepcopy(value)
    if isinstance(value, Mapping):
        if value.get("provider_visibility") == "INTERNAL_QUALITY_ONLY":
            return None
        return {key: projected for key, item in value.items()
                if not (history and key in HISTORY_FIELDS)
                if (projected := visible_business_data(item, stage=stage, history=history)) is not None or item is None}
    if isinstance(value, (list, tuple)):
        return [projected for item in value
                if (projected := visible_business_data(item, stage=stage, history=history)) is not None or item is None]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(decoded, (dict, list)):
            projected = visible_business_data(decoded, stage=stage, history=history)
            return None if projected is None else json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return deepcopy(value)


def story_history(text: str, *, physical_type: str, stage: str = "draft") -> str:
    if physical_type in WRITER_PROSE_TYPES:
        projected = json.loads(project_writer_history(text, source_artifact_type=physical_type))
        source = json.loads(text)
        if source.get("structured_facts"):
            projected["structured_facts"] = visible_business_data(source["structured_facts"], stage=stage, history=True)
        return json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    projected = visible_business_data(text, stage=stage, history=True)
    return projected if isinstance(projected, str) else ""


def clean_context_candidate(candidate: ContextCandidate, *, stage: str) -> ContextCandidate:
    if candidate.allowed_use == "evidence_only":
        return candidate
    if stage in QUALITY_STAGES or stage.startswith("quality_") or stage == "reference_analysis":
        return candidate
    prose = candidate.physical_asset_type in WRITER_PROSE_TYPES or candidate.asset_type in WRITER_PROSE_TYPES or candidate.narrative_function == "recent_accepted_prose"
    current_draft = stage == "revision" and candidate.asset_type in {"draft_chapter", "draft_version", "review_report", "review_issue"}
    if current_draft:
        return candidate
    if candidate.compression_trace:
        if prose and not all(row.get("writer_projection_version") == STORY_PROJECTION_VERSION for row in candidate.compression_trace):
            raise KernelError("WRITER_HISTORY_REBUILD_REQUIRED", "historical compressed prose requires a clean original-source projection; rebuild instead of summarizing its summary")
        summary = candidate.safe_summary if prose else visible_business_data(candidate.safe_summary, stage=stage, history=True)
    else:
        summary = story_history(candidate.safe_summary, physical_type="best_draft_candidate" if prose else candidate.physical_asset_type, stage=stage)
    facts = visible_business_data(list(candidate.structured_facts), stage=stage, history=True)
    from .task_context import serialized_token_upper_bound
    amount = max(1, serialized_token_upper_bound({"safe_summary": summary or "", "structured_facts": facts}))
    return replace(candidate, safe_summary=summary or "", structured_facts=tuple(facts), estimated_tokens=amount, truncation_strategy="",
                   provenance={**dict(candidate.provenance or {}), "writer_projection_version": STORY_PROJECTION_VERSION})


def clean_context_candidates(candidates: list[ContextCandidate], *, stage: str) -> list[ContextCandidate]:
    return [clean_context_candidate(candidate, stage=stage) for candidate in candidates]
