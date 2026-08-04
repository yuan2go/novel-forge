from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.tools.authority_reachability import (
    build_authority_import_graph,
    production_paths,
)


ROOT = Path(__file__).resolve().parents[2]
class LegacyProductionReachabilityTests(unittest.TestCase):
    def test_default_runtime_is_postgresql(self) -> None:
        settings = IndustrialSettings.from_env(env={"NOVEL_FORGE_ROOT": "."})
        self.assertEqual(settings.storage_authority, "postgresql")
        self.assertFalse(settings.postgres_write_through)

    def test_authority_mode_does_not_import_localstorage_runtime(self) -> None:
        forbidden = {
            "src/novel_forge/storage/local.py",
            "src/novel_forge/workers/runtime.py",
            "src/novel_forge/workers/legacy_tasks.py",
            "src/novel_forge/api/legacy_app.py",
            "src/novel_forge/api/services/postgres_fallback_policy.py",
        }
        graph = build_authority_import_graph(ROOT)
        findings = {
            path: production_paths(graph.paths_by_file.get(path, ()))
            for path in forbidden
            if production_paths(graph.paths_by_file.get(path, ()))
        }
        self.assertEqual(findings, {})

    def test_recursive_graph_covers_all_authority_runtime_entry_classes(self) -> None:
        graph = build_authority_import_graph(ROOT)
        required = {
            "api-app",
            "authority-dependencies",
            "authority-cli",
            "chapter-worker",
            "content-worker",
            "source-worker",
            "mkaos-worker",
            "book-worker",
            "outbox-worker",
            "maintenance-worker",
            "worker-healthcheck",
            "provider-callback",
            "external-effect-dispatch",
            "provider-qualification-worker",
            "compose-probe",
        }
        self.assertLessEqual(required, graph.entrypoints.keys())
        self.assertIn(
            "src/novel_forge/storage/authority_uow.py", graph.paths_by_file
        )

    def test_production_cannot_enable_legacy_fallback_or_dual_write(self) -> None:
        for field in (
            "legacy_write_enabled",
            "silent_legacy_fallback_enabled",
            "postgres_write_through",
        ):
            kwargs = {field: True}
            with self.assertRaises(ValueError):
                IndustrialSettings(
                    root=Path("."),
                    environment="production",
                    storage_authority="postgresql",
                    **kwargs,
                )


if __name__ == "__main__":
    unittest.main()
