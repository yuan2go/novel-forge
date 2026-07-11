from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.write_budget import WriteBudgetExceeded


class WriteBudgetRuntimeTests(unittest.TestCase):
    def test_storage_budget_counts_asset_and_json_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            with storage.write_budget({"max_file_writes": 2, "max_asset_writes": 1}) as budget:
                storage.write_asset("drafts", DraftChapter(title="one", content={"chapter": 1, "text": "body"}, metadata={"project_id": "budget-p"}))
                storage.write_json("data/indexes/one.json", {"status": "ok"})
                self.assertEqual(budget.metrics["file_writes"], 2)
                self.assertEqual(budget.metrics["asset_writes"], 1)

    def test_storage_budget_fails_closed_before_excess_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            with self.assertRaises(WriteBudgetExceeded) as raised:
                with storage.write_budget({"max_file_writes": 1, "max_scan_calls": 1}):
                    storage.write_json("data/indexes/one.json", {"status": "ok"})
                    storage.write_json("data/indexes/two.json", {"status": "blocked"})
            self.assertEqual(raised.exception.metric, "file_writes")
            self.assertEqual(raised.exception.limit, 1)
            self.assertFalse((storage.root / "data/indexes/two.json").exists())

    def test_budget_tracks_scans_and_context_builds_with_explicit_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            with self.assertRaises(WriteBudgetExceeded) as raised:
                with storage.write_budget({"max_scan_calls": 1, "max_context_builds": 1}):
                    storage.list_json("drafts")
                    storage.list_json("drafts")
            self.assertEqual(raised.exception.metric, "scan_calls")
            with storage.write_budget({"max_scan_calls": 5, "max_context_builds": 1}) as budget:
                storage.record_budget_metric("context_builds")
                self.assertEqual(budget.metrics["context_builds"], 1)


if __name__ == "__main__":
    unittest.main()
