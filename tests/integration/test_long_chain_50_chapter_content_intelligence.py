from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.genre_os import build_genre_strategy_pack
from novel_forge.modules.long_chain_proof import run_long_chain_proof
from novel_forge.modules.quality_eval import build_quality_rubric_pack
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample
from novel_forge.storage.local import LocalStorage


class LongChain50ChapterContentIntelligenceTests(unittest.TestCase):
    def test_deterministic_50_chapter_content_intelligence_proof_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            genre = build_genre_strategy_pack(storage, genre="玄幻", subgenre="凡人流", project_id="p1")
            sample = ingest_style_sample(storage, sample_text="目标清晰。代价明确。冲突升级。新钩子出现。 " * 120, project_id="p1")
            fp = extract_style_fingerprint(storage, sample_path=sample["path"])
            style = build_style_profile(storage, fingerprint_path=fp["path"])
            rubric = build_quality_rubric_pack(storage, genre_id="xuanhuan", platform_id="local", style_profile_path=style["style_profile_path"])

            result = run_long_chain_proof(storage, project_id="p1", mode="deterministic_50")
            run = storage.read_json(result["run_path"])

            self.assertEqual(result["asset"]["content"]["status"], "ready")
            self.assertEqual(result["asset"]["content"]["recommendation"], "pass")
            self.assertEqual(run["content"]["target_chapter_count"], 50)
            self.assertEqual(run["content"]["recap_chapters"], [10, 20, 30, 40, 50])
            self.assertEqual(run["content"]["volume_review_chapters"], [30])
            self.assertTrue(genre["genre_strategy_pack_path"])
            self.assertTrue(style["style_profile_path"])
            self.assertTrue(rubric["path"])


if __name__ == "__main__":
    unittest.main()
