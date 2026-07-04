from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_runs import start_agent_run, update_agent_run_status
from novel_forge.modules.clickhouse_analytics import analytics_capabilities, analytics_dashboard_snapshot, clickhouse_schema_plan, migrate_clickhouse, sync_analytics
from novel_forge.modules.clickhouse_analytics.service import _clickhouse_datetime
from novel_forge.storage.local import LocalStorage


class ClickHouseAnalyticsTests(unittest.TestCase):
    def test_clickhouse_defaults_to_offline_snapshot_without_external_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            capabilities = analytics_capabilities(storage)
            plan = clickhouse_schema_plan(storage, persist=False)
            migration = migrate_clickhouse(storage, dry_run=True)

            self.assertFalse(capabilities["online_enabled"])
            self.assertEqual(capabilities["status"], "offline_ready")
            self.assertIn("analytics_events", plan["content"]["query"])
            self.assertEqual(migration["status"], "planned")

    def test_local_assets_project_into_analytics_events_and_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            run = start_agent_run(storage, agent_key="draft", operation="draft", status="running", evidence={"trace": {"trace_id": "trace-analytics"}}, workspace_path="")
            update_agent_run_status(storage, run["path"], status="succeeded", event_type="agent_run.succeeded", message="done")

            sync = sync_analytics(storage, project_id="", online=False)
            dashboard = analytics_dashboard_snapshot(storage)

            self.assertGreaterEqual(sync["event_count"], 1)
            self.assertEqual(sync["asset"]["type"], "analytics_sync_job")
            self.assertEqual(dashboard["asset"]["type"], "analytics_dashboard_snapshot")
            self.assertIn("agent", dashboard["asset"]["content"]["metrics"])

    def test_clickhouse_datetime_uses_clickhouse_json_each_row_format(self):
        value = _clickhouse_datetime("2026-07-04T07:19:16+00:00")

        self.assertEqual(value, "2026-07-04 07:19:16.000")
