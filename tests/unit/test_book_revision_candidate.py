from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW
from novel_forge.modules.book_authority.production import StartBookProductionCommand
from novel_forge.modules.book_authority.revision_candidate import (
    ORIGIN_VERSION,
    _ROLES,
    require_revision_origin,
    validate_origin_request,
)
from novel_forge.modules.command_kernel.errors import KernelError


def fixture():
    origin = dict(
        version=ORIGIN_VERSION,
        source_book_run_id="source",
        source_book_version=7,
        plan_change_proposal_id="change",
    )
    command = StartBookProductionCommand(
        project_id="p",
        workspace_id="w",
        book_id="b",
        actor_id="operator",
        trace_id="trace",
        correlation_id="correlation",
        stable_idempotency_key="candidate",
        book_design_version="design",
        book_plan_version="plan",
        production_profile_version="profile",
        longform_context_versions={},
        target_chapter_count=3,
        input_mode="RESOLVED_AUTHORITY_INPUT",
        input_snapshot_id="new",
        revision_candidate_origin=origin,
    )
    source = dict(
        project_id="p",
        workspace_id="w",
        book_id="b",
        version=7,
        state="PAUSED",
        accepted_through_chapter=0,
        active_chapter_request_id=None,
        active_child_delegation_id=None,
        root_operation_id="root",
        input_snapshot_id="old",
        production_profile_version="profile",
    )
    previous = {key: key for key in _ROLES}
    previous.update(
        snapshot_id="old",
        project_id="p",
        workspace_id="w",
        book_id="b",
        volume_portfolio_plan_versions=["volume-old"],
        arc_portfolio_plan_versions=["arc-old"],
    )
    current = {
        **previous,
        "snapshot_id": "new",
        "narrative_chapter_cursor": 1,
        "volume_portfolio_plan_versions": ["volume-new"],
        "arc_portfolio_plan_versions": ["arc-new"],
    }
    proposal = dict(
        proposal_id="change",
        project_id="p",
        book_id="b",
        status="ACTIVE",
        target_asset_version_id="volume-old",
        proposed_asset_version_id="volume-new",
        activation_operation_id="activation",
        source_evidence_version_id="diagnosis",
    )
    rows = [
        (source,),
        (
            {
                "payload": asdict(
                    replace(
                        command,
                        input_snapshot_id="opening",
                        revision_candidate_origin=None,
                    )
                )
            },
            "EXECUTING",
        ),
        [(previous,), (current,)],
        (proposal, "w", "SUCCEEDED"),
        [
            (
                "arc-new",
                {"decision_evidence": {"parent_plan_change_proposal_id": "change"}},
                "SUCCEEDED",
            )
        ],
    ]
    cursor = Mock()
    cursor.fetchone.side_effect = lambda: rows.pop(0)
    cursor.fetchall.side_effect = lambda: rows.pop(0)
    authority = SimpleNamespace(
        database_url="unused", _require_completed_opening_workflow_for_snapshot=Mock()
    )
    return command, rows, authority, SimpleNamespace(cursor=cursor)


def verify(command, authority, uow):
    with patch(
        "novel_forge.modules.book_authority.manuscript.effective_workflow",
        return_value=AUTHOR_WORKFLOW,
    ):
        return require_revision_origin(authority, command, uow=uow)


def test_revision_inherits_exact_opening_and_plan_change_without_adoption():
    command, rows, authority, uow = fixture()
    evidence = verify(command, authority, uow)
    assert evidence["source_opening_input_snapshot_id"] == "opening"
    assert evidence["changed_plan_version_ids"] == ["arc-new", "volume-new"]
    assert evidence["author_adoption"] == evidence["formal_acceptance"] == "NOT_GRANTED"
    assert evidence["source_history_rewritten"] is False
    authority._require_completed_opening_workflow_for_snapshot.assert_called_once()
    assert rows == []
    assert all(
        not call.args[0].lstrip().startswith(("UPDATE", "INSERT", "DELETE"))
        for call in uow.cursor.execute.call_args_list
    )


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda rows: rows[0][0].update(book_id="another"), "SOURCE_SCOPE_INVALID"),
        (lambda rows: rows[0][0].update(version=8), "SOURCE_CHECKPOINT_REQUIRED"),
        (
            lambda rows: rows[0][0].update(accepted_through_chapter=1),
            "SOURCE_CHECKPOINT_REQUIRED",
        ),
        (
            lambda rows: rows[0][0].update(active_chapter_request_id="in-flight"),
            "SOURCE_CHECKPOINT_REQUIRED",
        ),
        (lambda rows: rows[0][0].update(state="ABORTED"), "SOURCE_CHECKPOINT_REQUIRED"),
        (
            lambda rows: rows[2][1][0].update(narrative_chapter_cursor=2),
            "GENESIS_INPUT_DRIFT",
        ),
        (
            lambda rows: rows[2][1][0].update(
                initial_canon_snapshot_version="replacement"
            ),
            "GENESIS_INPUT_DRIFT",
        ),
        (
            lambda rows: rows[2][1][0].update(foundation_set_digest="replacement"),
            "GENESIS_INPUT_DRIFT",
        ),
        (lambda rows: rows[3][0].update(status="APPROVED"), "PLAN_CHANGE_REQUIRED"),
        (
            lambda rows: rows[3][0].update(target_asset_version_id="unrelated"),
            "PLAN_CHANGE_REQUIRED",
        ),
        (lambda rows: rows[4].clear(), "PORTFOLIO_LINEAGE_INVALID"),
        (
            lambda rows: rows[4][0][1]["decision_evidence"].update(
                parent_plan_change_proposal_id="other"
            ),
            "PORTFOLIO_LINEAGE_INVALID",
        ),
    ],
)
def test_revision_rejects_source_or_lineage_drift(change, code):
    command, rows, authority, uow = fixture()
    change(rows)
    with pytest.raises(KernelError, match="BOOK_REVISION_" + code):
        verify(command, authority, uow)


def test_revision_rechecks_recorded_provenance_and_opening_failure():
    command, rows, authority, uow = fixture()
    command = replace(
        command,
        revision_candidate_origin={
            **command.revision_candidate_origin,
            "evidence": {"author_adoption": "GRANTED"},
        },
    )
    with pytest.raises(KernelError, match="ORIGIN_EVIDENCE_DRIFT"):
        verify(command, authority, uow)
    command, rows, authority, uow = fixture()
    authority._require_completed_opening_workflow_for_snapshot.side_effect = (
        KernelError("OPENING_UNPROVEN", "missing")
    )
    with pytest.raises(KernelError, match="OPENING_UNPROVEN"):
        verify(command, authority, uow)


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_book_version": True},
        {"source_book_version": -1},
        {"version": "unknown"},
        {"source_book_run_id": ""},
        {"override_gate": True},
    ],
)
def test_revision_request_rejects_unversioned_or_extra_controls(mutation):
    command, *_ = fixture()
    with pytest.raises(KernelError, match="ORIGIN_INVALID"):
        validate_origin_request({**command.revision_candidate_origin, **mutation})


def test_ordinary_start_api_defaults_do_not_enable_revision():
    from novel_forge.api.models import BookAuthorityStartRequest

    request = BookAuthorityStartRequest(
        project_id="p",
        workspace_id="w",
        book_id="b",
        idempotency_key="i",
        target_chapter_count=3,
    )
    assert request.revision_candidate_origin is None
    command, *_ = fixture()
    for incompatible in (
        {"input_mode": "LEGACY_FIXTURE_INPUT_MODE"},
        {"edition_revision_id": "accepted-edition"},
    ):
        with pytest.raises(KernelError, match="ORIGIN_INVALID"):
            require_revision_origin(None, replace(command, **incompatible))
