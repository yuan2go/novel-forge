"""Task-specific Provider projections from immutable Chapter Authority inputs.

The full ContextBundle and Capability materialization remain replay evidence.  This
module is the only Chapter path allowed to turn those Authority records into model
working context, so audit and duplicate representations cannot leak by accident.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


_MAX_SEGMENTS = 24
_MAX_FACTS_PER_SEGMENT = 32
_MAX_SUMMARY_CHARACTERS = 1200
_MAX_PROVIDER_CONTEXT_CHARACTERS = 65_536
_MAX_PROVIDER_KNOWLEDGE_CHARACTERS = 65_536
_STATE_ASSET_TYPES = {"story_state_snapshot", "canon_snapshot"}
_OPERATIONAL_KEYS = {
    "actual_context",
    "actual_context_digest",
    "context",
    "context_digest",
    "context_manifest",
    "created_by_operation_id",
    "normalized_digest",
    "provider_evidence",
    "qualification",
    "source_chapter_plan_asset_version_id",
    "source_chapter_plan_content_hash",
    "source_extensions",
    "stage_context_view",
    "trace_id",
}


def build_provider_task_view(stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return one non-duplicated stage payload without Authority audit metadata."""

    if stage == "draft":
        return _task(
            stage,
            chapter_plan=_compact(inputs.get("plan")),
            style=_compact(inputs.get("style")),
        )
    if stage == "review":
        return _task(stage, chapter=_prose(inputs.get("draft")))
    if stage == "revision":
        payload: dict[str, Any] = {"chapter": _prose(inputs.get("draft"))}
        if inputs.get("required_actions") is not None:
            payload["required_actions"] = _compact(inputs.get("required_actions"))
            payload["quality_decision"] = _compact(inputs.get("quality"))
        else:
            payload["review_issues"] = _compact(
                dict(inputs.get("review") or {}).get("issues") or []
            )
        return _task(stage, **payload)
    if stage == "rereview":
        revision = inputs.get("revision") or inputs.get("draft")
        issues = [
            _compact(item)
            for item in dict(inputs.get("review") or {}).get("issues") or []
            if str(item.get("severity") or "").lower()
            in {"critical", "blocker", "blocking", "high", "major"}
        ]
        return _task(
            stage,
            revised_chapter=_prose(revision),
            prior_blocking_issues=issues,
        )
    if stage == "canon_extraction":
        return _task(stage, accepted_revision=_prose(inputs.get("revision")))
    if stage.startswith("quality_"):
        return _task(
            stage,
            chapter=_prose(inputs.get("revision")),
            quality_context=_compact(inputs.get("quality_context")),
            dimensions=_compact(inputs.get("dimensions")),
        )
    if stage == "reader_outcome":
        return _task(
            stage,
            chapter=_prose(
                inputs.get("revision") or inputs.get("draft") or inputs.get("chapter")
            ),
            reader_contract=_compact(inputs.get("reader_contract")),
        )
    raise KernelError(
        "CHAPTER_PROVIDER_TASK_VIEW_UNSUPPORTED",
        f"Provider Task View is not defined for stage {stage}",
    )


def build_provider_context_view(
    stage: str,
    context_bundle: Mapping[str, Any],
    task_view: Mapping[str, Any],
) -> dict[str, Any]:
    """Project Minimum Sufficient Context with deterministic bounded cardinality."""

    segments = context_bundle.get("context_segments")
    if not isinstance(segments, list):
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_VIEW_INVALID",
            "ContextBundle requires canonical context_segments",
        )
    projection = context_bundle.get("task_narrative_projection") or {}
    if not isinstance(projection, Mapping):
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_VIEW_INVALID",
            "task_narrative_projection must be an object",
        )
    selectors = _selectors(projection, task_view)
    if (
        not projection
        and any(
            isinstance(item, Mapping)
            and str(item.get("asset_type") or "") in _STATE_ASSET_TYPES
            and list(item.get("structured_facts") or ())
            for item in segments
        )
        and not selectors
    ):
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_PROJECTION_REQUIRED",
            "state-bearing ContextBundle requires a task narrative projection; "
            "rebuild Context from the accepted checkpoint",
        )
    rendered: list[dict[str, Any]] = []
    omitted_facts = 0
    omitted_segments = 0
    for raw in segments:
        if len(rendered) >= _MAX_SEGMENTS:
            omitted_segments += 1
            omitted_facts += (
                len(raw.get("structured_facts") or [])
                if isinstance(raw, Mapping)
                else 0
            )
            continue
        if not isinstance(raw, Mapping) or raw.get("allowed_use") == "evidence_only":
            omitted_segments += 1
            continue
        asset_type = str(raw.get("asset_type") or "")
        if stage == "draft" and asset_type in {"chapter_plan", "style_policy"}:
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        if stage.startswith("quality_"):
            # QualityContext is already a bounded, dimension-specific projection.
            # Rendering Context segments again would duplicate the same semantics.
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        facts = [
            item
            for item in raw.get("structured_facts") or []
            if isinstance(item, Mapping)
        ]
        selected_facts = facts
        if asset_type in _STATE_ASSET_TYPES:
            selected_facts = [
                item
                for item in facts
                if _state_fact_relevant(item, selectors, context_bundle)
            ]
        included_facts = selected_facts[:_MAX_FACTS_PER_SEGMENT]
        omitted_facts += len(facts) - len(included_facts)
        selected_facts = included_facts
        summary = str(raw.get("safe_summary") or "").strip()
        if not summary and not selected_facts:
            omitted_segments += 1
            continue
        rendered.append(
            {
                "asset_version_id": str(raw.get("asset_version_id") or ""),
                "asset_type": asset_type,
                "narrative_function": str(raw.get("narrative_function") or ""),
                "safe_summary": summary[:_MAX_SUMMARY_CHARACTERS],
                "structured_facts": [deepcopy(dict(item)) for item in selected_facts],
            }
        )
    manifest = context_bundle.get("context_manifest") or {}
    position = (
        dict(manifest.get("narrative_position") or {})
        if isinstance(manifest, Mapping)
        else {}
    )
    boundary = (
        dict(manifest.get("authority_state_boundary") or {})
        if isinstance(manifest, Mapping)
        else {}
    )
    view = {
        "contract_version": "provider-context-view-v1",
        "stage": stage,
        "narrative_position": {
            key: position[key]
            for key in (
                "book_id",
                "volume_id",
                "chapter",
                "sequence_id",
                "sequence_ordinal",
            )
            if key in position
        },
        "accepted_state_boundary": {
            "accepted_through_chapter": int(
                boundary.get("accepted_through_chapter") or 0
            )
        },
        "task_narrative_projection": _compact(dict(projection)),
        "segments": rendered,
        "selection_explanation": {
            "policy": "minimum-sufficient-context-v1",
            "included_segment_count": len(rendered),
            "included_fact_count": sum(
                len(item["structured_facts"]) for item in rendered
            ),
            "omitted_segment_count": omitted_segments,
            "omitted_fact_count": omitted_facts,
            "maximum_segments": _MAX_SEGMENTS,
            "maximum_facts_per_segment": _MAX_FACTS_PER_SEGMENT,
            "maximum_serialized_characters": _MAX_PROVIDER_CONTEXT_CHARACTERS,
        },
    }
    if _serialized_character_count(view) > _MAX_PROVIDER_CONTEXT_CHARACTERS:
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
            "projected Provider Context exceeds its deterministic size boundary; "
            "rebuild the task projection with fewer accepted facts",
        )
    return view


def build_provider_knowledge_view(
    knowledge: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate selected MKAOS/Skill knowledge and remove deployment evidence."""

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in knowledge:
        content = item.get("content")
        if not isinstance(content, (Mapping, list, str)):
            raise KernelError(
                "CHAPTER_PROVIDER_KNOWLEDGE_VIEW_INVALID",
                "selected Knowledge requires provider-safe content",
            )
        identity = str(
            item.get("content_hash")
            or item.get("ref")
            or item.get("artifact_ref")
            or ""
        )
        if not identity:
            raise KernelError(
                "CHAPTER_PROVIDER_KNOWLEDGE_VIEW_INVALID",
                "selected Knowledge requires immutable identity",
            )
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(
            {
                "ref": str(item.get("ref") or item.get("artifact_ref") or ""),
                "version": str(item.get("version") or ""),
                "content": _compact(content),
            }
        )
        if _serialized_character_count(selected) > _MAX_PROVIDER_KNOWLEDGE_CHARACTERS:
            raise KernelError(
                "CHAPTER_PROVIDER_KNOWLEDGE_BUDGET_EXCEEDED",
                "task-selected Knowledge exceeds its deterministic size boundary; "
                "retrieve a smaller MKAOS projection",
            )
    return selected


def _task(stage: str, **values: Any) -> dict[str, Any]:
    return {
        "contract_version": "provider-task-view-v1",
        "stage": stage,
        **{key: value for key, value in values.items() if value not in (None, {}, [])},
    }


def _prose(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, Mapping) else {}
    return {
        key: deepcopy(source[key])
        for key in ("chapter", "title", "text")
        if source.get(key) not in (None, "")
    }


def _compact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact(item)
            for key, item in value.items()
            if key not in _OPERATIONAL_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_compact(item) for item in value]
    return deepcopy(value)


def _serialized_character_count(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _selectors(
    projection: Mapping[str, Any], task_view: Mapping[str, Any]
) -> frozenset[str]:
    values: set[str] = set()
    for key in (
        "character_ids",
        "arc_refs",
        "fact_refs",
        "belief_refs",
        "disclosure_refs",
        "state_entity_refs",
        "obligation_refs",
        "world_rule_refs",
    ):
        for item in projection.get(key) or ():
            text = str(item).strip()
            if text:
                values.add(text)
    plan = task_view.get("chapter_plan")
    if isinstance(plan, Mapping):
        for participant in plan.get("character_participation") or ():
            if isinstance(participant, Mapping):
                values.update(
                    str(item)
                    for key in (
                        "character_id",
                        "trajectory_refs",
                        "known_fact_ids",
                        "unknown_fact_ids",
                        "belief_refs",
                    )
                    for item in (
                        participant.get(key)
                        if isinstance(participant.get(key), list)
                        else [participant.get(key)]
                    )
                    if item
                )
    return frozenset(values)


def _state_fact_relevant(
    fact: Mapping[str, Any],
    selectors: frozenset[str],
    context_bundle: Mapping[str, Any],
) -> bool:
    state_kind = str(fact.get("state_kind") or "")
    state = fact.get("state") or {}
    if state_kind == "narrative_obligation" and isinstance(state, Mapping):
        status = str(state.get("status") or "").upper()
        priority = str(state.get("priority") or "").upper()
        window = state.get("target_window") or {}
        chapter = int(
            dict(context_bundle.get("context_manifest") or {})
            .get("narrative_position", {})
            .get("chapter", 0)
            or 0
        )
        due = (
            isinstance(window, Mapping)
            and str(window.get("status") or "") == "SCHEDULED"
            and int(window.get("to_chapter") or 0) <= chapter
        )
        if status not in {"FULFILLED", "CANCELLED"} and (
            priority in {"HIGH", "CRITICAL"} or due
        ):
            return True
    if not selectors:
        return False
    serialized = json.dumps(
        {"entity_key": fact.get("entity_key"), "state": state},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return any(selector in serialized for selector in selectors)


__all__ = [
    "build_provider_context_view",
    "build_provider_knowledge_view",
    "build_provider_task_view",
]
