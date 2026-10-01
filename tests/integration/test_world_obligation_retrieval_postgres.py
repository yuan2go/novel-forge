from copy import deepcopy
import json

from novel_forge.modules.context_builder.reality_projection import project_role_context
from novel_forge.modules.context_builder.task_context import task_references, world_task_scope
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_control_repositories import BookControlRepository
from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository
from tests.integration import narrative_reality_vertical_support as native_support
from tests.integration import test_core_functional_loops_postgres as core_fixture


def test_native_world_source_retrieves_ordinary_obligation_planting_outside_frontier(monkeypatch, request):
    original_transport = native_support.NativeRealityTransportFixture
    original_vertical = native_support.execute_native_reality_vertical
    obligation_id = "promise:choice"
    retrieved = []

    class OrdinaryObligationTransport(original_transport):
        def __call__(self, stage, inputs):
            result = super().__call__(stage, inputs)
            if stage == "canon_extraction":
                revision = inputs["revision"]
                chapter = int(revision["chapter"])
                result["obligation_changes"] = [
                    {
                        "obligation_id": identity,
                        "obligation_type": "PROMISE",
                        "status": "OPEN",
                        "from_status": "OPEN" if chapter == 2 else None,
                        "priority": "LOW",
                        "target_window": {"status": "UNSCHEDULED", "from_chapter": 0, "to_chapter": 0},
                        "summary": f"Ordinary promise {identity} advances in chapter {chapter}.",
                        "evidence_start": 0,
                        "evidence_end": min(40, len(revision["text"])),
                        "confidence": 1.0,
                    }
                    for identity in [obligation_id]
                ]
                unrelated = []
                for index in range(16):
                    claim = deepcopy(result["canon_facts"][0])
                    claim.update(subject=f"unrelated:context:{index}", predicate="recorded_observation", object=f"neutral:{index}")
                    unrelated.append(claim)
                result["canon_facts"].extend(unrelated)
                result = native_support.scripted_claim_evidence(stage, inputs, result)
            return result

    def verify_source(**arguments):
        evidence = original_vertical(**arguments)
        composition = arguments["composition"]
        snapshot = arguments["snapshot"]
        book_run_id = evidence["book_run_id"]
        book = composition.authority.require(book_run_id)
        assert book["accepted_through_chapter"] == 2
        with AuthorityUnitOfWork(composition.authority.database_url) as uow:
            repository = NarrativeRealityRepository(uow.cursor)
            frontier = repository.require(book_run_id=book_run_id, chapter_number=2)
            uow.cursor.execute(
                """SELECT v.content->'state_events'->i.event_ordinal, v.content_hash
                FROM authority_book_acceptance_lineage(%s) accepted
                JOIN authority_narrative_reality_revision r ON r.acceptance_id=accepted.acceptance_id
                JOIN authority_reality_event_index i ON i.revision_id=r.revision_id
                JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
                WHERE i.state_kind='narrative_obligation'
                  AND v.content->'state_events'->i.event_ordinal->'mutation'->'payload'->>'obligation_id'=%s
                ORDER BY i.accepted_chapter""",
                [book_run_id, obligation_id],
            )
            originals = uow.cursor.fetchall()
            assert len(originals) == 2
            plant, latest = [deepcopy(row[0]) for row in originals]
            assert [event["coordinate"]["source_chapter"] for event in (plant, latest)] == [1, 2]
            assert [event["version"]["entity"] for event in (plant, latest)] == [1, 2]
            assert all("fact_origin" not in event["mutation"]["payload"] and "world_transition" not in event["mutation"]["payload"] for event in (plant, latest))
            assert plant["event_id"] not in {event["event_id"] for event in frontier["events"]}
            assert plant["event_id"] not in {event["event_id"] for event in repository.recent_world_events(book_run_id=book_run_id, through_chapter=2, limit=128)}
            BookControlRepository(uow.cursor).freeze(project_id=snapshot.project_id, book_run_id=book_run_id, chapter_number=3, actor_id=composition.principal.principal_id)
            uow.cursor.execute(
                """SELECT binding.contract_type,binding.asset_version_id
                FROM story_plan_binding binding JOIN active_story_plan_version active USING(binding_id)
                WHERE binding.project_id=%s AND binding.book_id=%s AND binding.freshness='CURRENT'
                  AND binding.contract_type IN ('BOOK','VOLUME','ARC','CHAPTER_GROUP')""",
                [snapshot.project_id, snapshot.book_id],
            )
            roles = {"BOOK": "book_plan", "VOLUME": "volume_plan", "ARC": "arc_plans", "CHAPTER_GROUP": "chapter_group_plan"}
            source_request = {"book_run_id": book_run_id, "input_snapshot_id": book["input_snapshot_id"], "accepted_through_chapter": 2,
                              "story_state_version_id": book["active_story_state_version_id"], "canon_version_id": book["active_canon_snapshot_version_id"],
                              "planning_input_refs": [{"role": roles[kind], "asset_version_id": version} for kind, version in uow.cursor.fetchall()]}
            source = WorldPreparationRepository(uow.cursor).require_source(project_id=snapshot.project_id, book_id=snapshot.book_id, request=source_request)
            task = world_task_scope(chapter=3, intent=source["intent"], planning_window=source["planning_window"], world_foundation=source["world_foundation"])
            selectors = task_references(task)
            assert obligation_id in selectors
            assert not {plant["event_id"], latest["event_id"]}.intersection(selectors)
            events = {event["event_id"]: event for event in source["reality"]["events"]}
            assert events.get(plant["event_id"]) == plant
            assert events.get(latest["event_id"]) == latest
            uow.cursor.execute(
                """SELECT i.event_id FROM authority_book_acceptance_lineage(%s) accepted
                JOIN authority_narrative_reality_revision r ON r.acceptance_id=accepted.acceptance_id
                JOIN authority_reality_event_index i ON i.revision_id=r.revision_id
                JOIN authority_asset_version v ON v.asset_version_id=r.outcome_version_id
                WHERE i.accepted_chapter=1 AND i.state_kind='canon_fact'
                  AND v.content->'state_events'->i.event_ordinal->'mutation'->'payload'->>'predicate'='recorded_observation'""",
                [book_run_id],
            )
            unrelated_old_ids = {row[0] for row in uow.cursor.fetchall()}
            assert len(unrelated_old_ids) == 16
            assert not unrelated_old_ids.intersection(events)
            only_obligation = project_role_context(reality=source["reality"], role="DIRECTOR", token_budget=source["policy"]["context_token_budget"], task={"chapter": 3, "obligation_refs": [obligation_id]})
            formal = PlanningWorldPreparation._task(source, {"asset_version_id": "controlled-source", "content_hash": narrative_hash(source)}, "DIRECTOR")
            current_entry = next(entry for entry in frontier["current_state"]["narrative_obligation"] if entry["source_event_id"] == latest["event_id"])
            assert current_entry["entity_version"] == latest["version"]["entity"]
            expected_states = {plant["event_id"]: plant["mutation"]["payload"], latest["event_id"]: current_entry["state"]}
            for projection in (only_obligation, formal["context_projection"]):
                selected = {row["source_event_id"]: row for row in projection["selection"]}
                assert {plant["event_id"], latest["event_id"]}.issubset(selected)
                for event in (plant, latest):
                    assert narrative_hash(selected[event["event_id"]]["state"]) == narrative_hash(expected_states[event["event_id"]])
                assert selected[plant["event_id"]]["evidence_role"] == "OBLIGATION_PLANTING_OR_ADVANCE"
                assert selected[latest["event_id"]]["evidence_role"] == "CURRENT_STATE"
                assert len(projection["selection"]) < sum(len(entries) for entries in source["reality"]["current_state"].values())
                assert projection["task_workset"]["source_hash"] == narrative_hash(source["reality"])
                assert {row["source_event_id"] for row in projection["selection"] if row["state_kind"] == "narrative_obligation" and row["source_event_id"] in projection["task_workset"]["required_event_ids"]} == {plant["event_id"], latest["event_id"]}
            retrieved.append({"proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "accepted_through_chapter": 2,
                              "events": [{"event_id": event["event_id"], "event_hash": narrative_hash(event), "entity_version": event["version"]["entity"], "outcome_hash": digest} for event, digest in originals]})
        return evidence

    monkeypatch.setattr(native_support, "NativeRealityTransportFixture", OrdinaryObligationTransport)
    monkeypatch.setattr(native_support, "execute_native_reality_vertical", verify_source)
    core_fixture.test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres(request, False)
    assert len(retrieved) == 1
    request.node.user_properties.append(("ordinary_obligation_retrieval", json.dumps(retrieved[0], sort_keys=True)))
