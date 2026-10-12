from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_workflow_postgres_support import (
    build_workflow_fixture,
)


@pytest.fixture(scope="module", autouse=True)
def migrations():
    ensure_migrated()


def aborted_unwritten_fixture():
    fixture = build_workflow_fixture(target_chapter_count=6)
    admission = fixture.admit()
    claim = fixture.claim("unwritten-repair-source")
    assert claim is not None
    fixture.execute(claim)
    source = fixture.opening.require(admission.opening_run_id)
    source = fixture.opening.abort(
        admission.opening_run_id,
        expected_version=source["version"],
        principal=fixture.principal,
    )
    return fixture, source


def test_native_same_book_replacement_replays_and_activates_with_exact_predecessor():
    fixture, source = aborted_unwritten_fixture()
    arguments = dict(
        expected_version=source["version"],
        idempotency_key="repair:typed-allocation",
        reason="Book volume allocation lost at the Provider schema boundary",
        principal=fixture.principal,
    )
    successor = fixture.opening.reopen_unwritten(source["opening_run_id"], **arguments)
    replay = fixture.opening.reopen_unwritten(source["opening_run_id"], **arguments)
    assert replay.replayed and replay.opening_run_id == successor.opening_run_id
    frozen = fixture.opening._frozen_request(successor.opening_run_id)
    assert frozen.book_id == fixture.book_id
    assert frozen.planning_input_versions == fixture.request.planning_input_versions
    assert frozen.planning_replacement is not None
    old_plan = frozen.planning_replacement["expected_active_plan_versions"]["book:main"]
    claim = fixture.claim("unwritten-repair-successor")
    assert claim is not None
    fixture.execute(claim)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT asset_version_id FROM active_story_plan_version WHERE project_id=%s AND book_id=%s AND logical_key='book:main'",
            [fixture.project_id, fixture.book_id],
        )
        assert uow.cursor.fetchone()[0] != old_plan
        uow.cursor.execute(
            "SELECT freshness FROM story_plan_binding WHERE project_id=%s AND asset_version_id=%s",
            [fixture.project_id, old_plan],
        )
        assert uow.cursor.fetchone()[0] == "STALE"
        uow.cursor.execute(
            "SELECT count(*) FROM authority_book_production WHERE project_id=%s AND book_id=%s",
            [fixture.project_id, fixture.book_id],
        )
        assert uow.cursor.fetchone()[0] == 0
    assert fixture.opening.require(source["opening_run_id"])["lifecycle"] == "ABORTED"
    assert len(fixture.binder.generator_calls) == 6


def test_unwritten_repair_rejects_stale_foreign_frozen_and_changed_plan_boundaries():
    fixture, source = aborted_unwritten_fixture()
    arguments = dict(
        expected_version=source["version"] - 1,
        idempotency_key="repair:bad-version",
        reason="schema allocation repair",
        principal=fixture.principal,
    )
    with pytest.raises(KernelError, match="REPLACEMENT_SOURCE_INVALID"):
        fixture.opening.reopen_unwritten(source["opening_run_id"], **arguments)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(KernelError, match="REPLACEMENT_SOURCE_INVALID"):
            fixture.opening._unwritten_replacement_versions_in_uow(
                uow.cursor,
                request=replace(fixture.request, book_id="book:foreign"),
                source_opening_run_id=source["opening_run_id"],
                source_version=source["version"],
            )
    with AuthorityUnitOfWork(DATABASE_URL, coordinate_nested=True) as uow:
        uow.cursor.execute(
            "UPDATE story_plan_binding SET execution_scope='FROZEN' WHERE project_id=%s AND book_id=%s",
            [fixture.project_id, fixture.book_id],
        )
        with pytest.raises(KernelError, match="REPLACEMENT_SCOPE_INVALID"):
            fixture.opening.reopen_unwritten(
                source["opening_run_id"],
                **{**arguments, "expected_version": source["version"]},
            )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        versions = fixture.opening._unwritten_replacement_versions_in_uow(
            uow.cursor,
            request=fixture.request,
            source_opening_run_id=source["opening_run_id"],
            source_version=source["version"],
        )
    changed = replace(
        fixture.request,
        idempotency_key="repair:changed-map",
        planning_replacement={
            "contract_version": "unwritten-book-planning-replacement.v1",
            "source_opening_run_id": source["opening_run_id"],
            "source_version": source["version"],
            "reason": "schema allocation repair",
            "expected_active_plan_versions": {
                **versions,
                "volume:unexpected": versions["book:main"],
            },
        },
    )
    with pytest.raises(KernelError, match="REPLACEMENT_VERSION_CONFLICT"):
        fixture.opening.admit(changed, principal=fixture.principal)
