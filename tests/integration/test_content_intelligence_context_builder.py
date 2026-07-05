from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import create_context_build_plan
from novel_forge.modules.genre_os import build_genre_strategy_pack
from novel_forge.modules.quality_eval import build_quality_rubric_pack
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class ContentIntelligenceContextBuilderTests(unittest.TestCase):
    def test_context_builder_can_select_genre_style_quality_evidence_without_raw_style_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            genre = build_genre_strategy_pack(storage, genre="mystery", subgenre="police_procedural", project_id="p1")
            sample = ingest_style_sample(storage, sample_text="短句。行动。证据。反转。 " * 80, project_id="p1")
            fp = extract_style_fingerprint(storage, sample_path=sample["path"])
            style = build_style_profile(storage, fingerprint_path=fp["path"])
            rubric = build_quality_rubric_pack(storage, genre_id="mystery", platform_id="local", style_profile_path=style["style_profile_path"])
            draft = DraftChapter(
                title="target",
                content={"chapter": 1, "text": "案件目标、证据和冲突推进。", "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            plan = create_context_build_plan(storage, draft_path, query="mystery style quality evidence", top_k=20)
            candidate_types = {item.get("type") for item in plan["asset"]["content"]["candidate_assets"]}

            self.assertIn("genre_strategy_pack", candidate_types)
            self.assertIn("style_generation_policy", candidate_types)
            self.assertIn("quality_rubric_pack", candidate_types)
            self.assertNotIn("style_sample", candidate_types)
            self.assertTrue(genre["genre_strategy_pack_path"])
            self.assertTrue(rubric["path"])


if __name__ == "__main__":
    unittest.main()
