from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_LONG_TIMEOUT_POLICY_NODES,
    CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
    CHAPTER_MODEL_OPERATION_TIMEOUT_SECONDS,
    CHAPTER_MODEL_ROOT_TIMEOUT_SECONDS,
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
            10,
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
            {CHAPTER_MODEL_EFFECT_DEFINITION_VERSION},
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
        for node in CHAPTER_LONG_TIMEOUT_POLICY_NODES:
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
