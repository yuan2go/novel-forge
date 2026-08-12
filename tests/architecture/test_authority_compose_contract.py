from __future__ import annotations

from pathlib import Path
import unittest

import yaml

from novel_forge.storage.database_runtime import validate_connection_budget
from novel_forge.storage.database_runtime import authority_role_instances_from_env


ROOT = Path(__file__).resolve().parents[2]


class AuthorityComposeContractTests(unittest.TestCase):
    def test_authority_image_contains_governed_runtime_assets(self) -> None:
        source = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY config ./config", source)
        self.assertIn("COPY skills ./skills", source)

    def test_default_compose_is_complete_backend_only_authority_plane(self) -> None:
        document = yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))
        services = document["services"]
        required = {
            "postgresql",
            "object-store",
            "authority-migration",
            "authority-api",
            "chapter-authority-worker",
            "content-authority-worker",
            "source-authority-worker",
            "source-import-worker",
            "mkaos-authority-worker",
            "book-authority-worker",
            "agent-authority-worker",
            "outbox-worker",
            "maintenance-worker",
        }
        self.assertEqual(set(services), required)
        self.assertFalse(any("web" in name or "legacy" in name for name in services))
        for name, service in services.items():
            if name in {"postgresql", "object-store"}:
                continue
            environment = service["environment"]
            self.assertEqual(environment["NOVEL_FORGE_STORAGE_AUTHORITY"], "postgresql")

    def test_startup_order_health_and_worker_governance_are_explicit(self) -> None:
        document = yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))
        services = document["services"]
        migration_dependencies = services["authority-migration"]["depends_on"]
        self.assertEqual(migration_dependencies["postgresql"]["condition"], "service_healthy")
        self.assertEqual(migration_dependencies["object-store"]["condition"], "service_healthy")
        self.assertEqual(
            services["authority-api"]["depends_on"]["authority-migration"]["condition"],
            "service_completed_successfully",
        )
        for name in services:
            if not name.endswith("-worker"):
                continue
            service = services[name]
            self.assertEqual(
                service["depends_on"]["authority-api"]["condition"],
                "service_healthy",
            )
            self.assertTrue(service["healthcheck"]["test"])
            self.assertEqual(service["restart"], "unless-stopped")
            self.assertTrue(service["read_only"])
            self.assertEqual(service["user"], "10001:10001")
            self.assertTrue(service["stop_grace_period"])
            self.assertTrue(service["labels"]["novel-forge.runtime-group"])
            self.assertTrue(service["labels"]["novel-forge.operation-definitions"])

    def test_interactive_legacy_compose_is_retired(self) -> None:
        self.assertFalse((ROOT / "compose.legacy.yml").exists())

    def test_compose_connection_budget_fits_postgresql_capacity(self) -> None:
        result = validate_connection_budget(
            authority_role_instances_from_env({}),
            postgres_max_connections=100,
        )
        self.assertTrue(result["within_budget"])
        self.assertEqual(result["application_max_connections"], 33)
        self.assertEqual(result["application_capacity"], 83)


if __name__ == "__main__":
    unittest.main()
