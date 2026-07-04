from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import start_agent_run
from novel_forge.modules.agent_scheduler import (
    agent_center_snapshot,
    agent_operation_coverage_full_report,
    create_agent_dag,
    dispatch_agent_run,
    repair_dead_letter_dispatch,
    rehearse_agent_rollback,
)
from novel_forge.storage.local import LocalStorage


class AgentCenterV2Tests(unittest.TestCase):
    def test_dag_coverage_rollback_rehearsal_and_dead_letter_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            dag = create_agent_dag(
                storage,
                {
                    "project_id": "agent-v2",
                    "name": "review publish DAG",
                    "nodes": [
                        {"id": "draft", "operation": "draft"},
                        {"id": "review", "operation": "review", "depends_on": ["draft"]},
                        {"id": "publish", "operation": "create-publish-gate-report", "depends_on": ["review"]},
                    ],
                },
            )
            run = start_agent_run(storage, agent_key="review", operation="review", status="prepared", evidence={"expected_output_assets": []})
            queue = dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1, priority=5)
            queue_path = storage.root / queue["path"]
            queue_data = storage.read_json(queue_path)
            queue_data["content"]["status"] = "dead_letter"
            queue_data["content"]["last_error"] = "unit dead letter"
            storage.write_json(queue_path, queue_data)

            coverage = agent_operation_coverage_full_report(storage, project_id="agent-v2")
            rehearsal = rehearse_agent_rollback(storage, {"queue_path": queue["path"], "project_id": "agent-v2"})
            repaired = repair_dead_letter_dispatch(storage, {"queue_path": queue["path"], "project_id": "agent-v2", "reason": "unit repair"})
            snapshot = agent_center_snapshot(storage, project_id=None)

            self.assertEqual(dag["status"], "ready")
            self.assertEqual(dag["validation"]["topological_order"], ["draft", "review", "publish"])
            self.assertGreaterEqual(coverage["summary"]["operation_count"], 1)
            self.assertEqual(rehearsal["asset"]["type"], "agent_rollback_rehearsal")
            self.assertEqual(repaired["repair"]["before_status"], "dead_letter")
            self.assertEqual(repaired["repair"]["recovered_queue"]["status"], "queued")
            self.assertEqual(snapshot["agent_center_version"], "v2")
            self.assertIn("operation_coverage_full", snapshot)
            self.assertIn("hard_stop_dashboard", snapshot)


if __name__ == "__main__":
    unittest.main()
