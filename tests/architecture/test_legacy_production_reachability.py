from __future__ import annotations

import ast
import unittest
from pathlib import Path

from novel_forge.infrastructure.settings import IndustrialSettings


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_ENTRYPOINTS = (
    ROOT / "src/novel_forge/api/authority_app.py",
    ROOT / "src/novel_forge/api/authority_dependencies.py",
    ROOT / "src/novel_forge/workers/chapter_authority.py",
    ROOT / "src/novel_forge/workers/content_authority.py",
    ROOT / "src/novel_forge/workers/source_authority.py",
    ROOT / "src/novel_forge/workers/mkaos_authority.py",
    ROOT / "src/novel_forge/workers/runtime_groups.py",
)


class LegacyProductionReachabilityTests(unittest.TestCase):
    def test_default_runtime_is_postgresql(self) -> None:
        settings = IndustrialSettings.from_env(env={"NOVEL_FORGE_ROOT": "."})
        self.assertEqual(settings.storage_authority, "postgresql")
        self.assertFalse(settings.postgres_write_through)

    def test_authority_mode_does_not_import_localstorage_runtime(self) -> None:
        forbidden = {
            "novel_forge.storage.local",
            "novel_forge.workers.runtime",
            "novel_forge.workers.legacy_tasks",
            "novel_forge.api.legacy_app",
            "novel_forge.api.services.postgres_fallback_policy",
        }
        findings: list[str] = []
        for path in AUTHORITY_ENTRYPOINTS:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            for dependency in sorted(imports & forbidden):
                findings.append(f"{path.relative_to(ROOT)}: {dependency}")
        self.assertEqual(findings, [])

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
