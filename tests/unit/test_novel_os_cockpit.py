from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.novel_os_cockpit import build_multi_book_daily_production_report, build_project_cockpit_snapshot
from novel_forge.schemas import ChapterPlan, DraftChapter
from novel_forge.storage.local import LocalStorage


class NovelOsCockpitTests(unittest.TestCase):
    def test_project_cockpit_snapshot_is_schema_backed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset_auto(ChapterPlan(title="P1 plan", content={"chapter": 1}, metadata={"project_id": "book-a"}))
            storage.write_asset_auto(DraftChapter(title="P1 draft", content={"chapter": 1, "text": "原创章节"}, metadata={"project_id": "book-a"}))

            snapshot = build_project_cockpit_snapshot(storage, project_id="book-a")

            self.assertEqual(snapshot["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(snapshot["asset"]["metadata"]["snapshot_kind"], "novel_os_cockpit")
            self.assertEqual(snapshot["asset"]["content"]["throughput"]["chapter_plan_count"], 1)
            self.assertIn("cockpit", snapshot["asset"]["content"])
            self.assertIn("rollback_recovery_entry", snapshot["asset"]["content"]["cockpit"])

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


if __name__ == "__main__":
    unittest.main()
