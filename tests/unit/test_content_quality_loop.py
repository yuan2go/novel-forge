from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.content_quality_loop import run_content_quality_loop
from novel_forge.modules.genre_os import build_genre_strategy_pack
from novel_forge.modules.style_os import build_style_profile, extract_style_fingerprint, ingest_style_sample
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class ContentQualityLoopTests(unittest.TestCase):
    def test_draft_quality_loop_runs_v7_gates_and_attaches_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            build_genre_strategy_pack(storage, genre="mystery", subgenre="police_procedural", project_id="p1")
            sample = ingest_style_sample(
                storage,
                project_id="p1",
                sample_text=("异常现场出现后，侦探先确认目标，再让证据和嫌疑关系同时推进。危险逼近，但每次反转都有代价。 " * 8),
                rights={"license": "project-owned", "allowed_usage": "style_parameter_extraction"},
            )
            fingerprint = extract_style_fingerprint(storage, sample_path=sample["path"])
            profile = build_style_profile(storage, fingerprint_path=fingerprint["path"])
            draft = DraftChapter(
                title="Ready mystery draft",
                content={
                    "chapter": 1,
                    "text": "\n".join(
                        [
                            "异常现场留下第一条误导线索，侦探检查指纹证据。",
                            "嫌疑人的关系和动机同时推进，新的证词逼近旧假设。",
                            "主角必须在危险逼近前证伪假设，新的真相钩子指向下一章。",
                        ]
                        * 18
                    ),
                    "copyright_boundary": "original fixture",
                },
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            result = run_content_quality_loop(
                storage,
                target_path=draft_path,
                stage="draft",
                genre_strategy_pack_path="",
                style_profile_path=profile["style_profile_path"],
                platform_id="local",
            )

            self.assertEqual(result["asset"]["type"], "content_quality_loop_report")
            self.assertIn(result["status"], {"passed", "passed_with_warnings"})
            step_names = [step["name"] for step in result["asset"]["content"]["steps"]]
            self.assertEqual(
                step_names,
                [
                    "genre_risk_gate",
                    "style_drift_gate",
                    "canon_graph_plugin_gate",
                    "readable_prose_gate",
                    "golden_opening_gate",
                    "mobile_reading_gate",
                    "chapter_economy_gate",
                    "character_pressure_gate",
                    "quality_rubric_pack",
                    "quality_suite",
                    "provider_quality_judge",
                    "quality_gate",
                ],
            )
            self.assertTrue(result["asset"]["content"]["evidence_paths"])
            self.assertTrue(result["asset"]["content"]["chapter_quality_trend_path"])
            trend = storage.read_json(storage.root / result["asset"]["content"]["chapter_quality_trend_path"])
            self.assertEqual(trend["type"], "chapter_quality_trend")
            self.assertEqual(trend["content"]["points"][0]["chapter_no"], 1)
            self.assertEqual(trend["content"]["points"][0]["content_quality_loop_status"], result["status"])
            updated = storage.read_json(draft_path)
            self.assertEqual(updated["metadata"]["content_quality_loop_path"], result["path"])
            self.assertEqual(updated["metadata"]["chapter_quality_trend_path"], result["asset"]["content"]["chapter_quality_trend_path"])
            self.assertEqual(updated["content"]["content_quality_loop"]["path"], result["path"])

    def test_readable_prose_gate_blocks_thin_draft_and_creates_repair_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft = DraftChapter(
                title="Thin draft",
                content={
                    "chapter": 1,
                    "text": "他想了很多事情。命运似乎很复杂。一切都很重要。然后故事继续。",
                    "copyright_boundary": "original fixture",
                },
                metadata={"project_id": "p-readable"},
            )
            draft_path = storage.write_asset_auto(draft)

            result = run_content_quality_loop(
                storage,
                target_path=draft_path,
                stage="draft",
                platform_id="local",
            )

            self.assertEqual(result["status"], "blocked")
            readable_step = next(step for step in result["asset"]["content"]["steps"] if step["name"] == "readable_prose_gate")
            self.assertEqual(readable_step["status"], "blocked")
            self.assertTrue(readable_step["review_issue_paths"])
            self.assertTrue(result["asset"]["content"]["revision_task_paths"])
            issue = storage.read_json(storage.root / readable_step["review_issue_paths"][0])
            self.assertEqual(issue["type"], "review_issue")
            self.assertEqual(issue["content"]["source_system"], "readable_prose_gate.v1")
            task = storage.read_json(storage.root / result["asset"]["content"]["revision_task_paths"][0])
            self.assertEqual(task["type"], "revision_task")
            self.assertEqual(task["metadata"]["source_system"], "readable_prose_gate.v1")

    def test_golden_opening_gate_blocks_weak_first_three_chapter_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            draft = DraftChapter(
                title="Weak opening",
                content={
                    "chapter": 1,
                    "text": ("他坐在屋里想了很多事情。命运似乎很复杂，一切都有某种重要意义。 " * 80),
                    "copyright_boundary": "original fixture",
                },
                metadata={"project_id": "p-opening"},
            )
            draft_path = storage.write_asset_auto(draft)

            result = run_content_quality_loop(
                storage,
                target_path=draft_path,
                stage="draft",
                platform_id="local",
            )

            self.assertEqual(result["status"], "blocked")
            opening_step = next(step for step in result["asset"]["content"]["steps"] if step["name"] == "golden_opening_gate")
            self.assertEqual(opening_step["status"], "blocked")
            self.assertTrue(opening_step["review_issue_paths"])
            self.assertTrue(opening_step["revision_task_path"])
            issue = storage.read_json(storage.root / opening_step["review_issue_paths"][0])
            self.assertEqual(issue["content"]["source_system"], "golden_opening_gate.v1")
            self.assertEqual(issue["content"]["issue_type"], "quality_gate")
            task = storage.read_json(storage.root / opening_step["revision_task_path"])
            self.assertEqual(task["metadata"]["source_system"], "golden_opening_gate.v1")
            self.assertIn("rewrite_opening_pressure", task["content"]["revision_strategy_plan"]["strategy_ids"])

    def test_production_quality_loop_blocks_missing_provider_judge(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            build_genre_strategy_pack(storage, genre="mystery", project_id="p1", environment="production", envelope=_envelope("genre_strategy", "genre_strategy_pack", "trace-genre"))
            sample = ingest_style_sample(
                storage,
                project_id="p1",
                sample_text=("异常现场、证据、嫌疑关系和真相钩子持续推进。 " * 20),
                rights={"license": "project-owned", "allowed_usage": "style_parameter_extraction"},
                environment="production",
                envelope=_envelope("style_ingestion", "style_sample", "trace-style-sample", raw_allowed=True),
            )
            fingerprint = extract_style_fingerprint(storage, sample_path=sample["path"], environment="production", envelope=_envelope("style_fingerprint", "style_fingerprint", "trace-style-fp"))
            profile = build_style_profile(storage, fingerprint_path=fingerprint["path"], environment="production", envelope=_envelope("style_profile", "style_profile", "trace-style-profile"))
            draft = DraftChapter(
                title="Production draft",
                content={"chapter": 1, "text": ("异常现场和证据链推进，嫌疑关系制造冲突，真相钩子持续压迫。 " * 30), "copyright_boundary": "original fixture"},
                metadata={"project_id": "p1"},
            )
            draft_path = storage.write_asset_auto(draft)

            result = run_content_quality_loop(
                storage,
                target_path=draft_path,
                stage="draft",
                style_profile_path=profile["style_profile_path"],
                environment="production",
                envelope=_envelope("content_quality_loop", "content_quality_loop_report", "trace-content-quality-loop"),
            )

            self.assertEqual(result["status"], "blocked")
            self.assertTrue(any(issue["dimension"] == "content_quality_loop.provider_quality_judge" for issue in result["asset"]["content"]["blocking_issues"]))


def _envelope(task_type: str, asset_type: str, trace_id: str, *, raw_allowed: bool = False) -> dict:
    return {
        "project_id": "p1",
        "task_type": task_type,
        "asset_type": asset_type,
        "actor_type": "service",
        "source": "test",
        "trace_id": trace_id,
        "source_policy": {"raw_source_text_allowed": raw_allowed, "generation_rag_allowed": False},
        "environment": "production",
    }


if __name__ == "__main__":
    unittest.main()
