from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing.quality_gates import record_release_quality_gates
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class ReleaseQualityGateTests(unittest.TestCase):
    def test_production_blocks_duplicate_body_with_durable_content_quality_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            text = "主角必须在城门关闭前交出证据，却选择承担追兵的代价；新的线索迫使她进入下一章。" * 3
            _draft(storage, "Chapter 1", text, "quality-project")
            candidate = _draft(storage, "Chapter 2", text, "quality-project")

            gates = record_release_quality_gates(
                storage,
                target=storage.read_asset(candidate),
                target_path=candidate,
                chapter_audit=_passing_audit(),
                project_id="quality-project",
                workspace_path="",
                production=True,
            )

            self.assertEqual(gates["asset_integrity"]["status"], "passed")
            self.assertEqual(gates["content_quality"]["status"], "failed")
            self.assertTrue(gates["content_quality"]["blocking"])
            self.assertTrue(any(row["dimension"] == "body_uniqueness" for row in gates["content_quality"]["issues"]))
            self.assertEqual(storage.read_asset(gates["content_quality"]["path"]).type, "gate_result")

    def test_production_blocks_missing_body_as_asset_integrity_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            candidate = _draft(storage, "Empty", "", "quality-project")

            gates = record_release_quality_gates(
                storage,
                target=storage.read_asset(candidate),
                target_path=candidate,
                chapter_audit=_passing_audit(),
                project_id="quality-project",
                workspace_path="",
                production=True,
            )

            self.assertEqual(gates["asset_integrity"]["status"], "failed")
            self.assertTrue(any(row["dimension"] == "content_completeness" for row in gates["asset_integrity"]["issues"]))


def _draft(storage: LocalStorage, title: str, text: str, project_id: str):
    return storage.write_asset("drafts", DraftChapter(title=title, content={"chapter": 1, "text": text}, metadata={"project_id": project_id}))


def _passing_audit() -> dict:
    return {"content": {"gate_results": {"semantic_integrity": {"passed": True}, "stability_preflight": {"passed": True}}}}


if __name__ == "__main__":
    unittest.main()
