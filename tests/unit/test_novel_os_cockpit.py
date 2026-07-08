from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.novel_os_cockpit import build_multi_book_daily_production_report, build_multi_book_production_schedule, build_project_cockpit_snapshot
from novel_forge.modules.permission_center import create_approval_request, resolve_approval_request
from novel_forge.modules.context_builder import run_context_governance_coverage_gate
from novel_forge.modules.production_governance import build_production_governance_evidence_drift_report
from novel_forge.modules.runtime_ledger import record_model_call_log
from novel_forge.modules.chapter_production_bus.service import V1_SEQUENCE_REQUIRED_OUTPUTS
from novel_forge.schemas import BaseAsset, ChapterPlan, DraftChapter
from novel_forge.storage.local import LocalStorage


class NovelOsCockpitTests(unittest.TestCase):
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
            run_context_governance_coverage_gate(storage, project_id="book-a", environment="production")
            build_production_governance_evidence_drift_report(storage, project_id="book-a", persist=True)

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
            self.assertEqual(snapshot["asset"]["content"]["approval_gate_summary"]["summary"]["request_count"], 2)
            self.assertEqual(snapshot["asset"]["content"]["approval_gate_summary"]["blocking_pending_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["artifact_coverage"]["latest_chapter"], 1)
            self.assertEqual(snapshot["asset"]["content"]["production_control_console"]["gate_status_board"]["context_governance"], "passed")
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["context_governance_gate"]["status"], "passed")
            self.assertTrue(snapshot["asset"]["content"]["runtime_governance"]["context_governance_gate"]["path"])
            self.assertEqual(snapshot["asset"]["content"]["runtime_governance"]["production_governance_drift"]["status"], "passed")
            self.assertTrue(snapshot["asset"]["content"]["runtime_governance"]["production_governance_drift"]["path"])
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["approval_gate_summary"]["pending_count"], 1)
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["context_governance_gate"]["status"], "passed")
            self.assertEqual(snapshot["asset"]["content"]["cockpit"]["production_governance_drift"]["status"], "passed")
            self.assertEqual(pending_approval["asset"]["content"]["scope"], "publish")

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
