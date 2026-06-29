from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_messages import acknowledge_agent_message, create_agent_conversation_trace, replay_agent_messages, send_agent_message
from novel_forge.modules.long_memory import create_memory_record, retrieve_memory, select_memory_for_node
from novel_forge.modules.model_router import create_model_route, execute_model_gateway_call, resolve_model_route
from novel_forge.modules.pgvector_store import build_embedding_job, create_pgvector_schema_plan, hybrid_retrieve
from novel_forge.modules.prompt_registry import bind_prompt_to_node, create_prompt_version_asset, release_prompt_version, resolve_prompt
from novel_forge.modules.state_bus import create_state_snapshot, detect_state_conflicts, record_state_event, replay_state_events
from novel_forge.modules.tool_gateway import create_tool_permission_policy, invoke_tool, register_internal_tools
from novel_forge.schemas import ChapterPlan
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import build_rag_context


class NovelOSNewCapabilitiesTests(unittest.TestCase):
    def test_prompt_registry_and_model_router_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "os-project"

            prompt = create_prompt_version_asset(
                storage,
                prompt_id="draft.chapter",
                version="v1",
                task_type="draft",
                template="Write chapter with {{context}}",
                status="active",
                project_id=project_id,
            )
            release = release_prompt_version(storage, prompt_id="draft.chapter", version="v1", task_type="draft", project_id=project_id)
            binding = bind_prompt_to_node(storage, prompt_id="draft.chapter", version="v1", workflow_node_id="draft-node", task_type="draft", project_id=project_id)
            route = create_model_route(storage, task_type="draft", provider="mock", model_name="mock-draft", selection_rule="cost_first", project_id=project_id)

            resolved_prompt = resolve_prompt(storage, task_type="draft", workflow_node_id="draft-node", project_id=project_id)
            resolved_route = resolve_model_route(storage, task_type="draft", workflow_node_id="draft-node", project_id=project_id)

            self.assertEqual(prompt["asset"]["type"], "prompt_version")
            self.assertEqual(release["asset"]["type"], "prompt_release")
            self.assertEqual(binding["asset"]["type"], "prompt_node_binding")
            self.assertEqual(route["asset"]["type"], "model_route")
            self.assertEqual(resolved_prompt["status"], "resolved")
            self.assertEqual(resolved_prompt["prompt_path"], prompt["path"])
            self.assertEqual(resolved_route["resolution"]["provider"], "mock")
            self.assertEqual(resolved_route["asset"]["type"], "model_route_resolution")

    def test_model_gateway_records_provider_guard_checkpoint_and_cost_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "os-project"
            trace = {"trace_id": "trace-gateway", "span_id": "span-gateway", "parent_span_id": "trace-gateway"}
            create_model_route(storage, task_type="benchmark", provider="mock", model_name="mock-benchmark", project_id=project_id)

            result = execute_model_gateway_call(
                storage,
                task_type="benchmark",
                operation="model_benchmark",
                project_id=project_id,
                usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "usage_source": "unit_provider"},
                provider_runtime_guard={"max_total_tokens": 200, "cost_profile": {"input_per_1k": 0.01, "output_per_1k": 0.02, "currency": "USD"}},
                trace=trace,
            )

            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["model_call"]["asset"]["type"], "model_call_log")
            self.assertEqual(result["model_call"]["asset"]["content"]["operation"], "model_benchmark")
            self.assertIn("cost_ledger", result["model_call"])
            rows = [storage.read_json(path) for path in storage.list_json("runs")]
            checkpoints = [row for row in rows if row.get("type") == "agent_checkpoint" and row.get("content", {}).get("operation") == "model_benchmark"]
            stages = {row["content"]["stage"] for row in checkpoints}
            self.assertTrue({"prompt_built", "provider_started", "provider_completed", "output_validated"}.issubset(stages))
            provider_gates = [row for row in rows if row.get("type") == "gate_result" and row.get("content", {}).get("gate_kind") == "provider_runtime_guard"]
            self.assertTrue(provider_gates)

    def test_model_gateway_records_failed_call_when_provider_guard_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(storage, task_type="benchmark", provider="mock", model_name="mock-benchmark", project_id="os-project")

            with self.assertRaises(RuntimeError):
                execute_model_gateway_call(
                    storage,
                    task_type="benchmark",
                    operation="model_benchmark",
                    project_id="os-project",
                    usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                    provider_runtime_guard={"max_total_tokens": 100},
                    trace={"trace_id": "trace-gateway-fail"},
                )

            rows = [storage.read_json(path) for path in storage.list_json("runs")]
            failed_calls = [row for row in rows if row.get("type") == "model_call_log" and row.get("content", {}).get("status") == "failed"]
            failed_gates = [row for row in rows if row.get("type") == "gate_result" and row.get("content", {}).get("gate_kind") == "provider_runtime_guard" and row.get("content", {}).get("status") == "failed"]
            self.assertTrue(failed_calls)
            self.assertTrue(failed_gates)

    def test_tool_gateway_state_bus_and_agent_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "os-project"

            registered = register_internal_tools(storage, project_id=project_id)
            self.assertGreaterEqual(registered["count"], 5)
            create_tool_permission_policy(storage, tool_id="trace.timeline", agent_types=["workflow"], project_id=project_id)
            invocation = invoke_tool(
                storage,
                tool_name="trace.timeline",
                input_payload={"trace_id": "trace-os"},
                agent_type="workflow",
                project_id=project_id,
                trace={"trace_id": "trace-os"},
            )
            self.assertEqual(invocation["asset"]["type"], "tool_invocation")
            self.assertEqual(invocation["status"], "succeeded")

            first = record_state_event(storage, stream="workflow", subject_id="wf-1", event_type="created", payload={"status": "running"}, expected_version=0, project_id=project_id)
            conflict = record_state_event(storage, stream="workflow", subject_id="wf-1", event_type="patched", payload={"status": "paused"}, expected_version=0, project_id=project_id)
            snapshot = create_state_snapshot(storage, stream="workflow", subject_id="wf-1", project_id=project_id)
            replay = replay_state_events(storage, stream="workflow", subject_id="wf-1", project_id=project_id)
            report = detect_state_conflicts(storage, stream="workflow", subject_id="wf-1", project_id=project_id)
            self.assertFalse(first["conflict"])
            self.assertTrue(conflict["conflict"])
            self.assertEqual(snapshot["asset"]["type"], "state_snapshot")
            self.assertEqual(replay["asset"]["type"], "state_replay")
            self.assertEqual(report["asset"]["content"]["status"], "conflicts_found")

            message = send_agent_message(
                storage,
                sender_agent="workflow",
                recipient_agent="review",
                topic="review_ready",
                payload={"draft_path": "data/drafts/example.json"},
                conversation_id="conv-1",
                project_id=project_id,
            )
            ack = acknowledge_agent_message(storage, message["path"], actor_agent="review")
            replay_messages = replay_agent_messages(storage, conversation_id="conv-1", project_id=project_id)
            trace = create_agent_conversation_trace(storage, conversation_id="conv-1", project_id=project_id)
            self.assertEqual(ack["asset"]["content"]["status"], "acknowledged")
            self.assertEqual(replay_messages["message_count"], 1)
            self.assertEqual(trace["asset"]["type"], "agent_conversation_trace")

    def test_long_memory_pgvector_and_context_hybrid_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "os-project"

            memory = create_memory_record(
                storage,
                project_id=project_id,
                level="L4",
                memory_type="location",
                title="Clock City",
                summary="Clock City controls time gates and protagonist access rules.",
                content={"rule": "time gates require blue seals"},
                priority=9,
            )
            retrieval = retrieve_memory(storage, query="time gates", project_id=project_id)
            selection = select_memory_for_node(storage, target_node="draft-node", task_type="draft", project_id=project_id, query="Clock City")
            schema_plan = create_pgvector_schema_plan(storage, project_id=project_id)
            embedding = build_embedding_job(storage, source_paths=[memory["path"]], project_id=project_id)
            hybrid = hybrid_retrieve(storage, query="blue seals", project_id=project_id)

            self.assertEqual(memory["asset"]["type"], "memory_record")
            self.assertTrue(retrieval["results"])
            self.assertTrue(selection["results"])
            self.assertEqual(schema_plan["asset"]["type"], "pgvector_schema_plan")
            self.assertEqual(embedding["asset"]["type"], "embedding_job")
            self.assertTrue(hybrid["results"])

            chapter_plan_path = storage.write_asset_auto(
                ChapterPlan(
                    title="Chapter plan",
                    content={"chapter": 1, "objective": "enter Clock City", "beats": ["gate", "seal"], "hook": "the clock stops"},
                    metadata={"project_id": project_id},
                )
            )
            context = build_rag_context(
                storage,
                storage.read_asset(chapter_plan_path),
                input_path=chapter_plan_path,
                query="Clock City blue seals",
                top_k=4,
                backend="hybrid",
            )
            self.assertEqual(context["requested_backend"], "hybrid")
            self.assertIn(context["retrieval_backend"], {"hybrid", "local", "scan"})


if __name__ == "__main__":
    unittest.main()
