from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.validators import (
    STORY_DESIGN_VALIDATOR_VERSION,
    validate_story_design_candidate,
)


class StoryDesignValidatorTests(unittest.TestCase):
    def test_schema_structural_semantic_generator_and_scope_validators_bind_results(
        self,
    ) -> None:
        result = validate_story_design_candidate(
            content={
                "schema_version": "story_design.authority.v1",
                "project_id": "project-1",
                "generator_operation_name": "book_plan.generate",
                "planning_scope": "BOOK",
                "logical_key": "book-plan:main",
                "candidate_payload": {
                    "objective": "Escalate the central conflict through irreversible choices"
                },
            },
            project_id="project-1",
            generator_operation_name="book_plan.generate",
            planning_scope="BOOK",
            logical_key="book-plan:main",
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.validator_version, STORY_DESIGN_VALIDATOR_VERSION)
        self.assertTrue(result.implementation_hash.startswith("sha256:"))
        self.assertTrue(result.result_hash.startswith("sha256:"))
        self.assertEqual(
            {receipt.validation_kind for receipt in result.receipts},
            {
                "SCHEMA",
                "STRUCTURAL",
                "SEMANTIC",
                "GENERATOR_CONTRACT",
                "PLANNING_SCOPE",
            },
        )

    def test_scope_generator_mismatch_fails_closed(self) -> None:
        with self.assertRaises(KernelError) as raised:
            validate_story_design_candidate(
                content={
                    "schema_version": "story_design.authority.v1",
                    "project_id": "project-1",
                    "generator_operation_name": "chapter_plan.generate",
                    "planning_scope": "BOOK",
                    "logical_key": "chapter-plan:1",
                    "candidate_payload": {"objective": "A chapter objective"},
                },
                project_id="project-1",
                generator_operation_name="chapter_plan.generate",
                planning_scope="BOOK",
                logical_key="chapter-plan:1",
            )

        self.assertEqual(raised.exception.code, "STORY_DESIGN_SCOPE_INVALID")

    def test_versioned_story_chapter_generator_remains_validation_complete(
        self,
    ) -> None:
        result = validate_story_design_candidate(
            content={
                "schema_version": "story_design.authority.v1",
                "project_id": "project-1",
                "generator_operation_name": "chapter_plan.generate",
                "planning_scope": "CHAPTER",
                "logical_key": "chapter:1",
                "candidate_payload": {
                    "objective": "A chapter objective",
                    "title": "The Name in the Ledger",
                    "premise": "A clerk preserves an altered ledger at a visible cost.",
                },
            },
            project_id="project-1",
            generator_operation_name="chapter_plan.generate",
            planning_scope="CHAPTER",
            logical_key="chapter:1",
        )

        generator_receipt = next(
            receipt
            for receipt in result.receipts
            if receipt.validation_kind == "GENERATOR_CONTRACT"
        )
        self.assertEqual(
            generator_receipt.evidence["generator_definition_version"],
            "1.3.0",
        )

    def test_chapter_publish_metadata_rejects_internal_planning_instructions(
        self,
    ) -> None:
        with self.assertRaises(KernelError) as raised:
            validate_story_design_candidate(
                content={
                    "schema_version": "story_design.authority.v1",
                    "project_id": "project-1",
                    "generator_operation_name": "chapter_plan.generate",
                    "planning_scope": "CHAPTER",
                    "logical_key": "chapter:1",
                    "candidate_payload": {
                        "objective": "A chapter objective",
                        "title": "Chapter 1: Reveal the contradiction and force the first accountable choice",
                        "premise": "Plan Chapter 1 as a future-only candidate.",
                    },
                },
                project_id="project-1",
                generator_operation_name="chapter_plan.generate",
                planning_scope="CHAPTER",
                logical_key="chapter:1",
            )

        self.assertEqual(raised.exception.code, "STORY_DESIGN_SEMANTIC_INVALID")
        self.assertIn("publish metadata", raised.exception.message)

    def test_empty_candidate_payload_cannot_be_declared_passing(self) -> None:
        with self.assertRaises(KernelError) as raised:
            validate_story_design_candidate(
                content={
                    "schema_version": "story_design.authority.v1",
                    "project_id": "project-1",
                    "generator_operation_name": "book_plan.generate",
                    "planning_scope": "BOOK",
                    "logical_key": "book-plan:main",
                    "candidate_payload": {},
                },
                project_id="project-1",
                generator_operation_name="book_plan.generate",
                planning_scope="BOOK",
                logical_key="book-plan:main",
            )

        self.assertEqual(raised.exception.code, "STORY_DESIGN_SCHEMA_INVALID")


if __name__ == "__main__":
    unittest.main()
