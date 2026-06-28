from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import list_agent_runs
from novel_forge.modules.workflow_nodes import create_workflow_definition, execute_workflow, list_node_runs, resume_workflow, run_workflow_scheduler
from novel_forge.schemas import ChapterPlan, CleanedText, DraftChapter, Outline, SourceDocument
from novel_forge.storage.local import LocalStorage


class WorkflowExecutorTests(unittest.TestCase):
    def test_executor_runs_dag_and_records_workflow_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(
                    title="Raw",
                    source="fixture",
                    content={"text": "fixture"},
                    metadata={"rights": {"authorization": "test_fixture", "copyright_boundary": "fixture"}},
                ),
            )
            cleaned_path = storage.write_asset(
                "cleaned",
                CleanedText(title="Cleaned", source=storage.read_asset(source_path).id, content={"text": "clean"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    source=storage.read_asset(cleaned_path).id,
                    content={"chapter": 1, "text": "原创测试章节。"},
                    references=[storage.read_asset(cleaned_path).id, str(cleaned_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Executor DAG",
                entry_node_id="clean",
                nodes=[
                    {
                        "node_id": "clean",
                        "node_type": "cleaning",
                        "operation": "clean",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(cleaned_path.relative_to(storage.root))]},
                        "quality_gate": {"required": True, "min_input_count": 1},
                    },
                    {
                        "node_id": "draft",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["clean"],
                        "input_types": ["cleaned_text"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "deterministic", "expected_output_assets": [str(draft_path.relative_to(storage.root))]},
                    },
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[source_path])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["order"], ["clean", "draft"])
            self.assertEqual(storage.read_asset(result["workflow_run"]["path"]).type, "workflow_run")
            self.assertEqual(storage.read_asset(result["workflow_run"]["path"]).content["status"], "completed")
            runs = list_node_runs(storage, run_id=result["run_id"])
            self.assertEqual([row["node_id"] for row in reversed(runs)], ["clean", "draft"])
            node_run = storage.read_asset(runs[-1]["path"])
            self.assertEqual(node_run.content["trace"]["trace_id"], result["run_id"])
            self.assertTrue(node_run.content["trace"]["span_id"])

    def test_executor_blocks_failed_quality_gate_before_downstream_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            source_path = storage.write_asset(
                "raw",
                SourceDocument(title="Raw", source="fixture", content={"text": "fixture"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Gate Block",
                entry_node_id="blocked",
                nodes=[
                    {
                        "node_id": "blocked",
                        "node_type": "quality",
                        "operation": "gate",
                        "input_types": ["source_document"],
                        "output_types": ["cleaned_text"],
                        "processor": {"kind": "deterministic"},
                        "quality_gate": {"required": True, "status": "failed", "message": "schema gate failed"},
                    },
                    {
                        "node_id": "downstream",
                        "node_type": "draft",
                        "operation": "draft",
                        "depends_on": ["blocked"],
                        "processor": {"kind": "deterministic"},
                    },
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[source_path])

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["blocked"]["node_id"], "blocked")
            node_runs = list_node_runs(storage, run_id=result["run_id"])
            self.assertEqual(len(node_runs), 1)
            self.assertEqual(node_runs[0]["status"], "failed")
            self.assertIn("schema gate failed", storage.read_asset(result["workflow_run"]["path"]).content["error_message"])

    def test_executor_dispatches_agent_run_from_workflow_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Dispatch",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            self.assertEqual(result["status"], "running")
            self.assertEqual(result["blocked"]["status"], "prepared")
            self.assertEqual(len(result["agent_runs"]), 1)
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")
            self.assertEqual(list_node_runs(storage, run_id=result["run_id"])[0]["status"], "prepared")

    def test_resume_executes_prepared_agent_and_continues_downstream(self):
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
                name="Agent Resume",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
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
            self.assertEqual(initial["status"], "running")

            resumed = resume_workflow(
                storage,
                initial["workflow_run"]["path"],
                output_assets=[draft_path],
                token_used=120,
                cost_estimate=0.42,
                checkpoint={"status": "draft_completed", "chapter": 1},
            )

            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(resumed["resume_node_id"], "draft-agent")
            self.assertEqual(storage.read_asset(resumed["workflow_run"]["path"]).content["lineage"]["resumed_from_run_id"], initial["run_id"])
            resume_node_runs = list_node_runs(storage, run_id=resumed["run_id"])
            self.assertEqual([row["node_id"] for row in reversed(resume_node_runs)], ["draft-agent", "review"])
            agent_run = storage.read_asset(resumed["agent_runs"][0]["path"])
            self.assertEqual(agent_run.content["status"], "succeeded")
            self.assertEqual(agent_run.content["token_used"], 120)
            run_types = _run_asset_types(storage)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_checkpoint", run_types)
            self.assertIn("agent_sla_report", run_types)

    def test_resume_blocks_when_agent_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Draft", content={"chapter": 1, "text": "原创测试章节。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Agent Budget Block",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 5},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            resumed = resume_workflow(storage, initial["workflow_run"]["path"], output_assets=[draft_path], token_used=50)

            self.assertEqual(resumed["status"], "failed")
            self.assertEqual(resumed["blocked"]["node_id"], "draft-agent")
            agent_runs = list_agent_runs(storage)
            self.assertEqual(agent_runs[0]["status"], "failed")
            run_types = _run_asset_types(storage)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_gate", run_types)
            self.assertIn("agent_failure_report", run_types)
            resume_node_runs = list_node_runs(storage, run_id=resumed["run_id"])
            self.assertEqual(resume_node_runs[0]["status"], "failed")

    def test_executor_can_apply_downstream_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            outline_path = storage.write_asset(
                "outlines",
                Outline(title="Outline", content={"acts": [{"act": 1, "goal": "open"}]}),
            )
            outline = storage.read_asset(outline_path)
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(
                    title="Plan",
                    source=outline.id,
                    content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"},
                    references=[outline.id, str(outline_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Invalidate",
                entry_node_id="invalidate",
                nodes=[
                    {
                        "node_id": "invalidate",
                        "node_type": "impact",
                        "operation": "invalidate-downstream",
                        "input_types": ["outline"],
                        "output_types": ["change_impact_report"],
                        "processor": {"kind": "invalidation", "max_depth": 2, "reason": "unit test upstream change"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[outline_path], apply_invalidation=True)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(storage.read_json(plan_path)["metadata"]["asset_status"], "stale")
            self.assertTrue(result["invalidations"][0]["updated_assets"])
            self.assertEqual(list_node_runs(storage, run_id=result["run_id"])[0]["status"], "succeeded")

    def test_scheduler_tick_resumes_prepared_agent_and_supersedes_old_run(self):
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
                name="Scheduler Resume",
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
            self.assertEqual(initial["status"], "running")

            tick = run_workflow_scheduler(storage)

            self.assertEqual(tick["status"], "completed")
            self.assertEqual(tick["candidate_count"], 1)
            self.assertEqual(tick["resumed_count"], 1)
            self.assertEqual(tick["error_count"], 0)
            old_run = storage.read_asset(initial["workflow_run"]["path"])
            self.assertEqual(old_run.content["status"], "superseded")
            self.assertEqual(old_run.metadata["asset_status"], "superseded")
            self.assertTrue(old_run.content["superseded_by_run_id"])
            resumed_path = tick["resumed"][0]["resume_workflow_run_path"]
            resumed_run = storage.read_asset(resumed_path)
            self.assertEqual(resumed_run.content["status"], "completed")
            self.assertEqual(resumed_run.content["lineage"]["resumed_from_run_id"], initial["run_id"])
            agent_run = storage.read_asset(tick["resumed"][0]["agent_run_path"])
            self.assertEqual(agent_run.content["status"], "succeeded")
            self.assertEqual(agent_run.content["token_used"], 120)
            run_types = _run_asset_types(storage)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_checkpoint", run_types)
            self.assertIn("agent_sla_report", run_types)

    def test_scheduler_tick_records_checkpoint_when_outputs_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            plan_path = storage.write_asset(
                "chapter_plans",
                ChapterPlan(title="Plan", content={"chapter": 1, "objective": "open", "beats": ["beat"], "hook": "hook"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Scheduler Missing Outputs",
                entry_node_id="draft-agent",
                nodes=[
                    {
                        "node_id": "draft-agent",
                        "node_type": "agent",
                        "operation": "draft",
                        "input_types": ["chapter_plan"],
                        "output_types": ["draft_chapter"],
                        "processor": {"kind": "agent", "agent_key": "draft", "agent_status": "prepared", "token_budget": 500},
                    }
                ],
            )
            initial = execute_workflow(storage, workflow["path"], input_assets=[plan_path], execute_agents=False)

            tick = run_workflow_scheduler(storage)

            self.assertEqual(tick["resumed_count"], 0)
            self.assertEqual(tick["skipped_count"], 1)
            self.assertEqual(tick["skipped"][0]["reason"], "missing_output_assets")
            self.assertIn("checkpoint_path", tick["skipped"][0])
            self.assertEqual(storage.read_asset(initial["workflow_run"]["path"]).content["status"], "running")
            self.assertEqual(list_agent_runs(storage)[0]["status"], "prepared")
            self.assertIn("agent_checkpoint", _run_asset_types(storage))

    def test_service_processor_registry_runs_module_completion_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            workflow = create_workflow_definition(
                storage,
                name="Service Registry",
                entry_node_id="snapshot",
                nodes=[
                    {
                        "node_id": "snapshot",
                        "node_type": "metric",
                        "operation": "module_completion_snapshot",
                        "output_types": ["project_metric_snapshot"],
                        "processor": {"kind": "service"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            self.assertEqual(storage.read_asset(result["workflow_run"]["asset"]["content"]["outputs"][0]).type, "project_metric_snapshot")
            node_run = list_node_runs(storage, run_id=result["run_id"])[0]
            processor = storage.read_asset(node_run["path"]).content["processor"]
            self.assertEqual(processor["registry_operation"], "module_completion_snapshot")


def _run_asset_types(storage: LocalStorage) -> set[str]:
    types: set[str] = set()
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict):
            types.add(str(data.get("type", "")))
    return types


if __name__ == "__main__":
    unittest.main()
