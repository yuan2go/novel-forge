from __future__ import annotations

import json
from typing import Any

from novel_forge.modules.book_authority.production import StartBookProductionCommand
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.execution_gateway import (
    default_chapter_fixture_response,
)
from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import (
    execute_book_coordination_claim,
    schedule_book_coordination_jobs,
)


def compiled_world_fixture():
    return {
        "contract_version": "world-foundation.v1",
        "genre_profile": "institutional-mystery.v1",
        "compiled_scope": "ARC",
        "sections": {
            "core_laws": {
                "depth": "WORKING",
                "content": "A witnessed inquiry cannot be sealed by decree.",
            },
            "book:council": {
                "depth": "SEED",
                "content": "Only the current council inquiry is compiled.",
            },
        },
        "entities": [{"entity_id": "faction:council", "kind": "FACTION"}],
        "rules": [
            {
                "rule_id": "witnessed-inquiry-open",
                "category": "core_laws",
                "statement": "The witnessed inquiry remains open.",
                "enforcement": "HARD",
                "applicability": ["world_state"],
                "consequences": ["Sealing the inquiry is rejected."],
                "predicate": {
                    "requirement_id": "inquiry-open",
                    "state_kind": "world_state",
                    "entity_key": "world_state_id=council-inquiry",
                    "field": "status",
                    "operator": "EQUALS",
                    "value": "OPEN",
                },
            }
        ],
    }


class NativeRealityTransportFixture:
    def __init__(self) -> None:
        self.transition: dict[str, Any] = {}
        self.rejected_scene = False

    def planning(self, stage, inputs):
        from novel_forge.modules.story_planning_runtime.execution import (
            planning_fixture_response,
        )

        if stage == "world_candidates.generate":
            return {"disposition": "NO_OP", "reason": "This retained manual-direction fixture supplies no autonomous world advancement.", "candidates": []}
        if stage == "world_candidates.evaluate":
            return {"evaluations": []}
        result = planning_fixture_response(stage, inputs)
        if stage == "chapter_plan.generate" and not self.rejected_scene:
            result["character_participation"][0]["known_fact_ids"] = [
                "fact:unearned-secret"
            ]
            result["scene_plan"][0]["accessible_knowledge"] = ["fact:unearned-secret"]
            self.rejected_scene = True
        return result

    def __call__(self, stage, inputs):
        result = default_chapter_fixture_response(stage, inputs)
        source = (
            inputs.get(
                {
                    "draft": "plan",
                    "revision": "draft",
                    "canon_extraction": "revision",
                }.get(stage, "")
            )
            or {}
        )
        if not self.transition or int(source.get("chapter") or 0) != 2:
            return scripted_claim_evidence(stage, inputs, result)
        prose = "The council orders a public inquiry."
        if stage in {"draft", "revision"}:
            result["text"] += " " + prose
            result["scene_artifacts"][-1]["text"] += " " + prose
        if stage == "canon_extraction":
            start = source["text"].index(prose)
            result["world_state_changes"] = [
                {
                    "world_state_id": "council-inquiry",
                    "status": "OPEN",
                    "summary": prose,
                    "confidence": 1.0,
                    "evidence_start": start,
                    "evidence_end": start + len(prose),
                    "world_transition": {"payload_json": json.dumps(self.transition)},
                }
            ]
        return scripted_claim_evidence(stage, inputs, result)


def admit_native_production(*, composition, snapshot, generic):
    principal = composition.principal
    project_id, book_id = snapshot.project_id, snapshot.book_id
    admitted = composition.authority.start(
        StartBookProductionCommand(
            project_id=project_id,
            workspace_id=snapshot.workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            trace_id=f"trace:{project_id}:native-production",
            correlation_id=f"correlation:{project_id}",
            stable_idempotency_key=f"{project_id}:native-production",
            book_design_version=snapshot.book_design_version,
            book_plan_version=snapshot.book_plan_version,
            production_profile_version=generic["production_profile"],
            longform_context_versions={
                "volume_plan_version": snapshot.current_volume_plan_version,
                "arc_plan_versions": list(snapshot.current_relevant_arc_plan_versions),
                **{
                    key: getattr(snapshot, key)
                    for key in (
                        "character_state_version",
                        "foreshadowing_state_version",
                        "quality_trend_version",
                        "reward_ledger_version",
                        "promise_ledger_version",
                        "reader_segment_version",
                        "reader_contract_version",
                        "platform_profile_version",
                    )
                },
            },
            target_chapter_count=3,
            input_mode="RESOLVED_AUTHORITY_INPUT",
            input_snapshot_id=snapshot.snapshot_id,
        ),
        principal=principal,
    )
    return admitted


def execute_native_reality_vertical(
    *, composition, chapter_application, snapshot, generic, transport
):
    admitted = admit_native_production(composition=composition, snapshot=snapshot, generic=generic)
    principal = composition.principal
    project_id = snapshot.project_id
    database_url = composition.authority.database_url
    worker = Principal(
        principal_id="native-reality-fixture-worker",
        principal_type=PrincipalType.WORKER,
        permissions=principal.permissions - {"book.authority.approve_replan"},
        project_scope=principal.project_scope,
        authentication_source="postgres-native-reality-worker-fixture",
    )
    jobs = RuntimeJobAuthority(database_url)
    previous = None
    causal = None
    for _ in range(80):
        schedule_book_coordination_jobs(
            composition.query, jobs, limit=1, book_run_id=admitted.book_run_id
        )
        claim = jobs.claim(
            runtime_group="book",
            worker_id="native-reality-fixture-worker",
            lease_seconds=30,
            job_kinds=("BOOK_COORDINATION_TICK",),
            subject_kind="BOOK_RUN",
            subject_id=admitted.book_run_id,
        )
        assert claim is not None
        result = execute_book_coordination_claim(jobs, composition, claim)
        if result["action"] == "DISPATCH_CHAPTER":
            scheduler = chapter_application.scheduler(principal=worker)
            for _ in range(len(ChapterNode) * 2 + 4):
                tick = scheduler.tick(
                    project_id=project_id, root_operation_id=result["operation_id"]
                )
                if tick.saga_status == "SUCCEEDED":
                    break
            else:
                raise AssertionError(
                    "Native Chapter did not complete its bounded graph"
                )
        frontier = int(
            composition.authority.require(admitted.book_run_id)[
                "accepted_through_chapter"
            ]
        )
        if frontier == 1 and previous is None:
            previous = composition.query.narrative_reality(
                book_run_id=admitted.book_run_id
            )
            source = previous["current_state"]["canon_fact"][0]
            transport.transition = {
                "transition_id": "native-off-camera-inquiry",
                "actor_id": "faction:council",
                "camera": "OFF_CAMERA",
                "story_time": {
                    "timeline_id": "main",
                    "start_ordinal": previous["world_clock"].get("main", 0) + 1,
                    "end_ordinal": previous["world_clock"].get("main", 0) + 1,
                    "precision": "EXACT",
                },
                "action": "respond to the accepted discovery",
                "state_kind": "world_state",
                "entity_key": "world_state_id=council-inquiry",
                "changes": {"status": "OPEN"},
                "cause_refs": [source["source_event_id"]],
                "requirements": [
                    {
                        "requirement_id": "accepted-discovery",
                        "state_kind": "canon_fact",
                        "entity_key": source["entity_key"],
                        "field": "object",
                        "operator": "EXISTS",
                    }
                ],
            }
            with AuthorityUnitOfWork(database_url) as uow:
                uow.cursor.execute(
                    "SELECT s.asset_version_id FROM authority_story_design_version_state s JOIN authority_story_design_active_version a ON a.asset_version_id=s.asset_version_id AND a.project_id=s.project_id WHERE s.project_id=%s AND s.generator_operation_name='creative.candidates.generate'",
                    [project_id],
                )
                intent_version = str(uow.cursor.fetchone()[0])
            from copy import deepcopy

            impossible = deepcopy(transport.transition)
            impossible["changes"]["status"] = "SEALED"
            blocked = composition.causal_planning.propose(
                principal=principal,
                project_id=project_id,
                book_run_id=admitted.book_run_id,
                reality_revision_id=previous["revision_id"],
                intent_version_id=intent_version,
                chapter_number=2,
                candidates=[
                    {
                        "transition": impossible,
                        "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 1.0),
                        "affected_entities": ["faction:council"],
                        "world_consequences": ["sealed inquiry"],
                        "rationale": "A maximal Director preference cannot bypass a compiled World law",
                    }
                ],
                idempotency_key=f"{project_id}:native-impossible",
                trace_id=f"trace:{project_id}:native-impossible",
                correlation_id=f"correlation:{project_id}",
            )
            assert not blocked["selected_candidate_id"]
            assert (
                blocked["candidate_futures"][0]["rejection"]["code"]
                == "WORLD_COMPILED_RULE_VIOLATION"
            )
            assert (
                blocked["world_design_constraints"][0]["rule"]["rule_id"]
                == "witnessed-inquiry-open"
            )
            assert (
                composition.query.narrative_reality(book_run_id=admitted.book_run_id)
                == previous
            )
            causal = composition.causal_planning.propose(
                principal=principal,
                project_id=project_id,
                book_run_id=admitted.book_run_id,
                reality_revision_id=previous["revision_id"],
                intent_version_id=intent_version,
                chapter_number=2,
                candidates=[
                    {
                        "transition": transport.transition,
                        "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 0.6),
                        "affected_entities": ["faction:council"],
                        "world_consequences": ["public inquiry begins"],
                        "rationale": "An accepted discovery provokes the council",
                    }
                ],
                idempotency_key=f"{project_id}:native-causal",
                trace_id=f"trace:{project_id}:native-causal",
                correlation_id=f"correlation:{project_id}",
            )
            assert causal["selected_candidate_id"]
        if frontier >= 2:
            current = composition.query.narrative_reality(
                book_run_id=admitted.book_run_id
            )
            assert (
                previous is not None
                and current["parent_revision_id"] == previous["revision_id"]
            )
            assert any(
                entry["state"].get("world_state_id") == "council-inquiry"
                and entry["state"]["status"] == "OPEN"
                for entry in current["current_state"]["world_state"]
            )
            assert (
                composition.query.narrative_reality(
                    book_run_id=admitted.book_run_id, chapter_number=1
                )
                == previous
            )
            from novel_forge.modules.context_builder.reality_projection import (
                ROLE_STATE_KINDS,
            )

            role_context_digests = {}
            for role in ROLE_STATE_KINDS:
                contract = composition.query.reality_context(
                    book_run_id=admitted.book_run_id,
                    role=role,
                    token_budget=32768,
                    character_ids=("mara",),
                )
                assert contract["reality_revision_id"] == current["revision_id"]
                role_context_digests[role] = contract["context_digest"]
                assert contract["estimated_tokens"] <= 32768
                assert contract["fact_mutation_allowed"] is False
                assert contract == composition.query.reality_context(
                    book_run_id=admitted.book_run_id,
                    role=role,
                    token_budget=32768,
                    character_ids=("mara",),
                )
            with AuthorityUnitOfWork(database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT content FROM authority_asset_version v JOIN authority_asset a ON a.asset_id=v.asset_id
                    WHERE a.project_id=%s AND a.asset_type='chapter_plan' AND v.content->>'chapter_number'='2'
                """,
                    [project_id],
                )
                plans = [dict(row[0]) for row in uow.cursor.fetchall()]
                assert any(
                    any(
                        ref["asset_version_id"] == previous["state_version_id"]
                        for ref in plan.get("frozen_inputs", [])
                    )
                    for plan in plans
                )
                uow.cursor.execute(
                    "SELECT report FROM authority_story_planning_validation_report WHERE project_id=%s AND report->>'error_code'='SCENE_ACCEPTED_KNOWLEDGE_MISMATCH'",
                    [project_id],
                )
                rejections = [dict(row[0]) for row in uow.cursor.fetchall()]
                assert len(rejections) == 1
                rejection = rejections[0]["directed_rejection"]
                assert rejection["target_generator"] == "chapter_plan.generate"
                assert (
                    rejection["repair_number"] == 0
                    and rejection["maximum_repairs"] >= 1
                )
                uow.cursor.execute(
                    "SELECT repair_number, input_snapshot FROM authority_story_planning_generation WHERE project_id=%s AND generator_operation_name='chapter_plan.generate' AND logical_key='chapter:1' ORDER BY repair_number",
                    [project_id],
                )
                repairs = uow.cursor.fetchall()
                assert [row[0] for row in repairs] == [0, 1]
                assert repairs[0][1] == repairs[1][1]
                assert {
                    item["role"]: item["asset_version_id"] for item in repairs[0][1]
                } == rejection["frozen_input_versions"]
                reader = composition.query.reality_view(
                    book_run_id=admitted.book_run_id, view="reader"
                )
                assert (
                    reader["reader_response_evidence"]["reality_mutation_allowed"]
                    is False
                )
                uow.cursor.execute(
                    "SELECT COUNT(*) FROM authority_book_opening_legacy_snapshot_entitlement WHERE snapshot_id=%s",
                    [snapshot.snapshot_id],
                )
                assert uow.cursor.fetchone()[0] == 0
            return {
                "book_run_id": admitted.book_run_id,
                "opening_snapshot_id": snapshot.snapshot_id,
                "accepted_reality_lineage": [
                    {
                        key: reality[key]
                        for key in (
                            "revision_id",
                            "parent_revision_id",
                            "chapter_number",
                            "acceptance_id",
                            "outcome_version_id",
                            "state_version_id",
                            "canon_version_id",
                            "source_digest",
                        )
                    }
                    for reality in (previous, current)
                ],
                "role_context_digests": role_context_digests,
                "world_foundation_sources": [
                    {
                        "asset_version_id": item["asset_version_id"],
                        "content_hash": item["content_hash"],
                    }
                    for item in causal["world_design_constraints"]
                ],
                "compiled_world_rejection": blocked["candidate_futures"][0][
                    "rejection"
                ]["code"],
                "directed_rejection": rejection,
                "reality_revision_id": current["revision_id"],
                "causal_operation_id": causal["operation_id"],
                "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            }
    raise AssertionError(
        "Native Opening did not reach Reality N+1 within its operation budget"
    )


def scripted_claim_evidence(stage, inputs, result):
    if stage != "canon_extraction":
        return result
    from novel_forge.modules.canon_graph.domain import PROVIDER_SEMANTIC_CHANGE_FIELDS
    text = inputs["revision"]["text"]
    for field in PROVIDER_SEMANTIC_CHANGE_FIELDS.values():
        for claim in result.get(field, []):
            claim["evidence_quote"] = text[int(claim["evidence_start"]):int(claim["evidence_end"])]
            claim["claim_kind"] = {"character_knowledge_changes": "KNOWLEDGE_ACQUISITION",
                                   "character_belief_changes": "BELIEF",
                                   "disclosure_events": "READER_DISCLOSURE"}.get(field, "OBJECTIVE_EVENT")
    return result
