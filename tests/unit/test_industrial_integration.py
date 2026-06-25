from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.infrastructure.settings import IndustrialSettings, optional_dependency_status
from novel_forge.storage.graph import neo4j_status
from novel_forge.storage.object_store import object_name_for_path
from novel_forge.storage.postgres import POSTGRES_SCHEMA_STATEMENTS, PostgresAssetStore
from novel_forge.storage.qdrant_index import build_qdrant_index
from novel_forge.storage.local import LocalStorage
from novel_forge.schemas import SourceDocument
from novel_forge.workers.runtime import list_dead_letters, sync_postgres_after_task, write_dead_letter
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

    def test_settings_loads_cwd_dotenv_with_separate_runtime_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            runtime = repo / ".local" / "workspace"
            runtime.mkdir(parents=True)
            (repo / ".env").write_text(
                "NOVEL_FORGE_ROOT=.local/workspace\n"
                "NOVEL_FORGE_DATABASE_URL=postgresql://from-cwd-file\n"
                "NOVEL_FORGE_API_PORT=8123\n",
                encoding="utf-8",
            )
            (runtime / ".env").write_text("NOVEL_FORGE_API_PORT=8124\n", encoding="utf-8")
            cwd = os.getcwd()
            try:
                os.chdir(repo)
                settings = IndustrialSettings.from_env({}, root=runtime)
            finally:
                os.chdir(cwd)

            self.assertEqual(settings.root, runtime.resolve())
            self.assertEqual(settings.database_url, "postgresql://from-cwd-file")
            self.assertEqual(settings.api_port, 8124)

    def test_settings_does_not_inherit_cwd_dotenv_for_external_runtime_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            runtime = Path(tmp) / "external-runtime"
            repo.mkdir()
            runtime.mkdir()
            (repo / ".env").write_text(
                "NOVEL_FORGE_DATABASE_URL=postgresql://from-cwd-file\n",
                encoding="utf-8",
            )
            cwd = os.getcwd()
            try:
                os.chdir(repo)
                settings = IndustrialSettings.from_env({}, root=runtime)
            finally:
                os.chdir(cwd)

            self.assertEqual(settings.root, runtime.resolve())
            self.assertEqual(settings.database_url, "")

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

    def test_worker_postgres_sync_failure_dead_letters_or_raises_in_strict_mode(self):
        class FailingStore:
            def sync_asset(self, *_args, **_kwargs):
                raise RuntimeError("postgres sync down")

            def sync_from_local(self, *_args, **_kwargs):
                raise RuntimeError("postgres sync down")

        with tempfile.TemporaryDirectory() as tmp:
            env = {"NOVEL_FORGE_DATABASE_URL": "postgresql://example", "NOVEL_FORGE_POSTGRES_WRITE_STRICT": ""}
            with patch.dict(os.environ, env, clear=False), patch(
                "novel_forge.workers.runtime.PostgresAssetStore.from_settings",
                return_value=FailingStore(),
            ):
                sync_postgres_after_task(tmp, {"path": "data/raw/missing.json"})
            rows = list_dead_letters(tmp)
            self.assertEqual(rows[0]["task_name"], "novel_forge.postgres_sync_after_task")
            self.assertIn("postgres sync down", rows[0]["error_message"])

            with patch.dict(os.environ, {**env, "NOVEL_FORGE_POSTGRES_WRITE_STRICT": "true"}, clear=False), patch(
                "novel_forge.workers.runtime.PostgresAssetStore.from_settings",
                return_value=FailingStore(),
            ):
                with self.assertRaises(RuntimeError):
                    sync_postgres_after_task(tmp, {"path": "data/raw/missing.json"})

    def test_qdrant_index_batches_embeddings_and_rejects_dimension_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            storage.write_asset("raw", SourceDocument(title="Qdrant A", source="a.txt", content={"text": "alpha"}))
            storage.write_asset("raw", SourceDocument(title="Qdrant B", source="b.txt", content={"text": "beta"}))
            settings = IndustrialSettings(root=Path(tmp).resolve(), qdrant_collection="fixture")
            adapter = FakeEmbeddingAdapter(dimensions=3)
            client = FakeQdrantClient(existing=False, existing_size=3)

            with patch("novel_forge.storage.qdrant_index._qdrant_client", return_value=(client, FakeQdrantModels)):
                result = build_qdrant_index(storage, settings, adapter=adapter, batch_size=2)
                cached = build_qdrant_index(storage, settings, adapter=adapter, batch_size=2)

            self.assertEqual(result["indexed"], 2)
            self.assertEqual(result["embedded"], 2)
            self.assertEqual(cached["cache_hits"], 2)
            self.assertEqual(adapter.embed_batch_calls, 1)
            self.assertTrue((Path(tmp) / "data/indexes/qdrant-index-manifest.json").exists())

            mismatched = FakeQdrantClient(existing=True, existing_size=64)
            with patch("novel_forge.storage.qdrant_index._qdrant_client", return_value=(mismatched, FakeQdrantModels)):
                with self.assertRaises(RuntimeError):
                    build_qdrant_index(storage, settings, adapter=adapter)
                migrated = build_qdrant_index(storage, settings, adapter=adapter, recreate_collection=True)

            self.assertTrue(migrated["collection_status"]["recreated"])

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


class FakeEmbeddingAdapter:
    name = "fake-embedding"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.embed_batch_calls = 0

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.embed_batch_calls += 1
        return [[1.0, 0.0, 0.0] for _ in texts]

    def health_check(self) -> dict:
        return {
            "ok": True,
            "model": self.name,
            "provider": "fake",
            "dimensions": self.dimensions,
            "semantic_model": True,
            "external_api": False,
        }


class FakeQdrantClient:
    def __init__(self, existing: bool, existing_size: int) -> None:
        self.existing = existing
        self.existing_size = existing_size
        self.points = []
        self.deleted = False

    def collection_exists(self, collection: str) -> bool:
        return self.existing and not self.deleted

    def get_collection(self, collection_name: str):
        return FakeQdrantInfo(self.existing_size)

    def create_collection(self, collection_name: str, vectors_config):
        self.existing = True
        self.existing_size = vectors_config.size

    def delete_collection(self, collection_name: str):
        self.deleted = True
        self.existing = False

    def upsert(self, collection_name: str, points: list):
        self.points.extend(points)


class FakeQdrantInfo:
    def __init__(self, size: int) -> None:
        self.config = type("Config", (), {"params": type("Params", (), {"vectors": type("Vectors", (), {"size": size})()})()})()


class FakeQdrantModels:
    class Distance:
        COSINE = "Cosine"

    class VectorParams:
        def __init__(self, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    class PointStruct:
        def __init__(self, id: int, vector: list[float], payload: dict) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload
