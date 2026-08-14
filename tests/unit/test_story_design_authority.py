from __future__ import annotations

import unittest

from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.modules.story_design_authority import (
    GENERATOR_DEFINITIONS,
)


class StoryDesignAuthorityContractTests(unittest.TestCase):
    def test_all_required_generators_have_versioned_pep_capabilities(self) -> None:
        expected = {
            "creative.candidates.generate",
            "theme.candidates.generate",
            "ending.intent.generate",
            "world.design.generate",
            "character.cast.generate",
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        }
        self.assertEqual(
            {item.operation_name for item in GENERATOR_DEFINITIONS}, expected
        )
        registry = default_capability_registry()
        for definition in GENERATOR_DEFINITIONS:
            self.assertEqual(
                registry.resolve(definition.capability).capability_id.value,
                definition.capability,
            )
            self.assertTrue(definition.structural_validator_keys)
            self.assertTrue(definition.semantic_validator_keys)
            self.assertGreaterEqual(definition.maximum_semantic_repairs, 0)

    def test_generator_definitions_do_not_duplicate_capabilities_by_name(self) -> None:
        identities = {
            (item.operation_name, item.definition_version)
            for item in GENERATOR_DEFINITIONS
        }
        self.assertEqual(len(identities), len(GENERATOR_DEFINITIONS))

    def test_story_chapter_schema_change_is_a_versioned_generator_contract(
        self,
    ) -> None:
        definitions = {item.operation_name: item for item in GENERATOR_DEFINITIONS}

        self.assertEqual(
            definitions["chapter_plan.generate"].capability,
            "planning.story_chapter.generate",
        )
        self.assertEqual(
            definitions["chapter_plan.generate"].definition_version,
            "1.6.0",
        )
        self.assertEqual(
            definitions["chapter_plan.generate"].output_schema_version,
            "chapter-plan-generate-output-v6",
        )
        self.assertEqual(
            definitions["chapter_plan.generate"].prompt_contract_version,
            "chapter-plan-generate-prompt-v5",
        )
        self.assertEqual(definitions["book_plan.generate"].definition_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
