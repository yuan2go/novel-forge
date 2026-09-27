from __future__ import annotations

import unittest
from unittest.mock import patch

from novel_forge.modules.book_authority.input_resolver import (
    BookProductionInputSnapshot,
)
from novel_forge.modules.book_authority.production import (
    LONGFORM_CONTEXT_VERSION_KEYS,
    BookProductionState,
    BookProductionStateClass,
    PostgresBookAuthority,
    SubmitBookChapterCommand,
    book_production_state_semantics,
    stable_chapter_submission_key,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
)
from novel_forge.modules.book_followup_authority.registry import (
    BookFollowupHandlerRegistry,
)
from novel_forge.storage.migrations.runner import MIGRATIONS


class BookProductionAuthorityTests(unittest.TestCase):
    def test_arc_checkpoint_pending_is_a_durable_non_dispatching_wait(self) -> None:
        semantics = book_production_state_semantics(
            BookProductionState.CHECKPOINT_PENDING
        )

        self.assertEqual(semantics.state_class, BookProductionStateClass.DURABLE_WAIT)
        self.assertEqual(
            semantics.next_expected_transition,
            "RECONCILE_ARC_CHECKPOINT_FOLLOWUP",
        )
        self.assertEqual(
            semantics.wake_condition, "ARC_CHECKPOINT_FOLLOWUP_STATE_CHANGED"
        )

    def test_resolved_input_snapshot_exposes_api_serialization(self) -> None:
        self.assertTrue(callable(BookProductionInputSnapshot.to_dict))

    def test_resolved_chapter_rejects_a_substituted_execution_projection(self) -> None:
        class Query:
            def __init__(self, _database_url: str) -> None:
                pass

            def require_chapter_production_admission(self, **_values):
                return {
                    "longform_design_qualification_hash": "sha256:qualified",
                    "admission_hash": "sha256:admitted",
                }

            def require_chapter_execution_plan(self, _candidate_id: str):
                return {
                    "asset_version_id": "execution-plan:governed",
                    "content_hash": "sha256:execution",
                    "source_content_hash": "sha256:source",
                }

        authority = object.__new__(PostgresBookAuthority)
        authority.database_url = "postgresql://unit-test"
        command = SubmitBookChapterCommand(
            book_run_id="book-run:1",
            chapter_number=1,
            title="Chapter 1",
            premise="The governed plan advances.",
            chapter_plan_asset_version_id="chapter-plan:1",
            chapter_plan_content_hash="sha256:source",
            execution_chapter_plan_asset_version_id="execution-plan:substituted",
            execution_chapter_plan_content_hash="sha256:execution",
            parent_group_version_id="chapter-group:1",
            narrative_realization_id="realization:1",
            narrative_realization_slice_id="realization-slice:1",
            narrative_realization_contract_digest="sha256:realization",
            context_candidates=(),
        )

        with patch(
            "novel_forge.modules.book_authority.queries.PostgresBookProductionQuery",
            Query,
        ):
            with self.assertRaisesRegex(
                KernelError, "CHAPTER_PRODUCTION_EXECUTION_PLAN_MISMATCH"
            ):
                authority._require_chapter_production_admission(
                    {
                        "input_mode": "RESOLVED_AUTHORITY_INPUT",
                        "input_snapshot_id": "snapshot:1",
                        "accepted_through_chapter": 0,
                        "active_story_state_version_id": "",
                        "active_canon_snapshot_version_id": "",
                    },
                    command,
                )

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
            set(definitions),
            {"reader_outcome.evaluate", "longform.recap", "longform.prose_review", "screenplay_generate", "screenplay_review", "screenplay_revision"},
        )
        self.assertEqual(handlers, {"novel_forge.book_followup_authority." + name for name in {
            *definitions, "longform.prose_review.sample", "book.screenplay.sample.generate", "book.screenplay.sample.review", "book.screenplay.sample.revision"}})
        for stage in ("screenplay_generate", "screenplay_review", "screenplay_revision"):
            self.assertEqual(definitions[stage]["external_capabilities"], ["model." + stage])
            self.assertTrue(definitions[stage]["policy"]["frozen_inputs_required"])
            self.assertFalse(definitions[stage]["policy"]["body_mutation_allowed"])
        reader = definitions["reader_outcome.evaluate"]
        recap = definitions["longform.recap"]
        prose = definitions["longform.prose_review"]
        self.assertEqual(
            prose["external_capabilities"], ["model.longform_prose_review"]
        )
        self.assertEqual(
            prose["output_contract"]["asset_type"], "longform_prose_review_report"
        )
        self.assertEqual(
            prose["output_contract"]["output_key"], "longform.prose_review.report"
        )
        self.assertFalse(prose["policy"]["body_mutation_allowed"])
        self.assertFalse(prose["policy"]["plan_mutation_allowed"])
        self.assertIn("author_editor", prose["projection_consumers"])
        from novel_forge.modules.book_followup_authority.prose_handler import (
            LongformProseReviewHandler,
        )

        class EffectPort:
            external_effect_backed = True

        registration = BookFollowupHandlerRegistry(
            prose_model_port=EffectPort()
        ).registration("longform.prose_review", prose["definition_version"])
        self.assertIsInstance(registration.handler, LongformProseReviewHandler)
        with self.assertRaises(ValueError):
            LongformProseReviewHandler(object())
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
            set(recap["output_contract"]["optional_auxiliary_asset_types"]),
            {"replan_request", "arc_revision_candidate"},
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
                "arc_plan_versions",
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


def test_cancel_losing_race_to_success_preserves_terminal_child():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from novel_forge.modules.book_authority.production import ChapterAuthorityCommandAdapter
    query = Mock()
    query.require_operation_control_state.side_effect = [
        {'status': 'EXECUTING', 'version': 1}, {'status': 'SUCCEEDED', 'version': 2}]
    adapter = ChapterAuthorityCommandAdapter(SimpleNamespace(query=query, database_url='never-opened'), external_effect_adapters={})
    with patch('novel_forge.modules.book_authority.production.request_cancellation', side_effect=KernelError('OPERATION_VERSION_CONFLICT', 'child committed success')) as request, patch('novel_forge.modules.book_authority.production.cancel_operation_external_effects') as effects:
        result = adapter.cancel(project_id='project', root_operation_id='child', actor_id='operator', reason='stop book',
            idempotency_key='stop', trace_id='trace', correlation_id='correlation')
    assert result['status'] == 'SUCCEEDED'
    assert result['cancellation_requested'] is False
    request.assert_called_once()
    effects.assert_not_called()


def test_cancel_replay_continues_effect_protocol_without_second_control_request():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from novel_forge.modules.book_authority.production import ChapterAuthorityCommandAdapter
    query = Mock()
    query.require_operation_control_state.return_value = {'status': 'CANCELLATION_REQUESTED', 'version': 2}
    adapter = ChapterAuthorityCommandAdapter(SimpleNamespace(query=query, database_url='never-opened'), external_effect_adapters={})
    with patch('novel_forge.modules.book_authority.production.request_cancellation') as request, patch('novel_forge.modules.book_authority.production.cancel_operation_external_effects', return_value=({'status': 'UNKNOWN'},)) as effects:
        result = adapter.cancel(project_id='project', root_operation_id='child', actor_id='operator', reason='stop book',
            idempotency_key='stop', trace_id='trace', correlation_id='correlation')
    assert result['external_effect_cancellations'] == [{'status': 'UNKNOWN'}]
    request.assert_not_called()
    effects.assert_called_once()


def test_submission_recovery_uses_only_the_persisted_request_boundary():
    from dataclasses import asdict
    from unittest.mock import Mock, patch

    authority = object.__new__(PostgresBookAuthority)
    command = SubmitBookChapterCommand(book_run_id="book-run:edition", chapter_number=2,
        title="旧请求恢复", premise="只恢复既有定位合同", chapter_plan_asset_version_id="plan:2",
        chapter_plan_content_hash="sha256:plan", context_candidates=(),
        execution_chapter_plan_asset_version_id="execution:2", execution_chapter_plan_content_hash="sha256:execution",
        parent_group_version_id="group:edition", narrative_realization_id="realization:edition",
        narrative_realization_slice_id="slice:2", narrative_realization_contract_digest="sha256:realization",
        preparation_report={"book_edition": {"revision_id": "edition:frozen"}})
    authority.require_chapter_request = Mock(return_value={"book_run_id": command.book_run_id, "chapter_root_operation_id": None, "command_payload": asdict(command)})
    authority.require = Mock(return_value={"project_id": "project"})
    authority._dispatch_reserved_chapter = Mock(return_value={"chapter_root_operation_id": "root:resumed"})
    authority.submit_chapter = Mock(side_effect=AssertionError("recovery must not reserve again"))
    principal = Mock()
    with patch("novel_forge.modules.book_authority.edition_runtime.edition_dispatch_binding", side_effect=AssertionError("selected edition changed")):
        assert authority.recover_chapter_submission("request:2", principal=principal)["chapter_root_operation_id"] == "root:resumed"
    authority._dispatch_reserved_chapter.assert_called_once_with("request:2", principal=principal)
    authority.submit_chapter.assert_not_called()
