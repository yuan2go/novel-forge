from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit_log import build_audit_trail, create_audit_export_package, list_audit_events, record_audit_event
from novel_forge.modules.model_router import create_model_route, execute_model_gateway_call
from novel_forge.modules.operation_transactions import apply_rollback_plan, create_operation_transaction, preview_operation_rollback
from novel_forge.modules.tool_gateway import invoke_tool, register_internal_tools
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class AuditLogTests(unittest.TestCase):
    def test_audit_log_queries_by_project_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            record_audit_event(storage, event_type="agent_run", action="started", actor_id="draft", project_id="audit-p", trace_id="trace-1")
            record_audit_event(storage, event_type="publish_gate", action="blocked", actor_id="quality", project_id="audit-p", trace_id="trace-1", blocking=True)
            record_audit_event(storage, event_type="agent_run", action="started", actor_id="draft", project_id="other", trace_id="trace-2")

            rows = list_audit_events(storage, project_id="audit-p", trace_id="trace-1")
            trail = build_audit_trail(storage, project_id="audit-p", trace_id="trace-1")

            self.assertEqual(len(rows), 2)
            self.assertEqual(trail["status"], "blocked")
            self.assertEqual(trail["event_count"], 2)

    def test_audit_export_removes_raw_source_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            record_audit_event(
                storage,
                event_type="mkaos",
                action="query",
                project_id="audit-p",
                trace_id="trace-raw",
                metadata={"raw_text": "must not export", "note": "source_chunk.raw_text blocked"},
            )

            package = create_audit_export_package(storage, project_id="audit-p", trace_id="trace-raw")
            text = str(package["asset"]["content"])

            self.assertIn("[removed]", text)
            self.assertNotIn("must not export", text)
            self.assertFalse(package["asset"]["content"]["source_isolation"]["raw_source_text_included"])

    def test_model_and_tool_gateway_emit_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(storage, task_type="audit-task", provider="mock", model_name="mock-audit", project_id="audit-p")

            execute_model_gateway_call(
                storage,
                task_type="audit-task",
                operation="audit_model_call",
                project_id="audit-p",
                usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                trace={"trace_id": "trace-governance"},
            )
            register_internal_tools(storage, project_id="audit-p")
            invoke_tool(
                storage,
                tool_name="trace.timeline",
                input_payload={"trace_id": "trace-governance"},
                agent_type="audit-agent",
                operation="audit-tool",
                project_id="audit-p",
                trace={"trace_id": "trace-governance"},
            )

            model_events = list_audit_events(storage, project_id="audit-p", trace_id="trace-governance", event_type="model_gateway")
            tool_events = list_audit_events(storage, project_id="audit-p", trace_id="trace-governance", event_type="tool_gateway")

            self.assertTrue(model_events)
            self.assertTrue(tool_events)
            self.assertEqual(model_events[0]["content"]["target"]["operation"], "audit_model_call")
            self.assertEqual(tool_events[0]["content"]["target"]["tool_name"], "trace.timeline")

    def test_operation_rollback_emits_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Rollback target", content={"chapter": 1, "text": "rollback target"}, metadata={"project_id": "audit-rollback-p"}),
            )
            transaction = create_operation_transaction(
                storage,
                operation="audit-rollback-operation",
                created_assets=[str(draft_path.relative_to(storage.root))],
                project_id="audit-rollback-p",
                trace={"trace_id": "trace-rollback"},
            )
            plan = preview_operation_rollback(storage, transaction["path"], reason="unit rollback")
            apply_rollback_plan(storage, plan["path"], confirm=True, actor="unit-test")

            events = list_audit_events(storage, project_id="audit-rollback-p", trace_id="trace-rollback", event_type="rollback")
            actions = {event["content"]["action"] for event in events}

            self.assertIn("rollback_plan_previewed", actions)
            self.assertIn("rollback_plan_applied", actions)
