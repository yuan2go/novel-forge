from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import compare_context_bundles, create_context_build_plan, create_context_bundle, list_context_assets
from novel_forge.modules.continuity_graph import create_canon_graph_snapshot
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.outline import service as outline_service
from novel_forge.modules.chapter_plan import service as chapter_plan_service
from novel_forge.modules.chapter_production_bus import (
    cancel_chapter_production,
    mark_chapter_production_celery_task,
    pause_chapter_production,
    recover_chapter_production,
    resume_chapter_production,
    start_chapter_production,
)
from novel_forge.modules.change_impact import mark_downstream_assets_stale
from novel_forge.modules.editor import apply_editor_patch
from novel_forge.modules.long_planning import create_long_form_macro_plan
from novel_forge.modules.operations import create_local_ops_drill_report, create_long_chain_acceptance_report
from novel_forge.modules.publishing import create_publishing_log, create_publishing_plan
from novel_forge.modules.production_chain import (
    create_chapter_plan_version,
    create_draft_version,
    create_generation_run,
    create_outline_version,
    list_production_versions,
)
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import ChapterPlan, CharacterCard, ContinuityBible, CraftTemplate, DraftChapter, FeedbackInsight, ForeshadowingThread, KnowledgeCard, MaterialCard, Outline, ReleasePackage, WritingTemplate, WorldBible
from novel_forge.storage.local import LocalStorage
from novel_forge.workers.tasks import chapter_production_run_task


class ContextAndProductionChainTests(unittest.TestCase):
    def test_outline_and_chapter_plan_load_project_profiles_continuity_feedback_and_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Planning Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            feedback_path = storage.write_asset(
                "feedback",
                FeedbackInsight(
                    title="Reader retention signal",
                    content={
                        "signals": ["clear hook liked", "motivation confusion"],
                        "average_rating": 3.4,
                        "next_generation_constraints": ["increase protagonist motivation clarity"],
                        "retention_risk": {"level": "medium", "reason": "chapter 2 ratings dropped"},
                        "plot_adjustment_plan": {
                            "next_generation_constraints": ["add visible decision consequence before the chapter hook"],
                            "trend_direction": "declining",
                        },
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            character_path = storage.write_asset(
                "characters",
                CharacterCard(
                    title="Project protagonist",
                    content={
                        "name": "林乔",
                        "role": "protagonist",
                        "desire": "decode the public clock signal without becoming a tool of the archive",
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref, storage.read_asset(feedback_path).id],
                ),
            )

            outline_path = outline_service.generate_outline(storage, str(character_path.relative_to(storage.root)), workspace_path=workspace_ref)
            outline = storage.read_asset(outline_path)
            plan_path = chapter_plan_service.generate_chapter_plan(
                storage,
                str(outline_path.relative_to(storage.root)),
                workspace_path=workspace_ref,
                chapter=1,
            )
            plan = storage.read_asset(plan_path)

            self.assertEqual(outline.metadata["project_id"], project_id)
            self.assertEqual(plan.metadata["project_id"], project_id)
            self.assertTrue(outline.metadata["quality_standard_profile_id"])
            self.assertTrue(plan.metadata["quality_standard_profile_id"])
            self.assertTrue(outline.metadata["continuity_bible_id"])
            self.assertTrue(plan.metadata["continuity_bible_id"])
            self.assertIn(storage.read_asset(feedback_path).id, outline.metadata["feedback_asset_ids"])
            self.assertIn(storage.read_asset(feedback_path).id, plan.metadata["feedback_asset_ids"])
            self.assertTrue(outline.metadata["preflight_ready"])
            self.assertTrue(plan.metadata["preflight_ready"])
            self.assertIn("planning_context", outline.content)
            self.assertIn("planning_context", plan.content)
            self.assertIn("increase protagonist motivation clarity", outline.content["feedback_constraints"])
            self.assertIn("increase protagonist motivation clarity", plan.content["feedback_constraints"])
            self.assertTrue(plan.content["quality_targets"])
            self.assertTrue(plan.content["continuity_checks"] or plan.metadata["continuity_bible_id"])

    def test_context_builder_and_versioned_production_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            knowledge = storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Clock system knowledge",
                    content={"principles": ["clock signal must be causal"], "constraints": ["no copied source text"]},
                    metadata={"copyright_boundary": "abstract structure knowledge card"},
                ),
            )
            material = storage.write_asset(
                "materials",
                MaterialCard(
                    title="Chapter hook material",
                    content={"usable_patterns": ["delayed bell clue"], "do_not_copy": ["specific protected plots"]},
                    metadata={"copyright_boundary": "abstract structure material card"},
                ),
            )
            high_risk_material = storage.write_asset(
                "materials",
                MaterialCard(
                    title="Unsafe copied scene packet",
                    content={"usable_patterns": ["clock chapter hook conflict template"], "do_not_copy": ["copied protected scene"]},
                    metadata={"copyright_boundary": "unsafe fixture", "copyright_risk": "high"},
                ),
            )
            writing_template = storage.write_asset(
                "materials",
                WritingTemplate(
                    title="Hook writing template",
                    content={"template_kind": "chapter_hook", "structure": ["pressure", "choice", "next hook"], "usage_constraints": ["respect canon"]},
                    metadata={"copyright_boundary": "abstract template"},
                ),
            )
            craft_template = storage.write_asset(
                "materials",
                CraftTemplate(
                    title="Conflict craft template",
                    content={"craft_domain": "conflict", "pattern": "choice creates cost", "use_cases": ["chapter_plan"]},
                    metadata={"copyright_boundary": "abstract craft"},
                ),
            )
            outline = storage.write_asset(
                "outlines",
                Outline(title="Outline", content={"acts": [{"act": 1, "goal": "open mystery"}]}, references=[]),
            )
            chapter_plan = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Chapter plan",
                    source=storage.read_asset(outline).id,
                    content={
                        "chapter": 1,
                        "objective": "open the clock mystery",
                        "beats": ["rain", "archive clue"],
                        "hook": "a bell rings from a dismantled tower",
                    },
                    references=[storage.read_asset(outline).id],
                ),
            )

            plan = create_context_build_plan(
                storage,
                chapter_plan,
                query="clock chapter hook conflict template",
                top_k=8,
                token_budget=2000,
                context_profile="chapter_generation",
            )
            bundle = create_context_bundle(storage, plan["path"])
            plan_asset = storage.read_asset(plan["path"])
            bundle_asset = storage.read_asset(bundle["path"])

            self.assertEqual(storage.read_asset(plan["path"]).type, "context_build_plan")
            self.assertEqual(plan_asset.content["context_profile"], "chapter_generation")
            self.assertEqual(bundle_asset.type, "context_bundle")
            self.assertIn(storage.read_asset(knowledge).id, bundle_asset.content["source_asset_ids"])
            self.assertIn(storage.read_asset(material).id, bundle_asset.content["source_asset_ids"])
            self.assertNotIn(storage.read_asset(high_risk_material).id, bundle_asset.content["source_asset_ids"])
            self.assertIn(storage.read_asset(writing_template).id, bundle_asset.content["source_asset_ids"])
            self.assertIn(storage.read_asset(craft_template).id, bundle_asset.content["source_asset_ids"])
            self.assertIn("writing_templates", bundle_asset.content["compressed_context"])
            self.assertIn("actual_context", bundle_asset.content)
            high_risk_ref = str(high_risk_material.relative_to(storage.root))
            self.assertTrue(any(item["path"] == high_risk_ref for item in plan_asset.content["copyright_filter"]["filtered_assets"]))
            self.assertTrue(any(item["path"] == high_risk_ref for item in plan_asset.content["exclusions"]))
            self.assertTrue(plan_asset.content["recall_explanation"]["items"])
            self.assertIn("missing_buckets", plan_asset.content["omission_check"])
            self.assertIn("context_budget_score", bundle_asset.content)
            self.assertTrue(bundle_asset.content["rag_quality_report_path"])
            quality_report = storage.read_asset(bundle_asset.content["rag_quality_report_path"])
            self.assertEqual(quality_report.type, "rag_quality_report")
            self.assertEqual(quality_report.content["target_asset_id"], storage.read_asset(chapter_plan).id)
            self.assertTrue(quality_report.content["copyright_filter"]["filtered_assets"])
            self.assertGreaterEqual(quality_report.content["context_budget_score"]["score"], 0)
            self.assertEqual(len(list_context_assets(storage)), 3)

            tuned_bundle = create_context_bundle(
                storage,
                plan["path"],
                selected_asset_paths=[str(knowledge.relative_to(storage.root)), str(material.relative_to(storage.root))],
                disabled_asset_paths=[str(material.relative_to(storage.root))],
                priority_asset_paths=[str(knowledge.relative_to(storage.root))],
                final_confirmed=True,
            )
            tuned_asset = storage.read_asset(tuned_bundle["path"])
            self.assertTrue(tuned_asset.content["manual_selection"]["final_confirmed"])
            self.assertIn(str(material.relative_to(storage.root)), tuned_asset.content["manual_selection"]["disabled_asset_paths"])
            self.assertIn(storage.read_asset(knowledge).id, tuned_asset.content["source_asset_ids"])
            self.assertNotIn(storage.read_asset(material).id, tuned_asset.content["source_asset_ids"])
            diff = compare_context_bundles(storage, bundle["path"], tuned_bundle["path"])
            self.assertEqual(storage.read_asset(diff["path"]).type, "project_metric_snapshot")
            self.assertIn("recommendation", diff)

            outline_v0 = create_outline_version(storage, outline)
            outline_v1 = create_outline_version(storage, outline, change_summary="manual checkpoint")
            plan_v0 = create_chapter_plan_version(storage, chapter_plan)
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(chapter_plan).id,
                    content={"chapter": 1, "text": "原创钟声章节。", "copyright_boundary": "original test draft"},
                ),
            )
            draft_v0 = create_draft_version(storage, draft_path)
            run = create_generation_run(storage, chapter_plan, bundle["path"], output_path=draft_path, provider="mock", model="mock")
            versions = list_production_versions(storage)

            self.assertEqual(storage.read_asset(outline_v0["path"]).content["version_index"], 0)
            self.assertEqual(storage.read_asset(outline_v1["path"]).content["version_index"], 1)
            self.assertEqual(storage.read_asset(plan_v0["path"]).type, "chapter_plan_version")
            self.assertEqual(storage.read_asset(draft_v0["path"]).type, "draft_version")
            self.assertEqual(storage.read_asset(run["path"]).content["context_bundle_id"], bundle_asset.id)
            self.assertTrue(any(row["type"] == "generation_run" for row in versions))
            invalidation = mark_downstream_assets_stale(storage, chapter_plan, reason="unit test upstream plan changed")
            self.assertEqual(invalidation["status"], "applied")
            self.assertEqual(storage.read_json(draft_path)["metadata"]["asset_status"], "stale")

    def test_draft_service_records_context_bundle_and_generation_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset(
                "knowledge",
                KnowledgeCard(
                    title="Draft knowledge",
                    content={"principles": ["every clue changes a decision"]},
                    metadata={"copyright_boundary": "abstract structure knowledge card"},
                ),
            )
            storage.write_asset(
                "materials",
                MaterialCard(
                    title="Draft material",
                    content={"usable_patterns": ["choice cost before hook"], "do_not_copy": ["protected scenes"]},
                    metadata={"copyright_boundary": "abstract material card"},
                ),
            )
            storage.write_asset(
                "materials",
                WritingTemplate(
                    title="Draft hook template",
                    content={"template_kind": "chapter_hook", "structure": ["pressure", "decision", "hook"]},
                    metadata={"copyright_boundary": "abstract writing template"},
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="Draft protagonist",
                    content={"name": "林乔", "role": "protagonist", "current_state": "active"},
                    metadata={"copyright_boundary": "project-owned character"},
                ),
            )
            storage.write_asset(
                "worlds",
                WorldBible(
                    title="Draft world",
                    content={"rules": ["clock signal changes available choices"], "locations": ["钟城"]},
                    metadata={"copyright_boundary": "project-owned world bible"},
                ),
            )
            chapter_plan = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Chapter plan",
                    content={
                        "chapter": 1,
                        "objective": "open the mystery",
                        "beats": ["rain", "clue"],
                        "hook": "bell clue",
                    },
                ),
            )

            draft_path = drafting_service.draft(storage, str(chapter_plan))
            draft = storage.read_asset(draft_path)

            self.assertEqual(draft.type, "draft_chapter")
            self.assertIn("context_build_plan_path", draft.metadata)
            self.assertIn("context_bundle_path", draft.metadata)
            self.assertIn("draft_version_path", draft.metadata)
            self.assertIn("generation_run_path", draft.metadata)
            self.assertIn("stability_preflight_path", draft.metadata)
            self.assertIn(draft.metadata["stability_preflight_recommendation"], {"pass", "revise"})
            self.assertEqual(storage.read_asset(draft.metadata["context_bundle_path"]).type, "context_bundle")
            self.assertEqual(storage.read_asset(draft.metadata["draft_version_path"]).type, "draft_version")
            self.assertEqual(storage.read_asset(draft.metadata["generation_run_path"]).type, "generation_run")
            self.assertEqual(storage.read_asset(draft.metadata["stability_preflight_path"]).type, "chapter_continuity_report")

    def test_draft_service_blocks_low_quality_rag_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            chapter_plan = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Sparse chapter plan",
                    content={"chapter": 1, "objective": "open without assets", "beats": ["empty context"], "hook": "missing canon"},
                ),
            )

            with self.assertRaisesRegex(ValueError, "RAG quality gate"):
                drafting_service.draft(storage, str(chapter_plan))

    def test_direct_draft_service_cannot_bypass_stability_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Direct Draft Gate Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            storage.write_asset(
                "continuity",
                ContinuityBible(
                    title="Direct draft continuity",
                    content={
                        "project_id": project_id,
                        "worldview_rules": [],
                        "timeline": [],
                        "entities": [],
                        "open_threads": [],
                        "constraints": ["禁止主角离开钟城"],
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            chapter_plan = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Direct blocked chapter plan",
                    content={
                        "chapter": 1,
                        "objective": "主角离开钟城",
                        "beats": ["主角离开钟城"],
                        "hook": "城外钟声",
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            with self.assertRaisesRegex(ValueError, "stability preflight"):
                drafting_service.draft(storage, str(chapter_plan.relative_to(storage.root)), workspace_path=workspace_ref)

    def test_canon_graph_snapshot_structures_state_threads_and_preflight_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Canon Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={"name": "林乔", "role": "protagonist", "current_state": "active", "current_location": "钟城"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            storage.write_asset(
                "characters",
                CharacterCard(
                    title="林乔",
                    content={"name": "林乔", "role": "protagonist", "current_state": "dead", "current_location": "港口"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            storage.write_asset(
                "continuity",
                ForeshadowingThread(
                    title="Clock thread",
                    content={"thread_id": "clock", "status": "unknown_state", "related_chapters": [1], "setup": "钟声", "payoff_plan": "揭示规则"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            chapter_plan = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Canon chapter plan",
                    content={"chapter": 1, "objective": "林乔追查钟声", "beats": ["林乔行动"], "hook": "钟声再响"},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            snapshot = create_canon_graph_snapshot(storage, project_id=project_id, workspace_path=workspace_ref)
            snapshot_asset = storage.read_asset(snapshot["path"])
            self.assertEqual(snapshot_asset.type, "canon_graph_snapshot")
            self.assertTrue(snapshot_asset.content["entities"])
            self.assertTrue(snapshot_asset.content["state_machines"]["characters"])
            self.assertTrue(any(item["dimension"] == "character_state_machine" for item in snapshot_asset.content["violations"]))
            self.assertTrue(any(item["dimension"] == "foreshadowing_lifecycle" for item in snapshot_asset.content["violations"]))

            with self.assertRaisesRegex(ValueError, "stability preflight"):
                drafting_service.draft(storage, str(chapter_plan.relative_to(storage.root)), workspace_path=workspace_ref)
            preflights = [
                storage.read_asset(path)
                for path in storage.list_json("continuity")
                if storage.read_json(path).get("type") == "chapter_continuity_report"
            ]
            self.assertTrue(any("canon_graph" in report.content for report in preflights))

    def test_chapter_production_bus_runs_and_resumes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Bus Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            outline = storage.write_asset(
                "outlines",
                Outline(
                    title="Bus Outline",
                    content={"acts": [{"act": 1, "goal": "open the clock mystery"}]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            run = start_chapter_production(
                storage,
                outline_path=str(outline.relative_to(storage.root)),
                workspace_path=workspace_ref,
                chapter=1,
                run_to="final_draft",
            )

            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(run["current_step"], "final_draft")
            self.assertEqual(run["completed_steps"], 8)
            self.assertTrue(run["outputs"]["stability_preflight_path"])
            self.assertTrue(run["outputs"]["final_draft_path"])
            self.assertTrue(run["outputs"]["final_draft_version_path"])
            self.assertTrue(run["outputs"]["final_diff_report_path"])
            self.assertTrue(run["outputs"]["final_generation_run_path"])
            self.assertTrue(run["outputs"]["final_forward_patch_path"])
            self.assertTrue(run["outputs"]["final_rollback_patch_path"])
            final_draft = storage.read_asset(run["outputs"]["final_draft_path"])
            self.assertEqual(final_draft.type, "draft_chapter")
            self.assertEqual(final_draft.metadata["draft_status"], "final")
            forward_patch = storage.read_asset(run["outputs"]["final_forward_patch_path"])
            rollback_patch = storage.read_asset(run["outputs"]["final_rollback_patch_path"])
            diff_report = storage.read_asset(run["outputs"]["final_diff_report_path"])
            self.assertEqual(forward_patch.type, "editor_patch")
            self.assertEqual(forward_patch.content["status"], "applied")
            self.assertEqual(rollback_patch.type, "editor_patch")
            self.assertEqual(rollback_patch.content["status"], "proposed")
            self.assertTrue(diff_report.content["paragraph_diffs"])
            self.assertIn("revision_executor_outputs", final_draft.content["revision_execution"])
            preflight = storage.read_asset(run["outputs"]["stability_preflight_path"])
            self.assertEqual(preflight.type, "chapter_continuity_report")
            self.assertEqual(preflight.content["gate"], "long_form_stability_preflight")

            resumed = resume_chapter_production(storage, run["path"], from_step="next_chapter_plan", run_to="next_chapter_plan")

            self.assertEqual(resumed["status"], "succeeded")
            self.assertEqual(resumed["completed_steps"], 9)
            self.assertTrue(resumed["outputs"]["next_chapter_plan_path"])
            self.assertEqual(storage.read_asset(resumed["outputs"]["next_chapter_plan_path"]).type, "chapter_plan")
            self.assertTrue(any(entry["status"] == "completed" for entry in resumed["timeline"]))
            task_events = [
                storage.read_asset(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "task_status"
            ]
            self.assertTrue(any(event.content["step"] == "chapter-production:final_draft" for event in task_events))
            rollback_result = apply_editor_patch(storage, run["outputs"]["final_rollback_patch_path"])
            self.assertTrue(rollback_result["applied"])
            self.assertEqual(storage.read_asset(rollback_result["diff_report"]["path"]).type, "draft_diff_report")

    def test_chapter_production_bus_pause_cancel_recover_and_worker_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Async Bus Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            outline = storage.write_asset(
                "outlines",
                Outline(
                    title="Async Bus Outline",
                    content={"acts": [{"act": 1, "goal": "open async production"}]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            outline_ref = str(outline.relative_to(storage.root))

            planned = start_chapter_production(
                storage,
                outline_path=outline_ref,
                workspace_path=workspace_ref,
                chapter=1,
                run_to="outline_checkpoint",
                execute=False,
                execution_mode="celery",
            )
            self.assertEqual(planned["status"], "planned")
            marked = mark_chapter_production_celery_task(storage, planned["path"], "celery-task-1")
            self.assertEqual(marked["celery_task_id"], "celery-task-1")
            paused = pause_chapter_production(storage, planned["path"], reason="inspect before run")
            self.assertEqual(paused["status"], "paused")
            resumed = resume_chapter_production(storage, planned["path"], run_to="outline_checkpoint")
            self.assertEqual(resumed["status"], "succeeded")
            self.assertEqual(resumed["current_step"], "outline_checkpoint")

            cancellable = start_chapter_production(
                storage,
                outline_path=outline_ref,
                workspace_path=workspace_ref,
                chapter=2,
                run_to="outline_checkpoint",
                execute=False,
                execution_mode="celery",
            )
            cancelled = cancel_chapter_production(storage, cancellable["path"], reason="unit test cancel")
            self.assertEqual(cancelled["status"], "cancelled")
            recovered = recover_chapter_production(storage, cancellable["path"], run_to="outline_checkpoint")
            self.assertEqual(recovered["status"], "succeeded")

            worker_run = start_chapter_production(
                storage,
                outline_path=outline_ref,
                workspace_path=workspace_ref,
                chapter=3,
                run_to="outline_checkpoint",
                execute=False,
                execution_mode="celery",
            )
            worker_result = chapter_production_run_task(tmp, worker_run["path"], run_to="outline_checkpoint", clear_pause=False)
            self.assertEqual(worker_result["status"], "succeeded")
            self.assertEqual(worker_result["control"]["execution_mode"], "celery")

    def test_chapter_production_bus_blocks_before_context_on_stability_preflight_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Blocked Bus Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            storage.write_asset(
                "continuity",
                ContinuityBible(
                    title="Strict city continuity",
                    content={
                        "project_id": project_id,
                        "worldview_rules": [],
                        "timeline": [],
                        "entities": [],
                        "open_threads": [],
                        "constraints": ["禁止主角离开钟城"],
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            outline = storage.write_asset(
                "outlines",
                Outline(
                    title="Blocked Outline",
                    content={"acts": [{"act": 1, "goal": "test forbidden movement"}]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )
            chapter_plan = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Blocked Chapter Plan",
                    source=storage.read_asset(outline).id,
                    content={
                        "chapter": 1,
                        "objective": "主角离开钟城去寻找线索",
                        "beats": ["主角离开钟城", "远行寻找线索"],
                        "hook": "城外钟声再次响起",
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref, storage.read_asset(outline).id],
                ),
            )

            run = start_chapter_production(
                storage,
                outline_path=str(outline.relative_to(storage.root)),
                chapter_plan_path=str(chapter_plan.relative_to(storage.root)),
                workspace_path=workspace_ref,
                chapter=1,
                run_to="context_bundle",
            )

            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["current_step"], "stability_preflight")
            self.assertTrue(run["outputs"]["stability_preflight_path"])
            self.assertFalse(run["outputs"]["context_bundle_path"])
            report = storage.read_asset(run["outputs"]["stability_preflight_path"])
            self.assertEqual(report.type, "chapter_continuity_report")
            self.assertEqual(report.content["recommendation"], "block")
            self.assertEqual(report.content["gate_status"], "blocked")
            self.assertTrue(report.content["blocking_violations"])
            self.assertTrue(any(item["dimension"] == "setting_rule_conflict" for item in report.content["blocking_violations"]))

    def test_long_form_macro_plan_is_schema_backed_and_project_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Macro Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            outline = storage.write_asset(
                "outlines",
                Outline(
                    title="Macro outline",
                    content={"acts": [{"act": 1, "goal": "open macro plan"}]},
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            result = create_long_form_macro_plan(
                storage,
                workspace_path=workspace_ref,
                source_path=str(outline.relative_to(storage.root)),
                target_word_count=500000,
                volume_count=3,
                chapters_per_volume=60,
            )
            asset = storage.read_asset(result["path"])
            self.assertEqual(asset.type, "long_form_macro_plan")
            self.assertEqual(asset.metadata["project_id"], project_id)
            self.assertEqual(asset.content["volume_count"], 3)
            self.assertTrue(asset.content["mainline_matrix"])
            self.assertTrue(asset.content["commercial_pacing_table"])

    def test_publishing_plan_and_log_are_versioned_release_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace = init_workspace(storage, "Publishing Project")
            workspace_asset = storage.read_asset(workspace)
            project_id = workspace_asset.content["project_id"]
            workspace_ref = str(workspace.relative_to(storage.root))
            release_path = storage.write_asset(
                "publishing",
                ReleasePackage(
                    title="Release package ch1",
                    content={
                        "target_asset_id": "draft-1",
                        "publish_gate_report_id": "gate-1",
                        "title_candidates": ["Ch1"],
                        "summary": "Ready chapter",
                        "tags": ["release"],
                        "channel": "local",
                        "status": "ready",
                        "draft_path": "data/drafts/draft-1.json",
                        "publish_gate_report_path": "data/publishing/gate-1.json",
                    },
                    metadata={"project_id": project_id, "workspace_path": workspace_ref},
                    references=[workspace_ref],
                ),
            )

            plan = create_publishing_plan(storage, release_package_paths=[release_path], workspace_path=workspace_ref)
            self.assertEqual(storage.read_asset(plan["path"]).type, "publishing_plan")
            self.assertEqual(storage.read_asset(plan["path"]).content["chapter_queue"][0]["status"], "ready")
            log = create_publishing_log(storage, release_path, publishing_plan_path=plan["path"])
            self.assertEqual(storage.read_asset(log["path"]).type, "publishing_log")
            self.assertEqual(storage.read_asset(log["path"]).content["status"], "published")
            self.assertTrue(storage.read_asset(log["path"]).content["rollback_plan"]["available"])

    def test_local_ops_and_long_chain_acceptance_reports_are_schema_backed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            ops = create_local_ops_drill_report(storage)
            self.assertEqual(storage.read_asset(ops["path"]).type, "local_ops_drill_report")
            self.assertIn(storage.read_asset(ops["path"]).content["status"], {"passed", "warning", "failed"})
            acceptance = create_long_chain_acceptance_report(storage, chapter_count=10)
            self.assertEqual(storage.read_asset(acceptance["path"]).type, "long_chain_acceptance_report")
            self.assertEqual(storage.read_asset(acceptance["path"]).content["chapter_count"], 10)
            self.assertIn(storage.read_asset(acceptance["path"]).content["recommendation"], {"pass", "revise", "block"})


if __name__ == "__main__":
    unittest.main()
