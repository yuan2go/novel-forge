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
        (receipt_recovery, "recover_applicability_scope_receipt"),
        (current_semantic_recovery, "retire_semantic_frontier"),
        (retained_recovery, "recover_retained_quality"),
    ):
        monkeypatch.setattr(module, name, Mock(return_value=False))
    from novel_forge.modules.command_kernel import generation_isolation
    from novel_forge.modules.chapter_authority import context_transport_recovery
    from novel_forge.modules.chapter_authority import memo_recovery, scene_receipt_recovery
    from novel_forge.modules.story_planning_runtime import runtime_continuation
    from novel_forge.modules.book_authority import creation_inputs
    composition.planning = object()
    monkeypatch.setattr(creation_inputs, "refresh_creation_style_scope", Mock(return_value=False))
    monkeypatch.setattr(runtime_continuation, "recover_world_result_frontier", Mock(return_value=False))
    for name in ("recover_memo_references", "recover_memo_completion", "recover_intent_references"):
        monkeypatch.setattr(memo_recovery, name, Mock(return_value=False))
    monkeypatch.setattr(scene_receipt_recovery, "recover_scene_source_union", Mock(return_value=False))
    monkeypatch.setattr(generation_isolation, "recover_chapter_generations", Mock(return_value=False))
    monkeypatch.setattr(context_transport_recovery, "recover_unsent_context_transport", Mock(return_value=False))
    monkeypatch.setattr(context_transport_recovery, "recover_optional_memory_transport", Mock(return_value=False))
    monkeypatch.setattr(context_transport_recovery, "recover_schema_transport", Mock(return_value=False))
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


def test_operator_pause_blocks_the_next_recovery_hook(drive):
    arguments, candidates, _ = drive
    authority = arguments['composition'].authority
    authority.require.return_value = {'state': 'PAUSED', 'paused_reason': 'AUTHOR_PAUSE', 'project_id': 'p'}
    candidates.recover_quality_frontier.side_effect = AssertionError('A paused Book cannot start another recovery action')
    assert drive_book(**arguments) == 'PAUSED'
    candidates.recover_quality_frontier.assert_not_called()


@pytest.mark.parametrize(('state', 'reason', 'expected'), [
    ('PAUSED', 'AUTHOR_PAUSE', 'PAUSED'),
    ('ABORTED', '', 'CANCELLED'),
    ('CANCELLED', '', 'CANCELLED'),
    ('COMPLETED', '', 'COMPLETED'),
])
def test_exhausted_recovery_preserves_intervening_author_or_terminal_checkpoint(drive, monkeypatch, state, reason, expected):
    from novel_forge.modules.command_kernel import generation_isolation
    arguments, _, _ = drive
    authority = arguments['composition'].authority
    authority.pause = Mock()
    book = authority.require.return_value

    def exhaustion(*_, **__):
        book.update(state=state, paused_reason=reason)
        raise KernelError('GENERATION_RECOVERY_EXHAUSTED', 'Original generation cannot continue')

    monkeypatch.setattr(generation_isolation, 'recover_chapter_generations', exhaustion)
    assert drive_book(**arguments) == expected
    assert book['paused_reason'] == reason
    authority.pause.assert_not_called()


def test_exhausted_recovery_pause_binds_observed_book_version(drive, monkeypatch):
    from novel_forge.modules.command_kernel import generation_isolation
    arguments, _, _ = drive
    authority = arguments['composition'].authority
    authority.require.return_value['version'] = 7
    authority.pause = Mock(side_effect=KernelError('BOOK_MUTATION_CONFLICT', 'Author changed Book after exhaustion'))
    monkeypatch.setattr(generation_isolation, 'recover_chapter_generations', Mock(
        side_effect=KernelError('GENERATION_RECOVERY_EXHAUSTED', 'Original generation cannot continue')))
    with pytest.raises(KernelError, match='Author changed Book'):
        drive_book(**arguments)
    assert authority.pause.call_args.kwargs['expected_version'] == 7


def test_pause_rejects_stale_version_before_mutating_saga_or_book():
    from novel_forge.modules.book_authority.production import PostgresBookAuthority
    authority = object.__new__(PostgresBookAuthority)
    authority.require = Mock(return_value={'version': 8, 'state': 'PAUSED',
        'paused_reason': 'AUTHOR_PAUSE', 'project_id': 'p'})
    authority._book_graph_context = Mock()
    with pytest.raises(KernelError, match='Book checkpoint changed') as error:
        authority.pause('b', reason='GENERATION_RECOVERY_EXHAUSTED', principal=Mock(), expected_version=7)
    assert error.value.code == 'BOOK_MUTATION_CONFLICT'
    authority._book_graph_context.assert_not_called()


def test_operator_pause_during_recovery_blocks_the_following_action(drive):
    from novel_forge.modules.chapter_authority import canon_contract_recovery
    arguments, candidates, _ = drive
    book = arguments['composition'].authority.require.return_value

    def pause(*_, **__):
        book.update(state='PAUSED', paused_reason='AUTHOR_PAUSE')
        return True

    canon_contract_recovery.recover_canon_contract.side_effect = pause
    canon_contract_recovery.recover_completed_canon_window.side_effect = AssertionError('A paused Book cannot start the next recovery')
    assert drive_book(**arguments) == 'PAUSED'
    canon_contract_recovery.recover_completed_canon_window.assert_not_called()
    candidates.recover_quality_frontier.assert_not_called()


def test_pause_after_unknown_isolation_prevents_successor_dispatch(drive, monkeypatch):
    from novel_forge.modules.book_authority import creation_runtime
    from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW
    from novel_forge.modules.command_kernel import generation_isolation
    from novel_forge.workers import book_authority

    arguments, _, _ = drive
    composition = arguments['composition']
    book = composition.authority.require.return_value
    book.update(state='CHAPTER_RUNNING', author_workflow=AUTHOR_WORKFLOW,
        current_chapter=0, target_chapter_count=100)
    composition.query.progress = Mock(return_value=SimpleNamespace(
        active_operation_id='original-root', active_operation_status='WAITING_CHILDREN'))
    jobs = SimpleNamespace(claim=Mock(return_value=object()))
    monkeypatch.setattr(creation_runtime, 'RuntimeJobAuthority', lambda _: jobs)
    monkeypatch.setattr(book_authority, 'schedule_book_coordination_jobs', Mock())
    monkeypatch.setattr(book_authority, 'execute_book_coordination_claim', Mock(return_value={
        'action': 'WAIT_CHAPTER', 'operation_id': 'original-root'}))
    scheduler = SimpleNamespace(tick=Mock())
    arguments['chapter'] = SimpleNamespace(scheduler=Mock(return_value=scheduler))
    generation_isolation.recover_chapter_generations.side_effect = [False, True]

    def interrupted(**_):
        assert scheduler.tick.call_count == 1, 'Paused Book dispatched another Chapter stage'
        book.update(state='PAUSED', paused_reason='AUTHOR_PAUSE')
        raise KernelError('MODEL_EFFECT_OUTCOME_UNKNOWN', 'Original result remains unknown')

    scheduler.tick.side_effect = interrupted
    assert drive_book(**arguments) == 'PAUSED'
    assert generation_isolation.recover_chapter_generations.call_count == 2
    scheduler.tick.assert_called_once()
    composition.authority.cancel.assert_not_called()


@pytest.mark.parametrize('boundary', ['recover', 'cancel', 'paused', 'deadline', 'unresolved', 'unbound', 'foreign', 'unchanged'])
def test_shared_book_driver_recovers_only_owned_unstarted_planning_deployment(monkeypatch, boundary):
    from novel_forge.modules.book_authority import creation_runtime as runtime
    book = dict(book_run_id='book-run', project_id='project', workspace_id='workspace', book_id='book', state='READY')
    authority = SimpleNamespace(database_url='db', require=Mock(return_value=book), cancel=Mock())
    binding = None if boundary == 'unbound' else {'formation_run_id':'formation'}
    formation = dict(project_id='foreign' if boundary == 'foreign' else 'project', workspace_id='workspace', book_id='book')
    policy = {'auto_authorization': {'authorized_by_principal_id':'author'}}
    composition = SimpleNamespace(authority=authority, principal=SimpleNamespace(principal_id='author'),
        query=SimpleNamespace(creation_executor_binding=Mock(return_value=binding), unresolved_chapter_effects=Mock(return_value=boundary=='unresolved')),
        formation=SimpleNamespace(require=Mock(return_value=formation),frozen_input=Mock(return_value=SimpleNamespace(generation_policy=policy))))
    error = KernelError('PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT', 'retain original pending successor')
    monkeypatch.setattr(runtime, '_drive_book', Mock(side_effect=error))
    recovery = Mock(return_value=boundary != 'unchanged')
    monkeypatch.setattr(runtime, '_recover_pending_planning_deployment', recovery)
    if boundary == 'paused':
        book['state'] = 'PAUSED'
    arguments = dict(composition=composition, chapter=object(), book_run_id='book-run', worker=Mock(), maximum_ticks=1,
        deadline=0 if boundary=='deadline' else float('inf'), continuation_live=lambda:boundary!='cancel')
    if boundary in {'unbound','foreign','unchanged'}:
        with pytest.raises(KernelError):
            runtime.drive_book(**arguments)
    else:
        assert runtime.drive_book(**arguments) == {'recover':'YIELDED_CHECKPOINT','cancel':'CANCELLED','paused':'PAUSED',
            'deadline':'YIELDED_CHECKPOINT','unresolved':'WAIT_EXTERNAL_RECONCILIATION'}[boundary]
    if boundary in {'recover','unchanged'}:
        recovery.assert_called_once()
    else:
        recovery.assert_not_called()
