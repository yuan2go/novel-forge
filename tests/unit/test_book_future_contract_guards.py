from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from novel_forge.modules.artifact_lineage import (
    _lineage_impacts,
    PostgresArtifactLineageRepository,
    SemanticDiff,
)
from novel_forge.modules.book_authority.reader_pack import (
    require_current_reader_template,
)
from novel_forge.modules.book_replan.coordinator import BookReplanCoordinator
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_group_authority.replan_retirement import (
    require_replan_retirement,
)
from novel_forge.modules.book_authority.production_policy import require_planning_provider_dispatch
from novel_forge.modules.plan_change_authority.application import (
    _definition,
    COORDINATED_VERSION,
)


def test_accepted_lineage_stops_even_when_other_future_paths_continue():
    rows = [
        ("plan", "accepted", "PROPAGATE", "best_draft_candidate", True),
        ("accepted", "past-child", "PROPAGATE", "context_bundle", False),
        ("plan", "future", "PROPAGATE", "planning_generation_candidate", False),
        ("future", "context", "REQUALIFY", "context_bundle", False),
        ("context", "plan", "PROPAGATE", "planning_generation_candidate", False),
    ]
    impacts = {row[0]: row for row in _lineage_impacts("plan", rows)}
    assert impacts["accepted"][4] is True
    assert set(impacts) == {"accepted", "future", "context"}
    diamond = []
    previous = ["plan"]
    for depth in range(20):
        current = [f"{depth}:a", f"{depth}:b"]
        diamond.extend(
            (source, target, "PROPAGATE", "context_bundle", False)
            for source in previous
            for target in current
        )
        previous = current
    assert len(_lineage_impacts("plan", diamond)) == 40


@pytest.mark.parametrize("rows,code", [
    ([], ""), ([("READY", False, False)], ""),
    ([("PAUSED", False, False)], "RUNTIME_DISPATCH_PAUSED"),
    ([("READY", True, False)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("READY", False, True)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("ABORTED", False, False)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("READY", False, False)] * 2, "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
])
def test_planning_dispatch_honors_the_owning_book_and_creation_checkpoint(rows, code):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    if code:
        with pytest.raises(KernelError, match=code):
            require_planning_provider_dispatch(cursor, project_id="p", operation_id="generation")
    else:
        require_planning_provider_dispatch(cursor, project_id="p", operation_id="generation")


def test_lineage_edge_budget_fails_before_any_invalidation():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("root", f"target-{i}", "PROPAGATE", "context_bundle", False) for i in range(3)
    ]
    with pytest.raises(KernelError, match="finite"):
        PostgresArtifactLineageRepository(cursor).invalidate_downstream(
            project_id="project",
            book_id="book",
            semantic_diff=SemanticDiff("root", ("planning",), "changed", {}),
            reason="reason",
            created_by_operation_id="operation",
            maximum_edges=2,
        )
    assert cursor.execute.call_count == 1
    assert "accepted.status='COMMITTED'" in cursor.execute.call_args.args[0]


def test_current_reader_checks_frozen_template_inside_admission_envelope():
    with (
        patch(
            "novel_forge.modules.book_authority.reader_pack.selected_book_template",
            return_value={
                "version": "creative-book-admission.v1",
                "policy_snapshot": {"policy": {}},
            },
        ),
        patch(
            "novel_forge.modules.book_authority.reader_pack.selected_template",
            return_value={"version": "creative-execution-template.v11"},
        ),
    ):
        require_current_reader_template(None, project_id="p", book_id="b")
    with patch(
        "novel_forge.modules.book_authority.reader_pack.selected_book_template",
        return_value=None,
    ):
        with pytest.raises(KernelError):
            require_current_reader_template(None, project_id="p", book_id="b")


def test_old_auto_candidate_grant_does_not_authorize_planchange():
    coordinator = object.__new__(BookReplanCoordinator)
    coordinator.coordinated_contract = False
    coordinator.plan_change = SimpleNamespace(coordinated_contract=False)
    coordinator.require = lambda _: pytest.fail(
        "Legacy AUTO must not enter new approval"
    )
    assert coordinator.try_auto_approve("replan") is None


def test_replan_retirement_requires_same_run_approved_impact_before_mutation():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    with pytest.raises(KernelError):
        require_replan_retirement(
            cursor,
            project_id="p",
            payload={
                "replan_id": "r",
                "group_run_id": "g",
                "retired_group_plan_version_id": "plan",
                "expected_group_version": 1,
            },
        )
    assert cursor.execute.call_count == 2
    query = cursor.execute.call_args.args[0]
    assert "owned.active_chapter_request_id IS NULL" in query
    assert "owned.version=%s" in query
    assert "proposal.approval_operation_id IS NOT NULL" in query


def test_current_planchange_is_forward_and_pending_proof_is_not_legacy_policy():
    arguments = dict(application_build_id="test", commit_sha="a" * 40)
    old = _definition(
        "plan_change.propose",
        "plan_change_proposal",
        "plan_change.proposal",
        **arguments,
    )
    new = _definition(
        "plan_change.propose",
        "plan_change_proposal",
        "plan_change.proposal",
        definition_version=COORDINATED_VERSION,
        **arguments,
    )
    assert old["definition_version"] == "1.0.4"
    assert "plan_change_validation_candidate_asset_input_allowed" not in old["policy"]
    assert new["definition_version"] == "1.0.6"
    assert new["definition_status"] == "implemented_validation_pending"
    assert new["policy"]["plan_change_validation_candidate_asset_input_allowed"] is True


def test_current_reader_activation_replays_exact_deployment_and_rejects_drift():
    from novel_forge.modules.book_authority.reader_pack import (
        ensure_creation_reader_pack,
    )
    from novel_forge.modules.capability_pack_authority.domain import canonical_hash
    from novel_forge.modules.capability_pack_authority.application import (
        _normalized_artifact_catalog,
    )

    args = SimpleNamespace(
        project_id="p", workspace_id="w", book_id="b", repository_root="unused"
    )
    profile = SimpleNamespace(
        workflow_ref="book_followup_reader_outcome@1.4.0",
        manifest={"identity":{"version":"1.6.0"}},
        artifact_catalog={
            "schema_version": "novelos.capability_pack.artifact_catalog.v1",
            "artifacts": [],
        },
    )
    uow = MagicMock()
    uow.__enter__.return_value = uow
    active = (
        4,
        "deployment",
        "1.6.0",
        "ACTIVE",
        "a" * 40,
        canonical_hash(profile.manifest),
        canonical_hash(_normalized_artifact_catalog(profile.artifact_catalog)),
    )
    uow.cursor.fetchone.return_value = active
    with (
        patch(
            "novel_forge.modules.book_authority.reader_pack.AuthorityUnitOfWork",
            return_value=uow,
        ),
        patch(
            "novel_forge.modules.book_authority.reader_pack.require_current_reader_template"
        ),
        patch(
            "novel_forge.modules.capability_packs.validation_deployment.register_validation_runtime_definitions",
            return_value={"reader_proxy_current": "hash"},
        ),
        patch(
            "novel_forge.modules.capability_packs.longform_profiles.build_reader_outcome_pack_profile",
            return_value=profile,
        ),
        patch(
            "novel_forge.modules.capability_packs.validation_deployment.install_longform_validation_pack"
        ) as install,
    ):
        result = ensure_creation_reader_pack(
            SimpleNamespace(database_url="unused", environment="validation"),
            args,
            principal=MagicMock(),
            build_id="test",
            sha="a" * 40,
            pack_id="reader",
        )
        assert result["replayed"] and result["activation_version"] == 4
        install.assert_not_called()
        uow.cursor.fetchone.return_value = active[:4] + ("b" * 40,) + active[5:]
        with pytest.raises(KernelError, match="match exact"):
            ensure_creation_reader_pack(
                SimpleNamespace(database_url="unused", environment="validation"),
                args,
                principal=MagicMock(),
                build_id="test",
                sha="a" * 40,
                pack_id="reader",
            )
        install.assert_not_called()


def test_group_retirement_cannot_exempt_a_foreign_owner_lease():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        ("book-root", "group-root"),
        (
            {"root_operation_id": "group-root"},
            "book-root",
            "book",
            "impact",
            "proposal",
            "approval",
            "activation",
        ),
        None,
    ]
    with patch("novel_forge.modules.chapter_group_authority.replan_retirement.lock_replan_roots"), pytest.raises(KernelError, match="exact native"):
        require_replan_retirement(
            cursor,
            project_id="p",
            payload={
                "replan_id": "r",
                "group_run_id": "g",
                "retired_group_plan_version_id": "plan",
                "expected_group_version": 2,
            },
            current_operation_id="foreign",
        )
    query = cursor.execute.call_args.args[0]
    assert (
        "definition_version='1.1.0'" in query
        and "command_payload->'payload'=%s" in query
    )


def test_current_planchange_replays_frozen_legacy_operation_without_promotion():
    from novel_forge.modules.plan_change_authority.application import (
        PostgresPlanChangeAuthority,
    )

    app = object.__new__(PostgresPlanChangeAuthority)
    app.database_url = "unused"
    app.application_build_id = "test"
    app.commit_sha = "a" * 40
    app.coordinated_contract = True
    app.registry = SimpleNamespace(available_handler_keys=frozenset())
    app.worker_id = "worker"
    app._register_definitions = lambda: None
    app._proposal_contract_predecessor = lambda **_: ""
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.return_value = ("1.0.4",)
    uow.repositories.attempt_runtime.operation_state.return_value = {
        "status": "SUCCEEDED"
    }
    with (
        patch(
            "novel_forge.modules.plan_change_authority.application.AuthorityUnitOfWork",
            return_value=uow,
        ),
        patch(
            "novel_forge.modules.book_authority.reader_pack.require_current_reader_template"
        ),
        patch(
            "novel_forge.modules.plan_change_authority.application.ContentAuthorityScheduler"
        ),
        patch(
            "novel_forge.modules.plan_change_authority.application.admit_command",
            return_value={"operation_id": "old"},
        ) as admit,
    ):
        result = app._execute(
            definition="plan_change.propose",
            project_id="p",
            workspace_id="w",
            actor_id="actor",
            trace_id="trace",
            correlation_id="corr",
            idempotency_key="frozen",
            payload={"book_id": "book"},
            input_assets=(),
            principal=MagicMock(),
        )
    assert result == "old" and admit.call_args.args[1]["definition_version"] == "1.0.4"
    assert admit.call_args.args[1]["idempotency_key"] == "frozen"


@pytest.mark.parametrize('missing,pending,inserted', [(True, True, True), (True, True, False), (False, True, False), (True, False, False)])
def test_active_planchange_only_appends_missing_impact_for_pending_same_book_replan(missing, pending, inserted):
    from novel_forge.modules.plan_change_authority.application import PostgresPlanChangeAuthority

    proposal = dict(status='ACTIVE', project_id='p', book_id='b', target_asset_version_id='old',
        activation_operation_id='activation', proposal_operation_id='proposal-operation', approval_operation_id='approval')
    app = object.__new__(PostgresPlanChangeAuthority)
    app.database_url = 'unused'
    app.require = lambda _: proposal
    app._workspace_id = lambda *_: 'w'
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.side_effect = [None if missing else (1,), (pending,)]
    uow.repositories.plan_change.reconcile_replaced_target_impact.return_value = inserted
    with patch('novel_forge.modules.plan_change_authority.application.AuthorityUnitOfWork', return_value=uow), patch(
        'novel_forge.modules.chapter_group_authority.replan_retirement.require_replan_activation', return_value=True) as guard:
        assert app.activate('proposal', principal=MagicMock()) == proposal
    if missing and pending:
        guard.assert_called_once()
        uow.repositories.plan_change.reconcile_replaced_target_impact.assert_called_once_with('proposal')
        assert uow.repositories.operation_graph.record_event.call_count == int(inserted)
        uow.commit.assert_called_once()
        if inserted:
            event = uow.repositories.operation_graph.record_event.call_args.args[0]
            assert event['operation_id'] == 'activation'
            assert event['event_type'] == 'plan_change.replaced_target_impact_reconciled'
    else:
        guard.assert_not_called()
        uow.repositories.plan_change.reconcile_replaced_target_impact.assert_not_called()
        uow.repositories.operation_graph.record_event.assert_not_called()
        uow.commit.assert_not_called()


def test_active_planchange_cancellation_rejection_cannot_append_impact_or_event():
    from novel_forge.modules.plan_change_authority.application import PostgresPlanChangeAuthority

    app = object.__new__(PostgresPlanChangeAuthority)
    app.database_url = 'unused'
    app.require = lambda _: dict(status='ACTIVE',project_id='p',book_id='b',target_asset_version_id='old')
    app._workspace_id = lambda *_: 'w'
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.side_effect = [None, (True,)]
    with patch('novel_forge.modules.plan_change_authority.application.AuthorityUnitOfWork', return_value=uow), patch(
        'novel_forge.modules.chapter_group_authority.replan_retirement.require_replan_activation',
        side_effect=KernelError('BOOK_REPLAN_CANCELLED', 'cancelled')):
        with pytest.raises(KernelError, match='BOOK_REPLAN_CANCELLED'):
            app.activate('proposal', principal=MagicMock())
    uow.repositories.plan_change.reconcile_replaced_target_impact.assert_not_called()
    uow.repositories.operation_graph.record_event.assert_not_called()
    uow.commit.assert_not_called()


@pytest.mark.parametrize("rows,code", [
    ([], ""), ([("READY", False, False, True)], ""),
    ([("PAUSED", False, False, True)], "RUNTIME_DISPATCH_PAUSED"),
    ([(None, False, False, None)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("READY", True, False, True)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("READY", False, True, True)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("READY", False, False, False)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("COMPLETED", False, False, True)], "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
    ([("READY", False, False, True)] * 2, "BOOK_GENERATION_EXECUTION_NOT_LIVE"),
])
def test_chapter_preparation_and_dispatch_require_current_native_book(rows, code):
    from novel_forge.modules.book_authority.production_policy import require_chapter_provider_dispatch
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    if code:
        with pytest.raises(KernelError, match=code):
            require_chapter_provider_dispatch(cursor, project_id="p", operation_id="chapter")
    else:
        require_chapter_provider_dispatch(cursor, project_id="p", operation_id="chapter")
