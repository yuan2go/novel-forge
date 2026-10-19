from pathlib import Path

import pytest

from novel_forge.api.authority_dependencies import build_book_followup_authority_application, build_production_execution_composition
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import TrustedPrincipalResolver
from novel_forge.modules.book_authority.memory_backfill import admit_backfill, advance_backfill, memory_coverage
from novel_forge.modules.book_authority.manuscript import freeze_working_context, verify_working_context
from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.book_followup_authority.application import BookFollowupAdmission
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.test_longform_prose_editorial_postgres import _accept_chapter, scripted_book


def test_native_memory_extraction_keeps_receipts_replays_and_source_guards(tmp_path):
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=2)
        _accept_chapter(helper, fixture, 1)
        _accept_chapter(helper, fixture, 2)
        authority = fixture["authority"]
        book = authority.require(fixture["book"].book_run_id)
        env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "memory-native-test", "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            "NOVEL_FORGE_WORKING_MEMORY_PROVIDER": "scripted_provider_v2", "NOVEL_FORGE_WORKING_MEMORY_MODEL": "scripted-test-only",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path)}
        principal = TrustedPrincipalResolver.from_environment(env).resolve_api_principal()
        settings = IndustrialSettings(root=Path(__file__).resolve().parents[2], environment="development", storage_authority="postgresql", database_url=DATABASE_URL)
        from dataclasses import replace
        from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_longform_validation_pack
        from novel_forge.modules.capability_packs.memory_profiles import build_working_memory_pack_profile
        versions = register_validation_runtime_definitions(DATABASE_URL, application_build_id="memory-native-test", commit_sha="e" * 40)
        profile = build_working_memory_pack_profile(settings.root, operation_definition_hash=versions["working_memory"], pack_id="memory-" + book["book_id"].replace(":", "-"))
        install_longform_validation_pack(DATABASE_URL, profile=profile, pack_version="1.0.0", agent_generation=1,
            expected_activation_version=0, project_id=book["project_id"], workspace_id=book["workspace_id"], book_id=book["book_id"],
            application_build_id="memory-native-test", commit_sha="e" * 40, compiler=principal,
            approver=replace(principal, principal_id="memory-test-independent-approver"), agent_admin=principal,
            agent_domain="book_followup", agent_scope_type="BOOK", runtime_environment="development")
        env["NOVEL_FORGE_WORKING_MEMORY_CAPABILITY_PACK_ID"] = profile.pack_id
        execution = build_production_execution_composition(settings, env=env)
        try:
            followup = build_book_followup_authority_application(settings, execution=execution, env=env)
            app = PostgresBookAuthority(DATABASE_URL, chapter_port=None, followup_application=followup,
                application_build_id="memory-native-test", commit_sha="e" * 40)
            options = dict(book_run_id=book["book_run_id"], expected_version=book["version"],
                idempotency_key=book["book_run_id"] + ":extract", principal=principal)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                frozen = freeze_working_context(uow, book, 3, projection_policy={"version": "working-prose-projection.v3",
                    "history_chapters": 2, "recent_complete_chapters": 1, "max_characters": 16000, "queries": [], "guidance_mode": "COMBINED"})
            admitted = admit_backfill(app, followup, **options)
            assert len(admitted["operations"]) == 1
            assert admitted["chapters"] == [1, 2]
            # INVARIANT: Different request keys with identical frozen inputs share the native extraction.
            duplicate = admit_backfill(app, followup, **{**options, "idempotency_key": options["idempotency_key"] + ":duplicate"})
            assert [row["operation_id"] for row in duplicate["operations"]] == [row["operation_id"] for row in admitted["operations"]]
            pending = admitted["operations"]
            while pending:
                row = pending[0]
                first = followup.run_or_recover(BookFollowupAdmission(**row))
                assert first.output.asset_version_id
                assert followup.run_or_recover(BookFollowupAdmission(**row)).output.replayed
                pending = advance_backfill(app, followup, batch_operation_id=admitted["batch_operation_id"], principal=principal)
            replay = admit_backfill(app, followup, **options)
            assert all(row["replayed"] for row in replay["operations"])
            coverage = memory_coverage(DATABASE_URL, project_id=book["project_id"], book_run_id=book["book_run_id"], principal=principal)
            assert {row["coverage"] for row in coverage["sources"]} == {"LOCATED_EMPTY"}
            assert all(row["provenance"]["kind"] == "NATIVE_PROVIDER_OBSERVATION" for row in coverage["sources"])
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                verify_working_context(uow, app.require(book["book_run_id"]), frozen, require_current=False)
                uow.cursor.execute("""SELECT count(*),bool_and(status='SUCCEEDED') FROM authority_external_effect
                    WHERE project_id=%s AND request_payload->>'stage'='working_memory_extract'""", [book["project_id"]])
                assert uow.cursor.fetchone() == (2, True)
            with pytest.raises(KernelError, match="WORKING_MEMORY_CHECKPOINT_STALE"):
                admit_backfill(app, followup, **{**options, "idempotency_key": options["idempotency_key"] + ":stale"})
            from novel_forge.modules.book_authority.memory_backfill import cancel_backfill
            from novel_forge.modules.book_authority.manuscript_memory import save_manuscript_memory
            current = app.require(book["book_run_id"])
            cancelled = admit_backfill(app, followup, **{**options, "expected_version": current["version"],
                "idempotency_key": options["idempotency_key"] + ":cancel", "chapters": [1]})
            operation = cancelled["operations"][0]["operation_id"]
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                state = uow.repositories.attempt_runtime.operation_state(operation, book["project_id"])
            stopped = cancel_backfill(DATABASE_URL, project_id=book["project_id"], book_run_id=book["book_run_id"],
                operation_id=operation, expected_version=state["version"], idempotency_key=operation + ":cancel",
                reason="cancel unstarted extraction", principal=principal)
            assert stopped["status"] == "CANCELLED"
            assert advance_backfill(app, followup, batch_operation_id=cancelled["batch_operation_id"], principal=principal)[0]["operation_id"] == operation
            pending = admit_backfill(app, followup, **{**options, "expected_version": current["version"],
                "idempotency_key": options["idempotency_key"] + ":source-drift", "chapters": [2]})
            target = coverage["sources"][1]
            save_manuscript_memory(app, book["book_run_id"], chapter=2, source_asset_version_id=target["asset_version_id"],
                expected_version=current["version"], observations=[], idempotency_key=operation + ":annotation",
                source_kind="ASSISTANT_ANALYSIS", principal=principal)
            with pytest.raises(KernelError, match="WORKING_MEMORY_SOURCE_STALE"):
                followup.run_or_recover(BookFollowupAdmission(**pending["operations"][0]))
            stale_operation = pending["operations"][0]["operation_id"]
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [stale_operation])
                assert uow.cursor.fetchone()[0] == 0
            repaired = admit_backfill(app, followup, **{**options, "expected_version": app.require(book["book_run_id"])["version"],
                "idempotency_key": options["idempotency_key"] + ":retry", "chapters": [2],
                "retry_operation_id": stale_operation, "retry_reason": "Rebind the changed sidecar without changing original prose"})
            assert repaired["operations"][0]["operation_id"] != stale_operation
            assert followup.run_or_recover(BookFollowupAdmission(**repaired["operations"][0])).output.asset_version_id

        finally:
            execution.close()
    finally:
        helper.doCleanups()
