from unittest.mock import patch
from dataclasses import replace

import pytest

from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.chapter_group_authority.application import PostgresChapterGroupAuthority, StartChapterGroupCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration import test_chapter_group_authority_postgres as group_support


@pytest.mark.parametrize("crash_boundary", ["before_admission", "before_group_link", "reserved_pause_resume", "before_book_link_alternate_actor"])
def test_native_reserved_group_dispatch_recovers_same_request_root_and_delegation(crash_boundary):
    harness = group_support.ChapterGroupAuthorityPostgresTests()
    fixture = harness._fixture()
    try:
        authority, principal, book = fixture["group_authority"], fixture["principal"], fixture["book_authority"]
        group = authority.start(StartChapterGroupCommand(project_id=fixture["project_id"],
            workspace_id="workspace:" + fixture["project_id"], actor_id=principal.principal_id,
            trace_id="recovery-test", correlation_id=fixture["book"].root_operation_id,
            stable_idempotency_key=fixture["project_id"] + ":recovery-group", book_run_id=fixture["book"].book_run_id,
            group_plan_version_id=fixture["group_plan"]["asset_version_id"], group_plan_content_hash=fixture["group_plan"]["content_hash"]),
            principal=principal)
        target = book.chapter_port if crash_boundary != "before_group_link" else None
        if crash_boundary == "before_book_link_alternate_actor":
            def fail_after_admission(point):
                if point == "after_child_admission":
                    raise RuntimeError("reserved before Book link")
            injection = patch.object(book, "_probe", side_effect=fail_after_admission)
        elif target is not None:
            injection = patch.object(type(target), "submit", side_effect=RuntimeError("reserved before admission"))
        else:
            from novel_forge.storage.chapter_group_repositories import ChapterGroupRepository
            injection = patch.object(ChapterGroupRepository, "link_chapter", side_effect=RuntimeError("reserved before group link"))
        with injection, pytest.raises(RuntimeError, match="reserved before"):
            authority.dispatch(group["group_run_id"], harness._chapter_command(fixture, 1), principal=principal)
        reserved = book.require(fixture["book"].book_run_id)
        request = book.require_chapter_request(reserved["active_chapter_request_id"])
        assert bool(request["chapter_root_operation_id"]) is (crash_boundary == "before_group_link")
        assert authority.require(group["group_run_id"])["active_chapter_request_id"] is None
        original_root = None
        original_actor = principal.principal_id
        if crash_boundary == "before_book_link_alternate_actor":
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT operation_id,actor_id FROM authority_operation WHERE project_id=%s AND definition_name='chapter.slice.run'",
                    [fixture["project_id"]])
                original_root, frozen_actor = uow.cursor.fetchone()
                assert frozen_actor == original_actor
            principal = replace(principal, principal_id=original_actor + ":recovery-operator")
        if crash_boundary == "reserved_pause_resume":
            authority.pause(group["group_run_id"], reason="bounded recovery checkpoint", principal=principal)
            resumed = authority.resume(group["group_run_id"], reason="resume exact reserved request", principal=principal)
            assert resumed["state"] == "READY"
            assert resumed["active_chapter_request_id"] is None

        restarted_book = PostgresBookAuthority(DATABASE_URL, chapter_port=book.chapter_port,
            followup_application=book.followup, application_build_id=book.application_build_id,
            commit_sha=book.commit_sha, legacy_fixture_input_allowed=True)
        restarted = PostgresChapterGroupAuthority(DATABASE_URL, book_authority=restarted_book,
            application_build_id=authority.application_build_id, commit_sha=authority.commit_sha)
        with AuthorityUnitOfWork(DATABASE_URL) as lock:
            lock.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ["chapter-group-dispatch-recovery:" + group["book_run_id"]])
            with pytest.raises(KernelError, match="CHAPTER_GROUP_DISPATCH_RECOVERY_CONFLICT"):
                restarted.recover_dispatch(group["group_run_id"], principal=principal)
        result = restarted.recover_dispatch(group["group_run_id"], principal=principal)
        child = restarted_book.require_chapter_request(result["active_chapter_request_id"])
        assert result["state"] == "CHAPTER_RUNNING"
        assert child["chapter_request_id"] == request["chapter_request_id"]
        assert child["chapter_root_operation_id"]
        if original_root:
            assert child["chapter_root_operation_id"] == original_root
        if request["chapter_root_operation_id"]:
            assert child["chapter_root_operation_id"] == request["chapter_root_operation_id"]
        assert restarted.recover_dispatch(group["group_run_id"], principal=principal) == result
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for table, clause in (("authority_book_chapter_request", "project_id=%s"),
                ("authority_child_delegation", "project_id=%s"), ("authority_chapter_group_chapter", "project_id=%s"),
                ("authority_operation", "project_id=%s AND definition_name='chapter.slice.run'")):
                uow.cursor.execute(f"SELECT count(*) FROM {table} WHERE {clause}", [fixture["project_id"]])
                assert uow.cursor.fetchone() == (1,)
            uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [fixture["project_id"]])
            assert uow.cursor.fetchone() == (0,)
            if original_root:
                uow.cursor.execute("SELECT actor_id FROM authority_operation WHERE operation_id=%s", [original_root])
                assert uow.cursor.fetchone() == (original_actor,)
    finally:
        harness.doCleanups()


def test_native_ungrouped_scheduler_recovers_reserved_request_without_duplicate_admission():
    from novel_forge.modules.book_authority.governed_scheduler import PostgresBookAuthorityScheduler
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    from tests.integration.test_book_to_chapter_authority_vertical_postgres import BookToChapterAuthorityVerticalPostgresTests
    harness = BookToChapterAuthorityVerticalPostgresTests()
    fixture = harness._new_book_fixture(target_chapter_count=1)
    try:
        book = fixture["authority"]
        with patch.object(type(book.chapter_port), "submit", side_effect=RuntimeError("reserved before admission")), pytest.raises(RuntimeError):
            book.submit_chapter(harness._chapter_command(fixture, chapter_number=1), principal=fixture["principal"])
        request_id = book.require(fixture["book"].book_run_id)["active_chapter_request_id"]
        scheduler = PostgresBookAuthorityScheduler(book, query=PostgresBookProductionQuery(DATABASE_URL), principal=fixture["principal"])
        tick = scheduler.tick(fixture["book"].book_run_id)
        assert tick.action == "DISPATCH_CHAPTER"
        assert tick.operation_id == book.require_chapter_request(request_id)["chapter_root_operation_id"]
        assert scheduler.tick(fixture["book"].book_run_id).action == "RECONCILE_CHAPTER"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND definition_name='chapter.slice.run'",
                [fixture["project_id"]])
            assert uow.cursor.fetchone() == (1,)
    finally:
        harness.doCleanups()
