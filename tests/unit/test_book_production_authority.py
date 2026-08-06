from __future__ import annotations

import unittest

from novel_forge.modules.book_authority.production import (
    LONGFORM_CONTEXT_VERSION_KEYS,
    BookProductionState,
    stable_chapter_submission_key,
)
from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
)
from novel_forge.modules.book_followup_authority.registry import (
    BookFollowupHandlerRegistry,
)
from novel_forge.storage.migrations.runner import MIGRATIONS


class BookProductionAuthorityTests(unittest.TestCase):
    def test_chapter_submission_key_is_stable_and_version_sensitive(self) -> None:
        values = {
            "book_id": "book:1",
            "book_plan_version": "book-plan:v1",
            "chapter_number": 3,
            "chapter_plan_version": "chapter-plan:3:v1",
            "production_profile_version": "production-profile:v1",
        }
        first = stable_chapter_submission_key(**values)

        self.assertEqual(first, stable_chapter_submission_key(**values))
        self.assertNotEqual(
            first,
            stable_chapter_submission_key(
                **{**values, "chapter_plan_version": "chapter-plan:3:v2"}
            ),
        )

    def test_followup_operations_have_real_policies_and_outputs(self) -> None:
        definitions = {
            item["name"]: item
            for item in book_followup_operation_definitions(
                application_build_id="test-build",
                commit_sha="a" * 40,
            )
        }
        handlers = BookFollowupHandlerRegistry().available_handler_keys

        self.assertEqual(
            set(definitions), {"reader_outcome.evaluate", "longform.recap"}
        )
        self.assertEqual(len(handlers), 2)
        reader = definitions["reader_outcome.evaluate"]
        recap = definitions["longform.recap"]
        self.assertEqual(reader["external_capabilities"], ["model.reader_outcome"])
        self.assertEqual(
            set(reader["output_contract"]["auxiliary_asset_types"]),
            {"reader_state_transition", "reader_issue_set"},
        )
        self.assertFalse(recap["policy"]["plan_mutation_allowed"])
        self.assertIn(
            "plan_adjustment_proposal",
            recap["output_contract"]["auxiliary_asset_types"],
        )
        self.assertEqual(
            recap["output_contract"]["optional_auxiliary_asset_types"],
            ["replan_request"],
        )

    def test_book_states_and_database_constraints_cover_recovery(self) -> None:
        required = {
            "INPUT_RESOLUTION_REQUIRED",
            "PLANNING_REQUIRED",
            "PLAN_GENERATING",
            "PLAN_APPROVAL_PENDING",
            "READY",
            "CHAPTER_SUBMITTED",
            "CHAPTER_RUNNING",
            "CHAPTER_GROUP_REQUIRED",
            "CHAPTER_PLAN_REQUIRED",
            "CHAPTER_WAITING_RETRY",
            "CHAPTER_COMPLETED",
            "CHAPTER_ACCEPTANCE_PENDING",
            "FOLLOWUP_PENDING",
            "CHAPTER_FAILED_RETRYABLE",
            "CHAPTER_FAILED_TERMINAL",
            "CANON_PENDING",
            "CANON_COMMITTED",
            "READER_OUTCOME_PENDING",
            "CHECKPOINT_PENDING",
            "REPLAN_REQUIRED",
            "REPLAN_GENERATING",
            "REPLAN_APPROVAL_PENDING",
            "PAUSED",
            "COMPLETED",
            "ABORTED",
        }
        self.assertEqual({item.value for item in BookProductionState}, required)
        base = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260729_0034_unified_business_authority"
        )
        functional = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260806_0073_core_functional_loops"
        )
        sql = "\n".join((*base.upgrade_statements, *functional.upgrade_statements))
        for value in required:
            self.assertIn(f"'{value}'", sql)
        self.assertIn("UNIQUE(project_id, stable_idempotency_key)", sql)
        self.assertIn("REFERENCES authority_operation(operation_id)", sql)
        self.assertIn("CREATE VIEW authority_reader_outcome_projection", sql)
        self.assertIn("CREATE VIEW authority_longform_recap_projection", sql)
        self.assertIn("authority_book_production_active_request_fk_idx", sql)
        self.assertIn("authority_book_chapter_request_saga_fk_idx", sql)
        self.assertEqual(
            LONGFORM_CONTEXT_VERSION_KEYS,
            {
                "volume_plan_version",
                "arc_plan_version",
                "character_state_version",
                "foreshadowing_state_version",
                "quality_trend_version",
                "reward_ledger_version",
                "promise_ledger_version",
                "reader_segment_version",
                "reader_contract_version",
                "platform_profile_version",
            },
        )


if __name__ == "__main__":
    unittest.main()
