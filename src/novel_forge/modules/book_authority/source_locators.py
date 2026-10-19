import re

from novel_forge.modules.chapter_authority.author_editor import source_draft_content, text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

from .derived_cache import task_selection_cache

LEGACY_VERSION = "working-source-locators.v1"
VERSION = "working-source-locators.v2"
BOUNDARY = "HISTORICAL_GENERATION_PLAN_LOCATORS_NOT_EVENT_REALIZATION_OR_KNOWLEDGE"


def explicit_chapters(task, target_chapter):
    from novel_forge.modules.source_import.corpus_ingestion.segmentation import chinese_number
    ordinal = r"[0-9０-９零〇○一二三四五六七八九十百千万两]+"
    pattern = re.compile(r"第\s*(" + ordinal + r")(?:\s*(?:至|到|[-—–])\s*第?\s*(" + ordinal + r"))?\s*章|(?i:chapters?)\s+([0-9]+)(?:\s*[-—–]\s*([0-9]+))?")
    result = set()
    for scope in [task, *task.get("scenes", [])]:
        for value in [scope.get("goal", ""), *scope.get("queries", [])]:
            for match in pattern.finditer(value):
                first = chinese_number(match[1] or match[3])
                last = chinese_number(match[2] or match[4] or match[1] or match[3])
                result.update(range(max(1, first), min(last, target_chapter - 1) + 1))
    return result


def freeze_source_locators(uow, book, documents, *, version=VERSION):
    if version not in {LEGACY_VERSION, VERSION}:
        raise KernelError("WORKING_SOURCE_LOCATOR_INVALID", "Unsupported source locator algorithm")
    entries = []
    for chapter, document in documents:
        draft = source_draft_content(document)
        if canonical_hash(document.content) != document.content_hash:
            raise KernelError("WORKING_SOURCE_LOCATOR_INVALID", "Selected manuscript failed its frozen digest")
        pointer = (draft.get("creative_baseline") or {}).get("source_plan")
        entry = {"chapter": chapter, "asset_version_id": document.asset_version_id,
            "content_hash": document.content_hash, "text_hash": text_hash(draft["text"]),
            "plan": None, "event_refs": [], "status": "SOURCE_PLAN_UNAVAILABLE"}
        if pointer is not None:
            if not isinstance(pointer, dict) or set(pointer) != {"asset_version_id", "content_hash"}:
                raise KernelError("WORKING_SOURCE_LOCATOR_INVALID", "A generation plan locator requires its exact pointer")
            plan = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=pointer["asset_version_id"])
            content = plan.content
            if (plan.content_hash != pointer["content_hash"] or canonical_hash(content) != plan.content_hash
                    or plan.asset_type not in {"chapter_plan", "planning_generation_candidate"}
                    or content.get("project_id") != book["project_id"] or content.get("book_id") != book["book_id"]
                    or content.get("chapter", content.get("chapter_number")) != chapter):
                raise KernelError("WORKING_SOURCE_LOCATOR_INVALID", "The historical generation plan must match this selected manuscript")
            key = (version, document.asset_version_id, document.content_hash, plan.asset_version_id, plan.content_hash)
            cached = task_selection_cache.get(key)
            if cached is not None:
                entries.append(cached)
                continue
            events = set()
            realization = content.get("narrative_realization_slice") or {}
            events.update(realization.get("event_ids") or [])
            for scene in content.get("scene_plan") or content.get("scene_sequence") or []:
                events.update(scene.get("realization_event_ids") or [])
            if any(not isinstance(identity, str) or not identity.strip() for identity in events):
                raise KernelError("WORKING_SOURCE_LOCATOR_INVALID", "Historical event locators require literal identifiers")
            entry.update(plan=pointer, event_refs=sorted(events), status="HISTORICAL_PLAN_HINT_ONLY")
            task_selection_cache.put(key, entry)
        entries.append(entry)
    body = {"version": version, "boundary": BOUNDARY, "entries": entries}
    return {**body, "index_hash": canonical_hash(body)}


def source_locator_receipt(index, task, target_chapter):
    if (index.get("version") not in {LEGACY_VERSION, VERSION} or index.get("boundary") != BOUNDARY
            or index.get("index_hash") != canonical_hash({key: value for key, value in index.items() if key != "index_hash"})):
        raise KernelError("WORKING_SOURCE_LOCATOR_INVALID", "Source locators require their original checked index")
    scopes = [task, *task.get("scenes", [])]
    events = {value for scope in scopes for value in scope.get("event_refs", [])}
    chapters = explicit_chapters(task, target_chapter)
    current = index["version"] == VERSION
    selected = []
    for entry in index["entries"]:
        matched = sorted(events.intersection(entry["event_refs"]))
        handoff = current and entry["chapter"] == task.get("handoff_predecessor")
        if matched or entry["chapter"] in chapters or handoff:
            selected.append({**entry, "matched_event_refs": matched,
                "explicit_chapter_reference": entry["chapter"] in chapters,
                **({"predecessor_handoff": handoff} if current else {})})
    body = {"version": index["version"], "boundary": BOUNDARY, "index_hash": index["index_hash"],
        "source_count": len(index["entries"]), "unavailable_plan_count": sum(entry["plan"] is None for entry in index["entries"]),
        "selected": selected, "unlocated_event_refs": sorted(events - {value for entry in selected for value in entry["matched_event_refs"]})}
    return {**body, "receipt_hash": canonical_hash(body)}


def validate_locator_receipt(receipt, task, sources, target_chapter):
    failure = KernelError("WORKING_SOURCE_LOCATOR_INVALID", "Task locators must bind historical source plans and complete selected prose")
    if (not isinstance(receipt, dict) or set(receipt) != {"version", "boundary", "index_hash", "source_count", "unavailable_plan_count", "selected", "unlocated_event_refs", "receipt_hash"}
            or receipt.get("version") not in {LEGACY_VERSION, VERSION} or receipt.get("boundary") != BOUNDARY
            or receipt.get("receipt_hash") != canonical_hash({key: value for key, value in receipt.items() if key != "receipt_hash"})
            or receipt.get("source_count") != target_chapter - 1
            or type(receipt.get("unavailable_plan_count")) is not int or not 0 <= receipt["unavailable_plan_count"] <= receipt["source_count"]
            or not isinstance(receipt.get("selected"), list) or not isinstance(receipt.get("unlocated_event_refs"), list)):
        raise failure
    current = receipt["version"] == VERSION
    by_id = {source["asset_version_id"]: source for source in sources}
    events = {value for scope in [task, *task.get("scenes", [])] for value in scope.get("event_refs", [])}
    chapters = explicit_chapters(task, target_chapter)
    identities = []
    for entry in receipt["selected"]:
        if (not isinstance(entry, dict) or set(entry) != {"chapter", "asset_version_id", "content_hash", "text_hash", "plan", "event_refs", "status", "matched_event_refs", "explicit_chapter_reference"} | ({"predecessor_handoff"} if current else set())
                or entry.get("asset_version_id") not in by_id or not isinstance(entry.get("event_refs"), list)
                or any(not isinstance(ref, str) or not ref for ref in entry["event_refs"])
                or entry.get("matched_event_refs") != sorted(events.intersection(entry["event_refs"]))
                or type(entry.get("explicit_chapter_reference")) is not bool
                or entry["explicit_chapter_reference"] != (entry["chapter"] in chapters)
                or current and (type(entry.get("predecessor_handoff")) is not bool or entry["predecessor_handoff"] != (entry["chapter"] == task.get("handoff_predecessor")))
                or not (entry["matched_event_refs"] or entry["explicit_chapter_reference"] or current and entry["predecessor_handoff"])):
            raise failure
        source = by_id[entry["asset_version_id"]]
        if any(entry[key] != source[key] for key in ("chapter", "asset_version_id", "content_hash", "text_hash")):
            raise failure
        if entry["plan"] is None:
            if entry["status"] != "SOURCE_PLAN_UNAVAILABLE" or entry["event_refs"]:
                raise failure
        elif (not isinstance(entry["plan"], dict) or set(entry["plan"]) != {"asset_version_id", "content_hash"}
                or entry["status"] != "HISTORICAL_PLAN_HINT_ONLY"):
            raise failure
        identities.append(entry["asset_version_id"])
    located = {value for entry in receipt["selected"] for value in entry["matched_event_refs"]}
    required = chapters | ({task["handoff_predecessor"]} if current and task.get("handoff_predecessor", 0) > 0 else set())
    if (len(identities) != len(set(identities)) or receipt["unlocated_event_refs"] != sorted(events - located)
            or current and not required.issubset({entry["chapter"] for entry in receipt["selected"]})):
        raise failure
