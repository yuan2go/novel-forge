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
    cursor.fetchone.side_effect = [(1, evidence, external_effect_runtime._hash(evidence), {"evidence": evidence}, "VERIFIED"),
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
