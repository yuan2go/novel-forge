from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.creative_assets import create_creative_asset, list_creative_assets, list_creative_libraries
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.production_context import build_production_context
from novel_forge.modules.review import service as review_service
from novel_forge.api.product import create_project_with_defaults
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage
from novel_forge.workflows import pipeline


class CreativeAssetsTests(unittest.TestCase):
    def test_create_style_profile_is_schema_backed_and_project_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = pipeline.init_workspace(tmp, "Creative Project")
            storage = LocalStorage(tmp)
            workspace = storage.read_json(workspace_path)
            project_id = workspace["content"]["project_id"]

            created = create_creative_asset(
                storage,
                {
                    "asset_type": "style_profile",
                    "title": "Clean suspense project style",
                    "project_id": project_id,
                    "workspace_path": str(workspace_path.relative_to(Path(tmp).resolve())),
                    "content": {
                        "style_id": "clean_suspense_project",
                        "language_parameters": {"sentence_length": "mixed", "paragraph_density": "medium"},
                    },
                },
            )
            asset = storage.read_json(created["path"])

            self.assertEqual(created["library"], "style_center")
            self.assertEqual(asset["type"], "style_profile")
            self.assertEqual(asset["metadata"]["project_id"], project_id)
            self.assertEqual(asset["metadata"]["library_key"], "style_center")
            self.assertIn("abstract", asset["metadata"]["copyright_boundary"])

    def test_list_libraries_groups_quality_and_setting_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_path = pipeline.init_workspace(tmp, "Library Project")
            storage = LocalStorage(tmp)
            workspace = storage.read_json(workspace_path)
            project_id = workspace["content"]["project_id"]
            workspace_rel = str(workspace_path.relative_to(Path(tmp).resolve()))

            create_creative_asset(
                storage,
                {
                    "asset_type": "quality_standard_profile",
                    "title": "Local quality standard",
                    "project_id": project_id,
                    "workspace_path": workspace_rel,
                },
            )
            create_creative_asset(
                storage,
                {
                    "asset_type": "continuity_bible",
                    "title": "Local continuity bible",
                    "project_id": project_id,
                    "workspace_path": workspace_rel,
                },
            )

            libraries = list_creative_libraries(storage, project_id=project_id)
            quality = next(library for library in libraries if library["key"] == "quality_standards")
            setting = list_creative_assets(storage, "setting_bible", project_id=project_id)

            self.assertEqual(quality["assets"][0]["type"], "quality_standard_profile")
            self.assertEqual(setting[0]["type"], "continuity_bible")
            self.assertEqual(setting[0]["project_id"], project_id)

            writing = create_creative_asset(
                storage,
                {
                    "asset_type": "writing_template",
                    "title": "Hook template",
                    "project_id": project_id,
                    "workspace_path": workspace_rel,
                    "content": {"template_kind": "chapter_hook", "structure": ["pressure", "choice", "hook"]},
                },
            )
            craft = create_creative_asset(
                storage,
                {
                    "asset_type": "craft_template",
                    "title": "Conflict craft",
                    "project_id": project_id,
                    "workspace_path": workspace_rel,
                    "content": {"craft_domain": "conflict", "pattern": "choice creates cost"},
                },
            )
            material = list_creative_assets(storage, "material_library", project_id=project_id)
            self.assertIn(writing["path"], {row["path"] for row in material})
            self.assertIn(craft["path"], {row["path"] for row in material})

    def test_project_bound_profiles_feed_draft_and_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            detail = create_project_with_defaults(tmp, "Production Context Project")
            storage = LocalStorage(tmp)
            config = detail["project_config"]
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Chapter plan with bound context",
                    source="project",
                    tags=["chapter-plan"],
                    content={
                        "chapter": 1,
                        "objective": "Use the clock clue to force a visible choice.",
                        "beats": ["钟声出现", "主角选择", "代价显现"],
                        "hook": "第二声钟从港口传来。",
                    },
                    metadata={
                        "project_id": detail["project_id"],
                        "workspace_path": detail["path"],
                    },
                ),
            )

            draft_path = drafting_service.draft(storage, str(plan_path))
            draft = storage.read_asset(draft_path)
            self.assertTrue(draft.metadata["preflight_ready"], draft.metadata["preflight_warnings"])
            self.assertEqual(draft.metadata["quality_standard_profile_id"], config["quality_standard_profile_id"])
            self.assertEqual(draft.metadata["style_profile_id"], config["style_profile_id"])
            self.assertEqual(draft.metadata["creative_strategy_profile_id"], config["creative_strategy_profile_id"])
            self.assertTrue(draft.metadata["rag_quality_report_path"])
            self.assertNotEqual(draft.metadata["rag_quality_recommendation"], "block")

            review_path = review_service.review(storage, str(draft_path))
            review = storage.read_asset(review_path)
            self.assertEqual(review.metadata["quality_standard_profile_id"], config["quality_standard_profile_id"])
            self.assertIn("quality_standard_evaluation", review.content)
            self.assertTrue(review.metadata["quality_score_report_path"])
            self.assertTrue(review.metadata["style_review_report_path"])
            self.assertTrue(review.metadata["originality_report_path"])
            self.assertTrue(review.metadata["chapter_audit_report_path"])

    def test_legacy_continuity_binding_migrates_to_continuity_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            detail = create_project_with_defaults(tmp, "Legacy Continuity Project")
            storage = LocalStorage(tmp)
            workspace_path = storage.root / detail["path"]
            workspace = storage.read_json(workspace_path)
            config = workspace["content"]["project_config"]
            original_path = storage.root / config["continuity_bible_path"]
            legacy_path = storage.data_dir("worlds") / original_path.name
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(original_path.read_text(encoding="utf-8"), encoding="utf-8")
            original_path.unlink()
            config["continuity_bible_path"] = str(legacy_path.relative_to(storage.root))
            workspace["content"]["project_config"] = config
            storage.write_json(workspace_path, workspace)
            plan = ChapterPlan(
                title="Legacy continuity plan",
                source="project",
                tags=["chapter-plan"],
                content={
                    "chapter": 1,
                    "objective": "Test continuity migration.",
                    "beats": ["setup", "choice"],
                    "hook": "legacy path should move",
                },
                metadata={"project_id": detail["project_id"], "workspace_path": detail["path"]},
            )

            context = build_production_context(storage, plan, workspace_path=detail["path"])
            migrated_path = context["profiles"]["continuity_bible"]["path"]
            updated_config = storage.read_json(workspace_path)["content"]["project_config"]

            self.assertTrue(migrated_path.startswith("data/continuity/"))
            self.assertEqual(updated_config["continuity_bible_path"], migrated_path)
            self.assertTrue((storage.root / migrated_path).exists())
            self.assertTrue(legacy_path.exists())


if __name__ == "__main__":
    unittest.main()
