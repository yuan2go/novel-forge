from __future__ import annotations

from copy import deepcopy

from novel_forge.modules.story_planning_runtime.narrative_search import (
    CREATIVE_INTELLIGENCE_DIMENSIONS,
    NARRATIVE_SEARCH_PROJECTION_VERSION,
)


def current_planning_fixture_response(stage, inputs, database_url):
    from novel_forge.modules.story_planning_runtime.execution import planning_fixture_response

    frozen = current_planning_fixture_inputs({**inputs, "stage": stage}, database_url)
    return current_planning_wire_result(planning_fixture_response(stage, frozen), frozen)


def current_planning_wire_result(result, inputs):
    command = inputs.get("planning_command") or {}
    value = deepcopy(result)
    if command.get("creative_requirements_contract") in {"work-requirements.v1", "work-requirements.v2"}:
        for row in value.get("chapter_function_matrix", []):
            row["required_state_delta"] = {"status": "CHANGED", **row["required_state_delta"]}
        for event in value.get("narrative_event_chain", []):
            event["feature_status"] = {name: {"status": "APPLICABLE", "rationale": "Selected causal strategy of this synthetic mystery fixture"}
                for name in ("decision", "resistance", "irreversible_change")}
        if inputs.get("stage") == "chapter_plan.generate":
            value["chapter_contract_schema_version"] = (
                "chapter-mission-scene.v4" if command.get("execution_contract_version") in {"1.19.0", "1.20.0", "1.21.0"}
                else "chapter-mission-scene.v3")
            if value["chapter_contract_schema_version"] == "chapter-mission-scene.v4":
                value["serialization_function"] = "payoff_and_new_obligation"
            value["required_state_delta"] = {"status": "CHANGED", **value["required_state_delta"]}
    if command.get("execution_contract_version") != "1.21.0":
        return value
    story_state = (command.get("input_versions") or {}).get("story_state")
    if story_state is not None and "entry_state_ref" in value:
        value["entry_state_ref"] = story_state
        for segment in value.get("narrative_segments", []):
            segment["entry_state_ref"] = story_state
    if inputs.get("stage") == "book_plan.generate":
        target = value["length_strategy"]["target_chapters"]
        volumes = value["volume_skeleton"]
        width = (target + len(volumes) - 1) // len(volumes)
        for index, volume in enumerate(volumes):
            volume["chapter_range"] = [index * width + 1, min((index + 1) * width, target)]
    if inputs.get("stage") in {"book_plan.generate", "arc_plan.generate"}:
        value.pop("parent_version_id", None)
    if inputs.get("stage") == "chapter_plan.generate":
        value.pop("actual_arc_contributions", None)
        from novel_forge.modules.story_planning_runtime.domain import CHAPTER_SCHEDULE_FIELDS, CHAPTER_READER_SCHEDULE_FIELDS, require_chapter_schedule_row

        rows = [segment["content"] for segment in inputs.get("controlled_frozen_segments", []) if segment.get("role") == "chapter_function_matrix_row"]
        if len(rows) != 1:
            raise ValueError("current Chapter fixture requires its exact frozen Scheduling row")
        source = rows[0]
        if source.get("contract_version") == "planning-chapter-matrix-reference.v1":
            group_index = int(source["json_pointer"].split("/")[2])
            source = inputs["controlled_frozen_segments"][group_index]["content"]
        row = require_chapter_schedule_row(source, chapter_number=value["chapter_number"])
        for field in CHAPTER_SCHEDULE_FIELDS:
            value[field] = deepcopy(row[field])
        for field in CHAPTER_READER_SCHEDULE_FIELDS:
            value["reader_experience"][field] = deepcopy(row["reader_experience"][field])
    if inputs.get("stage") in {"chapter_group_plan.generate", "chapter_plan.generate"}:
        casts = [inputs["controlled_frozen_cast"]] if "controlled_frozen_cast" in inputs else [segment["content"] for segment in inputs.get("controlled_frozen_segments", []) if segment.get("role") == "character_cast"]
        if len(casts) == 1 and len(casts[0].get("characters", [])) == 1:
            actor = casts[0]["characters"][0]["character_id"]
            from novel_forge.modules.hierarchical_planning.domain import character_planning_locator

            locator = character_planning_locator(actor)
            def bind_fixture_actor(item):
                if isinstance(item, dict):
                    return {key: bind_fixture_actor(child) for key, child in item.items()}
                if isinstance(item, list):
                    return [bind_fixture_actor(child) for child in item]
                if item == "protagonist":
                    return locator
                if item == "character:protagonist":
                    return locator
                return item
            value = bind_fixture_actor(value)
    fields = {
        "world_realization": {"invariant_refs": "WORLD_INVARIANT", "structure_refs": "WORLD_STRUCTURE", "state_ref": "WORLD_STATE"},
        "character_realization": {"identity_ref": "CHARACTER_IDENTITY", "state_ref": "CHARACTER_STATE", "trajectory_ref": "CHARACTER_TRAJECTORY"},
    }
    reference_contract = inputs.get("realization_reference_contract") or {}
    cast = (reference_contract.get("character_references") or {}).get("bindings", [])
    if len(cast) == 1:
        character = cast[0]["character_id"]
        for collection in ("character_realization", "character_participation"):
            for entity in value.get(collection, []):
                if entity.get("character_id") == "protagonist":
                    entity["character_id"] = character
        for scene in value.get("scene_plan", []):
            if scene.get("pov_character_id") == "protagonist":
                scene["pov_character_id"] = character
            if isinstance(scene.get("participants"), list):
                scene["participants"] = [character if item == "protagonist" else item for item in scene["participants"]]
    catalog = reference_contract.get("references_by_domain", {})
    for manifest, domains in fields.items():
        for entity in value.get(manifest, []):
            levels = ("ANCHOR", "DEFINED", "DETAILED", "ACTIVE")
            old_level, required_level = entity.get("realization_level"), value.get("realization_level")
            if (entity.get("narrative_relevance") == "CURRENT" and old_level in levels
                    and required_level in levels and levels.index(old_level) < levels.index(required_level)):
                entity["realization_level"] = required_level
            for field, domain in domains.items():
                raw = entity[field]
                selected = []
                for reference in raw if isinstance(raw, list) else [raw]:
                    candidates = catalog.get(domain, [])
                    matches = [item for item in candidates if item["asset_version_id"] == reference["asset_version_id"]]
                    if len(matches) != 1:
                        if len(candidates) != 1:
                            raise ValueError(f"current fixture has no unambiguous frozen {domain} source")
                        matches = candidates
                    selected.append({"asset_version_id": matches[0]["asset_version_id"]})
                entity[field] = selected if isinstance(raw, list) else selected[0]
    return value


def current_foundation_search_result(result, inputs):
    task = inputs.get("foundation_task") or {}
    if task.get("contract_version") != "foundation-generation.v5":
        return result
    command = inputs["planning_command"]
    if command.get("execution_contract_version") != "1.21.0" or not command.get("narrative_search_id"):
        raise ValueError("Foundation search fixture requires the current frozen search command")
    branch = command["narrative_search_branch_key"]
    directive = command["narrative_search_strategy_directive"]
    if not branch or not directive:
        raise ValueError("Foundation search fixture requires its frozen branch strategy")
    value = deepcopy(result)
    value["constraints"].append(f"Candidate direction: {directive}")
    value["narrative_search_projection"] = {
        "contract_version": NARRATIVE_SEARCH_PROJECTION_VERSION,
        "strategy_fingerprint": f"controlled-foundation:{branch}:{directive}",
        "assumptions": ["No accepted story state exists at this Foundation comparison boundary"],
        "projected_consequences": [f"Explore a candidate direction under {directive}"],
        "narrative_opportunities": [f"Keep a distinct future option under {directive}"],
        "narrative_risks": [f"The {directive} direction could compress later choices"],
        "irreversible_decisions": [],
        "future_options": [f"Compare {directive} before approving a Foundation"],
        "repetition_keys": [f"controlled-foundation:{branch}"],
        "creative_intelligence": {dimension: 0.7 for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS},
        "selection_summary": f"Scripted candidate estimate for {directive}; literary quality is unproven",
    }
    return value


def current_world_disclosure_result(result, task):
    import json

    if task.get("epistemic_contract") != "world-agency.v2":
        return result
    value = deepcopy(result)
    for candidate in value.get("candidates", []):
        raw = json.loads(candidate["transition"]["payload_json"])
        if raw.get("state_kind") != "disclosure_event" or raw.get("transition_id") != "reveal-accepted-notice":
            continue
        event_id = raw["changes"]["fact_id"]
        sources = [entry for entry in task["context_projection"]["selection"]
                   if entry["source_event_id"] == event_id and entry["state_kind"] == "world_state"
                   and isinstance(entry["state"].get("status"), str)]
        characters = task.get("character_definitions") or []
        if len(sources) != 1 or not characters:
            raise ValueError("current disclosure fixture requires a frozen objective status and an approved character")
        disclosure = [row for row in candidate.get("information_scope", {}).get("disclosures", []) if row["event_id"] == event_id]
        if len(disclosure) != 1 or not disclosure[0].get("presentation_channel"):
            raise ValueError("current disclosure fixture requires an exact declared presentation channel")
        source = sources[0]
        actor = characters[0]["character_id"]
        knowledge_key = f"character_id={actor}&fact_id={event_id}"
        predicate = {"requirement_id": "observe-accepted-notice-status", "state_kind": "world_state",
                     "entity_key": source["entity_key"], "field": "status", "operator": "EQUALS", "value": source["state"]["status"]}
        observe = {
            "transition_id": "observe-accepted-notice", "actor_id": actor, "camera": "ON_CAMERA",
            "story_time": deepcopy(raw["story_time"]), "action": "Observe the supplied notice status before disclosing it",
            "action_mode": "PERCEPTION", "state_kind": "character_knowledge", "entity_key": knowledge_key,
            "changes": {"character_id": actor, "fact_id": event_id, "status": "KNOWN",
                        "observation_source": {key: predicate[key] for key in ("state_kind", "entity_key", "field", "value")}},
            "requirements": [predicate], "epistemic_basis": [], "cause_refs": [event_id],
        }
        raw.update(actor_id=actor, action="Disclose the notice status after personally observing it", action_mode="INFORMATION_DEPENDENT",
                   cause_refs=["local:observe-accepted-notice"], requirements=[],
                   epistemic_basis=[{"requirement_id": "own-observed-notice", "state_kind": "character_knowledge",
                                     "entity_key": knowledge_key, "field": "status", "operator": "EQUALS", "value": "KNOWN"}])
        raw["changes"]["presentation_channel"] = disclosure[0]["presentation_channel"]
        raw["story_time"]["start_ordinal"] += 1
        raw["story_time"]["end_ordinal"] += 1
        candidate["transition"]["payload_json"] = json.dumps(raw)
        candidate["affected_entities"] = list(dict.fromkeys([*candidate["affected_entities"], actor]))
        candidate["preparation_paths"] = [{"path_id": "observe-notice-before-disclosure", "rationale": "The actor observes an exact frozen objective source before choosing disclosure; this is an unaccepted preparation proposal.",
                                             "steps": [{"chapter_offset": 0, "transition": {"payload_json": json.dumps(observe)}}]}]
    return value


def current_world_fixture_classification(transition):
    if transition.get("action_mode") == "ROUTINE":
        return transition.get("action") == "act on the approved faction pressure" and transition.get("state_kind") not in {"character_knowledge", "character_belief", "reader_knowledge", "disclosure_event"}
    if transition.get("transition_id") == "observe-accepted-notice":
        return transition.get("action_mode") == "PERCEPTION" and transition.get("state_kind") == "character_knowledge" and transition.get("changes", {}).get("character_id") == transition.get("actor_id") and bool(transition.get("requirements")) and bool(transition.get("changes", {}).get("observation_source"))
    if transition.get("transition_id") == "reveal-accepted-notice":
        return transition.get("action_mode") == "INFORMATION_DEPENDENT" and transition.get("state_kind") == "disclosure_event" and transition.get("cause_refs") == ["local:observe-accepted-notice"] and len(transition.get("epistemic_basis", [])) == 1
    return False


def current_planning_fixture_inputs(inputs, database_url):
    command = inputs.get("planning_command") or {}
    version = command.get("execution_contract_version")
    if version is None and database_url and inputs.get("stage") in {"chapter_group_plan.generate", "chapter_plan.generate"}:
        from novel_forge.storage.authority_uow import AuthorityUnitOfWork
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("SELECT definition_version FROM authority_operation WHERE operation_id=%s AND project_id=%s AND definition_name='story_planning.generate'", [command["generation_operation_id"], command["project_id"]])
            row = uow.cursor.fetchone()
            version = row[0] if row else None
    if version not in {"1.18.0", "1.21.0"} or "realization_reference_contract" in inputs:
        return inputs
    if version == "1.18.0" and inputs.get("stage") not in {"chapter_group_plan.generate", "chapter_plan.generate"}:
        return inputs
    if not database_url:
        raise ValueError("current fixture requires its actual frozen Context view")
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    document = AuthorityAssetQuery(database_url).require(project_id=command["project_id"], logical_ref=f"planning/context_bundles/{command['generation_operation_id']}.json")
    view = document.content["context_manifest"]["provider_context_view"]["compiled_view"]
    frozen_cast = {}
    if inputs.get("stage") in {"chapter_group_plan.generate", "chapter_plan.generate"}:
        from novel_forge.storage.authority_uow import AuthorityUnitOfWork

        with AuthorityUnitOfWork(database_url) as uow:
            edition_run = (command.get("edition_execution") or {}).get("book_run_id")
            uow.cursor.execute("SELECT s.foundation_set FROM authority_book_production b JOIN authority_book_production_input_snapshot s ON s.snapshot_id=b.input_snapshot_id WHERE b.project_id=%s AND b.book_id=%s AND (%s::text IS NULL OR b.book_run_id=%s)", [command["project_id"], command["book_id"], edition_run, edition_run])
            snapshots = uow.cursor.fetchall()
            if len(snapshots) != 1:
                raise ValueError("Chapter fixture requires one exact active Book input snapshot")
            bindings = [b for b in snapshots[0][0]["bindings"] if b["role"] == "CHARACTER_CAST"]
            if len(bindings) != 1:
                raise ValueError("Chapter fixture requires one exact frozen cast")
            binding = bindings[0]
            cast = uow.repositories.asset_documents.require(project_id=command["project_id"], asset_version_id=binding["asset_version_id"])
            if cast.content_hash != binding["content_hash"]:
                raise ValueError("Chapter fixture cast must match the frozen content hash")
            frozen_cast = {"controlled_frozen_cast": deepcopy(cast.content)}
    if version == "1.18.0":
        return {**inputs, **frozen_cast, "controlled_execution_contract_version": version}
    return {**inputs, **frozen_cast, "realization_reference_contract": deepcopy(view["realization_reference_contract"]), "controlled_frozen_segments": deepcopy(view["segments"])}
