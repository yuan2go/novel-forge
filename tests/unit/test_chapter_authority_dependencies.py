from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_chapter_authority_application,
    build_chapter_authority_query,
    build_production_execution_composition,
    chapter_capability_pack_compilation_report,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.provider_control import (
    OpenAIProviderAdapterV2,
    ProviderAdapterRegistry,
    ProviderReceipt,
)


def _mixed_router_environment(root: Path) -> dict[str, str]:
    executable = root / "codex-test"
    executable.write_text("#!/bin/sh\nprintf 'codex-test 1.0\\n'\n", encoding="utf-8")
    executable.chmod(0o700)
    workspace = root / "isolated-workspace"
    workspace.mkdir()
    executable_sha256 = "sha256:" + hashlib.sha256(executable.read_bytes()).hexdigest()
    return {
        "NOVEL_FORGE_ENVIRONMENT": "validation",
        "NOVEL_FORGE_PROVIDER_ROUTER": "quality-cost-v1",
        "NOVEL_FORGE_ROUTER_CODEX_ESCALATION": "true",
        "NOVEL_FORGE_CODEX_ESCALATION_MODEL": "gpt-test",
        "NOVEL_FORGE_CODEX_ESCALATION_CALL_LIMIT": "3",
        "NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT": "200000",
        "NOVEL_FORGE_CODEX_ESCALATION_OUTPUT_LIMIT": "32000",
        "NOVEL_FORGE_CODEX_ESCALATION_VALID_FROM": "2026-09-01T00:00:00+00:00",
        "NOVEL_FORGE_CODEX_ESCALATION_VALID_UNTIL": "2027-01-01T00:00:00+00:00",
        "NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT",
        "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": "authorization:codex-test",
        "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF": "account:codex-test",
        "NOVEL_FORGE_CODEX_CLI_VERSION": "codex-test 1.0",
        "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256": executable_sha256,
        "NOVEL_FORGE_CODEX_CONFIGURATION_REF": "sha256:" + "4" * 64,
        "NOVEL_FORGE_CODEX_EXECUTABLE": str(executable),
        "NOVEL_FORGE_CODEX_HOME": str(root),
        "NOVEL_FORGE_CODEX_WORKSPACE": str(workspace),
        "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(root / "executions"),
        "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT": "20",
        "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT": "2000000",
        "NOVEL_FORGE_OPERATION_PROVIDER_TOKEN_LIMIT": "500000",
        "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "2",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(root / "objects"),
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "mixed-router-test",
        "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
        "NOVEL_FORGE_RUNTIME_HOST_ID": "host:mixed-router-test",
        "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:deepseek-test",
        "NOVEL_FORGE_PROMPT_SYSTEM_INSTRUCTION_HASH": "sha256:" + "1" * 64,
        "NOVEL_FORGE_PROMPT_TEMPLATE_HASH": "sha256:" + "2" * 64,
        "NOVEL_FORGE_SKILL_BUNDLE_HASH": "sha256:" + "3" * 64,
        "DEEPSEEK_API_KEY": "non-networked-test-credential",
    }


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
            build_production_execution_composition(settings, env={})

    def test_nonproduction_fixture_routes_are_explicit_and_filesystem_independent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory),
                database_url="postgresql://authority",
            )
            execution = build_production_execution_composition(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "test",
                    "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                    "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                    "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                },
            )
            application = build_chapter_authority_application(
                settings,
                execution=execution,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "test",
                },
            )

        self.assertEqual(
            execution.gateway.provider,
            "production_execution_gateway",
        )
        self.assertTrue(execution.gateway.production_execution_gateway_backed)
        self.assertEqual(
            execution.gateway.capability_profile.control_level.value,
            "FIXTURE_CONTROLLED",
        )
        fixture = execution.gateway.session_factory("project:actor-fixture").gateway.backends.resolve("scripted-fixture").payload_resolver.fixture_response_factory
        for stage in ("world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"):
            with self.assertRaisesRegex(ValueError, "explicit fixture transport"):
                fixture(stage, {})
        self.assertFalse(hasattr(application, "model_port"))
        self.assertFalse(hasattr(application, "object_store_adapter"))

    def test_production_rejects_mock_model_routes(self) -> None:
        settings = IndustrialSettings(
            root=Path("."), database_url="postgresql://authority"
        )
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            build_production_execution_composition(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "production",
                    "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                    "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                    "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                },
            )

    def test_validation_environment_accepts_injected_controlled_v2_registry(
        self,
    ) -> None:
        class Transport:
            def execute(self, request):
                raise AssertionError(
                    "dependency construction must not invoke the provider"
                )

            def query(self, request):
                raise AssertionError(
                    "dependency construction must not query the provider"
                )

            def cancel(self, request):
                raise AssertionError(
                    "dependency construction must not cancel the provider"
                )

            def verify_callback(self, body, headers, *, secret):
                return ProviderReceipt("r", "receipt", "message", "success", "hash", {})

        registry = ProviderAdapterRegistry()
        registry.register(
            OpenAIProviderAdapterV2(
                Transport(),
                supports_query=True,
                supports_cancel=True,
                supports_callback=True,
                supports_cost_receipt=True,
                provider_idempotency_supported=True,
            )
        )
        controlled_environment = {
            "NOVEL_FORGE_ENVIRONMENT": "validation",
            "NOVEL_FORGE_MODEL_PROVIDER": "openai",
            "NOVEL_FORGE_DRAFT_MODEL": "gpt-test",
            "NOVEL_FORGE_REVIEW_MODEL": "gpt-test",
            "NOVEL_FORGE_REVISION_MODEL": "gpt-test",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "openai",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "gpt-test",
            "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": "high",
            "NOVEL_FORGE_AGENT_PROVIDER": "openai",
            "NOVEL_FORGE_AGENT_MODEL": "gpt-test",
            "NOVEL_FORGE_AGENT_REASONING_EFFORT": "high",
            "NOVEL_FORGE_EMBEDDING_PROVIDER": "openai",
            "NOVEL_FORGE_EMBEDDING_MODEL": "text-embedding-test",
            "NOVEL_FORGE_EMBEDDING_DIMENSIONS": "1536",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
            "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "chapter-gateway-test",
            "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
            "NOVEL_FORGE_RUNTIME_HOST_ID": "host:test",
            "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:test",
        }
        with self.assertRaisesRegex(RuntimeError, "SYSTEM_INSTRUCTION_HASH"):
            build_production_execution_composition(
                IndustrialSettings(
                    root=Path("."),
                    database_url="postgresql://authority",
                ),
                provider_registry=registry,
                env=controlled_environment,
            )
        controlled_environment.update(
            {
                "NOVEL_FORGE_PROMPT_SYSTEM_INSTRUCTION_HASH": ("sha256:" + "1" * 64),
                "NOVEL_FORGE_PROMPT_TEMPLATE_HASH": "sha256:" + "2" * 64,
                "NOVEL_FORGE_SKILL_BUNDLE_HASH": "sha256:" + "3" * 64,
            }
        )
        with patch(
            "novel_forge.storage.object_store.MinioObjectStore",
            return_value=SimpleNamespace(client=object()),
        ):
            settings = IndustrialSettings(
                root=Path("."), database_url="postgresql://authority"
            )
            execution = build_production_execution_composition(
                settings,
                provider_registry=registry,
                env=controlled_environment,
            )
            application = build_chapter_authority_application(
                settings,
                execution=execution,
                env=controlled_environment,
            )
        self.assertEqual(
            execution.gateway.capability_profile.control_level.value,
            "V2_CONTROLLED",
        )
        self.assertTrue(
            execution.gateway.capability_profile.real_provider_validation_eligible
        )
        self.assertEqual(
            execution.gateway.routes["agent_session"].model_profile.model_id,
            "gpt-test",
        )
        self.assertEqual(
            execution.gateway.routes[
                "retrieval_query_expansion"
            ].model_profile.model_id,
            "gpt-test",
        )
        self.assertEqual(
            execution.gateway.routes["retrieval"].model_profile.model_id,
            "text-embedding-test",
        )
        from novel_forge.modules.worldbuilding.actor_isolation import actor_task, actor_output_schema
        from novel_forge.modules.command_kernel.errors import KernelError
        from tests.unit.test_world_actor_isolation import source

        actor_source = source()
        actor_source["provider_projection_version"] = "world-role-delivery.v2"
        task = actor_task(actor_source, {"asset_version_id": "source:v2", "content_hash": "hash"}, "hero")
        output_schema = actor_output_schema(task)
        output = {"actor_id": "hero", "action": "护住同门", "basis_summary": "东门已封", "basis_refs": ["seen"], "commitment_dispositions": []}
        session = execution.gateway.session_factory("project:actor-validator")
        backend = session.gateway.backends.resolve(execution.gateway.routes["draft"].model_profile.backend_id)
        for stage in ("world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"):
            self.assertEqual(backend.structured_result_validator(stage, output_schema, output), output)
            for invalid in ({key: value for key, value in output.items() if key != "commitment_dispositions"}, {**output, "basis_refs": ["rival-seen"]}):
                with self.assertRaises(KernelError):
                    backend.structured_result_validator(stage, output_schema, invalid)
        self.assertIsNotNone(application.embedding_projection_runtime)
        self.assertIn("retrieval_projection", execution.gateway.execution_binders)

    def test_semantic_route_requires_provider_and_model_as_one_binding(self) -> None:
        settings = IndustrialSettings(
            root=Path("."), database_url="postgresql://authority"
        )
        with self.assertRaisesRegex(RuntimeError, "semantic retrieval binding"):
            build_production_execution_composition(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "test",
                    "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                    "NOVEL_FORGE_EMBEDDING_PROVIDER": "scripted_provider_v2",
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                },
            )

    def test_provider_validation_composes_codex_directly_without_provider_v2(
        self,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _mixed_router_environment(root)
            executable = Path(fixture["NOVEL_FORGE_CODEX_EXECUTABLE"])
            workspace = Path(fixture["NOVEL_FORGE_CODEX_WORKSPACE"])
            environment = {
                "NOVEL_FORGE_ENVIRONMENT": "validation",
                "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
                "NOVEL_FORGE_DRAFT_MODEL": "gpt-5.4",
                "NOVEL_FORGE_REVIEW_MODEL": "gpt-5.4",
                "NOVEL_FORGE_REVISION_MODEL": "gpt-5.4",
                "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "codex-cli",
                "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "gpt-5.4",
                "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": "high",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(root / "objects"),
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "codex-composition-test",
                "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
                "NOVEL_FORGE_RUNTIME_HOST_ID": "host:codex-test",
                "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:codex-test",
                "NOVEL_FORGE_CODEX_EXECUTABLE": str(executable),
                "NOVEL_FORGE_CODEX_HOME": str(root),
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
                execution = build_production_execution_composition(
                    IndustrialSettings(
                        root=repository_root, database_url="postgresql://authority"
                    ),
                    provider_registry=ProviderAdapterRegistry(),
                    env=environment,
                )

            session = execution.gateway.session_factory("project:codex-test")
            backend = session.gateway.backends.resolve("codex-cli")

        routes = execution.gateway.routes
        self.assertEqual(
            {route.model_profile.backend_id for route in routes.values()},
            {"codex-cli"},
        )
        self.assertEqual(
            {route.model_profile.runtime_class.value for route in routes.values()},
            {"LOCAL_CLI_REMOTE_INFERENCE"},
        )
        self.assertTrue(
            execution.gateway.capability_profile.real_provider_validation_eligible
        )
        self.assertEqual(
            backend.capability_profile.qualification_ref,
            next(iter(routes.values())).model_profile.capability_probe_ref,
        )

    def test_codex_account_entitlement_composes_without_fake_pricing(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _mixed_router_environment(root)
            executable = Path(fixture["NOVEL_FORGE_CODEX_EXECUTABLE"])
            workspace = Path(fixture["NOVEL_FORGE_CODEX_WORKSPACE"])
            executable_sha256 = fixture["NOVEL_FORGE_CODEX_EXECUTABLE_SHA256"]
            cli_version = subprocess.run((str(executable), "--version"), check=True,
                                         capture_output=True, text=True).stdout.strip()
            environment = {
                "NOVEL_FORGE_ENVIRONMENT": "validation",
                "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
                "NOVEL_FORGE_DRAFT_MODEL": "gpt-5.6-sol",
                "NOVEL_FORGE_REVIEW_MODEL": "gpt-5.6-sol",
                "NOVEL_FORGE_REVISION_MODEL": "gpt-5.6-sol",
                "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "codex-cli",
                "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "gpt-5.6-sol",
                "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": ("high"),
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(root / "objects"),
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "codex-entitlement-test",
                "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
                "NOVEL_FORGE_RUNTIME_HOST_ID": "host:codex-test",
                "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:chatgpt-account",
                "NOVEL_FORGE_CODEX_EXECUTABLE": str(executable),
                "NOVEL_FORGE_CODEX_HOME": str(root),
                "NOVEL_FORGE_CODEX_WORKSPACE": str(workspace),
                "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(root / "executions"),
                "NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT",
                "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": (
                    "task-authorization:classical-corpus-20260908"
                ),
                "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF": "chatgpt-login:local",
                "NOVEL_FORGE_CODEX_CLI_VERSION": cli_version,
                "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256": executable_sha256,
                "NOVEL_FORGE_CODEX_CONFIGURATION_REF": ("sha256:" + "4" * 64),
                "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT": "420",
                "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT": "42000000",
            }
            with patch(
                "novel_forge.storage.object_store.MinioObjectStore",
                return_value=SimpleNamespace(client=object()),
            ):
                execution = build_production_execution_composition(
                    IndustrialSettings(
                        root=repository_root, database_url="postgresql://authority"
                    ),
                    provider_registry=ProviderAdapterRegistry(),
                    env=environment,
                )

                session = execution.gateway.session_factory("project:codex-entitlement")
                backend = session.gateway.backends.resolve("codex-cli")
                self.assertEqual(backend.codex_home, str(root.resolve()))
                changed_home = root / "different-account-directory"
                changed_home.mkdir()
                changed = build_production_execution_composition(
                    IndustrialSettings(
                        root=repository_root, database_url="postgresql://authority"
                    ),
                    provider_registry=ProviderAdapterRegistry(),
                    env={**environment, "NOVEL_FORGE_CODEX_HOME": str(changed_home)},
                )
                self.assertNotEqual(
                    execution.gateway.routes["draft"].auth_profile_ref,
                    changed.gateway.routes["draft"].auth_profile_ref,
                )
                with self.assertRaisesRegex(ValueError, "explicit existing CODEX_HOME"):
                    build_production_execution_composition(
                        IndustrialSettings(
                            root=repository_root, database_url="postgresql://authority"
                        ),
                        provider_registry=ProviderAdapterRegistry(),
                        env={**environment, "NOVEL_FORGE_CODEX_HOME": ""},
                    )

        self.assertEqual(execution.cost_accounting_basis, "ACCOUNT_ENTITLEMENT")
        self.assertEqual(
            execution.account_authorization_ref,
            "task-authorization:classical-corpus-20260908",
        )
        self.assertEqual(execution.max_cost_per_call, "0")
        self.assertEqual(execution.shared_budget_caps, {})
        self.assertEqual(execution.provider_call_caps, {"project_total": 420})
        self.assertEqual(execution.provider_token_caps, {"project_total": 42_000_000})
        self.assertIsNone(backend.pricing)
        self.assertEqual(
            backend.account_entitlement.authorization_ref,
            "task-authorization:classical-corpus-20260908",
        )

    def test_mixed_router_composes_priced_deepseek_and_entitled_codex_lanes(
        self,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = _mixed_router_environment(root)
            with (
                patch(
                    "novel_forge.storage.object_store.MinioObjectStore",
                    return_value=SimpleNamespace(client=object()),
                ),
                patch(
                    "novel_forge.api.authority_dependencies.observe_codex_cli_version",
                    return_value="codex-test 1.0",
                ),
            ):
                execution = build_production_execution_composition(
                    IndustrialSettings(
                        root=repository_root,
                        database_url="postgresql://authority",
                    ),
                    env=environment,
                )
                session = execution.gateway.session_factory("project:mixed-router")

        router = execution.gateway.provider_router
        self.assertIsNotNone(router)
        from novel_forge.modules.authority_handler_runtime.routing_feedback import domain_gate_outcomes

        self.assertIs(router.registry.outcome_projection, domain_gate_outcomes)
        candidates = router.candidates
        deepseek = [item for item in candidates if item.provider == "deepseek"]
        codex = [item for item in candidates if item.provider == "codex-cli"]
        self.assertEqual(len(deepseek), 3)
        self.assertEqual(len(codex), 1)
        self.assertTrue(
            all(item.pricing.accounting_basis == "PRICED" for item in deepseek)
        )
        self.assertTrue(all(item.model_revision for item in deepseek))
        self.assertEqual(codex[0].pricing.accounting_basis, "ACCOUNT_ENTITLEMENT")
        self.assertEqual(codex[0].authorization_ref, "authorization:codex-test")
        self.assertEqual(codex[0].model_revision, "sha256:" + "4" * 64)
        self.assertTrue(codex[0].escalation_only)
        self.assertEqual(codex[0].quota_remaining, 3)
        from dataclasses import asdict
        base = next(iter(execution.gateway.routes.values()))
        selected = router._selected_route(base, {"status": "SELECTED", "task": {"declared_requirements": {}}, "selected": {"candidate": asdict(deepseek[0])}})
        self.assertEqual(selected.auth_profile_ref, "provider-account:deepseek:credential-sha256:"
                         + hashlib.sha256(environment["DEEPSEEK_API_KEY"].encode()).hexdigest())
        codex_selected = router._selected_route(base, {"status": "SELECTED", "task": {"declared_requirements": {}}, "selected": {"candidate": asdict(codex[0])}})
        self.assertIn(":codex:", codex_selected.auth_profile_ref)
        self.assertNotEqual(codex_selected.auth_profile_ref, selected.auth_profile_ref)
        self.assertEqual(execution.cost_accounting_basis, "PRICED")
        self.assertEqual(
            execution.account_authorization_ref, "authorization:codex-test"
        )
        self.assertEqual(
            session.gateway.backends.resolve(
                "remote-provider-deepseek"
            ).provider_adapter.provider,
            "deepseek",
        )
        codex_backend = session.gateway.backends.resolve("codex-cli")
        self.assertIsNone(codex_backend.pricing)
        self.assertEqual(
            codex_backend.account_entitlement.authorization_ref,
            "authorization:codex-test",
        )

    def test_production_codex_only_router_has_no_deepseek_dependency(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            environment = _mixed_router_environment(Path(directory))
            environment.update({
                "NOVEL_FORGE_ENVIRONMENT": "production",
                "NOVEL_FORGE_ROUTER_PROVIDERS": "codex-cli",
                "NOVEL_FORGE_ROUTER_CODEX_ESCALATION": "false",
            })
            environment.pop("DEEPSEEK_API_KEY")
            environment.pop("NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL")
            with (
                patch("novel_forge.storage.object_store.MinioObjectStore",
                      return_value=SimpleNamespace(client=object())),
                patch("novel_forge.api.authority_dependencies.observe_codex_cli_version",
                      return_value="codex-test 1.0"),
            ):
                execution = build_production_execution_composition(
                    IndustrialSettings(root=repository_root,
                                       database_url="postgresql://authority"),
                    env=environment,
                )
                session = execution.gateway.session_factory("project:codex-only")
        self.assertEqual(execution.cost_accounting_basis, "ACCOUNT_ENTITLEMENT")
        self.assertEqual(execution.max_cost_per_call, "0")
        self.assertEqual(execution.gateway.provider_adapters, {})
        self.assertIsNotNone(session.gateway.backends.resolve("codex-cli"))
        candidates = execution.gateway.provider_router.candidates
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider, "codex-cli")
        self.assertTrue(candidates[0].escalation_only)
        self.assertEqual(candidates[0].quota_remaining, 3)
        self.assertEqual(candidates[0].pricing.accounting_basis, "ACCOUNT_ENTITLEMENT")
        self.assertEqual({route.model_profile.model_provider
                          for route in execution.gateway.routes.values()}, {"codex-cli"})
        self.assertTrue(all(route.token_accounting_method ==
                            "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1"
                            for route in execution.gateway.routes.values()))

    def test_configured_mixed_router_fails_closed_when_codex_lane_is_unavailable(
        self,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = _mixed_router_environment(root)
            Path(environment["NOVEL_FORGE_CODEX_EXECUTABLE"]).unlink()
            with self.assertRaisesRegex(RuntimeError, "controlled Codex"):
                build_production_execution_composition(
                    IndustrialSettings(
                        root=repository_root,
                        database_url="postgresql://authority",
                    ),
                    env=environment,
                )

    def test_configured_mixed_router_fails_closed_when_deepseek_lane_is_unavailable(
        self,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = _mixed_router_environment(root)
            environment.pop("DEEPSEEK_API_KEY")
            with self.assertRaisesRegex(RuntimeError, "DeepSeek credential"):
                build_production_execution_composition(
                    IndustrialSettings(
                        root=repository_root,
                        database_url="postgresql://authority",
                    ),
                    env=environment,
                )


if __name__ == "__main__":
    unittest.main()
