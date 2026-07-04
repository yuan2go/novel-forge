from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.clickhouse_analytics import clickhouse_online_e2e_smoke
from novel_forge.modules.pgvector_store import pgvector_online_e2e_smoke
from novel_forge.storage.local import LocalStorage


class OnlineServiceSmokeTests(unittest.TestCase):
    def setUp(self):
        self._pgvector_online = os.environ.get("NOVEL_FORGE_PGVECTOR_ONLINE")
        self._clickhouse_online = os.environ.get("NOVEL_FORGE_CLICKHOUSE_ONLINE")
        os.environ.pop("NOVEL_FORGE_PGVECTOR_ONLINE", None)
        os.environ.pop("NOVEL_FORGE_CLICKHOUSE_ONLINE", None)

    def tearDown(self):
        if self._pgvector_online is None:
            os.environ.pop("NOVEL_FORGE_PGVECTOR_ONLINE", None)
        else:
            os.environ["NOVEL_FORGE_PGVECTOR_ONLINE"] = self._pgvector_online
        if self._clickhouse_online is None:
            os.environ.pop("NOVEL_FORGE_CLICKHOUSE_ONLINE", None)
        else:
            os.environ["NOVEL_FORGE_CLICKHOUSE_ONLINE"] = self._clickhouse_online

    def test_pgvector_smoke_defaults_to_local_projection_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = pgvector_online_e2e_smoke(storage, project_id="online-smoke-p")

            self.assertEqual(result["asset"]["type"], "local_ops_drill_report")
            self.assertEqual(result["status"], "warning")
            self.assertIn("online pgvector disabled", str(result["content"]["results"]))

    def test_clickhouse_smoke_defaults_to_offline_dashboard_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = clickhouse_online_e2e_smoke(storage, project_id="online-smoke-p")

            self.assertEqual(result["asset"]["type"], "local_ops_drill_report")
            self.assertEqual(result["status"], "warning")
            self.assertIn("online ClickHouse disabled", str(result["content"]["results"]))
