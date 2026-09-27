from __future__ import annotations

from copy import deepcopy

from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.book_edition_repositories import BookEditionRepository
from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository


def accepted_source_evidence(uow, *, project_id: str, source: dict, for_update: bool = True) -> dict:
    repo = BookEditionRepository(uow.cursor)
    revision = repo.revision(project_id=project_id, book_id=source["book_id"], revision_id=source["source_revision_id"], for_update=for_update)
    events = repo.events(revision["revision_id"])
    validations = [event["content"] for event in events if event["event_kind"] == "VALIDATED"
                   and event["content"].get("manifest_digest") == source["source_manifest_digest"]]
    if (revision["manifest_digest"] != source["source_manifest_digest"] or not validations
        or any(event["event_kind"] == "REJECTED" for event in events)):
        raise KernelError("SCREENPLAY_SOURCE_NOT_VALIDATED", "Adaptation requires the exact accepted edition and its native validation")
    validation = validations[-1]
    units = revision["manifest"]["units"]
    accepted = validation.get("accepted_units")
    if accepted is None:
        sources = {item["acceptance_id"]: item for item in revision["manifest"]["sources"]}
        accepted = []
        for unit in units:
            ids = unit.get("source_acceptance_ids", [])
            if len(ids) != 1 or ids[0] not in sources:
                raise KernelError("SCREENPLAY_SOURCE_EVIDENCE_INVALID", "Original manuscript units must retain exact accepted sources")
            accepted.append({"unit_id": unit["unit_id"], **sources[ids[0]]})
    proofs = {item["unit_id"]: item for item in accepted}
    reality = NarrativeRealityRepository(uow.cursor)
    boundaries = {}
    for unit_id in source["selected_unit_ids"]:
        proof = proofs.get(unit_id)
        if not proof:
            raise KernelError("SCREENPLAY_SOURCE_EVIDENCE_INVALID", "Every mapped unit needs its native version acceptance")
        uow.cursor.execute("""SELECT a.book_run_id,a.chapter_number,a.chapter_outcome_asset_version_id,a.story_state_asset_version_id,
            a.canon_snapshot_asset_version_id,a.longform_projection_set_id FROM authority_book_chapter_acceptance a
            JOIN authority_book_production b ON b.book_run_id=a.book_run_id
            WHERE a.project_id=%s AND b.book_id=%s AND a.acceptance_id=%s AND a.status='COMMITTED'""",
            [project_id, source["book_id"], proof["acceptance_id"]])
        row = uow.cursor.fetchone()
        expected = tuple(proof[key] for key in ("outcome_asset_version_id", "story_state_asset_version_id", "canon_snapshot_asset_version_id", "projection_set_id"))
        if not row or row[2:] != expected:
            raise KernelError("SCREENPLAY_SOURCE_EVIDENCE_INVALID", "Edition proof differs from its immutable Book acceptance")
        projected = reality.require(book_run_id=row[0], chapter_number=row[1])
        known, readers, facts, characters = {}, set(), set(), set()
        for kind, entries in projected["current_state"].items():
            for entry in entries:
                state = entry["state"]
                character = state.get("character_id")
                if character:
                    characters.add(character)
                fact = state.get("fact_id")
                if fact:
                    facts.add(fact)
                facts.add(entry["entity_key"])
                if kind == "character_knowledge" and state.get("status") == "KNOWN" and character and fact:
                    known.setdefault(character, set()).add(fact)
                if (kind == "reader_knowledge" and state.get("status") == "KNOWN" and fact
                    and state.get("reader_visibility") != "HIDDEN"
                    and (state.get("fact_origin") or {}).get("kind") not in {"GOVERNED_BACKGROUND", "GOVERNED_PREPARATION"}):
                    readers.add(fact)
        boundaries[unit_id] = {"unit_id": unit_id, "acceptance_id": proof["acceptance_id"], "book_run_id": row[0],
            "chapter_number": row[1], "reality_revision_id": projected["revision_id"],
            **dict(zip(("outcome_asset_version_id", "story_state_asset_version_id", "canon_snapshot_asset_version_id", "projection_set_id"), row[2:])),
            "characters": sorted(characters), "known": {key: sorted(value) for key, value in known.items()},
            "reader_known": sorted(readers), "fact_ids": sorted(facts)}
    policy = source["policy"]["knowledge_contract"]
    scopes = {}
    for scene in source["scene_plan"]:
        mapped = [boundaries[key] for key in scene["source_unit_ids"]]
        earliest = min(mapped, key=lambda item: item["chapter_number"])
        if set(scene["participants"]) - set(earliest["characters"]):
            raise KernelError("SCREENPLAY_CHARACTER_SOURCE_INVALID", "A participant must exist in the mapped accepted narrative state")
        allowed = {actor: sorted(set(policy["character_known_fact_ids"][actor]) & set(earliest["known"].get(actor, [])))
                   for actor in scene["participants"]}
        reader = sorted(set(policy["reader_allowed_fact_ids"]) & set(earliest["reader_known"]))
        available = set().union(*(set(item["fact_ids"]) for item in mapped))
        if set(scene["required_fact_ids"]) - available:
            raise KernelError("SCREENPLAY_FACT_SOURCE_INVALID", "Required facts need exact accepted source evidence")
        scopes[scene["scene_id"]] = {"knowledge_boundary": "EARLIEST_MAPPED_ACCEPTED_UNIT", "boundary_unit_id": earliest["unit_id"],
            "character_known_fact_ids": allowed, "reader_allowed_fact_ids": reader}
    all_known = {actor: set().union(*(set(item["known"].get(actor, [])) for item in boundaries.values()))
                 for actor in policy["character_known_fact_ids"]}
    if (any(set(ids) - all_known[actor] for actor, ids in policy["character_known_fact_ids"].items())
        or set(policy["reader_allowed_fact_ids"]) - set().union(*(set(item["reader_known"]) for item in boundaries.values()))):
        raise KernelError("SCREENPLAY_KNOWLEDGE_SOURCE_INVALID", "An adaptation policy cannot declare new character or reader knowledge")
    return {"contract_version": "screenplay-accepted-source-evidence.v1", "source_revision_id": source["source_revision_id"],
        "units": [boundaries[key] for key in source["selected_unit_ids"]], "scenes": scopes,
        "semantic_review_required": True, "fact_declarations_are_not_semantic_proof": True}



def accepted_character_display(uow, *, project_id: str, source: dict) -> dict:
    units = source["accepted_source_evidence"]["units"]
    displays, refs = {}, []
    for unit in units:
        uow.cursor.execute("""SELECT snapshot.snapshot_id,snapshot.snapshot_hash,snapshot.foundation_set
            FROM authority_book_chapter_acceptance accepted JOIN authority_book_chapter_request request USING(chapter_request_id)
            JOIN authority_book_production_input_snapshot snapshot
                ON snapshot.snapshot_id=request.command_payload #>> '{context_version_refs,book_production_input_snapshot_id}'
            WHERE accepted.project_id=%s AND accepted.acceptance_id=%s AND snapshot.project_id=%s AND snapshot.book_id=%s""",
            [project_id, unit["acceptance_id"], project_id, source["book_id"]])
        row = uow.cursor.fetchone()
        names = {}
        if row is not None:
            bindings = [item for item in row[2].get("bindings", []) if item.get("role") == "CHARACTER_CAST"]
            if len(bindings) != 1:
                raise KernelError("SCREENPLAY_CHARACTER_SOURCE_INVALID", "Accepted Chapter must retain one exact frozen Cast")
            binding = bindings[0]
            cast = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=binding["asset_version_id"])
            if cast.content_hash != binding["content_hash"]:
                raise KernelError("SCREENPLAY_CHARACTER_SOURCE_INVALID", "Frozen Cast hash differs from the accepted Chapter snapshot")
            names = {item["character_id"]: item["name"] for item in cast.content.get("candidate_payload", cast.content).get("characters", [])
                     if item.get("character_id") and isinstance(item.get("name"), str) and item["name"].strip()}
            refs.append({"unit_id": unit["unit_id"], "acceptance_id": unit["acceptance_id"], "input_snapshot_id": row[0],
                "snapshot_hash": row[1], "cast_asset_version_id": cast.asset_version_id, "cast_content_hash": cast.content_hash})
        displays[unit["unit_id"]] = names
    scenes = {}
    by_id = {unit["unit_id"]: unit for unit in units}
    for scene in source["scene_plan"]:
        earliest = min((by_id[key] for key in scene["source_unit_ids"]), key=lambda item: item["chapter_number"])
        names = displays[earliest["unit_id"]]
        scenes[scene["scene_id"]] = {actor: names.get(actor, actor) for actor in scene["participants"]}
    return {"contract_version": "screenplay-character-display.v1", "scenes": scenes, "sources": refs}


def freeze_accepted_source(uow, *, project_id: str, source: dict) -> dict:
    result = deepcopy(source)
    result["accepted_source_evidence"] = accepted_source_evidence(uow, project_id=project_id, source=source)
    if source["schema_version"] == "screenplay-source.v2":
        from .screenplay_craft import freeze_screenplay_craft
        result["screenplay_craft"] = freeze_screenplay_craft(uow, source=source)
        result["character_display"] = accepted_character_display(uow, project_id=project_id, source=result)
    result["source_digest"] = completion_digest({key: value for key, value in result.items() if key != "source_digest"})
    return result
