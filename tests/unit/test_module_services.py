from pathlib import Path
import os
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
from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.topics import service as topics_service
from novel_forge.modules.training import service as training_service
from novel_forge.modules.workspace import service as workspace_service
from novel_forge.modules.worldbuilding import service as worldbuilding_service
from novel_forge.schemas import DraftChapter
from novel_forge.workflows import pipeline

ROOT = Path(__file__).resolve().parents[2]


class ModuleServiceTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

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
            knowledge_asset = storage.read_asset(knowledge)
            self.assertIn("retrieved_context", knowledge_asset.metadata)
            self.assertIn("retrieval_source_asset_ids", knowledge_asset.metadata)
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
            draft_asset = storage.read_asset(draft)
            self.assertIn("retrieved_context", draft_asset.metadata)
            self.assertIn("retrieval_query", draft_asset.metadata)
            review = review_service.review(storage, str(draft))
            review_asset = storage.read_asset(review)
            self.assertIn("retrieved_context", review_asset.metadata)
            self.assertIn("retrieval_ranker", review_asset.metadata)
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
            self.assertLess(insight_asset.content["trend_metrics"]["rating_slope"], 0)
            self.assertEqual(insight_asset.content["trend_metrics"]["confidence"], "low")
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
            self.assertTrue(all("rights" in asset.metadata for asset in assets))
            self.assertTrue(any("EPUB clue" in asset.content["text"] for asset in assets))
            self.assertTrue(all(asset.content["text"].strip() for asset in assets))

    def test_epub_ingestion_uses_opf_spine_order_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = pipeline.ensure_project(root)
            epub = root / "ordered.epub"
            with zipfile.ZipFile(epub, "w") as archive:
                archive.writestr(
                    "META-INF/container.xml",
                    """<?xml version="1.0"?>
                    <container>
                      <rootfiles>
                        <rootfile full-path="OEBPS/content.opf" />
                      </rootfiles>
                    </container>""",
                )
                archive.writestr(
                    "OEBPS/content.opf",
                    """<package>
                      <metadata><title>Ordered Test</title><language>zh</language></metadata>
                      <manifest>
                        <item id="second" href="ch2.xhtml" />
                        <item id="first" href="ch1.xhtml" />
                      </manifest>
                      <spine>
                        <itemref idref="first" />
                        <itemref idref="second" />
                      </spine>
                    </package>""",
                )
                archive.writestr("OEBPS/ch2.xhtml", "<html><body>第二章 后出现</body></html>")
                archive.writestr("OEBPS/ch1.xhtml", "<html><body>第一章 先出现</body></html>")

            raw = ingestion_service.ingest(storage, str(epub))
            asset = storage.read_asset(raw)

            self.assertLess(asset.content["text"].index("第一章"), asset.content["text"].index("第二章"))
            self.assertEqual(asset.metadata["extraction_method"], "epub-opf-spine")
            self.assertEqual(asset.metadata["epub_spine_items"], ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"])
            self.assertEqual(asset.metadata["epub_metadata"]["title"], "Ordered Test")

    def test_review_outputs_creative_quality_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = pipeline.ensure_project(Path(tmp))
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Weak draft",
                    source="plan",
                    tags=["draft"],
                    content={
                        "chapter": 1,
                        "text": "他走进房间。天气很好。然后结束。",
                        "copyright_boundary": "test fixture",
                    },
                ),
            )

            review = review_service.review(storage, str(draft))
            asset = storage.read_asset(review)

            self.assertIn("quality_gates", asset.content)
            self.assertIn("quality_standard_evaluation", asset.content)
            self.assertIn("production_context", asset.content)
            self.assertIn("quality_score_report_path", asset.metadata)
            self.assertIn("style_review_report_path", asset.metadata)
            self.assertIn("originality_report_path", asset.metadata)
            self.assertIn("chapter_audit_report_path", asset.metadata)
            self.assertIn("character_motivation_chain", asset.content["quality_gates"]["blocked_dimensions"])
            self.assertTrue(any(issue.get("reviewer") == "local-creative-gate" for issue in asset.issues))
            quality_report = storage.read_asset(asset.metadata["quality_score_report_path"])
            style_report = storage.read_asset(asset.metadata["style_review_report_path"])
            originality_report = storage.read_asset(asset.metadata["originality_report_path"])
            chapter_audit_report = storage.read_asset(asset.metadata["chapter_audit_report_path"])
            self.assertEqual(quality_report.type, "quality_score_report")
            self.assertEqual(style_report.type, "style_review_report")
            self.assertEqual(originality_report.type, "originality_report")
            self.assertEqual(chapter_audit_report.type, "chapter_audit_report")

    def test_review_rework_loop_binds_issue_to_patch_version_review_and_publish_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = pipeline.ensure_project(Path(tmp))
            model = MockModelAdapter()
            draft = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Rework loop draft",
                    source="chapter-plan",
                    tags=["draft"],
                    content={
                        "chapter": 1,
                        "text": (
                            "林乔推开旧钟楼的门，雨水顺着袖口落下。\n\n"
                            "她发现档案上的时间被人改过，决定留下来找出原因。\n\n"
                            "午夜钟声再次响起，墙后传来钥匙坠地的声音。"
                        ),
                        "copyright_boundary": "test fixture original draft",
                    },
                ),
            )
            review = review_service.review(storage, str(draft), model=model)
            review_asset = storage.read_asset(review)
            self.assertTrue(review_asset.issues)
            self.assertIn("issue_id", review_asset.issues[0])

            result = revision_service.run_review_rework_loop(
                storage,
                review,
                draft_path=draft,
                issue_indexes=[0],
                revision_model=model,
                editor_model=model,
                review_model=model,
                human_override=True,
            )

            task = storage.read_asset(result["revision_task_path"])
            revision_plan = storage.read_asset(result["revision_plan_path"])
            editor_patch = storage.read_asset(result["editor_patch_path"])
            draft_version = storage.read_asset(result["draft_version_path"])
            re_review = storage.read_asset(result["re_review_path"])
            publish_gate = storage.read_asset(result["publish_gate_report_path"])
            updated_review = storage.read_asset(review)

            self.assertEqual(task.type, "revision_task")
            self.assertIn(task.content["status"], {"publish_ready", "needs_revision", "blocked"})
            self.assertEqual(task.content["outputs"]["editor_patch_path"], result["editor_patch_path"])
            self.assertEqual(task.content["outputs"]["draft_version_path"], result["draft_version_path"])
            self.assertEqual(revision_plan.type, "revision_plan")
            self.assertEqual(revision_plan.content["revision_task_path"], result["revision_task_path"])
            self.assertEqual(editor_patch.type, "editor_patch")
            self.assertEqual(editor_patch.content["status"], "applied")
            self.assertEqual(draft_version.type, "draft_version")
            self.assertEqual(re_review.type, "review_report")
            self.assertEqual(re_review.metadata["rework_loop"]["revision_task_path"], result["revision_task_path"])
            self.assertEqual(publish_gate.type, "publish_gate_report")
            self.assertEqual(publish_gate.metadata["rework_loop"]["revision_task_path"], result["revision_task_path"])
            self.assertIn("rework_evidence", updated_review.issues[0])
            self.assertEqual(updated_review.issues[0]["rework_evidence"]["draft_version_path"], result["draft_version_path"])

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

    def test_workspace_supports_multi_book_series_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = pipeline.ensure_project(Path(tmp))
            book_one = workspace_service.init_workspace(storage, "Clockverse Book One", "Clockverse", 1)
            book_two = workspace_service.init_workspace(storage, "Clockverse Book Two", "Clockverse", 2)
            draft_one = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Book one chapter",
                    source="book-one-plan",
                    tags=["draft"],
                    content={"chapter": 1, "text": "第一部第一章留下钟楼钩子。"},
                ),
            )
            draft_two = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Book two chapter",
                    source="book-two-plan",
                    tags=["draft"],
                    content={"chapter": 1, "text": "第二部第一章回收旧钥匙并打开新钩子。"},
                ),
            )

            updated_one = workspace_service.update_workspace(storage, str(draft_one), str(book_one), chapter=1)
            updated_two = workspace_service.update_workspace(storage, str(draft_two), str(book_two), chapter=1)
            status_one = workspace_service.workspace_status(storage, str(updated_one))
            status_two = workspace_service.workspace_status(storage, str(updated_two))

            self.assertEqual(status_one["series_title"], "Clockverse")
            self.assertEqual(status_two["series_title"], "Clockverse")
            self.assertEqual(status_one["book_number"], 1)
            self.assertEqual(status_two["book_number"], 2)
            self.assertNotEqual(
                storage.read_asset(updated_one).content["project_id"],
                storage.read_asset(updated_two).content["project_id"],
            )

    def test_long_project_fixture_tracks_six_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = pipeline.ensure_project(Path(tmp))
            fixture = ROOT / "tests" / "fixtures" / "long_project" / "clockverse_long_fixture.txt"
            raw = ingestion_service.ingest(
                storage,
                str(fixture),
                rights_authorization="test_fixture",
                copyright_note="self-authored long project fixture",
                allow_downstream_generation=True,
            )
            cleaned = cleaning_service.clean(storage, str(raw))
            cleaned_asset = storage.read_asset(cleaned)
            workspace = workspace_service.init_workspace(storage, "Clockverse Fixture", "Clockverse", 1)

            for number, chapter in enumerate(cleaned_asset.content["chapters"], start=1):
                draft = storage.write_asset(
                    "drafts",
                    DraftChapter(
                        title=f"Fixture chapter {number}",
                        source=cleaned_asset.id,
                        tags=["draft", "fixture"],
                        content={
                            "chapter": number,
                            "text": f"{chapter['title']}。为了推进线索，角色必须选择并留下新的章节钩子。",
                            "copyright_boundary": "self-authored fixture",
                        },
                    ),
                )
                workspace = workspace_service.update_workspace(storage, str(draft), str(workspace), chapter=number)

            summary = workspace_service.workspace_status(storage, str(workspace))

            self.assertEqual(cleaned_asset.metadata["chapter_count"], 6)
            self.assertEqual(summary["chapter_count"], 6)
            self.assertEqual(summary["series_title"], "Clockverse")
            self.assertGreaterEqual(summary["open_hook_count"], 6)


if __name__ == "__main__":
    unittest.main()
