from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel import budget_runtime, external_effect_runtime
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.contracts import local_cli_remote_outcome_unknown


@pytest.mark.parametrize("outcome,started,usage,unknown", [
    ("UNKNOWN", "started", None, True),
    ("UNKNOWN", "started", "original-usage", False),
    ("TIMED_OUT", "started", None, True),
    ("CANCELLED", "started", "", True),
    ("ORPHANED", None, None, True),
    ("TIMED_OUT", None, None, False),
    ("CANCELLED", None, None, False),
    ("TIMED_OUT", "started", "original-usage", False),
    ("SUCCEEDED", "started", None, False),
])
def test_local_process_terminal_does_not_prove_remote_outcome(outcome, started, usage, unknown):
    assert local_cli_remote_outcome_unknown(
        transport="LOCAL_CLI_REMOTE_INFERENCE", outcome=outcome,
        started_at=started, usage_receipt_ref=usage,
    ) is unknown
    assert not local_cli_remote_outcome_unknown(
        transport="SCRIPTED_FIXTURE", outcome=outcome,
        started_at=started, usage_receipt_ref=usage,
    )


@pytest.mark.parametrize("book", ["original-book", ""])
def test_send_guard_reads_original_book_or_root_before_new_send(monkeypatch, book):
    cursor = SimpleNamespace(execute=Mock(), fetchone=Mock(return_value=("old-root", book)))
    read = Mock(return_value=[{"usage": "UNKNOWN"}])
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", read)
    with pytest.raises(KernelError, match="EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
        budget_runtime.require_known_cli_lineage(cursor, project_id="project", operation_id="replacement")
    read.assert_called_once_with(cursor, "project", root_operation_id="" if book else "old-root", book_id=book)


def test_missing_operation_scope_cannot_authorize_dispatch(monkeypatch):
    cursor = SimpleNamespace(execute=Mock(), fetchone=Mock(return_value=None))
    read = Mock()
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", read)
    with pytest.raises(KernelError, match="CROSS_PROJECT_REFERENCE"):
        budget_runtime.require_known_cli_lineage(cursor, project_id="foreign", operation_id="operation")
    read.assert_not_called()


def test_prepare_generation_does_not_mutate_dispatch_when_lineage_unknown(monkeypatch):
    repository = Mock()
    repository.get_for_update.return_value = {"project_id": "project", "effect_type": "model.invoke"}
    uow = SimpleNamespace(cursor=Mock(), repositories=SimpleNamespace(external_effects=repository))
    uow.cursor.fetchone.return_value = None
    repository.cursor = uow.cursor
    monkeypatch.setattr(external_effect_runtime, "AuthorityUnitOfWork", lambda _: nullcontext(uow))
    monkeypatch.setattr(external_effect_runtime, "require_dispatch_enabled", Mock())
    guard = Mock(side_effect=KernelError("EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED", "Original remote outcome remains unknown"))
    monkeypatch.setattr(budget_runtime, "require_known_cli_lineage", guard)
    context = external_effect_runtime.EffectCommandContext("operation", "project", "actor", "trace", "correlation")
    with pytest.raises(KernelError, match="EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
        external_effect_runtime.prepare_effect_dispatch("unused", context, effect_id="effect")
    repository.prepare_dispatch.assert_not_called()


def test_provider_authorization_stops_before_budget_or_router_mutation(monkeypatch):
    from novel_forge.modules.command_kernel import creative_budget_runtime, routing_bootstrap

    uow = SimpleNamespace(cursor=Mock())
    uow.cursor.fetchone.return_value = None
    monkeypatch.setattr(budget_runtime, "AuthorityUnitOfWork", lambda _: nullcontext(uow))
    monkeypatch.setattr(budget_runtime, "require_known_cli_lineage", Mock(side_effect=KernelError(
        "EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED", "Original remote outcome remains unknown")))
    creative = Mock()
    routing = Mock()
    monkeypatch.setattr(creative_budget_runtime, "assert_creative_budget_dispatch", creative)
    monkeypatch.setattr(routing_bootstrap, "verify_routing_bootstrap_dispatch", routing)
    with pytest.raises(KernelError, match="EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
        budget_runtime.assert_provider_execution_authorized("unused", operation_id="operation",
            external_effect_id="effect", project_id="project")
    creative.assert_not_called()
    routing.assert_not_called()


@pytest.mark.parametrize("basis,amount,expected", [("PRICED", "1.25", "1.25"), ("ACCOUNT_ENTITLEMENT", None, None)])
def test_verified_retained_receipt_preserves_membership_unknown_cost(monkeypatch, basis, amount, expected):
    evidence = {"production_execution": {"receipt": "original"}}
    repository = Mock()
    repository.get_for_update.return_value = {"project_id": "project", "operation_id": "operation", "status": "SUCCEEDED"}
    cursor = Mock()
    cursor.fetchone.side_effect = [None, (1, evidence, external_effect_runtime._hash(evidence), {"evidence": evidence}, "VERIFIED"),
        ("reservation", "SETTLED", amount, 1200, 2, basis)]
    monkeypatch.setattr(external_effect_runtime, "_validated_frozen_provider_capability_profile", lambda _: {"frozen": True})
    context = external_effect_runtime.EffectCommandContext("operation", "project", "actor", "trace", "correlation")
    proof = external_effect_runtime._read_verified_success(SimpleNamespace(cursor=cursor), repository, context, "effect")
    assert proof["budget_reserved_amount"] == expected
    assert proof["budget_accounting_basis"] == basis
    assert proof["budget_reservation_status"] == "SETTLED"
    assert proof["provider_evidence"] == evidence


def test_unclassified_started_codex_exit_requires_original_receipt_reconciliation():
    from novel_forge.modules.production_execution.backends import _codex_process_failure
    from novel_forge.modules.production_execution.contracts import ExecutionOutcome
    from novel_forge.modules.production_execution.process_supervisor import ProcessReceiptStatus

    assert _codex_process_failure(ProcessReceiptStatus.FAILED) == ("PROCESS_EXIT_FAILURE", ExecutionOutcome.UNKNOWN)
    assert _codex_process_failure(ProcessReceiptStatus.START_FAILED)[1] is ExecutionOutcome.RETRYABLE_FAILURE


def test_optional_review_unknown_is_excluded_only_for_native_author_work(monkeypatch):
    from novel_forge.modules.book_authority import manuscript

    cursor = SimpleNamespace(execute=Mock(), fetchone=Mock(return_value=({'book_run_id': 'book-run'},)),
        fetchall=Mock(return_value=[('optional-review',)]))
    monkeypatch.setattr(manuscript, 'effective_workflow', lambda *_: manuscript.AUTHOR_WORKFLOW)
    optional = {'operation_id': 'optional-review', 'usage': 'UNKNOWN'}
    required = {'operation_id': 'draft', 'usage': 'UNKNOWN'}
    original = [optional, required]
    assert manuscript.blocking_working_cli_outcomes(cursor, project_id='project', book_id='book',
        operation_id='next-draft', outcomes=original) == [required]
    assert original == [optional, required]
    monkeypatch.setattr(manuscript, 'effective_workflow', lambda *_: None)
    assert manuscript.blocking_working_cli_outcomes(cursor, project_id='project', book_id='book',
        operation_id='next-draft', outcomes=original) == original


def test_author_review_of_saved_prefix_does_not_depend_on_unknown_future_chapter(monkeypatch):
    from novel_forge.modules.book_authority import manuscript

    cursor = SimpleNamespace(execute=Mock(), fetchone=Mock(side_effect=[None, ({'book_run_id': 'book-run'}, 3)]),
        fetchall=Mock(return_value=[('future-draft',)]))
    monkeypatch.setattr(manuscript, 'effective_workflow', lambda *_: manuscript.AUTHOR_WORKFLOW)
    original = [{'operation_id': 'future-draft'}, {'operation_id': 'own-review'}, {'operation_id': 'prior-draft'}]
    assert manuscript.blocking_working_cli_outcomes(cursor, project_id='project', book_id='book',
        operation_id='own-review', outcomes=original) == original[1:]
    assert cursor.execute.call_args.args[1][3] == 3
    assert original[0]['operation_id'] == 'future-draft'


@pytest.mark.parametrize("unresolved", [False, True])
def test_curated_source_gate_checks_own_lineage_before_reading_or_dispatch(monkeypatch, unresolved):
    from novel_forge.modules.source_import.corpus_ingestion.curated_analysis import require_known_cli_outcomes

    cursor = Mock()
    guard = Mock(side_effect=KernelError("EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED", "Original research outcome unknown") if unresolved else None)
    project_wide = Mock(side_effect=AssertionError("Independent Book requests are not Source dependencies"))
    monkeypatch.setattr(budget_runtime, "require_known_cli_lineage", guard)
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", project_wide)
    if unresolved:
        with pytest.raises(KernelError, match="EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
            require_known_cli_outcomes(cursor, "project", operation_id="research-operation")
    else:
        require_known_cli_outcomes(cursor, "project", operation_id="research-operation")
    guard.assert_called_once_with(cursor, project_id="project", operation_id="research-operation")
    project_wide.assert_not_called()


def test_retained_world_sibling_is_readable_without_restoring_old_commit_rights(monkeypatch):
    from novel_forge.modules.command_kernel import generation_isolation

    evidence = {'result': {'world': 'complete'}}
    repository = Mock()
    repository.get_for_update.return_value = {'project_id': 'project', 'operation_id': 'operation',
        'status': 'SUCCEEDED', 'effect_type': 'model.invoke', 'request_payload': {'stage': 'world_candidates.generate'}}
    cursor = Mock()
    cursor.fetchone.side_effect = [(False, True),
        (1, evidence, external_effect_runtime._hash(evidence), {'evidence': evidence}, 'VERIFIED'),
        ('reservation', 'SETTLED', None, 1200, 2, 'ACCOUNT_ENTITLEMENT')]
    revoked = Mock(side_effect=KernelError('GENERATION_ATTEMPT_ISOLATED', 'Old submission right revoked'))
    monkeypatch.setattr(generation_isolation, 'require_not_isolated', revoked)
    monkeypatch.setattr(external_effect_runtime, '_validated_frozen_provider_capability_profile', lambda _: {'frozen': True})
    context = external_effect_runtime.EffectCommandContext('operation', 'project', 'actor', 'trace', 'correlation')
    proof = external_effect_runtime._read_verified_success(SimpleNamespace(cursor=cursor), repository, context,
        'effect', retained_generation_stage=True)
    assert proof['provider_evidence'] == evidence and proof['budget_reserved_amount'] is None
    revoked.assert_not_called()
    with pytest.raises(KernelError, match='GENERATION_ATTEMPT_ISOLATED'):
        external_effect_runtime._read_verified_success(SimpleNamespace(cursor=cursor), repository, context, 'effect')


@pytest.mark.parametrize('isolated,status,kind,stage', [
    (True, 'SUCCEEDED', 'model.invoke', 'world_candidates.generate'),
    (False, 'UNKNOWN', 'model.invoke', 'world_candidates.generate'),
    (False, 'SUCCEEDED', 'blob.write', 'world_candidates.generate'),
    (False, 'SUCCEEDED', 'model.invoke', 'unsafe-tools'),
])
def test_retained_stage_reader_rejects_late_isolated_results_and_non_world_effects(isolated, status, kind, stage):
    cursor = Mock()
    cursor.fetchone.return_value = (isolated, stage != "unsafe-tools")
    repository = Mock()
    repository.get_for_update.return_value = {'status': status, 'effect_type': kind, 'request_payload': {'stage': stage}}
    context = external_effect_runtime.EffectCommandContext('operation', 'project', 'actor', 'trace', 'correlation')
    with pytest.raises(KernelError, match='EFFECT_RETAINED_STAGE_INVALID'):
        external_effect_runtime._read_verified_success(SimpleNamespace(cursor=cursor), repository, context,
            'effect', retained_generation_stage=True)


@pytest.mark.parametrize("pure,unknown", [(True, False), (True, True), (False, False)])
def test_historical_token_correction_does_not_lock_authorized_pure_generation(monkeypatch, pure, unknown):
    from novel_forge.modules.command_kernel import generation_policy
    cursor = SimpleNamespace(execute=Mock(), fetchone=Mock(return_value=("old-root", "", True)))
    monkeypatch.setattr(generation_policy, "generation_graph", lambda *args: pure)
    read = Mock(return_value=[{"usage": "UNKNOWN"}] if unknown else [])
    monkeypatch.setattr(budget_runtime, "unresolved_cli_outcomes", read)
    if not pure or unknown:
        with pytest.raises(KernelError, match="BUDGET_CORRECTION_BREACH" if not pure else "EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
            budget_runtime.require_known_cli_lineage(cursor, project_id="project", operation_id="op")
    else:
        budget_runtime.require_known_cli_lineage(cursor, project_id="project", operation_id="op")
        read.assert_called_once()
