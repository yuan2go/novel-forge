from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority.creation_runtime import drive_book
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.fixture
def drive(monkeypatch):
    from novel_forge.modules.chapter_authority import candidate_repair, derived_recovery
    from novel_forge.modules.chapter_authority import canon_contract_recovery, receipt_recovery, current_semantic_recovery
    from novel_forge.modules.book_authority import retained_recovery

    authority = SimpleNamespace(database_url="unused", require=Mock(return_value={"state": "RUNNING", "project_id": "p"}), cancel=Mock())
    composition = SimpleNamespace(authority=authority, principal=Mock(), query=SimpleNamespace(unresolved_chapter_effects=Mock(return_value=[])))
    for name in (
        "recover_quality_frontier", "recover_support_frontier", "recover_information_frontier",
        "recover_review_frontier", "recover_length_frontier", "recover_length_retry_phase",
        "recover_canon_capacity_frontier", "recover_canon_protocol_frontier", "recover_canon_schema_retry_phase",
    ):
        monkeypatch.setattr(candidate_repair, name, Mock(return_value=False))
    monkeypatch.setattr(derived_recovery, "recover_derived_frontier", Mock(return_value=False))
    for module, name in (
        (canon_contract_recovery, "recover_canon_contract"),
        (canon_contract_recovery, "recover_completed_canon_window"),
        (receipt_recovery, "recover_known_draft_receipt"),
        (current_semantic_recovery, "retire_semantic_frontier"),
        (retained_recovery, "recover_retained_quality"),
    ):
        monkeypatch.setattr(module, name, Mock(return_value=False))
    from novel_forge.modules.command_kernel import generation_isolation
    from novel_forge.modules.chapter_authority import context_transport_recovery
    monkeypatch.setattr(generation_isolation, "recover_chapter_generations", Mock(return_value=False))
    monkeypatch.setattr(context_transport_recovery, "recover_unsent_context_transport", Mock(return_value=False))
    arguments = dict(composition=composition, chapter=object(), book_run_id="b", worker=Mock(), maximum_ticks=3, deadline=float("inf"))
    return arguments, candidate_repair, derived_recovery


def test_original_cancellation_between_hooks_prevents_next_recovery(drive):
    arguments, candidates, _ = drive
    live = True

    def repair(*_, **__):
        nonlocal live
        live = False
        return True

    candidates.recover_quality_frontier.side_effect = repair
    assert drive_book(**arguments, continuation_live=lambda: live) == "CANCELLED"
    candidates.recover_quality_frontier.assert_called_once()
    candidates.recover_support_frontier.assert_not_called()
    arguments["composition"].authority.cancel.assert_called_once()


@pytest.mark.parametrize("boundary", ["cancel", "deadline", "lease", "action-limit"])
def test_forward_recovery_hooks_cannot_bypass_creation_checkpoints(drive, monkeypatch, boundary):
    from novel_forge.modules.chapter_authority import canon_contract_recovery, receipt_recovery
    arguments, candidates, _ = drive
    live = True
    now = 0
    arguments["deadline"] = 1
    arguments["maximum_ticks"] = 1 if boundary == "action-limit" else 3
    monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.monotonic", lambda: now)

    def repair(*_, **__):
        nonlocal live, now
        if boundary in {"cancel", "lease"}:
            live = False
        if boundary == "deadline":
            now = 1
        return True

    def probe():
        if boundary == "lease" and not live:
            raise KernelError("CREATION_EXECUTION_LEASE_LOST", "lease lost after forward recovery")

    canon_contract_recovery.recover_canon_contract.side_effect = repair
    if boundary == "lease":
        with pytest.raises(KernelError, match="lease lost after forward recovery"):
            drive_book(**arguments, execution_probe=probe)
    else:
        expected = "CANCELLED" if boundary == "cancel" else "YIELDED_CHECKPOINT"
        assert drive_book(**arguments, continuation_live=lambda: live, execution_probe=probe) == expected
    canon_contract_recovery.recover_completed_canon_window.assert_not_called()
    receipt_recovery.recover_known_draft_receipt.assert_not_called()
    candidates.recover_quality_frontier.assert_not_called()
    if boundary == "cancel":
        arguments["composition"].authority.cancel.assert_called_once()


def test_derived_recovery_repeated_success_is_finitely_bounded(drive):
    arguments, candidates, derived = drive
    derived.recover_derived_frontier.return_value = True
    assert drive_book(**arguments) == "YIELDED_CHECKPOINT"
    assert derived.recover_derived_frontier.call_count == arguments["maximum_ticks"]
    candidates.recover_quality_frontier.assert_not_called()


def test_deadline_between_hooks_prevents_next_mutation(drive, monkeypatch):
    arguments, candidates, _ = drive
    now = 0
    arguments["deadline"] = 1
    monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.monotonic", lambda: now)

    def repair(*_, **__):
        nonlocal now
        now = 1
        return True

    candidates.recover_quality_frontier.side_effect = repair
    assert drive_book(**arguments) == "YIELDED_CHECKPOINT"
    candidates.recover_support_frontier.assert_not_called()


def test_lost_execution_lease_between_hooks_propagates_before_next_mutation(drive):
    arguments, candidates, _ = drive
    lease_live = True

    def repair(*_, **__):
        nonlocal lease_live
        lease_live = False
        return True

    def probe():
        if not lease_live:
            raise KernelError("CREATION_EXECUTION_LEASE_LOST", "lease lost")

    candidates.recover_quality_frontier.side_effect = repair
    with pytest.raises(KernelError, match="lease lost"):
        drive_book(**arguments, execution_probe=probe)
    candidates.recover_support_frontier.assert_not_called()


def test_original_unknown_remote_receipt_blocks_all_recovery_hooks(drive):
    arguments, candidates, derived = drive
    arguments['composition'].query.unresolved_chapter_effects.return_value = [{'external_effect_id': 'original', 'usage': 'UNKNOWN'}]
    assert drive_book(**arguments) == 'WAIT_EXTERNAL_RECONCILIATION'
    candidates.recover_quality_frontier.assert_not_called()
    derived.recover_derived_frontier.assert_not_called()


def test_remote_uncertainty_between_hooks_blocks_next_action(drive):
    arguments, candidates, _ = drive
    query = arguments['composition'].query.unresolved_chapter_effects

    def new_uncertainty(*_, **__):
        query.return_value = [{'external_effect_id': 'original', 'usage': 'UNKNOWN'}]
        return True

    candidates.recover_quality_frontier.side_effect = new_uncertainty
    assert drive_book(**arguments) == 'WAIT_EXTERNAL_RECONCILIATION'
    candidates.recover_quality_frontier.assert_called_once()
    candidates.recover_support_frontier.assert_not_called()


def test_historical_generation_pause_resumes_owned_runnable_successor(monkeypatch):
    from novel_forge.modules.book_authority.creation_runtime import resume_generation_pause
    from novel_forge.modules.command_kernel import generation_policy
    from novel_forge.storage import authority_uow
    book = {'state':'PAUSED','paused_reason':'GENERATION_RECOVERY_EXHAUSTED','project_id':'p', 'version':10,
        'active_chapter_request_id':'chapter-request'}
    authority = SimpleNamespace(database_url='unused', require=Mock(return_value=book),
        require_chapter_request=Mock(return_value={'chapter_root_operation_id':'root'}), resume=Mock())
    cursor=Mock()
    cursor.fetchone.return_value=(True,)
    uow=SimpleNamespace(cursor=cursor)
    class OwnedUow:
        def __init__(self, *_): pass
        def __enter__(self): return uow
        def __exit__(self, *_): pass
    monkeypatch.setattr(authority_uow, 'AuthorityUnitOfWork', OwnedUow)
    monkeypatch.setattr('novel_forge.modules.book_authority.creation_runtime.AuthorityUnitOfWork', OwnedUow)
    monkeypatch.setattr(generation_policy, 'generation_graph', Mock(return_value=True))
    assert resume_generation_pause(authority,book_run_id='b',principal='principal')
    assert authority.resume.call_args.kwargs['expected_version'] == 10
    assert 'chapter-pure-generation-successor.v1' in cursor.execute.call_args.args[0]
    authority.resume.reset_mock()
    book['paused_reason']='AUTHOR_PAUSE'
    assert not resume_generation_pause(authority,book_run_id='b',principal='principal')
    authority.resume.assert_not_called()
