from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.chapter_runtime_growth import build_chapter_runtime_growth_profile
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
