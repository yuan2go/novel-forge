from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters import MockModelAdapter
from novel_forge.modules.agent_runs import (
    create_agent_rollback_report,
    create_agent_sla_report,
    guard_agent_action,
    start_agent_run,
)
from novel_forge.modules.continuity_graph import build_continuity_graph, create_chapter_continuity_report, create_chapter_stability_preflight_report, create_continuity_graph_snapshot
from novel_forge.modules.editor import apply_editor_patch, create_draft_diff_report, create_editor_patch
from novel_forge.modules.evaluation_center import compare_model_runs, create_model_benchmark_task, create_model_profile, run_model_benchmark
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import ChapterPlan, CharacterCard, ContinuityBible, DraftChapter, ForeshadowingThread
from novel_forge.storage.local import LocalStorage


class AgentEditorContinuityEvaluationTests(unittest.TestCase):
    def test_agent_allowlist_sla_and_rollback_are_enforced_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "旧文本", "copyright_boundary": "fixture"}),
            )
            run = start_agent_run(storage, agent_key="quality", operation="quality-check", output_assets=[draft_path])
            with self.assertRaises(PermissionError):
                guard_agent_action(storage, run["path"], tool_name="call_model_adapter")
            sla = create_agent_sla_report(storage, agent_run_path=run["path"], sla_seconds=3600)
            self.assertEqual(storage.read_asset(sla["path"]).type, "agent_sla_report")
            rollback = create_agent_rollback_report(storage, agent_run_path=run["path"], apply=True, reason="unit test rollback")
            self.assertEqual(storage.read_asset(rollback["path"]).type, "agent_rollback_report")
            self.assertEqual(storage.read_json(draft_path)["metadata"]["rollback_status"], "rolled_back")

    def test_editor_patch_apply_and_diff_report_are_schema_backed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "旧文本", "copyright_boundary": "fixture"}),
            )
            patch = create_editor_patch(
                storage,
                draft_path,
                operations=[{"kind": "replace_text", "before": "旧文本", "after": "新文本", "instruction": "tighten wording"}],
            )
            applied = apply_editor_patch(storage, patch["path"])
            self.assertTrue(applied["applied"])
            self.assertEqual(storage.read_json(draft_path)["content"]["text"], "新文本")
            self.assertEqual(storage.read_asset(applied["diff_report"]["path"]).type, "draft_diff_report")
            self.assertEqual(storage.read_asset(applied["draft_version"]["path"]).type, "draft_version")
            diff = create_draft_diff_report(storage, draft_path, applied["draft_version"]["path"])
            self.assertEqual(storage.read_asset(diff["path"]).type, "draft_diff_report")

            paragraph_draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Paragraph Draft",
                    content={
                        "chapter": 2,
                        "text": "第一段其实非常拖沓，需要收紧。\n\n第二段保留原样。",
                        "copyright_boundary": "fixture",
                    },
                ),
            )
            paragraph_patch = create_editor_patch(storage, paragraph_draft, instructions="收紧段落")
            patch_asset = storage.read_asset(paragraph_patch["path"])
            self.assertGreaterEqual(len(patch_asset.content["operations"]), 1)
            selected = apply_editor_patch(storage, paragraph_patch["path"], operation_ids=["op-1"])
            self.assertEqual(selected["applied_operations"], ["op-1"])
            self.assertIn("第一段", storage.read_json(paragraph_draft)["content"]["text"])

    def test_continuity_graph_snapshot_and_chapter_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            character_path = storage.write_asset(
                "characters",
                CharacterCard(title="林乔", content={"role": "protagonist", "arc": "truth seeker"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    references=[storage.read_asset(character_path).id],
                    content={"chapter": 1, "text": "林乔推开钟楼的门。", "copyright_boundary": "fixture"},
                ),
            )
            graph = build_continuity_graph(storage)
            self.assertGreaterEqual(graph["summary"]["node_count"], 2)
            snapshot = create_continuity_graph_snapshot(storage)
            self.assertEqual(storage.read_asset(snapshot["path"]).type, "continuity_graph_snapshot")
            report = create_chapter_continuity_report(storage, draft_path)
            self.assertEqual(storage.read_asset(report["path"]).type, "chapter_continuity_report")

    def test_long_form_stability_preflight_checks_character_foreshadowing_timeline_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Preflight Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={"name": "林乔", "role": "protagonist", "status": "死亡"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            storage.write_asset(
                "continuity",
                ContinuityBible(
                    title="Preflight continuity",
                    content={
                        "project_id": project_id,
                        "worldview_rules": [],
                        "timeline": [{"chapter": 5, "event": "天门开启"}],
                        "entities": [],
                        "open_threads": [],
                        "constraints": ["禁止主角离开钟城"],
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref, storage.read_asset(character_path).id],
                ),
            )
            storage.write_asset(
                "continuity",
                ForeshadowingThread(
                    title="铜铃伏笔",
                    content={
                        "thread_id": "铜铃伏笔",
                        "status": "abandoned",
                        "setup": "铜铃伏笔",
                        "payoff_plan": "不再使用",
                        "related_chapters": [2],
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Risky chapter plan",
                    content={
                        "chapter": 2,
                        "objective": "林乔出场并救下同伴，随后主角离开钟城",
                        "beats": ["铜铃伏笔再次出现", "天门开启的消息提前泄露"],
                        "hook": "天门开启",
                        "carry_forward": {"previous_chapter": 2},
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            report = create_chapter_stability_preflight_report(storage, plan_path, workspace_path=workspace_ref)
            asset = storage.read_asset(report["path"])
            dimensions = asset.content["dimensions"]
            blocking_dimensions = {item["dimension"] for item in asset.content["blocking_violations"]}

            self.assertEqual(asset.type, "chapter_continuity_report")
            self.assertEqual(asset.content["gate"], "long_form_stability_preflight")
            self.assertEqual(asset.content["recommendation"], "block")
            self.assertEqual(dimensions["characters"]["status"], "blocked")
            self.assertEqual(dimensions["foreshadowing"]["status"], "blocked")
            self.assertEqual(dimensions["timeline"]["status"], "blocked")
            self.assertEqual(dimensions["setting_conflicts"]["status"], "blocked")
            self.assertIn("character_state_conflict", blocking_dimensions)
            self.assertIn("foreshadowing_status_conflict", blocking_dimensions)
            self.assertIn("timeline_regression", blocking_dimensions)
            self.assertIn("future_timeline_leak", blocking_dimensions)
            self.assertIn("setting_rule_conflict", blocking_dimensions)

    def test_model_evaluation_assets_can_run_and_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "fixture"}),
            )
            profile = create_model_profile(storage, provider="mock", model_name="mock-model", task_types=["generate"])
            self.assertEqual(storage.read_asset(profile["path"]).type, "model_profile")
            task = create_model_benchmark_task(storage, task_type="generate", input_assets=[draft_path], expected_output_type="generate")
            run = run_model_benchmark(storage, task["path"], provider="mock", model_name="mock-model", model=MockModelAdapter())
            self.assertEqual(storage.read_asset(run["path"]).type, "model_benchmark_run")
            comparison = compare_model_runs(storage, [run["path"]], task_type="generate")
            self.assertEqual(storage.read_asset(comparison["path"]).type, "model_comparison_report")


if __name__ == "__main__":
    unittest.main()
