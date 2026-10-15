from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.agent_runtime.harness import AgentHarnessStatus, AgentHarnessUsage, canonical_execution_contract_hash, transcript_payload_hash
from novel_forge.modules.agent_runtime.unsent_recovery import AgentReferenceRecoveryRequest, require_empty_reference_source
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import _hash
from tests.unit.test_unified_agent_harness import _session


@pytest.fixture
def empty_native_reference():
    source = _session(max_turns=1)
    source = replace(source,status=AgentHarnessStatus.COMPLETED,
        accepted_boundary=replace(source.accepted_boundary,accepted_through_chapter=0),
        usage=AgentHarnessUsage(turns=1,external_effects=1))
    instruction = 'Frozen independent reference brief.'
    reference = dict(contract_version='agent-reference-prose.v1',production_eligible=False,
        tools_allowed=False,skills_activation_allowed=False,book_id=source.accepted_boundary.book_id,
        instruction_hash=canonical_execution_contract_hash({'instruction':instruction}))
    contract = {'contract_version':'agent-session-execution-contract.v1','provider_io_policy':'agent-io-budget.v1',
        'reference_prose':reference,'budget':asdict(source.budget),'accepted_boundary':asdict(source.accepted_boundary)}
    source = replace(source,execution_contract=contract,execution_contract_hash=canonical_execution_contract_hash(contract))
    command = dict(instruction=instruction,execution_contract=contract,execution_contract_hash=source.execution_contract_hash,
        agent_session_id=source.agent_session_id,accepted_boundary=asdict(source.accepted_boundary),budget=asdict(source.budget),
        book_id=source.accepted_boundary.book_id,agent_role=source.role.value,
        skill_bindings=[dict(item) for item in source.skill_bindings],tool_policy=[asdict(item) for item in source.tool_policy])
    operation = dict(operation_id=source.operation_id,root_operation_id=source.operation_id,parent_operation_id=None,
        definition_name='agent.session.execute',status='SUCCEEDED',version=3,request_digest='a'*64,
        actor_id='operator',workspace_id=source.workspace_id,command_payload=command)
    empty = dict(basis='frozen_instruction_only',status='ineligible_reference_sample',candidate=None,
        tool_requests=[],owner_decision=None,domain_submission=None,validation_status='reference_only',
        accepted_story_facts=[],domain_acceptance_claimed=False)
    events = [(n,k,p,transcript_payload_hash(p)) for n,k,p in (
        (1,'REQUEST_STARTED',{'instruction':instruction}),(2,'MODEL_MESSAGE',{'final_response':empty}),(3,'REQUEST_COMMITTED',{'response':empty}))]
    payload = dict(action='FINAL',tool_call=None,final_response=empty)
    content = dict(payload=payload,execution_id='original-execution',payload_hash=_hash(payload).removeprefix('sha256:'))
    output = SimpleNamespace(content=content,content_hash=_hash(content))
    effect = dict(status='SUCCEEDED',effect_type='model.invoke',external_effect_id='effect-1',request_payload={'stage':'agent_session','input':{
        'agent_session_id':source.agent_session_id,'instruction':instruction,'execution_contract_hash':source.execution_contract_hash}})
    effect['request_hash'] = _hash(effect['request_payload'])
    identity = dict(execution_id='original-execution',operation_id=source.operation_id,attempt_id='original-attempt',fencing_token=1)
    evidence = {'production_execution':{'execution_request':dict(operation_id=source.operation_id,external_effect_id='effect-1',
        project_id=source.project_id,book_id=source.accepted_boundary.book_id,execution_id='original-execution',attempt_id='original-attempt',fencing_token=1),
        'execution_handle':identity,'execution_result':dict(**identity,outcome='SUCCEEDED',normalized_output_ref='authority-asset-version:original-output')}}
    cursor = Mock()
    cursor.fetchone.side_effect = [(operation,),(False,False,False,False)]
    cursor.fetchall.side_effect = [events,[(effect,evidence,'SUCCEEDED',effect['request_hash'])]]
    uow = SimpleNamespace(cursor=cursor,repositories=SimpleNamespace(
        agent_runtime=SimpleNamespace(require_harness_session=lambda *a,**k:source),
        asset_documents=SimpleNamespace(require=lambda **k:output)))
    principal = Principal('operator',PrincipalType.LOCAL_OPERATOR,frozenset({'agent.authority.admin'}),frozenset({source.project_id}),'unit')
    request = AgentReferenceRecoveryRequest(source.project_id,source.agent_session_id,3,source.version,'a'*64,'b'*40,'Repair omitted frozen instruction delivery')
    return uow,request,principal,operation,effect,empty,output


def test_empty_reference_continuation_retains_original_native_output_and_identity(empty_native_reference):
    uow,request,principal,*_ = empty_native_reference
    source,operation,lineage = require_empty_reference_source(uow,request,principal)
    assert lineage['source_response_asset_version_id'] == 'original-output'
    assert lineage['source_operation_id'] == operation['operation_id'] == source.operation_id
    assert lineage['source_result'] == 'COMPLETE_NATIVE_EMPTY_REFERENCE_RESPONSE'
    assert all(call.args[0].lstrip().startswith('SELECT') for call in uow.cursor.execute.call_args_list)


@pytest.mark.parametrize('fault',['version','body_present','unknown_effect','output_hash','actor','undispatched_effect','handle_identity'])
def test_reference_continuation_cannot_replace_prose_or_unknown_external_work(empty_native_reference,fault):
    uow,request,principal,operation,effect,empty,output = empty_native_reference
    if fault == 'version':
        operation['version'] += 1
    elif fault == 'body_present':
        empty['chapters'] = [{'body':'Already saved prose'}]
    elif fault == 'unknown_effect':
        effect['status'] = 'UNKNOWN'
    elif fault == 'output_hash':
        output.content_hash = 'sha256:'+'0'*64
    elif fault == 'undispatched_effect':
        events = [(n,k,p,transcript_payload_hash(p)) for n,k,p in (
            (1,'REQUEST_STARTED',{}),(2,'MODEL_MESSAGE',{'final_response':empty}),(3,'REQUEST_COMMITTED',{'response':empty}))]
        uow.cursor.fetchall.side_effect = [events,[(effect,{},'SUCCEEDED',effect['request_hash']),({'status':'UNKNOWN'},None,None,None)]]
    elif fault == 'handle_identity':
        rows = list(uow.cursor.fetchall.side_effect)
        rows[1][0][1]['production_execution']['execution_handle']['attempt_id'] = 'foreign-attempt'
        uow.cursor.fetchall.side_effect = rows
    else:
        operation['actor_id'] = 'foreign-actor'
    with pytest.raises(KernelError,match='AGENT_REFERENCE_RECOVERY_'):
        require_empty_reference_source(uow,request,principal)


@pytest.mark.parametrize('fault', [None, 'unknown_effect', 'request_hash', 'instruction', 'admission',
    'projection', 'foreign_execution', 'result', 'stdin', 'process_hash', 'scripted', 'host_context', 'host_knowledge'])
def test_completed_reference_input_requires_original_projection_process_and_result(monkeypatch, fault):
    from novel_forge.modules.agent_runtime.queries import require_completed_reference_input
    from novel_forge.modules.command_kernel import generation_policy, external_effect_runtime
    from novel_forge.storage import authority_uow

    instruction = 'Unit fixture complete frozen reading input.'
    boundary = {'book_id': 'unit-book', 'accepted_through_chapter': 0}
    result = {'action': 'FINAL', 'final_response': {'unit': 'diagnosis'}, 'message': '', 'tool_call': None}
    command = {'instruction': instruction, 'accepted_boundary': boundary, 'agent_session_id': 'unit-session',
        'execution_contract_hash': 'unit-sealed-hash',
        'execution_contract': {'reference_prose': {'task_purpose': 'MANUSCRIPT_READING'}}}
    prompt_hash = 'sha256:' + 'a' * 64
    from novel_forge.modules.chapter_authority.provider_views import controlled_manuscript_reading_views
    task, public_context = controlled_manuscript_reading_views(instruction)
    admission_content = {'contract': {'prompt_materialization': {'provider_view': {
        'component_hashes': {'provider_task_view': _hash(task), 'provider_context_view': _hash(public_context),
            'provider_knowledge': _hash([])}}, 'fully_rendered_prompt_hash': prompt_hash},
        'provider_request_identity': {'input_text_hash': prompt_hash}}}
    admission = SimpleNamespace(asset_version_id='unit-admission', content=admission_content, content_hash=_hash(admission_content))
    request = {'stage': 'agent_session', 'input': {**{k: command[k] for k in (
        'instruction', 'accepted_boundary', 'agent_session_id', 'execution_contract_hash')}},
        '_production_execution': {'capability_runtime': {'provider_admission_asset_version_id': admission.asset_version_id,
            'provider_admission_content_hash': admission.content_hash}}}
    process = {'status': 'SUCCEEDED', 'execution_id': 'unit-execution', 'input_sha256': 'a' * 64}
    receipt = SimpleNamespace(asset_version_id='unit-receipt', content_hash='unit-receipt-hash',
        content={'kind': 'process-receipt', 'payload': process, 'payload_hash': _hash(process).removeprefix('sha256:')})
    evidence = {'real_model_call': True, 'result': result, 'production_execution': {
        'execution_result': {'execution_id': 'unit-execution', 'process_receipt_ref': 'authority-asset-version:unit-receipt'}}}
    if fault == 'instruction':
        request['input']['instruction'] = 'different instruction'
    elif fault == 'admission':
        request['_production_execution']['capability_runtime']['provider_admission_content_hash'] = 'foreign'
    elif fault == 'projection':
        admission.content['contract']['prompt_materialization']['provider_view']['component_hashes']['provider_task_view'] = 'foreign'
    elif fault == 'host_context':
        admission.content['contract']['prompt_materialization']['provider_view']['component_hashes']['provider_context_view'] = 'foreign'
    elif fault == 'host_knowledge':
        admission.content['contract']['prompt_materialization']['provider_view']['component_hashes']['provider_knowledge'] = 'foreign'
    elif fault == 'foreign_execution':
        evidence['production_execution']['execution_result']['execution_id'] = 'foreign'
    elif fault == 'result':
        evidence['result'] = {'action': 'FINAL', 'final_response': {'foreign': True}}
    elif fault == 'stdin':
        process['input_sha256'] = 'b' * 64
        receipt.content['payload_hash'] = _hash(process).removeprefix('sha256:')
    elif fault == 'process_hash':
        receipt.content['payload_hash'] = 'b' * 64
    elif fault == 'scripted':
        evidence['real_model_call'] = False
    request_hash = 'foreign' if fault == 'request_hash' else _hash(request)
    cursor = Mock()
    cursor.fetchall.return_value = [] if fault == 'unknown_effect' else [(command, 'unit-trace', 'unit-correlation', 'unit-effect', request, request_hash)]
    docs = {'unit-admission': admission, 'unit-receipt': receipt}
    uow = SimpleNamespace(cursor=cursor, repositories=SimpleNamespace(asset_documents=SimpleNamespace(
        require=lambda **kwargs: docs[kwargs['asset_version_id']])))
    context = Mock()
    context.__enter__ = Mock(return_value=uow)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(authority_uow, 'AuthorityUnitOfWork', lambda _: context)
    monkeypatch.setattr(generation_policy, 'reference_prose_generation', lambda *args: True)
    monkeypatch.setattr(external_effect_runtime, 'read_completed_operation_success', lambda *args, **kwargs: {'provider_evidence': evidence})
    values = dict(project_id='unit-project', operation_id='unit-operation', execution_id='unit-execution', normalized_result=result)
    if fault:
        with pytest.raises(KernelError, match='REFERENCE_INPUT_'):
            require_completed_reference_input('unit-fixture', **values)
    else:
        actual, proof = require_completed_reference_input('unit-fixture', **values)
        assert actual == instruction and proof['status'] == 'ACTUAL_PROVIDER_INPUT_VERIFIED'
        assert proof['fully_rendered_prompt_hash'] == prompt_hash
