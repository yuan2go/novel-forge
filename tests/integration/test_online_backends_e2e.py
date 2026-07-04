from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.clickhouse_analytics import clickhouse_online_e2e_smoke
from novel_forge.modules.pgvector_store import pgvector_online_e2e_smoke
from novel_forge.storage.local import LocalStorage


@unittest.skipUnless(
    os.environ.get("NOVEL_FORGE_PGVECTOR_ONLINE") in {"1", "true", "yes", "on", "enabled"}
    and os.environ.get("NOVEL_FORGE_CLICKHOUSE_ONLINE") in {"1", "true", "yes", "on", "enabled"},
    "online pgvector and ClickHouse E2E requires explicit opt-in env vars",
)
class OnlineBackendsE2ETests(unittest.TestCase):
    def test_pgvector_and_clickhouse_online_smoke_require_real_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            pgvector = pgvector_online_e2e_smoke(storage, project_id="online-e2e-p", require_online=True)
            clickhouse = clickhouse_online_e2e_smoke(storage, project_id="online-e2e-p", require_online=True)

            self.assertNotEqual(pgvector["status"], "failed")
            self.assertNotEqual(clickhouse["status"], "failed")


if __name__ == "__main__":
    unittest.main()
