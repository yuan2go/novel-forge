from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import list_agent_runs
from novel_forge.modules.runtime_ledger import acquire_scheduler_lease, create_budget_policy, scheduler_lease_status
from novel_forge.modules.workflow_nodes import create_workflow_definition, execute_workflow, list_node_runs, resume_workflow, run_workflow_scheduler, run_workflow_scheduler_loop
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
            self.assertEqual(storage.read_asset(initial["workflow_run"]["path"]).content["status"], "superseded")
            resume_node_runs = list_node_runs(storage, run_id=resumed["run_id"])
            self.assertEqual([row["node_id"] for row in reversed(resume_node_runs)], ["draft-agent", "review"])
            agent_run = storage.read_asset(resumed["agent_runs"][0]["path"])
            self.assertEqual(agent_run.content["status"], "succeeded")
            self.assertEqual(agent_run.content["token_used"], 120)
            run_types = _run_asset_types(storage)
            self.assertIn("agent_budget", run_types)
            self.assertIn("agent_checkpoint", run_types)
            self.assertIn("agent_sla_report", run_types)
            self.assertIn("model_call_log", run_types)
            self.assertIn("cost_ledger", run_types)
            self.assertIn("trace_span", run_types)

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

    def test_resume_blocks_when_budget_policy_is_exceeded(self):
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
            create_budget_policy(storage, scope="local-system", limits={"max_cost": 0.1, "max_tokens_per_run": 1000}, project_id="local-system")
            workflow = create_workflow_definition(
                storage,
                name="Agent Budget Policy Block",
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

            resumed = resume_workflow(storage, initial["workflow_run"]["path"], output_assets=[draft_path], token_used=50, cost_estimate=0.42)

            self.assertEqual(resumed["status"], "failed")
            run_types = _run_asset_types(storage)
            self.assertIn("budget_policy", run_types)
            self.assertIn("cost_alert", run_types)
            self.assertIn("agent_failure_report", run_types)

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
            self.assertIn("cost_ledger", run_types)

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

    def test_scheduler_loop_respects_active_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            lease = acquire_scheduler_lease(storage, owner="worker-a", ttl_seconds=300)
            self.assertTrue(lease["acquired"])

            loop = run_workflow_scheduler_loop(storage, iterations=1, interval_seconds=0, lease_owner="worker-b")

            self.assertEqual(loop["status"], "skipped")
            self.assertEqual(loop["recommendation"], "scheduler_lease_active")
            status = scheduler_lease_status(storage)
            self.assertEqual(status["owner"], "worker-a")
            self.assertEqual(status["status"], "active")

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

    def test_service_processor_resumes_from_checkpoint_when_outputs_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            output_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Recovered Draft", content={"chapter": 1, "text": "已存在输出。", "copyright_boundary": "unit test"}),
            )
            workflow = create_workflow_definition(
                storage,
                name="Checkpoint Resume",
                entry_node_id="recover",
                nodes=[
                    {
                        "node_id": "recover",
                        "node_type": "service",
                        "operation": "unknown_service_that_should_not_run",
                        "output_types": ["draft_chapter"],
                        "processor": {
                            "kind": "service",
                            "resume_from_checkpoint": True,
                            "expected_output_assets": [str(output_path.relative_to(storage.root))],
                            "checkpoint_schema": {"version": "0.1.0", "state": "output_exists"},
                        },
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "recovered")
            self.assertTrue(node_run.content["processor"]["resumed_from_checkpoint"])

    def test_gate_registry_schema_gate_blocks_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            invalid_path = storage.data_dir("raw") / "invalid-source.json"
            storage.write_json(invalid_path, {"type": "source_document", "id": "invalid-source", "content": {}})
            workflow = create_workflow_definition(
                storage,
                name="Schema Gate Registry",
                entry_node_id="schema",
                nodes=[
                    {
                        "node_id": "schema",
                        "node_type": "quality",
                        "operation": "schema",
                        "processor": {"kind": "deterministic"},
                        "quality_gate": {"required": True, "kind": "schema"},
                    }
                ],
            )

            result = execute_workflow(storage, workflow["path"], input_assets=[invalid_path])

            self.assertEqual(result["status"], "failed")
            self.assertIn("gate_result", _run_asset_types(storage))
            node_run = storage.read_asset(list_node_runs(storage, run_id=result["run_id"])[0]["path"])
            self.assertEqual(node_run.content["status"], "failed")
            self.assertIn("registry_results", node_run.content["quality_gate"])

    def test_scheduler_loop_records_task_status_and_worker_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            loop = run_workflow_scheduler_loop(storage, iterations=2, interval_seconds=0, stop_when_idle=True)

            self.assertEqual(loop["status"], "completed")
            self.assertEqual(loop["tick_count"], 1)
            self.assertGreaterEqual(len(loop["task_status_paths"]), 3)
            task_statuses = _run_assets_by_type(storage, "task_status")
            self.assertIn("workflow-scheduler-loop", {item["content"]["step"] for item in task_statuses})
            self.assertIn("completed", {item["content"]["status"] for item in task_statuses})

            from novel_forge.workers.tasks import workflow_scheduler_loop_task

            worker = workflow_scheduler_loop_task(tmp, iterations=1, interval_seconds=0, request_id="scheduler-worker-test")
            self.assertEqual(worker["status"], "completed")
            self.assertTrue(worker["task_status_paths"])

    def test_service_processor_registry_runs_quality_originality_and_continuity_services(self):
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
                    content={"chapter": 1, "text": "林乔推开档案室的门，发现旧钟声和失踪名单有关。她决定先救人，再追查幕后。", "copyright_boundary": "unit test original draft"},
                    references=[storage.read_asset(plan_path).id, str(plan_path.relative_to(storage.root))],
                ),
            )
            workflow = create_workflow_definition(
                storage,
                name="Service Registry Gates",
                entry_node_id="preflight",
                nodes=[
                    {
                        "node_id": "preflight",
                        "node_type": "continuity",
                        "operation": "chapter_stability_preflight",
                        "input_assets": [str(plan_path.relative_to(storage.root))],
                        "output_types": ["chapter_continuity_report"],
                        "processor": {"kind": "service"},
                    },
                    {
                        "node_id": "quality",
                        "node_type": "quality",
                        "operation": "quality_score_report",
                        "depends_on": ["preflight"],
                        "input_assets": [str(draft_path.relative_to(storage.root))],
                        "output_types": ["quality_score_report"],
                        "processor": {"kind": "service"},
                    },
                    {
                        "node_id": "originality",
                        "node_type": "quality",
                        "operation": "originality_report",
                        "depends_on": ["quality"],
                        "input_assets": [str(draft_path.relative_to(storage.root))],
                        "output_types": ["originality_report"],
                        "processor": {"kind": "service"},
                    },
                ],
            )

            result = execute_workflow(storage, workflow["path"])

            self.assertEqual(result["status"], "completed")
            output_types = {storage.read_asset(path).type for path in result["workflow_run"]["asset"]["content"]["outputs"]}
            self.assertIn("chapter_continuity_report", output_types)
            self.assertIn("quality_score_report", output_types)
            self.assertIn("originality_report", output_types)
            registry_operations = [storage.read_asset(row["path"]).content["processor"]["registry_operation"] for row in list_node_runs(storage, run_id=result["run_id"])]
            self.assertIn("chapter_stability_preflight", registry_operations)
            self.assertIn("quality_score_report", registry_operations)
            self.assertIn("originality_report", registry_operations)


def _run_asset_types(storage: LocalStorage) -> set[str]:
    types: set[str] = set()
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict):
            types.add(str(data.get("type", "")))
    return types


def _run_assets_by_type(storage: LocalStorage, asset_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        data = storage.read_json(path)
        if isinstance(data, dict) and data.get("type") == asset_type:
            rows.append(data)
    return rows


if __name__ == "__main__":
    unittest.main()
