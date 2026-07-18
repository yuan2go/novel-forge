from __future__ import annotations

import unittest
import hashlib
import json

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decide_canon_approval,
    list_canon_approvals,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    admit_single_chapter_saga,
)
from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from novel_forge.modules.production_preparation import (
    PostgresProductionAssetResolver,
    ProductionPreparationRequest,
    ProductionPreparationService,
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
        self.assertTrue(all(item["project_id"] == project_id for item in command.context_candidates))
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
            scheduler.tick(project_id=project_id, root_operation_id=admission.root_operation_id)
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

    def test_chapter_two_consumes_typed_empty_state_assets_as_logical_snapshots(self) -> None:
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
            )
        )
        self.assertEqual(prepared.report.decision, "READY")
        command = prepared.command
        assert command is not None
        typed_candidates = [
            item for item in command.context_candidates
            if item.get("physical_asset_type") == "typed_empty_state_snapshot"
        ]
        self.assertEqual(len(typed_candidates), 9)

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
            item for item in bundle["context_segments"]
            if item.get("physical_asset_type") == "typed_empty_state_snapshot"
        ]
        self.assertEqual(len(typed_segments), 9)
        self.assertTrue(
            all(item["structured_facts"][0]["declared_empty"] for item in typed_segments)
        )

    def test_high_impact_canon_waits_for_approved_decision_asset(self) -> None:
        class HighImpactFixture(DeterministicFixtureChapterProvider):
            supports_semantic_extraction = True

            def invoke(self, request, *, stage, payload):
                if stage != "canon_extraction":
                    return super().invoke(request, stage=stage, payload=payload)
                return ModelProviderResult(
                    output={"character_state_changes": [{
                        "character_id": "protagonist", "status": "dead",
                        "impact_type": "character_death", "confidence": .9,
                        "evidence_start": 0, "evidence_end": 12,
                    }]},
                    provider_id="deterministic_semantic_fixture", model_id="fixture",
                    prompt_version="fixture-v1", skill_version="fixture-v1",
                    input_tokens=0, output_tokens=0, cost_amount="0", currency="USD",
                    real_model_call=False,
                )

        project_id = identifier("canon-gate-project")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(HighImpactFixture())
        request = SingleChapterRequest(
            project_id=project_id, workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator", chapter=1, title="A Canon Gate",
            premise="A costly choice changes an identity permanently.",
            trace_id=identifier("trace"), correlation_id=identifier("correlation"),
            application_build_id="canon-gate-test", commit_sha="d" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL, request=request, registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL, registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        waiting = None
        for _ in range(12):
            tick = scheduler.tick(project_id=project_id, root_operation_id=admission.root_operation_id)
            if tick.saga_status == "WAITING_GATE":
                waiting = tick
                break
        self.assertIsNotNone(waiting)
        approvals = list_canon_approvals(DATABASE_URL, project_id=project_id)
        self.assertEqual(len(approvals), 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM authority_operation WHERE root_operation_id = %s AND definition_name = %s", [admission.root_operation_id, ChapterNode.CANON.definition_name])
            self.assertEqual(cursor.fetchone()[0], 0)
        decision = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(project_id, "local-operator", request.trace_id, request.correlation_id),
            approval_request_id=approvals[0]["approval_request_id"],
            expected_version=approvals[0]["version"], decision="APPROVE",
            reason="fixture proves per-change gate recovery", evidence={"fixture": True},
            edited_payload=None, idempotency_key="approve-once",
        )
        self.assertTrue(decision["gate_resumed"])
        self.assertTrue(decision["decision_operation_id"])
        replay = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(project_id, "local-operator", request.trace_id, request.correlation_id),
            approval_request_id=approvals[0]["approval_request_id"],
            expected_version=approvals[0]["version"], decision="APPROVE",
            reason="fixture proves per-change gate recovery", evidence={"fixture": True},
            edited_payload=None, idempotency_key="approve-once",
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["decision_operation_id"], decision["decision_operation_id"])
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
            terminal = scheduler.tick(project_id=project_id, root_operation_id=admission.root_operation_id)
            if terminal.saga_status == "SUCCEEDED":
                break
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version.content FROM authority_operation_output_asset binding JOIN authority_asset_version version ON version.asset_version_id = binding.asset_version_id JOIN authority_asset asset ON asset.asset_id = version.asset_id WHERE binding.operation_id IN (SELECT operation_id FROM authority_operation WHERE root_operation_id = %s AND definition_name = %s) AND asset.asset_type = 'character_state_snapshot'", [admission.root_operation_id, ChapterNode.CANON.definition_name])
            snapshot = cursor.fetchone()[0]
        self.assertEqual(snapshot["changes"][0]["status"], "dead")
        self.assertIn(decision["asset_version_id"], snapshot["canon_approval_decision_asset_version_ids"])

    @staticmethod
    def _preparation_assets(
        project_id: str, *, chapter: int = 1, typed_empty: bool = False
    ) -> None:
        def calibrated(dimensions: tuple[str, ...]) -> dict[str, object]:
            return {
                "safe_summary": "Human-calibrated fixture gate evidence.",
                "allowed_use": "evidence_only",
                "structured_facts": [{
                    "key": "dimension_evidence",
                    "value": [
                        {
                            "dimension": item,
                            "gate_status": "PASSED",
                            "calibration_status": "HUMAN_CALIBRATED",
                            "human_verified": True,
                            "fixture_protocol_only": True,
                        }
                        for item in dimensions
                    ],
                }],
            }
        assets = {
            "chapter_plan": {
                "chapter": chapter,
                "title": "Prepared Chapter",
                "premise": "A prepared promise creates a visible cost.",
                "chapter_objective": "Force a public choice with a visible cost.",
                "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                "chapter_hook": "The cost creates a new obligation.",
                "safe_summary": "Prepared chapter plan.",
                "structured_facts": [{"key": "chapter", "value": 1}],
            },
            "style_policy": {
                "safe_summary": "Project style policy.", "structured_facts": []
            },
            "quality_rubric": {
                "safe_summary": "Project quality rubric.", "structured_facts": []
            },
            "platform_profile": {
                "safe_summary": "Internal fixture platform profile.",
                "structured_facts": [{"key": "platform", "value": "fixture"}],
            },
            "operator_checklist": {
                "safe_summary": "Checklist completed.",
                "structured_facts": [{"key": "completed", "value": True}],
            },
            "operator_approval": {
                "safe_summary": "Operator approval.",
                "structured_facts": [{"key": "approved", "value": True}],
            },
            "commercial_quality_report": calibrated((
                "golden_opening", "reader_promise", "reward", "protagonist_charm",
                "antagonist_pressure", "toxic_point", "chapter_hook",
                "suspense_progression", "emotional_curve", "serialization_function",
            )),
            "source_originality_quality_report": calibrated((
                "originality", "anti_ai", "style_drift",
            )),
            "longform_quality_report": calibrated((
                "character_motivation_drift", "relationship_continuity",
                "timeline_consistency", "foreshadow_status", "promise_payoff_debt",
                "world_rule_conflict", "power_state_conflict",
                "narrative_pattern_repetition", "arc_progress",
            )),
            "platform_quality_report": calibrated((
                "chapter_length", "format", "sensitive_content", "ai_content_policy",
                "opening_expectations", "platform_rhythm", "publish_metadata",
            )),
        }
        with transaction() as connection, connection.cursor() as cursor:
            for asset_type, content in assets.items():
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
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
                        eligibility, governance, content, content_hash
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )
            if typed_empty:
                state_kinds = (
                    "canon_snapshot", "character_state_snapshot",
                    "relationship_state_snapshot", "timeline_snapshot",
                    "foreshadow_snapshot", "promise_ledger_snapshot",
                    "reward_ledger_snapshot", "world_rule_snapshot",
                    "power_state_snapshot",
                )
                for state_kind in state_kinds:
                    content = {
                        "type": "TypedEmptyStateSnapshot",
                        "project_id": project_id,
                        "chapter": chapter - 1,
                        "previous_chapter": chapter - 1,
                        "state_kind": state_kind,
                        "logical_asset_type": state_kind,
                        "declared_empty": True,
                        "entries": [],
                        "reason": "explicit empty fixture baseline",
                        "contract_version": "typed-empty-state-snapshot-v1",
                    }
                    content_hash = "sha256:" + hashlib.sha256(
                        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    asset_id = identifier(f"typed-empty-{state_kind}-asset")
                    version_id = identifier(f"typed-empty-{state_kind}")
                    cursor.execute(
                        "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                        [asset_id, project_id, "typed_empty_state_snapshot"],
                    )
                    cursor.execute(
                        """
                        INSERT INTO authority_asset_version (
                            asset_version_id, asset_id, version_number, lifecycle,
                            eligibility, governance, content, content_hash
                        ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                        """,
                        [version_id, asset_id, json.dumps(content), content_hash],
                    )

    @staticmethod
    def _release_evidence(project_id: str) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        quality = {
            "commercial_quality_report": (
                "golden_opening", "reader_promise", "reward", "protagonist_charm",
                "antagonist_pressure", "toxic_point", "chapter_hook",
                "suspense_progression", "emotional_curve", "serialization_function",
            ),
            "source_originality_quality_report": ("originality", "anti_ai", "style_drift"),
            "longform_quality_report": (
                "character_motivation_drift", "relationship_continuity",
                "timeline_consistency", "foreshadow_status", "promise_payoff_debt",
                "world_rule_conflict", "power_state_conflict",
                "narrative_pattern_repetition", "arc_progress",
            ),
            "platform_quality_report": (
                "chapter_length", "format", "sensitive_content", "ai_content_policy",
                "opening_expectations", "platform_rhythm", "publish_metadata",
            ),
        }
        evidence = [
            (
                "chapter_plan", "Complete authoritative ChapterPlan.", [],
                {
                    "project_id": project_id, "chapter": 1,
                    "title": "A Durable Promise",
                    "premise": "A promise creates a visible irreversible cost.",
                    "chapter_objective": "Force a public choice with an irreversible loss.",
                    "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                    "chapter_hook": "The cost creates a new obligation.",
                },
            ),
            (
                "quality_rubric", "Versioned quality thresholds.",
                [{"key": "thresholds", "value": {"readability": 70}}], None,
            ),
            (
                "platform_profile", "Versioned internal platform rules.",
                [{"key": "platform_rules", "value": {
                    "chapter_length": {"minimum": 10, "maximum": 10000},
                    "format": {"paragraph_max": 500}, "sensitive_content": [],
                    "ai_content": {"mode": "internal"},
                    "opening": ["visible conflict"], "rhythm": ["payoff"],
                    "publish_metadata": {"title_required": True},
                }}], None,
            ),
            ("operator_checklist", "Operator checklist completed.", [{"key": "completed", "value": True}]),
            ("operator_approval", "Operator approved fixture release.", [{"key": "approved", "value": True}]),
        ]
        evidence.extend(
            (
                asset_type,
                "Human-calibrated fixture quality evidence.",
                [{"key": "dimension_evidence", "value": [
                    {
                        "dimension": dimension, "gate_status": "PASSED",
                        "calibration_status": "HUMAN_CALIBRATED", "human_verified": True,
                        "fixture_protocol_only": True,
                    }
                    for dimension in dimensions
                ]}],
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
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
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
                        eligibility, governance, content, content_hash
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
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
                        "allowed_use": "evidence_only" if asset_type.endswith("quality_report") else "generation",
                        "source_use_mode": "generation",
                        **content,
                        "narrative_function": "release_evidence",
                    }
                )
        return candidates


if __name__ == "__main__":
    unittest.main()
