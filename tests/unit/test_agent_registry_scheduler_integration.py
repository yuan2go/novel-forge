from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_registry import record_agent_lifecycle_event, sync_runtime_profiles
from novel_forge.modules.agent_runs import list_agent_runs, start_agent_run
from novel_forge.modules.agent_scheduler import dispatch_agent_run, list_agent_dispatch_queue, run_agent_scheduler_tick
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class AgentRegistrySchedulerIntegrationTests(unittest.TestCase):
    def test_scheduler_records_registry_version_on_agent_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            run = start_agent_run(storage, agent_key="continuity", operation="create-continuity-graph-snapshot", status="prepared")
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage) if row["operation"] == "create-continuity-graph-snapshot"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertTrue(runs[0]["agent_registry_entry_id"])
            self.assertTrue(runs[0]["agent_registry_version"])

    def test_scheduler_fail_closed_for_deprecated_agent_registry_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            record_agent_lifecycle_event(storage, agent_id="continuity", to_state="deprecated", reason="unit test")
            run = start_agent_run(storage, agent_key="continuity", operation="create-continuity-graph-snapshot", status="prepared")
            dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1)

            tick = run_agent_scheduler_tick(storage)
            queue = list_agent_dispatch_queue(storage)[0]

            self.assertEqual(tick["error_count"], 1)
            self.assertEqual(queue["status"], "dead_letter")
            self.assertIn("not schedulable", queue["last_error"])

    def test_scheduler_executes_longform_recap_as_longform_agent_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)
            latest_path = _longform_recap_fixture(storage)
            run = start_agent_run(
                storage,
                agent_key="longform_recap",
                operation="run-longform-recap",
                input_assets=[latest_path],
                status="prepared",
                evidence={"project_id": "scheduler-recap-p", "chapter_count": 12, "force": True},
            )
            dispatch_agent_run(storage, agent_run_path=run["path"])

            tick = run_agent_scheduler_tick(storage)
            runs = [row for row in list_agent_runs(storage, operation="run-longform-recap")]
            queue = list_agent_dispatch_queue(storage)[0]
            queue_asset = storage.read_json(storage.root / queue["path"])
            output_assets = queue_asset["content"]["result"]["output_assets"]

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(queue["status"], "acked")
            self.assertEqual(runs[0]["agent_type"], "Longform Recap Agent")
            self.assertTrue(any(str(path).endswith(".json") for path in output_assets))
            self.assertTrue(any(storage.read_json(storage.root / path)["type"] == "longform_recap_report" for path in output_assets))


def _longform_recap_fixture(storage: LocalStorage) -> Path:
    latest_path = None
    for chapter in range(1, 13):
        latest_path = storage.write_asset(
            "drafts",
            DraftChapter(
                title=f"Scheduler recap chapter {chapter}",
                content={
                    "chapter": chapter,
                    "text": f"第{chapter}章。主角持续追查同一条账册线索，人物目标和伏笔都保持连续。",
                    "copyright_boundary": "project-owned scheduler recap fixture",
                },
                metadata={"project_id": "scheduler-recap-p"},
            ),
        )
    assert latest_path is not None
    return latest_path
