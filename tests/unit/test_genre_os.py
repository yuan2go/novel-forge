from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.genre_os import build_genre_strategy_pack, inspect_genre_catalog, run_genre_risk_gate
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class GenreOSTests(unittest.TestCase):
    def test_strategy_pack_contains_context_contract_and_required_genre_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            result = build_genre_strategy_pack(storage, genre="悬疑", subgenre="刑侦", project_id="p1", platform_id="local")

            asset = result["asset"]
            content = asset["content"]
            self.assertEqual(asset["type"], "genre_strategy_pack")
            self.assertEqual(content["genre_id"], "mystery")
            self.assertIn("evidence_chain", content["required_systems"])
            self.assertFalse(content["context_contract"]["raw_reference_text_allowed"])
            self.assertIn("genre_strategy_pack", content["context_contract"]["allowed_context_asset_types"])

    def test_risk_gate_generates_review_issue_for_uncontrolled_longform_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            pack = build_genre_strategy_pack(storage, genre="科幻", subgenre="赛博朋克", project_id="p1")
            draft = DraftChapter(
                title="chapter",
                content={"chapter": 1, "text": "主角突然获得无限能源，突破所有物理限制。", "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            gate = run_genre_risk_gate(storage, strategy_pack_path=pack["genre_strategy_pack_path"], target_path=draft_path)

            self.assertEqual(gate["asset"]["type"], "genre_risk_gate")
            self.assertGreaterEqual(gate["asset"]["content"]["blocking_issue_count"], 1)
            self.assertTrue(gate["review_issues"])

    def test_catalog_covers_required_major_genres(self):
        catalog = inspect_genre_catalog()
        self.assertGreaterEqual(catalog["count"], 10)
        for genre in ["xuanhuan", "urban", "mystery", "sci_fi", "historical", "romance", "fantasy", "horror", "realist", "light_novel"]:
            self.assertIn(genre, catalog["genres"])


if __name__ == "__main__":
    unittest.main()
