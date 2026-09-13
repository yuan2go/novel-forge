from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash


TARGETS = frozenset({"CREATIVE_FOUNDATION", "THEME_CONTRACT", "ENDING_INTENT", "READER_PROMISE", "WORLD_BIBLE", "CHARACTER_CAST", "BOOK", "VOLUME", "ARC", "NEAR_TERM", "CHAPTER"})
PRIVATE_TARGETS = frozenset({"BOOK", "VOLUME", "ARC"})
GENERATOR_TARGETS = {
    "creative.candidates.generate": "CREATIVE_FOUNDATION",
    "theme.candidates.generate": "THEME_CONTRACT",
    "ending.intent.generate": "ENDING_INTENT",
    "reader.promise.generate": "READER_PROMISE",
    "world.design.generate": "WORLD_BIBLE",
    "character.cast.generate": "CHARACTER_CAST",
    "book_plan.generate": "BOOK", "volume_plan.generate": "VOLUME",
    "arc_plan.generate": "ARC", "chapter_group_plan.generate": "NEAR_TERM",
    "chapter_plan.generate": "CHAPTER",
}


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise KernelError("AUTHOR_DESIGN_INPUT_INVALID", message)


def validate_author_design(raw: Mapping[str, Any], *, project_id: str | None = None, book_id: str | None = None) -> dict[str, Any]:
    _require(isinstance(raw, Mapping) and set(raw) == {"contract_version", "project_id", "book_id", "version", "evidence_class", "source_task", "documents", "fragments"}, "Author design requires an explicit versioned input set")
    _require(raw["contract_version"] == "author-design-input.v1" and raw["evidence_class"] in {"AI_ASSISTED_AUTHOR_INPUT", "OPERATOR_AUTHORED_INPUT"}, "Author intent is not generated or approved narrative history")
    _require(all(isinstance(raw[k], str) and raw[k].strip() for k in ("project_id", "book_id", "version", "source_task")), "Author identity and source task are required")
    _require((project_id is None or raw["project_id"] == project_id) and (book_id is None or raw["book_id"] == book_id), "Author input belongs to another project or Book")
    documents, fragments = raw["documents"], raw["fragments"]
    _require(isinstance(documents, list) and 0 < len(documents) <= 32 and isinstance(fragments, list) and 0 < len(fragments) <= 256, "Author sources must be bounded explicit documents and fragments")
    by_path: dict[str, Any] = {}
    for doc in documents:
        _require(isinstance(doc, Mapping) and set(doc) == {"path", "content", "content_hash"}, "Author documents need exact source bytes")
        path = doc["path"]
        _require(isinstance(path, str) and bool(path) and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts and "\\" not in path and path not in by_path, "Author source paths must be distinct relative locators")
        _require(isinstance(doc["content"], str) and doc["content"].strip() and len(doc["content"]) <= 100000 and text_hash(doc["content"]) == doc["content_hash"], "Author document bytes differ from their frozen hash")
        by_path[path] = doc
    identities: set[str] = set()
    for item in fragments:
        _require(isinstance(item, Mapping) and set(item) == {"fragment_id", "source_path", "start", "end", "content_hash", "targets", "chapter_range", "visibility", "strength"}, "Author fragments require exact source spans and routing")
        identity, bounds, targets = item["fragment_id"], item["chapter_range"], item["targets"]
        _require(isinstance(identity, str) and bool(identity.strip()) and identity not in identities, "Author fragment identities must be unique")
        identities.add(identity)
        _require(isinstance(bounds, list) and len(bounds) == 2 and all(type(v) is int for v in bounds) and 1 <= bounds[0] <= bounds[1] <= 10000, "Author fragments require a legal chapter range")
        _require(isinstance(targets, list) and bool(targets) and all(isinstance(t, str) for t in targets) and len(set(targets)) == len(targets) and set(targets) <= TARGETS, "Author fragment targets are not governed roles")
        _require(item["visibility"] in {"SCENE_INTENT", "AUTHOR_ONLY"} and item["strength"] in {"REQUIRED", "DIRECTION"}, "Author visibility and strength must be explicit")
        _require(item["visibility"] != "AUTHOR_ONLY" or set(targets) <= PRIVATE_TARGETS, "Behind-scenes intent cannot be sent to Foundation or scene execution")
        doc = by_path.get(item["source_path"])
        _require(doc is not None and type(item["start"]) is int and type(item["end"]) is int and 0 <= item["start"] < item["end"] <= len(doc["content"]), "Author fragment must locate actually frozen source text")
        _require(text_hash(doc["content"][item["start"]:item["end"]]) == item["content_hash"], "Author fragment hash differs from its source span")
    return deepcopy(dict(raw))


def bind_author_design(raw: Mapping[str, Any], *, asset_version_id: str, content_hash: str) -> dict[str, Any]:
    value = validate_author_design(raw)
    documents = {item["path"]: item for item in value.pop("documents")}
    value["fragments"] = [{**item, "text": documents[item["source_path"]]["content"][item["start"]:item["end"]], "source_document_hash": documents[item["source_path"]]["content_hash"]} for item in value["fragments"]]
    value.update(contract_version="author-design-binding.v1", brief_asset_version_id=asset_version_id, brief_content_hash=content_hash)
    return {**value, "binding_digest": narrative_hash(value)}


def gather_author_design(contents: list[Mapping[str, Any]], *, project_id: str, book_id: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for content in contents:
        value = (content.get("constraint_envelope") or {}).get("author_design")
        if not value:
            value = ((content.get("candidate_payload") or {}).get("constraint_envelope") or {}).get("author_design")
        if not value:
            continue
        _require(isinstance(value, Mapping) and value.get("contract_version") == "author-design-binding.v1" and value.get("project_id") == project_id and value.get("book_id") == book_id and narrative_hash({k:v for k,v in value.items() if k != "binding_digest"}) == value.get("binding_digest"), "Inherited author input has stale bytes or another Book boundary")
        _require(not found or found == value, "Conflicting author versions require a governed future PlanChange")
        found = deepcopy(dict(value))
    return found


def author_binding_from_inputs(inputs: list[Mapping[str, Any]], *, project_id: str, book_id: str) -> dict[str, Any]:
    bindings = [item["content"] for item in inputs]
    for item in inputs:
        content = item["content"]
        if item.get("role") == "creative_brief" and content.get("author_design"):
            source = validate_author_design(content["author_design"], project_id=project_id, book_id=book_id)
            bindings.append({"constraint_envelope": {"author_design": bind_author_design(source, asset_version_id=item["asset_version_id"], content_hash=item["content_hash"])}})
    return gather_author_design(bindings, project_id=project_id, book_id=book_id)


def project_author_design(binding: Mapping[str, Any], *, target: str, chapter: int = 0, chapter_range: tuple[int, int] | None = None) -> dict[str, Any]:
    if not binding:
        return {}
    _require(target in TARGETS, "Author projection requires a governed role")
    _require(target != "CHAPTER" or chapter > 0, "Chapter author input requires an exact chapter")
    _require(target != "NEAR_TERM" or chapter_range is not None, "Near-term author input requires a frozen chapter range")
    if chapter_range is not None:
        chapter_range = _chapter_range(chapter_range)
    selected = []
    excluded = []
    for item in binding["fragments"]:
        bounds = item["chapter_range"]
        permitted = target in item["targets"] and (item["visibility"] != "AUTHOR_ONLY" or target in PRIVATE_TARGETS)
        in_scope = (not chapter or bounds[0] <= chapter <= bounds[1]) and (not chapter_range or max(bounds[0], chapter_range[0]) <= min(bounds[1], chapter_range[1]))
        if permitted and in_scope:
            selected.append(deepcopy(item))
        else:
            excluded.append({"fragment_id": item["fragment_id"], "content_hash": item["content_hash"], "reason": "OUTSIDE_ROLE" if not permitted else "OUTSIDE_CHAPTER_RANGE"})
    return {
        "contract_version": "author-design-projection.v1", "target": target,
        "brief_asset_version_id": binding["brief_asset_version_id"], "brief_content_hash": binding["brief_content_hash"],
        "design_version": binding["version"], "binding_digest": binding["binding_digest"],
        "evidence_class": binding["evidence_class"], "authority": "AUTHOR_INTENT_NOT_CANON",
        "chapter_range": list(chapter_range or ((chapter, chapter) if chapter else ())),
        "fragments": selected, "exclusions": excluded,
    }


def compile_provider_author_projection(
    projection: Mapping[str, Any], *,
    frozen_context_pointer: str = "/author_design_projection",
    source_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if source_projection is not None:
        expected = compile_provider_author_projection(source_projection, frozen_context_pointer=frozen_context_pointer)
        if projection != expected:
            raise KernelError("AUTHOR_DESIGN_PROVIDER_VIEW_DRIFT", "Author Provider view differs from its complete frozen projection")
        return expected
    if not projection:
        return {}
    _require(isinstance(projection, Mapping) and set(projection) == {"contract_version", "target", "brief_asset_version_id", "brief_content_hash", "design_version", "binding_digest", "evidence_class", "authority", "chapter_range", "fragments", "exclusions"}, "Author Provider compilation requires the complete frozen projection")
    _require(projection["contract_version"] == "author-design-projection.v1" and projection["target"] in TARGETS and projection["authority"] == "AUTHOR_INTENT_NOT_CANON", "Author Provider guidance must retain its governed role and evidence boundary")
    _require(all(isinstance(projection[k], str) and projection[k] for k in ("brief_asset_version_id", "design_version")) and all(re.fullmatch(r"sha256:[0-9a-f]{64}", str(projection[k])) for k in ("brief_content_hash", "binding_digest")), "Author Provider guidance requires exact source identities")
    _require(isinstance(frozen_context_pointer, str) and frozen_context_pointer.startswith("/") and not re.search(r"~(?![01])", frozen_context_pointer), "Author source receipt requires a frozen Context JSON pointer")
    fragments, exclusions = projection["fragments"], projection["exclusions"]
    _require(isinstance(fragments, list) and isinstance(exclusions, list), "Author Provider compilation requires explicit selected and excluded fragments")
    semantic_fields = {"fragment_id", "content_hash", "chapter_range", "visibility", "strength", "text"}
    seen = set()
    for item in fragments:
        _require(isinstance(item, Mapping) and set(item) == semantic_fields | {"source_path", "start", "end", "source_document_hash", "targets"}, "Author fragment metadata cannot conceal unclassified semantics")
        _require(isinstance(item["fragment_id"], str) and item["fragment_id"] and item["fragment_id"] not in seen, "Author Provider fragment identities must be distinct")
        seen.add(item["fragment_id"])
        _require(isinstance(item["text"], str) and text_hash(item["text"]) == item["content_hash"] and type(item["start"]) is int and type(item["end"]) is int and item["end"] - item["start"] == len(item["text"]), "Author Provider text must match its frozen source span and hash")
        _chapter_range(item["chapter_range"])
        _require(item["visibility"] in {"SCENE_INTENT", "AUTHOR_ONLY"} and item["strength"] in {"REQUIRED", "DIRECTION"} and projection["target"] in item["targets"] and (item["visibility"] != "AUTHOR_ONLY" or projection["target"] in PRIVATE_TARGETS), "Author Provider fragment lies outside its permitted role")
    for item in exclusions:
        _require(isinstance(item, Mapping) and set(item) == {"fragment_id", "content_hash", "reason"} and item["reason"] in {"OUTSIDE_ROLE", "OUTSIDE_CHAPTER_RANGE"}, "Author exclusion receipt may replace only a source directory")
    result = {key: deepcopy(value) for key, value in projection.items() if key not in {"fragments", "exclusions"}}
    result.update(
        contract_version="author-design-provider-view.v1",
        fragments=[{key: deepcopy(value) for key, value in item.items() if key in semantic_fields} for item in fragments],
        source_receipt={
            "json_pointer": frozen_context_pointer, "content_hash": narrative_hash(projection),
            "excluded_count": len(exclusions), "metadata_count": len(fragments),
            "reason": "ROLE_SOURCE_METADATA_ONLY",
        },
    )
    return result


def planning_author_projection(binding: Mapping[str, Any], *, generator: str, logical_key: str, chapter_range: tuple[int, int] | None = None) -> dict[str, Any]:
    chapter = int(logical_key.split(":")[1]) if logical_key.startswith("chapter:") and logical_key.split(":")[1].isdigit() else 0
    return project_author_design(binding, target=GENERATOR_TARGETS[generator], chapter=chapter, chapter_range=chapter_range)


def _chapter_range(value: Any) -> tuple[int, int]:
    _require(isinstance(value, (list, tuple)) and len(value) == 2 and all(type(n) is int for n in value) and 1 <= value[0] <= value[1], "Author input requires an exact positive chapter range")
    return value[0], value[1]


def compile_planning_author_projection(binding: Mapping[str, Any], *, command: Any, selected_inputs: list[Mapping[str, Any]]) -> dict[str, Any]:
    target = GENERATOR_TARGETS[command.generator_operation_name]
    bounds = command.narrative_search_chapter_range
    if target == "NEAR_TERM" and bounds is None:
        exact = re.fullmatch(r"chapter-group:(\d+)-(\d+)", command.logical_key)
        if exact:
            bounds = _chapter_range(tuple(map(int, exact.groups())))
    if target == "VOLUME" and bounds is None:
        from novel_forge.modules.story_planning_runtime.domain import canonical_book_volume_allocation
        ordinal = re.fullmatch(r"volume:(\d+)", command.logical_key)
        parents = [item["content"] for item in selected_inputs if item["role"] == "book_plan"]
        _require(ordinal is not None and len(parents) == 1, "Volume author input requires a frozen Book allocation and exact ordinal")
        allocation, _ = canonical_book_volume_allocation(parents[0])
        rows = [item for item in allocation if item["volume"] == int(ordinal[1])]
        _require(len(rows) == 1, "Volume author input lies outside its frozen Book allocation")
        bounds = _chapter_range(rows[0]["chapter_range"])
    if target == "ARC":
        ranges = [_chapter_range(item["content"].get("chapter_range")) for item in selected_inputs if item["role"] == "volume_plan" or item["role"].startswith("arc_scope_volume:")]
        _require(bool(ranges), "Arc author input requires frozen Volume chapter ranges")
        ordered = sorted(ranges)
        _require(all(right[0] <= left[1] + 1 for left, right in zip(ordered, ordered[1:])), "Disjoint Arc author chapter ranges require an explicit bounded planning split")
        bounds = (min(start for start, _ in ranges), max(end for _, end in ranges))
    if target == "NEAR_TERM" and bounds is not None:
        parents = [item["content"] for item in selected_inputs if item["role"] == "volume_plan"]
        _require(len(parents) == 1, "Near-term author input requires its frozen parent Volume")
        parent_range = _chapter_range(parents[0].get("chapter_range"))
        _require(parent_range[0] <= bounds[0] <= bounds[1] <= parent_range[1], "Near-term author chapter range exceeds its frozen parent Volume")
    return planning_author_projection(binding, generator=command.generator_operation_name, logical_key=command.logical_key, chapter_range=bounds)


def frozen_author_projection(content: Mapping[str, Any], *, generator: str, logical_key: str) -> dict[str, Any]:
    envelope = content.get("constraint_envelope") or {}
    binding = envelope.get("author_design")
    if not binding:
        return {}
    projection = envelope.get("author_design_projection")
    _require(isinstance(projection, Mapping), "Author evaluation requires the frozen generation projection")
    bounds = projection.get("chapter_range")
    expected = planning_author_projection(binding, generator=generator, logical_key=logical_key, chapter_range=_chapter_range(bounds) if bounds else None)
    _require(projection == expected, "Author evaluation projection differs from its exact source binding and scope")
    if expected["target"] in {"NEAR_TERM", "VOLUME"} and content.get("chapter_range") is not None:
        _require(_chapter_range(content["chapter_range"]) == _chapter_range(bounds), "Author generation scope differs from the candidate chapter range")
    return deepcopy(dict(projection))


def add_author_decision_contract(schema: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    selected = projection.get("fragments") or []
    if not selected:
        return dict(schema)
    text = {"type": "string", "minLength": 1}
    properties = {
        "fragment_id": {"type": "string", "enum": [i["fragment_id"] for i in selected]},
        "content_hash": {"type": "string", "enum": [i["content_hash"] for i in selected]},
        "decision": {"type": "string", "enum": ["ADOPT", "ADAPT", "REJECT", "RETAIN_PRIVATE"]},
        "rationale": text, "target_pointer": {"type": "string"}, "realization_excerpt": {"type": "string"},
    }
    result = deepcopy(dict(schema))
    result["properties"]["author_design_decisions"] = {
        "type": "array", "minItems": len(selected), "maxItems": len(selected),
        "description": "Account for every scoped author fragment. Locate actual candidate text for ADOPT/ADAPT; for World use /world_foundation/... string leaves of the decoded world_foundation_json. AUTHOR_ONLY must RETAIN_PRIVATE with a reason and empty location; never adopt private text into public candidate fields. REJECT only optional DIRECTION with a reason and empty location. REQUIRED intent cannot silently disappear. Preserve limited POV, disclosure prerequisites and accepted history. These decisions are planning claims, not prose verification or Canon facts.",
        "items": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
    }
    result["required"].append("author_design_decisions")
    return result


def validate_author_decisions(candidate: Mapping[str, Any], projection: Mapping[str, Any]) -> None:
    from novel_forge.modules.mkaos_authority.applicability import resolve_pointer
    selected = {item["fragment_id"]: item for item in projection.get("fragments") or []}
    _require_private_candidate_boundary(candidate, list(selected.values()))
    decisions = candidate.get("author_design_decisions") or []
    _require(isinstance(decisions, list) and len(decisions) == len(selected), "Every scoped author fragment needs an explicit adoption decision")
    seen = set()
    for item in decisions:
        _require(isinstance(item, Mapping), "Author decisions must be structured")
        source = selected.get(item.get("fragment_id"))
        _require(source is not None and source["fragment_id"] not in seen and item.get("content_hash") == source["content_hash"], "Author decision must bind the exact selected source fragment")
        seen.add(source["fragment_id"])
        _require(item.get("decision") in {"ADOPT", "ADAPT", "REJECT", "RETAIN_PRIVATE"} and isinstance(item.get("rationale"), str) and bool(item["rationale"].strip()), "Author adoption needs a decision and explanation")
        if item["decision"] == "REJECT":
            _require(source["strength"] != "REQUIRED" and item.get("target_pointer") == "" and item.get("realization_excerpt") == "", "Required author constraints cannot be discarded by a generated candidate")
            continue
        if source["visibility"] == "AUTHOR_ONLY":
            _require(item["decision"] == "RETAIN_PRIVATE" and item.get("target_pointer") == "" and item.get("realization_excerpt") == "", "Author private intent must remain in its private carrier, not public candidate fields")
            continue
        _require(item["decision"] != "RETAIN_PRIVATE", "Scene author intent cannot be hidden as private guidance")
        pointer, excerpt = item.get("target_pointer", ""), item.get("realization_excerpt", "")
        view = dict(candidate)
        if projection.get("target") == "WORLD_BIBLE" and "world_foundation_json" in view:
            from novel_forge.modules.worldbuilding.foundation import WorldFoundation
            try:
                world = json.loads(view.pop("world_foundation_json"))
            except (ValueError, TypeError) as error:
                raise KernelError("AUTHOR_DESIGN_INPUT_INVALID", "Author World adoption requires the typed decoded world") from error
            _require(isinstance(world, Mapping), "Author World adoption requires a decoded object")
            WorldFoundation.from_mapping(world)
            _require("world_foundation" not in view or view["world_foundation"] == world, "Author World adoption has conflicting canonical views")
            view["world_foundation"] = world
        found, value = resolve_pointer(view, pointer)
        _require(isinstance(pointer, str) and not pointer.startswith(("/author_", "/constraint_envelope", "/execution_evidence", "/frozen_inputs")) and found and isinstance(value, str) and isinstance(excerpt, str) and len(excerpt.strip()) >= 4 and excerpt in value, "Author adoption must locate actual candidate content rather than a self-report")


def _require_private_candidate_boundary(candidate: Mapping[str, Any], fragments: list[Mapping[str, Any]]) -> None:
    private = {item["fragment_id"]: item for item in fragments if item["visibility"] == "AUTHOR_ONLY"}
    for item in candidate.get("author_design_decisions") or []:
        if item.get("fragment_id") in private:
            _require(item.get("decision") in {"RETAIN_PRIVATE", "REJECT"} and item.get("target_pointer") == "" and item.get("realization_excerpt") == "", "Author private adoption cannot be projected through a public parent field")
    def check(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key not in {"constraint_envelope", "author_design", "author_design_decisions", "author_design_projection", "execution_evidence", "frozen_inputs"}:
                    check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check(item)
        elif isinstance(value, str):
            _require(not any(item["text"] in value for item in private.values()), "Author private source text cannot be copied into a public candidate field")
    check(candidate)


def without_author_private(value: Any) -> Any:
    if isinstance(value, Mapping):
        binding = (value.get("constraint_envelope") or {}).get("author_design")
        if binding:
            _require_private_candidate_boundary(value, binding["fragments"])
        return {key: without_author_private(item) for key, item in value.items() if key not in {"author_design", "author_design_decisions", "author_design_projection"}}
    if isinstance(value, (list, tuple)):
        return [without_author_private(item) for item in value]
    return deepcopy(value)


def evaluation_author_view(content: Mapping[str, Any], *, generator: str = "") -> dict[str, Any]:
    payload = content.get("candidate_payload") or content
    binding = (payload.get("constraint_envelope") or {}).get("author_design")
    if not binding:
        return deepcopy(dict(content))
    generator = str(content.get("generator_operation_name") or generator)
    logical_key = str(content.get("logical_key") or "")
    if generator == "chapter_plan.generate" and not logical_key:
        logical_key = "chapter:" + str(payload.get("chapter_number") or payload.get("chapter") or "")
    result = without_author_private(content)
    result["author_design_projection"] = frozen_author_projection(payload, generator=generator, logical_key=logical_key)
    result["author_design_decisions"] = deepcopy(payload.get("author_design_decisions") or [])
    return result
