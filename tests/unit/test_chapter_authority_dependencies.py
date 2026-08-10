from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
    chapter_capability_pack_compilation_report,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.provider_control import (
    OpenAIProviderAdapterV2,
    ProviderAdapterRegistry,
    ProviderReceipt,
)


class ChapterAuthorityDependenciesTests(unittest.TestCase):
    def test_shipped_chapter_capability_pack_compiles_for_readiness(self) -> None:
        report = chapter_capability_pack_compilation_report(
            IndustrialSettings(
                root=Path(__file__).resolve().parents[2],
                database_url="postgresql://authority",
            ),
            env={
                "NOVEL_FORGE_ENVIRONMENT": "validation",
                "NOVEL_FORGE_RELEASE_CHANNEL": "VALIDATION",
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "readiness-test",
                "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
            },
        )

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["pack_id"], "chapter_generation_pack")

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

        self.assertEqual(
            application.model_port.adapter.provider,
            "production_execution_gateway",
        )
        self.assertTrue(
            application.model_port.adapter.production_execution_gateway_backed
        )
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
        controlled_environment = {
            "NOVEL_FORGE_ENVIRONMENT": "provider-validation",
            "NOVEL_FORGE_MODEL_PROVIDER": "openai",
            "NOVEL_FORGE_DRAFT_MODEL": "gpt-test",
            "NOVEL_FORGE_REVIEW_MODEL": "gpt-test",
            "NOVEL_FORGE_REVISION_MODEL": "gpt-test",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
            "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "chapter-gateway-test",
            "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
            "NOVEL_FORGE_RUNTIME_HOST_ID": "host:test",
            "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:test",
        }
        with self.assertRaisesRegex(RuntimeError, "SYSTEM_INSTRUCTION_HASH"):
            build_chapter_authority_application(
                IndustrialSettings(
                    root=Path("."),
                    database_url="postgresql://authority",
                ),
                provider_registry=registry,
                env=controlled_environment,
            )
        controlled_environment.update(
            {
                "NOVEL_FORGE_PROMPT_SYSTEM_INSTRUCTION_HASH": (
                    "sha256:" + "1" * 64
                ),
                "NOVEL_FORGE_PROMPT_TEMPLATE_HASH": "sha256:" + "2" * 64,
                "NOVEL_FORGE_SKILL_BUNDLE_HASH": "sha256:" + "3" * 64,
            }
        )
        with patch(
            "novel_forge.storage.object_store.MinioObjectStore",
            return_value=SimpleNamespace(client=object()),
        ):
            application = build_chapter_authority_application(
                IndustrialSettings(
                    root=Path("."), database_url="postgresql://authority"
                ),
                provider_registry=registry,
                env=controlled_environment,
            )
        self.assertEqual(
            application.model_port.adapter.capability_profile.control_level.value,
            "V2_CONTROLLED",
        )
        self.assertTrue(
            application.model_port.adapter.capability_profile.real_provider_validation_eligible
        )
    def test_provider_validation_composes_codex_directly_without_provider_v2(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        executable = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
        if not executable.is_file():
            self.skipTest("application Codex CLI is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "isolated-workspace"
            workspace.mkdir()
            environment = {
                "NOVEL_FORGE_ENVIRONMENT": "provider-validation",
                "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
                "NOVEL_FORGE_DRAFT_MODEL": "gpt-5.4",
                "NOVEL_FORGE_REVIEW_MODEL": "gpt-5.4",
                "NOVEL_FORGE_REVISION_MODEL": "gpt-5.4",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(root / "objects"),
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "codex-composition-test",
                "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
                "NOVEL_FORGE_RUNTIME_HOST_ID": "host:codex-test",
                "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:codex-test",
                "NOVEL_FORGE_CODEX_EXECUTABLE": str(executable),
                "NOVEL_FORGE_CODEX_WORKSPACE": str(workspace),
                "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(root / "executions"),
                "NOVEL_FORGE_CODEX_PRICING_REF": "pricing:gpt-5.4:test",
                "NOVEL_FORGE_CODEX_PRICING_CURRENCY": "USD",
                "NOVEL_FORGE_CODEX_INPUT_PER_MILLION": "1",
                "NOVEL_FORGE_CODEX_CACHED_INPUT_PER_MILLION": "0.1",
                "NOVEL_FORGE_CODEX_OUTPUT_PER_MILLION": "2",
            }
            with patch(
                "novel_forge.storage.object_store.MinioObjectStore",
                return_value=SimpleNamespace(client=object()),
            ):
                application = build_chapter_authority_application(
                    IndustrialSettings(
                        root=repository_root,
                        database_url="postgresql://authority",
                    ),
                    provider_registry=ProviderAdapterRegistry(),
                    env=environment,
                )

        routes = application.model_port.adapter.routes
        self.assertEqual(
            {route.model_profile.backend_id for route in routes.values()},
            {"codex-cli"},
        )
        self.assertEqual(
            {route.model_profile.runtime_class.value for route in routes.values()},
            {"LOCAL_CLI_REMOTE_INFERENCE"},
        )
        self.assertTrue(
            application.model_port.adapter.capability_profile.real_provider_validation_eligible
        )
        session = application.model_port.adapter.session_factory("project:codex-test")
        backend = session.gateway.backends.resolve("codex-cli")
        self.assertEqual(
            backend.capability_profile.qualification_ref,
            next(iter(routes.values())).model_profile.capability_probe_ref,
        )


if __name__ == "__main__":
    unittest.main()
