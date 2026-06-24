from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.chapter_plan import service as chapter_plan_service
from novel_forge.modules.characters import service as characters_service
from novel_forge.modules.cleaning import service as cleaning_service
from novel_forge.modules.decomposition import service as decomposition_service
from novel_forge.modules.drafting import service as drafting_service
from novel_forge.modules.feedback import service as feedback_service
from novel_forge.modules.ingestion import service as ingestion_service
from novel_forge.modules.knowledge import service as knowledge_service
from novel_forge.modules.materials import service as materials_service
from novel_forge.modules.outline import service as outline_service
from novel_forge.modules.review import service as review_service
from novel_forge.modules.revision import service as revision_service
from novel_forge.modules.topics import service as topics_service
from novel_forge.modules.training import service as training_service
from novel_forge.modules.workspace import service as workspace_service
from novel_forge.modules.worldbuilding import service as worldbuilding_service
from novel_forge.schemas import DraftChapter
from novel_forge.workflows import pipeline


class ModuleServiceTests(unittest.TestCase):
    def test_services_run_main_asset_chain_without_pipeline_step_bodies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = pipeline.ensure_project(root)
            input_path = root / "source.txt"
            input_path.write_text("Hook line\n\nConflict line", encoding="utf-8")
            feedback_path = root / "feedback.csv"
            feedback_path.write_text(
                "reader,chapter,rating,comment\n"
                "r1,1,4,clear hook\n"
                "r2,1,5,strong suspense\n"
                "r1,2,2,slow and confused motive\n"
                "r2,2,3,drop risk because motivation unclear\n",
                encoding="utf-8",
            )

            raw = ingestion_service.ingest(storage, str(input_path))
            cleaned = cleaning_service.clean(storage, str(raw))
            decomposition = decomposition_service.decompose(storage, str(cleaned))
            knowledge = knowledge_service.extract_knowledge(storage, str(decomposition))
            material = materials_service.build_materials(storage, str(knowledge))
            material_asset = storage.read_asset(material)
            self.assertIn("hook", material_asset.tags)
            self.assertIn("reader-retention", material_asset.metadata["tag_facets"]["function"])
            topic = topics_service.generate_topic(storage, str(material))
            developed_topic = topics_service.develop_topic(storage, str(material))
            training = training_service.generate_training_exercise(storage, str(developed_topic))
            world = worldbuilding_service.generate_world(storage, str(topic))
            character = characters_service.generate_characters(storage, str(world))
            outline = outline_service.generate_outline(storage, str(character))
            chapter_plan = chapter_plan_service.generate_chapter_plan(storage, str(outline))
            draft = drafting_service.draft(storage, str(chapter_plan))
            review = review_service.review(storage, str(draft))
            comparison = review_service.compare_reviews(storage, str(draft))
            revision = revision_service.revise(storage, str(review))
            feedback = feedback_service.import_feedback(storage, str(feedback_path))
            insight = feedback_service.analyze_feedback(storage, str(feedback))
            workspace = workspace_service.init_workspace(storage, "Echo Clock Project")
            workspace = workspace_service.update_workspace(storage, str(draft), str(workspace), chapter=1)
            second_draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 2 draft v0",
                    source=chapter_plan.name,
                    tags=["draft", "v0"],
                    content={
                        "chapter": 2,
                        "text": "第二章里，新的钟声把线索推向港口。结尾留下一个未回收的钥匙钩子。",
                        "copyright_boundary": "mock original draft; no reference expression copied",
                    },
                ),
            )
            workspace = workspace_service.update_workspace(storage, str(second_draft), str(workspace), chapter=2)
            workspace_summary = workspace_service.workspace_status(storage, str(workspace))

            self.assertEqual(storage.read_asset(raw).type, "source_document")
            self.assertEqual(storage.read_asset(developed_topic).type, "topic_seed")
            self.assertEqual(storage.read_asset(training).type, "training_exercise")
            self.assertIn("rubric", storage.read_asset(training).content)
            comparison_asset = storage.read_asset(comparison)
            self.assertEqual(comparison_asset.type, "review_report")
            self.assertIn("review-comparison", comparison_asset.tags)
            self.assertEqual(comparison_asset.metadata["reviewer_count"], 3)
            self.assertIn("model_reviews", comparison_asset.content)
            self.assertIn("score_summary", comparison_asset.content)
            self.assertEqual(storage.read_asset(revision).type, "revision_plan")
            insight_asset = storage.read_asset(insight)
            self.assertEqual(insight_asset.type, "feedback_insight")
            self.assertEqual(insight_asset.content["retention_risk"]["level"], "medium")
            self.assertEqual(insight_asset.content["plot_adjustment_plan"]["trend_direction"], "declining")
            self.assertIn("chapter_trends", insight_asset.content)
            workspace_asset = storage.read_asset(workspace)
            self.assertEqual(workspace_asset.type, "project_workspace_state")
            self.assertEqual(workspace_summary["chapter_count"], 2)
            self.assertEqual(workspace_asset.metadata["chapter_count"], 2)
            self.assertEqual(len(workspace_asset.content["chapter_states"]), 2)
            self.assertEqual(feedback_service.average_rating([{"rating": "4"}, {"rating": "bad"}]), 4.0)

    def test_ingest_many_imports_supported_directory_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = pipeline.ensure_project(root)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "a.txt").write_text("Plain text clue", encoding="utf-8")
            (fixture_dir / "b.md").write_text("# Markdown clue\n\nConflict note", encoding="utf-8")
            with zipfile.ZipFile(fixture_dir / "c.epub", "w") as archive:
                archive.writestr("OEBPS/chapter.xhtml", "<html><body><h1>EPUB clue</h1><p>Hidden bell</p></body></html>")
            (fixture_dir / "d.mobi").write_bytes("MOBI fixture clue".encode("utf-8"))
            (fixture_dir / "e.azw3").write_bytes("AZW3 fixture clue".encode("utf-8"))
            (fixture_dir / "skip.pdf").write_text("unsupported", encoding="utf-8")

            paths = ingestion_service.ingest_many(storage, str(fixture_dir))

            self.assertEqual(len(paths), 5)
            assets = [storage.read_asset(path) for path in paths]
            formats = {asset.metadata["source_format"] for asset in assets}
            self.assertEqual(formats, {"txt", "md", "epub", "mobi", "azw3"})
            self.assertTrue(all(asset.type == "source_document" for asset in assets))
            self.assertTrue(any("EPUB clue" in asset.content["text"] for asset in assets))
            self.assertTrue(all(asset.content["text"].strip() for asset in assets))

    def test_ingest_many_rejects_directory_without_supported_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = pipeline.ensure_project(root)
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "unsupported.pdf").write_text("unsupported", encoding="utf-8")

            with self.assertRaises(ValueError):
                ingestion_service.ingest_many(storage, str(fixture_dir))

    def test_clean_text_removes_noise_and_detects_chapters(self):
        noisy = (
            "\ufeff第 一 章  雨 夜\n"
            "本书首发 起点中文网\n"
            "林 乔 走 进 旧 钟 楼 。。\n"
            "\n\n\n"
            "https://example.com/download\n"
            "第2章 新线索\n"
            "  线索  被   塞进门缝  ！！  \n"
            "关注公众号 获取最新章节\n"
        )

        result = cleaning_service.clean_text(noisy)

        self.assertNotIn("本书首发", result["text"])
        self.assertNotIn("https://example.com", result["text"])
        self.assertNotIn("关注公众号", result["text"])
        self.assertIn("林乔走进旧钟楼。", result["text"])
        self.assertIn("线索被塞进门缝！", result["text"])
        self.assertEqual(result["removed_line_count"], 3)
        self.assertEqual([chapter["title"] for chapter in result["chapters"]], ["第一章雨夜", "第2章新线索"])

    def test_clean_service_writes_chapter_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = pipeline.ensure_project(root)
            source_path = root / "noisy.txt"
            source_path.write_text("第一章 开端\n\n请收藏本书\n正文内容", encoding="utf-8")

            raw = ingestion_service.ingest(storage, str(source_path))
            cleaned = cleaning_service.clean(storage, str(raw))
            asset = storage.read_asset(cleaned)

            self.assertEqual(asset.type, "cleaned_text")
            self.assertEqual(asset.metadata["removed_line_count"], 1)
            self.assertEqual(asset.metadata["chapter_count"], 1)
            self.assertEqual(asset.content["chapters"][0]["title"], "第一章开端")


if __name__ == "__main__":
    unittest.main()
