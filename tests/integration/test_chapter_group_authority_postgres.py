from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

import psycopg

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
    build_reader_outcome_model_port,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.governed_scheduler import (
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.book_authority.production import (
    ChapterAuthorityCommandAdapter,
    PostgresBookAuthority,
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_group_authority import (
    PostgresChapterGroupAuthority,
    StartChapterGroupCommand,
)
from novel_forge.modules.chapter_group_authority.policy import (
    ChapterGroupExecutionPolicy,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.realization_application import (
    NarrativeRealizationCommand,
    PostgresNarrativeRealizationApplication,
)
from novel_forge.modules.hierarchical_planning.realization_domain import (
    NarrativeRealizationContract,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration import (
    test_postgresql_only_chapter_slice as chapter_fixture,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration import test_book_to_chapter_authority_vertical_postgres as book_chapter_support
from tests.integration.hierarchy_closure_postgres_support import (
    seed_ready_story_foundation,
)
from tests.unit.test_narrative_realization import _extended_contract


class ChapterGroupAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_nine_chapter_realization_freezes_and_replays_without_count_invariant(self) -> None:
        self._verify_realization_freeze_replay(observational=False)

    def test_observational_realization_preserves_zero_changes_across_lost_response(self) -> None:
        self._verify_realization_freeze_replay(observational=True)

    def _verify_realization_freeze_replay(self, *, observational: bool) -> None:
        fixture = self._fixture(group_chapters=9, chapter_fixture_factory=self._observational_response if observational else None)
        project_id, book_id = fixture["project_id"], fixture["book_id"]
        workspace_id = f"workspace:{project_id}"
        principal = replace(
            fixture["principal"],
            permissions=fixture["principal"].permissions
            | {"story_design.authority.execute"},
        )
        foundation = seed_ready_story_foundation(
            DATABASE_URL,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            principal=principal,
            target_chapters=9,
            release_sha="f" * 40,
        )
        group_authority = fixture["group_authority"]
        group_authority.execution_policies.configure(
            project_id=project_id,
            workspace_id=workspace_id,
            principal=principal,
            policy=ChapterGroupExecutionPolicy("nine-v1", 9, 9),
            idempotency_key=f"{project_id}:nine-window-policy",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        group = group_authority.start(
            StartChapterGroupCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=principal.principal_id,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                stable_idempotency_key=f"{project_id}:nine-window",
                book_run_id=fixture["book"].book_run_id,
                group_plan_version_id=fixture["group_plan"]["asset_version_id"],
                group_plan_content_hash=fixture["group_plan"]["content_hash"],
            ),
            principal=principal,
        )
        self.assertEqual(group["chapter_end"], 9)
        value = _extended_contract(9).to_dict()
        if observational:
            value["schema_version"] = "narrative-realization-contract.v2"
            value["proof"]["schema_version"] = "narrative-realization-proof.v2"
            value["proof"]["causal_alignment_proven"] = value["proof"].pop("causal_escalation_proven")
            value["proof"]["design_admission"] = {"mode": "STRICT_QUALIFIED", "literary_qualification": "NOT_PROVEN"}
            for event in value["events"]:
                event.update(motivation="Observe the winter street", action="Look at falling snow", consequence="The observation is rendered to the reader", decision=None, resistance=None, irreversible_change=None,
                             state_deltas=[], disclosures=[], obligation_actions=[],
                             arc_contributions=[], preconditions=[], causes=[], next_event_ids=[])
                event["knowledge_boundary"] = {"actor_knows": [], "reader_may_learn": [], "forbidden_disclosures": []}
                event["feature_status"] = {field: {"status": "NOT_APPLICABLE", "rationale": "Synthetic approved observational scope"}
                                           for field in ("decision", "resistance", "irreversible_change")}

        value.update(
            realization_id=f"realization:{project_id}",
            project_id=project_id,
            book_id=book_id,
            chapter_group_plan_version_id=fixture["group_plan"]["asset_version_id"],
            chapter_group_content_hash=fixture["group_plan"]["content_hash"],
            foundation_set_digest=foundation["foundation_set_digest"],
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT longform_context_versions->>'volume_plan_version' FROM authority_book_production WHERE book_run_id=%s",
                [fixture["book"].book_run_id],
            )
            volume_id = uow.cursor.fetchone()[0]
        arc = self._seed_asset(
            project_id,
            "planning_generation_candidate",
            "arc",
            {"cross_volume_scope": [volume_id]},
        )
        state = self._seed_asset(project_id, "narrative_state", "boundary-state", {})
        canon = self._seed_asset(project_id, "canon_snapshot", "boundary-canon", {})
        content = self._seed_asset(
            project_id,
            "narrative_realization",
            "realization-content",
            {"events": value["events"]},
        )
        proof = self._seed_asset(
            project_id,
            "narrative_design_evaluation",
            "realization-proof",
            value["proof"],
        )
        value.update(
            content_asset_version_id=content["asset_version_id"],
            content_hash=content["content_hash"],
            proof_asset_version_id=proof["asset_version_id"],
            proof_hash=proof["content_hash"],
        )
        value["proof"].update(
            semantic_evaluation_asset_version_id=proof["asset_version_id"],
            semantic_evaluation_hash=proof["content_hash"],
        )
        value["arc_plan_bindings"] = [
            {
                "arc_id": "arc-main",
                "asset_version_id": arc["asset_version_id"],
                "content_hash": arc["content_hash"],
            }
        ]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type, logical_key,
                    asset_version_id, execution_scope, freshness, created_by_operation_id
                ) VALUES (%s,%s,%s,'ARC','arc:main',%s,'FROZEN','CURRENT',%s)""",
                [
                    f"arc-binding:{project_id}",
                    project_id,
                    book_id,
                    arc["asset_version_id"],
                    fixture["book"].root_operation_id,
                ],
            )
            uow.cursor.execute(
                """INSERT INTO active_story_plan_version(
                    project_id, book_id, logical_key, binding_id,
                    asset_version_id, activated_by_operation_id
                ) VALUES (%s,%s,'arc:main',%s,%s,%s)""",
                [
                    project_id,
                    book_id,
                    f"arc-binding:{project_id}",
                    arc["asset_version_id"],
                    fixture["book"].root_operation_id,
                ],
            )
            uow.cursor.execute(
                """INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type, logical_key,
                    asset_version_id, execution_scope, freshness, created_by_operation_id
                ) SELECT %s,project_id,book_id,'BOOK','book:main',book_plan_version,
                    'FROZEN','CURRENT',root_operation_id
                  FROM authority_book_production WHERE book_run_id=%s""",
                [f"book-binding:{project_id}", fixture["book"].book_run_id],
            )
            uow.cursor.execute(
                """INSERT INTO authority_book_production_input_snapshot(
                    snapshot_id,project_id,workspace_id,book_id,expected_book_version,
                    book_record_version,book_design_version,book_plan_version,
                    current_volume_plan_version,volume_portfolio_plan_versions,
                    active_arc_plan_versions,arc_portfolio_plan_versions,
                    current_relevant_arc_plan_versions,current_chapter_group_plan_version,
                    production_profile_version,reader_segment_version,
                    reader_contract_version,platform_profile_version,
                    character_state_version,foreshadowing_state_version,
                    quality_trend_version,reward_ledger_version,promise_ledger_version,
                    capability_pack_deployment_refs,release_sha,snapshot_hash,
                    resolved_by_operation_id,initial_story_state_version,
                    initial_canon_snapshot_version,foundation_set_digest
                ) SELECT %s,project_id,workspace_id,book_id,1,book_design_version,
                    book_design_version,book_plan_version,
                    longform_context_versions->>'volume_plan_version',
                    jsonb_build_array(longform_context_versions->>'volume_plan_version'),
                    jsonb_build_array(%s::text),jsonb_build_array(%s::text),
                    jsonb_build_array(%s::text),%s,
                    longform_context_versions->>'platform_profile_version',
                    longform_context_versions->>'reader_segment_version',
                    longform_context_versions->>'reader_contract_version',
                    longform_context_versions->>'platform_profile_version',
                    longform_context_versions->>'character_state_version',
                    longform_context_versions->>'foreshadowing_state_version',
                    longform_context_versions->>'quality_trend_version',
                    longform_context_versions->>'reward_ledger_version',
                    longform_context_versions->>'promise_ledger_version',
                    '[]'::jsonb,%s,%s,root_operation_id,%s,%s,%s
                  FROM authority_book_production WHERE book_run_id=%s""",
                [
                    f"snapshot:{project_id}",
                    *([arc["asset_version_id"]] * 3),
                    fixture["group_plan"]["asset_version_id"],
                    "f" * 40,
                    "sha256:" + hashlib.sha256(project_id.encode()).hexdigest(),
                    state["asset_version_id"],
                    canon["asset_version_id"],
                    foundation["foundation_set_digest"],
                    fixture["book"].book_run_id,
                ],
            )
            uow.cursor.execute(
                "UPDATE authority_book_production SET input_snapshot_id=%s WHERE book_run_id=%s",
                [f"snapshot:{project_id}", fixture["book"].book_run_id],
            )
            uow.cursor.execute(
                """SELECT state.asset_version_id, state.content_hash,
                          canon.asset_version_id, canon.content_hash
                   FROM authority_book_production AS production
                   JOIN authority_book_production_input_snapshot AS snapshot
                     ON snapshot.snapshot_id=production.input_snapshot_id
                   JOIN authority_asset_version AS state
                     ON state.asset_version_id=snapshot.initial_story_state_version
                   JOIN authority_asset_version AS canon
                     ON canon.asset_version_id=snapshot.initial_canon_snapshot_version
                   WHERE production.book_run_id=%s""",
                [fixture["book"].book_run_id],
            )
            state_id, state_hash, canon_id, canon_hash = uow.cursor.fetchone()
            uow.commit()
        value["accepted_boundary"].update(
            story_state_version_id=state_id,
            story_state_content_hash=state_hash,
            canon_version_id=canon_id,
            canon_content_hash=canon_hash,
        )
        authority = PostgresNarrativeRealizationApplication(
            DATABASE_URL,
            application_build_id="realization-policy-test",
            commit_sha="f" * 40,
        )
        common = dict(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            realization_id=value["realization_id"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            reason="fixture verifies configurable execution range contract",
        )
        qualified = authority.execute(
            NarrativeRealizationCommand(
                **common,
                definition_name="planning.realization.qualify",
                expected_version=0,
                idempotency_key=f"{project_id}:qualify-nine",
                contract=NarrativeRealizationContract.from_mapping(value),
            ),
            principal=principal,
        )
        approved = authority.execute(
            NarrativeRealizationCommand(
                **common,
                definition_name="planning.realization.approve",
                expected_version=qualified["version"],
                idempotency_key=f"{project_id}:approve-nine",
            ),
            principal=principal,
        )
        command = NarrativeRealizationCommand(
            **common,
            definition_name="planning.realization.freeze",
            expected_version=approved["version"],
            idempotency_key=f"{project_id}:freeze-nine",
        )

        def lose_response(name: str) -> None:
            if name == "after_operation_completion_before_response":
                raise RuntimeError("freeze committed response lost")

        authority.fault_injector = lose_response
        with self.assertRaisesRegex(RuntimeError, "freeze committed"):
            authority.execute(command, principal=principal)
        recovered = PostgresNarrativeRealizationApplication(
            DATABASE_URL,
            application_build_id="realization-policy-test",
            commit_sha="f" * 40,
        ).execute(command, principal=principal)
        self.assertTrue(recovered["replayed"])
        self.assertEqual(recovered["lifecycle"], "FROZEN")
        self.assertEqual((recovered["chapter_start"], recovered["chapter_end"]), (1, 9))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_narrative_realization_event WHERE realization_id=%s",
                [value["realization_id"]],
            )
            self.assertEqual(uow.cursor.fetchone()[0], 9)
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_narrative_realization_consumption WHERE realization_id=%s",
                [value["realization_id"]],
            )
            self.assertEqual(uow.cursor.fetchone()[0], 0)
            if observational:
                uow.cursor.execute("SELECT planned_event FROM authority_narrative_realization_event WHERE realization_id=%s", [value["realization_id"]])
                for (event,) in uow.cursor.fetchall():
                    self.assertIsNone(event["decision"])
                    self.assertEqual(event["state_deltas"], [])
                    self.assertEqual(event["disclosures"], [])
                    self.assertEqual(event["obligation_actions"], [])
        if observational:
            self._verify_zero_chapter_acceptance(fixture, value, recovered["contract_digest"])

    @staticmethod
    def _observational_response(stage, inputs):
        from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
        from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
        output = default_chapter_fixture_response(stage, inputs)
        if stage == "draft":
            text = "Snow falls quietly on the winter street. The observer watches the lamps and the windows without making a decision. Nobody learns a new fact. The street remains as it was before the observation."
            for scene in output["scene_artifacts"]:
                scene["text"] = text
            output["text"] = serialize_realization(output["scene_artifacts"]) if output["scene_artifacts"] else text
        elif stage == "review":
            output.update(score=90, issues=[])
        elif stage == "revision":
            draft = inputs["draft"]
            output = {"text": draft["text"], "scene_artifacts": draft["scene_artifacts"], "resolved_issue_codes": []}
        elif stage == "canon_extraction":
            for key, value in output.items():
                if isinstance(value, list) and key != "realization_evidence":
                    output[key] = []
            output.update(extraction_status="EXTRACTED" if output["realization_evidence"] else "NO_CHANGE", no_change_reason="" if output["realization_evidence"] else "No business changes or observations.")
        return output

    def _verify_zero_chapter_acceptance(self, fixture, value, contract_digest):
        from novel_forge.storage.narrative_realization_repositories import NarrativeRealizationRepository
        from novel_forge.modules.hierarchical_planning.chapter_contracts import require_chapter_contracts
        for number in (1, 2):
            event = next(item for item in value["events"] if item["chapter_number"] == number)
            plan = dict(fixture["chapter_plans"][number]["content"])
            plan.update(chapter_contract_schema_version="chapter-mission-scene.v3", primary_function="observation",
                        chapter_objective="Render an observation of the winter street", chapter_intent="Render an observation",
                        required_state_delta={"status": "NO_INCREMENT", "summary": None},
                        arc_schedule=[], required_arc_contributions=[], required_state_transitions=[],
                        obligation_actions=[], character_participation=[], knowledge_boundaries=[], disclosures=[],
                        reward_action=None, promise_action=None, ending_hook=None, serialization_function=None,
                        antagonist_actions=[], canon_expected_changes=[], reader_promise_actions=[], reward_setup=[], reward_payoff=[],
                        antagonist_pressure=None, chapter_hook=None, next_chapter_bridge=None,
                        narrative_realization_slice={"accepted_through_chapter": 0, "chapter_number": number, "contract_digest": contract_digest, "realization_id": value["realization_id"], "slice_id": event["slice_id"], "events": [event]},
                        scene_plan=[{"scene_id": f"observation:{number}", "goal": "Render the winter street",
                                     "conflict": "", "participants": [], "arc_progress": [], "trajectory_refs": [],
                                     "obligation_refs": [], "state_transitions": [], "realization_event_ids": [event["event_id"]],
                                     "information_gain": [], "entry_state": "winter street", "exit_state": "winter street",
                                     "reader_effect": "contemplation", "beats": [{"beat_id": f"look:{number}", "ordinal": 1, "function": "observation"}]}])
            require_chapter_contracts(plan)
            frozen = self._seed_asset(fixture["project_id"], "chapter_plan", f"observation-plan-{number}", plan)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                binding = f"observation-binding:{fixture['project_id']}:{number}"
                uow.cursor.execute("INSERT INTO story_plan_binding(binding_id,project_id,book_id,contract_type,logical_key,asset_version_id,parent_version_id,execution_scope,freshness,created_by_operation_id) VALUES (%s,%s,%s,'CHAPTER',%s,%s,%s,'FROZEN','CURRENT',%s)", [binding, fixture["project_id"], fixture["book_id"], f"chapter:{number}", frozen["asset_version_id"], fixture["group_plan"]["asset_version_id"], fixture["book"].root_operation_id])
                uow.cursor.execute("UPDATE active_story_plan_version SET binding_id=%s,asset_version_id=%s WHERE project_id=%s AND book_id=%s AND logical_key=%s", [binding,frozen["asset_version_id"],fixture["project_id"],fixture["book_id"],f"chapter:{number}"])
                uow.commit()
            candidates = tuple(item for item in fixture["candidates"] if item["asset_type"] != "chapter_plan") + (frozen,)
            command = SubmitBookChapterCommand(book_run_id=fixture["book"].book_run_id, chapter_number=number,
                title=f"Observation {number}", premise="A winter street is observed without business state changes.",
                chapter_plan_asset_version_id=frozen["asset_version_id"], chapter_plan_content_hash=frozen["content_hash"],
                context_candidates=candidates, context_token_budget=64_000,
                narrative_realization_id=value["realization_id"], narrative_realization_slice_id=event["slice_id"],
                narrative_realization_contract_digest=contract_digest)
            delegated = fixture["book_authority"].submit_chapter(command, principal=fixture["principal"])
            for _ in range(len(ChapterNode) * 2 + 4):
                tick = fixture["chapter"].scheduler(principal=fixture["worker"]).tick(project_id=fixture["project_id"], root_operation_id=delegated["chapter_root_operation_id"])
                if tick.saga_status == "SUCCEEDED":
                    break
            status = fixture["book_authority"].reconcile_chapter(delegated["chapter_request_id"])
            self.assertEqual(status["status_reference"], "SUCCEEDED", status)
            accepted = fixture["book_authority"].accept_chapter(delegated["chapter_request_id"], principal=fixture["principal"])
            self.assertEqual(accepted["accepted_through_chapter"], number)
            self.assertEqual(fixture["book_authority"].accept_chapter(delegated["chapter_request_id"], principal=fixture["principal"])["accepted_through_chapter"], number)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                current = NarrativeRealizationRepository(uow.cursor).require(value["realization_id"])
                self.assertEqual(current["lifecycle"], "FROZEN")
                uow.cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [accepted["last_chapter_outcome_version_id"]])
                outcome = uow.cursor.fetchone()[0]
                self.assertEqual(outcome["state_events"], [])
                self.assertEqual(outcome["obligation_events"], [])
                self.assertEqual(outcome["realization_evidence"][0]["observed_disclosures"], [])
                self.assertEqual(outcome["realization_evidence"][0]["observed_state_deltas"], [])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT count(*) FROM authority_narrative_realization_consumption WHERE realization_id=%s", [value["realization_id"]])
            self.assertEqual(uow.cursor.fetchone()[0], 2)
            uow.cursor.execute("SELECT chapter_outcome_asset_version_id,chapter_outcome FROM authority_narrative_state_rebuild_source WHERE book_run_id=%s ORDER BY accepted_chapter", [fixture["book"].book_run_id])
            from novel_forge.modules.narrative_state.reducers import rebuild_story_state
            sources = uow.cursor.fetchall()
            self.assertEqual(len(sources), 2)
            rebuilt = rebuild_story_state(sources)
            self.assertEqual(rebuilt["accepted_through_chapter"], 2)
            self.assertTrue(all(not entries for entries in rebuilt["current_state"].values()))
            uow.cursor.execute("SELECT count(*) FROM authority_narrative_state_event_projection WHERE book_run_id=%s", [fixture["book"].book_run_id])
            self.assertEqual(uow.cursor.fetchone()[0], 0)

    def test_one_chapter_execution_window_freezes_policy_across_restart_and_replay(
        self,
    ) -> None:
        fixture = self._fixture(group_chapters=1)
        authority = fixture["group_authority"]
        principal = fixture["principal"]
        config = {
            "project_id": fixture["project_id"],
            "workspace_id": f"workspace:{fixture['project_id']}",
            "principal": principal,
            "trace_id": identifier("trace"),
            "correlation_id": identifier("correlation"),
        }
        authority.execution_policies.configure(
            **config,
            idempotency_key="window:v1",
            policy=ChapterGroupExecutionPolicy("one-v1", 1, 1),
        )
        command = StartChapterGroupCommand(
            project_id=fixture["project_id"],
            workspace_id=config["workspace_id"],
            actor_id=principal.principal_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            stable_idempotency_key="one-window",
            book_run_id=fixture["book"].book_run_id,
            group_plan_version_id=fixture["group_plan"]["asset_version_id"],
            group_plan_content_hash=fixture["group_plan"]["content_hash"],
        )
        original = authority.start(command, principal=principal)
        self.assertEqual(original["chapter_end"] - original["chapter_start"] + 1, 1)
        authority.execution_policies.configure(
            **config,
            idempotency_key="window:v2",
            policy=ChapterGroupExecutionPolicy("twelve-v2", 12, 12),
        )
        recovered = PostgresChapterGroupAuthority(
            DATABASE_URL,
            book_authority=fixture["book_authority"],
            application_build_id="chapter-group-integration",
            commit_sha="f" * 40,
        ).start(command, principal=principal)
        self.assertEqual(recovered["group_run_id"], original["group_run_id"])
        self.assertEqual(
            recovered["execution_policy_snapshot"],
            original["execution_policy_snapshot"],
        )
        self.assertEqual(
            recovered["execution_policy_snapshot"]["policy"]["maximum_chapters"], 1
        )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "UPDATE authority_chapter_group_production SET execution_policy_snapshot=NULL WHERE group_run_id=%s",
                    [original["group_run_id"]],
                )
                uow.commit()

    def test_chapter_group_three_chapter_vertical_and_rolling_horizon(
        self,
    ) -> None:
        fixture = self._fixture()
        group_authority = fixture["group_authority"]
        principal = fixture["principal"]
        group = group_authority.start(
            StartChapterGroupCommand(
                project_id=fixture["project_id"],
                workspace_id=f"workspace:{fixture['project_id']}",
                actor_id=principal.principal_id,
                trace_id=identifier("group-trace"),
                correlation_id=fixture["book"].root_operation_id,
                stable_idempotency_key=(f"{fixture['project_id']}:group:1:v1"),
                book_run_id=fixture["book"].book_run_id,
                group_plan_version_id=fixture["group_plan"]["asset_version_id"],
                group_plan_content_hash=fixture["group_plan"]["content_hash"],
            ),
            principal=principal,
        )
        paused = group_authority.pause(
            group["group_run_id"],
            reason="operator checkpoint",
            principal=principal,
        )
        self.assertEqual(paused["state"], "PAUSED")
        with self.assertRaisesRegex(KernelError, "CHAPTER_GROUP_DISPATCH_NOT_READY"):
            group_authority.dispatch(
                group["group_run_id"],
                self._chapter_command(fixture, 1),
                principal=principal,
            )
        resumed = group_authority.resume(
            group["group_run_id"],
            reason="checkpoint cleared",
            principal=principal,
        )
        self.assertEqual(resumed["state"], "READY")

        scheduler = PostgresBookAuthorityScheduler(
            fixture["book_authority"],
            query=PostgresBookProductionQuery(DATABASE_URL),
            principal=principal,
        )
        for chapter_number in (1, 2, 3):
            running = group_authority.dispatch(
                group["group_run_id"],
                self._chapter_command(fixture, chapter_number),
                principal=principal,
            )
            self.assertEqual(running["state"], "CHAPTER_RUNNING")
            with self.assertRaisesRegex(
                KernelError, "CHAPTER_GROUP_DISPATCH_NOT_READY"
            ):
                group_authority.dispatch(
                    group["group_run_id"],
                    self._chapter_command(fixture, min(3, chapter_number + 1)),
                    principal=principal,
                )
            request = fixture["book_authority"].require_chapter_request(
                str(running["active_chapter_request_id"])
            )
            for _ in range(2):
                waiting = group_authority.reconcile_and_accept(
                    group["group_run_id"], principal=principal
                )
                self.assertEqual(int(waiting["accepted_through_chapter"]), chapter_number - 1)
            self._run_child(
                fixture,
                str(request["chapter_root_operation_id"]),
            )
            accepted = group_authority.reconcile_and_accept(
                group["group_run_id"], principal=principal
            )
            self.assertEqual(
                int(accepted["accepted_through_chapter"]),
                chapter_number,
            )
            scheduler.tick(fixture["book"].book_run_id)
            scheduler.tick(fixture["book"].book_run_id)
            if chapter_number == 3:
                scheduler.tick(fixture["book"].book_run_id)
                scheduler.tick(fixture["book"].book_run_id)

        closed = group_authority.close(group["group_run_id"], principal=principal)
        self.assertEqual(closed["state"], "COMPLETED")
        self.assertIsNone(closed["recap_operation_id"])
        self.assertIsNone(closed["plan_adjustment_proposal_version_id"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT chapter_request_id),
                       COUNT(DISTINCT child_root_operation_id)
                FROM authority_chapter_group_chapter
                WHERE group_run_id=%s AND status='ACCEPTED'
                """,
                [group["group_run_id"]],
            )
            accepted_counts = tuple(int(value) for value in uow.cursor.fetchone())
            uow.cursor.execute(
                """
                SELECT executed_through_chapter,
                       frozen_through_chapter,
                       planned_through_chapter,
                       speculative_through_chapter,
                       status
                FROM planning_horizon
                WHERE project_id=%s AND book_id=%s
                """,
                [fixture["project_id"], fixture["book_id"]],
            )
            horizon = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation
                WHERE root_operation_id=%s
                  AND definition_name LIKE %s
                """,
                [group["root_operation_id"], "chapter_group.%"],
            )
            step_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset
                  ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND asset.asset_type='chapter_outcome'
                  AND version.content->>'parent_group_version_id'=%s
                """,
                [
                    fixture["project_id"],
                    fixture["group_plan"]["asset_version_id"],
                ],
            )
            group_bound_outcomes = int(uow.cursor.fetchone()[0])
        self.assertEqual(accepted_counts, (3, 3, 3))
        self.assertEqual(tuple(horizon), (3, 3, 10, 23, "CURRENT"))
        self.assertGreaterEqual(step_count, 16)
        self.assertEqual(group_bound_outcomes, 3)

    def test_group_cancel_propagates_to_active_child(self) -> None:
        fixture = self._fixture()
        group = fixture["group_authority"].start(
            StartChapterGroupCommand(
                project_id=fixture["project_id"],
                workspace_id=f"workspace:{fixture['project_id']}",
                actor_id=fixture["principal"].principal_id,
                trace_id=identifier("group-cancel-trace"),
                correlation_id=fixture["book"].root_operation_id,
                stable_idempotency_key=(f"{fixture['project_id']}:group:cancel:v1"),
                book_run_id=fixture["book"].book_run_id,
                group_plan_version_id=fixture["group_plan"]["asset_version_id"],
                group_plan_content_hash=fixture["group_plan"]["content_hash"],
            ),
            principal=fixture["principal"],
        )
        fixture["group_authority"].dispatch(
            group["group_run_id"],
            self._chapter_command(fixture, 1),
            principal=fixture["principal"],
        )
        cancelled = fixture["group_authority"].cancel(
            group["group_run_id"],
            reason="operator cancelled group",
            principal=fixture["principal"],
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, delegation.status
                FROM authority_chapter_group_chapter AS child
                JOIN authority_operation AS operation
                  ON operation.operation_id=child.child_root_operation_id
                JOIN authority_child_delegation AS delegation
                  ON delegation.delegation_id=child.child_delegation_id
                WHERE child.group_run_id=%s
                """,
                [group["group_run_id"]],
            )
            child = uow.cursor.fetchone()
        self.assertEqual(cancelled["state"], "ABORTED")
        self.assertEqual(str(child[0]), "CANCELLATION_REQUESTED")
        self.assertEqual(str(child[1]), "CANCELLATION_REQUESTED")

    def test_generation_coordinators_ignore_elapsed_time_with_independent_children(self) -> None:
        from novel_forge.modules.command_kernel.deadline_runtime import probe_operation_execution
        from novel_forge.modules.command_kernel.generation_policy import generation_graph
        fixture = self._fixture()
        group = fixture["group_authority"].start(
            StartChapterGroupCommand(
                project_id=fixture["project_id"], workspace_id=f"workspace:{fixture['project_id']}",
                actor_id=fixture["principal"].principal_id, trace_id=identifier("long-generation"),
                correlation_id=fixture["book"].root_operation_id,
                stable_idempotency_key=f"{fixture['project_id']}:group:long-generation",
                book_run_id=fixture["book"].book_run_id,
                group_plan_version_id=fixture["group_plan"]["asset_version_id"],
                group_plan_content_hash=fixture["group_plan"]["content_hash"],
            ), principal=fixture["principal"],
        )
        roots = [fixture["book"].root_operation_id, group["root_operation_id"]]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("UPDATE authority_operation SET business_deadline_at='2000-01-01' WHERE operation_id=ANY(%s)", [roots])
            for root in roots:
                self.assertTrue(generation_graph(uow.cursor, root, fixture["project_id"]))
            uow.commit()
        for root in roots:
            observed = probe_operation_execution(DATABASE_URL, operation_id=root, project_id=fixture["project_id"])
            self.assertEqual(observed["business_deadline_at"].year, 2000)
        fixture["group_authority"].dispatch(group["group_run_id"], self._chapter_command(fixture, 1), principal=fixture["principal"])
        for root in roots:
            observed = probe_operation_execution(DATABASE_URL, operation_id=root, project_id=fixture["project_id"])
            self.assertEqual(observed["business_deadline_at"].year, 2000)
        from novel_forge.modules.command_kernel.deadline_runtime import scan_expired_operation_deadlines
        report = scan_expired_operation_deadlines(DATABASE_URL, actor_id="native-coordinator-clock", limit=1000)
        self.assertFalse(set(roots) & set(report["cancellation_issued"]))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT child_root_operation_id FROM authority_chapter_group_chapter WHERE group_run_id=%s", [group["group_run_id"]])
            child = uow.cursor.fetchone()[0]
            for root in roots:
                self.assertTrue(generation_graph(uow.cursor, root, fixture["project_id"]))
            uow.cursor.execute("SELECT root_operation_id FROM authority_operation WHERE operation_id=%s", [child])
            self.assertEqual(uow.cursor.fetchone()[0], child)
            uow.cursor.execute("UPDATE authority_operation SET definition_snapshot=jsonb_set(definition_snapshot,'{irreversible_effect_policy,allowed}','true') WHERE operation_id=%s", [child])
            for root in roots:
                self.assertFalse(generation_graph(uow.cursor, root, fixture["project_id"]))
            uow.cursor.execute("UPDATE authority_operation SET definition_snapshot=jsonb_set(definition_snapshot,'{irreversible_effect_policy,allowed}','false') WHERE operation_id=%s", [child])
            uow.cursor.execute("SAVEPOINT mismatched_delegation")
            uow.cursor.execute("UPDATE authority_child_delegation SET chapter_number=chapter_number+1 WHERE child_root_operation_id=%s", [child])
            with self.assertRaisesRegex(KernelError, "GENERATION_COORDINATOR_REFERENCE_INVALID"):
                generation_graph(uow.cursor, group["root_operation_id"], fixture["project_id"])
            uow.cursor.execute("ROLLBACK TO SAVEPOINT mismatched_delegation")

    def _fixture(self, *, group_chapters: int = 3, chapter_fixture_factory=None) -> dict:
        project_id = identifier("chapter-group")
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        settings = IndustrialSettings(
            root=Path(root.name),
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_COMMIT_SHA": "f" * 40,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(Path(root.name) / "objects"),
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "group-chapter-worker",
        }
        execution = build_production_execution_composition(settings, env=env, chapter_fixture_factory=chapter_fixture_factory)
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        followup = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="chapter-group-integration",
            commit_sha="f" * 40,
            model_port=build_reader_outcome_model_port(
                settings, execution=execution, env=env
            ),
            worker_id="group-followup-worker",
        )
        book_authority = PostgresBookAuthority(
            DATABASE_URL,
            chapter_port=ChapterAuthorityCommandAdapter(
                chapter,
                external_effect_adapters=execution.external_effect_adapters,
            ),
            followup_application=followup,
            application_build_id="chapter-group-integration",
            commit_sha="f" * 40,
            legacy_fixture_input_allowed=True,
        )
        principal = Principal(
            principal_id="chapter-group-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "book.authority.execute",
                    "book.followup:*",
                    "chapter.authority.execute",
                }
            ),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )
        worker = Principal(
            principal_id="chapter-group-worker",
            principal_type=PrincipalType.WORKER,
            permissions=frozenset(
                {"chapter.authority.execute", "external_effect.execute"}
            ),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )
        candidates = list(
            chapter_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(project_id, current_state_contract=True)
        )
        versions = book_chapter_support.BookToChapterAuthorityVerticalPostgresTests._seed_book_inputs(
            project_id
        )
        book_id = f"book:{project_id}"
        book = book_authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                book_id=book_id,
                actor_id=principal.principal_id,
                trace_id=identifier("book-trace"),
                correlation_id=identifier("book-correlation"),
                stable_idempotency_key=f"{project_id}:book:v1",
                book_design_version=versions.pop("book_design_version"),
                book_plan_version=versions.pop("book_plan_version"),
                production_profile_version="production-profile:v1",
                longform_context_versions=versions,
                target_chapter_count=group_chapters,
                input_mode="LEGACY_FIXTURE_INPUT_MODE",
                light_recap_cadence=3,
                formal_recap_cadence=10,
            ),
            principal=principal,
        )
        planning = self._seed_planning(
            project_id=project_id,
            book_id=book_id,
            operation_id=book.root_operation_id,
            volume_plan_version=versions["volume_plan_version"],
            candidates=candidates,
            group_chapters=group_chapters,
        )
        return {
            "project_id": project_id,
            "book_id": book_id,
            "chapter": chapter,
            "book_authority": book_authority,
            "group_authority": PostgresChapterGroupAuthority(
                DATABASE_URL,
                book_authority=book_authority,
                application_build_id="chapter-group-integration",
                commit_sha="f" * 40,
            ),
            "principal": principal,
            "worker": worker,
            "candidates": candidates,
            "chapter_plans": planning["chapter_plans"],
            "group_plan": planning["group_plan"],
            "book": book,
        }

    def _chapter_command(
        self, fixture: dict, chapter_number: int
    ) -> SubmitBookChapterCommand:
        plan = fixture["chapter_plans"][chapter_number]
        candidates = tuple(
            item
            for item in fixture["candidates"]
            if item["asset_type"] != "chapter_plan"
        ) + (plan,)
        return SubmitBookChapterCommand(
            book_run_id=fixture["book"].book_run_id,
            chapter_number=chapter_number,
            title=f"Group Chapter {chapter_number}",
            premise="A decision creates an irreversible cost.",
            chapter_plan_asset_version_id=plan["asset_version_id"],
            chapter_plan_content_hash=plan["content_hash"],
            context_candidates=candidates,
            context_token_budget=196_608,
            parent_group_version_id=fixture["group_plan"]["asset_version_id"],
        )

    @staticmethod
    def _run_child(fixture: dict, root_operation_id: str) -> None:
        for _ in range(len(ChapterNode) + 3):
            tick = (
                fixture["chapter"]
                .scheduler(principal=fixture["worker"])
                .tick(
                    project_id=fixture["project_id"],
                    root_operation_id=root_operation_id,
                )
            )
            if tick.saga_status == "SUCCEEDED":
                return
        raise AssertionError("Chapter Saga did not reach SUCCEEDED")

    @staticmethod
    def _seed_planning(
        *,
        project_id: str,
        book_id: str,
        operation_id: str,
        volume_plan_version: str,
        candidates: list[dict],
        group_chapters: int = 3,
    ) -> dict:
        first = next(
            item for item in candidates if item["asset_type"] == "chapter_plan"
        )
        matrix = [
            {
                "chapter_number": chapter,
                "primary_function": function,
                "secondary_functions": ["continuity"],
                "required_state_delta": {"pressure": chapter},
                "required_arc_contributions": ["mainline"],
                "promise_action": "advance",
                "foreshadow_action": "plant",
                "reward_action": "partial",
                "ending_hook": hook,
                "prohibited_outcomes": ["premature closure"],
            }
            for chapter in range(1, group_chapters + 1)
            for function, hook in [
                (
                    ("DISCOVERY", "threat revealed"),
                    ("ESCALATION", "cost revealed"),
                    ("REVERSAL", "choice demanded"),
                )[(chapter - 1) % 3]
            ]
        ]
        group_content = {
            "type": "ChapterGroupPlan",
            "local_objective": "force a public commitment",
            "chapter_range": [1, group_chapters],
            "chapter_function_matrix": matrix,
        }
        group = ChapterGroupAuthorityPostgresTests._seed_asset(
            project_id,
            "chapter_group_plan",
            "group-plan",
            group_content,
        )
        chapter_plans: dict[int, dict] = {}
        for chapter in range(1, group_chapters + 1):
            content = {
                **dict(first["content"]),
                "chapter": chapter,
                "chapter_number": chapter,
                "title": f"Group Chapter {chapter}",
                "chapter_objective": matrix[chapter - 1]["required_state_delta"],
            }
            if content.get("narrative_realization_slice"):
                content["narrative_realization_slice"] = {
                    **content["narrative_realization_slice"], "chapter_number": chapter
                }
            chapter_plans[chapter] = ChapterGroupAuthorityPostgresTests._seed_asset(
                project_id,
                "chapter_plan",
                f"group-chapter-plan-{chapter}",
                content,
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            volume_binding = f"binding:{project_id}:volume"
            uow.cursor.execute(
                """
                INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type,
                    logical_key, asset_version_id, parent_version_id,
                    execution_scope, freshness, created_by_operation_id
                ) VALUES (
                    %s, %s, %s, 'VOLUME', 'volume:1', %s, %s,
                    'FROZEN', 'CURRENT', %s
                )
                """,
                [
                    volume_binding,
                    project_id,
                    book_id,
                    volume_plan_version,
                    volume_plan_version,
                    operation_id,
                ],
            )
            group_binding = f"binding:{project_id}:group"
            uow.cursor.execute(
                """
                INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type,
                    logical_key, asset_version_id, parent_version_id,
                    execution_scope, freshness, created_by_operation_id
                ) VALUES (
                    %s, %s, %s, 'CHAPTER_GROUP', 'group:1', %s, %s,
                    'FROZEN', 'CURRENT', %s
                )
                """,
                [
                    group_binding,
                    project_id,
                    book_id,
                    group["asset_version_id"],
                    volume_plan_version,
                    operation_id,
                ],
            )
            for chapter, plan in chapter_plans.items():
                binding_id = f"binding:{project_id}:chapter:{chapter}"
                uow.cursor.execute(
                    """
                    INSERT INTO story_plan_binding(
                        binding_id, project_id, book_id, contract_type,
                        logical_key, asset_version_id, parent_version_id,
                        execution_scope, freshness, created_by_operation_id
                    ) VALUES (
                        %s, %s, %s, 'CHAPTER', %s, %s, %s,
                        'FROZEN', 'CURRENT', %s
                    )
                    """,
                    [
                        binding_id,
                        project_id,
                        book_id,
                        f"chapter:{chapter}",
                        plan["asset_version_id"],
                        group["asset_version_id"],
                        operation_id,
                    ],
                )
                uow.cursor.execute(
                    """
                    INSERT INTO active_story_plan_version(
                        project_id, book_id, logical_key, binding_id,
                        asset_version_id, activated_by_operation_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        project_id,
                        book_id,
                        f"chapter:{chapter}",
                        binding_id,
                        plan["asset_version_id"],
                        operation_id,
                    ],
                )
            for logical_key, binding_id, version_id in (
                ("volume:1", volume_binding, volume_plan_version),
                (
                    "group:1",
                    group_binding,
                    group["asset_version_id"],
                ),
            ):
                uow.cursor.execute(
                    """
                    INSERT INTO active_story_plan_version(
                        project_id, book_id, logical_key, binding_id,
                        asset_version_id, activated_by_operation_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        project_id,
                        book_id,
                        logical_key,
                        binding_id,
                        version_id,
                        operation_id,
                    ],
                )
            uow.commit()
        return {"group_plan": group, "chapter_plans": chapter_plans}

    @staticmethod
    def _seed_asset(
        project_id: str,
        asset_type: str,
        label: str,
        content: dict,
    ) -> dict:
        asset_id = f"{project_id}:{label}:asset"
        version_id = f"{project_id}:{label}:v1"
        content_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [asset_id, project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (
                    %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1'
                )
                """,
                [version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'chapter-group-fixture-v1',
                          'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{version_id}:qualification", version_id],
            )
            uow.commit()
        return {
            "asset_type": asset_type,
            "asset_version_id": version_id,
            "content_hash": content_hash,
            "content": content,
            "project_id": project_id,
            "estimated_tokens": max(1, len(json.dumps(content)) // 4),
            "allowed_use": "generation",
            "source_use_mode": "generation",
            "safe_summary": f"Frozen {asset_type} fixture.",
            "structured_facts": [],
            "narrative_function": asset_type,
        }


if __name__ == "__main__":
    unittest.main()
