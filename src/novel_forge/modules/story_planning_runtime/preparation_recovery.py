from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from .domain import canonical_hash


def preparation_boundary(database_url, *, command, operation_id, capture, current):
    from copy import deepcopy
    from .runtime_continuation import require_binding

    if not command.runtime_continuation_id:
        return current
    binding = require_binding(database_url, command.runtime_continuation_id)
    handoff = binding['target_runtime'].get('preparation_handoff')
    if not handoff:
        return current
    if (binding['project_id'], binding['workspace_id'], binding['book_id'], binding['successor_operation_id']) != (
        command.project_id, command.workspace_id, command.book_id, operation_id):
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Preparation custody requires the registered successor')
    if canonical_hash(capture) != handoff['preparation_source_projection_hash']:
        return current
    return deepcopy(handoff['preparation_source_boundary'])


def reuse_completed_task(database_url, *, command, operation_id, stage, task):
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_acknowledged_preparation_success_in_uow
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from .runtime_continuation import require_binding

    if not command.runtime_continuation_id:
        return None
    binding = require_binding(database_url, command.runtime_continuation_id)
    handoff = binding['target_runtime'].get('preparation_handoff')
    if not handoff:
        return None
    if (binding['project_id'], binding['workspace_id'], binding['book_id'], binding['successor_operation_id'], binding['source_command']['actor_id']) != (
        command.project_id, command.workspace_id, command.book_id, operation_id, command.actor_id):
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Only the registered same-Book successor and author may consume original preparation')
    matches = [item for item in handoff['retained_preparation'] if item['stage'] == stage and item['task_hash'] == canonical_hash(task)]
    if not matches:
        return None
    retained = matches[0]
    context = EffectCommandContext(binding['source_operation_id'], command.project_id, command.actor_id, command.trace_id, command.correlation_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT request_payload,request_hash FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s AND project_id=%s", [retained['external_effect_id'], context.operation_id, command.project_id])
        frozen = uow.cursor.fetchone()
        if not frozen or frozen[1] != retained['request_hash'] or frozen[0].get('stage') != stage or frozen[0].get('input', {}).get('context_compression_task') != task:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Reuse requires the same complete task and original immutable request')
        receipt = read_acknowledged_preparation_success_in_uow(uow, context, effect_id=retained['external_effect_id'])
        if not receipt or receipt['budget_reservation_status'] != 'SETTLED' or canonical_hash(receipt['provider_evidence']['result']) != retained['result_hash']:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Reuse requires the exact verified settled original result')
    provider = receipt['provider_evidence']
    production = provider['production_execution']
    request, result = production['execution_request'], production['execution_result']
    original_evidence = dict(execution_id=result['execution_id'], operation_id=request['operation_id'],
        attempt_id=request['attempt_id'], fencing_token=request['fencing_token'], capability=request['capability'],
        backend_id=production['execution_handle']['backend_id'], route_snapshot_id=request['route_snapshot_id'],
        input_manifest_ref=request['input_manifest_ref'], output_manifest_ref=result['output_manifest_ref'],
        validation_manifest_ref=result['validation_report_ref'], usage_receipt_ref=result['usage_receipt_ref'],
        cost_receipt_ref=result['cost_receipt_ref'], fixture_protocol_only=bool(provider.get('fixture_protocol_only')),
        real_model_call=bool(provider.get('real_model_call')), production_verified=False,
        provider_id=provider.get('provider_id', ''), model_id=provider.get('model_id', ''), external_receipt_ref=retained['external_effect_id'])
    return {**provider['result'], '_execution_evidence': {**original_evidence,
        'receipt_reuse': dict(contract_version='planning-completed-preparation-reuse.v1',
            continuation_id=command.runtime_continuation_id, consumer_operation_id=operation_id,
            task_hash=retained['task_hash'], result_hash=retained['result_hash'], provider_invoked_this_attempt=False)}}


def require_source(uow, *, source_operation_id, row, frozen):
    from novel_forge.modules.book_authority.manuscript import historical_working_inputs
    from novel_forge.modules.chapter_group_authority.replan_retirement import lock_replan_roots
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_acknowledged_preparation_success_in_uow
    from .runtime_continuation import require_binding

    rejected = KernelError("PLANNING_PREPARATION_HANDOFF_UNSAFE", "Retain acknowledged cancellation, exact current Book inputs and settled pure preparation; no main send or old submission right is permitted")
    if row[0] != 'RECONCILIATION_REQUIRED' or row[5] or frozen.get('execution_contract_version') != '1.21.0' or not frozen.get('runtime_continuation_id'):
        raise rejected
    uow.cursor.execute("SELECT to_jsonb(operation) FROM authority_operation operation WHERE operation_id=%s", [source_operation_id])
    operation = uow.cursor.fetchone()[0]
    prior = require_binding(uow.database_url, frozen['runtime_continuation_id'])
    if prior['successor_operation_id'] != source_operation_id or prior['successor_command'] != frozen:
        raise rejected
    allocation = prior['target_runtime'].get('planning_capacity', {})
    if allocation.get('context_revalidation', {}).get('contract_version') != 'same-capacity-semantic-preparation.v1':
        raise rejected
    working = frozen.get('arc_working_set', {}).get('working_manuscript', {})
    uow.cursor.execute("SELECT root_operation_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s",
        [working.get('book_run_id'), frozen['project_id'], frozen['workspace_id'], frozen['book_id']])
    owner = uow.cursor.fetchone()
    if not owner:
        raise rejected
    lock_replan_roots(uow.cursor, project_id=frozen['project_id'], book_root=owner[0])
    uow.cursor.execute("""SELECT current_chapter,accepted_through_chapter,input_snapshot_id,state,active_chapter_request_id
        FROM authority_book_production WHERE book_run_id=%s FOR UPDATE""", [working['book_run_id']])
    book = uow.cursor.fetchone()
    if (not book or book[0] + 1 != working.get('target_chapter') or book[1] != working.get('accepted_through_chapter')
            or book[3] not in {'PAUSED','READY'} or book[4] is not None):
        raise rejected
    if historical_working_inputs(uow, operation)[0] != frozen['book_id']:
        raise rejected
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status<>'CANCELLED')
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
            WHERE attempt.operation_id=%s AND lease.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND acknowledged_at IS NULL)""",
        [owner[0], source_operation_id, source_operation_id, source_operation_id])
    if uow.cursor.fetchone()[0]:
        raise rejected
    uow.cursor.execute("""SELECT cancellation.cancel_command_id,cancellation.actor_id,cancellation.reason
        FROM authority_cancellation_command cancellation
        WHERE cancellation.operation_id=%s AND cancellation.project_id=%s ORDER BY cancellation.created_at""",
        [source_operation_id, frozen['project_id']])
    cancellations = uow.cursor.fetchall()
    uow.cursor.execute("SELECT attempt_id,status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source_operation_id])
    attempt = uow.cursor.fetchone()
    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND attempt_id=%s AND status='ACKNOWLEDGED' AND acknowledged_at IS NOT NULL)", [source_operation_id, attempt[0] if attempt else ''])
    if not cancellations or any(item[1] != frozen['actor_id'] for item in cancellations) or not attempt or attempt[1] != 'CANCELLED' or not uow.cursor.fetchone()[0]:
        raise rejected
    uow.cursor.execute("""SELECT snapshot_payload,attempt_id,snapshot_id,snapshot_hash
        FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s AND attempt_id=%s""", [source_operation_id, attempt[0]])
    snapshots = uow.cursor.fetchall()
    uow.cursor.execute("""SELECT output.asset_version_id,output.content_hash FROM authority_operation_output_asset output
        WHERE output.operation_id=%s AND output.output_key='planning.context_bundle'""", [source_operation_id])
    contexts = uow.cursor.fetchall()
    if len(snapshots) != 1 or len(contexts) != 1 or snapshots[0][0].get('context_policy_ref') != 'context-policy:chapter-generation-pack:v4':
        raise rejected
    context = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=contexts[0][0])
    if context.content_hash != contexts[0][1] or context.content.get('arc_working_set') != frozen['arc_working_set']:
        raise rejected
    uow.cursor.execute("""SELECT to_jsonb(effect),reservation.status FROM authority_external_effect effect
        LEFT JOIN authority_budget_reservation reservation USING(external_effect_id)
        WHERE effect.operation_id=%s ORDER BY effect.external_effect_id FOR UPDATE OF effect""", [source_operation_id])
    effects = uow.cursor.fetchall()
    if not effects:
        raise rejected
    receipts = []
    preparation_boundary, preparation_projection = None, None
    command_context = EffectCommandContext(source_operation_id, frozen['project_id'], frozen['actor_id'], frozen['trace_id'], frozen['correlation_id'])
    for effect, budget in effects:
        payload = effect['request_payload']
        task = payload.get('input', {}).get('context_compression_task')
        if effect['effect_type'] != 'model.invoke' or effect['status'] != 'SUCCEEDED' or budget != 'SETTLED' or payload.get('stage') not in {'context_compress','context_fidelity'} or not isinstance(task, dict):
            raise rejected
        boundary = task.get('frozen_input_boundary')
        projection = task.get('task', {}).get('source_projection_hash')
        expected_boundary = dict(kind='FROZEN_STAGE_INPUTS',project_id=frozen['project_id'],book_id=frozen['book_id'],
            pack_snapshot_hash=snapshots[0][3],sources=[dict(asset_version_id=context.asset_version_id,content_hash=context.content_hash)])
        if boundary != expected_boundary or not isinstance(projection, str) or (
            preparation_projection is not None and projection != preparation_projection
        ):
            raise rejected
        preparation_boundary, preparation_projection = boundary, projection
        receipt = read_acknowledged_preparation_success_in_uow(uow, command_context, effect_id=effect['external_effect_id'])
        if not receipt or receipt['budget_reservation_status'] != 'SETTLED' or not isinstance(receipt['provider_evidence'].get('result'), dict):
            raise rejected
        receipts.append(dict(external_effect_id=effect['external_effect_id'], request_hash=effect['request_hash'],
            stage=payload['stage'], task_hash=canonical_hash(task), result_hash=canonical_hash(receipt['provider_evidence']['result'])))
    uow.cursor.execute("SELECT input_snapshot FROM authority_story_planning_generation WHERE operation_id=%s", [source_operation_id])
    inputs = uow.cursor.fetchone()[0]
    original_inputs = {item['role']: item for item in context.content['input_versions']}
    for item in inputs:
        document = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=item['asset_version_id'])
        if document.content_hash != item['content_hash'] or any(original_inputs.get(item['role'], {}).get(key) != item[key] for key in ('asset_version_id','content_hash','asset_type')):
            raise rejected
    uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s", [source_operation_id])
    depth = uow.cursor.fetchone()
    proof = dict(contract_version='planning-completed-preparation-handoff.v1', source_operation_id=source_operation_id,
        source_attempt_id=attempt[0], cancellations=[dict(cancel_command_id=item[0], actor_id=item[1], reason=item[2]) for item in cancellations],
        book_run_id=working['book_run_id'], current_chapter=book[0], accepted_through_chapter=book[1], input_snapshot_id=book[2],
        working_snapshot_hash=working['snapshot_hash'], context_asset_version_id=context.asset_version_id,
        context_content_hash=context.content_hash, retained_preparation=receipts, main_dispatch_count=0,
        preparation_source_boundary=preparation_boundary,preparation_source_projection_hash=preparation_projection,
        source_submission_rights='REVOKED_BY_ACKNOWLEDGED_CANCELLATION')
    return dict(mode='PRE_SEND_CAPACITY', source_operation_id=source_operation_id, command=frozen, version=int(row[1]),
        evidence_asset_version_id=context.asset_version_id, evidence_hash=context.content_hash, snapshot=snapshots[0][0],
        attempt_id=attempt[0], snapshot_id=snapshots[0][2], snapshot_hash=snapshots[0][3], inputs=inputs,
        failure=allocation['source_failure'], depth=int(depth[0]) + 1,
        context_revalidation={**allocation['context_revalidation'], 'context_asset_version_id':context.asset_version_id, 'context_content_hash':context.content_hash},
        completed_preparation=proof)
