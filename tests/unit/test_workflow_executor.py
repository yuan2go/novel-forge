from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import list_agent_runs
from novel_forge.modules.workflow_nodes import create_workflow_definition, execute_workflow, list_node_runs
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


if __name__ == "__main__":
    unittest.main()
