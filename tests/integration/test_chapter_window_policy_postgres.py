from dataclasses import replace

import pytest
import psycopg

from novel_forge.modules.chapter_group_authority import StartChapterGroupCommand
from novel_forge.modules.hierarchical_planning.window_policy import ChapterWindowPolicy
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration import test_chapter_group_authority_postgres as group_fixture


@pytest.mark.parametrize("count", (1, 2))
def test_terminal_window_persists_policy_and_replays_after_operator_policy_change(
    count: int,
) -> None:
    ensure_migrated()
    harness = group_fixture.ChapterGroupAuthorityPostgresTests()
    try:
        fixture = harness._fixture(chapter_count=count)
        authority = fixture["group_authority"]
        principal = fixture["principal"]
        command = StartChapterGroupCommand(
            project_id=fixture["project_id"],
            workspace_id=f"workspace:{fixture['project_id']}",
            actor_id=principal.principal_id,
            trace_id=identifier("window-trace"),
            correlation_id=fixture["book"].root_operation_id,
            stable_idempotency_key=identifier("window-start"),
            book_run_id=fixture["book"].book_run_id,
            group_plan_version_id=fixture["group_plan"]["asset_version_id"],
            group_plan_content_hash=fixture["group_plan"]["content_hash"],
        )
        original = authority.start(command, principal=principal)
        assert original["chapter_end"] == count
        assert original["window_policy_digest"] == ChapterWindowPolicy().digest
        authority.window_policy = replace(ChapterWindowPolicy(), maximum_chapters=1)
        replay = authority.start(command, principal=principal)
        assert replay["group_run_id"] == original["group_run_id"]
        assert replay["window_policy"] == original["window_policy"]
        with pytest.raises(
            psycopg.errors.CheckViolation, match="frozen execution window"
        ):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "UPDATE authority_chapter_group_production SET chapter_end=chapter_end+1 WHERE group_run_id=%s",
                    [original["group_run_id"]],
                )
                uow.commit()
        assert authority.require(original["group_run_id"])["chapter_end"] == count
    finally:
        harness.doCleanups()


@pytest.mark.parametrize(
    "failure_point",
    (
        "after_group_admission",
        "after_group_root_ready",
        "after_group_step_ready:chapter_group.prepare",
    ),
)
def test_window_start_recovers_each_durable_admission_boundary(
    failure_point: str,
) -> None:
    ensure_migrated()
    harness = group_fixture.ChapterGroupAuthorityPostgresTests()
    try:
        fixture = harness._fixture(chapter_count=2)
        authority, principal = fixture["group_authority"], fixture["principal"]
        command = StartChapterGroupCommand(
            project_id=fixture["project_id"],
            workspace_id=f"workspace:{fixture['project_id']}",
            actor_id=principal.principal_id,
            trace_id=identifier("window-trace"),
            correlation_id=fixture["book"].root_operation_id,
            stable_idempotency_key=identifier("window-start-recover"),
            book_run_id=fixture["book"].book_run_id,
            group_plan_version_id=fixture["group_plan"]["asset_version_id"],
            group_plan_content_hash=fixture["group_plan"]["content_hash"],
        )

        def interrupt(point: str) -> None:
            if point == failure_point:
                raise RuntimeError("window process interrupted")

        authority.failure_injector = interrupt
        with pytest.raises(RuntimeError, match="process interrupted"):
            authority.start(command, principal=principal)
        authority.failure_injector = None
        authority.window_policy = ChapterWindowPolicy(maximum_chapters=1)
        recovered = authority.start(command, principal=principal)
        assert recovered["state"] == "READY"
        assert recovered["window_policy"] == ChapterWindowPolicy().snapshot()
        assert (
            authority.start(command, principal=principal)["group_run_id"]
            == recovered["group_run_id"]
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [recovered["root_operation_id"]],
            )
            assert uow.cursor.fetchone() == ("EXECUTING",)
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_saga_step WHERE saga_id=%s",
                [recovered["saga_id"]],
            )
            assert uow.cursor.fetchone() == (3,)
    finally:
        harness.doCleanups()


def test_window_insert_rejects_policy_identity_different_from_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from novel_forge.storage.chapter_group_repositories import ChapterGroupRepository
    import psycopg

    ensure_migrated()
    harness = group_fixture.ChapterGroupAuthorityPostgresTests()
    original_create = ChapterGroupRepository.create
    try:
        fixture = harness._fixture(chapter_count=2)
        authority, principal = fixture["group_authority"], fixture["principal"]
        command = StartChapterGroupCommand(
            project_id=fixture["project_id"],
            workspace_id=f"workspace:{fixture['project_id']}",
            actor_id=principal.principal_id,
            trace_id=identifier("window-trace"),
            correlation_id=fixture["book"].root_operation_id,
            stable_idempotency_key=identifier("window-start-tamper"),
            book_run_id=fixture["book"].book_run_id,
            group_plan_version_id=fixture["group_plan"]["asset_version_id"],
            group_plan_content_hash=fixture["group_plan"]["content_hash"],
        )

        def forged_create(repository, row):
            policy = ChapterWindowPolicy(maximum_chapters=99)
            original_create(
                repository,
                {
                    **row,
                    "window_policy": policy.snapshot(),
                    "window_policy_digest": policy.digest,
                },
            )

        monkeypatch.setattr(ChapterGroupRepository, "create", forged_create)
        with pytest.raises(psycopg.errors.CheckViolation, match="admitted snapshot"):
            authority.start(command, principal=principal)
        monkeypatch.setattr(ChapterGroupRepository, "create", original_create)
        recovered = authority.start(command, principal=principal)
        assert recovered["window_policy_digest"] == ChapterWindowPolicy().digest
    finally:
        harness.doCleanups()
