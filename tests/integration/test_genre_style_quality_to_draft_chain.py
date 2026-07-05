from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.genre_os import build_genre_strategy_pack, run_genre_risk_gate
from novel_forge.modules.quality_eval import build_quality_rubric_pack, run_quality_gate, run_quality_suite
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample, run_style_drift_gate
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class GenreStyleQualityDraftChainTests(unittest.TestCase):
    def test_genre_style_quality_gates_produce_release_ready_evidence_for_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            genre = build_genre_strategy_pack(storage, genre="mystery", subgenre="police_procedural", project_id="p1")
            sample = ingest_style_sample(
                storage,
                sample_text=("案件目标、证据和冲突同时推进。然而新证据带来代价，下一章真相会继续逼近。主角必须选择。 " * 40),
                project_id="p1",
            )
            fp = extract_style_fingerprint(storage, sample_path=sample["path"])
            style = build_style_profile(storage, fingerprint_path=fp["path"], style_name="mystery terse")
            rubric = build_quality_rubric_pack(storage, genre_id="mystery", platform_id="local", style_profile_path=style["style_profile_path"])
            draft = DraftChapter(
                title="chapter",
                content={
                    "chapter": 1,
                    "text": ("案件目标、证据和冲突同时推进。然而新证据带来代价，下一章真相会继续逼近。主角必须选择。 " * 40),
                    "copyright_boundary": "original draft",
                },
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            genre_gate = run_genre_risk_gate(
                storage,
                strategy_pack_path=genre["genre_strategy_pack_path"],
                target_path=draft_path,
                evidence={"线索不可回溯": "mitigated", "反转靠新增设定": "mitigated"},
            )
            style_gate = run_style_drift_gate(storage, style_profile_path=style["style_profile_path"], target_path=draft_path)
            quality_report = run_quality_suite(storage, suite_type="opening_3", target_paths=[str(draft_path)], rubric_path=rubric["path"])
            quality_gate = run_quality_gate(storage, quality_report_path=quality_report["path"])

            self.assertEqual(genre_gate["asset"]["content"]["recommendation"], "passed")
            self.assertIn(style_gate["asset"]["content"]["drift_level"], {"low", "medium"})
            self.assertEqual(quality_gate["asset"]["content"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
