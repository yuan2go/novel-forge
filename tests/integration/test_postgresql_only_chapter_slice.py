from __future__ import annotations

import unittest
import hashlib
import json

from novel_forge.modules.chapter_authority.contracts import (
    ChapterNode,
    QUALITY_GROUP_NODES,
)
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    run_single_chapter_slice,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class PostgreSQLOnlyChapterSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    @staticmethod
    def release_evidence(project_id: str):
        def report(asset_type: str, dimensions: tuple[str, ...]) -> dict[str, object]:
            return {
                "asset_version_id": f"{project_id}:{asset_type}-v1",
                "asset_type": asset_type,
                "project_id": project_id,
                "estimated_tokens": 40,
                "allowed_use": "evidence_only",
                "source_use_mode": "generation",
                "safe_summary": "Human-calibrated fixture quality evidence.",
                "structured_facts": [
                    {
                        "key": "dimension_evidence",
                        "value": [
                            {
                                "dimension": item,
                                "gate_status": "WAIVED_BY_APPROVAL",
                                "calibration_status": "HUMAN_CALIBRATED",
                                "human_verified": True,
                                "fixture_protocol_only": True,
                            }
                            for item in dimensions
                        ],
                    }
                ],
                "narrative_function": "quality_evidence",
            }

        candidates = (
            {
                "asset_version_id": f"{project_id}:chapter-plan-v1",
                "asset_type": "chapter_plan",
                "project_id": project_id,
                "estimated_tokens": 120,
                "safe_summary": "A complete authoritative ChapterPlan.",
                "structured_facts": [],
                "narrative_function": "chapter_plan",
                "content": {
                    "project_id": project_id,
                    "chapter": 1,
                    "title": "The Cost of a Promise",
                    "premise": "The protagonist must pay a visible cost to keep a promise.",
                    "chapter_objective": "Force a public choice with an irreversible loss.",
                    "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                    "required_arc_contributions": [
                        {
                            "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                            "contribution": "ADVANCE",
                        }
                    ],
                    "constraint_envelope": {
                        "arc_working_set": {
                            "selected_contributions": [
                                {
                                    "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                                    "role": "PRIMARY",
                                    "action": "ADVANCE",
                                }
                            ]
                        }
                    },
                    "scene_plan": [
                        {
                            "scene_id": "s1",
                            "goal": "keep the promise",
                            "conflict": "safety requires breaking the promise",
                            "arc_progress": [f"{project_id}:fixture-arc-plan-v1"],
                            "beats": ["pressure", "choice", "visible cost"],
                        }
                    ],
                    "chapter_hook": "The loss creates a second debt.",
                },
            },
            {
                "asset_version_id": f"{project_id}:checklist-v1",
                "asset_type": "operator_checklist",
                "project_id": project_id,
                "estimated_tokens": 20,
                "safe_summary": "Operator checklist completed.",
                "structured_facts": [
                    {"key": "completed", "value": True},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-checklist-v1",
                    },
                ],
                "narrative_function": "release_evidence",
            },
            {
                "asset_version_id": f"{project_id}:quality-rubric-v1",
                "asset_type": "quality_rubric",
                "project_id": project_id,
                "safe_summary": "Versioned quality thresholds.",
                "structured_facts": [
                    {"key": "thresholds", "value": {"readability": 70}}
                ],
                "estimated_tokens": 20,
                "narrative_function": "quality_policy",
            },
            {
                "asset_version_id": f"{project_id}:platform-profile-v1",
                "asset_type": "platform_profile",
                "project_id": project_id,
                "safe_summary": "Versioned internal platform policy.",
                "structured_facts": [
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
                "estimated_tokens": 30,
                "narrative_function": "platform_policy",
            },
            {
                "asset_version_id": f"{project_id}:approval-v1",
                "asset_type": "operator_approval",
                "project_id": project_id,
                "estimated_tokens": 20,
                "safe_summary": "Operator approved fixture release evidence.",
                "structured_facts": [
                    {"key": "approved", "value": True},
                    {"key": "decision", "value": "APPROVED"},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-approval-v1",
                    },
                    {"key": "fixture_protocol_only", "value": True},
                    {
                        "key": "waiver_reason",
                        "value": "Deterministic integration fixture release only.",
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
                ],
                "narrative_function": "release_evidence",
            },
            report(
                "commercial_quality_report",
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
                ),
            ),
            report(
                "source_originality_quality_report",
                (
                    "originality",
                    "anti_ai",
                    "style_drift",
                ),
            ),
            report(
                "longform_quality_report",
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
                ),
            ),
            report(
                "platform_quality_report",
                (
                    "chapter_length",
                    "format",
                    "sensitive_content",
                    "ai_content_policy",
                    "opening_expectations",
                    "platform_rhythm",
                    "publish_metadata",
                ),
            ),
        )
        with transaction() as connection, connection.cursor() as cursor:
            for candidate in candidates:
                content = dict(
                    candidate.get("content")
                    or {
                        "safe_summary": candidate["safe_summary"],
                        "structured_facts": candidate["structured_facts"],
                    }
                )
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                candidate["content_hash"] = content_hash
                asset_id = f"{candidate['asset_version_id']}:asset"
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, candidate["asset_type"]],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                    """,
                    [
                        candidate["asset_version_id"],
                        asset_id,
                        json.dumps(content),
                        content_hash,
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_qualification (
                        qualification_id, asset_version_id, policy_version, decision, evidence
                    ) VALUES (%s, %s, 'fixture-release-evidence-v1', 'ELIGIBLE', '{}'::jsonb)
                    """,
                    [
                        f"{candidate['asset_version_id']}:qualification",
                        candidate["asset_version_id"],
                    ],
                )
        return candidates

    def test_one_chapter_uses_authority_handlers_recovery_and_verified_export(
        self,
    ) -> None:
        project_id = identifier("chapter-project")
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="chapter-slice-worker",
            chapter=1,
            title="The Cost of a Promise",
            premise="The protagonist must pay a visible cost to keep a promise.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="postgresql-only-chapter-test",
            commit_sha="c" * 40,
            context_candidates=self.release_evidence(project_id),
        )
        result = run_single_chapter_slice(
            DATABASE_URL,
            request=request,
            registry=build_chapter_handler_registry(
                DeterministicFixtureChapterProvider()
            ),
            object_store_adapter=FakeDeterministicProvider("ambiguous"),
            retry_once_at=ChapterNode.DRAFT,
            exercise_unknown_export_reconciliation=True,
        )

        self.assertEqual(result.root_status, "SUCCEEDED")
        self.assertEqual(result.saga_status, "SUCCEEDED")
        self.assertEqual(set(result.operation_ids), set(ChapterNode))
        self.assertEqual(set(result.outputs), set(ChapterNode))
        self.assertTrue(result.export_evidence.retry_blocked_before_reconciliation)
        self.assertTrue(result.export_evidence.stale_fencing_rejected)
        self.assertEqual(result.export_evidence.reconciliation_outcome, "ambiguous")
        self.assertTrue(result.export_evidence.duplicate_receipt_replayed)

        manifest = result.evidence_manifest
        self.assertEqual(manifest["root"]["status"], "SUCCEEDED")
        self.assertEqual(manifest["saga"]["status"], "SUCCEEDED")
        self.assertEqual(manifest["saga"]["forward_recovery_attempts"], 1)
        self.assertEqual(len(manifest["operations"]), 1 + len(ChapterNode))
        # Evidence contains every current dimension, bounded Quality group coverage,
        # and ten non-dimension preparation, continuity and projection artifacts.
        expected_output_count = len(ChapterNode) + len(QUALITY_DIMENSIONS) + 10 + len(QUALITY_GROUP_NODES)
        self.assertEqual(len(manifest["outputs"]), expected_output_count)
        self.assertEqual(
            sum(
                item["asset_type"] == "multiscale_narrative_quality_report"
                for item in manifest["outputs"]
            ),
            1,
        )
        self.assertEqual(
            {item["output_key"] for item in manifest["outputs"] if item["asset_type"] == "chapter_quality_evidence"},
            {f"chapter.quality.evidence.{dimension}" for dimension in QUALITY_DIMENSIONS},
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in manifest["outputs"]
                    if item["asset_type"] == "quality_context_coverage_report"
                ]
            ),
            len(QUALITY_GROUP_NODES),
        )
        self.assertEqual(manifest["attempt_counts"][ChapterNode.DRAFT.value], 2)
        for node in ChapterNode:
            self.assertEqual(manifest["operation_statuses"][node.value], "SUCCEEDED")
            self.assertEqual(
                manifest["attempt_terminal_statuses"][node.value], "SUCCEEDED"
            )
            self.assertEqual(
                manifest["qualification_decisions"][node.value], "ELIGIBLE"
            )
        self.assertEqual(manifest["export"]["blob_status"], "AVAILABLE")
        self.assertEqual(manifest["export"]["effect_status"], "SUCCEEDED")
        self.assertEqual(manifest["export"]["dispatch_status"], "SUCCEEDED")
        self.assertEqual(manifest["export"]["receipt_status"], "VERIFIED")
        final_gate = next(
            item
            for item in manifest["outputs"]
            if item["asset_type"] == "final_release_gate_report"
        )
        self.assertEqual(final_gate["node"], ChapterNode.FINAL_RELEASE_GATE.value)
        self.assertGreaterEqual(manifest["evidence_counts"]["state_event"], 1)
        self.assertGreaterEqual(manifest["evidence_counts"]["audit_log"], 1)
        self.assertGreaterEqual(manifest["evidence_counts"]["outbox_event"], 1)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                WHERE operation.root_operation_id = %s
                  AND binding.content_hash <> ''
                """,
                [result.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], expected_output_count)
            cursor.execute(
                """
                SELECT asset.asset_type, binding.role, version.content->>'state_kind'
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE operation.root_operation_id = %s
                  AND operation.definition_name = %s
                  AND binding.role = 'state_snapshot'
                ORDER BY asset.asset_type
                """,
                [result.root_operation_id, ChapterNode.CANON.definition_name],
            )
            snapshots = cursor.fetchall()
            self.assertEqual(snapshots, [])
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation AS operation
                WHERE operation.root_operation_id = %s
                  AND operation.operation_id <> %s
                  AND jsonb_array_length(operation.input_asset_snapshot) > 0
                """,
                [result.root_operation_id, result.root_operation_id],
            )
            # Every production node, including deterministic preparation and
            # Memo-driven Retrieval, now freezes an explicit input snapshot.
            self.assertEqual(cursor.fetchone()[0], len(ChapterNode))

    def test_standard_success_adapter_completes_without_unknown_probe(self) -> None:
        project_id = identifier("chapter-project-success")
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="chapter-slice-worker",
            chapter=1,
            title="A Bounded Success",
            premise="A choice has an immediate and visible cost.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="postgresql-only-chapter-test",
            commit_sha="c" * 40,
            context_candidates=self.release_evidence(project_id),
        )

        result = run_single_chapter_slice(
            DATABASE_URL,
            request=request,
            registry=build_chapter_handler_registry(
                DeterministicFixtureChapterProvider()
            ),
            object_store_adapter=FakeDeterministicProvider("success"),
        )

        self.assertEqual(result.root_status, "SUCCEEDED")
        self.assertEqual(result.export_evidence.reconciliation_outcome, "not_exercised")
        self.assertFalse(result.export_evidence.retry_blocked_before_reconciliation)
        self.assertEqual(result.evidence_manifest["export"]["blob_status"], "AVAILABLE")


if __name__ == "__main__":
    unittest.main()
