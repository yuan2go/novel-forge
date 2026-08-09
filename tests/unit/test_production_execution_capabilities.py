from __future__ import annotations

import unittest

from novel_forge.modules.production_execution import (
    CapabilityDefinition,
    CapabilityId,
    CapabilityRegistry,
    CompletionMode,
    ExecutionCapabilityProfile,
    ExecutionRuntimeClass,
    default_capability_registry,
)
from novel_forge.modules.production_execution.capability_registry import (
    PLANNING_TIMEOUT_POLICY_VERSION,
    capability_contract_version,
)


REQUIRED_CAPABILITIES = {
    "creative.topic.generate",
    "creative.proposal.generate",
    "theme.question.generate",
    "ending.intent.generate",
    "world.design.generate",
    "character.cast.generate",
    "planning.book.generate",
    "planning.volume.generate",
    "planning.arc.generate",
    "planning.chapter_group.generate",
    "planning.chapter.generate",
    "prose.chapter.draft",
    "review.chapter.evaluate",
    "revision.chapter.revise",
    "canon.extract",
    "quality.intrinsic.judge",
    "quality.originality.judge",
    "quality.platform.judge",
    "quality.reader_outcome.judge",
    "quality.pairwise.judge",
    "mkaos.knowledge.extract",
    "mkaos.rule.extract",
    "mkaos.template.extract",
    "retrieval.embed",
    "retrieval.rerank",
    "longform.recap.analyze",
    "longform.plan_vs_actual.judge",
    "longform.arc_closure.judge",
    "longform.plan_change.generate",
    "agent.workspace.execute",
    "publishing.release.submit",
    "publishing.release.query",
    "publishing.release.withdraw",
    "feedback.platform.fetch",
    "source.remote.fetch",
    "notification.send",
}


def backend_profile(
    *,
    backend_id: str = "remote-provider-openai",
    runtime_class: ExecutionRuntimeClass = ExecutionRuntimeClass.REMOTE_PROVIDER_API,
    provider_idempotency: bool = True,
    query: bool = True,
    cancel: bool = True,
    callback: bool = True,
) -> ExecutionCapabilityProfile:
    return ExecutionCapabilityProfile(
        backend_id=backend_id,
        backend_version="1.0.0",
        runtime_class=runtime_class,
        supported_completion_modes=(
            CompletionMode.SYNCHRONOUS,
            CompletionMode.POLL,
            CompletionMode.CALLBACK,
        ),
        supported_reasoning_efforts=("none", "low", "medium", "high", "xhigh"),
        supports_query=query,
        supports_cancel=cancel,
        supports_callback=callback,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        supports_structured_output=True,
        supports_process_group_control=False,
        supports_persistent_execution_directory=False,
        supports_provider_idempotency=provider_idempotency,
        real_provider_validation_eligible=(
            runtime_class is not ExecutionRuntimeClass.SCRIPTED_FIXTURE
        ),
        qualification_ref="capability-probe:remote-provider-openai:1",
    )


class ProductionExecutionCapabilityTests(unittest.TestCase):
    def test_default_registry_contains_every_governed_capability(self) -> None:
        registry = default_capability_registry()

        self.assertTrue(REQUIRED_CAPABILITIES.issubset(set(registry.capability_ids())))
        self.assertEqual(
            len(registry.capability_ids()), len(set(registry.capability_ids()))
        )
        self.assertTrue(
            REQUIRED_CAPABILITIES.issubset({item.value for item in CapabilityId})
        )

    def test_planning_capabilities_use_versioned_long_running_timeout_policy(
        self,
    ) -> None:
        registry = default_capability_registry()

        for capability_id in (
            "planning.book.generate",
            "planning.volume.generate",
            "planning.arc.generate",
            "planning.chapter_group.generate",
            "planning.chapter.generate",
        ):
            self.assertTrue(
                registry.resolve(capability_id).timeout_policy_ref.endswith(
                    f":{PLANNING_TIMEOUT_POLICY_VERSION}"
                )
            )
            self.assertEqual(capability_contract_version(capability_id), 2)
        self.assertTrue(
            registry.resolve("prose.chapter.draft").timeout_policy_ref.endswith(":v1")
        )
        self.assertEqual(capability_contract_version("prose.chapter.draft"), 1)

    def test_every_definition_has_a_complete_serializable_governance_contract(
        self,
    ) -> None:
        registry = default_capability_registry()

        hashes: set[str] = set()
        for definition in registry.definitions():
            payload = definition.to_dict()
            self.assertEqual(
                set(payload),
                {
                    "capability_id",
                    "domain",
                    "input_schema_ref",
                    "output_schema_ref",
                    "allowed_runtime_classes",
                    "allowed_backend_ids",
                    "prompt_bundle_type",
                    "skill_bundle_type",
                    "timeout_policy_ref",
                    "budget_policy_ref",
                    "permission_policy_ref",
                    "source_policy_ref",
                    "validation_policy_ref",
                    "commit_policy_ref",
                    "requires_provider_idempotency",
                    "supports_query",
                    "supports_cancel",
                    "supports_callback",
                    "fixture_allowed",
                    "production_allowed",
                    "risk_class",
                },
            )
            self.assertTrue(
                all(
                    payload[key]
                    for key in (
                        "capability_id",
                        "domain",
                        "input_schema_ref",
                        "output_schema_ref",
                        "allowed_runtime_classes",
                        "allowed_backend_ids",
                        "prompt_bundle_type",
                        "skill_bundle_type",
                        "timeout_policy_ref",
                        "budget_policy_ref",
                        "permission_policy_ref",
                        "source_policy_ref",
                        "validation_policy_ref",
                        "commit_policy_ref",
                        "risk_class",
                    )
                )
            )
            self.assertEqual(
                CapabilityDefinition.from_dict(payload).contract_hash,
                definition.contract_hash,
            )
            hashes.add(definition.contract_hash)
        self.assertEqual(len(hashes), len(registry.capability_ids()))

    def test_duplicate_registration_is_idempotent_but_contract_drift_fails(
        self,
    ) -> None:
        definition = default_capability_registry().resolve(
            CapabilityId.PROSE_CHAPTER_DRAFT
        )
        registry = CapabilityRegistry((definition,))

        self.assertIs(registry.register(definition), definition)
        changed = CapabilityDefinition.from_dict(
            {**definition.to_dict(), "risk_class": "critical"}
        )
        with self.assertRaisesRegex(ValueError, "different contract"):
            registry.register(changed)

    def test_controlled_environment_rejects_fixture_backend(self) -> None:
        registry = default_capability_registry()
        fixture = backend_profile(
            backend_id="scripted-fixture",
            runtime_class=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
            provider_idempotency=False,
            query=False,
            cancel=False,
            callback=False,
        )

        for environment in ("validation", "provider-validation", "production"):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ValueError, "fixture"):
                    registry.require_backend(
                        CapabilityId.PROSE_CHAPTER_DRAFT,
                        fixture,
                        environment=environment,
                    )
        admitted = registry.require_backend(
            CapabilityId.PROSE_CHAPTER_DRAFT,
            fixture,
            environment="test",
        )
        self.assertEqual(admitted.capability_id, CapabilityId.PROSE_CHAPTER_DRAFT)

    def test_backend_qualification_checks_runtime_backend_and_provider_idempotency(
        self,
    ) -> None:
        registry = default_capability_registry()

        with self.assertRaisesRegex(ValueError, "backend"):
            registry.require_backend(
                CapabilityId.PUBLISHING_RELEASE_SUBMIT,
                backend_profile(),
                environment="production",
            )
        external_without_idempotency = backend_profile(
            backend_id="remote-external-action",
            runtime_class=ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
            provider_idempotency=False,
        )
        with self.assertRaisesRegex(ValueError, "idempotency"):
            registry.require_backend(
                CapabilityId.PUBLISHING_RELEASE_SUBMIT,
                external_without_idempotency,
                environment="production",
            )
        qualified = backend_profile(
            backend_id="remote-external-action",
            runtime_class=ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
        )
        definition = registry.require_backend(
            CapabilityId.PUBLISHING_RELEASE_SUBMIT,
            qualified,
            environment="production",
        )
        self.assertEqual(
            definition.capability_id, CapabilityId.PUBLISHING_RELEASE_SUBMIT
        )


if __name__ == "__main__":
    unittest.main()
