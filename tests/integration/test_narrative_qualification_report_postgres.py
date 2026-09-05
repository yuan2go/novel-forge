import pytest

from novel_forge.modules.chapter_quality_authority.narrative_qualification import (
    build_narrative_qualification_report,
    narrative_digest,
)
from novel_forge.modules.chapter_quality_authority.narrative_qualification_sources import (
    _native_gate,
    _verified_provider_receipt,
    load_native_narrative_receipts,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _ExternalEffectPepFixturePlanningBinder,
    _principal,
    _seed_inputs,
)


def test_native_qualification_receipts_replay_without_promoting_fixture_or_mutating_authority() -> (
    None
):
    ensure_migrated()
    project_id = identifier("narrative-report-fixture")
    book_id = f"book:{project_id}"
    workspace_id = f"workspace:{project_id}"
    seed_authority_project_book(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id
    )
    sources = _seed_inputs(project_id, book_id, target_chapter_count=6)
    principal = _principal(project_id)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(
            target_chapter_count=6
        ),
        application_build_id="narrative-report-fixture",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:main",
        input_versions={
            role: sources[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key=f"{project_id}:generate",
        trace_id=f"trace:{project_id}",
        correlation_id=book_id,
    )
    generated = application.generate(command, principal=principal)
    for action in (application.approve_candidate, application.activate_candidate):
        action(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{command.idempotency_key}:{action.__name__}",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
    receipts = load_native_narrative_receipts(
        DATABASE_URL, project_id=project_id, book_id=book_id
    )
    assert receipts
    assert any(item.layer == "BOOK_ARCHITECTURE" for item in receipts)
    assert all(
        item.source_table == "authority_narrative_design_qualification"
        for item in receipts
    )
    assert not any(item.source_class == "REAL_PROVIDER_SEMANTIC" for item in receipts)
    assert all(item.gate_status == "PASS" for item in receipts)
    inputs = {
        "project_id": project_id,
        "book_id": book_id,
        "implementation_sha": RELEASE_SHA,
        "implementation_tree_sha": "sha256:" + "c" * 64,
        "receipts": receipts,
    }
    report = build_narrative_qualification_report(**inputs)
    replayed = load_native_narrative_receipts(
        DATABASE_URL, project_id=project_id, book_id=book_id
    )
    assert replayed == receipts
    assert (
        build_narrative_qualification_report(**{**inputs, "receipts": replayed})
        == report
    )
    assert report["status"] == "NOT_PROVEN"
    assert report["evidence_scope"] == "FIXTURE_CONTRACT_ONLY"
    assert report["prose_qualification_allowed"] is False
    assert (
        report["evidence_dimensions"]["HUMAN_EDITORIAL"]["status"] == "WAITING_EVIDENCE"
    )
    assert (
        report["evidence_dimensions"]["PRODUCTION_EVIDENCE"]["status"] == "NOT_PROVEN"
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert _native_gate(
            uow.cursor,
            project_id=project_id,
            book_id=book_id,
            layer="FOUNDATION",
            asset_version_id="unbound-semantic-asset",
            content={},
        ) == ("NOT_PROVEN", "SEMANTIC_ASSET_NOT_IN_READY_FOUNDATION_SET")
        assert _native_gate(
            uow.cursor,
            project_id="missing-foundation-project",
            book_id="missing-foundation-book",
            layer="FOUNDATION",
            asset_version_id="unbound-semantic-asset",
            content={},
        ) == ("NOT_PROVEN", "FOUNDATION_SET_INCOMPLETE")
        assert _native_gate(
            uow.cursor,
            project_id=project_id,
            book_id=book_id,
            layer="BOOK_ARCHITECTURE",
            asset_version_id="unbound-semantic-asset",
            content={},
        ) == ("NOT_PROVEN", "CURRENT_TYPED_PLANNING_BINDING_MISSING")
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_narrative_design_qualification WHERE project_id=%s AND book_id=%s",
            [project_id, book_id],
        )
        assert int(uow.cursor.fetchone()[0]) >= len(receipts)
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_book_chapter_acceptance WHERE project_id=%s",
            [project_id],
        )
        assert uow.cursor.fetchone()[0] == 0
        evidence = {
            "real_model_call": True,
            "result": {},
            "production_execution": {
                "route_snapshot": {"route_snapshot_id": "claimed-route"},
                "execution_handle": {"transport": "REMOTE_PROVIDER_API"},
            },
        }
        log = {
            "operation_id": generated.generation_operation_id,
            "external_effect_id": "missing-effect",
            "provider_evidence": evidence,
        }
        claimed = [None] * 26
        claimed[5] = generated.generation_operation_id
        claimed[18] = claimed[19] = narrative_digest(log)
        claimed[20] = log
        claimed[21] = narrative_digest(evidence)
        claimed[22] = narrative_digest({})
        claimed[23] = "claimed-route"
        assert (
            _verified_provider_receipt(
                uow.cursor, project_id=project_id, row=tuple(claimed)
            )
            is False
        )
    with pytest.raises(ValueError, match="does not exist"):
        load_native_narrative_receipts(
            DATABASE_URL, project_id="other-project", book_id=book_id
        )
