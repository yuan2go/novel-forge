from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.provider_control import (
    OpenAIProviderAdapterV2,
    ProviderAdapterRegistry,
    ProviderReceipt,
)


class ChapterAuthorityDependenciesTests(unittest.TestCase):
    def test_strong_query_requires_only_postgresql(self) -> None:
        query = build_chapter_authority_query(
            IndustrialSettings(root=Path("."), database_url="postgresql://authority")
        )
        self.assertEqual(query.database_url, "postgresql://authority")
        with self.assertRaisesRegex(RuntimeError, "PostgreSQL"):
            build_chapter_authority_query(IndustrialSettings(root=Path(".")))

    def test_release_identity_is_explicit_and_validated(self) -> None:
        self.assertEqual(
            authority_release_identity(
                env={
                    "NOVEL_FORGE_APPLICATION_BUILD_ID": "build-42",
                    "NOVEL_FORGE_COMMIT_SHA": "A" * 40,
                }
            ),
            ("build-42", "a" * 40),
        )
        with self.assertRaisesRegex(RuntimeError, "APPLICATION_BUILD_ID"):
            authority_release_identity(env={})
        with self.assertRaisesRegex(RuntimeError, "hexadecimal"):
            authority_release_identity(
                env={
                    "NOVEL_FORGE_APPLICATION_BUILD_ID": "build-42",
                    "NOVEL_FORGE_COMMIT_SHA": "not-a-commit",
                }
            )
        with self.assertRaisesRegex(RuntimeError, "full 40-character"):
            authority_release_identity(
                env={
                    "NOVEL_FORGE_APPLICATION_BUILD_ID": "build-42",
                    "NOVEL_FORGE_COMMIT_SHA": "a" * 7,
                }
            )

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

        self.assertEqual(application.model_port.adapter.provider, "novel_forge_provider_v2_gateway")
        self.assertEqual(
            application.model_port.adapter.capability_profile.control_level.value,
            "FIXTURE_CONTROLLED",
        )

    def test_production_rejects_mock_model_routes(self) -> None:
        settings = IndustrialSettings(root=Path("."), database_url="postgresql://authority")
        with self.assertRaisesRegex(RuntimeError, "not registered"):
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

    def test_validation_environment_accepts_injected_controlled_v2_registry(self) -> None:
        class Transport:
            def execute(self, request):
                raise AssertionError("dependency construction must not invoke the provider")
            def query(self, request):
                raise AssertionError("dependency construction must not query the provider")
            def cancel(self, request):
                raise AssertionError("dependency construction must not cancel the provider")
            def verify_callback(self, body, headers, *, secret):
                return ProviderReceipt("r", "receipt", "message", "success", "hash", {})

        registry = ProviderAdapterRegistry()
        registry.register(OpenAIProviderAdapterV2(
            Transport(), supports_query=True, supports_cancel=True,
            supports_callback=True, supports_cost_receipt=True,
            provider_idempotency_supported=True,
        ))
        application = build_chapter_authority_application(
            IndustrialSettings(root=Path("."), database_url="postgresql://authority"),
            provider_registry=registry,
            env={
                "NOVEL_FORGE_ENVIRONMENT": "provider-validation",
                "NOVEL_FORGE_MODEL_PROVIDER": "openai",
                "NOVEL_FORGE_DRAFT_MODEL": "gpt-test",
                "NOVEL_FORGE_REVIEW_MODEL": "gpt-test",
                "NOVEL_FORGE_REVISION_MODEL": "gpt-test",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
            },
        )
        self.assertEqual(
            application.model_port.adapter.capability_profile.control_level.value,
            "V2_CONTROLLED",
        )
        self.assertTrue(
            application.model_port.adapter.capability_profile.real_provider_validation_eligible
        )


if __name__ == "__main__":
    unittest.main()
