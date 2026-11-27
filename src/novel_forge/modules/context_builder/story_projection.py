from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate

from .writer_projection import WRITER_PROSE_TYPES, project_writer_history
from . import source_json

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


def visible_business_data(value: Any, *, stage: str, history: bool = False, preserve_json: bool = False) -> Any:
    if stage in QUALITY_STAGES or stage.startswith("quality_") or stage == "reference_analysis":
        return deepcopy(value)
    if isinstance(value, Mapping):
        if value.get("provider_visibility") == "INTERNAL_QUALITY_ONLY":
            return None
        return {key: projected for key, item in value.items()
                if not (history and key in HISTORY_FIELDS)
                if (projected := visible_business_data(item, stage=stage, history=history, preserve_json=preserve_json)) is not None or item is None}
    if isinstance(value, (list, tuple)):
        return [projected for item in value
                if (projected := visible_business_data(item, stage=stage, history=history, preserve_json=preserve_json)) is not None or item is None]
    if isinstance(value, str):
        try:
            decoded = source_json.loads(value) if preserve_json else json.loads(value)
        except KernelError:
            raise
        except (ValueError, TypeError):
            return value
        if isinstance(decoded, (dict, list)):
            projected = visible_business_data(decoded, stage=stage, history=history, preserve_json=preserve_json)
            return None if projected is None else source_json.dumps(projected) if preserve_json else json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return deepcopy(value)


def story_history(text: str, *, physical_type: str, stage: str = "draft", preserve_json: bool = False) -> str:
    if physical_type in WRITER_PROSE_TYPES:
        decode = source_json.loads if preserve_json else json.loads
        projected = decode(project_writer_history(text, source_artifact_type=physical_type, preserve_json=preserve_json))
        source = decode(text)
        if source.get("structured_facts"):
            projected["structured_facts"] = visible_business_data(source["structured_facts"], stage=stage, history=True, preserve_json=preserve_json)
        return source_json.dumps(projected) if preserve_json else json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    projected = visible_business_data(text, stage=stage, history=True, preserve_json=preserve_json)
    return projected if isinstance(projected, str) else ""


def clean_context_candidate(candidate: ContextCandidate, *, stage: str, preserve_json: bool = False) -> ContextCandidate:
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
        summary = candidate.safe_summary if prose else visible_business_data(candidate.safe_summary, stage=stage, history=True, preserve_json=preserve_json)
    else:
        summary = story_history(candidate.safe_summary, physical_type="best_draft_candidate" if prose else candidate.physical_asset_type, stage=stage, preserve_json=preserve_json)
    facts = visible_business_data(list(candidate.structured_facts), stage=stage, history=True, preserve_json=preserve_json)
    from .task_context import serialized_token_upper_bound
    amount = max(1, serialized_token_upper_bound({"safe_summary": summary or "", "structured_facts": facts}))
    return replace(candidate, safe_summary=summary or "", structured_facts=tuple(facts), estimated_tokens=amount, truncation_strategy="",
                   provenance={**dict(candidate.provenance or {}), "writer_projection_version": STORY_PROJECTION_VERSION})


def clean_context_candidates(candidates: list[ContextCandidate], *, stage: str, preserve_json: bool = False) -> list[ContextCandidate]:
    return [clean_context_candidate(candidate, stage=stage, preserve_json=preserve_json) for candidate in candidates]


SOURCE_JSON_PROJECTION = "source-json-values.v1"


def restore_source_json_fields(text: str, source: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    from novel_forge.modules.narrative_state.reality import narrative_hash

    try:
        projected = source_json.loads(text)
    except KernelError:
        raise
    except (ValueError, TypeError):
        return text, []
    bindings = []

    def contains_json_string(value):
        if isinstance(value, str):
            try:
                return isinstance(source_json.loads(value), (dict, list))
            except KernelError:
                return True
            except (ValueError, TypeError):
                return False
        if isinstance(value, Mapping):
            return any(contains_json_string(child) for child in value.values())
        if isinstance(value, list):
            return any(contains_json_string(child) for child in value)
        return False

    def restore(value, original, path=(), selected_path=()):
        if isinstance(value, Mapping) and isinstance(original, Mapping):
            from .semantic_units import ATTRIBUTION_FIELDS
            if contains_json_string(original) and any(source_json.dumps(value[key]) != source_json.dumps(original[key])
                    for key in set(value) & set(original) & ATTRIBUTION_FIELDS):
                raise KernelError("CONTEXT_SOURCE_JSON_SCOPE_CHANGED", "selected JSON record changed its original identity or attribution")
            return {key: restore(child, original[key], (*path, key), (*selected_path, key)) if key in original else child for key, child in value.items()}
        if isinstance(value, list) and isinstance(original, list):
            if not contains_json_string(original):
                return value
            by_projection = {}
            for position, item in enumerate(original):
                for exact in (False, True):
                    represented = visible_business_data(item, stage="draft", history=True, preserve_json=exact)
                    if represented is not None or item is None:
                        by_projection.setdefault(source_json.dumps(represented), set()).add(position)
            result, used = [], set()
            for index, child in enumerate(value):
                matches = by_projection.get(source_json.dumps(child), set())
                if len(matches) != 1:
                    raise KernelError("CONTEXT_SOURCE_JSON_SCOPE_CHANGED", "filtered JSON list requires an unambiguous original element; rebuild its source scope")
                position = next(iter(matches))
                if position in used:
                    raise KernelError("CONTEXT_SOURCE_JSON_SCOPE_CHANGED", "selected JSON list repeats an original element without a declared reference")
                used.add(position)
                result.append(restore(child, original[position], (*path, position), (*selected_path, index)))
            return result
        if isinstance(value, str) and isinstance(original, str):
            try:
                document = source_json.loads(original)
            except KernelError:
                raise
            except (ValueError, TypeError):
                return value
            if not isinstance(document, (dict, list)):
                return value
            exact = visible_business_data(original, stage="draft", history=True, preserve_json=True)
            legacy = visible_business_data(original, stage="draft", history=True)
            if value not in (original, exact, legacy):
                raise KernelError("CONTEXT_SOURCE_JSON_SCOPE_CHANGED", "selected JSON field differs from its exact source and known projection; rebuild the original scoped projection")
            bindings.append({"source_field_path": list(path), "selected_field_path": list(selected_path), "original_field_hash": narrative_hash(original),
                "previous_projection_hash": narrative_hash(value), "projected_field_hash": narrative_hash(exact)})
            return exact
        return value

    result = restore(projected, source)
    return source_json.dumps(result), bindings
