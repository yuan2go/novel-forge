from __future__ import annotations

import unittest
from dataclasses import asdict

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.validators import (
    STORY_DESIGN_VALIDATOR_VERSION,
    validate_story_design_candidate,
)
from novel_forge.modules.story_planning_runtime.domain import (
    GENERATOR_INPUT_ROLES,
    FrozenPlanningInput,
    build_planning_constraint_envelope,
    canonical_hash,
)


def _content_with_constraints(
    generator: str,
    scope: str,
    logical_key: str,
    payload: dict[str, object],
) -> dict[str, object]:
    inputs = tuple(
        FrozenPlanningInput(
            role=role,
            asset_version_id=f"version:{role}",
            content_hash="sha256:" + "0" * 64,
            asset_type=role,
        )
        for role in GENERATOR_INPUT_ROLES[generator]
    )
    envelope = build_planning_constraint_envelope(
        generator_operation_name=generator,
        frozen_inputs=inputs,
        input_contents={role: {} for role in GENERATOR_INPUT_ROLES[generator]},
        candidate_payload=payload,
    )
    return {
        "schema_version": "story_design.authority.v1",
        "project_id": "project-1",
        "generator_operation_name": generator,
        "planning_scope": scope,
        "logical_key": logical_key,
        "candidate_payload": {**payload, "constraint_envelope": envelope},
        "frozen_inputs": [asdict(item) for item in inputs],
        "constraint_envelope": envelope,
    }


class StoryDesignValidatorTests(unittest.TestCase):
    def test_schema_structural_semantic_generator_and_scope_validators_bind_results(
        self,
    ) -> None:
        result = validate_story_design_candidate(
            content=_content_with_constraints(
                "book_plan.generate",
                "BOOK",
                "book-plan:main",
                {"objective": "Escalate the central conflict through irreversible choices"},
            ),
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
                "CONSTRAINT_PROPAGATION",
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
            content=_content_with_constraints(
                "chapter_plan.generate",
                "CHAPTER",
                "chapter:1",
                {
                    "objective": "A chapter objective",
                    "title": "The Name in the Ledger",
                    "premise": "A clerk preserves an altered ledger at a visible cost.",
                },
            ),
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
            "2.0.0",
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

    def test_candidate_validation_does_not_accept_or_require_generator_self_evaluation(
        self,
    ) -> None:
        content = _content_with_constraints(
            "book_plan.generate",
            "BOOK",
            "book-plan:main",
            {"objective": "A structurally complete but unevaluated Book plan"},
        )
        result = validate_story_design_candidate(
            content=content,
            project_id="project-1",
            generator_operation_name="book_plan.generate",
            planning_scope="BOOK",
            logical_key="book-plan:main",
        )
        semantic = next(
            receipt for receipt in result.receipts
            if receipt.validation_kind == "SEMANTIC"
        )

        self.assertEqual(
            semantic.evidence["narrative_semantic_evaluation"]["status"],
            "PENDING_INDEPENDENT_OPERATION",
        )

    def test_constraint_governance_shape_fails_closed(self) -> None:
        content = _content_with_constraints(
            "book_plan.generate",
            "BOOK",
            "book-plan:main",
            {"objective": "Preserve accepted history"},
        )
        envelope = dict(content["constraint_envelope"])
        envelope["change_governance"] = []
        envelope["envelope_digest"] = canonical_hash(
            {key: value for key, value in envelope.items() if key != "envelope_digest"}
        )
        content["constraint_envelope"] = envelope
        content["candidate_payload"] = {
            **dict(content["candidate_payload"]),
            "constraint_envelope": envelope,
        }

        with self.assertRaises(KernelError) as raised:
            validate_story_design_candidate(
                content=content,
                project_id="project-1",
                generator_operation_name="book_plan.generate",
                planning_scope="BOOK",
                logical_key="book-plan:main",
            )

        self.assertEqual(
            raised.exception.code,
            "PLANNING_CONSTRAINT_ENVELOPE_INVALID",
        )


if __name__ == "__main__":
    unittest.main()
