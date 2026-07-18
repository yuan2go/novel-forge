from __future__ import annotations

import unittest
import hashlib
import json

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
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

    @staticmethod
    def _preparation_assets(project_id: str) -> None:
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
                        }
                        for item in dimensions
                    ],
                }],
            }
        assets = {
            "chapter_plan": {
                "chapter": 1,
                "title": "Prepared Chapter",
                "premise": "A prepared promise creates a visible cost.",
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
                    }
                    for dimension in dimensions
                ]}],
            )
            for asset_type, dimensions in quality.items()
        )
        with transaction() as connection, connection.cursor() as cursor:
            for asset_type, summary, facts in evidence:
                content = {
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
