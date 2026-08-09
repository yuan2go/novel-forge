from __future__ import annotations

import unittest
import hashlib
import json

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decide_canon_approval,
    expire_deferred_canon_approvals,
    list_canon_approvals,
    reopen_canon_approval,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    admit_single_chapter_saga,
)
from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.content_authority.application import (
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.production_preparation import (
    PostgresProductionAssetResolver,
    ProductionPreparationRequest,
    ProductionPreparationService,
)
from novel_forge.modules.production_preparation.policies import (
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class ChapterAuthoritySchedulerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_admission_does_not_execute_and_ticks_rebuild_full_saga(self) -> None:
        project_id = identifier("async-chapter-project")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Durable Promise",
            premise="A promise creates a visible irreversible cost.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="async-chapter-test",
            commit_sha="f" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )

        self.assertEqual(admission.status, "ACCEPTED")
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        seen = []
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            seen.append(tick.node)
            self.assertEqual(tick.operation_status, "SUCCEEDED")
            if tick.node == ChapterNode.QUALITY_STRUCTURAL.value:
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT definition_name, status
                        FROM authority_operation
                        WHERE root_operation_id = %s
                          AND definition_name LIKE 'chapter.quality.%%.evaluate'
                          AND definition_name <> 'chapter.quality.evaluate'
                        ORDER BY definition_name
                        """,
                        [admission.root_operation_id],
                    )
                    fanout = cursor.fetchall()
                self.assertEqual(len(fanout), 5)
                self.assertEqual(
                    sum(status == "READY" for _, status in fanout),
                    4,
                )

        terminal = scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(seen, [node.value for node in ChapterNode])
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        self.assertEqual(terminal.recovery_mode, "terminal_replay")
        quality, publish_gate = self._quality_and_publish_gate(
            admission.root_operation_id
        )
        self.assertEqual(quality["gate"], "PASSED_WITH_UNCALIBRATED")
        self.assertEqual(publish_gate["gate"], "PASSED")
        self.assertEqual(publish_gate["release_readiness"], "INTERNAL_REVIEW_RELEASE")
        self.assertFalse(publish_gate["external_publish_permitted"])
        self.assertFalse(publish_gate["production_verified"])
        self.assertTrue(publish_gate["fixture_protocol_only"])

    def test_uncalibrated_fixture_is_a_successful_publish_block(self) -> None:
        project_id = identifier("uncalibrated-publish-block-project")
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="An Honest Fixture",
                premise="Fixture evidence cannot become production proof.",
                trace_id=identifier("uncalibrated-trace"),
                correlation_id=identifier("uncalibrated-correlation"),
                application_build_id="uncalibrated-fixture-test",
                commit_sha="f" * 40,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(
                    self._release_evidence(project_id, with_waiver=False)
                ),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="uncalibrated-fixture-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            if tick.node == ChapterNode.PUBLISH_GATE.value:
                break
        else:
            self.fail("uncalibrated fixture did not reach Publish Gate")

        quality, publish_gate = self._quality_and_publish_gate(
            admission.root_operation_id
        )
        self.assertEqual(quality["gate"], "PASSED_WITH_UNCALIBRATED")
        self.assertEqual(publish_gate["gate"], "PUBLISH_GATE_BLOCKED")
        self.assertEqual(publish_gate["release_readiness"], "BLOCKED")
        self.assertFalse(publish_gate["external_publish_permitted"])
        self.assertFalse(publish_gate["production_verified"])

    def test_preparation_command_runs_through_async_context_and_full_saga(self) -> None:
        project_id = identifier("prepared-async-project")
        self._preparation_assets(project_id)
        prepared = ProductionPreparationService(
            PostgresProductionAssetResolver(DATABASE_URL)
        ).prepare(
            ProductionPreparationRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                chapter=1,
                idempotency_key=f"{project_id}:chapter:1",
            )
        )
        self.assertEqual(prepared.report.decision, "READY")
        self.assertIsNotNone(prepared.command)
        command = prepared.command
        assert command is not None
        self.assertTrue(
            all(item["project_id"] == project_id for item in command.context_candidates)
        )
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                actor_id="trusted-operator",
                chapter=command.chapter,
                title=command.title,
                premise=command.premise,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                application_build_id="prepared-async-test",
                commit_sha="f" * 40,
                idempotency_key=command.idempotency_key,
                preparation_report=command.preparation_report,
                context_candidates=command.context_candidates,
                context_version_refs=command.context_version_refs,
                context_token_budget=command.context_token_budget,
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-prepared-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in ChapterNode:
            scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
        terminal = scheduler.tick(
            project_id=project_id, root_operation_id=admission.root_operation_id
        )
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id = operation.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE operation.root_operation_id = %s
                  AND operation.definition_name = 'chapter.plan.materialize'
                  AND binding.output_key = 'chapter.plan'
                """,
                [admission.root_operation_id],
            )
            authoritative_plan = cursor.fetchone()[0]
        self.assertEqual(
            authoritative_plan["source_chapter_plan_asset_version_id"],
            command.chapter_plan_asset_version_id,
        )
        self.assertEqual(
            authoritative_plan["source_chapter_plan_content_hash"],
            command.chapter_plan_content_hash,
        )

    def test_chapter_two_consumes_typed_empty_state_assets_as_logical_snapshots(
        self,
    ) -> None:
        project_id = identifier("prepared-typed-empty-project")
        self._preparation_assets(project_id, chapter=2, typed_empty=True)
        prepared = ProductionPreparationService(
            PostgresProductionAssetResolver(DATABASE_URL)
        ).prepare(
            ProductionPreparationRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                chapter=2,
                idempotency_key=f"{project_id}:chapter:2",
                context_token_budget=6_000,
            )
        )
        self.assertEqual(prepared.report.decision, "READY")
        command = prepared.command
        assert command is not None
        typed_candidates = [
            item
            for item in command.context_candidates
            if item.get("physical_asset_type") == "typed_empty_state_snapshot"
        ]
        self.assertEqual(
            len(typed_candidates), len(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES)
        )

        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                actor_id="chapter-scheduler-worker",
                chapter=command.chapter,
                chapter_plan_asset_version_id=command.chapter_plan_asset_version_id,
                chapter_plan_content_hash=command.chapter_plan_content_hash,
                title=command.title,
                premise=command.premise,
                trace_id=identifier("typed-empty-trace"),
                correlation_id=identifier("typed-empty-correlation"),
                application_build_id="typed-empty-async-test",
                commit_sha="f" * 40,
                context_candidates=command.context_candidates,
                context_version_refs=command.context_version_refs,
                context_token_budget=command.context_token_budget,
                preparation_report=command.preparation_report,
                idempotency_key=command.idempotency_key,
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="chapter-scheduler-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        terminal = None
        for _ in range(30):
            terminal = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            if terminal.saga_status == "SUCCEEDED":
                break
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation ON operation.operation_id = binding.operation_id
                JOIN authority_asset_version AS version ON version.asset_version_id = binding.asset_version_id
                WHERE operation.root_operation_id = %s
                  AND operation.definition_name = 'chapter.context.build'
                  AND binding.output_key = 'chapter.context'
                """,
                [admission.root_operation_id],
            )
            bundle = cursor.fetchone()[0]
        typed_segments = [
            item
            for item in bundle["context_segments"]
            if item.get("physical_asset_type") == "typed_empty_state_snapshot"
        ]
        self.assertEqual(
            len(typed_segments), len(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES)
        )
        self.assertTrue(
            all(
                item["structured_facts"][0]["declared_empty"] for item in typed_segments
            )
        )

    def test_high_impact_canon_waits_for_approved_decision_asset(self) -> None:
        class HighImpactFixture(DeterministicFixtureChapterProvider):
            supports_semantic_extraction = True

            def invoke(self, request, *, stage, payload):
                if stage != "canon_extraction":
                    return super().invoke(request, stage=stage, payload=payload)
                return ModelProviderResult(
                    output={
                        "character_state_changes": [
                            {
                                "character_id": "protagonist",
                                "status": "dead",
                                "impact_type": "character_death",
                                "confidence": 0.9,
                                "evidence_start": 0,
                                "evidence_end": 12,
                            }
                        ]
                    },
                    provider_id="deterministic_semantic_fixture",
                    model_id="fixture",
                    prompt_version="fixture-v1",
                    skill_version="fixture-v1",
                    input_tokens=0,
                    output_tokens=0,
                    cost_amount="0",
                    currency="USD",
                    real_model_call=False,
                )

        project_id = identifier("canon-gate-project")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(HighImpactFixture())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Canon Gate",
            premise="A costly choice changes an identity permanently.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="canon-gate-test",
            commit_sha="d" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        waiting = None
        for _ in range(12):
            tick = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if tick.saga_status == "WAITING_GATE":
                waiting = tick
                break
        self.assertIsNotNone(waiting)
        approvals = list_canon_approvals(DATABASE_URL, project_id=project_id)
        self.assertEqual(len(approvals), 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_operation WHERE root_operation_id = %s AND definition_name = %s",
                [admission.root_operation_id, ChapterNode.CANON.definition_name],
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        decision = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approvals[0]["approval_request_id"],
            expected_version=approvals[0]["version"],
            decision="APPROVE",
            reason="fixture proves per-change gate recovery",
            evidence={"fixture": True},
            edited_payload=None,
            idempotency_key="approve-once",
        )
        self.assertTrue(decision["gate_resumed"])
        self.assertTrue(decision["decision_operation_id"])
        replay = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approvals[0]["approval_request_id"],
            expected_version=approvals[0]["version"],
            decision="APPROVE",
            reason="fixture proves per-change gate recovery",
            evidence={"fixture": True},
            edited_payload=None,
            idempotency_key="approve-once",
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            replay["decision_operation_id"], decision["decision_operation_id"]
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, attempt.status, decision.decision_operation_id
                FROM authority_operation operation
                JOIN authority_attempt attempt ON attempt.operation_id = operation.operation_id
                JOIN authority_canon_approval_decision decision
                  ON decision.decision_operation_id = operation.operation_id
                WHERE operation.operation_id = %s
                """,
                [decision["decision_operation_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("SUCCEEDED", "SUCCEEDED", decision["decision_operation_id"]),
            )
        terminal = None
        for _ in range(30):
            terminal = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if terminal.saga_status == "SUCCEEDED":
                break
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT version.content FROM authority_operation_output_asset binding JOIN authority_asset_version version ON version.asset_version_id = binding.asset_version_id JOIN authority_asset asset ON asset.asset_id = version.asset_id WHERE binding.operation_id IN (SELECT operation_id FROM authority_operation WHERE root_operation_id = %s AND definition_name = %s) AND asset.asset_type = 'character_state_snapshot'",
                [admission.root_operation_id, ChapterNode.CANON.definition_name],
            )
            snapshot = cursor.fetchone()[0]
        self.assertEqual(snapshot["changes"][0]["status"], "dead")
        self.assertIn(
            decision["asset_version_id"],
            snapshot["canon_approval_decision_asset_version_ids"],
        )

    def test_deferred_canon_approval_reopens_without_bypassing_gate(self) -> None:
        project_id, request, admission, scheduler = self._high_impact_waiting_fixture(
            "canon-defer"
        )
        approval = list_canon_approvals(DATABASE_URL, project_id=project_id)[0]
        deferred = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"],
            decision="DEFER",
            reason="need a continuity packet",
            evidence={
                "defer_until": "2999-07-18T00:00:00+00:00",
                "required_information": "continuity packet",
                "assigned_operator": "chief-editor",
                "expiry_policy": "REOPEN",
            },
            edited_payload=None,
            idempotency_key="defer-once",
        )
        self.assertFalse(deferred["gate_resumed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "WAITING_GATE")
        reopened = reopen_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"] + 1,
            reason="continuity packet supplied",
            idempotency_key="reopen-once",
        )
        self.assertEqual(reopened["status"], "PENDING")
        replay = reopen_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"] + 1,
            reason="continuity packet supplied",
            idempotency_key="reopen-once",
        )
        self.assertTrue(replay["replayed"])
        with self.assertRaisesRegex(KernelError, "CANON_APPROVAL_VERSION_CONFLICT"):
            reopen_canon_approval(
                DATABASE_URL,
                CanonApprovalContext(
                    project_id,
                    "local-operator",
                    request.trace_id,
                    request.correlation_id,
                ),
                approval_request_id=approval["approval_request_id"],
                expected_version=approval["version"] + 1,
                reason="stale reopen",
                idempotency_key="reopen-stale",
            )
        deferred_again = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"] + 2,
            decision="DEFER",
            reason="wait for automatic expiry",
            evidence={
                "defer_until": "2999-07-19T00:00:00+00:00",
                "required_information": "expiry fixture",
                "assigned_operator": "chief-editor",
                "expiry_policy": "REOPEN",
            },
            edited_payload=None,
            idempotency_key="defer-for-expiry",
        )
        self.assertFalse(deferred_again["gate_resumed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_canon_approval_request SET defer_until=NOW() - INTERVAL '1 second' WHERE approval_request_id=%s",
                [approval["approval_request_id"]],
            )
        expired = expire_deferred_canon_approvals(
            DATABASE_URL,
            CanonApprovalContext(
                project_id,
                "system-scheduler",
                request.trace_id,
                request.correlation_id,
            ),
        )
        self.assertEqual(expired[0]["status"], "PENDING")

    def test_request_reextraction_supersedes_old_proposal_and_recovers_gate(
        self,
    ) -> None:
        project_id, request, admission, scheduler = self._high_impact_waiting_fixture(
            "canon-reextract"
        )
        old = list_canon_approvals(DATABASE_URL, project_id=project_id)[0]
        decision = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=old["approval_request_id"],
            expected_version=old["version"],
            decision="REQUEST_REEXTRACTION",
            reason="evidence needs a clean semantic pass",
            evidence={"fixture_protocol_only": True},
            edited_payload=None,
            idempotency_key="reextract-once",
        )
        self.assertTrue(decision["reextraction_requested"])
        self.assertFalse(decision["gate_resumed"])
        for _ in range(8):
            scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            approvals = list_canon_approvals(DATABASE_URL, project_id=project_id)
            pending = [item for item in approvals if item["status"] == "PENDING"]
            if pending and pending[0]["proposal_generation"] == 2:
                break
        else:
            self.fail("re-extraction did not produce a generation-2 approval")
        invalidated = [item for item in approvals if item["proposal_generation"] == 1]
        self.assertTrue(invalidated)
        self.assertTrue(all(item["status"] == "INVALIDATED" for item in invalidated))
        new_approval = pending[0]
        self.assertNotEqual(
            new_approval["proposal_asset_version_id"], old["proposal_asset_version_id"]
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT step_key FROM authority_saga_step WHERE saga_id=%s AND step_key LIKE 'canon_%%:g2' ORDER BY step_key",
                [admission.saga_id],
            )
            self.assertEqual(
                [row[0] for row in cursor.fetchall()],
                ["canon_extraction:g2", "canon_proposal:g2"],
            )
            cursor.execute(
                "SELECT policy_snapshot->>'policy_version', extraction_digest, proposal_digest, change_set_digest, no_progress_count FROM authority_canon_reextraction_generation WHERE project_id=%s AND root_operation_id=%s",
                [project_id, admission.root_operation_id],
            )
            governance = cursor.fetchone()
            self.assertEqual(governance[0], "canon-reextraction-policy-v1")
            self.assertTrue(
                all(str(value).startswith("sha256:") for value in governance[1:4])
            )
            self.assertEqual(governance[4], 1)
        approved = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=new_approval["approval_request_id"],
            expected_version=new_approval["version"],
            decision="APPROVE",
            reason="generation two evidence reviewed",
            evidence={"fixture_protocol_only": True},
            edited_payload=None,
            idempotency_key="approve-generation-two",
        )
        self.assertTrue(approved["gate_resumed"])
        for _ in range(30):
            terminal = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if terminal.saga_status == "SUCCEEDED":
                break
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_canon_reextraction_generation WHERE project_id=%s AND root_operation_id=%s",
                [project_id, admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "RESOLVED")

    def _high_impact_waiting_fixture(self, prefix: str):
        class HighImpactFixture(DeterministicFixtureChapterProvider):
            supports_semantic_extraction = True

            def invoke(self, request, *, stage, payload):
                if stage != "canon_extraction":
                    return super().invoke(request, stage=stage, payload=payload)
                return ModelProviderResult(
                    output={
                        "character_state_changes": [
                            {
                                "character_id": "protagonist",
                                "status": "dead",
                                "impact_type": "character_death",
                                "confidence": 0.9,
                                "evidence_start": 0,
                                "evidence_end": 12,
                            }
                        ]
                    },
                    provider_id="deterministic_semantic_fixture",
                    model_id="fixture",
                    prompt_version="fixture-v1",
                    skill_version="fixture-v1",
                    input_tokens=0,
                    output_tokens=0,
                    cost_amount="0",
                    currency="USD",
                    real_model_call=False,
                )

        project_id = identifier(f"{prefix}-project")
        registry = build_chapter_handler_registry(HighImpactFixture())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Canon Gate",
            premise="A costly choice changes an identity permanently.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id=f"{prefix}-test",
            commit_sha="e" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(self._release_evidence(project_id)),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in range(20):
            tick = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if tick.saga_status == "WAITING_GATE":
                return project_id, request, admission, scheduler
        self.fail("high-impact fixture did not reach Canon WAITING_GATE")

    @staticmethod
    def _preparation_assets(
        project_id: str, *, chapter: int = 1, typed_empty: bool = False
    ) -> None:
        absence_inputs: list[tuple[str, dict[str, str]]] = []

        def calibrated(dimensions: tuple[str, ...]) -> dict[str, object]:
            return {
                "safe_summary": "Fixture-only waived quality evidence.",
                "allowed_use": "evidence_only",
                "structured_facts": [
                    {
                        "key": "dimension_evidence",
                        "value": [
                            {
                                "dimension": item,
                                "gate_status": "WAIVED_BY_APPROVAL",
                                "calibration_status": "FIXTURE_UNCALIBRATED",
                                "human_verified": False,
                                "fixture_protocol_only": True,
                            }
                            for item in dimensions
                        ],
                    }
                ],
            }

        assets = {
            "chapter_plan": {
                "chapter": chapter,
                "title": "Prepared Chapter",
                "premise": "A prepared promise creates a visible cost.",
                "chapter_objective": "Force a public choice with a visible cost.",
                "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                "chapter_hook": "The cost creates a new obligation.",
                "conflict_chain": ["promise collides with institutional safety"],
                "emotional_curve": ["resolve", "fear", "costly resolve"],
                "suspense_curve": ["question", "pressure", "new obligation"],
                "reader_promise_actions": ["test and advance the promise"],
                "protagonist_charm_mechanism": "keeps a costly promise under pressure",
                "information_reveals": ["the safe path requires betraying the promise"],
                "antagonist_pressure": "the institution closes the safe path",
                "next_chapter_bridge": "the obligation requires a new witness",
                "safe_summary": "Prepared chapter plan.",
                "structured_facts": [{"key": "chapter", "value": 1}],
            },
            "style_policy": {
                "safe_summary": "Project style policy.",
                "structured_facts": [],
            },
            "quality_rubric": {
                "safe_summary": "Project quality rubric.",
                "structured_facts": [],
            },
            "platform_profile": {
                "safe_summary": "Internal fixture platform profile.",
                "structured_facts": [{"key": "platform", "value": "fixture"}],
            },
            "operator_checklist": {
                "safe_summary": "Checklist completed.",
                "structured_facts": [
                    {"key": "completed", "value": True},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-checklist-v1",
                    },
                ],
            },
            "approval_decision": {
                "safe_summary": "Versioned fixture-only waiver approval.",
                "structured_facts": [
                    {"key": "approved", "value": True},
                    {"key": "decision", "value": "APPROVED"},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-approval-v1",
                    },
                    {
                        "key": "waiver_reason",
                        "value": "Exercise internal fixture release protocol.",
                    },
                    {
                        "key": "waived_dimensions",
                        "value": list(QUALITY_DIMENSIONS),
                    },
                    {
                        "key": "scope",
                        "value": {
                            "project_id": project_id,
                            "scope_type": "PROJECT_FIXTURE",
                            "release_readiness": "INTERNAL_REVIEW_RELEASE",
                        },
                    },
                    {"key": "expiry", "value": "2099-01-01T00:00:00Z"},
                    {"key": "fixture_protocol_only", "value": True},
                ],
            },
            "commercial_quality_report": calibrated(
                (
                    "golden_opening",
                    "reader_promise",
                    "reward",
                    "protagonist_charm",
                    "antagonist_pressure",
                    "toxic_point",
                    "chapter_hook",
                    "suspense_progression",
                    "emotional_curve",
                    "serialization_function",
                )
            ),
            "source_originality_quality_report": calibrated(
                (
                    "originality",
                    "anti_ai",
                    "style_drift",
                )
            ),
            "longform_quality_report": calibrated(
                (
                    "character_motivation_drift",
                    "relationship_continuity",
                    "timeline_consistency",
                    "foreshadow_status",
                    "promise_payoff_debt",
                    "world_rule_conflict",
                    "power_state_conflict",
                    "narrative_pattern_repetition",
                    "arc_progress",
                )
            ),
            "platform_quality_report": calibrated(
                (
                    "chapter_length",
                    "format",
                    "sensitive_content",
                    "ai_content_policy",
                    "opening_expectations",
                    "platform_rhythm",
                    "publish_metadata",
                )
            ),
        }
        with transaction() as connection, connection.cursor() as cursor:
            for asset_type, content in assets.items():
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                asset_id = identifier(f"{asset_type}-asset")
                version_id = identifier(asset_type)
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )
            if typed_empty:
                for state_kind in CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES:
                    content = {
                        "state_kind": state_kind,
                        "previous_chapter": chapter - 1,
                        "state_exists": False,
                        "canon_reduction_status": "SUCCEEDED",
                        "previous_final_release_gate_id": f"release-gate:{chapter - 1}",
                        "fixture_protocol_only": True,
                    }
                    content_hash = (
                        "sha256:"
                        + hashlib.sha256(
                            json.dumps(
                                content, sort_keys=True, separators=(",", ":")
                            ).encode()
                        ).hexdigest()
                    )
                    asset_id = identifier(f"state-absence-{state_kind}-asset")
                    version_id = identifier(f"state-absence-{state_kind}")
                    cursor.execute(
                        "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                        [asset_id, project_id, "state_absence_evidence"],
                    )
                    cursor.execute(
                        """
                        INSERT INTO authority_asset_version (
                            asset_version_id, asset_id, version_number, lifecycle,
                            eligibility, governance, content, content_hash, schema_version
                        ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                        """,
                        [version_id, asset_id, json.dumps(content), content_hash],
                    )
                    absence_inputs.append(
                        (
                            state_kind,
                            {
                                "asset_version_id": version_id,
                                "content_hash": content_hash,
                            },
                        )
                    )
        if typed_empty:
            app = ContentAuthorityApplication(
                DATABASE_URL,
                application_build_id="typed-empty-integration",
                commit_sha="a" * 40,
                integration_proven=CONTENT_CODECS,
            )
            for state_kind, evidence in absence_inputs:
                app.execute(
                    ContentOperationRequest(
                        definition_name="chapter.state.initialize_empty",
                        project_id=project_id,
                        workspace_id=f"workspace:{project_id}",
                        actor_id="fixture-system-scheduler",
                        trace_id=identifier(f"empty-trace-{state_kind}"),
                        correlation_id=identifier("empty-correlation"),
                        idempotency_key=f"{project_id}:empty:{chapter - 1}:{state_kind}",
                        payload={
                            "state_kind": state_kind,
                            "previous_chapter": chapter - 1,
                            "reason": "explicit empty fixture baseline",
                        },
                        input_assets=(evidence,),
                    )
                )

    @staticmethod
    def _release_evidence(
        project_id: str, *, with_waiver: bool = True
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        quality = {
            "commercial_quality_report": (
                "golden_opening",
                "reader_promise",
                "reward",
                "protagonist_charm",
                "antagonist_pressure",
                "toxic_point",
                "chapter_hook",
                "suspense_progression",
                "emotional_curve",
                "serialization_function",
            ),
            "source_originality_quality_report": (
                "originality",
                "anti_ai",
                "style_drift",
            ),
            "longform_quality_report": (
                "character_motivation_drift",
                "relationship_continuity",
                "timeline_consistency",
                "foreshadow_status",
                "promise_payoff_debt",
                "world_rule_conflict",
                "power_state_conflict",
                "narrative_pattern_repetition",
                "arc_progress",
            ),
            "platform_quality_report": (
                "chapter_length",
                "format",
                "sensitive_content",
                "ai_content_policy",
                "opening_expectations",
                "platform_rhythm",
                "publish_metadata",
            ),
        }
        evidence = [
            (
                "chapter_plan",
                "Complete authoritative ChapterPlan.",
                [],
                {
                    "project_id": project_id,
                    "chapter": 1,
                    "title": "A Durable Promise",
                    "premise": "A promise creates a visible irreversible cost.",
                    "chapter_objective": "Force a public choice with an irreversible loss.",
                    "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                    "chapter_hook": "The cost creates a new obligation.",
                },
            ),
            (
                "quality_rubric",
                "Versioned quality thresholds.",
                [{"key": "thresholds", "value": {"readability": 70}}],
                None,
            ),
            (
                "platform_profile",
                "Versioned internal platform rules.",
                [
                    {
                        "key": "platform_rules",
                        "value": {
                            "chapter_length": {"minimum": 10, "maximum": 10000},
                            "format": {"paragraph_max": 500},
                            "sensitive_content": [],
                            "ai_content": {"mode": "internal"},
                            "opening": ["visible conflict"],
                            "rhythm": ["payoff"],
                            "publish_metadata": {"title_required": True},
                        },
                    }
                ],
                None,
            ),
            (
                "operator_checklist",
                "Versioned fixture waiver checklist.",
                [
                    {"key": "completed", "value": True},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-checklist-v1",
                    },
                ],
            ),
            (
                "operator_approval",
                "Versioned fixture-only approval decision.",
                [
                    {"key": "approved", "value": with_waiver},
                    {
                        "key": "decision",
                        "value": "APPROVED" if with_waiver else "NOT_APPROVED",
                    },
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-approval-v1",
                    },
                    {
                        "key": "waiver_reason",
                        "value": "Exercise internal fixture release protocol.",
                    },
                    {
                        "key": "waived_dimensions",
                        "value": list(QUALITY_DIMENSIONS) if with_waiver else [],
                    },
                    {
                        "key": "scope",
                        "value": {
                            "project_id": project_id,
                            "scope_type": "PROJECT_FIXTURE",
                            "release_readiness": "INTERNAL_REVIEW_RELEASE",
                        },
                    },
                    {"key": "expiry", "value": "2099-01-01T00:00:00Z"},
                    {"key": "fixture_protocol_only", "value": True},
                ],
            ),
        ]
        evidence.extend(
            (
                asset_type,
                "Honest fixture-only quality evidence.",
                [
                    {
                        "key": "dimension_evidence",
                        "value": [
                            {
                                "dimension": dimension,
                                "gate_status": (
                                    "WAIVED_BY_APPROVAL" if with_waiver else "PASSED"
                                ),
                                "calibration_status": "FIXTURE_UNCALIBRATED",
                                "human_verified": False,
                                "fixture_protocol_only": True,
                            }
                            for dimension in dimensions
                        ],
                    }
                ],
                None,
            )
            for asset_type, dimensions in quality.items()
        )
        with transaction() as connection, connection.cursor() as cursor:
            normalized_evidence = [
                item if len(item) == 4 else (*item, None) for item in evidence
            ]
            for asset_type, summary, facts, explicit_content in normalized_evidence:
                content = explicit_content or {
                    "safe_summary": summary,
                    "structured_facts": facts,
                }
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                version_id = identifier(asset_type)
                asset_id = identifier(f"{asset_type}-asset")
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )
                candidates.append(
                    {
                        "asset_version_id": version_id,
                        "asset_type": asset_type,
                        "project_id": project_id,
                        "content_hash": content_hash,
                        "estimated_tokens": 20,
                        "allowed_use": "evidence_only"
                        if asset_type.endswith("quality_report")
                        else "generation",
                        "source_use_mode": "generation",
                        **content,
                        "narrative_function": "release_evidence",
                    }
                )
        return candidates

    @staticmethod
    def _quality_and_publish_gate(
        root_operation_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.definition_name, version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name IN (
                      'chapter.quality.evaluate',
                      'chapter.publishing.prepare_release'
                  )
                  AND output.output_key IN (
                      'chapter.quality', 'chapter.publish_gate'
                  )
                """,
                [root_operation_id],
            )
            values = {str(name): dict(content) for name, content in cursor.fetchall()}
        return (
            values["chapter.quality.evaluate"],
            values["chapter.publishing.prepare_release"],
        )


if __name__ == "__main__":
    unittest.main()
