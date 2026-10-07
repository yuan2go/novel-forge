from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterNode,
    resolve_stage_context_token_budget,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_LONG_TIMEOUT_POLICY_NODES,
    CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
    CHAPTER_MODEL_WORKFLOW_DEFINITION_ID,
    CHAPTER_MODEL_WORKFLOW_DEFINITION_REF,
    CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION,
    CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS,
    CHAPTER_MODEL_ROOT_TIMEOUT_SECONDS,
    CHAPTER_QUALITY_GROUP_TIMEOUT_SECONDS,
    CHAPTER_QUALITY_PROVIDER_NODES,
    CHAPTER_SLICE_HANDLER_CONTRACT_VERSION,
    CHAPTER_SLICE_DEFINITION_VERSION,
    CHAPTER_SLICE_ROOT_DEFINITION_NAME,
    chapter_root_operation_definition,
    chapter_operation_definitions,
)
from novel_forge.modules.command_kernel.errors import KernelError


class _Handler:
    def execute(self, request):  # type: ignore[no-untyped-def]
        return ChapterHandlerOutput(
            asset_type="chapter_plan",
            output_key="chapter.plan",
            role="primary",
            content={"chapter": 1},
        )


class ChapterAuthorityDefinitionTests(unittest.TestCase):
    def test_sample_definition_requires_ineligible_output_without_weakening_formal_contract(self) -> None:
        from novel_forge.modules.chapter_authority.definitions import chapter_provider_sample_definitions

        samples = chapter_provider_sample_definitions(application_build_id="test", commit_sha="a" * 40)
        formal = {item["name"]: item for item in chapter_operation_definitions(
            application_build_id="test", commit_sha="a" * 40, model_effects_required=True,
        )}
        for sample in samples:
            with self.subTest(definition=sample["name"]):
                original = formal[sample["policy"]["source_definition_name"]]
                self.assertNotEqual(sample["name"], original["name"])
                selector = sample["completion_contract"]["required_asset_selectors"][0]
                self.assertEqual(selector["selector"], "chapter_provider_sample")
                self.assertEqual(selector["eligibility"], "INELIGIBLE")
                self.assertEqual(original["completion_contract"]["required_qualifications"], ["production_eligible"])
                self.assertTrue(all(item["eligibility"] == "ELIGIBLE" for item in original["completion_contract"]["required_asset_selectors"]))
                self.assertEqual(sample["completion_contract"]["required_external_effects"], original["completion_contract"]["required_external_effects"])
                self.assertEqual(sample["retry_policy"]["max_attempts"], 1)

    def test_root_definition_requires_every_node_and_is_saga_owned(self) -> None:
        definition = chapter_root_operation_definition(
            application_build_id="unit-test-build",
            commit_sha="a" * 40,
        )

        self.assertEqual(definition["name"], CHAPTER_SLICE_ROOT_DEFINITION_NAME)
        self.assertEqual(definition["execution_mode"], "saga")
        self.assertEqual(definition["definition_status"], "enabled")
        self.assertTrue(definition["evidence_status"]["handler_bound"])
        self.assertFalse(definition["evidence_status"]["integration_proven"])
        self.assertEqual(definition["migration_owner"], "chapter-authority")
        self.assertIn("chapter_production_run", definition["projection_consumers"])
        self.assertEqual(
            [
                item["definition_name"]
                for item in definition["completion_contract"][
                    "required_child_operations"
                ]
            ],
            [node.definition_name for node in ChapterNode],
        )

    def test_catalog_freezes_ordered_closed_node_contracts(self) -> None:
        definitions = chapter_operation_definitions(
            application_build_id="unit-test-build",
            commit_sha="a" * 40,
        )

        self.assertEqual(
            [definition["name"] for definition in definitions],
            [node.definition_name for node in ChapterNode],
        )
        self.assertEqual(len(definitions), len(ChapterNode))
        self.assertEqual(
            {definition["definition_version"] for definition in definitions},
            {CHAPTER_SLICE_DEFINITION_VERSION},
        )
        self.assertEqual(
            len({item["handler_key"] for item in definitions}), len(ChapterNode)
        )
        self.assertEqual(definitions[-3]["name"], "chapter.publishing.prepare_release")
        self.assertEqual(definitions[-1]["name"], "chapter.publishing.finalize_release")
        for node, definition in zip(ChapterNode, definitions, strict=True):
            with self.subTest(node=node.value):
                schema = definition["command_schema"]
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                self.assertIn("chapter", schema["required"])
                self.assertEqual(definition["family"], "chapter_authority")
                self.assertEqual(
                    definition["idempotency_scope"], "project:chapter-slice"
                )
                self.assertEqual(
                    definition["handler_contract_version"],
                    CHAPTER_SLICE_HANDLER_CONTRACT_VERSION,
                )
                self.assertEqual(definition["definition_status"], "enabled")
                self.assertEqual(
                    definition["input_contract"], definition["command_schema"]
                )
                self.assertEqual(
                    definition["output_contract"], definition["result_schema"]
                )
                self.assertEqual(
                    definition["completion_contract"]["required_asset_selectors"][0],
                    {
                        "selector": node.asset_type,
                        "output_key": node.output_key,
                        "role": "primary",
                        "lifecycle": "ACTIVE",
                        "eligibility": "ELIGIBLE",
                        "governance": "CLEAR",
                    },
                )
                self.assertEqual(
                    definition["completion_contract"]["required_audit_actions"],
                    [node.completion_topic],
                )
                self.assertEqual(
                    definition["completion_contract"]["required_outbox_events"],
                    [node.completion_topic],
                )
        self.assertEqual(
            definitions[list(ChapterNode).index(ChapterNode.EXPORT)][
                "completion_contract"
            ]["required_blobs"],
            [{"status": "AVAILABLE", "role": "content", "min_count": 1}],
        )
        canon_definition = definitions[list(ChapterNode).index(ChapterNode.CANON)]
        self.assertEqual(
            len(canon_definition["completion_contract"]["required_asset_selectors"]),
            2,
        )
        self.assertEqual(
            canon_definition["completion_contract"]["required_asset_selectors"][1][
                "selector"
            ],
            "deterministic_continuity_report",
        )
        quality_definition = definitions[list(ChapterNode).index(ChapterNode.QUALITY)]
        self.assertIn(
            {
                "selector": "narrative_runtime_measurement",
                "output_key": "chapter.quality.narrative_runtime_measurement",
                "role": "proof_observation",
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            },
            quality_definition["completion_contract"]["required_asset_selectors"],
        )
        self.assertEqual(
            definitions[list(ChapterNode).index(ChapterNode.EXPORT)][
                "completion_contract"
            ]["required_external_effects"],
            [{"capability": "object_store.put", "allowed_states": ["SUCCEEDED"]}],
        )

    def test_model_effect_profile_versions_and_requires_each_model_capability(
        self,
    ) -> None:
        definitions = chapter_operation_definitions(
            application_build_id="unit-test-build",
            commit_sha="a" * 40,
            model_effects_required=True,
        )

        self.assertEqual(
            {item["definition_version"] for item in definitions},
            {CHAPTER_MODEL_EFFECT_DEFINITION_VERSION, "3.9.2", "3.9.19", "3.9.26", "3.9.18", "3.9.30", "3.9.23", "3.9.9", "3.9.10", "3.9.25", "3.9.12", "3.9.13", "3.9.14", "3.9.15"},
        )
        self.assertEqual(
            {item["handler_contract_version"] for item in definitions},
            {CHAPTER_MODEL_EFFECT_DEFINITION_VERSION},
        )
        self.assertEqual(
            CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION,
            CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
        )
        self.assertEqual(
            CHAPTER_MODEL_WORKFLOW_DEFINITION_REF,
            (
                f"{CHAPTER_MODEL_WORKFLOW_DEFINITION_ID}@"
                f"{CHAPTER_MODEL_EFFECT_DEFINITION_VERSION}"
            ),
        )
        root = chapter_root_operation_definition(
            application_build_id="unit-test-build",
            commit_sha="a" * 40,
            model_effects_required=True,
        )
        self.assertEqual(
            root["timeout_policy"]["operation_timeout_seconds"],
            CHAPTER_MODEL_ROOT_TIMEOUT_SECONDS,
        )
        for node, capability in (
            (ChapterNode.DRAFT, "model.draft"),
            (ChapterNode.REVIEW, "model.review"),
            (ChapterNode.REVISION, "model.revision"),
            (ChapterNode.REREVIEW, "model.rereview"),
        ):
            definition = definitions[list(ChapterNode).index(node)]
            self.assertEqual(
                definition["timeout_policy"]["operation_timeout_seconds"],
                CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS,
            )
            self.assertIn(capability, definition["external_capabilities"])
            self.assertIn(
                {"capability": capability, "allowed_states": ["SUCCEEDED"]},
                definition["completion_contract"]["required_external_effects"],
            )
        retrieval = definitions[list(ChapterNode).index(ChapterNode.RETRIEVAL)]
        self.assertEqual(
            retrieval["external_capabilities"],
            ["model.retrieval", "model.retrieval_query_expansion"],
        )
        self.assertNotIn("required_external_effects", retrieval["completion_contract"])
        self.assertEqual(
            retrieval,
            chapter_operation_definitions(
                application_build_id="unit-test-build",
                commit_sha="a" * 40,
                model_effects_required=True,
                semantic_retrieval_available=True,
            )[list(ChapterNode).index(ChapterNode.RETRIEVAL)],
        )
        for node in CHAPTER_QUALITY_PROVIDER_NODES:
            definition = definitions[list(ChapterNode).index(node)]
            self.assertEqual(
                definition["timeout_policy"]["operation_timeout_seconds"],
                CHAPTER_QUALITY_GROUP_TIMEOUT_SECONDS,
            )
        for node in CHAPTER_LONG_TIMEOUT_POLICY_NODES - CHAPTER_QUALITY_PROVIDER_NODES:
            definition = definitions[list(ChapterNode).index(node)]
            self.assertEqual(
                definition["timeout_policy"]["operation_timeout_seconds"],
                CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS,
            )

    def test_registry_is_explicit_and_fails_closed(self) -> None:
        registry = ChapterHandlerRegistry()
        registry.register(ChapterNode.PLAN, _Handler())

        self.assertIsInstance(registry.require(ChapterNode.PLAN), _Handler)
        with self.assertRaises(KernelError) as duplicate:
            registry.register(ChapterNode.PLAN, _Handler())
        self.assertEqual(duplicate.exception.code, "CHAPTER_HANDLER_ALREADY_REGISTERED")
        with self.assertRaises(KernelError) as missing:
            registry.require(ChapterNode.CONTEXT)
        self.assertEqual(missing.exception.code, "CHAPTER_HANDLER_NOT_REGISTERED")

    def test_stage_context_budget_comes_only_from_frozen_chapter_command(
        self,
    ) -> None:
        command = {
            "context_token_budget": 16_000,
            "preparation_report": {
                "stage_context_token_budgets": {
                    "draft": 16_000,
                    "quality": 28_000,
                }
            },
        }

        self.assertEqual(resolve_stage_context_token_budget(command, "draft"), 16_000)
        self.assertEqual(
            resolve_stage_context_token_budget(command, "quality_longform"),
            28_000,
        )
        self.assertEqual(
            resolve_stage_context_token_budget(command, "canon_extraction"),
            16_000,
        )

    def test_authority_slice_does_not_import_local_storage_or_legacy_projection(
        self,
    ) -> None:
        module_root = (
            Path(__file__).resolve().parents[2]
            / "src/novel_forge/modules/chapter_authority"
        )
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(module_root.glob("*.py"))
        )

        self.assertNotIn("novel_forge.storage.local", source)
        self.assertNotIn("LocalStorage", source)
        self.assertNotIn("nf_assets", source)


if __name__ == "__main__":
    unittest.main()


def test_retained_revision_is_a_pure_derivation_with_ordinary_fenced_asset_completion():
    from novel_forge.modules.chapter_authority.definitions import retained_revision_definition
    definition=retained_revision_definition(application_build_id='unit',commit_sha='a'*40)
    assert definition['definition_version']=='3.9.17'
    assert definition['external_capabilities']==[]
    assert 'required_external_effects' not in definition['completion_contract']
    assert definition['policy']['retained_result_contract']=='chapter-quality-range-revalidation.v1'
    assert definition['permissions']==['chapter.authority.execute']
    assert definition['completion_contract']['required_asset_selectors'][0]['lifecycle']=='ACTIVE'
