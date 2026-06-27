from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.context_builder import create_context_build_plan, create_context_bundle, list_context_assets
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.chapter_production_bus import start_chapter_production, resume_chapter_production
from novel_forge.modules.production_chain import (
    create_chapter_plan_version,
    create_draft_version,
    create_generation_run,
    create_outline_version,
    list_production_versions,
)
from novel_forge.modules.workspace.service import init_workspace
from novel_forge.schemas import ChapterPlan, CraftTemplate, DraftChapter, KnowledgeCard, MaterialCard, Outline, WritingTemplate
from novel_forge.storage.local import LocalStorage


class ContextAndProductionChainTests(unittest.TestCase):
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

            plan = create_context_build_plan(storage, chapter_plan, query="clock chapter hook conflict template", top_k=8, token_budget=2000)
            bundle = create_context_bundle(storage, plan["path"])
            bundle_asset = storage.read_asset(bundle["path"])

            self.assertEqual(storage.read_asset(plan["path"]).type, "context_build_plan")
            self.assertEqual(bundle_asset.type, "context_bundle")
            self.assertIn(storage.read_asset(knowledge).id, bundle_asset.content["source_asset_ids"])
            self.assertIn(storage.read_asset(material).id, bundle_asset.content["source_asset_ids"])
            self.assertIn(storage.read_asset(writing_template).id, bundle_asset.content["source_asset_ids"])
            self.assertIn(storage.read_asset(craft_template).id, bundle_asset.content["source_asset_ids"])
            self.assertIn("writing_templates", bundle_asset.content["compressed_context"])
            self.assertIn("actual_context", bundle_asset.content)
            self.assertEqual(len(list_context_assets(storage)), 2)

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
            self.assertEqual(storage.read_asset(draft.metadata["context_bundle_path"]).type, "context_bundle")
            self.assertEqual(storage.read_asset(draft.metadata["draft_version_path"]).type, "draft_version")
            self.assertEqual(storage.read_asset(draft.metadata["generation_run_path"]).type, "generation_run")

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
            self.assertEqual(run["completed_steps"], 7)
            self.assertTrue(run["outputs"]["final_draft_path"])
            self.assertTrue(run["outputs"]["final_draft_version_path"])
            self.assertTrue(run["outputs"]["final_diff_report_path"])
            self.assertTrue(run["outputs"]["final_generation_run_path"])
            final_draft = storage.read_asset(run["outputs"]["final_draft_path"])
            self.assertEqual(final_draft.type, "draft_chapter")
            self.assertEqual(final_draft.metadata["draft_status"], "final")

            resumed = resume_chapter_production(storage, run["path"], from_step="next_chapter_plan", run_to="next_chapter_plan")

            self.assertEqual(resumed["status"], "succeeded")
            self.assertEqual(resumed["completed_steps"], 8)
            self.assertTrue(resumed["outputs"]["next_chapter_plan_path"])
            self.assertEqual(storage.read_asset(resumed["outputs"]["next_chapter_plan_path"]).type, "chapter_plan")
            self.assertTrue(any(entry["status"] == "completed" for entry in resumed["timeline"]))
            task_events = [
                storage.read_asset(path)
                for path in storage.list_json("runs")
                if storage.read_json(path).get("type") == "task_status"
            ]
            self.assertTrue(any(event.content["step"] == "chapter-production:final_draft" for event in task_events))


if __name__ == "__main__":
    unittest.main()
