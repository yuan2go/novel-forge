from __future__ import annotations

from copy import deepcopy
from difflib import unified_diff
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.review.diagnostics import prose_hash


EDITION_CONTRACT = "book-manuscript-edition.v1"
CHANGE_KINDS = frozenset({"EXPRESSION", "STRUCTURE", "NARRATIVE_FACT", "UNKNOWN"})


def edition_manifest(scope: dict[str, str], sources: list[dict[str, Any]]) -> dict[str, Any]:
    if not sources or any(not scope.get(key) for key in ("project_id", "workspace_id", "book_id", "book_run_id")):
        raise KernelError("EDITION_SOURCE_REQUIRED", "An exact nonempty accepted Book manuscript is required")
    units = []
    for source in sources:
        text = source.get("text")
        if not isinstance(text, str) or not text.strip() or not all(source.get(key) for key in (
            "acceptance_id", "asset_version_id", "asset_hash", "chapter_plan_asset_version_id",
        )):
            raise KernelError("EDITION_SOURCE_INVALID", "Every source needs accepted prose, plan and immutable asset identity")
        units.append({
            "unit_id": source.get("unit_id") or "chapter:" + source["acceptance_id"],
            "title": source.get("title", ""), "text": text, "text_hash": prose_hash(text),
            "source_ranges": [{"asset_version_id": source["asset_version_id"], "asset_hash": source["asset_hash"],
                               "start": 0, "end": len(text), "text_hash": prose_hash(text)}],
            "source_acceptance_ids": [source["acceptance_id"]],
            "chapter_plan_asset_version_id": source["chapter_plan_asset_version_id"],
            "scene_artifacts": deepcopy(source.get("scene_artifacts", [])),
            "scene_mapping": deepcopy(source.get("scene_mapping", [])),
            "scene_separators": deepcopy(source.get("scene_separators")),
        })
    if len({item["unit_id"] for item in units}) != len(units):
        raise KernelError("EDITION_IDENTITY_COLLISION", "Manuscript units require distinct stable identities")
    manifest = {"contract_version": EDITION_CONTRACT, **scope, "units": units,
                "sources": deepcopy(sources), "publication_authorized": False}
    manifest["manifest_digest"] = completion_digest(manifest)
    return manifest


def require_manifest(manifest: dict[str, Any]) -> None:
    if (manifest.get("contract_version") != EDITION_CONTRACT
        or manifest.get("manifest_digest") != completion_digest({k: v for k, v in manifest.items() if k != "manifest_digest"})):
        raise KernelError("EDITION_MANIFEST_DRIFT", "The immutable manuscript manifest does not match its digest")


def revise_manifest(base: dict[str, Any], *, units: list[dict[str, Any]], reason: str,
                    change_kind: str, removed_source_ranges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    require_manifest(base)
    if (change_kind not in CHANGE_KINDS or not reason.strip() or not isinstance(units, list)
        or not units or len(units) > 10000 or any(not isinstance(unit, dict) for unit in units)):
        raise KernelError("EDITION_EDIT_INVALID", "A bounded nonempty manuscript, change classification and reason are required")
    removed_source_ranges = deepcopy(base.get("removed_source_ranges", [])) if removed_source_ranges is None else removed_source_ranges
    if not isinstance(removed_source_ranges, list) or any(not isinstance(item, dict) for item in removed_source_ranges):
        raise KernelError("EDITION_SOURCE_RANGE_INVALID", "Explicit removals must retain their exact source mappings")
    source_by_id = {item["asset_version_id"]: item for item in base["sources"]}
    known_ids = {item["unit_id"] for item in base["units"]}
    ids: set[str] = set()
    spans: dict[str, list[tuple[int, int]]] = {key: [] for key in source_by_id}
    normalized = []
    for item in units:
        item = deepcopy(item)
        unit_id, text = item.get("unit_id"), item.get("text")
        if (not isinstance(unit_id, str) or not unit_id.strip() or unit_id in ids
            or not isinstance(text, str) or not text.strip() or len(text) > 200000 or "\0" in text
            or not isinstance(item.get("source_ranges"), list) or not item["source_ranges"]
            or any(not isinstance(value, dict) for value in item["source_ranges"])
            or not item.get("chapter_plan_asset_version_id")):
            raise KernelError("EDITION_UNIT_INVALID", "Units require stable identities, exact mapping, plan and bounded text")
        ids.add(unit_id)
        acceptances = []
        for mapping in item["source_ranges"]:
            source = _validate_source_range(mapping, source_by_id)
            spans[source["asset_version_id"]].append((mapping["start"], mapping["end"]))
            acceptances.append(source["acceptance_id"])
        item["source_acceptance_ids"] = list(dict.fromkeys(acceptances))
        item["text_hash"] = prose_hash(text)
        if item.get("scene_artifacts"):
            from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
            scenes = item["scene_artifacts"]
            if not isinstance(scenes, list) or any(not isinstance(scene, dict) for scene in scenes):
                raise KernelError("EDITION_SCENE_MAPPING_INVALID", "Scene artifacts must be explicit mapped realization objects")
            scene_ids = [scene.get("scene_id") for scene in scenes]
            slot_ids = [scene.get("slot_id") for scene in scenes]
            if len(set(slot_ids)) != len(slot_ids) or not all(slot_ids) or (any(scene_ids) and not all(scene_ids)):
                raise KernelError("EDITION_SCENE_IDENTITY_INVALID", "Each realization slot retains a unique identity within its mapped Scene")
            mapping = item.get("scene_mapping") or []
            if not isinstance(mapping, list) or any(not isinstance(entry, dict) for entry in mapping):
                raise KernelError("EDITION_SCENE_MAPPING_INVALID", "Scene mapping must be an ordered list of identities")
            if mapping and ([entry.get("slot_id") for entry in mapping] != slot_ids or not all(entry.get("scene_id") for entry in mapping)):
                raise KernelError("EDITION_SCENE_MAPPING_INVALID", "Explicit Scene mapping must cover every realization slot in order")
            if serialize_realization(scenes, item.get("scene_separators")) != text:
                old_unit = next((old for old in base["units"] if old["unit_id"] == unit_id), None)
                if change_kind == "EXPRESSION" and old_unit and scenes == old_unit.get("scene_artifacts"):
                    from novel_forge.modules.chapter_authority.author_editor import reconcile_author_scenes
                    item["scene_artifacts"] = reconcile_author_scenes(old_unit, text, None, item.get("scene_separators"))
                else:
                    raise KernelError("EDITION_SCENE_MAPPING_INVALID", "Scene mapping must reproduce exact Unicode text")
        normalized.append(item)
    for mapping in removed_source_ranges or []:
        source = _validate_source_range(mapping, source_by_id)
        spans[source["asset_version_id"]].append((mapping["start"], mapping["end"]))
    for version_id, ranges in spans.items():
        cursor = 0
        for start, end in sorted(ranges):
            if start != cursor:
                raise KernelError("EDITION_MAPPING_INCOMPLETE", "Mapped and explicitly removed source ranges must cover each source exactly once")
            cursor = end
        if cursor != len(source_by_id[version_id]["text"]):
            raise KernelError("EDITION_MAPPING_INCOMPLETE", "An original source cannot silently disappear")
    original = base["units"]
    structural = ([item["unit_id"] for item in original] != [item["unit_id"] for item in normalized]
                  or any(item["unit_id"] not in known_ids for item in normalized)
                  or any(item["source_ranges"] != old["source_ranges"] for item, old in zip(normalized, original))
                  or any(item.get("scene_mapping") != old.get("scene_mapping") for item, old in zip(normalized, original))
                  or any([(scene.get("scene_id"),scene.get("slot_id")) for scene in item.get("scene_artifacts", [])] != [(scene.get("scene_id"),scene.get("slot_id")) for scene in old.get("scene_artifacts", [])] for item, old in zip(normalized, original)))
    if structural and change_kind == "EXPRESSION":
        raise KernelError("EDITION_CLASSIFICATION_CONFLICT", "Split, merge, removal or reorder is a structural change")
    if normalized == original:
        raise KernelError("EDITION_NO_CHANGE", "No manuscript change was supplied")
    changed = []
    for index, unit in enumerate(normalized):
        old = next((item for item in original if item["unit_id"] == unit["unit_id"]), None)
        if old != unit or index >= len(original) or original[index]["unit_id"] != unit["unit_id"]:
            changed.append(index + 1)
    earliest = min(changed, default=min(len(original), len(normalized)) + 1)
    earliest = min(earliest, base.get("impact", {}).get("earliest_affected_position", earliest))
    result = {**deepcopy(base), "units": normalized, "base_manifest_digest": base["manifest_digest"],
              "reason": reason, "change_kind": change_kind, "removed_source_ranges": removed_source_ranges or [],
              "impact": {"earliest_affected_position": earliest,
                         "changed_unit_ids": [normalized[index - 1]["unit_id"] for index in changed],
                         "required_revalidation_unit_ids": [item["unit_id"] for item in normalized[earliest - 1:]],
                         "fact_reuse": "REQUIRES_EXACT_NATIVE_VALIDATION",
                         "review_signatures": "INVALIDATED", "publication_candidates": "INVALIDATED"}}
    result.pop("manifest_digest", None)
    result["manifest_digest"] = completion_digest(result)
    return result


def _validate_source_range(mapping: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    version_id = mapping.get("asset_version_id")
    source = sources.get(version_id) if isinstance(version_id, str) else None
    if source is None or source["asset_hash"] != mapping.get("asset_hash"):
        raise KernelError("EDITION_SOURCE_HASH_CONFLICT", "Mapping must name an exact base source and asset hash")
    start, end = mapping.get("start"), mapping.get("end")
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"])
        or mapping.get("text_hash") != prose_hash(source["text"][start:end])):
        raise KernelError("EDITION_SOURCE_RANGE_INVALID", "Mapping must bind exact source Unicode offsets and fragment hash")
    return source


def edition_diff(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    require_manifest(base)
    require_manifest(candidate)
    old = {item["unit_id"]: item for item in base["units"]}
    new = {item["unit_id"]: item for item in candidate["units"]}
    changes = []
    for unit_id in dict.fromkeys((*old, *new)):
        before, after = old.get(unit_id), new.get(unit_id)
        changed = before != after or (before is not None and after is not None and list(old).index(unit_id) != list(new).index(unit_id))
        if changed:
            changes.append({"unit_id": unit_id, "before_position": list(old).index(unit_id) + 1 if before else None,
                            "after_position": list(new).index(unit_id) + 1 if after else None,
                            "diff": "".join(unified_diff((before or {}).get("text", "").splitlines(keepends=True),
                                                        (after or {}).get("text", "").splitlines(keepends=True),
                                                        fromfile="base/" + unit_id, tofile="candidate/" + unit_id))})
    return {"base_manifest_digest": base["manifest_digest"], "candidate_manifest_digest": candidate["manifest_digest"],
            "changes": changes, "impact": candidate.get("impact", {})}


def derived_invalidations(source: dict[str, Any], replacement: dict[str, Any], unit_ids: list[str]) -> list[dict[str, Any]]:
    require_manifest(source)
    require_manifest(replacement)
    before = {item["unit_id"]: item for item in source["units"]}
    after = {item["unit_id"]: item for item in replacement["units"]}
    if not unit_ids or set(unit_ids) - set(before):
        raise KernelError("ADAPTATION_SOURCE_RANGE_INVALID", "Adaptation requires an explicit source-edition range")
    changes = []
    for unit_id in unit_ids:
        changed = unit_id not in after or before[unit_id] != after[unit_id]
        moved = unit_id in after and list(before).index(unit_id) != list(after).index(unit_id)
        if changed or moved:
            changes.append({"unit_id": unit_id, "reason": "SOURCE_REMOVED" if unit_id not in after else
                            "SOURCE_CHANGED" if changed else "SOURCE_REORDERED",
                            "old_source_digest": source["manifest_digest"], "new_source_digest": replacement["manifest_digest"]})
    return changes
