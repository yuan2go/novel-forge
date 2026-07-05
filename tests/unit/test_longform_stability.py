from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.publishing import create_publish_gate_report
from novel_forge.modules.longform_stability import (
    calibrate_longform_extraction,
    check_canon_consistency,
    create_arc_plan,
    create_canon_database,
    create_longform_artifacts_for_draft,
    evaluate_longform_stability_gate,
    longform_os_acceptance_report,
    longform_stability_dashboard,
    model_assisted_longform_extraction,
    sanitize_chapter_text,
    upsert_longform_control_asset,
)
from novel_forge.schemas import ArcPlan, DraftChapter
from novel_forge.storage.local import LocalStorage


class LongformStabilityTests(unittest.TestCase):
    def test_output_sanitizer_blocks_json_notes_and_extracts_text(self):
        result = sanitize_chapter_text('{"text":"第一章 正文。","notes":["策略"],"copyright_boundary":"meta"}')

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["text"], "第一章 正文。")
        self.assertTrue(any(issue["dimension"] == "json_wrapper_detected" for issue in result["issues"]))
        self.assertTrue(any("notes" in issue["message"] for issue in result["issues"]))

    def test_canon_database_fails_forbidden_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            canon = create_canon_database(
                storage,
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
                project_id="project1",
            )

            result = check_canon_consistency("沈砚站在井口。", canon["asset"])

            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["drift_report"]["forbidden_alias_hits"][0]["forbidden_alias"], "沈砚")

    def test_pattern_checker_fails_repeated_investigation_and_old_debt_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            for chapter in range(1, 4):
                draft = storage.write_asset(
                    "drafts",
                    DraftChapter(
                        title=f"Chapter {chapter}",
                        content={
                            "chapter": chapter,
                            "text": "阿照验灰，官署封存，按旧例反压。师父旧债又添一笔。",
                            "copyright_boundary": "test fixture original draft",
                        },
                        metadata={"project_id": "project1"},
                    ),
                )
                result = create_longform_artifacts_for_draft(storage, draft)

            pattern_report = storage.read_asset(result["chapter_pattern_report_path"])
            issues = pattern_report.content["similarity_checks"]

            self.assertTrue(any(issue["severity"] == "high" for issue in issues))
            self.assertTrue(any("investigation_method" in issue["message"] for issue in issues))

    def test_publish_gate_writes_revision_task_for_longform_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_canon_database(
                storage,
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
                project_id="project1",
            )
            storage.write_asset(
                "continuity",
                ArcPlan(
                    title="桥南隐税卷",
                    content={
                        "arc_id": "arc_03",
                        "title": "桥南隐税卷",
                        "chapter_range": "1-10",
                        "arc_question": "谁在复活旧城隐税机制？",
                        "protagonist_goal": "找到隐税机制源头",
                        "villain_goal": "逼夜档司承接旧债",
                        "required_payoffs": [],
                        "forbidden_expansion": [],
                    },
                    metadata={"project_id": "project1"},
                ),
            )
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Bad Chapter",
                    content={
                        "chapter": 1,
                        "text": '{"text":"沈砚验灰，官署封存，师父旧债又添一笔。","notes":["bad"]}',
                        "copyright_boundary": "test fixture original draft",
                    },
                    metadata={"project_id": "project1"},
                ),
            )

            gate_path = create_publish_gate_report(storage, draft)
            gate = storage.read_asset(gate_path)
            tasks = [storage.read_asset(path) for path in storage.list_json("reviews") if storage.read_json(path).get("type") == "revision_task"]

            self.assertEqual(gate.content["decision"], "blocked")
            self.assertFalse(gate.content["gates"]["longform_output_sanitizer_passed"])
            self.assertTrue(tasks)
            self.assertTrue(any(issue["dimension"] in {"json_wrapper_detected", "metadata_leak"} for issue in tasks[-1].content["issues"]))

    def test_evaluate_gate_requires_preexisting_chapter_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="No state",
                    content={"chapter": 2, "text": "阿照查旧井。", "copyright_boundary": "test fixture original draft"},
                    metadata={"project_id": "project1"},
                ),
            )

            result = evaluate_longform_stability_gate(storage, draft)

            self.assertEqual(result["status"], "fail")
            self.assertTrue(any(issue["dimension"] == "chapter_state" for issue in result["blocking_issues"]))

    def test_dashboard_and_acceptance_summarize_longform_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = _write_good_longform_fixture(storage)

            model_assisted_longform_extraction(storage, draft, use_model=False)
            dashboard = longform_stability_dashboard(storage, project_id="project1")
            acceptance = longform_os_acceptance_report(storage, project_id="project1", persist=False)

            self.assertGreaterEqual(dashboard["summary"]["chapter_state_count"], 1)
            self.assertIn("arc_visualization", dashboard)
            self.assertTrue(dashboard["arc_visualization"]["lanes"])
            self.assertGreaterEqual(acceptance["summary"]["check_count"], 10)
            self.assertTrue(any(check["key"] == "chapter_state_coverage" for check in acceptance["checks"]))

    def test_model_assisted_extraction_records_gateway_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = _write_good_longform_fixture(storage)

            result = model_assisted_longform_extraction(storage, draft, use_model=True)
            calls = [storage.read_asset(path) for path in storage.list_json("runs") if storage.read_json(path).get("type") == "model_call_log"]

            self.assertIn(result["model_gateway"]["status"], {"succeeded", "fallback"})
            if result["model_gateway"]["status"] == "succeeded":
                self.assertTrue(any(call.content["operation"] == "model_assisted_longform_extraction" for call in calls))

    def test_control_asset_upsert_and_extraction_calibration_persist_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft = _write_good_longform_fixture(storage)

            canon = upsert_longform_control_asset(
                storage,
                asset_type="canon_database",
                project_id="project1",
                content={"entities": [{"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照", "forbidden_aliases": ["沈砚"]}]},
            )
            calibration = calibrate_longform_extraction(
                storage,
                draft,
                expected={"characters": ["阿照"], "organizations": ["夜档司"], "clues": ["竹筹"], "motifs": ["税"]},
                use_model=False,
                persist=True,
            )
            report = storage.read_asset(calibration["path"])

            self.assertEqual(canon["asset"]["type"], "canon_database")
            self.assertEqual(report.type, "semantic_extraction_report")
            self.assertIn("confidence", report.content)
            self.assertIn("metrics", report.content)
            self.assertIn("evidence_spans", report.content)
            self.assertGreaterEqual(report.content["confidence"], 0)


def _write_good_longform_fixture(storage: LocalStorage) -> Path:
    create_canon_database(
        storage,
        entities=[
            {
                "entity_id": "azhao",
                "entity_type": "character",
                "canonical_name": "阿照",
                "aliases": [],
                "forbidden_aliases": ["沈砚", "江砚", "顾砚秋"],
                "role": "protagonist",
                "status": "active",
            },
            {
                "entity_id": "night_archive_office",
                "entity_type": "organization",
                "canonical_name": "夜档司",
                "aliases": [],
                "forbidden_aliases": ["北档房", "夜档库"],
                "role": "core_organization",
                "status": "active",
            },
        ],
        project_id="project1",
    )
    create_arc_plan(
        storage,
        arc_id="arc_03",
        title="桥南隐税卷",
        chapter_range="1-10",
        arc_question="谁在复活旧城隐税机制？",
        protagonist_goal="找到隐税机制源头",
        villain_goal="逼夜档司承接旧债",
        project_id="project1",
    )
    return storage.write_asset(
        "drafts",
        DraftChapter(
            title="Controlled Chapter",
            content={
                "chapter": 1,
                "text": "阿照在夜档司查到竹筹穿册。陶主簿把旧竹筹藏入铺牌，真相露出一角，旧城隐税机制被确认。",
                "copyright_boundary": "test fixture original draft",
            },
            metadata={"project_id": "project1"},
        ),
    )


if __name__ == "__main__":
    unittest.main()
