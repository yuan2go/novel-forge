from pathlib import Path
import sys
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
            self.assertEqual(entry["envelope_policy"], "required_in_production")
            self.assertEqual(entry["kernel_route"], "dispatch_production_operation")

    def test_workflow_agent_and_loop_commands_use_one_kernel_dispatcher(self):
        storage = LocalStorage("/tmp/novel-forge-kernel-routing-tests")
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

    def test_kernel_dispatcher_rejects_production_commands_without_envelope(self):
        storage = LocalStorage("/tmp/novel-forge-kernel-routing-production-tests")
        with self.assertRaisesRegex(ValueError, "OS envelope required"):
            dispatch_production_operation(storage, "loop.run", environment="production", project_id="kernel-p", loop_type="chapter_review")

    def test_chapter_kernel_returns_structured_failure_when_write_budget_is_exceeded(self):
        storage = LocalStorage("/tmp/novel-forge-kernel-write-budget-tests")
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
