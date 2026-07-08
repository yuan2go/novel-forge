from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.chapter_runtime_growth import (
    build_chapter_runtime_growth_approved_policy_apply_plan,
    build_chapter_runtime_growth_hotspot_ledger,
    build_chapter_runtime_growth_profile,
    build_chapter_runtime_growth_write_policy_candidate_plan,
    request_chapter_runtime_growth_write_policy_approval,
    run_chapter_runtime_growth_threshold_gate,
)
from novel_forge.modules.permission_center import list_approval_requests
from novel_forge.modules.permission_center import resolve_approval_request
from novel_forge.schemas import BaseAsset
from novel_forge.storage.local import LocalStorage


class ChapterRuntimeGrowthTests(unittest.TestCase):
    def test_profile_reports_missing_without_chapter_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = build_chapter_runtime_growth_profile(storage, project_id="book-a", persist=False)

            self.assertEqual(result["status"], "missing")
            self.assertEqual(result["path"], "")
            self.assertEqual(result["summary"]["chapter_run_count"], 0)

    def test_profile_characterizes_compact_and_full_runtime_artifact_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_1 = self._write_asset(storage, "draft-1", "draft_chapter", project_id="book-a")
            draft_2 = self._write_asset(storage, "draft-2", "draft_chapter", project_id="book-a")
            draft_3 = self._write_asset(storage, "draft-3", "draft_chapter", project_id="book-a")
            draft_b = self._write_asset(storage, "draft-b", "draft_chapter", project_id="book-b")
            task_1 = self._write_asset(storage, "task-1", "task_status", project_id="book-a")
            task_2 = self._write_asset(storage, "task-2", "task_status", project_id="book-a")
            task_3 = self._write_asset(storage, "task-3", "task_status", project_id="book-a")
            task_4 = self._write_asset(storage, "task-4", "task_status", project_id="book-a")
            self._write_asset(storage, "node-run-compact", "node_run", project_id="book-a", content={"run_id": "run-compact"})
            self._write_asset(storage, "trace-compact", "trace_span", project_id="book-a", content={"trace_id": "run-compact"})
            self._write_chapter_run(
                storage,
                run_id="run-compact",
                chapter=1,
                task_status_mode="compact",
                outputs={"draft_v0_path": draft_1, "final_draft_path": draft_2},
                steps={
                    "draft": {"task_status_paths": [task_1], "output_paths": [draft_1]},
                    "final": {"task_status_paths": [task_2], "output_paths": [draft_2]},
                },
            )
            self._write_chapter_run(
                storage,
                run_id="run-full",
                chapter=2,
                task_status_mode="full",
                outputs={"draft_v0_path": draft_2, "final_draft_path": draft_3},
                steps={
                    "draft": {"task_status_paths": [task_3], "output_paths": [draft_2]},
                    "final": {"task_status_paths": [task_4], "output_paths": [draft_3]},
                },
            )
            self._write_chapter_run(
                storage,
                run_id="run-book-b",
                chapter=1,
                task_status_mode="compact",
                outputs={"draft_v0_path": draft_b},
                steps={"draft": {"task_status_paths": [], "output_paths": [draft_b]}},
                project_id="book-b",
            )

            result = build_chapter_runtime_growth_profile(storage, project_id="book-a", persist=True)

            self.assertEqual(result["status"], "review_required")
            self.assertTrue(result["path"])
            self.assertEqual(result["summary"]["chapter_run_count"], 2)
            self.assertEqual(result["summary"]["estimated_compacted_write_savings"], 8)
            self.assertEqual(result["summary"]["referenced_asset_type_counts"]["draft_chapter"], 4)
            self.assertIn("draft_chapter", result["summary"]["repeated_asset_type_counts"])
            self.assertEqual({row["task_status_mode"] for row in result["runtime_rows"]}, {"compact", "full"})
            snapshot = storage.read_json(storage.root / result["path"])
            self.assertEqual(snapshot["type"], "project_metric_snapshot")
            self.assertEqual(snapshot["metadata"]["snapshot_kind"], "chapter_runtime_growth_profile")
            self.assertEqual(snapshot["content"]["task_health"]["review_required_count"], 1)

    def test_hotspot_ledger_identifies_artifact_families_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_1 = self._write_asset(storage, "hotspot-draft-1", "draft_chapter", project_id="book-a")
            draft_2 = self._write_asset(storage, "hotspot-draft-2", "draft_chapter", project_id="book-a")
            task_1 = self._write_asset(storage, "hotspot-task-1", "task_status", project_id="book-a")
            task_2 = self._write_asset(storage, "hotspot-task-2", "task_status", project_id="book-a")
            self._write_asset(storage, "hotspot-node-run", "node_run", project_id="book-a", content={"run_id": "hotspot-full"})
            self._write_asset(storage, "hotspot-trace-span", "trace_span", project_id="book-a", content={"trace_id": "hotspot-full"})
            self._write_chapter_run(
                storage,
                run_id="hotspot-compact",
                chapter=1,
                task_status_mode="compact",
                outputs={"draft_v0_path": draft_1},
                steps={"draft": {"task_status_paths": [task_1], "output_paths": [draft_1]}},
            )
            self._write_chapter_run(
                storage,
                run_id="hotspot-full",
                chapter=2,
                task_status_mode="full",
                outputs={"draft_v0_path": draft_1, "final_draft_path": draft_2},
                steps={
                    "draft": {"task_status_paths": [task_1], "output_paths": [draft_1]},
                    "final": {"task_status_paths": [task_2], "output_paths": [draft_2]},
                },
            )
            self._write_asset(
                storage,
                "hotspot-acceptance",
                "long_chain_acceptance_report",
                project_id="book-a",
                content={"output_counts": {"draft_chapter": 12, "review_issue": 8}},
            )

            result = build_chapter_runtime_growth_hotspot_ledger(storage, project_id="book-a", persist=True, top_n=10)

            self.assertEqual(result["status"], "review_required")
            self.assertTrue(result["path"])
            self.assertFalse(result["summary"]["chapter_production_executed"])
            self.assertFalse(result["summary"]["provider_proof_executed"])
            families = {row["artifact_family"]: row for row in result["hotspot_rows"]}
            self.assertIn("draft_chapter", families)
            self.assertIn("task_status_ref", families)
            self.assertIn("trace_span", families)
            self.assertEqual(result["run_hotspot_rows"][0]["run_id"], "hotspot-full")
            snapshot = storage.read_json(storage.root / result["path"])
            self.assertEqual(snapshot["type"], "project_metric_snapshot")
            self.assertEqual(snapshot["metadata"]["snapshot_kind"], "chapter_runtime_growth_hotspot_ledger")
            self.assertEqual(snapshot["content"]["acceptance_report_hotspot_rows"][0]["top_output_counts"]["draft_chapter"], 12)

    def test_write_policy_candidate_plan_is_reviewable_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = self._write_asset(storage, "policy-draft", "draft_chapter", project_id="book-a")
            task = self._write_asset(storage, "policy-task", "task_status", project_id="book-a")
            self._write_asset(storage, "policy-node-run", "node_run", project_id="book-a", content={"run_id": "policy-full"})
            self._write_asset(storage, "policy-trace-span", "trace_span", project_id="book-a", content={"trace_id": "policy-full"})
            self._write_chapter_run(
                storage,
                run_id="policy-full",
                chapter=3,
                task_status_mode="full",
                outputs={"draft_v0_path": draft},
                steps={"draft": {"task_status_paths": [task], "output_paths": [draft]}},
            )

            result = build_chapter_runtime_growth_write_policy_candidate_plan(storage, project_id="book-a", persist=True)

            self.assertEqual(result["status"], "review_required")
            self.assertTrue(result["path"])
            self.assertFalse(result["summary"]["mutation_applied"])
            self.assertFalse(result["summary"]["runtime_policy_changed"])
            self.assertFalse(result["summary"]["chapter_production_executed"])
            self.assertTrue(result["summary"]["requires_operator_review"])
            families = {row["artifact_family"] for row in result["candidate_actions"]}
            self.assertIn("task_status_ref", families)
            self.assertIn("node_run", families)
            self.assertIn("trace_span", families)
            snapshot = storage.read_json(storage.root / result["path"])
            self.assertEqual(snapshot["metadata"]["snapshot_kind"], "chapter_runtime_growth_write_policy_candidate_plan")
            self.assertTrue(snapshot["content"]["safeguards"])
            self.assertTrue(snapshot["content"]["rollback_criteria"])
            self.assertFalse(any(row["auto_apply"] for row in snapshot["content"]["candidate_actions"]))

    def test_write_policy_approval_request_is_required_before_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = self._write_asset(storage, "approval-policy-draft", "draft_chapter", project_id="book-a")
            task = self._write_asset(storage, "approval-policy-task", "task_status", project_id="book-a")
            self._write_chapter_run(
                storage,
                run_id="approval-policy-run",
                chapter=4,
                task_status_mode="full",
                outputs={"draft_v0_path": draft},
                steps={"draft": {"task_status_paths": [task], "output_paths": [draft]}},
            )

            result = request_chapter_runtime_growth_write_policy_approval(storage, project_id="book-a", environment="production")
            duplicate = request_chapter_runtime_growth_write_policy_approval(storage, project_id="book-a", environment="production")

            self.assertEqual(result["status"], "pending")
            self.assertTrue(result["approval_created"])
            self.assertFalse(result["mutation_applied"])
            self.assertFalse(result["runtime_policy_changed"])
            self.assertEqual(duplicate["status"], "pending")
            self.assertFalse(duplicate["approval_created"])
            approvals = list_approval_requests(storage, project_id="book-a", scope="agent")
            self.assertEqual(len(approvals), 1)
            content = approvals[0]["content"]
            self.assertEqual(content["action"], "approve_runtime_write_policy_candidate_plan")
            self.assertTrue(content["blocking"])
            self.assertIn("runtime_policy_update", content["required_before"])
            self.assertEqual(content["target"]["target_path"], result["plan"]["path"])

    def test_approved_policy_apply_plan_requires_approved_request_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = self._write_asset(storage, "apply-policy-draft", "draft_chapter", project_id="book-a")
            task = self._write_asset(storage, "apply-policy-task", "task_status", project_id="book-a")
            self._write_chapter_run(
                storage,
                run_id="apply-policy-run",
                chapter=5,
                task_status_mode="full",
                outputs={"draft_v0_path": draft},
                steps={"draft": {"task_status_paths": [task], "output_paths": [draft]}},
            )
            approval = request_chapter_runtime_growth_write_policy_approval(storage, project_id="book-a", environment="production")
            blocked = build_chapter_runtime_growth_approved_policy_apply_plan(storage, project_id="book-a", persist=True)
            resolve_approval_request(
                storage,
                approval["approval_request_path"],
                {"decision": "approved", "actor": "unit-test", "reason": "candidate plan reviewed", "project_id": "book-a"},
            )
            ready = build_chapter_runtime_growth_approved_policy_apply_plan(storage, project_id="book-a", persist=True)

            self.assertEqual(blocked["status"], "review_required")
            self.assertFalse(blocked["summary"]["apply_allowed"])
            self.assertEqual(ready["status"], "ready")
            self.assertTrue(ready["summary"]["approved"])
            self.assertTrue(ready["summary"]["apply_allowed"])
            self.assertFalse(ready["summary"]["mutation_applied"])
            self.assertFalse(ready["summary"]["runtime_policy_changed"])
            self.assertTrue(ready["asset"]["content"]["policy_deltas"])
            self.assertIn("runtime-growth-regression", ready["asset"]["content"]["required_regression_gates"])

    def test_threshold_gate_passes_clean_compact_runtime_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = self._write_asset(storage, "clean-draft", "draft_chapter", project_id="book-a")
            task = self._write_asset(storage, "clean-task", "task_status", project_id="book-a")
            self._write_chapter_run(
                storage,
                run_id="clean-run",
                chapter=1,
                task_status_mode="compact",
                outputs={"draft_v0_path": draft},
                steps={"draft": {"task_status_paths": [task], "output_paths": [draft]}},
            )

            result = run_chapter_runtime_growth_threshold_gate(storage, project_id="book-a", environment="production", max_linked_asset_refs=10)

            self.assertEqual(result["status"], "passed")
            self.assertFalse(result["blocking"])
            self.assertEqual(result["summary"]["blocking_count"], 0)
            self.assertEqual(result["gate_result"]["asset"]["content"]["gate_kind"], "chapter_runtime_growth_threshold")
            self.assertFalse(result["gate_result"]["asset"]["content"]["result"]["summary"]["chapter_production_executed"])

    def test_threshold_gate_warns_locally_and_fails_in_production_for_full_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = self._write_asset(storage, "full-draft", "draft_chapter", project_id="book-a")
            task = self._write_asset(storage, "full-task", "task_status", project_id="book-a")
            self._write_chapter_run(
                storage,
                run_id="full-run",
                chapter=2,
                task_status_mode="full",
                outputs={"draft_v0_path": draft},
                steps={"draft": {"task_status_paths": [task], "output_paths": [draft]}},
            )

            local_result = run_chapter_runtime_growth_threshold_gate(storage, project_id="book-a", environment="local", max_linked_asset_refs=10)
            production_result = run_chapter_runtime_growth_threshold_gate(storage, project_id="book-a", environment="production", max_linked_asset_refs=10)

            self.assertEqual(local_result["status"], "warning")
            self.assertFalse(local_result["blocking"])
            self.assertEqual(production_result["status"], "failed")
            self.assertTrue(production_result["blocking"])
            self.assertIn("chapter_runtime_full_mode", {row["code"] for row in production_result["blocking_rows"]})

    def test_threshold_gate_fails_closed_without_profile_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = run_chapter_runtime_growth_threshold_gate(storage, project_id="book-a", environment="production")

            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["blocking"])
            self.assertEqual(result["summary"]["profile_status"], "missing")
            self.assertIn("chapter_runtime_growth_profile_missing", {row["code"] for row in result["blocking_rows"]})

    def _write_asset(self, storage: LocalStorage, asset_id: str, asset_type: str, *, project_id: str, content: dict | None = None) -> str:
        path = storage.write_asset_auto(
            BaseAsset(
                id=asset_id,
                type=asset_type,
                title=asset_id,
                content=content or {"status": "available"},
                metadata={"project_id": project_id},
            )
        )
        return str(path.relative_to(storage.root))

    def _write_chapter_run(
        self,
        storage: LocalStorage,
        *,
        run_id: str,
        chapter: int,
        task_status_mode: str,
        outputs: dict[str, str],
        steps: dict[str, dict],
        project_id: str = "book-a",
    ) -> str:
        policy = {
            "policy_version": "chapter-production-runtime-artifact-policy-v1",
            "task_status_mode": task_status_mode,
            "task_status_recording": {"pending": task_status_mode == "full", "running": task_status_mode == "full", "completed": True, "failed": True},
            "node_run_recording": {"succeeded": task_status_mode == "full", "failed": True},
            "trace_recording": {"node_run_succeeded_span": task_status_mode == "full", "node_run_failed_span": True, "external_runtime_spans": True},
        }
        path = storage.write_asset_auto(
            BaseAsset(
                id=run_id,
                type="chapter_production_run",
                title=f"Chapter run {chapter}",
                content={
                    "run_id": run_id,
                    "status": "succeeded",
                    "chapter": chapter,
                    "current_step": "completed",
                    "outputs": outputs,
                    "steps": steps,
                    "control": {"task_status_mode": task_status_mode, "runtime_artifact_policy": policy},
                },
                metadata={"project_id": project_id},
            )
        )
        return str(path.relative_to(storage.root))


if __name__ == "__main__":
    unittest.main()
