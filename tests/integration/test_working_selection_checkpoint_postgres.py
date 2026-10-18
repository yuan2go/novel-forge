from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
from psycopg.types.json import Jsonb
import pytest

from novel_forge.modules.book_authority.manuscript import (
    AUTHOR_WORKFLOW,
    _require_workflow_checkpoint,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.modules.story_planning_runtime.preparation_recovery import (
    PREPARED_MAIN_HANDOFF,
    PRE_SUBMIT_FAILURE,
    retired_pre_submit_main,
)
from tests.integration.authority_postgres_support import DATABASE_URL


@contextmanager
def historical_checkpoint():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in (
                "book",
                "book_production",
                "operation",
                "story_planning_runtime_continuation",
                "operation_output_asset",
                "asset_version",
                "asset",
                "asset_locator",
                "external_effect",
                "budget_reservation",
                "external_effect_dispatch",
                "attempt",
                "lease_acquisition",
                "worker_cancel_signal",
                "cancellation_command",
                "effect_dispatch_lease",
                "external_receipt",
                "story_planning_generation",
                "book_chapter_request",
                "book_prose_review_event",
                "book_prose_review_run",
            ):
                connection.execute(
                    f"CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA"
                )

            def insert(table, **values):
                connection.execute(
                    f"INSERT INTO authority_{table} ({','.join(values)}) VALUES ({','.join(['%s'] * len(values))})",
                    [
                        Jsonb(v) if isinstance(v, (dict, list)) else v
                        for v in values.values()
                    ],
                )

            book = dict(
                book_run_id="run",
                project_id="project",
                workspace_id="workspace",
                book_id="book",
                root_operation_id="book-root",
                state="READY",
                current_chapter=19,
                accepted_through_chapter=0,
                version=133,
                production_profile_version="profile",
            )
            insert("book", book_id="book")
            insert("book_production", **book)
            insert(
                "asset_version",
                asset_version_id="profile",
                content=dict(author_workflow=AUTHOR_WORKFLOW),
            )
            source = dict(
                project_id="project",
                workspace_id="workspace",
                book_id="book",
                actor_id="author",
            )
            successor = {**source, "runtime_continuation_id": "control"}
            payload = dict(
                operation_id="source", _production_execution=dict(book_id="book")
            )
            proof = dict(
                source_operation_id="source",
                external_effect_id="main",
                request_hash=canonical_hash(payload),
                dispatch_id="dispatch",
                generation=1,
                diagnostic=PRE_SUBMIT_FAILURE,
            )
            target = dict(
                preparation_handoff=dict(
                    contract_version=PREPARED_MAIN_HANDOFF,
                    prepared_main_failure=proof,
                    source_submission_rights="RELEASED_BY_TERMINAL_PRE_SUBMIT_HANDOFF",
                )
            )
            receipt = dict(
                contract_version="planning-runtime-continuation.v10",
                continuation_id="control",
                source_operation_id="source",
                project_id="project",
                workspace_id="workspace",
                book_id="book",
                source_command=source,
                successor_command=successor,
                target_runtime=target,
            )
            for identity, status, definition, payload_value, cause, version in (
                (
                    "source",
                    "FAILED_FINAL",
                    "story_planning.generate",
                    source,
                    None,
                    "1.21.0",
                ),
                (
                    "child",
                    "SUCCEEDED",
                    "story_planning.generate",
                    successor,
                    "source",
                    "1.21.0",
                ),
                (
                    "registration",
                    "SUCCEEDED",
                    "story_planning.runtime_continuation.register",
                    {},
                    None,
                    "10.0.0",
                ),
            ):
                insert(
                    "operation",
                    operation_id=identity,
                    status=status,
                    definition_name=definition,
                    definition_version=version,
                    project_id="project",
                    workspace_id="workspace",
                    actor_id="author",
                    causation_operation_id=cause,
                    command_payload=dict(payload=payload_value),
                )
            insert(
                "story_planning_runtime_continuation",
                continuation_id="control",
                source_operation_id="source",
                successor_operation_id="child",
                registered_by_operation_id="registration",
                project_id="project",
                workspace_id="workspace",
                book_id="book",
                source_command=source,
                successor_command=successor,
                target_runtime=target,
            )
            insert(
                "asset",
                asset_id="control-asset",
                asset_type="planning_runtime_continuation",
                project_id="project",
            )
            insert(
                "asset_version",
                asset_id="control-asset",
                asset_version_id="receipt",
                content=receipt,
                content_hash=canonical_hash(receipt),
            )
            insert(
                "operation_output_asset",
                operation_id="registration",
                asset_version_id="receipt",
                role="primary",
                content_hash=canonical_hash(receipt),
            )
            insert(
                "external_effect",
                external_effect_id="main",
                operation_id="source",
                project_id="project",
                effect_type="model.invoke",
                status="FAILED_RETRYABLE",
                request_payload=payload,
                request_hash=canonical_hash(payload),
                last_error=PRE_SUBMIT_FAILURE,
            )
            insert(
                "external_effect_dispatch",
                external_effect_id="main",
                dispatch_id="dispatch",
                generation=1,
                status="FAILED_RETRYABLE",
                evidence=PRE_SUBMIT_FAILURE,
            )
            insert(
                "budget_reservation",
                external_effect_id="main",
                operation_id="source",
                project_id="project",
                status="RELEASED",
            )
            insert(
                "attempt",
                attempt_id="attempt",
                operation_id="source",
                status="FAILED_RETRYABLE",
            )
            with connection.cursor() as cursor:
                yield SimpleNamespace(
                    connection=connection,
                    cursor=cursor,
                    book=book,
                    insert=insert,
                    uow=SimpleNamespace(cursor=cursor),
                )
        finally:
            connection.rollback()


def test_advanced_book_reuses_exact_retired_main_proof_only_for_work_selection():
    with historical_checkpoint() as s:
        assert retired_pre_submit_main(
            s.uow, project_id="project", book_id="book", effect_id="main"
        )
        assert (
            _require_workflow_checkpoint(s.uow, s.book, 133, working_selection=True)[
                "current_chapter"
            ]
            == 19
        )
        with pytest.raises(
            KernelError, match="AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED"
        ):
            _require_workflow_checkpoint(s.uow, s.book, 133)
        assert s.connection.execute(
            "SELECT status FROM authority_external_effect WHERE external_effect_id='main'"
        ).fetchone() == ("FAILED_RETRYABLE",)
        assert s.connection.execute(
            "SELECT status FROM authority_attempt WHERE operation_id='source'"
        ).fetchone() == ("FAILED_RETRYABLE",)


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM authority_operation_output_asset",
        "UPDATE authority_asset_version SET content_hash='wrong' WHERE asset_version_id='receipt'",
        "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='registration'",
        "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='child'",
        "UPDATE authority_story_planning_runtime_continuation SET book_id='foreign'",
        "UPDATE authority_external_effect SET request_hash='wrong'",
        "UPDATE authority_external_effect SET last_error=jsonb_set(last_error,'{request_sent}','true')",
        "UPDATE authority_external_effect SET status='UNKNOWN'",
        "UPDATE authority_external_effect_dispatch SET status='UNKNOWN'",
        "UPDATE authority_operation SET status='EXECUTING' WHERE operation_id='source'",
        "UPDATE authority_attempt SET status='RUNNING'",
        "INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('attempt','HELD')",
        "INSERT INTO authority_effect_dispatch_lease(dispatch_id,status) VALUES('dispatch','HELD')",
        "INSERT INTO authority_external_receipt(dispatch_id,status) VALUES('dispatch','VERIFIED')",
        "UPDATE authority_budget_reservation SET status='HELD_UNKNOWN'",
        "UPDATE authority_operation SET definition_version='9.0.0' WHERE operation_id='registration'",
    ],
)
def test_work_selection_does_not_hide_unknown_or_unproven_retirement(statement):
    with historical_checkpoint() as s:
        s.connection.execute(statement)
        with pytest.raises(
            KernelError, match="AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED"
        ):
            _require_workflow_checkpoint(s.uow, s.book, 133, working_selection=True)


@pytest.mark.parametrize(
    "damage", ["", "body-mutation", "plan-mutation", "foreign-book", "current-chapter"]
)
def test_work_selection_and_unknown_budget_share_optional_observer_ownership(damage):
    with historical_checkpoint() as s:
        policy = dict(body_mutation_allowed=False, plan_mutation_allowed=False)
        if damage == "body-mutation":
            policy["body_mutation_allowed"] = True
        if damage == "plan-mutation":
            policy["plan_mutation_allowed"] = True
        s.insert(
            "operation",
            operation_id="observer",
            project_id="project",
            workspace_id="workspace",
            definition_name="longform.prose_review",
            definition_snapshot=dict(
                policy=policy, irreversible_effect_policy=dict(allowed=False)
            ),
        )
        s.insert(
            "book_prose_review_run",
            run_id="review",
            book_run_id="foreign" if damage == "foreign-book" else "run",
            project_id="project",
            workspace_id="workspace",
            manifest=dict(source_isolation="AUTHOR_SELECTED_UNREVIEWED_PROSE"),
        )
        s.insert(
            "book_prose_review_event",
            run_id="review",
            kind="WINDOW_ADMITTED",
            content=dict(operation_id="observer"),
        )
        if damage == "current-chapter":
            s.connection.execute(
                "UPDATE authority_operation SET definition_name='chapter.draft.generate' WHERE operation_id='observer'"
            )
        s.insert(
            "external_effect",
            external_effect_id="review-effect",
            operation_id="observer",
            project_id="project",
            effect_type="model.invoke",
            status="UNKNOWN",
            request_payload=dict(_production_execution=dict(book_id="book")),
        )
        s.insert(
            "budget_reservation",
            external_effect_id="review-effect",
            operation_id="observer",
            project_id="project",
            status="HELD_UNKNOWN",
        )
        if damage:
            with pytest.raises(
                KernelError, match="AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED"
            ):
                _require_workflow_checkpoint(s.uow, s.book, 133, working_selection=True)
        else:
            assert (
                _require_workflow_checkpoint(
                    s.uow, s.book, 133, working_selection=True
                )["version"]
                == 133
            )
            assert s.connection.execute(
                "SELECT status FROM authority_budget_reservation WHERE external_effect_id='review-effect'"
            ).fetchone() == ("HELD_UNKNOWN",)
        with pytest.raises(
            KernelError, match="AUTHOR_WORKFLOW_RECONCILIATION_REQUIRED"
        ):
            _require_workflow_checkpoint(s.uow, s.book, 133)


@pytest.mark.parametrize(
    "field,value",
    [("version", 134), ("state", "CANCELLED"), ("active_chapter_request_id", "other")],
)
def test_work_selection_keeps_version_idle_and_concurrent_request_guards(field, value):
    with historical_checkpoint() as s:
        s.connection.execute(
            f"UPDATE authority_book_production SET {field}=%s", [value]
        )
        with pytest.raises(KernelError, match="AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED"):
            _require_workflow_checkpoint(s.uow, s.book, 133, working_selection=True)
