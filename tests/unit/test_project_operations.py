from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.project_operations import project_operating_dashboard
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage


class ProjectOperationsTests(unittest.TestCase):
    def test_operating_dashboard_ranks_daily_actions_and_project_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_a = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Missing Profiles",
                    content={
                        "project_id": "project_missing",
                        "memory": {},
                        "chapter_states": [],
                        "continuity_threads": {},
                        "open_issues": [],
                        "project_config": {},
                    },
                ),
            )
            workspace_b = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Production Ready",
                    content={
                        "project_id": "project_ready",
                        "memory": {},
                        "chapter_states": [{"chapter": 1, "status": "planned"}],
                        "continuity_threads": {},
                        "open_issues": [],
                        "project_config": {
                            "platform_profile_path": "data/platforms/platform.json",
                            "genre_market_profile_path": "data/genres/genre.json",
                            "quality_standard_profile_path": "data/quality_standards/quality.json",
                            "style_profile_path": "data/styles/style.json",
                            "continuity_bible_path": "data/continuity/bible.json",
                        },
                    },
                ),
            )
            storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Ready Draft",
                    content={"chapter": 1, "text": "原创章节。"},
                    metadata={"project_id": "project_ready", "workspace_path": str(workspace_b.relative_to(storage.root))},
                    references=[str(workspace_b.relative_to(storage.root))],
                ),
            )

            dashboard = project_operating_dashboard(storage)
            rows = {row["project_id"]: row for row in dashboard["projects"]}
            self.assertEqual(rows["project_missing"]["today_action"]["action"], "bind_profiles")
            self.assertEqual(rows["project_ready"]["profile_binding_count"], 5)
            self.assertGreater(rows["project_ready"]["investment_score"], rows["project_missing"]["investment_score"])
            self.assertTrue(dashboard["today_priorities"])
            self.assertEqual(Path(workspace_a).name.endswith(".json"), True)


if __name__ == "__main__":
    unittest.main()
