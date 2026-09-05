from __future__ import annotations

from dataclasses import replace

from novel_forge.modules.book_authority.completion import (
    PostgresBookCompletionAuthority,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as scripted_book,
)


def test_completion_freezes_native_accepted_sources_without_mutating_history() -> None:
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        delegated = fixture["authority"].submit_chapter(
            helper._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        helper._run_child(fixture, delegated["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
        fixture["authority"].accept_chapter(
            delegated["chapter_request_id"], principal=fixture["principal"]
        )
        book_run_id = fixture["book"].book_run_id
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT row_to_json(a) FROM authority_book_chapter_acceptance a WHERE book_run_id=%s",
                [book_run_id],
            )
            before = uow.cursor.fetchall()
        authority = PostgresBookCompletionAuthority(
            DATABASE_URL,
            application_build_id="completion-source-contract",
            commit_sha="e" * 40,
        )
        command = {
            "project_id": fixture["project_id"],
            "workspace_id": "workspace:" + fixture["project_id"],
            "book_run_id": book_run_id,
            "principal": fixture["principal"],
            "trace_id": identifier("trace"),
            "correlation_id": identifier("correlation"),
            "idempotency_key": identifier("completion-source"),
        }
        case = authority.assess(**command)
        replay = authority.assess(**command)
        assert case["accepted_through"] == 1
        assert len(case["acceptance_ids"]) == 1
        assert replay["case_id"] == case["case_id"]
        assert case["evidence_dimensions"]["HUMAN_EDITORIAL"] == "WAITING_EVIDENCE"
        assert case["evidence_dimensions"]["PRODUCTION_EVIDENCE"] == "NOT_PROVEN"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT row_to_json(a) FROM authority_book_chapter_acceptance a WHERE book_run_id=%s",
                [book_run_id],
            )
            assert uow.cursor.fetchall() == before
            uow.cursor.execute(
                "SELECT acceptance_id,source_record FROM authority_book_completion_source WHERE case_id=%s",
                [case["case_id"]],
            )
            acceptance_id, source = uow.cursor.fetchone()
            assert acceptance_id == case["acceptance_ids"][0]
            assert source["source_eligible"] is True
            assert source["projection_set_id"] == source["acceptance_projection_set_id"]
        queried = authority.require_case(
            **{
                key: command[key]
                for key in ("project_id", "workspace_id", "book_run_id")
            },
            principal=replace(
                fixture["principal"],
                permissions=fixture["principal"].permissions | {"book.authority.query"},
            ),
            case_id=case["case_id"],
        )
        assert queried["source_current"] is True
    finally:
        helper.doCleanups()
