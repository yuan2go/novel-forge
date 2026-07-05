from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.model_router import create_model_route
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_provider_quality_judge, run_quality_gate, run_quality_suite
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class ProviderJudgeAdapter:
    def review(self, payload: str, context: dict):
        return {
            "text": '{"recommendation":"ready","scores":{"genre_promise":91,"platform_rhythm":88,"style_adherence":86,"hook_strength":90,"conflict_density":87,"character_motivation":88,"canon_consistency":92,"ai_flavor_risk":85},"rationale":"provider-backed fixture judgment"}',
            "usage": {"input_tokens": 1200, "output_tokens": 240, "total_tokens": 1440, "usage_source": "provider_fixture"},
            "cost": {"amount": 0.012, "currency": "USD", "source": "provider_fixture"},
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
                environment="production",
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
                environment="production",
                envelope={
                    "project_id": "p1",
                    "task_type": "quality_eval",
                    "asset_type": "quality_rubric_pack",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-quality",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": True},
                    "environment": "production",
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
                environment="production",
                envelope={
                    "project_id": "p1",
                    "task_type": "quality_judge",
                    "asset_type": "opening_3_report",
                    "actor_type": "service",
                    "source": "test",
                    "trace_id": "trace-provider-quality",
                    "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                    "environment": "production",
                },
                provider_runtime_guard={"max_total_tokens": 2000, "cost_profile": {"input_per_1k": 0.005, "output_per_1k": 0.015}},
            )
            gate = run_quality_gate(storage, quality_report_path=report["path"], environment="production", envelope={
                "project_id": "p1",
                "task_type": "quality_gate",
                "asset_type": "evaluation_gate",
                "actor_type": "service",
                "source": "test",
                "trace_id": "trace-provider-quality-gate",
                "source_policy": {"raw_source_text_allowed": False, "generation_rag_allowed": False},
                "environment": "production",
            })

            self.assertEqual(report["asset"]["content"]["judge_policy"]["mode"], "provider_backed_judge")
            self.assertTrue(report["model_judge_result_paths"])
            judge = storage.read_json(storage.root / report["model_judge_result_paths"][0])
            evidence = judge["content"]["provider_evidence"]
            self.assertTrue(evidence["model_route_resolution_path"])
            self.assertTrue(evidence["model_call_log_path"])
            self.assertTrue(evidence["runtime_policy_path"])
            self.assertTrue(evidence["cost_ledger_path"])
            self.assertEqual(evidence["provider_policy"]["status"], "passed")
            self.assertEqual(gate["asset"]["content"]["status"], "passed")

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


if __name__ == "__main__":
    unittest.main()
