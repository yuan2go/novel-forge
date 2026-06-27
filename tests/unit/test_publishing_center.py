from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit import create_release_package
from novel_forge.modules.publishing import create_publishing_log, create_publishing_plan, list_publishing_assets
from novel_forge.schemas import DraftChapter, ProjectWorkspaceState
from novel_forge.storage.local import LocalStorage


class PublishingCenterTests(unittest.TestCase):
    def test_publishing_calendar_rules_logs_and_version_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workspace_path = storage.write_asset(
                "workspaces",
                ProjectWorkspaceState(
                    title="Publishing Project",
                    content={
                        "project_id": "project_publish",
                        "memory": {},
                        "chapter_states": [],
                        "continuity_threads": {},
                        "open_issues": [],
                        "project_config": {"target_platform": "local_serial", "publish_min_hook_score": 0.75},
                    },
                ),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 1",
                    content={"chapter": 1, "text": "原创章节文本，包含明确章节钩子和发布摘要。"},
                    metadata={"project_id": "project_publish", "workspace_path": str(workspace_path.relative_to(storage.root))},
                    references=[str(workspace_path.relative_to(storage.root))],
                ),
            )

            package_path = create_release_package(
                storage,
                draft_path,
                workspace_path=str(workspace_path.relative_to(storage.root)),
                channel="local_serial",
                human_override=True,
            )
            package = storage.read_asset(package_path)
            self.assertEqual(package.type, "release_package")
            self.assertTrue(package.content["release_version"])
            self.assertEqual(package.content["platform_rules"]["target_platform"], "local_serial")

            plan = create_publishing_plan(
                storage,
                release_package_paths=[str(package_path.relative_to(storage.root))],
                project_id="project_publish",
                workspace_path=str(workspace_path.relative_to(storage.root)),
                channel="local_serial",
                cadence="daily",
                start_date="2026-07-01",
            )
            self.assertEqual(storage.read_asset(plan["path"]).content["calendar"][0]["scheduled_at"], "2026-07-01")
            self.assertTrue(storage.read_asset(plan["path"]).content["platform_rules"]["require_publish_gate_ready"])

            log = create_publishing_log(
                storage,
                str(package_path.relative_to(storage.root)),
                publishing_plan_path=plan["path"],
                channel="local_serial",
                external_url="https://local.example/chapter-1",
            )
            self.assertTrue(storage.read_asset(log["path"]).content["rollback_plan"]["available"])

            rows = list_publishing_assets(storage, project_id="project_publish")
            by_type = {row["type"]: row for row in rows}
            self.assertEqual(by_type["release_package"]["release_version"], package.content["release_version"])
            self.assertEqual(by_type["publishing_plan"]["next_scheduled_at"], "2026-07-01")
            self.assertTrue(by_type["publishing_log"]["rollback_available"])


if __name__ == "__main__":
    unittest.main()
