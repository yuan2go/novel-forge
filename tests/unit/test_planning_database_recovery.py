from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import database_recovery as recovery
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def source_fixture(monkeypatch, *, unsafe=False, missing=False, drift=False):
    failure = {'error_code':'PROGRAMMING_BUG', 'failure_class':'programming_bug',
               'error_message':'canceling statement due to statement timeout'}
    inputs = [{'role':'book_plan', 'asset_version_id':'input', 'content_hash':'hash', 'asset_type':'book_plan'}]
    snapshot = ({'release_sha':'old'}, 'snapshot', 'snapshot-hash', 'attempt', inputs)
    responses = iter([(unsafe,), None if missing else snapshot, None])
    cursor = SimpleNamespace(execute=lambda *args: None, fetchone=lambda: next(responses))
    document = SimpleNamespace(content_hash='drift' if drift else 'hash', asset_type='book_plan')
    monkeypatch.setattr(recovery, 'AuthorityAssetQuery', lambda _: SimpleNamespace(require=lambda **kwargs: document))
    return SimpleNamespace(cursor=cursor, database_url='unused'), ('FAILED_FINAL', 3), {'project_id':'project', 'workspace_id':'workspace', 'book_id':'book'}, ('FAILED_FINAL', {}, failure), inputs


def test_known_unsent_recovery_retains_exact_failed_attempt_and_input_identity(monkeypatch):
    uow, row, command, attempt, inputs = source_fixture(monkeypatch)
    before = deepcopy((command, attempt, inputs))
    result = recovery.require_source(uow, source_operation_id='source', row=row, frozen=command, attempt=attempt)
    assert result['mode'] == recovery.MODE
    assert result['database_failure']['source_failure_hash'] == canonical_hash(attempt[2])
    assert result['database_failure']['input_snapshot_hash'] == canonical_hash(inputs)
    assert result['database_failure']['context_status'] == 'NOT_MATERIALIZED'
    assert 'NO_RECORDED_SQLSTATE' in result['database_failure']['classification_basis']
    assert (command, attempt, inputs) == before


@pytest.mark.parametrize('change', ['failure', 'unsafe', 'missing', 'drift'])
def test_unsent_recovery_rejects_unknown_failure_effects_or_lost_provenance(monkeypatch, change):
    uow, row, command, attempt, _ = source_fixture(monkeypatch, unsafe=change=='unsafe', missing=change=='missing', drift=change=='drift')
    if change == 'failure':
        attempt[2]['error_message'] = 'user requested cancellation'
    with pytest.raises(KernelError, match='SOURCE_INVALID|SOURCE_UNSAFE|SNAPSHOT_MISSING|INPUT_DRIFT'):
        recovery.require_source(uow, source_operation_id='source', row=row, frozen=command, attempt=attempt)


@pytest.mark.parametrize('change', ['', 'failure_hash', 'book_id', 'source_attempt_id', 'query_owner', 'sqlstate', 'revalidation_status', 'query_hash'])
def test_supplemental_diagnostic_is_explicit_and_never_backfills_old_attempt(change):
    source = {'database_failure': {'source_failure_hash':'sha256:'+'a'*64,
        **{k:k+'-identity' for k in ('source_operation_id','source_attempt_id','project_id','workspace_id','book_id',
            'original_command_hash','input_snapshot_hash','pack_snapshot_id','pack_snapshot_hash')}}}
    proof = dict(**source['database_failure'], contract_version=recovery.CONTRACT,
        query_owner='mkaos_authority.list_planning_usage', exception_type='psycopg.errors.QueryCanceled', sqlstate='57014',
        diagnostic_status='ACTUAL_READ_ONLY_REPRODUCTION', revalidation_status='PASS_NO_PROVIDER_NO_OUTPUT',
        **{key:'sha256:'+'b'*64 for key in ('query_hash','diagnostic_hash','revalidation_hash')})
    if change:
        proof['source_failure_hash' if change=='failure_hash' else change] = 'wrong'
        with pytest.raises(KernelError, match='DIAGNOSTIC_REQUIRED'):
            recovery.require_diagnostic({'unsent_context_query_diagnostic':proof}, source)
    else:
        result = recovery.require_diagnostic({'unsent_context_query_diagnostic':proof}, source)
        assert result['evidence_kind'] == 'OPERATOR_REPORTED_SUPPLEMENTAL_DIAGNOSTIC_NOT_PROVIDER_OR_HUMAN_REVIEW'
        assert 'sqlstate' not in source['database_failure']


@pytest.mark.parametrize('change', ['', 'model_id', 'reasoning_effort', 'model_backend_id', 'account', 'missing_reference'])
def test_allowed_model_set_does_not_replace_original_stage_runtime(monkeypatch, change):
    from novel_forge.modules.story_planning_runtime import runtime_continuation
    prior = {key:key for key in ('model_provider','model_id','reasoning_effort','runtime_class','model_backend_id','cost_accounting_basis')}
    prior['account'] = {'executable':'original-cli', 'entitlement':{'account_identity_ref':'original-account','authorization_ref':'old-budget'}}
    target = deepcopy(prior)
    target['account']['entitlement']['authorization_ref'] = 'current-authorized-budget'
    if change == 'account':
        target['account']['entitlement']['account_identity_ref'] = 'other-account'
    elif change and change != 'missing_reference':
        target[change] = 'another-allowed-value'
    monkeypatch.setattr(runtime_continuation, '_capacity_authorization', lambda *args, **kwargs: {'capacity_only':True})
    monkeypatch.setattr(recovery, 'completed_reference_route', lambda *args, **kwargs: {'external_effect_id':'effect'})
    reference = None if change == 'missing_reference' else ('original-binding','original-operation',prior)
    uow = SimpleNamespace(cursor=SimpleNamespace(execute=lambda *args:None, fetchone=lambda:reference))
    command = SimpleNamespace(project_id='project',workspace_id='workspace',book_id='book',generator_operation_name='arc_plan.generate',logical_key='arc')
    source = {'source_operation_id':'source','database_failure':{'source_operation_id':'source'}}
    if change:
        with pytest.raises(KernelError, match='ROUTE_DRIFT|ROUTE_MISSING'):
            recovery.authorization(uow, source=source, successor=command, principal=None, target=target)
    else:
        result = recovery.authorization(uow, source=source, successor=command, principal=None, target=target)
        assert result['capacity_only'] is False
        assert result['original_stage_runtime']['operation_id'] == 'original-operation'
        assert result['original_stage_runtime']['evidence_boundary'] == 'SAME_OPENING_STAGE_REFERENCE_NOT_SOURCE_PROVIDER_INPUT'


@pytest.mark.parametrize('change', ['', 'actual_model', 'actual_reasoning', 'actual_backend', 'missing_receipt', 'fixture'])
def test_actual_receipt_must_match_registered_reference_not_just_exist(monkeypatch, change):
    from novel_forge.modules.command_kernel import external_effect_runtime
    prior = dict(model_provider='provider',model_id='model',reasoning_effort='high',model_backend_id='backend',auth_profile_ref='auth')
    route = dict(model_provider='provider',model_id='model',reasoning_effort='high',backend_id='backend',auth_profile_ref='auth',operation_id='reference',route_snapshot_id='route')
    provider = dict(real_model_call=False,fixture_protocol_only=False,provider_id='provider',model_id='model',production_execution=dict(route_snapshot=route,execution_request=dict(operation_id='reference',external_effect_id='effect',stage='arc_plan.generate'),process_evidence=dict(transport='LOCAL_CLI_REMOTE_INFERENCE',terminal_event_observed=True,model_authority=dict(local_user_config_ignored=True,invocation_model='model',invocation_reasoning_effort='high'))))
    if change.startswith('actual_'):
        route[{'actual_model':'model_id','actual_reasoning':'reasoning_effort','actual_backend':'backend_id'}[change]] = 'different'
    if change == 'fixture':
        provider['fixture_protocol_only'] = True
    monkeypatch.setattr(external_effect_runtime,'read_completed_operation_success',lambda *args, **kwargs: None if change=='missing_receipt' else {'provider_evidence':provider})
    uow = SimpleNamespace(database_url='unused',cursor=SimpleNamespace(execute=lambda *args:None,fetchall=lambda:[('effect','request-hash')]))
    command = SimpleNamespace(project_id='project',generator_operation_name='arc_plan.generate',actor_id='actor',trace_id='trace',correlation_id='correlation')
    if change:
        with pytest.raises(KernelError,match='ROUTE_DRIFT'):
            recovery.completed_reference_route(uow,reference_operation_id='reference',command=command,prior=prior)
    else:
        result=recovery.completed_reference_route(uow,reference_operation_id='reference',command=command,prior=prior)
        assert result['external_effect_id']=='effect'
        assert result['request_hash']=='request-hash'
        assert result['identity_basis']=='VERIFIED_COMPLETED_NATIVE_RECEIPT_AND_FROZEN_ROUTE'
