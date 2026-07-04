from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle
from novel_forge.modules.longform_recap import evaluate_recap_trigger, run_longform_recap
from novel_forge.modules.longform_stability import create_arc_plan, create_canon_database, create_longform_artifacts_for_draft
from novel_forge.modules.mkaos import create_knowledge_card, create_usage_binding
from novel_forge.modules.review_issue import create_review_issue, list_review_issues
from novel_forge.schemas import ChapterPlan, DraftChapter
from novel_forge.storage.local import LocalStorage


class LongformRecapAgentTests(unittest.TestCase):
    def test_twelve_chapter_recap_writes_governance_assets_without_raw_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            latest_path = _longform_fixture(storage)
            latest = storage.read_asset(latest_path)
            create_review_issue(
                storage,
                {
                    "project_id": "recap-p",
                    "target_asset_id": latest.id,
                    "target_asset_type": "draft_chapter",
                    "issue_type": "foreshadowing_drop",
                    "severity": "high",
                    "message": "chapter 12 has unresolved clue payoff risk",
                },
            )

            trigger = evaluate_recap_trigger(storage, project_id="recap-p")
            result = run_longform_recap(storage, {"project_id": "recap-p", "chapter_count": 12})
            report = result["asset"]
            writeback = result["writeback"]

            self.assertTrue(trigger["should_trigger"])
            self.assertIn("ten_chapter_interval", trigger["reasons"])
            self.assertEqual(report["type"], "longform_recap_report")
            self.assertEqual(report["content"]["chapter_range"]["end"], 12)
            self.assertEqual(writeback["status"], "applied")
            self.assertTrue(writeback["canon_patch_path"])
            self.assertTrue(writeback["character_state_ledger_path"])
            self.assertTrue(writeback["arc_plan_path"])
            self.assertTrue(writeback["foreshadowing_graph_path"])
            self.assertTrue(writeback["review_issue_paths"])
            self.assertTrue(writeback["revision_task_path"])
            self.assertGreater(writeback["mkaos_usage_event_count"], 0)
            self.assertTrue(writeback["mkaos_feedback_paths"])
            self.assertEqual(result["loop"]["status"], "succeeded")
            _assert_no_raw_text_payload(self, report["content"])

            issues = list_review_issues(storage, project_id="recap-p", limit=50)
            self.assertTrue(any(issue["content"]["source_system"] == "longform_recap.agent" for issue in issues))

    def test_next_chapter_context_can_read_recap_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            _longform_fixture(storage)
            recap = run_longform_recap(storage, {"project_id": "recap-p", "chapter_count": 12})
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Chapter 13 plan",
                    content={
                        "chapter": 13,
                        "objective": "continue after longform recap governance",
                        "beats": ["read recap", "resolve clue", "advance arc"],
                        "hook": "the old tax proof returns",
                    },
                    metadata={"project_id": "recap-p"},
                ),
            )

            context_plan = create_context_build_plan(
                storage,
                plan_path,
                query="Longform recap chapters continuity risks next chapter",
                top_k=20,
                token_budget=3000,
                context_profile="chapter_generation",
            )
            bundle = create_context_bundle(storage, context_plan["path"], selected_asset_paths=[recap["path"]], final_confirmed=True)
            selected_paths = {item.get("path") for item in bundle["asset"]["content"]["selected_assets"]}

            self.assertIn(recap["path"], selected_paths)
            _assert_no_raw_text_payload(self, bundle["asset"]["content"])


def _longform_fixture(storage: LocalStorage) -> Path:
    create_canon_database(
        storage,
        entities=[
            {"entity_id": "azhao", "entity_type": "character", "canonical_name": "阿照", "aliases": [], "forbidden_aliases": ["沈砚"], "role": "protagonist", "status": "active"},
            {"entity_id": "night_archive", "entity_type": "organization", "canonical_name": "夜档司", "aliases": [], "forbidden_aliases": [], "role": "core_org", "status": "active"},
        ],
        project_id="recap-p",
    )
    create_arc_plan(
        storage,
        arc_id="arc-tax",
        title="旧城隐税卷",
        chapter_range="1-20",
        arc_question="谁在复活旧城隐税机制？",
        protagonist_goal="查清隐税机制",
        villain_goal="逼夜档司承接旧债",
        required_payoffs=["解释竹筹来源"],
        forbidden_expansion=["不要新开无关宗门线"],
        project_id="recap-p",
    )
    knowledge = create_knowledge_card(
        storage,
        {
            "project_id": "recap-p",
            "concept_name": "长篇复盘节奏",
            "discipline": "叙事工程",
            "knowledge_type": "longform_control",
            "core_explanation": "每十章需要检查设定漂移、伏笔偿还和读者回报节奏。",
        },
    )
    create_usage_binding(storage, knowledge["asset"]["id"], {"flow": "review", "usage_type": "required", "input_role": "recap_rule", "priority": 10})
    latest_path = None
    for chapter in range(1, 13):
        draft_path = storage.write_asset(
            "drafts",
            DraftChapter(
                title=f"Chapter {chapter}",
                content={
                    "chapter": chapter,
                    "text": f"第{chapter}章。阿照在夜档司追查竹筹和旧城隐税。线索{chapter}指向旧税契，师父旧债仍压在账上。",
                    "copyright_boundary": "project-owned longform recap fixture",
                },
                metadata={"project_id": "recap-p"},
            ),
        )
        create_longform_artifacts_for_draft(storage, draft_path)
        latest_path = draft_path
    assert latest_path is not None
    return latest_path


def _assert_no_raw_text_payload(testcase: unittest.TestCase, value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "raw_text":
                testcase.fail("raw_text payload must not be present in recap or context assets")
            if key in {"source_chunk_raw_text_allowed", "raw_source_text_allowed"}:
                testcase.assertFalse(bool(child), f"{key} must not allow raw source text")
            _assert_no_raw_text_payload(testcase, child)
        return
    if isinstance(value, list):
        for child in value:
            _assert_no_raw_text_payload(testcase, child)
        return
    if isinstance(value, str):
        testcase.assertNotIn("source_chunk.raw_text", value)


if __name__ == "__main__":
    unittest.main()
