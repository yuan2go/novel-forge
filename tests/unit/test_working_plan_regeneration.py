from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority.plan_recovery import current_working_group_correction
from novel_forge.modules.chapter_authority import working_regeneration as regeneration
from novel_forge.modules.chapter_authority.working_revision import NODES, REGENERATION_NODES, ROOT_VERSION, working_revision_definition
from novel_forge.modules.command_kernel.errors import KernelError


def checkpoint():
    return {'project_id': 'p', 'workspace_id': 'w', 'book_id': 'book', 'book_run_id': 'run',
        'current_chapter': 16, 'accepted_through_chapter': 0, 'state': 'READY',
        'active_chapter_request_id': None, 'stable_idempotency_key': 'formation:production'}


def test_corrected_generation_keeps_normal_native_preparation_and_excludes_optional_gates():
    old = working_revision_definition(application_build_id='build', commit_sha='a' * 40)
    new = working_revision_definition(application_build_id='build', commit_sha='a' * 40, regeneration=True)
    assert old['definition_version'] == ROOT_VERSION
    assert old['policy']['expected_saga_steps'] == len(NODES)
    assert new['definition_version'] == regeneration.ROOT_VERSION
    assert new['policy']['working_regeneration_contract'] == regeneration.CONTRACT
    assert new['policy']['expected_saga_steps'] == 6
    assert [item['definition_name'] for item in new['completion_contract']['required_child_operations']] == [node.definition_name for node in REGENERATION_NODES]
    assert REGENERATION_NODES[-1].definition_name == 'chapter.draft.generate'
    assert new['external_capabilities'] == []
    assert old['command_schema'] == new['command_schema']


@pytest.mark.parametrize('drift', ['accepted', 'old-frontier', 'active-child', 'cancelled', 'aborted', 'running'])
def test_regeneration_cannot_reopen_a_changed_book_checkpoint(drift):
    book = checkpoint()
    if drift == 'accepted':
        book['accepted_through_chapter'] = 16
    elif drift == 'old-frontier':
        book['current_chapter'] = 17
    elif drift == 'active-child':
        book['active_chapter_request_id'] = 'active'
    else:
        book['state'] = {'cancelled': 'CANCELLED', 'aborted': 'ABORTED', 'running': 'CHAPTER_RUNNING'}[drift]
    uow = SimpleNamespace(cursor=Mock())
    with pytest.raises(KernelError, match='MANUSCRIPT_REGENERATION_FRONTIER_INVALID'):
        regeneration.require_correction_scope(uow, book=book, chapter=16, proposal_id='change', plan_id='new')
    uow.cursor.execute.assert_not_called()


@pytest.mark.parametrize('actor', ['operator', 'foreign', None])
def test_regeneration_requires_a_native_plan_change_and_its_original_actor(actor):
    cursor = Mock()
    cursor.fetchone.return_value = ({'activation_operation_id': 'activation', 'target_asset_version_id': 'old-group',
        'proposed_asset_version_id': 'new-group'}, 'hash', 'new-group', 'predecessor', 'root', 'operator')
    uow = SimpleNamespace(cursor=cursor)
    if actor == 'foreign':
        with pytest.raises(KernelError, match='MANUSCRIPT_REGENERATION_PLAN_INVALID'):
            regeneration.require_correction_scope(uow, book=checkpoint(), chapter=16, proposal_id='change', plan_id='new', actor_id=actor)
    else:
        result = regeneration.require_correction_scope(uow, book=checkpoint(), chapter=16, proposal_id='change', plan_id='new', actor_id=actor)
        assert result['predecessor_root_operation_id'] == 'root'
        assert result['corrected_chapter_plan_content_hash'] == 'hash'
        assert result['activation_operation_id'] == 'activation'
    cursor.fetchone.return_value = None
    with pytest.raises(KernelError, match='MANUSCRIPT_REGENERATION_PLAN_INVALID'):
        regeneration.require_correction_scope(uow, book=checkpoint(), chapter=16, proposal_id='unrelated', plan_id='new', actor_id=actor)


@pytest.mark.parametrize('drift', ['', 'earlier-row', 'earlier-event', 'group-range', 'frontier', 'accepted', 'active-child', 'missing-proof', 'ambiguous-proof', 'foreign-ancestry'])
def test_mid_group_realization_preserves_the_delivered_prefix_and_exact_native_replacement(drift):
    old = {'chapter_range': [13, 16], 'chapter_function_matrix': [{'chapter_number': i, 'function': f'original-{i}'} for i in range(13, 17)]}
    old['narrative_event_chain'] = [{'chapter_number': i, 'event_id': f'event-{i}', 'action': f'original-action-{i}'} for i in range(13, 17)]
    new = deepcopy(old)
    new['chapter_function_matrix'][-1]['function'] = 'corrected-first-class'
    book = checkpoint()
    if drift == 'earlier-row':
        new['chapter_function_matrix'][1]['function'] = 'rewritten-history'
    elif drift == 'earlier-event':
        new['narrative_event_chain'][1]['action'] = 'rewritten-action'
    elif drift == 'group-range':
        new['chapter_range'] = [13, 17]
    elif drift == 'frontier':
        book['current_chapter'] = 17
    elif drift == 'accepted':
        book['accepted_through_chapter'] = 16
    elif drift == 'active-child':
        book['active_chapter_request_id'] = 'active'
    cursor = Mock()
    cursor.fetchall.return_value = [] if drift == 'missing-proof' else [(old, new, 'original-group', 'actor')] * (2 if drift == 'ambiguous-proof' else 1)
    cursor.fetchone.return_value = (drift != 'foreign-ancestry',)
    assert current_working_group_correction(cursor, book=book, group_version_id='new-group', working={'target_chapter': 16}) is (not drift)
    assert old['chapter_function_matrix'][1]['function'] == 'original-14'


@pytest.mark.parametrize('drift', ['', 'plan-hash', 'proposal', 'activation', 'actor', 'paused'])
def test_each_regeneration_stage_rechecks_its_frozen_correction(monkeypatch, drift):
    proof = {'corrected_chapter_plan_version_id': 'new', 'proposal_id': 'change', 'activation_operation_id': 'activation',
        'actor_id': 'operator', 'corrected_chapter_plan_content_hash': 'hash'}
    actual = deepcopy(proof)
    book = checkpoint()
    if drift == 'paused':
        book['state'] = 'PAUSED'
    elif drift:
        key = {'plan-hash': 'corrected_chapter_plan_content_hash', 'proposal': 'proposal_id', 'activation': 'activation_operation_id', 'actor': 'actor_id'}[drift]
        actual[key] = 'changed'
    verify = Mock(return_value=actual)
    monkeypatch.setattr(regeneration, 'require_correction_scope', verify)
    root = {'actor_id': 'operator', 'command_payload': {'chapter': 16, 'preparation_report': {regeneration.BINDING: proof}}}
    if drift:
        with pytest.raises(KernelError, match='MANUSCRIPT_REGENERATION_PLAN_INVALID'):
            regeneration.require_frontier(None, root=root, book=book)
    else:
        regeneration.require_frontier(None, root=root, book=book)
    assert root['command_payload']['preparation_report'][regeneration.BINDING] == proof


@pytest.mark.parametrize('state', ['CANCELLED', 'CANCELLATION_REQUESTED', 'FAILED_FINAL', 'DEAD_LETTER'])
def test_stopped_regeneration_has_no_execution_or_selection_right(monkeypatch, state):
    verify = Mock()
    monkeypatch.setattr(regeneration, 'require_correction_scope', verify)
    with pytest.raises(KernelError, match='MANUSCRIPT_REGENERATION_FRONTIER_INVALID'):
        regeneration.require_frontier(None, root={'status': state}, book=checkpoint())
    verify.assert_not_called()


@pytest.mark.parametrize('regenerating,concurrent', [(False, False), (False, True), (True, False), (True, True)])
def test_both_admission_directions_share_atomic_book_exclusion(monkeypatch, regenerating, concurrent):
    from novel_forge.modules.book_authority import manuscript
    from novel_forge.modules.chapter_authority.working_revision import ROOT_VERSIONS
    source = SimpleNamespace(asset_version_id='selected', content_hash='hash')
    monkeypatch.setattr(manuscript, 'selected_source', lambda *args: source)
    proof = {'proposal_id': 'change', 'corrected_chapter_plan_version_id': 'corrected'} if regenerating else None
    monkeypatch.setattr(regeneration, 'require_correction_scope', Mock(return_value=proof))
    report = {'working_revision': {'book_run_id': 'run', 'source_asset_version_id': 'selected', 'source_content_hash': 'hash'}}
    if proof:
        report[regeneration.BINDING] = proof
    cursor = Mock()
    cursor.fetchone.side_effect = [(dict(checkpoint(), version=7),), (False,), (concurrent,)]
    request = SimpleNamespace(preparation_report=report, chapter=16, actor_id='operator', project_id='p', idempotency_key='new')
    if concurrent:
        with pytest.raises(KernelError, match='MANUSCRIPT_REGENERATION_CONCURRENT'):
            regeneration.admission_guard(SimpleNamespace(cursor=cursor), request=request, expected_version=7)
    else:
        regeneration.admission_guard(SimpleNamespace(cursor=cursor), request=request, expected_version=7)
    assert 'FOR UPDATE' in cursor.execute.call_args_list[0].args[0]
    assert cursor.execute.call_args_list[-1].args[1][1] == (list(ROOT_VERSIONS) if regenerating else [regeneration.ROOT_VERSION])


def test_isolation_extension_keeps_every_previous_guard_and_does_not_settle_unknown():
    from novel_forge.storage.migrations.versions import v20261018_0224_working_regeneration_isolation as migration
    assert migration.UPGRADE_STATEMENTS[1].replace(migration._NEW, migration._OLD) == migration.PREVIOUS[0]
    assert "book.state='READY' AND book.active_chapter_request_id IS NULL" in migration._NEW
    assert "NEW.proof->>'usage'='UNKNOWN'" in migration.UPGRADE_STATEMENTS[1]
    assert "NEW.proof->>'business_commit_right'='REVOKED'" in migration.UPGRADE_STATEMENTS[1]


def test_same_idempotency_race_reaches_kernel_payload_check_even_after_source_progress(monkeypatch):
    from novel_forge.modules.book_authority import manuscript
    selected = Mock()
    monkeypatch.setattr(manuscript, 'selected_source', selected)
    verify = Mock()
    monkeypatch.setattr(regeneration, 'require_correction_scope', verify)
    cursor = Mock()
    cursor.fetchone.side_effect = [(dict(checkpoint(), version=99, state='CHAPTER_RUNNING'),), (True,)]
    request = SimpleNamespace(project_id='p', idempotency_key='exact-original', preparation_report={
        'working_revision': {'book_run_id': 'run'}})
    regeneration.admission_guard(SimpleNamespace(cursor=cursor), request=request, expected_version=7)
    selected.assert_not_called()
    verify.assert_not_called()
    assert cursor.execute.call_args.args[1] == ['p', 'exact-original']


@pytest.mark.parametrize('drift', ['', 'missing', 'contract-hash', 'other-run', 'other-chapter', 'revoked-correction'])
def test_current_slice_consumption_requires_the_exact_frozen_corrected_contract(monkeypatch, drift):
    from novel_forge.modules.book_authority import plan_recovery, manuscript
    from novel_forge.modules.hierarchical_planning.realization_domain import NarrativeRealizationContract, realization_hash
    from tests.unit.test_work_realization_contract import observation_contract

    value = observation_contract()
    value['schema_version'] = 'narrative-realization-contract.v4'
    working = {'version': 'working-manuscript-context.v1', 'book_run_id': 'run', 'project_id': value['project_id'],
        'book_id': value['book_id'], 'target_chapter': 2, 'accepted_through_chapter': 0, 'sources': []}
    working['snapshot_hash'] = realization_hash(working)
    value['working_manuscript'] = working
    contract = NarrativeRealizationContract.from_mapping(value)
    book = dict(checkpoint(), project_id=value['project_id'], book_id=value['book_id'], current_chapter=2)
    if drift == 'other-run':
        book['book_run_id'] = 'other'
    if drift == 'other-chapter':
        book['current_chapter'] = 3
    cursor = Mock()
    cursor.fetchone.return_value = None if drift == 'missing' else (value, 'original-actor', 'wrong' if drift == 'contract-hash' else contract.contract_digest)
    current = Mock(return_value=drift != 'revoked-correction')
    monkeypatch.setattr(plan_recovery, 'current_working_group_correction', current)
    verify = Mock()
    monkeypatch.setattr(manuscript, 'verify_working_context', verify)
    assert plan_recovery.current_corrected_working_realization(SimpleNamespace(cursor=cursor), book=book,
        realization_id=contract.realization_id, chapter=2) is (not drift)
    assert verify.call_count == (0 if drift else 1)
    if not drift:
        assert current.call_args.kwargs['actor_id'] == 'original-actor'
        assert "realization.lifecycle='FROZEN'" in cursor.execute.call_args.args[0]
        assert "source.status='SUCCEEDED'" in cursor.execute.call_args.args[0]
        assert "narrative-realization-contract.v4" in cursor.execute.call_args.args[0]


def test_impacted_plan_continuation_retains_every_zero_send_and_identity_guard():
    from novel_forge.storage.migrations.versions import v20261018_0225_impacted_working_plan_continuation as migration

    restored = migration.UPGRADE_STATEMENTS[0].replace('CREATE OR REPLACE FUNCTION', 'CREATE FUNCTION', 1)
    assert restored.replace(migration._NEW_JOIN, migration._OLD_JOIN).replace(migration._NEW_SCOPE, migration._OLD_SCOPE) == migration.PREVIOUS
    assert "original.chapter_plan_version=binding.asset_version_id" in migration._NEW_SCOPE
    assert "original_root.actor_id=source.actor_id" in migration._NEW_SCOPE
    assert "competing.logical_key=binding.logical_key" in migration._NEW_SCOPE
    assert "authority_working_group_prefix_preserved" in migration._NEW_SCOPE


def test_regeneration_preparation_uses_the_actual_author_workflow_projection(monkeypatch):
    from dataclasses import make_dataclass
    from novel_forge.modules.book_authority import manuscript, chapter_dispatch

    book = checkpoint()
    original = SimpleNamespace(chapter=16, idempotency_key='original-request')
    proof = {'predecessor_root_operation_id': 'original-root', 'parent_group_version_id': 'group'}
    monkeypatch.setattr(regeneration, 'require_correction_scope', Mock(return_value=proof))
    monkeypatch.setattr(manuscript, 'effective_workflow', Mock(return_value=manuscript.AUTHOR_WORKFLOW))
    monkeypatch.setattr(manuscript, 'freeze_working_context', Mock(return_value={'target_chapter': 16}))
    cursor = Mock()
    cursor.fetchone.return_value = (False, False, False, False)
    supervisor = Mock()
    supervisor._active_plan.side_effect = [{'asset_version_id': 'group'}, {'asset_version_id': 'new-plan'}]
    supervisor.prepare_chapter_command.return_value = make_dataclass('Prepared', ['preparation_report'])(None)
    reserved = Mock(return_value='native-prepared-request')
    monkeypatch.setattr(chapter_dispatch, 'reserved_chapter_command', reserved)
    request, retained = regeneration.prepare_regeneration(SimpleNamespace(database_url='db', application_build_id='build', commit_sha='sha'),
        supervisor=supervisor, uow=SimpleNamespace(cursor=cursor), book=book, source=SimpleNamespace(asset_version_id='selected'),
        original=original, proposal_id='change', plan_id='new-plan', principal=SimpleNamespace(principal_id='operator'))
    assert request == 'native-prepared-request' and retained == proof
    prepared_book = supervisor.prepare_chapter_command.call_args.kwargs['book']
    assert prepared_book['author_workflow'] == manuscript.AUTHOR_WORKFLOW
    assert prepared_book['accepted_through_chapter'] == 0 and prepared_book['current_chapter'] == 16
    assert 'author_workflow' not in book
