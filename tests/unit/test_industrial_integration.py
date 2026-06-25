from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.infrastructure.settings import IndustrialSettings, optional_dependency_status
from novel_forge.storage.graph import neo4j_status
from novel_forge.storage.object_store import object_name_for_path
from novel_forge.storage.postgres import POSTGRES_SCHEMA_STATEMENTS, PostgresAssetStore
from novel_forge.storage.local import LocalStorage
from novel_forge.workers.runtime import list_dead_letters, write_dead_letter
from novel_forge.workflows.industrial import industrial_status


class IndustrialIntegrationTests(unittest.TestCase):
    def test_settings_from_env_maps_service_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = IndustrialSettings.from_env(
                {
                    "NOVEL_FORGE_DATABASE_URL": "postgresql://example",
                    "NOVEL_FORGE_REDIS_URL": "redis://example/0",
                    "NOVEL_FORGE_ENABLE_NEO4J": "true",
                    "NOVEL_FORGE_NEO4J_URI": "bolt://example:7687",
                    "NOVEL_FORGE_NEO4J_PASSWORD": "secret",
                    "NOVEL_FORGE_POSTGRES_WRITE_STRICT": "true",
                    "NOVEL_FORGE_API_CORS_ORIGINS": "http://localhost:3000,http://localhost:3001",
                },
                root=tmp,
            )

            self.assertEqual(settings.root, Path(tmp).resolve())
            self.assertTrue(settings.configured_services()["postgresql"])
            self.assertTrue(settings.configured_services()["neo4j"])
            self.assertTrue(settings.postgres_write_through)
            self.assertTrue(settings.postgres_write_strict)
            self.assertEqual(settings.api_cors_origins, ("http://localhost:3000", "http://localhost:3001"))

    def test_settings_loads_dotenv_from_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "NOVEL_FORGE_DATABASE_URL=postgresql://from-file\n"
                "NOVEL_FORGE_API_PORT=8123\n",
                encoding="utf-8",
            )

            settings = IndustrialSettings.from_env({}, root=tmp)

            self.assertEqual(settings.database_url, "postgresql://from-file")
            self.assertEqual(settings.api_port, 8123)

    def test_industrial_status_is_available_without_optional_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = industrial_status(tmp)

            self.assertEqual(status["root"], str(Path(tmp).resolve()))
            self.assertIn("raw", status["local_counts"])
            self.assertIn("postgresql", status["configured_services"])
            self.assertIn("fastapi", status["optional_dependencies"])
            self.assertIn("reason", status["neo4j"])

    def test_optional_dependency_status_reports_expected_keys(self):
        status = optional_dependency_status()

        for key in ["fastapi", "psycopg", "celery", "qdrant_client", "minio", "neo4j"]:
            self.assertIn(key, status)
            self.assertIsInstance(status[key], bool)

    def test_postgres_schema_declares_asset_version_and_task_tables(self):
        schema = "\n".join(POSTGRES_SCHEMA_STATEMENTS)

        self.assertIn("nf_assets", schema)
        self.assertIn("nf_asset_versions", schema)
        self.assertIn("nf_task_statuses", schema)
        self.assertIn("nf_projects", schema)
        self.assertIn("path TEXT", schema)
        self.assertIn("project_id TEXT", schema)
        self.assertIn("workspace_path TEXT", schema)
        with self.assertRaises(ValueError):
            PostgresAssetStore("")

    def test_worker_dead_letter_is_schema_backed_and_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_dead_letter(
                root=tmp,
                task_name="novel_forge.fixture",
                task_id="task-1",
                args=(tmp, "input"),
                kwargs={"flag": True},
                exc=RuntimeError("fixture failure"),
            )
            rows = list_dead_letters(tmp)
            data = LocalStorage(tmp).read_json(path)

            self.assertEqual(data["type"], "task_dead_letter")
            self.assertEqual(rows[0]["task_name"], "novel_forge.fixture")
            self.assertIn("fixture failure", rows[0]["error_message"])

    def test_object_name_for_path_preserves_project_relative_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            path = storage.data_dir("raw") / "asset.json"
            path.write_text("{}", encoding="utf-8")

            self.assertEqual(object_name_for_path(storage, path), "data/raw/asset.json")

    def test_neo4j_is_disabled_by_default(self):
        settings = IndustrialSettings.from_env({}, root=".")
        status = neo4j_status(settings)

        self.assertFalse(status["enabled"])
        self.assertIn("disabled", status["reason"])


if __name__ == "__main__":
    unittest.main()
