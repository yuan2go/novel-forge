from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.editor_chief import build_editor_chief_snapshot
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database, model_assisted_longform_extraction
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage
from tests.unit.legacy_compatibility import legacy_settings


class EditorChiefConsoleTests(unittest.TestCase):
    def test_snapshot_answers_editorial_control_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = _seed_editorial_project(storage)
            model_assisted_longform_extraction(storage, draft_path, use_model=False)
            create_review_issue(
                storage,
                {
                    "project_id": "chief-p",
                    "target_asset_path": str(draft_path.relative_to(storage.root)),
                    "issue_type": "character_drift",
                    "severity": "critical",
                    "blocking": True,
                    "message": "人物动机突然改写，必须先修。",
                    "fix_suggestion": "回到上一章动机链，补足代价和选择。",
                    "source_system": "unit.editor_chief",
                },
            )

            snapshot = build_editor_chief_snapshot(storage, project_id="chief-p")

            self.assertEqual(snapshot["status"], "ready")
            self.assertEqual(snapshot["executive_decision"]["decision"], "pause_for_revision")
            self.assertTrue(snapshot["executive_decision"]["must_pause"])
            self.assertGreaterEqual(snapshot["overall_health"]["blocking_issue_count"], 1)
            self.assertIn(snapshot["arc_progress"]["status"], {"healthy", "warning", "blocked"})
            self.assertEqual(snapshot["character_drift"]["status"], "blocked")
            self.assertIn("chapter_range", snapshot["next_10_chapter_strategy"])
            self.assertTrue(snapshot["blocking_repair_queue"]["issues"])
            self.assertIn("publish_gate", snapshot["control_links"])

    def test_product_api_exposes_editor_chief_snapshot(self):
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")

        from novel_forge.api.app import create_app
        from novel_forge.infrastructure.settings import IndustrialSettings

        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(legacy_settings(root=Path(tmp).resolve())))
            response = client.get("/product/editor-chief/snapshot")

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "ready")
            self.assertIn("executive_decision", response.json())


def _seed_editorial_project(storage: LocalStorage) -> Path:
    create_canon_database(
        storage,
        project_id="chief-p",
        entities=[
            {
                "entity_id": "azhao",
                "entity_type": "character",
                "canonical_name": "阿照",
                "aliases": [],
                "forbidden_aliases": ["沈砚"],
                "role": "protagonist",
                "status": "active",
            }
        ],
    )
    create_arc_plan(
        storage,
        arc_id="tax-arc",
        title="旧税契主线",
        chapter_range="1-10",
        arc_question="谁在复活旧税契？",
        protagonist_goal="查清旧税契源头",
        villain_goal="拖延归档并嫁祸夜档司",
        required_payoffs=["解释竹筹来源"],
        project_id="chief-p",
    )
    return storage.write_asset(
        "drafts",
        DraftChapter(
            title="Chapter 1",
            content={
                "chapter": 1,
                "text": "阿照在夜档司查到竹筹穿册。官署封存旧税契，师父旧债逼她承担代价。竹筹指向旧税契责任人，主线问题被推到台前。",
                "copyright_boundary": "project-owned unit fixture",
            },
            metadata={"project_id": "chief-p"},
        ),
    )


if __name__ == "__main__":
    unittest.main()
