from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

WRITER_PROJECTION_VERSION = "accepted-writer-history.v1"
_PROSE_TYPES = frozenset({"best_draft_candidate", "draft_chapter", "draft_version"})


def provider_visible_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        if value.get("provider_visibility") == "INTERNAL_QUALITY_ONLY":
            return None
        return {
            key: projected for key, item in value.items()
            if (projected := provider_visible_data(item)) is not None or item is None
        }
    if isinstance(value, (list, tuple)):
        return [projected for item in value if (projected := provider_visible_data(item)) is not None or item is None]
    return deepcopy(value)


def project_writer_history(content_text: str, *, source_artifact_type: str) -> str:
    try:
        source = json.loads(content_text)
    except (ValueError, TypeError) as error:
        if source_artifact_type in _PROSE_TYPES:
            raise KernelError("WRITER_HISTORY_SOURCE_INVALID", "accepted prose projection requires the complete source JSON") from error
        return content_text
    if source_artifact_type in _PROSE_TYPES:
        if not isinstance(source, Mapping):
            raise KernelError("WRITER_HISTORY_SOURCE_INVALID", "accepted prose must be a semantic object")
        scenes = source.get("scene_artifacts")
        if isinstance(scenes, list) and scenes:
            if any(not isinstance(item, Mapping) or not isinstance(item.get("text"), str) for item in scenes):
                raise KernelError("WRITER_HISTORY_SOURCE_INVALID", "accepted Scene prose cannot be partially projected")
            projected = {"scene_artifacts": [
                {key: deepcopy(item[key]) for key in ("slot_id", "text", "used_fact_ids") if key in item}
                for item in scenes
            ]}
            separators = source.get("scene_separators", ["\n\n"] * max(0, len(scenes) - 1))
            if not isinstance(separators, list) or len(separators) != len(scenes) - 1 or any(not isinstance(item, str) or (item and not item.isspace()) for item in separators):
                raise KernelError("WRITER_HISTORY_SOURCE_INVALID", "accepted Scene separators must preserve frozen prose")
            if "scene_separators" in source:
                projected["scene_separators"] = list(separators)
            body = "".join((separators[index - 1] if index else "") + item["text"] for index, item in enumerate(scenes))
            if isinstance(source.get("text"), str) and source["text"] != body:
                raise KernelError("WRITER_HISTORY_PROSE_DRIFT", "accepted prose and Scene bodies disagree")
        elif isinstance(source.get("text"), str):
            projected = {"text": source["text"]}
        else:
            raise KernelError("WRITER_HISTORY_SOURCE_INVALID", "accepted prose projection cannot find a complete body")
        projected.update({key: deepcopy(source[key]) for key in ("chapter", "title") if key in source})
    else:
        projected = source
    return json.dumps(provider_visible_data(projected), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def project_visible_summary(text: str) -> str:
    try:
        source = json.loads(text)
    except (ValueError, TypeError):
        return text
    projected = provider_visible_data(source)
    return "" if projected is None else json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def project_writer_context_summary(segment: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    from novel_forge.modules.narrative_state.reality import narrative_hash

    summary = str(segment.get("safe_summary") or "").strip()
    prose = (segment.get("asset_type") in _PROSE_TYPES
             or segment.get("physical_asset_type") in _PROSE_TYPES
             or segment.get("narrative_function") == "recent_accepted_prose")
    if not prose:
        return project_visible_summary(summary)
    if segment.get("compression_method") == "host-bound-extractive-semantic.v2":
        records = [row for row in manifest.get("compression_trace") or ()
                   if isinstance(row, Mapping) and row.get("asset_version_id") == segment.get("asset_version_id")]
        traces = records[0].get("trace") if len(records) == 1 else None
        trace = traces[0] if isinstance(traces, list) and len(traces) == 1 and isinstance(traces[0], Mapping) else {}
        payload = {"safe_summary": summary, "structured_facts": list(segment.get("structured_facts") or ())}
        if (trace.get("writer_projection_version") != WRITER_PROJECTION_VERSION
            or trace.get("method") != segment.get("compression_method")
            or trace.get("source_asset_version_id") != segment.get("asset_version_id")
            or not segment.get("content_digest")
            or trace.get("source_content_hash") != segment.get("content_digest")
            or trace.get("forward_check") != "EXACT_HOST_SOURCE_UNITS"
            or trace.get("result_content_hash") != narrative_hash(payload)):
            raise KernelError("WRITER_HISTORY_COMPRESSED_PROJECTION_REQUIRED", "compressed accepted prose requires its frozen clean source projection and exact extraction receipt")
        return project_visible_summary(summary)
    return project_writer_history(summary, source_artifact_type="best_draft_candidate")
