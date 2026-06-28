from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters import MockModelAdapter, model_from_env
from novel_forge.modules.agent_runs import (
    create_agent_boundary_audit,
    create_agent_rollback_report,
    create_agent_sla_report,
    execute_agent_run_once,
    guard_agent_action,
    start_agent_run,
)
from novel_forge.modules.continuity_graph import (
    apply_canon_patch,
    build_continuity_graph,
    create_canon_patch_from_draft,
    create_chapter_continuity_report,
    create_chapter_stability_preflight_report,
    create_continuity_graph_snapshot,
)
from novel_forge.modules.editor import apply_editor_patch, create_draft_diff_report, create_editor_patch
from novel_forge.modules.evaluation_center import (
    compare_model_runs,
    create_benchmark_task_from_generation_run,
    create_model_benchmark_task,
    create_model_profile,
    create_model_routing_policy,
    resolve_model_route,
    run_model_benchmark,
    run_model_benchmark_batch,
)
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.modules.production_chain import create_generation_run
from novel_forge.schemas import ChapterPlan, CharacterCard, ContextBundle, ContinuityBible, DraftChapter, ForeshadowingThread, WorldBible
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

    def test_agent_executor_enforces_allowlist_and_token_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(storage, agent_key="draft", operation="executor-test", token_budget=10)
            result = execute_agent_run_once(
                storage,
                run["path"],
                tool_name="call_model_adapter",
                output_type="draft_chapter",
                token_used=9,
                evidence={"unit_test": True},
            )
            self.assertEqual(result["status"], "succeeded")

            over = start_agent_run(storage, agent_key="draft", operation="executor-budget-test", token_budget=5)
            blocked = execute_agent_run_once(
                storage,
                over["path"],
                tool_name="call_model_adapter",
                output_type="draft_chapter",
                token_used=6,
            )
            self.assertEqual(blocked["status"], "failed")
            self.assertEqual(storage.read_asset(blocked["budget"]["path"]).type, "agent_budget")

    def test_agent_boundary_audit_records_static_and_runtime_guard_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            audit = create_agent_boundary_audit(storage, apply_runtime_guard=True)
            asset = storage.read_asset(audit["path"])
            self.assertEqual(asset.type, "agent_metric")
            self.assertIn("coverage", asset.content)
            self.assertIn("runtime_guard_probe", asset.content)
            self.assertEqual(asset.content["runtime_guard_probe"]["status"], "passed")

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

    def test_canon_patch_updates_continuity_after_final_draft_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Canon Patch Project")
            workspace_ref = str(workspace.relative_to(storage.root))
            project_id = storage.read_asset(workspace).content["project_id"]
            storage.write_asset(
                "continuity",
                ContinuityBible(
                    title="Canon bible",
                    content={"project_id": project_id, "worldview_rules": [], "timeline": [], "entities": [], "open_threads": [], "constraints": []},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={"name": "林乔", "role": "protagonist", "current_state": "active", "current_location": "钟城"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Final Draft",
                    content={"chapter": 3, "text": "林乔抵达钟塔。林乔发现铜铃真相。", "copyright_boundary": "fixture"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref, "draft_status": "final"},
                    references=[workspace_ref],
                ),
            )

            patch = create_canon_patch_from_draft(storage, draft_path, workspace_path=workspace_ref)
            patch_asset = storage.read_asset(patch["path"])
            self.assertEqual(patch_asset.type, "canon_patch")
            self.assertEqual(patch_asset.content["status"], "proposed")
            self.assertTrue(patch_asset.content["proposed_events"])
            applied = apply_canon_patch(storage, patch["path"], confirmed=True, note="unit test accepted")
            self.assertTrue(applied["updated_targets"])
            updated_bibles = [
                storage.read_asset(path)
                for path in storage.list_json("continuity")
                if storage.read_json(path).get("type") == "continuity_bible"
            ]
            self.assertTrue(updated_bibles[0].content["timeline"])
            self.assertEqual(storage.read_asset(patch["path"]).content["status"], "applied")

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

    def test_stability_preflight_hard_blocks_novel_kg_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "KG Preflight Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            metadata = {"project_id": project_id, "workspace_path": workspace_ref}
            storage.write_asset(
                "worlds",
                WorldBible(
                    title="Alias collision world",
                    content={"factions": [{"name": "Shadow Court", "goal": "control the archive"}]},
                    metadata=metadata,
                    references=[workspace_ref],
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="Shadow Court",
                    content={"name": "Shadow Court", "role": "protagonist", "status": "active"},
                    metadata=metadata,
                    references=[workspace_ref],
                ),
            )
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="KG alias collision plan",
                    content={
                        "chapter": 1,
                        "objective": "Shadow Court enters the archive.",
                        "beats": ["Shadow Court receives a warning."],
                        "hook": "archive opens",
                    },
                    metadata=metadata,
                    references=[workspace_ref],
                ),
            )

            report = create_chapter_stability_preflight_report(storage, plan_path, workspace_path=workspace_ref)
            asset = storage.read_asset(report["path"])
            blocking_types = {item["conflict_type"] for item in asset.content["blocking_violations"]}

            self.assertEqual(asset.content["recommendation"], "block")
            self.assertEqual(asset.content["dimensions"]["novel_kg"]["status"], "blocked")
            self.assertEqual(asset.content["novel_kg_gate"]["recommendation"], "block")
            self.assertIn("alias_collision", blocking_types)

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
            batch = run_model_benchmark_batch(storage, task_paths=[task["path"]], candidates=[{"provider": "mock", "model_name": "mock-model"}])
            self.assertTrue(batch["comparisons"])
            policy = create_model_routing_policy(storage, comparison_paths=[comparison["path"]])
            self.assertEqual(storage.read_asset(policy["path"]).type, "model_routing_policy")
            route = resolve_model_route(storage, task_type="generate")
            self.assertEqual(route["provider"], "mock")

            bundle_path = storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Eval context bundle",
                    content={"source_asset_ids": [], "selected_assets": [], "actual_context": "fixture"},
                ),
            )
            generation = create_generation_run(storage, draft_path, bundle_path, output_path=draft_path)
            production_task = create_benchmark_task_from_generation_run(storage, generation["path"])
            task_asset = storage.read_asset(production_task["path"])
            self.assertEqual(task_asset.type, "model_benchmark_task")
            self.assertEqual(task_asset.content["source_generation_run_path"], generation["path"])

            previous_root = os.environ.get("NOVEL_FORGE_ROOT")
            previous_provider = os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
            os.environ["NOVEL_FORGE_ROOT"] = tmp
            try:
                self.assertEqual(model_from_env("generate").name, "mock-model")
            finally:
                if previous_root is None:
                    os.environ.pop("NOVEL_FORGE_ROOT", None)
                else:
                    os.environ["NOVEL_FORGE_ROOT"] = previous_root
                if previous_provider is not None:
                    os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = previous_provider


if __name__ == "__main__":
    unittest.main()
