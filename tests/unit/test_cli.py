from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "novel_forge.cli", *args],
            cwd=cwd or ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_help(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Novel Forge V5 CLI", result.stdout)

    def test_init_and_validate_temp_project_reports_missing_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("init", "--root", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            status = self.run_cli("status", "--root", tmp)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("raw: 0", status.stdout)

    def test_ingest_directory_imports_supported_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "inputs"
            fixture_dir.mkdir()
            (fixture_dir / "a.txt").write_text("Plain text fixture", encoding="utf-8")
            (fixture_dir / "b.md").write_text("# Markdown fixture", encoding="utf-8")
            with zipfile.ZipFile(fixture_dir / "c.epub", "w") as archive:
                archive.writestr("chapter.xhtml", "<html><body>EPUB fixture text</body></html>")
            (fixture_dir / "d.mobi").write_bytes("MOBI fixture text".encode("utf-8"))
            (fixture_dir / "e.azw3").write_bytes("AZW3 fixture text".encode("utf-8"))

            result = self.run_cli("ingest", str(fixture_dir), "--root", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            output_paths = [line for line in result.stdout.splitlines() if line.strip()]
            self.assertEqual(len(output_paths), 5)
            status = self.run_cli("status", "--root", tmp)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("raw: 5", status.stdout)

    def test_ingest_records_rights_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Owned fixture", encoding="utf-8")

            result = self.run_cli(
                "ingest",
                str(source),
                "--root",
                tmp,
                "--rights",
                "owned",
                "--license",
                "internal-test",
                "--copyright-note",
                "self-authored fixture",
                "--allow-downstream-generation",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
            self.assertEqual(data["metadata"]["rights"]["authorization"], "owned")
            self.assertTrue(data["metadata"]["rights"]["allow_downstream_generation"])

    def test_search_lists_and_filters_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hidden clue for search", encoding="utf-8")
            ingest = self.run_cli("ingest", str(source), "--root", tmp)
            self.assertEqual(ingest.returncode, 0, ingest.stderr)
            clean = self.run_cli("clean", "--root", tmp)
            self.assertEqual(clean.returncode, 0, clean.stderr)
            decompose = self.run_cli("decompose", "--root", tmp)
            self.assertEqual(decompose.returncode, 0, decompose.stderr)
            knowledge = self.run_cli("extract-knowledge", "--root", tmp)
            self.assertEqual(knowledge.returncode, 0, knowledge.stderr)
            material = self.run_cli("build-materials", "--root", tmp)
            self.assertEqual(material.returncode, 0, material.stderr)
            index = self.run_cli("build-index", "--root", tmp)
            self.assertEqual(index.returncode, 0, index.stderr)
            self.assertTrue(Path(index.stdout.strip()).exists())
            manifest = self.run_cli("build-manifest", "--root", tmp)
            self.assertEqual(manifest.returncode, 0, manifest.stderr)
            self.assertTrue(Path(manifest.stdout.strip()).exists())
            manifest_status = self.run_cli("manifest-status", "--root", tmp)
            self.assertEqual(manifest_status.returncode, 0, manifest_status.stderr)
            self.assertGreaterEqual(json.loads(manifest_status.stdout)["raw"], 1)

            result = self.run_cli(
                "search",
                "--root",
                tmp,
                "--category",
                "materials",
                "--type",
                "material_card",
                "--tag",
                "hook",
                "--keyword",
                "obligation",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = json.loads(result.stdout)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["type"], "material_card")
            self.assertIn("hook", rows[0]["tags"])

            ranked = self.run_cli(
                "search",
                "--root",
                tmp,
                "--category",
                "materials",
                "--keyword",
                "hook",
                "--rank",
                "relevance",
            )
            self.assertEqual(ranked.returncode, 0, ranked.stderr)
            ranked_rows = json.loads(ranked.stdout)
            self.assertEqual(len(ranked_rows), 1)
            self.assertIn("score", ranked_rows[0])

            fallback = self.run_cli(
                "search",
                "--root",
                tmp,
                "--category",
                "materials",
                "--tag",
                "hook",
                "--keyword",
                "obligation",
                "--no-index",
            )
            self.assertEqual(fallback.returncode, 0, fallback.stderr)
            self.assertEqual(len(json.loads(fallback.stdout)), 1)

            vector_index = self.run_cli("build-vector-index", "--root", tmp)
            self.assertEqual(vector_index.returncode, 0, vector_index.stderr)
            self.assertTrue(Path(vector_index.stdout.strip()).exists())
            vector = self.run_cli(
                "vector-search",
                "--root",
                tmp,
                "--category",
                "materials",
                "--query",
                "chapter hook obligation",
            )
            self.assertEqual(vector.returncode, 0, vector.stderr)
            vector_rows = json.loads(vector.stdout)
            self.assertEqual(len(vector_rows), 1)
            self.assertEqual(vector_rows[0]["ranker"], "hybrid-hash-vector-bm25")

    def test_topic_development_and_training_exercise_commands_write_schema_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("第一章 钟声\n线索推动选择，结尾留下追读义务。", encoding="utf-8")
            for command in [
                ("ingest", str(source)),
                ("clean",),
                ("decompose",),
                ("extract-knowledge",),
                ("build-materials",),
            ]:
                result = self.run_cli(*command, "--root", tmp)
                self.assertEqual(result.returncode, 0, result.stderr)

            topic = self.run_cli("topic-development", "--root", tmp)
            self.assertEqual(topic.returncode, 0, topic.stderr)
            topic_path = Path(topic.stdout.strip())
            self.assertTrue(topic_path.exists())
            topic_data = json.loads(topic_path.read_text(encoding="utf-8"))
            self.assertEqual(topic_data["type"], "topic_seed")
            self.assertIn("market_positioning", topic_data["content"])

            training = self.run_cli("training-exercise", "--input", str(topic_path), "--root", tmp)
            self.assertEqual(training.returncode, 0, training.stderr)
            training_path = Path(training.stdout.strip())
            self.assertTrue(training_path.exists())
            training_data = json.loads(training_path.read_text(encoding="utf-8"))
            self.assertEqual(training_data["type"], "training_exercise")
            self.assertIn("rubric", training_data["content"])

            status = self.run_cli("status", "--root", tmp)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("topics: 1", status.stdout)
            self.assertIn("training: 1", status.stdout)

    def test_compare_reviews_command_writes_multi_model_review_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hook line\nConflict line\nReader obligation.", encoding="utf-8")
            for command in [
                ("ingest", str(source)),
                ("clean",),
                ("decompose",),
                ("extract-knowledge",),
                ("build-materials",),
                ("generate-topic",),
                ("generate-world",),
                ("generate-characters",),
                ("generate-outline",),
                ("generate-chapter-plan",),
                ("draft",),
            ]:
                result = self.run_cli(*command, "--root", tmp)
                self.assertEqual(result.returncode, 0, result.stderr)

            comparison = self.run_cli("compare-reviews", "--root", tmp)
            self.assertEqual(comparison.returncode, 0, comparison.stderr)
            comparison_path = Path(comparison.stdout.strip())
            self.assertTrue(comparison_path.exists())
            comparison_data = json.loads(comparison_path.read_text(encoding="utf-8"))

            self.assertEqual(comparison_data["type"], "review_report")
            self.assertIn("review-comparison", comparison_data["tags"])
            self.assertEqual(len(comparison_data["content"]["model_reviews"]), 3)
            self.assertIn("score_summary", comparison_data["content"])
            self.assertIn("revision_suggestions", comparison_data)

    def test_workspace_commands_track_multiple_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            source.write_text("Hook line\nConflict line\nReader obligation.", encoding="utf-8")
            draft_path = None
            for command in [
                ("ingest", str(source)),
                ("clean",),
                ("decompose",),
                ("extract-knowledge",),
                ("build-materials",),
                ("generate-topic",),
                ("generate-world",),
                ("generate-characters",),
                ("generate-outline",),
                ("generate-chapter-plan",),
                ("draft",),
            ]:
                result = self.run_cli(*command, "--root", tmp)
                self.assertEqual(result.returncode, 0, result.stderr)
                if command[0] == "draft":
                    draft_path = result.stdout.strip()
            self.assertIsNotNone(draft_path)

            workspace = self.run_cli(
                "init-workspace",
                "--root",
                tmp,
                "--title",
                "Echo Clock Project",
                "--series",
                "Clockverse",
                "--book",
                "1",
            )
            self.assertEqual(workspace.returncode, 0, workspace.stderr)
            workspace_path = workspace.stdout.strip()
            self.assertTrue(Path(workspace_path).exists())

            update_one = self.run_cli(
                "update-workspace",
                "--root",
                tmp,
                "--workspace",
                workspace_path,
                "--input",
                draft_path,
                "--chapter",
                "1",
            )
            self.assertEqual(update_one.returncode, 0, update_one.stderr)
            update_two = self.run_cli(
                "update-workspace",
                "--root",
                tmp,
                "--workspace",
                workspace_path,
                "--input",
                draft_path,
                "--chapter",
                "2",
                "--status",
                "planned",
            )
            self.assertEqual(update_two.returncode, 0, update_two.stderr)

            status = self.run_cli("workspace-status", "--root", tmp, "--workspace", workspace_path)
            self.assertEqual(status.returncode, 0, status.stderr)
            summary = json.loads(status.stdout)
            self.assertEqual(summary["chapter_count"], 2)
            self.assertEqual(summary["latest_chapter"], 2)
            self.assertEqual(summary["series_title"], "Clockverse")
            self.assertEqual(summary["book_number"], 1)
            self.assertGreaterEqual(summary["open_hook_count"], 1)

    def test_analyze_feedback_outputs_trends_and_retention_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feedback = root / "feedback.csv"
            feedback.write_text(
                "reader,chapter,rating,comment\n"
                "r1,1,5,strong hook and suspense\n"
                "r2,1,4,clear hook\n"
                "r1,2,2,slow and confused motive\n"
                "r2,2,2,drop risk because motivation unclear\n",
                encoding="utf-8",
            )
            imported = self.run_cli("import-feedback", str(feedback), "--root", tmp)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            insight = self.run_cli("analyze-feedback", "--root", tmp)
            self.assertEqual(insight.returncode, 0, insight.stderr)
            insight_path = Path(insight.stdout.strip())
            data = json.loads(insight_path.read_text(encoding="utf-8"))

            self.assertEqual(data["type"], "feedback_insight")
            self.assertEqual(data["content"]["plot_adjustment_plan"]["trend_direction"], "declining")
            self.assertEqual(data["content"]["retention_risk"]["level"], "high")
            self.assertEqual(len(data["content"]["chapter_trends"]), 2)
            self.assertLess(data["content"]["trend_metrics"]["rating_slope"], 0)
            self.assertEqual(data["content"]["trend_metrics"]["low_rating_ratio"], 0.5)
            self.assertIn("make protagonist motivation pressure explicit by beat 2", data["content"]["next_generation_constraints"])


if __name__ == "__main__":
    unittest.main()
