from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.model_router import create_model_route
from novel_forge.modules.evaluation_center import (
    build_golden_set,
    calibrate_provider_judge,
    create_calibrated_quality_rubric,
    create_human_annotation_asset,
)
from novel_forge.modules.quality_eval import (
    build_quality_calibration_readiness_report,
    build_quality_rubric_pack,
    run_provider_quality_judge,
    run_quality_calibration_readiness_gate,
    run_quality_gate,
    run_quality_suite,
)
from novel_forge.schemas import DraftChapter, ModelJudgeResult
from novel_forge.storage.local import LocalStorage


class ProviderJudgeAdapter:
    def review(self, payload: str, context: dict):
        return {
            "text": '{"recommendation":"ready","scores":{"genre_promise":91,"platform_rhythm":88,"style_adherence":86,"hook_strength":90,"conflict_density":87,"character_motivation":88,"canon_consistency":92,"ai_flavor_risk":85},"rationale":"provider-backed fixture judgment"}',
            "usage": {"input_tokens": 1200, "output_tokens": 240, "total_tokens": 1440, "usage_source": "provider_fixture"},
            "cost": {"amount": 0.012, "currency": "USD", "source": "provider_fixture"},
        }


class ExternalProviderJudgeAdapter:
    external_provider_evidence = {
        "external_call": True,
        "fixture": False,
        "provider_response_id": "resp-quality-1",
        "endpoint_host": "api.provider.example",
        "credential_ref": "env:QUALITY_PROVIDER_API_KEY",
        "rate_limit_policy": {"requests_per_minute": 60, "burst": 5},
    }

    def review(self, payload: str, context: dict):
        return {
            "text": '{"recommendation":"ready","scores":{"genre_promise":91,"platform_rhythm":88,"style_adherence":86,"hook_strength":90,"conflict_density":87,"character_motivation":88,"canon_consistency":92,"ai_flavor_risk":85},"rationale":"external provider contract judgment"}',
            "usage": {"input_tokens": 1200, "output_tokens": 240, "total_tokens": 1440, "usage_source": "external_provider"},
            "cost": {"amount": 0.012, "currency": "USD", "source": "external_provider"},
            "external_provider_evidence": self.external_provider_evidence,
        }


class QualityEvalV2Tests(unittest.TestCase):
    def test_quality_suite_ready_report_and_gate_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            rubric = build_quality_rubric_pack(storage, genre_id="mystery", platform_id="local")
            draft = DraftChapter(
                title="ready chapter",
                content={
                    "chapter": 1,
                    "text": ("目标、案件、关系和冲突同时推进。然而新证据带来代价，下一章真相会继续逼近。主角必须选择。 " * 35),
                    "copyright_boundary": "original draft",
                },
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            report = run_quality_suite(storage, suite_type="opening_3", target_paths=[str(draft_path)], rubric_path=rubric["path"])
            gate = run_quality_gate(storage, quality_report_path=report["path"])

            self.assertEqual(report["asset"]["type"], "opening_3_report")
            self.assertEqual(report["asset"]["content"]["recommendation"], "ready")
            self.assertEqual(gate["asset"]["content"]["status"], "passed")

    def test_low_quality_suite_generates_review_issue_and_revision_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft = DraftChapter(
                title="weak chapter",
                content={"chapter": 1, "text": "无聊。", "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            report = run_quality_suite(storage, suite_type="golden_10", target_paths=[str(draft_path)])

            self.assertEqual(report["asset"]["type"], "golden_10_report")
            self.assertIn(report["asset"]["content"]["recommendation"], {"needs_revision", "blocked"})
            self.assertTrue(report["review_issues"])
            self.assertTrue(report["revision_task_path"])

    def test_provider_quality_judge_records_route_model_call_cost_and_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            create_model_route(
                storage,
                task_type="quality_judge",
                provider="unit-provider",
                model_name="premium-judge-v1",
                project_id="p1",
                environment="development",
                approval_status="approved",
                approval_id="approval-quality-1",
                approved_by="qa-lead",
                production_provider_allowlist=["unit-provider"],
                max_cost_per_run=1.0,
            )
            rubric = build_quality_rubric_pack(
                storage,
                genre_id="mystery",
                platform_id="local",
                environment="development",
                envelope={
                    "project_id": "p1",
                    "task_type": "quality_eval",
                    "asset_type": "quality_rubric_pack",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-quality",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": True},
                    "environment": "development",
                },
            )
            draft = DraftChapter(
                title="provider judged chapter",
                content={
                    "chapter": 1,
                    "text": ("目标、案件、关系和冲突同时推进。然而新证据带来代价，下一章真相会继续逼近。主角必须选择。 " * 30),
                    "copyright_boundary": "original draft",
                },
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            report = run_provider_quality_judge(
                storage,
                suite_type="opening_3",
                target_paths=[str(draft_path)],
                rubric_path=rubric["path"],
                adapter=ProviderJudgeAdapter(),
                environment="development",
                envelope={
                    "project_id": "p1",
                    "task_type": "quality_judge",
                    "asset_type": "opening_3_report",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-provider-quality",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                    "environment": "development",
                },
                provider_runtime_guard={"max_total_tokens": 2000, "cost_profile": {"input_per_1k": 0.005, "output_per_1k": 0.015}},
            )
            gate = run_quality_gate(storage, quality_report_path=report["path"], environment="development", envelope={
                "project_id": "p1",
                "task_type": "quality_gate",
                "asset_type": "evaluation_gate",
                "actor_type": "service",
                "source": "test",
                "trace_id": "trace-provider-quality-gate",
                "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                "environment": "development",
            })

            self.assertEqual(report["asset"]["content"]["judge_policy"]["mode"], "provider_backed_judge")
            run_report = report["asset"]["content"]["provider_judge_run_report"]
            self.assertEqual(run_report["status"], "completed")
            self.assertEqual(run_report["provider"], "unit-provider")
            self.assertTrue(run_report["route_resolution_path"])
            self.assertTrue(run_report["model_call_log_path"])
            self.assertTrue(run_report["cost_ledger_path"])
            self.assertEqual(run_report["external_provider_proof_status"], "not_required")
            self.assertTrue(report["model_judge_result_paths"])
            judge = storage.read_json(storage.root / report["model_judge_result_paths"][0])
            evidence = judge["content"]["provider_evidence"]
            self.assertTrue(evidence["model_route_resolution_path"])
            self.assertTrue(evidence["model_call_log_path"])
            self.assertTrue(evidence["runtime_policy_path"])
            self.assertTrue(evidence["cost_ledger_path"])
            self.assertEqual(evidence["provider_policy"]["status"], "skipped")
            self.assertEqual(gate["asset"]["content"]["status"], "passed")

    def test_provider_quality_judge_external_proof_blocks_fixture_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            create_model_route(
                storage,
                task_type="quality_judge",
                provider="unit-provider",
                model_name="premium-judge-v1",
                project_id="p1",
                environment="production",
                approval_status="approved",
                approval_id="approval-quality-external-block",
                approved_by="qa-lead",
                production_provider_allowlist=["unit-provider"],
                max_cost_per_run=1.0,
            )
            rubric = _production_rubric(storage)
            draft_path = _ready_draft(storage)

            with self.assertRaisesRegex(RuntimeError, "legacy direct model adapters"):
                run_provider_quality_judge(
                    storage,
                    suite_type="opening_3",
                    target_paths=[str(draft_path)],
                    rubric_path=rubric["path"],
                    adapter=ProviderJudgeAdapter(),
                    environment="production",
                    envelope=_envelope("quality_judge", "opening_3_report", "trace-quality-external-block"),
                    provider_runtime_guard={"max_total_tokens": 2000},
                    require_external_provider_proof=True,
                )

    def test_provider_quality_judge_cannot_claim_external_proof_via_legacy_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            create_model_route(
                storage,
                task_type="quality_judge",
                provider="external-provider",
                model_name="premium-judge-v1",
                project_id="p1",
                environment="production",
                approval_status="approved",
                approval_id="approval-quality-external-pass",
                approved_by="qa-lead",
                production_provider_allowlist=["external-provider"],
                max_cost_per_run=1.0,
            )
            rubric = _production_rubric(storage)
            draft_path = _ready_draft(storage)

            with self.assertRaisesRegex(
                RuntimeError, "legacy direct model adapters"
            ):
                run_provider_quality_judge(
                    storage,
                    suite_type="opening_3",
                    target_paths=[str(draft_path)],
                    rubric_path=rubric["path"],
                    adapter=ExternalProviderJudgeAdapter(),
                    environment="production",
                    envelope=_envelope(
                        "quality_judge",
                        "opening_3_report",
                        "trace-quality-external-pass",
                    ),
                    provider_runtime_guard={"max_total_tokens": 2000},
                    require_external_provider_proof=True,
                )

    def test_production_quality_gate_blocks_local_heuristic_without_provider_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft = DraftChapter(
                title="local only chapter",
                content={"chapter": 1, "text": ("目标、案件、关系和冲突。下一章真相逼近。 " * 30), "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)
            report = run_quality_suite(storage, suite_type="opening_3", target_paths=[str(draft_path)])

            gate = run_quality_gate(
                storage,
                quality_report_path=report["path"],
                environment="production",
                envelope={
                    "project_id": "p1",
                    "task_type": "quality_gate",
                    "asset_type": "evaluation_gate",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-local-quality-gate",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                    "environment": "production",
                },
            )

            self.assertEqual(gate["asset"]["content"]["status"], "blocked")
            self.assertTrue(gate["asset"]["content"]["blocking"])
            self.assertEqual(gate["asset"]["content"]["provider_judge_required"], True)

    def test_eval_center_golden_set_human_annotation_and_provider_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft = DraftChapter(
                title="golden chapter",
                content={"chapter": 1, "text": "目标、冲突、情绪、反转、留存证据都完整。", "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)
            annotation = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="chief-editor",
                scores={"hook_strength": 0.9, "style_adherence": 0.8, "canon_consistency": 0.85},
                verdict="pass",
                comment="人工标注为高质量样本",
            )
            golden = build_golden_set(
                storage,
                name="Opening Golden Set",
                case_specs=[
                    {
                        "target_asset_path": str(draft_path),
                        "expected_scores": {"hook_strength": 0.88, "style_adherence": 0.82},
                        "annotation_path": annotation["path"],
                    }
                ],
                project_id="p1",
            )
            calibration = calibrate_provider_judge(
                storage,
                golden_set_path=golden["path"],
                provider_judge_results=[
                    {"target_asset_path": str(draft_path), "scores": {"hook_strength": 0.84, "style_adherence": 0.78}, "provider": "claude-code"}
                ],
                tolerance=0.08,
                project_id="p1",
            )

            self.assertEqual(annotation["asset"]["type"], "human_annotation")
            self.assertEqual(golden["asset"]["type"], "evaluation_suite")
            self.assertTrue(golden["asset"]["content"]["golden_set"]["enabled"])
            self.assertEqual(calibration["asset"]["type"], "evaluation_regression_report")
            self.assertEqual(calibration["asset"]["content"]["calibration_status"], "passed")
            self.assertLessEqual(calibration["asset"]["content"]["mean_absolute_error"], 0.08)

    def test_quality_calibration_readiness_missing_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            report = build_quality_calibration_readiness_report(storage, project_id="p-missing")

            self.assertEqual(report["status"], "missing")
            self.assertEqual(report["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(report["asset"]["metadata"]["snapshot_kind"], "quality_calibration_readiness")
            self.assertFalse(report["asset"]["content"]["task_health"]["provider_call_executed"])
            self.assertEqual(report["summary"]["model_judge_result_count"], 0)

    def test_quality_calibration_readiness_keeps_fixture_provider_unready(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            _write_fixture_model_judge(storage, project_id="p-fixture")

            report = build_quality_calibration_readiness_report(storage, project_id="p-fixture")

            self.assertEqual(report["status"], "review_required")
            self.assertEqual(report["summary"]["model_judge_result_count"], 1)
            self.assertEqual(report["summary"]["fixture_or_mock_provider_judge_count"], 1)
            self.assertEqual(report["summary"]["external_provider_judge_count"], 0)
            self.assertIn("external_provider_judge_proof", report["summary"]["missing_dimensions"])

    def test_quality_calibration_readiness_passes_with_external_human_golden_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            rubric = build_quality_rubric_pack(storage, genre_id="mystery", platform_id="local")
            run_quality_suite(storage, suite_type="opening_3", target_paths=[str(_ready_draft(storage, project_id="p-ready"))], rubric_path=rubric["path"])
            external_judge_path = _write_external_model_judge(storage, project_id="p-ready")
            draft_path = _ready_draft(storage, project_id="p-ready")
            annotation = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="chief-editor",
                scores={"hook_strength": 0.9, "style_adherence": 0.86},
                verdict="pass",
                comment="calibration-ready human annotation",
                project_id="p-ready",
            )
            golden = build_golden_set(
                storage,
                name="Readiness Golden Set",
                case_specs=[
                    {
                        "target_asset_path": str(draft_path),
                        "expected_scores": {"hook_strength": 0.9, "style_adherence": 0.86},
                        "annotation_path": annotation["path"],
                    }
                ],
                project_id="p-ready",
            )
            calibrate_provider_judge(
                storage,
                golden_set_path=golden["path"],
                provider_judge_results=[
                    {
                        "target_asset_path": str(draft_path),
                        "scores": {"hook_strength": 0.9, "style_adherence": 0.86},
                        "provider": "external-provider",
                        "model_judge_path": str(external_judge_path),
                    }
                ],
                tolerance=0.08,
                project_id="p-ready",
            )

            report = build_quality_calibration_readiness_report(storage, project_id="p-ready")

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["summary"]["external_provider_judge_count"], 1)
            self.assertEqual(report["summary"]["human_annotation_count"], 1)
            self.assertEqual(report["summary"]["golden_set_count"], 1)
            self.assertEqual(report["summary"]["passed_provider_calibration_count"], 1)
            self.assertEqual(report["summary"]["missing_dimension_count"], 0)
            self.assertTrue(report["path"])

    def test_quality_calibration_readiness_gate_fails_closed_in_production_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            gate = run_quality_calibration_readiness_gate(storage, project_id="p-missing", environment="production")

            self.assertEqual(gate["status"], "failed")
            self.assertTrue(gate["blocking"])
            self.assertEqual(gate["summary"]["readiness_status"], "missing")
            self.assertFalse(gate["summary"]["provider_call_executed"])
            self.assertFalse(gate["summary"]["chapter_acceptance_executed"])
            self.assertEqual(gate["gate_result"]["asset"]["content"]["gate_kind"], "quality_calibration_readiness_gate")
            self.assertEqual(gate["gate_result"]["asset"]["content"]["status"], "failed")
            self.assertTrue(gate["gate_result"]["asset"]["content"]["blocking"])

    def test_quality_calibration_readiness_gate_warns_locally_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            gate = run_quality_calibration_readiness_gate(storage, project_id="p-missing", environment="local")

            self.assertEqual(gate["status"], "warning")
            self.assertFalse(gate["blocking"])
            self.assertEqual(gate["summary"]["readiness_status"], "missing")
            self.assertEqual(gate["gate_result"]["asset"]["content"]["status"], "warning")

    def test_quality_calibration_readiness_gate_passes_with_external_human_golden_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            rubric = build_quality_rubric_pack(storage, genre_id="mystery", platform_id="local")
            draft_path = _ready_draft(storage, project_id="p-ready")
            run_quality_suite(storage, suite_type="opening_3", target_paths=[str(draft_path)], rubric_path=rubric["path"])
            external_judge_path = _write_external_model_judge(storage, project_id="p-ready")
            annotation = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="chief-editor",
                scores={"hook_strength": 0.9, "style_adherence": 0.86},
                verdict="pass",
                comment="calibration-ready human annotation",
                project_id="p-ready",
            )
            golden = build_golden_set(
                storage,
                name="Readiness Golden Set",
                case_specs=[
                    {
                        "target_asset_path": str(draft_path),
                        "expected_scores": {"hook_strength": 0.9, "style_adherence": 0.86},
                        "annotation_path": annotation["path"],
                    }
                ],
                project_id="p-ready",
            )
            calibrate_provider_judge(
                storage,
                golden_set_path=golden["path"],
                provider_judge_results=[
                    {
                        "target_asset_path": str(draft_path),
                        "scores": {"hook_strength": 0.9, "style_adherence": 0.86},
                        "provider": "external-provider",
                        "model_judge_path": str(external_judge_path),
                    }
                ],
                tolerance=0.08,
                project_id="p-ready",
            )

            gate = run_quality_calibration_readiness_gate(storage, project_id="p-ready", environment="production")

            self.assertEqual(gate["status"], "passed")
            self.assertFalse(gate["blocking"])
            self.assertEqual(gate["summary"]["readiness_status"], "passed")
            self.assertEqual(gate["summary"]["external_provider_judge_count"], 1)
            self.assertEqual(gate["gate_result"]["asset"]["content"]["status"], "passed")

    def test_human_calibration_produces_a_versioned_threshold_rubric(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft_path = _ready_draft(storage, project_id="p-calibrated")
            first = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="editor-a",
                annotator_role="editor",
                scores={"hook_strength": 0.92, "style_adherence": 0.88},
                verdict="pass",
                project_id="p-calibrated",
            )
            second = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="editor-b",
                annotator_role="editor",
                scores={"hook_strength": 0.88, "style_adherence": 0.84},
                verdict="pass",
                project_id="p-calibrated",
            )
            golden = build_golden_set(
                storage,
                name="Calibrated Golden Set",
                case_specs=[
                    {
                        "target_asset_path": str(draft_path),
                        "annotation_paths": [first["path"], second["path"]],
                        "expected_verdict": "pass",
                    }
                ],
                project_id="p-calibrated",
            )
            calibration = calibrate_provider_judge(
                storage,
                golden_set_path=golden["path"],
                provider_judge_results=[
                    {
                        "target_asset_path": str(draft_path),
                        "scores": {"hook_strength": 0.90, "style_adherence": 0.86},
                        "provider": "external-provider",
                    }
                ],
                project_id="p-calibrated",
            )

            report = calibration["asset"]["content"]
            self.assertEqual(report["calibration_status"], "passed")
            self.assertEqual(report["human_calibration"]["annotated_case_count"], 1)
            self.assertEqual(report["human_calibration"]["annotator_count_max"], 2)
            self.assertGreaterEqual(report["human_calibration"]["mean_agreement_score"], 0.8)
            self.assertEqual(report["threshold_recommendation"]["labelled_ready_case_count"], 1)

            rubric = build_quality_rubric_pack(storage, genre_id="mystery", platform_id="local")
            calibrated = create_calibrated_quality_rubric(storage, rubric_path=rubric["path"], calibration_report_path=calibration["path"], project_id="p-calibrated")
            calibrated_content = calibrated["asset"]["content"]
            self.assertEqual(calibrated_content["threshold_calibration"]["status"], "passed")
            self.assertEqual(calibrated_content["calibration_ref"], calibration["path"])
            self.assertEqual(calibrated_content["judge_policy"]["threshold_source"], "human_calibrated")
            self.assertNotEqual(calibrated_content["rubric_version"], rubric["asset"]["content"].get("rubric_version", "v1"))

    def test_production_provider_judge_can_require_calibrated_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            create_model_route(
                storage,
                task_type="quality_judge",
                provider="unit-provider",
                model_name="premium-judge-v1",
                project_id="p1",
                environment="production",
                approval_status="approved",
                approval_id="approval-quality-calibrated",
                approved_by="qa-lead",
                production_provider_allowlist=["unit-provider"],
                max_cost_per_run=1.0,
            )
            draft_path = _ready_draft(storage, project_id="p1")
            second_draft_path = _ready_draft(storage, project_id="p1")
            annotation = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="chief-editor",
                scores={"hook_strength": 0.9, "style_adherence": 0.86},
                verdict="pass",
                project_id="p1",
            )
            second_same_annotation = create_human_annotation_asset(
                storage,
                target_asset_path=str(draft_path),
                annotator="review-editor",
                scores={"hook_strength": 0.88, "style_adherence": 0.84},
                verdict="pass",
                project_id="p1",
            )
            second_annotation = create_human_annotation_asset(
                storage,
                target_asset_path=str(second_draft_path),
                annotator="review-editor",
                scores={"hook_strength": 0.88, "style_adherence": 0.84},
                verdict="pass",
                project_id="p1",
            )
            golden = build_golden_set(
                storage,
                name="Production Threshold Golden Set",
                case_specs=[
                    {
                        "target_asset_path": str(draft_path),
                        "expected_scores": {"hook_strength": 0.9, "style_adherence": 0.86},
                        "annotation_paths": [annotation["path"], second_same_annotation["path"]],
                        "expected_verdict": "pass",
                    },
                    {
                        "target_asset_path": str(second_draft_path),
                        "expected_scores": {"hook_strength": 0.88, "style_adherence": 0.84},
                        "annotation_path": second_annotation["path"],
                        "expected_verdict": "pass",
                    },
                ],
                project_id="p1",
            )
            calibration = calibrate_provider_judge(
                storage,
                golden_set_path=golden["path"],
                provider_judge_results=[
                    {
                        "target_asset_path": str(draft_path),
                        "scores": {"hook_strength": 0.9, "style_adherence": 0.86},
                        "provider": "unit-provider",
                    },
                    {
                        "target_asset_path": str(second_draft_path),
                        "scores": {"hook_strength": 0.88, "style_adherence": 0.84},
                        "provider": "unit-provider",
                    },
                ],
                project_id="p1",
            )
            rubric = _production_rubric(storage)
            calibrated = create_calibrated_quality_rubric(
                storage,
                rubric_path=rubric["path"],
                calibration_report_path=calibration["path"],
                project_id="p1",
            )

            with self.assertRaisesRegex(
                RuntimeError, "legacy direct model adapters"
            ):
                run_provider_quality_judge(
                    storage,
                    suite_type="opening_3",
                    target_paths=[str(draft_path), str(second_draft_path)],
                    rubric_path=calibrated["path"],
                    adapter=ProviderJudgeAdapter(),
                    environment="production",
                    envelope=_envelope(
                        "quality_judge",
                        "opening_3_report",
                        "trace-quality-calibrated",
                    ),
                    provider_runtime_guard={"max_total_tokens": 2000},
                    require_calibrated_thresholds=True,
                )

    def test_provider_calibration_missing_case_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft_path = _ready_draft(storage, project_id="p-missing-provider")
            golden = build_golden_set(
                storage,
                name="Missing Provider Result Golden Set",
                case_specs=[
                    {
                        "target_asset_path": str(draft_path),
                        "expected_scores": {"hook_strength": 0.9},
                        "expected_verdict": "pass",
                    }
                ],
                project_id="p-missing-provider",
            )

            calibration = calibrate_provider_judge(
                storage,
                golden_set_path=golden["path"],
                provider_judge_results=[],
                project_id="p-missing-provider",
            )

            self.assertEqual(calibration["asset"]["content"]["calibration_status"], "needs_calibration")
            self.assertEqual(calibration["asset"]["content"]["comparisons"][0]["status"], "missing_provider_result")


def _production_rubric(storage: LocalStorage) -> dict:
    return build_quality_rubric_pack(
        storage,
        genre_id="mystery",
        platform_id="local",
        environment="production",
        envelope=_envelope("quality_eval", "quality_rubric_pack", "trace-quality-rubric"),
    )


def _ready_draft(storage: LocalStorage, *, project_id: str = "p1") -> Path:
    draft = DraftChapter(
        title="provider judged chapter",
        content={
            "chapter": 1,
            "text": ("目标、案件、关系和冲突同时推进。然而新证据带来代价，下一章真相会继续逼近。主角必须选择。 " * 30),
            "copyright_boundary": "original draft",
        },
        metadata={"project_id": project_id},
    )
    return storage.write_asset_auto(draft)


def _envelope(task_type: str, asset_type: str, trace_id: str) -> dict:
    return {
        "project_id": "p1",
        "task_type": task_type,
        "asset_type": asset_type,
        "actor_type": "service",
        "source": "test",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
        "environment": "production",
    }


def _write_fixture_model_judge(storage: LocalStorage, *, project_id: str) -> Path:
    asset = ModelJudgeResult(
        title="Fixture model judge",
        tags=["quality-eval-v2", "model-judge", "fixture"],
        content={
            "judge_id": "judge-fixture",
            "target_asset_id": "draft-fixture",
            "rubric_id": "rubric-fixture",
            "scores": {"overall": 88},
            "recommendation": "ready",
            "provider_evidence": {
                "provider": "mock",
                "model": "mock-model",
                "provider_policy": {"status": "passed", "mock_provider_fixture_mode": True},
                "approval_evidence": {"approved": True},
                "external_provider_proof": {"status": "blocked"},
            },
        },
        metadata={"project_id": project_id},
    )
    return storage.write_asset_auto(asset)


def _write_external_model_judge(storage: LocalStorage, *, project_id: str) -> Path:
    asset = ModelJudgeResult(
        title="External model judge",
        tags=["quality-eval-v2", "model-judge", "external-provider"],
        content={
            "judge_id": "judge-external",
            "target_asset_id": "draft-external",
            "rubric_id": "rubric-external",
            "scores": {"overall": 90},
            "recommendation": "ready",
            "provider_evidence": {
                "provider": "external-provider",
                "model": "premium-judge-v1",
                "model_route_resolution_path": "data/runs/model-route-external.json",
                "model_call_log_path": "data/runs/model-call-external.json",
                "runtime_policy_path": "data/runs/runtime-policy-external.json",
                "cost_ledger_path": "data/runs/cost-ledger-external.json",
                "provider_policy": {"status": "passed", "mock_provider_fixture_mode": False},
                "approval_evidence": {"approved": True, "approval_id": "approval-external"},
                "external_provider_proof": {"status": "passed", "path": "data/runs/external-provider-proof.json"},
            },
        },
        metadata={"project_id": project_id},
    )
    return storage.write_asset_auto(asset)


if __name__ == "__main__":
    unittest.main()
