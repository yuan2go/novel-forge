from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.novel_os_cockpit import build_multi_book_daily_production_report, build_multi_book_production_schedule, build_project_cockpit_snapshot
from novel_forge.modules.permission_center import build_approval_request_caller_readiness_report, create_approval_request, resolve_approval_request
from novel_forge.modules.context_builder import run_context_governance_coverage_gate
from novel_forge.modules.production_governance import build_production_governance_evidence_drift_report, run_production_governance_drift_gate
from novel_forge.modules.runtime_ledger import record_gate_result, record_model_call_log
from novel_forge.modules.chapter_production_bus.service import V1_SEQUENCE_REQUIRED_OUTPUTS
from novel_forge.schemas import BaseAsset, ChapterPlan, ContextBundle, DraftChapter, ProjectMetricSnapshot
from novel_forge.storage.local import LocalStorage


class NovelOsCockpitTests(unittest.TestCase):
    def test_project_cockpit_treats_source_gate_evidence_without_status_as_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(
                BaseAsset(
                    id="agent-run-source-gate-no-status",
                    type="agent_run",
                    title="Agent run with incomplete source gate evidence",
                    content={
                        "run_id": "agent-run-source-gate-no-status",
                        "agent_type": "context",
                        "operation": "build-context-bundle",
                        "status": "succeeded",
                        "input_assets": [],
                        "output_assets": [],
                        "contract_id": "context-contract",
                        "permissions": {},
                        "evidence": {
                            "source_governance_runtime_gate": {
                                "gate_result_path": "data/runs/source-governance-runtime-gate-no-status.json",
                                "summary": {"blocking_count": 0},
                            }
                        },
                    },
                    metadata={"project_id": "book-a"},
                )
            )

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-a")

            evidence = snapshot["asset"]["content"]["cockpit"]["source_governance_runtime_evidence"]
            self.assertEqual(evidence["status"], "warning")
            self.assertEqual(evidence["latest"]["status"], "missing")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["source_governance_runtime_evidence_status"], "warning")

    def test_project_cockpit_infers_source_gate_scope_from_linked_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            context_path = storage.write_asset_auto(
                ContextBundle(
                    title="Book A context bundle",
                    content={"project_id": "book-a", "bundle": "scope fixture"},
                    metadata={"project_id": "book-a"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="source-governance-runtime-gate-book-a",
                    type="gate_result",
                    title="Source gate fixture",
                    content={"gate_kind": "source_governance_runtime", "status": "passed"},
                    metadata={"project_id": "book-a"},
                )
            )
            run_path = storage.write_asset_auto(
                BaseAsset(
                    id="sparse-agent-run-source-gate",
                    type="agent_run",
                    title="Sparse agent run with linked context evidence",
                    content={
                        "run_id": "sparse-agent-run-source-gate",
                        "agent_type": "context",
                        "operation": "build-context-bundle",
                        "status": "succeeded",
                        "input_assets": [],
                        "output_assets": [{"path": str(context_path.relative_to(storage.root)), "type": "context_bundle"}],
                        "evidence": {
                            "source_governance_runtime_gate": {
                                "status": "passed",
                                "gate_result_path": "data/runs/source-governance-runtime-gate-book-a.json",
                                "summary": {"blocking_count": 0},
                            }
                        },
                    },
                    metadata={},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="sparse-checkpoint-source-gate",
                    type="agent_checkpoint",
                    title="Sparse checkpoint with linked run source gate",
                    content={
                        "agent_run_id": "sparse-agent-run-source-gate",
                        "agent_run_path": str(run_path.relative_to(storage.root)),
                        "checkpoint_id": "sparse-checkpoint-source-gate",
                        "status": "succeeded",
                        "state": {
                            "operation": "build-context-bundle",
                            "source_governance_runtime_gate": {
                                "status": "passed",
                                "gate_result_path": "data/runs/source-governance-runtime-gate-book-a.json",
                                "summary": {"blocking_count": 0},
                            },
                        },
                    },
                    metadata={},
                )
            )

            book_a = build_project_cockpit_snapshot(storage, project_id="book-a")
            book_b = build_project_cockpit_snapshot(storage, project_id="book-b")

            self.assertEqual(book_a["asset"]["content"]["quality"]["source_governance_runtime_evidence_status"], "passed")
            self.assertEqual(book_a["asset"]["content"]["quality"]["source_governance_runtime_evidence_count"], 2)
            self.assertEqual(
                {row["source_type"] for row in book_a["asset"]["content"]["cockpit"]["source_governance_runtime_evidence"]["rows"]},
                {"agent_run", "agent_checkpoint"},
            )
            self.assertEqual(book_b["asset"]["content"]["quality"]["source_governance_runtime_evidence_status"], "missing")
            self.assertEqual(book_b["asset"]["content"]["quality"]["source_governance_runtime_evidence_count"], 0)

    def test_project_cockpit_surfaces_quality_calibration_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Quality calibration readiness",
                    content={
                        "snapshot_kind": "quality_calibration_readiness",
                        "contract": "quality-calibration-readiness-v1",
                        "status": "review_required",
                        "project_id": "book-a",
                        "snapshot_at": "2026-07-08T00:00:00Z",
                        "throughput": {"asset_count": 3, "model_judge_result_count": 1, "human_annotation_count": 0, "golden_set_count": 0},
                        "quality": {
                            "readiness_status": "review_required",
                            "external_provider_judge_count": 0,
                            "human_annotation_count": 0,
                            "golden_set_count": 0,
                            "passed_provider_calibration_count": 0,
                            "missing_dimension_count": 4,
                            "fixture_or_mock_provider_judge_count": 1,
                        },
                        "task_health": {"review_required": True, "blocked_calibration_count": 0, "provider_call_executed": False},
                        "agent_health": {"calibration_boundary": "read-only", "premium_judge_claim_allowed": False},
                        "storage_health": {"evidence_path_count": 1, "asset_types_scanned": ["model_judge_result"], "data_dirs_scanned": 1},
                        "recommendations": ["run external provider judge and human calibration"],
                        "summary": {
                            "quality_rubric_pack_count": 1,
                            "quality_suite_report_count": 1,
                            "model_judge_result_count": 1,
                            "external_provider_judge_count": 0,
                            "provider_route_approved_judge_count": 0,
                            "fixture_or_mock_provider_judge_count": 1,
                            "human_annotation_count": 0,
                            "golden_set_count": 0,
                            "provider_calibration_report_count": 0,
                            "passed_provider_calibration_count": 0,
                            "failed_provider_calibration_count": 0,
                            "missing_dimension_count": 4,
                            "missing_dimensions": ["external_provider_judge_proof"],
                        },
                        "dimensions": [{"dimension": "external_provider_judge_proof", "status": "missing"}],
                        "evidence_paths": ["data/runs/fixture-model-judge.json"],
                        "operator_action": "run external provider judge with calibration",
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "quality_calibration_readiness"},
                )
            )

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-a")

            readiness = snapshot["asset"]["content"]["runtime_governance"]["quality_calibration_readiness"]
            self.assertEqual(readiness["status"], "review_required")
            self.assertEqual(readiness["summary"]["fixture_or_mock_provider_judge_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["quality_calibration_readiness_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["quality_calibration_missing_dimension_count"], 4)
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["quality_calibration"], "review_required")

    def test_project_cockpit_surfaces_quality_calibration_readiness_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            readiness_path = storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Quality calibration readiness",
                    content={
                        "snapshot_kind": "quality_calibration_readiness",
                        "contract": "quality-calibration-readiness-v1",
                        "status": "missing",
                        "summary": {"missing_dimension_count": 7, "external_provider_judge_count": 0},
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "quality_calibration_readiness"},
                )
            )
            record_gate_result(
                storage,
                gate_kind="quality_calibration_readiness_gate",
                status="failed",
                target_paths=[str(readiness_path)],
                result={
                    "contract": "quality-calibration-readiness-gate-v1",
                    "readiness_report_path": str(readiness_path),
                    "summary": {"readiness_status": "missing", "blocking_count": 1},
                    "blocking_dimensions": [{"dimension": "quality_calibration_readiness"}],
                },
                project_id="book-a",
                message="quality calibration readiness gate has 1 blocking dimension(s)",
                blocking=True,
            )

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-a")

            gate = snapshot["asset"]["content"]["runtime_governance"]["quality_calibration_readiness_gate"]
            self.assertEqual(gate["status"], "failed")
            self.assertEqual(gate["readiness_report_path"], str(readiness_path))
            self.assertTrue(gate["blocking"])
            self.assertEqual(snapshot["asset"]["content"]["quality"]["quality_calibration_readiness_gate_status"], "failed")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["quality_calibration_gate"], "failed")

    def test_project_cockpit_snapshot_is_schema_backed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(ChapterPlan(title="P1 plan", content={"chapter": 1}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(DraftChapter(title="P1 draft", content={"chapter": 1, "text": "原创章节"}, metadata={"project_id": "book-a"}))
            outputs = {key: f"data/v1/{key}.json" for key in V1_SEQUENCE_REQUIRED_OUTPUTS}
            storage.write_asset_auto(
                BaseAsset(
                    type="chapter_production_run",
                    title="Chapter 1 run",
                    content={
                        "run_id": "run-1",
                        "status": "succeeded",
                        "current_step": "completed",
                        "chapter": 1,
                        "step_order": ["chapter_plan", "draft", "review", "revision", "export"],
                        "steps": {},
                        "timeline": [],
                        "outputs": outputs,
                        "created_at": "2026-07-08T00:00:00Z",
                        "updated_at": "2026-07-08T00:00:01Z",
                    },
                    metadata={"project_id": "book-a"},
                )
            )
            pending_approval = create_approval_request(
                storage,
                {
                    "project_id": "book-a",
                    "scope": "publish",
                    "action": "submit_release_package",
                    "environment": "production",
                    "risk_level": "high",
                    "target_type": "release_package",
                    "target_id": "release-1",
                },
            )
            approved_approval = create_approval_request(
                storage,
                {
                    "project_id": "book-a",
                    "scope": "context",
                    "action": "override_context_bundle",
                    "environment": "local",
                    "risk_level": "medium",
                },
            )
            resolve_approval_request(storage, approved_approval["asset"]["content"]["request_id"], {"decision": "approved", "actor": "unit-test", "reason": "fixture"})
            build_approval_request_caller_readiness_report(storage, project_id="book-a")
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Source guarded apply readiness",
                    content={
                        "snapshot_kind": "source_guarded_apply_readiness",
                        "contract": "source-guarded-apply-readiness-v1",
                        "status": "review_required",
                        "project_id": "book-a",
                        "snapshot_at": "2026-07-08T00:00:00Z",
                        "throughput": {"repair_plan_count": 1, "approval_request_count": 1, "stale_asset_count": 1, "agent_task_count": 2},
                        "quality": {"readiness_status": "review_required", "stale_pending_regeneration_count": 1, "dispatch_applied": False},
                        "task_health": {"dispatch_ready_task_count": 1, "operator_action": "dispatch approved regeneration"},
                        "agent_health": {"planned_agent_operations": ["plan-source-derived-regeneration"]},
                        "storage_health": {"evidence_path_count": 3},
                        "recommendations": ["dispatch approved regeneration"],
                        "summary": {
                            "repair_plan_count": 1,
                            "pending_review_plan_count": 0,
                            "applied_plan_count": 1,
                            "approval_request_count": 1,
                            "pending_approval_count": 0,
                            "blocking_approval_count": 0,
                            "stale_pending_regeneration_count": 1,
                            "review_task_count": 0,
                            "dispatch_ready_task_count": 1,
                            "rollback_plan_count": 1,
                            "rollback_result_count": 0,
                        },
                        "repair_plans": [{"path": "data/runs/source-repair.json", "asset_status": "applied"}],
                        "stale_assets": [{"path": "data/knowledge/stale-card.json", "asset_status": "stale"}],
                        "agent_tasks": [{"path": "data/runs/source-task.json", "status": "approved_pending_dispatch"}],
                        "evidence_paths": ["data/runs/source-repair.json", "data/knowledge/stale-card.json", "data/runs/source-task.json"],
                        "operator_action": "dispatch approved regeneration",
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "source_guarded_apply_readiness"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="source-governance-runtime-gate-book-a",
                    type="gate_result",
                    title="Source governance runtime gate",
                    content={
                        "gate_id": "source-governance-runtime-gate-book-a",
                        "gate_kind": "source_governance_runtime",
                        "status": "failed",
                        "target_paths": ["data/runs/source-readiness.json"],
                        "blocking": True,
                        "message": "source governance runtime gate has blockers",
                        "result": {
                            "contract": "source-governance-runtime-gate-v1",
                            "summary": {"blocking_count": 1, "readiness_status": "review_required"},
                            "blocking_rows": [{"code": "source_guarded_apply_review_required"}],
                        },
                        "created_at": "2026-07-08T00:00:02Z",
                    },
                    metadata={"project_id": "book-a"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="agent-run-source-gate-book-a",
                    type="agent_run",
                    title="Agent run with source gate evidence",
                    content={
                        "run_id": "agent-run-source-gate-book-a",
                        "agent_type": "context",
                        "operation": "build-context-bundle",
                        "status": "succeeded",
                        "input_assets": [],
                        "output_assets": [],
                        "contract_id": "context-contract",
                        "permissions": {},
                        "started_at": "2026-07-08T00:00:02Z",
                        "finished_at": "2026-07-08T00:00:03Z",
                        "evidence": {
                            "source_governance_runtime_gate": {
                                "status": "failed",
                                "blocking": True,
                                "gate_result_path": "data/runs/source-governance-runtime-gate-book-a.json",
                                "readiness_report_path": "data/runs/source-readiness.json",
                                "summary": {"blocking_count": 1},
                            }
                        },
                    },
                    metadata={"project_id": "book-a"},
                )
            )
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Chapter runtime growth profile",
                    content={
                        "snapshot_kind": "chapter_runtime_growth_profile",
                        "contract": "chapter-runtime-growth-profile-v1",
                        "status": "review_required",
                        "project_id": "book-a",
                        "snapshot_at": "2026-07-08T00:00:03Z",
                        "summary": {
                            "chapter_run_count": 2,
                            "max_linked_asset_ref_count": 132,
                            "average_linked_asset_ref_count": 72.5,
                            "estimated_compacted_write_savings": 12,
                            "referenced_asset_type_counts": {"draft_chapter": 4},
                            "repeated_asset_type_counts": {"draft_chapter": 4},
                        },
                        "throughput": {"chapter_run_count": 2, "chapter_count": 2, "compact_run_count": 1, "full_run_count": 1},
                        "quality": {
                            "runtime_growth_status": "review_required",
                            "high_growth_run_count": 1,
                            "missing_runtime_policy_count": 0,
                            "max_linked_asset_ref_count": 132,
                            "average_linked_asset_ref_count": 72.5,
                        },
                        "task_health": {"blocking_drift_count": 0, "review_required_count": 1, "estimated_compacted_write_savings": 12},
                        "agent_health": {"chapter_runtime_profiler": "review_required", "chapter_run_count": 2, "node_run_count": 1, "trace_span_count": 1},
                        "storage_health": {"referenced_asset_type_counts": {"draft_chapter": 4}, "repeated_asset_type_counts": {"draft_chapter": 4}},
                        "runtime_rows": [{"run_id": "run-1", "risk_level": "high", "linked_asset_ref_count": 132}],
                        "evidence_paths": ["data/runs/run-1.json"],
                        "operator_action": "review high-fanout run",
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "chapter_runtime_growth_profile"},
                )
            )
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Chapter runtime growth hotspot ledger",
                    content={
                        "snapshot_kind": "chapter_runtime_growth_hotspot_ledger",
                        "contract": "chapter-runtime-growth-hotspot-ledger-v1",
                        "status": "review_required",
                        "project_id": "book-a",
                        "snapshot_at": "2026-07-08T00:00:04Z",
                        "summary": {
                            "chapter_run_count": 2,
                            "hotspot_family_count": 2,
                            "high_risk_hotspot_count": 1,
                            "max_linked_asset_ref_count": 132,
                            "estimated_compacted_write_savings": 12,
                        },
                        "hotspot_rows": [
                            {
                                "artifact_family": "draft_chapter",
                                "total_count": 40,
                                "run_count": 2,
                                "max_per_run": 28,
                                "risk_level": "medium",
                            }
                        ],
                        "run_hotspot_rows": [{"run_id": "run-1", "linked_asset_ref_count": 132}],
                        "operator_action": "inspect hotspot rows",
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "chapter_runtime_growth_hotspot_ledger"},
                )
            )
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Chapter runtime growth write policy candidate plan",
                    content={
                        "snapshot_kind": "chapter_runtime_growth_write_policy_candidate_plan",
                        "contract": "chapter-runtime-growth-write-policy-candidate-plan-v1",
                        "status": "review_required",
                        "project_id": "book-a",
                        "snapshot_at": "2026-07-08T00:00:05Z",
                        "summary": {
                            "hotspot_status": "review_required",
                            "candidate_action_count": 2,
                            "estimated_compacted_write_savings": 14,
                            "requires_operator_review": True,
                            "mutation_applied": False,
                            "runtime_policy_changed": False,
                        },
                        "candidate_actions": [
                            {
                                "action_id": "candidate-task_status_ref",
                                "artifact_family": "task_status_ref",
                                "requires_operator_approval": True,
                                "auto_apply": False,
                            }
                        ],
                        "safeguards": ["preserve failure evidence"],
                        "rollback_criteria": ["rollback if evidence disappears"],
                        "operator_action": "review candidate actions",
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "chapter_runtime_growth_write_policy_candidate_plan"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="runtime-write-policy-approval",
                    type="approval_request",
                    title="Runtime write policy approval",
                    content={
                        "request_id": "runtime-write-policy-approval",
                        "status": "pending",
                        "scope": "agent",
                        "action": "approve_runtime_write_policy_candidate_plan",
                        "blocking": True,
                        "target": {
                            "target_type": "project_metric_snapshot",
                            "target_id": "chapter-runtime-growth-write-policy-candidate-plan",
                            "target_path": "data/runs/chapter-runtime-growth-write-policy-candidate-plan.json",
                        },
                    },
                    metadata={"project_id": "book-a", "asset_status": "pending", "blocking": True},
                )
            )
            storage.write_asset_auto(
                ProjectMetricSnapshot(
                    title="Chapter runtime growth approved apply plan",
                    content={
                        "snapshot_kind": "chapter_runtime_growth_approved_policy_apply_plan",
                        "contract": "chapter-runtime-growth-approved-policy-apply-plan-v1",
                        "status": "ready",
                        "project_id": "book-a",
                        "snapshot_at": "2026-07-08T00:00:06Z",
                        "summary": {
                            "approved": True,
                            "apply_allowed": True,
                            "policy_delta_count": 1,
                            "mutation_applied": False,
                            "runtime_policy_changed": False,
                        },
                        "policy_deltas": [{"artifact_family": "task_status_ref", "auto_apply": False}],
                        "operator_action": "review exact policy deltas",
                    },
                    metadata={"project_id": "book-a", "snapshot_kind": "chapter_runtime_growth_approved_policy_apply_plan"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="v1-acceptance-preflight-report",
                    type="long_chain_acceptance_report",
                    title="V1 acceptance with preflight manifest",
                    content={
                        "status": "failed",
                        "recommendation": "repair_runtime_growth_before_acceptance",
                        "unified_acceptance_preflight_manifest": {
                            "contract": "v1-unified-acceptance-preflight-manifest-v1",
                            "status": "review_required",
                            "enforced_failure_count": 0,
                            "missing_or_deferred_final_evidence_count": 2,
                            "required_evidence": [
                                {"key": "runtime_growth_threshold", "status": "passed"},
                                {"key": "source_governance_runtime", "status": "deferred"},
                            ],
                            "operator_action": "complete deferred final preflight evidence before unified acceptance",
                        },
                    },
                    metadata={"project_id": "book-a"},
                )
            )
            run_context_governance_coverage_gate(storage, project_id="book-a", environment="production")
            build_production_governance_evidence_drift_report(storage, project_id="book-a", persist=True)
            run_production_governance_drift_gate(storage, project_id="book-a", environment="production")

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-a")

            self.assertEqual(snapshot["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(snapshot["asset"]["metadata"]["snapshot_kind"], "novel_os_cockpit")
            self.assertEqual(snapshot["asset"]["content"]["throughput"]["chapter_plan_count"], 1)
            self.assertIn("cockpit", snapshot["asset"]["content"])
            self.assertIn("rollback_recovery_entry", snapshot["asset"]["content"]["cockpit"])
            self.assertIn("production_control_console", snapshot["asset"]["content"])
            self.assertIn("chapter_queue", snapshot["asset"]["content"]["production_control_console"])
            self.assertIn("gate_status_board", snapshot["asset"]["content"]["production_control_console"])
            self.assertEqual(snapshot["asset"]["content"]["v1_artifact_coverage"]["summary"]["latest_coverage_ratio"], 1.0)
            self.assertEqual(snapshot["asset"]["content"]["v1_artifact_coverage"]["summary"]["full_coverage_run_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["approval_gate_summary"]["summary"]["request_count"], 3)
            self.assertEqual(snapshot["asset"]["content"]["approval_gate_summary"]["blocking_pending_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["artifact_coverage"]["latest_chapter"], 1)
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["context_governance"], "passed")
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["context_governance_gate"]["status"], "passed")
            self.assertTrue(snapshot["asset"]["content"]["runtime_governance"]["context_governance_gate"]["path"])
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["production_governance_drift"]["status"], "passed")
            self.assertTrue(snapshot["asset"]["content"]["runtime_governance"]["production_governance_drift"]["path"])
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["production_governance_drift_gate"]["status"], "passed")
            self.assertTrue(snapshot["asset"]["content"]["runtime_governance"]["production_governance_drift_gate"]["gate_result_path"])
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["approval_gate_summary"]["pending_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["context_governance_gate"]["status"], "passed")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["production_governance_drift"]["status"], "passed")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["production_governance_drift_gate"]["status"], "passed")
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["workflow_governance"]["status"], "missing")
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["workflow_governance"]["preflight_count"], 0)
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["workflow_governance"]["dead_letter_count"], 0)
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["approval_request_caller_readiness"]["status"], "partial")
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["approval_request_caller_readiness"]["summary"]["covered_dimension_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["approval_request_caller_readiness"]["summary"]["missing_dimension_count"], 3)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["approval_request_caller_readiness_status"], "partial")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["approval_request_missing_caller_count"], 3)
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["source_guarded_apply_readiness"]["status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["source_guarded_apply_readiness"]["summary"]["stale_pending_regeneration_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["source_guarded_apply_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["source_stale_pending_regeneration_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["source_governance_runtime_gate_status"], "failed")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["source_governance_runtime_evidence_status"], "failed")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["source_governance_runtime_evidence_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_hotspot_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_hotspot_family_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_write_policy_plan_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_write_policy_candidate_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_write_policy_approval_status"], "pending")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_approved_apply_plan_status"], "ready")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_high_run_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["chapter_runtime_growth_max_ref_count"], 132)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["unified_acceptance_preflight_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["unified_acceptance_preflight_missing_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["unified_acceptance_preflight_unready_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["quality"]["unified_acceptance_preflight_repair_plan_status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["quality"]["unified_acceptance_preflight_repair_action_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["workflow_governance"], "missing")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["approval_request_callers"], "partial")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["source_guarded_apply"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["source_governance_runtime"], "failed")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["source_governance_runtime_evidence"], "failed")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["runtime_growth"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["runtime_growth_hotspots"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["runtime_growth_write_policy_plan"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["runtime_growth_write_policy_approval"], "pending")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["runtime_growth_approved_apply_plan"], "ready")
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["unified_acceptance_preflight"], "review_required")
            self.assertEqual(
                snapshot["asset"]["content"]["production_control_console"]["repair_plan_summary"]["unified_acceptance_preflight"]["action_count"],
                1,
            )
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["workflow_governance"]["status"], "missing")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["approval_request_caller_readiness"]["status"], "partial")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["source_guarded_apply_readiness"]["status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["source_governance_runtime_gate"]["status"], "failed")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["source_governance_runtime_evidence"]["latest"]["gate_result_path"], "data/runs/source-governance-runtime-gate-book-a.json")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["chapter_runtime_growth"]["summary"]["max_linked_asset_ref_count"], 132)
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["chapter_runtime_growth_hotspot_ledger"]["hotspot_rows"][0]["artifact_family"], "draft_chapter")
            self.assertEqual(
                snapshot["asset"]["content"]["cockpit"]["chapter_runtime_growth_write_policy_candidate_plan"]["candidate_actions"][0]["artifact_family"],
                "task_status_ref",
            )
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["chapter_runtime_growth_write_policy_approval"]["target_path"], "data/runs/chapter-runtime-growth-write-policy-candidate-plan.json")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["chapter_runtime_growth_approved_policy_apply_plan"]["summary"]["policy_delta_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["unified_acceptance_preflight"]["status"], "review_required")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["unified_acceptance_preflight"]["required_evidence"][0]["key"], "runtime_growth_threshold")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["unified_acceptance_preflight"]["unready_final_evidence"][0]["key"], "source_governance_runtime")
            repair_plan = snapshot["asset"]["content"]["cockpit"]["unified_acceptance_preflight"]["operator_repair_plan"]
            self.assertEqual(repair_plan["status"], "review_required")
            self.assertEqual(repair_plan["actions"][0]["repair_group"], "source_governance")
            self.assertFalse(repair_plan["repair_executed"])
            self.assertEqual(pending_approval["asset"]["content"]["scope"], "publish")

    def test_project_cockpit_surfaces_workflow_governance_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            preflight = {
                "status": "failed",
                "gate_status": "failed",
                "blocking": True,
                "message": "workflow governance drift has 1 blocking row(s)",
                "environment": "production",
                "mode": "strict",
                "gate_result_path": "data/runs/workflow-governance-gate.json",
                "drift_report_path": "data/runs/workflow-governance-report.json",
                "summary": {"drift_count": 1, "blocking_drift_count": 1},
            }
            storage.write_asset_auto(
                BaseAsset(
                    id="workflow-governance-gate",
                    type="gate_result",
                    title="Workflow governance drift gate",
                    content={
                        "gate_id": "workflow-governance-gate",
                        "gate_kind": "workflow_governance_drift",
                        "status": "failed",
                        "target_paths": ["data/runs/workflow-definition.json"],
                        "blocking": True,
                        "message": preflight["message"],
                        "result": {"summary": preflight["summary"], "report_path": preflight["drift_report_path"]},
                        "created_at": "2026-07-08T00:00:00Z",
                    },
                    metadata={"project_id": "book-a"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="workflow-run-governance-failed",
                    type="workflow_run",
                    title="Workflow governance failed run",
                    content={
                        "run_id": "workflow-run-governance-failed",
                        "workflow_id": "workflow-definition",
                        "workflow_definition_path": "data/runs/workflow-definition.json",
                        "status": "failed",
                        "outputs": [],
                        "node_runs": [],
                        "agent_runs": [],
                        "run_log": [],
                        "blocked": {"node_id": "chapter-production-start", "status": "failed", "gate_kind": "workflow_governance_drift"},
                        "error_message": preflight["message"],
                        "recovery_instruction": "repair workflow governance evidence before resume",
                        "lineage": {"workflow_governance_preflight": preflight},
                    },
                    metadata={"project_id": "book-a"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="ready-node-workflow-governance-dead-letter",
                    type="ready_node_queue",
                    title="Dead-lettered workflow governance node",
                    content={
                        "queue_id": "ready-node-workflow-governance-dead-letter",
                        "workflow_run_id": "workflow-run-governance-failed",
                        "workflow_run_path": "data/runs/workflow-run-governance-failed.json",
                        "node_id": "chapter-production-start",
                        "status": "dead_letter",
                        "last_error": preflight["message"],
                        "dead_letter_evidence": {
                            "workflow_governance_preflight": preflight,
                            "resume_workflow_run_path": "data/runs/workflow-run-governance-resume.json",
                        },
                    },
                    metadata={"project_id": "book-a"},
                )
            )

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-a")
            content = snapshot["asset"]["content"]
            workflow_governance = content["runtime_governance"]["workflow_governance"]

            self.assertEqual(workflow_governance["status"], "blocked")
            self.assertEqual(workflow_governance["gate_status"], "failed")
            self.assertEqual(workflow_governance["failed_preflight_count"], 1)
            self.assertEqual(workflow_governance["dead_letter_count"], 1)
            self.assertEqual(workflow_governance["latest_preflight"]["gate_status"], "failed")
            self.assertEqual(workflow_governance["dead_letters"][0]["gate_result_path"], preflight["gate_result_path"])
            self.assertIn("data/runs/workflow-governance-gate.json", workflow_governance["evidence_paths"])
            self.assertIn(preflight["drift_report_path"], workflow_governance["evidence_paths"])
            self.assertEqual(content["quality"]["workflow_governance_status"], "blocked")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["workflow_governance"], "blocked")
            self.assertEqual(content["production_control_console"]["workflow_governance"]["dead_letter_count"], 1)
            self.assertEqual(content["cockpit"]["workflow_governance"]["status"], "blocked")

    def test_project_cockpit_surfaces_clean_workflow_governance_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            preflight = {
                "status": "passed",
                "gate_status": "passed",
                "blocking": False,
                "message": "workflow governance drift gate passed",
                "environment": "production",
                "mode": "strict",
                "gate_result_path": "data/runs/workflow-governance-clean-gate.json",
                "drift_report_path": "data/runs/workflow-governance-clean-report.json",
                "summary": {"drift_count": 0, "blocking_drift_count": 0},
            }
            storage.write_asset_auto(
                BaseAsset(
                    id="workflow-governance-clean-gate",
                    type="gate_result",
                    title="Clean workflow governance drift gate",
                    content={
                        "gate_id": "workflow-governance-clean-gate",
                        "gate_kind": "workflow_governance_drift",
                        "status": "passed",
                        "target_paths": ["data/runs/workflow-definition-clean.json"],
                        "blocking": False,
                        "message": preflight["message"],
                        "result": {"summary": preflight["summary"], "report_path": preflight["drift_report_path"]},
                        "created_at": "2026-07-08T00:00:00Z",
                    },
                    metadata={"project_id": "book-clean"},
                )
            )
            storage.write_asset_auto(
                BaseAsset(
                    id="workflow-run-governance-clean",
                    type="workflow_run",
                    title="Workflow governance clean run",
                    content={
                        "run_id": "workflow-run-governance-clean",
                        "workflow_id": "workflow-definition-clean",
                        "workflow_definition_path": "data/runs/workflow-definition-clean.json",
                        "status": "completed",
                        "outputs": ["data/runs/chapter-production-clean.json"],
                        "node_runs": [],
                        "agent_runs": [],
                        "run_log": [],
                        "blocked": {},
                        "error_message": "",
                        "recovery_instruction": "",
                        "lineage": {"workflow_governance_preflight": preflight},
                    },
                    metadata={"project_id": "book-clean"},
                )
            )

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-clean")
            content = snapshot["asset"]["content"]
            workflow_governance = content["runtime_governance"]["workflow_governance"]

            self.assertEqual(workflow_governance["status"], "passed")
            self.assertEqual(workflow_governance["gate_status"], "passed")
            self.assertEqual(workflow_governance["preflight_count"], 1)
            self.assertEqual(workflow_governance["failed_preflight_count"], 0)
            self.assertEqual(workflow_governance["dead_letter_count"], 0)
            self.assertEqual(workflow_governance["latest_preflight"]["gate_status"], "passed")
            self.assertIn(preflight["drift_report_path"], workflow_governance["evidence_paths"])
            self.assertEqual(content["quality"]["workflow_governance_status"], "passed")
            self.assertEqual(content["production_control_console"]["gate_status_board"]["workflow_governance"], "passed")
            self.assertEqual(content["cockpit"]["workflow_governance"]["status"], "passed")

    def test_multi_book_daily_production_report_tracks_isolation_and_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(ChapterPlan(title="A plan", content={"chapter": 1}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(ChapterPlan(title="B plan", content={"chapter": 1}, metadata={"project_id": "book-b"}))

            report = build_multi_book_daily_production_report(storage, project_ids=["book-a", "book-b"], provider_budget=20.0)

            content = report["asset"]["content"]
            self.assertEqual(report["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(content["multi_book_scheduler"]["provider_budget_plan"]["per_book_budget"], 10.0)
            self.assertEqual(content["agent_health"]["capacity_plan"]["provider_parallelism"], 2)
            self.assertTrue(all(row["memory_isolation"] == "project_id_scoped" for row in content["multi_book_scheduler"]["books"]))

    def test_multi_book_report_includes_cost_quality_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(ChapterPlan(title="A plan", content={"chapter": 1}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(DraftChapter(title="A draft", content={"chapter": 1, "text": "原创章节"}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(BaseAsset(type="evaluation_result", title="A eval", content={"overall_score": 0.82, "recommendation": "pass"}, metadata={"project_id": "book-a"}))
            record_model_call_log(
                storage,
                provider="claude-code",
                model="codex",
                operation="draft",
                status="succeeded",
                usage={"total_tokens": 1200},
                cost={"amount": 0.42, "currency": "USD", "source": "test"},
                project_id="book-a",
            )

            report = build_multi_book_daily_production_report(storage, project_ids=["book-a"], provider_budget=5.0)
            dashboard = report["asset"]["content"]["cost_quality_dashboard"]

            self.assertEqual(dashboard["total_cost"], 0.42)
            self.assertEqual(dashboard["books"][0]["project_id"], "book-a")
            self.assertEqual(dashboard["books"][0]["latest_quality_score"], 0.82)
            self.assertEqual(dashboard["books"][0]["cost_quality_ratio"], round(0.82 / 0.42, 4))

    def test_multi_book_production_schedule_allocates_lanes_budget_and_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(ChapterPlan(title="A plan", content={"chapter": 1}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(ChapterPlan(title="B plan", content={"chapter": 1}, metadata={"project_id": "book-b"}))
            storage.write_asset_auto(BaseAsset(type="review_issue", title="B blocker", content={"issue_id": "i1", "severity": "critical", "blocking": True, "status": "open"}, metadata={"project_id": "book-b"}))

            schedule = build_multi_book_production_schedule(storage, project_ids=["book-a", "book-b"], provider_budget=12.0, max_parallel_books=2)
            content = schedule["asset"]["content"]

            self.assertEqual(schedule["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(content["multi_book_parallel_schedule"]["provider_budget_plan"]["per_book_budget"], 6.0)
            self.assertEqual(content["multi_book_parallel_schedule"]["parallel_lanes"][0]["lane"], 1)
            self.assertEqual(content["multi_book_parallel_schedule"]["parallel_lanes"][0]["project_id"], "book-a")
            self.assertEqual(content["multi_book_parallel_schedule"]["books"][1]["recommended_action"], "resolve_blocking_review_issues")
            self.assertTrue(content["multi_book_parallel_schedule"]["cross_book_contamination_guard"]["enabled"])


if __name__ == "__main__":
    unittest.main()
