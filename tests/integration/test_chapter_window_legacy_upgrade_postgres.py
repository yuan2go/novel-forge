import pytest

from novel_forge.modules.chapter_group_authority import StartChapterGroupCommand
from novel_forge.modules.hierarchical_planning.window_policy import ChapterWindowPolicy
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration import test_chapter_group_authority_postgres as group_fixture


def test_legacy_admitted_window_recovers_without_rewriting_frozen_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from novel_forge.modules.chapter_group_authority import (
        application as group_application,
    )
    from novel_forge.modules.hierarchical_planning.window_policy import (
        LEGACY_CHAPTER_WINDOW_POLICY,
    )

    ensure_migrated()
    harness = group_fixture.ChapterGroupAuthorityPostgresTests()
    actual_admit = group_application.admit_command
    try:
        fixture = harness._fixture(chapter_count=3)
        authority, principal = fixture["group_authority"], fixture["principal"]
        command = StartChapterGroupCommand(
            project_id=fixture["project_id"],
            workspace_id=f"workspace:{fixture['project_id']}",
            actor_id=principal.principal_id,
            trace_id=identifier("legacy-window-trace"),
            correlation_id=fixture["book"].root_operation_id,
            stable_idempotency_key=identifier("legacy-window-start"),
            book_run_id=fixture["book"].book_run_id,
            group_plan_version_id=fixture["group_plan"]["asset_version_id"],
            group_plan_content_hash=fixture["group_plan"]["content_hash"],
        )

        def admit_pre_policy_contract(database_url, envelope, **kwargs):
            historical = {
                **envelope,
                "input": {
                    **envelope["input"],
                    "payload": {
                        key: value
                        for key, value in envelope["input"]["payload"].items()
                        if key != "window_policy"
                    },
                },
            }
            return actual_admit(database_url, historical, **kwargs)

        def interrupt(point: str) -> None:
            if point == "after_group_admission":
                raise RuntimeError(
                    "historical process lost before group materialization"
                )

        monkeypatch.setattr(
            group_application, "admit_command", admit_pre_policy_contract
        )
        authority.failure_injector = interrupt
        with pytest.raises(RuntimeError, match="historical process lost"):
            authority.start(command, principal=principal)
        monkeypatch.setattr(group_application, "admit_command", actual_admit)
        authority.failure_injector = None
        authority.window_policy = ChapterWindowPolicy(maximum_chapters=1)
        recovered = authority.start(command, principal=principal)
        assert recovered["window_policy"] == LEGACY_CHAPTER_WINDOW_POLICY.snapshot()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT command_payload->'payload' FROM authority_operation WHERE operation_id=%s",
                [recovered["root_operation_id"]],
            )
            assert "window_policy" not in uow.cursor.fetchone()[0]
        assert (
            authority.start(command, principal=principal)["group_run_id"]
            == recovered["group_run_id"]
        )
    finally:
        harness.doCleanups()
