from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import list_agent_runs
from novel_forge.modules.agent_scheduler import (
    list_agent_dispatch_queue,
    list_agent_operation_contracts,
    recover_agent_dispatch,
    run_agent_scheduler_tick,
    scheduler_status,
)
from novel_forge.modules.workflow_nodes import create_workflow_definition, execute_workflow, list_node_runs
from novel_forge.schemas import ChapterPlan, DraftChapter
from novel_forge.storage.local import LocalStorage


class AgentSchedulerTests(unittest.TestCase):
    def test_scheduler_completes_prepared_agent_and_resumes_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(plan_path).id,
                    content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"},
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Workflow",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "agent",
                            "agent_key": "draft",
                            "agent_status": "prepared",
                            "token_budget": 500,
                            "expected_output_assets": [str(draft_path.relative_to(storage.root))],
                            "token_used": 120,
                            "cost_estimate": 0.42,
                        },
                    },
                    {
                        "node_id": "review",
                        "node_type": "review",
                        "operation": "review",
                        "depends_on": ["draft-agent"],
                        "input_types": ["draft_chapter"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            queue = list_agent_dispatch_queue(storage)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["status"], "queued")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(tick["error_count"], 0)
            self.assertEqual(list_agent_dispatch_queue(storage)[0]["status"], "acked")
            agent = list_agent_runs(storage)[0]
            self.assertEqual(agent["status"], "succeeded")
            self.assertEqual(agent["token_used"], 120)
            old_run = storage.read_asset(initial["workflow_run"]["path"])
            self.assertEqual(old_run.content["status"], "superseded")
            resume = tick["acked"][0]["workflow_resume"]
            self.assertEqual(resume["status"], "completed")
            resumed_run = storage.read_asset(resume["workflow_run"]["path"])
            self.assertEqual(resumed_run.content["lineage"]["resumed_from_run_id"], initial["run_id"])
            node_statuses = {row["node_id"]: row["status"] for row in list_node_runs(storage, run_id=resume["run_id"])}
            self.assertEqual(node_statuses["draft-agent"], "succeeded")
            self.assertEqual(node_statuses["review"], "succeeded")
            status = scheduler_status(storage)
            self.assertEqual(status["by_status"]["acked"], 1)

    def test_scheduler_waits_for_human_when_prepared_agent_has_no_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Waiting",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "manual-human-operation",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["acked_count"], 0)
            self.assertEqual(tick["waiting_human_count"], 1)
            queue = list_agent_dispatch_queue(storage)[0]
            self.assertEqual(queue["status"], "waiting_human")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "waiting_human")
            recovered = recover_agent_dispatch(storage, queue_path=queue["path"], reason="unit test recovery")
            self.assertEqual(recovered["status"], "queued")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")

    def test_scheduler_runs_registered_local_service_operation_without_expected_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            contracts = list_agent_operation_contracts()
            self.assertIn("create-continuity-graph-snapshot", {item["operation"] for item in contracts})
            workflow = create_workflow_definition(
                storage,
                name="Agent Scheduler Local Service",
                entry_node_id="continuity",
                nodes=[
                    {
                        "node_id": "continuity",
                        "node_type": "agent",
                        "operation": "create-continuity-graph-snapshot",
                        "output_types": ["continuity_graph_snapshot"],
                        "processor": {"kind": "agent", "agent_key": "continuity", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], execute_agents=False)

            tick = run_agent_scheduler_tick(storage)

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["acked_count"], 1)
            self.assertEqual(tick["waiting_human_count"], 0)
            self.assertEqual(tick["error_count"], 0)
            output_assets = tick["acked"][0]["output_assets"]
            self.assertEqual(len(output_assets), 1)
            produced = storage.read_json(storage.root / output_assets[0])
            self.assertEqual(produced["type"], "continuity_graph_snapshot")
            queue = list_agent_dispatch_queue(storage)[0]
            self.assertEqual(queue["status"], "acked")
            old_run = storage.read_asset(initial["workflow_run"]["path"])
            self.assertEqual(old_run.content["status"], "superseded")
            resume = tick["acked"][0]["workflow_resume"]
            self.assertEqual(resume["status"], "completed")
            scheduler_agent = [row for row in list_agent_runs(storage) if row["operation"] == "create-continuity-graph-snapshot" and row["status"] == "succeeded"]
            self.assertGreaterEqual(len(scheduler_agent), 1)


if __name__ == "__main__":
    unittest.main()
