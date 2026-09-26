from copy import deepcopy
import json

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration import test_core_functional_loops_postgres as core
from tests.integration import world_causal_production_support as world
from tests.integration import hierarchy_closure_postgres_support as hierarchy


def test_actor_receipt_recovery_continues_through_native_acceptances(
    request, monkeypatch
):
    state = {}
    seed_inputs = core._seed_inputs
    foundation = hierarchy._payload

    def actor_foundation(role, **kwargs):
        result = foundation(role, **kwargs)
        if "characters" in result:
            companion = deepcopy(result["characters"][0])
            companion.update(
                character_id="ilya",
                name="Ilya",
                aliases=["Ilya"],
                desire="protect witnesses",
                secret="PRIVATE_ILYA_SECRET_MARKER",
                arc_direction="FUTURE_ILYA_ARC_MARKER",
            )
            result["characters"].append(companion)
            result["characters"][0]["secret"] = "PRIVATE_MARA_SECRET_MARKER"
        return result

    def seed_actor_inputs(project_id, book_id, **kwargs):
        kwargs["world_production_policy"] = {
            "version": "world-production-policy.v2",
            "max_provider_stages": 4,
            "max_candidates": 2,
            "max_paths_per_candidate": 1,
            "max_preparation_steps": 1,
            "planning_window_chapters": 1,
            "context_token_budget": 16000,
        }
        kwargs["initial_current_state"] = {
            "character_knowledge": [
                {
                    "entity_key": f"character_id={actor}|fact_id={actor}-observation",
                    "source_event_id": f"fixture-initial:{actor}:observed",
                    "state": {
                        "character_id": actor,
                        "fact_id": f"{actor}-observation",
                        "status": "KNOWN",
                        "content": f"PRIVATE_OBSERVATION_{actor.upper()}",
                    },
                }
                for actor in ("mara", "ilya")
            ]
        }
        generic = seed_inputs(project_id, book_id, **kwargs)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
                [generic["production_profile"]],
            )
            content = uow.cursor.fetchone()[0]
            content["world_actor_experiment"] = {
                "version": "world-actor-experiment.v1",
                "actor_ids": ["mara", "ilya"],
                "max_rounds": 1,
                "max_actions_per_actor": 1,
            }
            replacement = generic["production_profile"] + ":actor-fixture"
            uow.cursor.execute(
                "UPDATE authority_asset_version SET lifecycle='SUPERSEDED' WHERE asset_version_id=%s",
                [generic["production_profile"]],
            )
            uow.cursor.execute(
                """INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version)
                SELECT %s,asset_id,2,'ACTIVE',eligibility,governance,%s,%s,schema_version FROM authority_asset_version WHERE asset_version_id=%s""",
                [
                    replacement,
                    Jsonb(content),
                    canonical_hash(content),
                    generic["production_profile"],
                ],
            )
            generic["production_profile"] = replacement
            uow.commit()
        state.update(project_id=project_id, book_id=book_id)
        return generic

    class ActorTransport(world.AutonomousWorldTransport):
        def __init__(self, scenario):
            super().__init__(scenario)
            state["transport"] = self

        def __call__(self, stage, inputs):
            if stage.startswith("world_candidates.actor_"):
                return self.planning(stage, inputs)
            result = super().__call__(stage, inputs)
            if stage in {"draft", "revision", "canon_extraction"}:
                chapter = int(inputs[{"draft": "plan", "revision": "draft", "canon_extraction": "revision"}[stage]]["chapter"])
                promise = "Mara promises to protect the witnesses until they reach sanctuary."
                continued = "Mara carries out the same promise by delivering their testimony, while the witnesses still await safe passage."
                statement = promise if chapter == 1 else continued
                attitudes = {"mara": "Mara trusts Ilya to guard the witnesses.", "ilya": "Ilya privately still doubts Mara's caution."}
                if stage in {"draft", "revision"} and statement not in result["text"]:
                    result["scene_artifacts"][-1]["text"] += " " + " ".join((statement, *attitudes.values()))
                    result["text"] = "\n\n".join(item["text"] for item in result["scene_artifacts"])
                if stage == "canon_extraction":
                    text = inputs["revision"]["text"]
                    start = text.index(statement)
                    evidence = {"summary": statement, "evidence_start": start,
                                "evidence_end": start + len(statement), "confidence": 1.0}
                    result["promise_changes"].append({**evidence, "character_id": "mara",
                        "promise_id": "mara:protect-witnesses", "status": "OPEN",
                        **({"from_status": "OPEN"} if chapter > 1 else {})})
                    result["character_state_changes"].append({**evidence, "character_id": "mara",
                        "action_state": "PRESERVING_TESTIMONY" if chapter == 1 else "DELIVERING_TESTIMONY"})
                    result["relationship_changes"].extend([
                        {"source_id": actor, "target_id": "ilya" if actor == "mara" else "mara",
                         "status": "TRUSTING" if actor == "mara" else "DOUBTFUL",
                         "summary": f"{actor.upper()}_PRIVATE_ATTITUDE " + attitude,
                         "evidence_start": text.index(attitude), "evidence_end": text.index(attitude) + len(attitude),
                         "confidence": 1.0}
                        for actor, attitude in attitudes.items()
                    ])
                    from tests.integration.narrative_reality_vertical_support import scripted_claim_evidence
                    result = scripted_claim_evidence(stage, inputs, result)
                self.calls[-1]["output"] = result
            return result

        def planning(self, stage, inputs):
            if stage.startswith("world_candidates.actor_"):
                task = inputs["world_preparation"]
                private = task["private_observation"]
                encoded = json.dumps(inputs)
                assert "PRIVATE_MARA_SECRET_MARKER" not in encoded
                assert "PRIVATE_ILYA_SECRET_MARKER" not in encoded
                assert "FUTURE_ILYA_ARC_MARKER" not in encoded
                assert set(private["traits"]) <= {
                    "name",
                    "desire",
                    "need",
                    "fear",
                    "false_belief",
                    "moral_boundary",
                    "capability",
                    "weakness",
                    "behavioral_pattern",
                    "risk_preference",
                }
                assert all(
                    row["content"]["character_id"] == private["actor_id"]
                    for row in private["observations"]
                )
                assert len(private["observations"]) == 1
                own_state = private["accepted_self_state"]
                assert task["contract_version"] == "world-actor-task.v2"
                if task["accepted_through_chapter"]:
                    assert "ILYA_PRIVATE_ATTITUDE" not in encoded and "MARA_PRIVATE_ATTITUDE" not in encoded
                    relationships = [row["content"] for row in own_state if row["kind"] == "relationship_state"]
                    assert len(relationships) == 1
                    assert relationships[0]["source_id"] == private["actor_id"]
                    assert relationships[0]["status"] == ("TRUSTING" if private["actor_id"] == "mara" else "DOUBTFUL")
                    if private["actor_id"] == "mara":
                        assert any(row["content"].get("action_state") == "PRESERVING_TESTIMONY" for row in own_state)
                        assert any(row["content"].get("obligation_id") == "mara:protect-witnesses" for row in own_state)
                commitments = [row for row in own_state if row["kind"] == "narrative_obligation" and row["content"].get("status") in {"OPEN", "DEVELOPING", "DUE"}]
                self.calls.append({"stage": stage, "input": deepcopy(inputs)})
                return {
                    "actor_id": private["actor_id"],
                    "action": "protect the witnesses"
                    if private["actor_id"] == "ilya"
                    else "deliver the preserved witness testimony" if commitments else "preserve the witness testimony",
                    "basis_summary": "Own frozen observation and personal desire motivate this candidate action.",
                    "basis_refs": [
                        "APPROVED_SELF_TRAITS",
                        private["observations"][0]["source_event_id"],
                        *[row["source_event_id"] for row in commitments],
                    ],
                    "commitment_dispositions": [
                        {"obligation_id": row["content"]["obligation_id"], "source_event_id": row["source_event_id"],
                         "decision": "CONTINUE", "reason": "Continue the accepted promise through the same witness testimony."}
                        for row in commitments
                    ],
                }
            result = super().planning(stage, inputs)
            if stage == "world_candidates.generate":
                proposals = inputs["world_preparation"]["actor_proposals"]
                if result["candidates"]:
                    transition = json.loads(
                        result["candidates"][0]["transition"]["payload_json"]
                    )
                    transition.update(
                        actor_id=proposals[0]["actor_id"], action=proposals[0]["action"]
                    )
                    transition["epistemic_basis"] = [
                        {
                            "requirement_id": "own-frozen-observation",
                            "state_kind": "character_knowledge",
                            "entity_key": f"character_id={proposals[0]['actor_id']}|fact_id={proposals[0]['actor_id']}-observation",
                            "field": "status",
                            "operator": "EQUALS",
                            "value": "KNOWN",
                        }
                    ]
                    transition["cause_refs"].extend(proposals[0]["basis_refs"][1:])
                    result["candidates"][0]["transition"]["payload_json"] = json.dumps(
                        transition
                    )
                    result["candidates"][0]["obligation_refs"] = [
                        row["obligation_id"] for row in proposals[0]["commitment_dispositions"] if row["decision"] == "CONTINUE"
                    ]
                result["actor_adjudications"] = [
                    {
                        "actor_id": proposal["actor_id"],
                        "proposal_hash": proposal["proposal_hash"],
                        "decision": "EXECUTABLE"
                        if index == 0 and result["candidates"]
                        else "REJECTED",
                        "consequence_summary": "The world judge admits one feasible transition and preserves the other intention as rejected.",
                    }
                    for index, proposal in enumerate(proposals)
                ]
            return result

        def post_provider_checkpoint(self, point):
            if (
                point != "after_provider_receipt_before_budget_settlement"
                or self.faults
                or self.calls[-1]["stage"] != "world_candidates.actor_1"
            ):
                return
            self.faults.append(point)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """SELECT a.asset_type, count(*) FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                    WHERE a.project_id=%s AND a.asset_type IN ('world_actor_proposal','world_preparation_generation','narrative_governance_action') GROUP BY a.asset_type""",
                    [state["project_id"]],
                )
                counts = dict(uow.cursor.fetchall())
                assert counts.get("world_actor_proposal") == 1
                assert counts.get("world_preparation_generation", 0) == 0
                assert counts.get("narrative_governance_action", 0) == 0
                uow.cursor.execute(
                    "SELECT accepted_through_chapter FROM authority_book_production WHERE project_id=%s",
                    [state["project_id"]],
                )
                assert all(row[0] == 0 for row in uow.cursor.fetchall())
                uow.cursor.execute(
                    "SELECT count(*) FROM authority_narrative_reality_revision WHERE project_id=%s",
                    [state["project_id"]],
                )
                assert uow.cursor.fetchone()[0] == 0
                uow.cursor.execute(
                    """SELECT e.external_effect_id,d.dispatch_id,r.external_receipt_id,e.request_payload
                    FROM authority_external_effect e
                    JOIN authority_external_effect_dispatch d USING(external_effect_id)
                    JOIN authority_external_receipt r USING(dispatch_id)
                    WHERE e.project_id=%s AND e.request_payload->>'stage'='world_candidates.actor_1'""",
                    [state["project_id"]],
                )
                receipts = uow.cursor.fetchall()
                assert len(receipts) == 1
                state["recovered_actor_receipt"] = receipts[0]
            raise KernelError(
                "MODEL_EFFECT_RETRYABLE_WORLD_PROOF",
                "fixture process loss after second Actor receipt",
            )

    monkeypatch.setattr(hierarchy, "_payload", actor_foundation)
    monkeypatch.setattr(core, "_seed_inputs", seed_actor_inputs)
    monkeypatch.setattr(world, "AutonomousWorldTransport", ActorTransport)
    core.test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres(
        request, "provider_recovery"
    )
    calls = state["transport"].calls
    final = json.loads(
        next(
            value
            for key, value in request.node.user_properties
            if key == "narrative_reality_vertical"
        )
    )
    actor_requests = [
        row
        for row in final["final_provider_requests"]
        if row["stage"].startswith("world_candidates.actor_")
    ]
    assert len(actor_requests) == 4
    for row in actor_requests:
        own, other = (
            ("MARA", "ILYA") if row["stage"].endswith("_0") else ("ILYA", "MARA")
        )
        assert f"PRIVATE_OBSERVATION_{own}" in row["input_text"]
        assert f"PRIVATE_OBSERVATION_{other}" not in row["input_text"]
        assert "PRIVATE_MARA_SECRET_MARKER" not in row["input_text"]
        assert "PRIVATE_ILYA_SECRET_MARKER" not in row["input_text"]
        assert "FUTURE_ILYA_ARC_MARKER" not in row["input_text"]
        assert "MARA_PRIVATE_ATTITUDE" not in row["input_text"]
        assert "ILYA_PRIVATE_ATTITUDE" not in row["input_text"]
    assert {
        call["input"]["world_preparation"]["baseline_kind"]
        for call in calls
        if call["stage"].startswith("world_candidates.actor_")
    } == {"APPROVED_FOUNDATION", "ACCEPTED_REALITY"}
    assert len(state["transport"].faults) == 1
    for stage in ("world_candidates.actor_0", "world_candidates.actor_1"):
        assert len([call for call in calls if call["stage"] == stage]) == 2
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
        from novel_forge.modules.worldbuilding.actor_isolation import accepted_self_state

        uow.cursor.execute("SELECT accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s", [final["book_run_id"]])
        assert uow.cursor.fetchone()[0] == 2
        first = NarrativeRealityRepository(uow.cursor).require(book_run_id=final["book_run_id"], chapter_number=1)
        second = NarrativeRealityRepository(uow.cursor).require(book_run_id=final["book_run_id"], chapter_number=2)
        own = [accepted_self_state({"reality": reality}, "mara") for reality in (first, second)]
        promises = [[row for row in rows if row["kind"] == "narrative_obligation" and row["content"]["obligation_id"] == "mara:protect-witnesses"] for rows in own]
        assert all(len(rows) == 1 and rows[0]["content"]["status"] == "OPEN" for rows in promises)
        assert promises[0][0]["source_event_id"] != promises[1][0]["source_event_id"]
        assert [next(row["entity_version"] for row in reality["current_state"]["narrative_obligation"] if row["state"]["obligation_id"] == "mara:protect-witnesses") for reality in (first, second)] == [1, 2]
        uow.cursor.execute("SELECT count(*) FROM authority_narrative_reality_revision WHERE book_run_id=%s", [final["book_run_id"]])
        assert uow.cursor.fetchone()[0] == 2
        assert "same promise" in promises[1][0]["content"]["current_development"]
        subsequent_actor = next(call["input"]["world_preparation"] for call in calls if call["stage"] == "world_candidates.actor_0" and call["input"]["world_preparation"]["accepted_through_chapter"] == 1)
        assert subsequent_actor["private_observation"]["accepted_self_state"] == own[0]
        assert subsequent_actor["baseline_id"] == first["revision_id"]
        uow.cursor.execute(
            """SELECT e.external_effect_id,d.dispatch_id,r.external_receipt_id,e.request_payload
            FROM authority_external_effect e
            JOIN authority_external_effect_dispatch d USING(external_effect_id)
            JOIN authority_external_receipt r USING(dispatch_id)
            WHERE e.external_effect_id=%s AND e.status='SUCCEEDED'""",
            [state["recovered_actor_receipt"][0]],
        )
        assert uow.cursor.fetchall() == [state["recovered_actor_receipt"]]
        uow.cursor.execute(
            """SELECT request_payload->>'stage', count(*), bool_and(status='SUCCEEDED')
            FROM authority_external_effect WHERE project_id=%s AND request_payload->>'stage' LIKE 'world_candidates.actor_%%'
            GROUP BY request_payload->>'stage' """,
            [state["project_id"]],
        )
        assert sorted(uow.cursor.fetchall()) == [
            ("world_candidates.actor_0", 2, True),
            ("world_candidates.actor_1", 2, True),
        ]
        uow.cursor.execute(
            """SELECT count(*) FROM authority_external_effect_dispatch d JOIN authority_external_effect e USING(external_effect_id)
            WHERE e.project_id=%s AND e.request_payload->>'stage' LIKE 'world_candidates.actor_%%' """,
            [state["project_id"]],
        )
        assert uow.cursor.fetchone()[0] == 4
        uow.cursor.execute(
            """SELECT e.request_payload->>'stage', count(DISTINCT e.external_effect_id),
                      bool_and(e.status='SUCCEEDED'), count(DISTINCT d.dispatch_id),
                      count(DISTINCT r.external_receipt_id)
               FROM authority_external_effect e
               LEFT JOIN authority_external_effect_dispatch d USING(external_effect_id)
               LEFT JOIN authority_external_receipt r USING(dispatch_id)
               WHERE e.project_id=%s AND e.request_payload->>'stage' IN
                     ('world_candidates.generate','world_candidates.evaluate')
               GROUP BY e.request_payload->>'stage'""",
            [state["project_id"]],
        )
        assert sorted(uow.cursor.fetchall()) == [
            ("world_candidates.evaluate", 2, True, 2, 2),
            ("world_candidates.generate", 2, True, 2, 2),
        ]

    import subprocess
    import sys

    recovered = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from novel_forge.modules.narrative_state import NarrativeStateRebuildService
from novel_forge.modules.worldbuilding.actor_isolation import accepted_self_state
rebuilt = NarrativeStateRebuildService(sys.argv[1]).rebuild(project_id=sys.argv[2], book_id=sys.argv[3])
print(json.dumps(accepted_self_state({"reality": rebuilt.projection}, "mara")))
""", DATABASE_URL, state["project_id"], state["book_id"]],
        check=True, capture_output=True, text=True, timeout=30,
    )
    assert json.loads(recovered.stdout) == own[1]
