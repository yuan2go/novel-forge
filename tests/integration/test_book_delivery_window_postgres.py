from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.book_authority.creation_window import extend_delivery_window
from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW, current_manuscript
from novel_forge.modules.book_authority.production import PostgresBookAuthority, StartBookProductionCommand
from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier
from tests.integration import test_book_to_chapter_authority_vertical_postgres as vertical_support


@pytest.fixture
def work(request):
    ensure_migrated()
    project = identifier("delivery-window")
    case = vertical_support.BookToChapterAuthorityVerticalPostgresTests()
    versions = case._seed_book_inputs(project)
    profile_id = project + ":profile:v1"
    profile = {"book_id": "book:" + project, "target_chapter_count": 240,
        "execution_window": {"version": "creation-execution-window.v1", "stop_after_chapter": 3},
        "author_workflow": getattr(request, "param", AUTHOR_WORKFLOW)}
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES(%s,%s,'production_profile')", [profile_id, project])
        uow.cursor.execute("""INSERT INTO authority_asset_version
            (asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version)
            VALUES(%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'fixture.v1')""", [profile_id, profile_id, Jsonb(profile), canonical_hash(profile)])
        uow.commit()
    principal = case._principal(project)
    principal = replace(principal, permissions=principal.permissions | {"book.authority.query"})
    followup = BookFollowupAuthorityApplication(DATABASE_URL, application_build_id="delivery-window-test", commit_sha="e" * 40)
    authority = PostgresBookAuthority(DATABASE_URL, chapter_port=None, followup_application=followup,
        application_build_id="delivery-window-test", commit_sha="e" * 40, legacy_fixture_input_allowed=True)
    command = StartBookProductionCommand(project_id=project, workspace_id="workspace:" + project, book_id="book:" + project,
        actor_id=principal.principal_id, trace_id=identifier("trace"), correlation_id=identifier("correlation"),
        stable_idempotency_key=project + ":start", book_design_version=versions.pop("book_design_version"),
        book_plan_version=versions.pop("book_plan_version"), production_profile_version=profile_id,
        longform_context_versions=versions, target_chapter_count=3, input_mode="LEGACY_FIXTURE_INPUT_MODE")
    admitted = authority.start(command, principal=principal)
    return authority, principal, command, authority.require(admitted.book_run_id)


def extend(work, target=40, key="extend-40", version=None):
    authority, principal, _, book = work
    return extend_delivery_window(authority, book["book_run_id"], principal=principal,
        expected_version=book["version"] if version is None else version, stop_after_chapter=target,
        idempotency_key=book["book_run_id"] + ":" + key)


def test_extension_preserves_start_and_frontier_and_replays_response_loss(work):
    authority, principal, command, before = work
    def lose_response(checkpoint):
        if checkpoint == "after_operation_completion_before_response":
            raise RuntimeError("lost committed response")
    authority.failure_injector = lose_response
    with pytest.raises(RuntimeError, match="lost committed response"):
        extend(work)
    authority.failure_injector = None
    replay = extend(work)
    assert replay["replayed"] and replay["stop_after_chapter"] == 40
    after = authority.require(before["book_run_id"])
    assert after["target_chapter_count"] == 40 and after["version"] == before["version"] + 1
    for key in ("production_profile_version", "root_operation_id", "saga_id", "book_plan_version", "book_design_version",
                "current_chapter", "accepted_through_chapter", "input_snapshot_id", "state"):
        assert after[key] == before[key]
    assert after["delivery_window_policy"]["full_book_target_chapters"] == 240
    assert authority.start(command, principal=principal).replayed
    assert authority.require(before["book_run_id"])["target_chapter_count"] == 40
    manifest = current_manuscript(DATABASE_URL, book=after, principal=principal)
    assert manifest["target_chapters"] == 40 and manifest["units"] == []
    assert manifest["delivery_window_policy"]["asset_version_id"] == replay["policy_asset_version_id"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s", [before["production_profile_version"]])
        assert uow.cursor.fetchone()[0]["execution_window"]["stop_after_chapter"] == 3
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [before["project_id"]])
        assert uow.cursor.fetchone()[0] == 0
    second = extend(work, target=80, key="extend-80", version=after["version"])
    policy = authority.require(before["book_run_id"])["delivery_window_policy"]
    assert policy["previous_policy_asset_version_id"] == replay["policy_asset_version_id"]
    assert second["book_version"] == after["version"] + 1
    assert extend(work)["policy_asset_version_id"] == replay["policy_asset_version_id"]


@pytest.mark.parametrize("target", [0, 3, 241])
def test_invalid_extension_keeps_original_work(work, target):
    with pytest.raises(KernelError, match="RANGE_INVALID"):
        extend(work, target=target)
    authority, _, _, before = work
    assert authority.require(before["book_run_id"])["target_chapter_count"] == 3


def test_extension_rollback_and_concurrent_checkpoint(work):
    authority, _, _, before = work
    def interrupt(checkpoint):
        if checkpoint == "after_delivery_window_extension":
            raise RuntimeError("interrupt before commit")
    authority.failure_injector = interrupt
    with pytest.raises(RuntimeError, match="interrupt before commit"):
        extend(work)
    authority.failure_injector = None
    assert authority.require(before["book_run_id"])["delivery_window_policy"] is None
    barrier = Barrier(2)
    def run(index):
        barrier.wait(timeout=10)
        try:
            return extend(work, target=40 + index, key="race-" + str(index))["status"]
        except KernelError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert sorted(results) == sorted(["SUCCEEDED", "AUTHOR_WORKFLOW_CHECKPOINT_REQUIRED"])
    assert authority.require(before["book_run_id"])["version"] == before["version"] + 1


def test_unknown_original_effect_and_scope_block_extension(work):
    authority, principal, _, before = work
    other = replace(principal, project_scope=frozenset({"another-project"}))
    with pytest.raises(PermissionError):
        extend_delivery_window(authority, before["book_run_id"], principal=other,
            expected_version=before["version"], stop_after_chapter=40, idempotency_key="wrong-project")
    effect_id = str(uuid4())
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("""INSERT INTO authority_external_effect
            (external_effect_id,operation_id,project_id,effect_type,stable_idempotency_key,status,request_hash,request_payload)
            VALUES(%s,%s,%s,'model.call',%s,'UNKNOWN','sha256:fixture',%s)""",
            [effect_id, before["root_operation_id"], before["project_id"], effect_id,
             Jsonb({"_production_execution": {"book_id": before["book_id"]}})])
        uow.commit()
    with pytest.raises(KernelError, match="RECONCILIATION_REQUIRED"):
        extend(work)
    assert authority.require(before["book_run_id"])["target_chapter_count"] == 3


def test_key_cannot_change_target_or_principal(work):
    authority, principal, _, before = work
    extend(work)
    with pytest.raises(KernelError, match="different request digest"):
        extend(work, target=41)
    with pytest.raises(KernelError, match="different request digest"):
        extend_delivery_window(authority, before["book_run_id"], principal=replace(principal, principal_id="another-author"),
            expected_version=before["version"], stop_after_chapter=40, idempotency_key=before["book_run_id"] + ":extend-40")


@pytest.mark.parametrize("work", [None], indirect=True)
def test_strict_work_requires_native_author_workflow_adoption(work):
    with pytest.raises(KernelError, match="AUTHOR_FIRST_REQUIRED"):
        extend(work)


def test_paused_extension_keeps_pause_and_acceptance(work):
    authority, principal, _, before = work
    authority.pause(before["book_run_id"], reason="author checkpoint", principal=principal)
    paused = authority.require(before["book_run_id"])
    extended = extend(work, version=paused["version"])
    current = authority.require(before["book_run_id"])
    assert current["state"] == "PAUSED" and current["accepted_through_chapter"] == 0
    assert current["paused_reason"] == paused["paused_reason"]
    assert current["version"] == extended["book_version"]
