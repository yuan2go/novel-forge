from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.api.authority_dependencies import build_chapter_authority_application
from novel_forge.infrastructure.settings import IndustrialSettings


class ChapterAuthorityDependenciesTests(unittest.TestCase):
    def test_requires_explicit_routes_and_object_store(self) -> None:
        settings = IndustrialSettings(
            root=Path("."),
            database_url="postgresql://authority",
        )
        with self.assertRaisesRegex(RuntimeError, "explicit chapter model provider"):
            build_chapter_authority_application(settings, env={})

    def test_nonproduction_fixture_routes_are_explicit_and_filesystem_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory),
                database_url="postgresql://authority",
            )
            application = build_chapter_authority_application(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "test",
                    "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                    "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                    "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                },
            )

        self.assertEqual(application.model_port.adapter.provider, "novel_forge_model_gateway_v1")

    def test_production_rejects_mock_model_routes(self) -> None:
        settings = IndustrialSettings(root=Path("."), database_url="postgresql://authority")
        with self.assertRaisesRegex(RuntimeError, "mock model routes are forbidden"):
            build_chapter_authority_application(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "production",
                    "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                    "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                    "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                },
            )


if __name__ == "__main__":
    unittest.main()
