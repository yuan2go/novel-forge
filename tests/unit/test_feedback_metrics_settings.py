from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.feedback import apply_feedback_strategy_to_workspace, create_feedback_import_batch, create_reader_sentiment_report
from novel_forge.modules.metrics import create_project_metric_snapshot
from novel_forge.modules.settings_center import create_local_settings_profile
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage


class FeedbackMetricsSettingsTests(unittest.TestCase):
    def test_feedback_import_sentiment_metrics_and_settings_are_agent_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_path = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Industrial Project",
                    content={
                        "project_id": "project_industrial",
                        "memory": {},
                        "chapter_states": [],
                        "continuity_threads": {},
                        "open_issues": [],
                        "project_config": {},
                    },
                ),
            )
            storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    content={"chapter": 1, "text": "原创章节。", "copyright_boundary": "fixture"},
                    metadata={"project_id": "project_industrial", "workspace_path": str(workspace_path.relative_to(storage.root))},
                ),
            )
            csv_path = Path(tmp) / "feedback.csv"
            csv_path.write_text("reader,chapter,rating,comment\nr1,1,5,钩子很好追读\nr2,1,2,节奏慢想弃文\n", encoding="utf-8")

            imported = create_feedback_import_batch(
                storage,
                str(csv_path),
                workspace_path=str(workspace_path.relative_to(storage.root)),
                source_label="first feedback",
            )
            self.assertEqual(storage.read_asset(imported["batch"]["path"]).type, "feedback_import_batch")
            self.assertEqual(storage.read_asset(imported["reader_feedback"]["path"]).type, "reader_feedback")

            sentiment = create_reader_sentiment_report(
                storage,
                feedback_paths=[imported["reader_feedback"]["path"]],
                workspace_path=str(workspace_path.relative_to(storage.root)),
            )
            sentiment_asset = storage.read_asset(sentiment["path"])
            self.assertEqual(sentiment_asset.type, "reader_sentiment_report")
            self.assertIn("slow", sentiment_asset.content["poison_points"])
            self.assertIn("follow_read_risk", sentiment_asset.content)
            self.assertIn("character_heat", sentiment_asset.content)
            self.assertIn("next_chapter_strategy", sentiment_asset.content)
            applied_strategy = apply_feedback_strategy_to_workspace(
                storage,
                sentiment["path"],
                workspace_path=str(workspace_path.relative_to(storage.root)),
            )
            self.assertEqual(applied_strategy["workspace_path"], str(workspace_path.relative_to(storage.root)))
            workspace_after = storage.read_json(workspace_path)
            self.assertIn("reader_feedback", workspace_after["content"]["memory"])

            snapshot = create_project_metric_snapshot(
                storage,
                project_id="project_industrial",
                workspace_path=str(workspace_path.relative_to(storage.root)),
            )
            self.assertEqual(storage.read_asset(snapshot["path"]).type, "project_metric_snapshot")
            self.assertGreaterEqual(storage.read_asset(snapshot["path"]).content["throughput"]["draft_count"], 1)
            self.assertIn("trends", storage.read_asset(snapshot["path"]).content)
            self.assertIn("model_cost", storage.read_asset(snapshot["path"]).content)

            settings = create_local_settings_profile(storage, workspace_path=str(workspace_path.relative_to(storage.root)))
            self.assertEqual(storage.read_asset(settings["path"]).type, "local_settings_profile")

            agent_runs = [storage.read_json(path) for path in storage.list_json("runs") if storage.read_json(path).get("type") == "agent_run"]
            operations = {item["content"]["operation"] for item in agent_runs}
            self.assertIn("import-feedback-batch", operations)
            self.assertIn("create-reader-sentiment-report", operations)
            self.assertIn("create-project-metric-snapshot", operations)
            self.assertIn("create-local-settings-profile", operations)


if __name__ == "__main__":
    unittest.main()
