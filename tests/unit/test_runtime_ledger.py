from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.runtime_ledger import (
    create_agent_cost_snapshot,
    create_chapter_cost_snapshot,
    create_cost_quality_dashboard,
    create_project_cost_snapshot,
    list_cost_ledgers,
    record_model_call_log,
    record_trace_span,
    trace_timeline_payload,
)
from novel_forge.schemas import validate_common_fields
from novel_forge.storage.local import LocalStorage


class RuntimeLedgerTests(unittest.TestCase):
    def test_trace_timeline_and_cost_snapshots_are_schema_backed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            project_id = "runtime-project"
            trace = {"trace_id": "trace-runtime", "span_id": "span-model", "parent_span_id": "trace-runtime"}

            model_call = record_model_call_log(
                storage,
                provider="local",
                model="codex-local",
                operation="draft_chapter",
                status="succeeded",
                usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                cost={"amount": 0.25, "currency": "USD", "source": "unit_test"},
                trace=trace,
                project_id=project_id,
                source_id="agent-run-1",
            )
            record_trace_span(storage, trace_id="trace-runtime", span_type="context_bundle", name="create_context_bundle", project_id=project_id)
            record_trace_span(storage, trace_id="trace-runtime", span_type="feedback", name="create_reader_sentiment_report", project_id=project_id)

            ledgers = list_cost_ledgers(storage, project_id=project_id)
            timeline = trace_timeline_payload(storage, trace_id="trace-runtime", project_id=project_id)
            project_snapshot = create_project_cost_snapshot(storage, project_id=project_id)
            agent_snapshot = create_agent_cost_snapshot(storage, project_id=project_id)
            chapter_snapshot = create_chapter_cost_snapshot(storage, project_id=project_id, chapter=1)
            dashboard = create_cost_quality_dashboard(storage, project_id=project_id, chapter=1)

            self.assertTrue(model_call["path"])
            self.assertEqual(len(ledgers), 1)
            self.assertGreaterEqual(timeline["summary"]["span_count"], 4)
            self.assertIn("model_call", timeline["summary"]["by_type"])
            self.assertIn("cost", timeline["summary"]["by_type"])
            self.assertIn("context_bundle", timeline["summary"]["by_type"])
            self.assertIn("feedback", timeline["summary"]["by_type"])
            for result in [project_snapshot, agent_snapshot, chapter_snapshot, dashboard]:
                asset = result["asset"]
                self.assertEqual(validate_common_fields(asset), [])
            self.assertEqual(project_snapshot["asset"]["type"], "project_cost_snapshot")
            self.assertEqual(agent_snapshot["asset"]["type"], "agent_cost_snapshot")
            self.assertEqual(chapter_snapshot["asset"]["type"], "chapter_cost_snapshot")
            self.assertEqual(dashboard["asset"]["type"], "cost_quality_dashboard")
            self.assertEqual(dashboard["asset"]["content"]["summary"]["total_cost"], 0.25)


if __name__ == "__main__":
    unittest.main()
