from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from unittest.mock import patch

from novel_forge.modules.production_kernel import dispatch_production_operation, production_entrypoints, require_production_entrypoint
from novel_forge.schemas import ProductionOperation, validate_common_fields
from novel_forge.storage.local import LocalStorage


class ProductionEntrypointContractTests(unittest.TestCase):
    def test_production_operation_schema_requires_envelope_and_child_projection(self):
        asset = ProductionOperation(
            title="Kernel operation",
            metadata={"project_id": "project-a", "workspace_path": "/tmp/project-a"},
            content={
                "operation_id": "op-1",
                "operation": "loop.run",
                "state_owner": "loop_run",
                "status": "running",
                "idempotency_key": "idem-1",
                "request_digest": "digest-1",
                "execution_envelope": {
                    "project_id": "project-a",
                    "operation": "loop.run",
                    "idempotency_key": "idem-1",
                    "trace_id": "trace-1",
                    "environment": "local",
                },
                "input_refs": [],
                "expected_output_types": ["loop_run"],
                "child": {"status": "running"},
                "created_at": "2026-07-11T00:00:00+00:00",
                "updated_at": "2026-07-11T00:00:00+00:00",
            },
        )
        self.assertEqual(validate_common_fields(asset.to_dict()), [])

        invalid = asset.to_dict()
        invalid["content"] = {**invalid["content"], "status": "unknown", "execution_envelope": {}}
        errors = validate_common_fields(invalid)
        self.assertIn("production_operation status is invalid", errors)
        self.assertIn("production_operation execution_envelope missing project_id", errors)

    def test_every_registered_entrypoint_declares_one_state_owner_and_policy(self):
        entries = production_entrypoints()
        self.assertTrue(entries)
        self.assertEqual(len({entry["operation"] for entry in entries}), len(entries))
        for entry in entries:
            self.assertTrue(entry["state_owner"])
            self.assertEqual(entry["parent_state_owner"], "production_operation")
            self.assertEqual(entry["envelope_policy"], "required_in_production")
            self.assertEqual(entry["kernel_route"], "dispatch_production_operation")

    def test_workflow_agent_and_loop_commands_use_one_kernel_dispatcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            with patch("novel_forge.modules.workflow_nodes.execute_workflow", return_value={"status": "workflow"}) as workflow:
                result = dispatch_production_operation(storage, "workflow.execute", workflow_path_or_id="workflow.json")
                self.assertEqual(result["status"], "workflow")
                workflow.assert_called_once()
            with patch("novel_forge.modules.agent_scheduler.dispatch_agent_run", return_value={"status": "agent"}) as agent:
                result = dispatch_production_operation(storage, "agent.dispatch", agent_run_path="runs/agent.json")
                self.assertEqual(result["status"], "agent")
                agent.assert_called_once()
            with patch("novel_forge.modules.loop_kernel.run_loop", return_value={"status": "loop"}) as loop:
                result = dispatch_production_operation(storage, "loop.run", loop_type="chapter_review")
                self.assertEqual(result["status"], "loop")
                loop.assert_called_once()

    def test_kernel_persists_parent_and_replays_duplicate_idempotency_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            with patch("novel_forge.modules.loop_kernel.run_loop", return_value={"status": "loop", "run_id": "loop-1"}) as loop:
                first = dispatch_production_operation(storage, "loop.run", project_id="project-a", loop_type="chapter_review")
                second = dispatch_production_operation(storage, "loop.run", project_id="project-a", loop_type="chapter_review")

            self.assertEqual(loop.call_count, 1)
            self.assertFalse(first.get("replayed", False))
            self.assertTrue(second["replayed"])
            self.assertEqual(first["production_operation_path"], second["production_operation_path"])
            parent = storage.read_json(storage.root / first["production_operation_path"])
            self.assertEqual(parent["type"], "production_operation")
            self.assertEqual(parent["metadata"]["project_id"], "project-a")
            self.assertEqual(parent["content"]["status"], "completed")
            self.assertEqual(parent["content"]["child"]["state_owner"], "loop_run")
            self.assertEqual(parent["content"]["execution_envelope"]["project_id"], "project-a")

    def test_kernel_rejects_same_idempotency_key_for_different_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            envelope = {
                "schema_version": 2,
                "project_ref": "project-a",
                "task_ref": "chapter-1",
                "idempotency_key": "idem-fixed",
                "source": "unit-test",
                "source_policy": {"raw_source_text_allowed": False},
                "environment": "local",
            }
            with patch("novel_forge.modules.loop_kernel.run_loop", return_value={"status": "loop"}) as loop:
                dispatch_production_operation(storage, "loop.run", envelope=envelope, loop_type="chapter_review")
                with self.assertRaisesRegex(ValueError, "idempotency conflict"):
                    dispatch_production_operation(storage, "loop.run", envelope=envelope, loop_type="different_request")
            loop.assert_called_once()

    def test_kernel_persists_failed_parent_with_recovery_instruction_when_child_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            with patch("novel_forge.modules.loop_kernel.run_loop", side_effect=RuntimeError("provider timeout")):
                with self.assertRaisesRegex(RuntimeError, "provider timeout"):
                    dispatch_production_operation(storage, "loop.run", project_id="project-a", loop_type="chapter_review")

            parents = [storage.read_json(path) for path in storage.list_json("runs") if storage.read_json(path).get("type") == "production_operation"]
            self.assertEqual(len(parents), 1)
            self.assertEqual(parents[0]["content"]["status"], "failed")
            self.assertEqual(parents[0]["content"]["error"]["type"], "RuntimeError")
            self.assertIn("recovery_instruction", parents[0]["content"]["error"])

    def test_kernel_dispatcher_rejects_production_commands_without_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                dispatch_production_operation(storage, "loop.run", environment="production", project_id="kernel-p", loop_type="chapter_review")

    def test_chapter_kernel_returns_structured_failure_when_write_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            with patch("novel_forge.modules.chapter_production_bus.start_chapter_production") as start:
                def over_budget(storage_arg, **_kwargs):
                    storage_arg.write_json("data/indexes/kernel-budget-one.json", {"status": "one"})
                    storage_arg.write_json("data/indexes/kernel-budget-two.json", {"status": "two"})
                    return {"status": "succeeded"}

                start.side_effect = over_budget
                result = dispatch_production_operation(
                    storage,
                    "chapter_production.start",
                    environment="local",
                    write_budget={"max_file_writes": 1},
                )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_type"], "write_budget_exceeded")
        self.assertEqual(result["write_budget"]["metrics"]["file_writes"], 2)
        self.assertEqual(result["write_budget"]["status"], "failed")

    def test_unknown_production_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unregistered production operation"):
            require_production_entrypoint("unbounded.side.effect")


if __name__ == "__main__":
    unittest.main()
