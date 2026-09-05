from __future__ import annotations

import psycopg
import pytest

from novel_forge.modules.book_production.checkpoints import (
    PostgresBookNarrativeCheckpointAuthority,
)

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as book_support,
)


@pytest.fixture
def book_fixture():
    ensure_migrated()
    support = book_support.BookToChapterAuthorityVerticalPostgresTests()
    failure = {"enabled": False}

    def inject(point: str) -> None:
        if failure["enabled"] and point == "after_book_completion_before_cursor":
            raise RuntimeError("completion transaction interrupted")

    fixture = support._new_book_fixture(target_chapter_count=1, failure_injector=inject)
    try:
        yield support, fixture, failure
    finally:
        support.doCleanups()


def test_book_completion_requires_terminal_accepted_boundary(book_fixture) -> None:
    _, fixture, _ = book_fixture
    with pytest.raises(KernelError) as raised:
        fixture["authority"].complete_book_checkpoint(
            fixture["book"].book_run_id, chapter_number=1
        )
    assert raised.value.code == "BOOK_COMPLETION_ACCEPTED_BOUNDARY_REQUIRED"
    book = fixture["authority"].require(fixture["book"].book_run_id)
    assert book["whole_book_completion"] is None
    assert book["state"] != "COMPLETED"


def test_book_completion_crash_rolls_back_and_replay_retains_exact_accepted_history(
    book_fixture,
) -> None:
    support, fixture, failure = book_fixture
    authority, book_run_id = fixture["authority"], fixture["book"].book_run_id
    delegated = authority.submit_chapter(
        support._chapter_command(fixture, chapter_number=1),
        principal=fixture["principal"],
    )
    support._run_child(fixture, delegated["chapter_root_operation_id"])
    authority.reconcile_chapter(delegated["chapter_request_id"])
    authority.accept_chapter(
        delegated["chapter_request_id"], principal=fixture["principal"]
    )
    before = authority.require(book_run_id)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT acceptance_operation_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s",
            [book_run_id],
        )
        acceptance_operation_id = str(uow.cursor.fetchone()[0])
        PostgresBookNarrativeCheckpointAuthority._append_volume_checkpoint(
            uow.cursor,
            project_id=str(before["project_id"]),
            book_id=str(before["book_id"]),
            book_run_id=book_run_id,
            volume_plan_version=before["longform_context_versions"][
                "volume_plan_version"
            ],
            active_chapter_group="",
            chapter_number=1,
            target_chapter_count=1,
            arc_status={},
            reachability={"replan_required": False, "status": "REACHABLE"},
            acceptance_operation_id=acceptance_operation_id,
        )
        uow.cursor.execute(
            "SELECT state,volume_goal_status FROM authority_book_volume_checkpoint WHERE book_run_id=%s",
            [book_run_id],
        )
        assert uow.cursor.fetchone() == ("COMPLETED", "NOT_PROVEN")
        uow.commit()
    failure["enabled"] = True
    with pytest.raises(RuntimeError, match="completion transaction interrupted"):
        authority.complete_book_checkpoint(book_run_id, chapter_number=1)
    failed = authority.require(book_run_id)
    assert failed["whole_book_completion"] is None
    assert failed["version"] == before["version"]
    failure["enabled"] = False
    completed = authority.complete_book_checkpoint(book_run_id, chapter_number=1)
    replayed = authority.complete_book_checkpoint(book_run_id, chapter_number=1)
    report = completed["whole_book_completion"]
    assert completed["state"] == "COMPLETED"
    assert report == replayed["whole_book_completion"]
    assert report["decision"] == "BLOCKED"
    assert report["whole_book_accepted"] is False
    assert (
        report["snapshot"]["accepted_boundary"]["story_state_asset_version_id"]
        == before["active_story_state_version_id"]
    )
    assert (
        report["snapshot"]["accepted_boundary"]["canon_snapshot_asset_version_id"]
        == before["active_canon_snapshot_version_id"]
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_book_completion_case WHERE book_run_id=%s",
            [book_run_id],
        )
        assert uow.cursor.fetchone()[0] == 1
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_book_chapter_acceptance WHERE book_run_id=%s",
            [book_run_id],
        )
        assert uow.cursor.fetchone()[0] == 1
    with pytest.raises(
        psycopg.errors.CheckViolation, match="terminal accepted boundary"
    ):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_book_completion_case(
                    completion_case_id,book_run_id,project_id,book_id,
                    acceptance_id,projection_set_id,chapter_number,
                    operation_id,contract_version,content_hash,decision,report
                )
                SELECT completion_case_id||':forged',book_run_id,project_id,book_id,
                       acceptance_id,projection_set_id,chapter_number,
                       operation_id,contract_version,content_hash,decision,
                       jsonb_set(report,
                         '{snapshot,accepted_boundary,story_state_asset_version_id}',
                         '"unrelated-story-state"'::jsonb)
                FROM authority_book_completion_case WHERE book_run_id=%s
                """,
                [book_run_id],
            )
            uow.commit()
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "DELETE FROM authority_book_completion_case WHERE book_run_id=%s",
                [book_run_id],
            )
            uow.commit()
