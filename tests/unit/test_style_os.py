from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample, run_style_drift_gate
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class StyleOSTests(unittest.TestCase):
    def test_style_sample_raw_text_is_source_isolated_and_profile_uses_abstract_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            sample = ingest_style_sample(
                storage,
                sample_text="雨落在长街上。他想起旧案，心里一沉。\"走。\"她说。 " * 30,
                project_id="p1",
                rights={"license": "owned", "allowed_usage": "style_parameter_extraction"},
            )
            self.assertFalse(sample["asset"]["metadata"]["use_in_generation_rag"])
            fp = extract_style_fingerprint(storage, sample_path=sample["path"])
            profile = build_style_profile(storage, fingerprint_path=fp["path"], style_name="p1 style")

            self.assertEqual(profile["asset"]["type"], "style_profile")
            self.assertEqual(profile["asset"]["content"]["source_boundary"]["allowed_usage"], "parameter_only")
            self.assertIn("style_generation_policy_path", profile)
            self.assertIn("style_review_rule_path", profile)

    def test_style_drift_gate_writes_review_issue_and_rewrite_task_for_high_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            sample = ingest_style_sample(storage, sample_text="短句。对话。行动。代价。 " * 50, project_id="p1")
            fp = extract_style_fingerprint(storage, sample_path=sample["path"])
            profile = build_style_profile(storage, fingerprint_path=fp["path"], style_name="short style")
            draft = DraftChapter(
                title="long chapter",
                content={
                    "chapter": 1,
                    "text": "这是一段非常漫长的叙述，它不断铺陈背景、解释情绪、重复抽象判断，并且不禁让空气仿佛凝固。 " * 30,
                    "copyright_boundary": "original draft",
                },
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            report = run_style_drift_gate(storage, style_profile_path=profile["style_profile_path"], target_path=draft_path)

            self.assertEqual(report["asset"]["type"], "style_drift_report")
            self.assertIn(report["asset"]["content"]["drift_level"], {"medium", "high", "critical"})
            self.assertTrue(report["review_issues"])
            self.assertTrue(report["style_rewrite_task_path"])

    def test_style_drift_gate_passes_matching_profile_without_rewrite_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            sample_text = "短句。对话。行动。代价。 " * 50
            sample = ingest_style_sample(storage, sample_text=sample_text, project_id="p1")
            fp = extract_style_fingerprint(storage, sample_path=sample["path"])
            profile = build_style_profile(storage, fingerprint_path=fp["path"], style_name="short style")
            draft = DraftChapter(
                title="matching chapter",
                content={"chapter": 1, "text": sample_text, "copyright_boundary": "original draft"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            report = run_style_drift_gate(storage, style_profile_path=profile["style_profile_path"], target_path=draft_path)

            self.assertEqual(report["asset"]["content"]["drift_level"], "low")
            self.assertEqual(report["review_issues"], [])
            self.assertEqual(report["style_rewrite_task_path"], "")


if __name__ == "__main__":
    unittest.main()
