from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from .domain import canonical_hash

ISOLATED_HANDOFF = 'planning-isolated-preparation-handoff.v1'
QUERY_HANDOFF = 'planning-unsent-preparation-query-handoff.v1'
LINEAGE_HANDOFF = 'planning-unsent-preparation-lineage-handoff.v1'
UNSENT_HANDOFF_CONTRACTS = frozenset({QUERY_HANDOFF, LINEAGE_HANDOFF})
CUSTODY_HANDOFF_CONTRACTS = frozenset({'planning-terminal-preparation-handoff.v1', ISOLATED_HANDOFF}) | UNSENT_HANDOFF_CONTRACTS
MULTI_OWNER_HANDOFF_CONTRACTS = frozenset({ISOLATED_HANDOFF}) | UNSENT_HANDOFF_CONTRACTS


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
        if handoff.get('contract_version') in CUSTODY_HANDOFF_CONTRACTS:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Terminal handoff must preserve the complete original Provider input')
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
    context = EffectCommandContext(retained.get('operation_id', binding['source_operation_id']), command.project_id, command.actor_id, command.trace_id, command.correlation_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT request_payload,request_hash FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s AND project_id=%s", [retained['external_effect_id'], context.operation_id, command.project_id])
        frozen = uow.cursor.fetchone()
        if not frozen or frozen[1] != retained['request_hash'] or frozen[0].get('stage') != stage or frozen[0].get('input', {}).get('context_compression_task') != task:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Reuse requires the same complete task and original immutable request')
        if handoff.get('contract_version') in MULTI_OWNER_HANDOFF_CONTRACTS and retained['receipt_contract'] == 'ISOLATED_GENERATION_SIBLING':
            from novel_forge.modules.command_kernel.external_effect_runtime import read_retained_generation_stage_success_in_uow
            receipt = read_retained_generation_stage_success_in_uow(uow, context, effect_id=retained['external_effect_id'])
        elif handoff.get('contract_version') == 'planning-terminal-preparation-handoff.v1' or (handoff.get('contract_version') in MULTI_OWNER_HANDOFF_CONTRACTS and retained['receipt_contract'] == 'TERMINAL_PREPARATION'):
            from novel_forge.modules.command_kernel.external_effect_runtime import read_terminal_preparation_success_in_uow
            receipt = read_terminal_preparation_success_in_uow(uow, context, effect_id=retained['external_effect_id'])
        else:
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


def require_source(uow, *, source_operation_id, row, frozen, terminal=False):
    from novel_forge.modules.book_authority.manuscript import historical_working_inputs
    from novel_forge.modules.chapter_group_authority.replan_retirement import lock_replan_roots
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_acknowledged_preparation_success_in_uow
    from .runtime_continuation import require_binding

    rejected = KernelError("PLANNING_PREPARATION_HANDOFF_UNSAFE", "Retain acknowledged cancellation, exact current Book inputs and settled pure preparation; no main send or old submission right is permitted")
    if row[0] != ('FAILED_FINAL' if terminal else 'RECONCILIATION_REQUIRED') or row[5] or frozen.get('execution_contract_version') != '1.21.0' or not frozen.get('runtime_continuation_id'):
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
    if uow.cursor.fetchone()[0] and not terminal:
        raise rejected
    uow.cursor.execute("""SELECT cancellation.cancel_command_id,cancellation.actor_id,cancellation.reason
        FROM authority_cancellation_command cancellation
        WHERE cancellation.operation_id=%s AND cancellation.project_id=%s ORDER BY cancellation.created_at""",
        [source_operation_id, frozen['project_id']])
    cancellations = uow.cursor.fetchall()
    uow.cursor.execute("SELECT attempt_id,status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source_operation_id])
    attempt = uow.cursor.fetchone()
    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND attempt_id=%s AND status='ACKNOWLEDGED' AND acknowledged_at IS NOT NULL)", [source_operation_id, attempt[0] if attempt else ''])
    acknowledged = uow.cursor.fetchone()[0]
    if terminal:
        if cancellations or not attempt or attempt[1] != 'FAILED_FINAL':
            raise rejected
        uow.cursor.execute("""SELECT result FROM authority_attempt WHERE attempt_id=%s AND operation_id=%s
            AND NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status<>'FAILED_FINAL')
            AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND lease.status='HELD')
            AND NOT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s)
            AND NOT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)""",
            [attempt[0], source_operation_id, source_operation_id, source_operation_id, source_operation_id, owner[0]])
        failed = uow.cursor.fetchone()
        if not failed or not is_terminal_chunk_failure(failed[0]):
            raise rejected
    elif not cancellations or any(item[1] != frozen['actor_id'] for item in cancellations) or not attempt or attempt[1] != 'CANCELLED' or not acknowledged:
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
    first_task = None
    preparation_boundary, preparation_projection = None, None
    if terminal:
        from novel_forge.modules.command_kernel.external_effect_runtime import read_terminal_preparation_success_in_uow
        read_preparation = read_terminal_preparation_success_in_uow
    else:
        read_preparation = read_acknowledged_preparation_success_in_uow
    command_context = EffectCommandContext(source_operation_id, frozen['project_id'], frozen['actor_id'], frozen['trace_id'], frozen['correlation_id'])
    for effect, budget in effects:
        payload = effect['request_payload']
        task = payload.get('input', {}).get('context_compression_task')
        if effect['effect_type'] != 'model.invoke' or effect['status'] != 'SUCCEEDED' or budget != 'SETTLED' or payload.get('stage') not in {'context_compress','context_fidelity'} or not isinstance(task, dict):
            raise rejected
        if first_task is None:
            first_task = task
        boundary = task.get('frozen_input_boundary')
        projection = task.get('task', {}).get('source_projection_hash')
        expected_boundary = dict(kind='FROZEN_STAGE_INPUTS',project_id=frozen['project_id'],book_id=frozen['book_id'],
            pack_snapshot_hash=snapshots[0][3],sources=[dict(asset_version_id=context.asset_version_id,content_hash=context.content_hash)])
        if boundary != expected_boundary or not isinstance(projection, str) or (
            preparation_projection is not None and projection != preparation_projection
        ):
            raise rejected
        preparation_boundary, preparation_projection = boundary, projection
        receipt = read_preparation(uow, command_context, effect_id=effect['external_effect_id'])
        if not receipt or receipt['budget_reservation_status'] != 'SETTLED' or not isinstance(receipt['provider_evidence'].get('result'), dict):
            raise rejected
        receipts.append(dict(external_effect_id=effect['external_effect_id'], request_hash=effect['request_hash'],
            stage=payload['stage'], task_hash=canonical_hash(task), result_hash=canonical_hash(receipt['provider_evidence']['result'])))
    if terminal and canonical_hash(reconstruct_preparation_capture(context.content, first_task)) != preparation_projection:
        raise rejected
    uow.cursor.execute("SELECT input_snapshot FROM authority_story_planning_generation WHERE operation_id=%s", [source_operation_id])
    inputs = uow.cursor.fetchone()[0]
    original_inputs = {item['role']: item for item in context.content['input_versions']}
    for item in inputs:
        document = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=item['asset_version_id'])
        if document.content_hash != item['content_hash'] or any(original_inputs.get(item['role'], {}).get(key) != item[key] for key in ('asset_version_id','content_hash','asset_type')):
            raise rejected
    uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s", [source_operation_id])
    depth = uow.cursor.fetchone()
    proof = dict(contract_version='planning-terminal-preparation-handoff.v1' if terminal else 'planning-completed-preparation-handoff.v1', source_operation_id=source_operation_id,
        source_attempt_id=attempt[0], cancellations=[dict(cancel_command_id=item[0], actor_id=item[1], reason=item[2]) for item in cancellations],
        book_run_id=working['book_run_id'], current_chapter=book[0], accepted_through_chapter=book[1], input_snapshot_id=book[2],
        working_snapshot_hash=working['snapshot_hash'], context_asset_version_id=context.asset_version_id,
        context_content_hash=context.content_hash, retained_preparation=receipts, main_dispatch_count=0,
        preparation_source_boundary=preparation_boundary,preparation_source_projection_hash=preparation_projection,
        source_submission_rights='RELEASED_BY_TERMINAL_FAILURE' if terminal else 'REVOKED_BY_ACKNOWLEDGED_CANCELLATION',
        **({'host_failure': failed[0], 'host_failure_hash': canonical_hash(failed[0])} if terminal else {}))
    return dict(mode='PRE_SEND_CAPACITY', source_operation_id=source_operation_id, command=frozen, version=int(row[1]),
        evidence_asset_version_id=context.asset_version_id, evidence_hash=context.content_hash, snapshot=snapshots[0][0],
        attempt_id=attempt[0], snapshot_id=snapshots[0][2], snapshot_hash=snapshots[0][3], inputs=inputs,
        failure=allocation['source_failure'], depth=int(depth[0]) + 1,
        context_revalidation={**allocation['context_revalidation'], 'context_asset_version_id':context.asset_version_id, 'context_content_hash':context.content_hash},
        completed_preparation=proof)


def is_terminal_chunk_failure(failure):
    return isinstance(failure, dict) and failure.get('error_code') == 'CONTEXT_COMPRESSION_TASK_INVALID' and failure.get('error_message') == 'CONTEXT_COMPRESSION_TASK_INVALID: compression needs a bounded source chunk and frozen task boundary' and failure.get('failure_class') == 'final_failure'


def terminal_custody(database_url, command, operation_id):
    from .runtime_continuation import require_binding
    if not command.runtime_continuation_id:
        return None
    binding = require_binding(database_url, command.runtime_continuation_id)
    proof = binding['target_runtime'].get('preparation_handoff', {})
    if proof.get('contract_version') not in CUSTODY_HANDOFF_CONTRACTS:
        return None
    if (binding['successor_operation_id'], binding['project_id'], binding['workspace_id'], binding['book_id'], binding['source_command']['actor_id']) != (operation_id, command.project_id, command.workspace_id, command.book_id, command.actor_id):
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Only the registered consumer may retain original preparation custody')
    return proof


def reconstruct_preparation_capture(context, task):
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.provider_views import compile_working_history_transport, project_planning_narrative_intent
    from novel_forge.modules.context_builder.request_capacity import expand_semantic_history

    provider = context['context_manifest']['provider_context_view']
    view = provider['compiled_view']
    if canonical_hash(view) != provider['content_hash']:
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Original compiled Context must retain its exact hash')
    original = deepcopy(task['task']['task_context'])
    history = context['arc_working_set']['working_manuscript']
    transported, _ = compile_working_history_transport({'working_manuscript': history})
    history = transported['working_manuscript']
    def restore(value):
        if isinstance(value, dict):
            if value.get('delivery') == 'ORIGINAL_SOURCE_UNITS_PER_CHUNK':
                if value != dict(source_projection_hash=canonical_hash(history), delivery='ORIGINAL_SOURCE_UNITS_PER_CHUNK'):
                    raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Every original history placeholder must bind the frozen working manuscript')
                return deepcopy(history)
            return {key: restore(child) for key, child in value.items()}
        if isinstance(value, list):
            return [restore(child) for child in value]
        return value
    _, view, _ = project_planning_narrative_intent({}, deepcopy(view))
    capture, _ = compile_working_history_transport(dict(input_manifest=restore(original), context_bundle=view))
    capture = expand_semantic_history(capture)
    if canonical_hash(capture) != task['task']['source_projection_hash']:
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Reconstructed complete original Provider view differs from its retained hash')
    return capture


def retained_world_action(preparer, *, command, operation_id, proof):
    from novel_forge.modules.canon_graph.background import public_world_direction
    capture = retained_capture(preparer.database_url, command=command, operation_id=operation_id, proof=proof)
    direction = capture['input_manifest']['narrative_inputs']['world_preparation']
    action = preparer.query.require(project_id=command.project_id, asset_version_id=direction['action_asset_version_id'])
    if action.content_hash != direction['action_content_hash'] or public_world_direction(dict(asset_version_id=action.asset_version_id,
            content_hash=action.content_hash, action=action.content['contract'])) != direction:
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Retained World action must match its exact original public projection')
    return action


def retained_capture(database_url, *, command, operation_id, proof):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    with AuthorityUnitOfWork(database_url) as uow:
        context = uow.repositories.asset_documents.require(project_id=command.project_id, asset_version_id=proof['context_asset_version_id'])
        if context.content_hash != proof['context_content_hash']:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Original Context hash changed')
        retained = proof['retained_preparation'][0]
        uow.cursor.execute('SELECT request_payload,request_hash FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s AND project_id=%s',
            [retained['external_effect_id'], proof['source_operation_id'], command.project_id])
        row = uow.cursor.fetchone()
        if not row or row[1] != retained['request_hash']:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Original preparation request hash changed')
        task = row[0]['input']['context_compression_task']
        if canonical_hash(task) != retained['task_hash']:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Original preparation task hash changed')
        return reconstruct_preparation_capture(context.content, task)


def consumer_realization_catalog(database_url, *, command, operation_id, context):
    from copy import deepcopy
    proof = terminal_custody(database_url, command, operation_id)
    catalog = context.get('realization_reference_contract') or {}
    if not proof:
        return catalog
    if canonical_hash(context) != proof['context_content_hash']:
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Consumer realization projection requires the exact original Context')
    projected = deepcopy(catalog)
    for references in projected['references_by_domain'].values():
        for reference in references:
            if reference['frozen_by_operation_id'] != proof['source_operation_id']:
                raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Realization source owner must match its registered custodian')
            reference['frozen_by_operation_id'] = operation_id
    return projected





def _require_unsent_carrier(uow, *, member, operation_id, frozen, rejected):
    from .runtime_continuation import require_source

    handoff = member['target'].get('preparation_handoff', {})
    if handoff.get('contract_version') not in UNSENT_HANDOFF_CONTRACTS:
        return False
    failure_key = 'unsent_lineage_failure' if handoff['contract_version'] == LINEAGE_HANDOFF else 'unsent_query_failure'
    if handoff.get(failure_key, {}).get('source_operation_id') != operation_id:
        raise rejected
    uow.cursor.execute("""SELECT version.content,version.content_hash FROM authority_story_planning_runtime_continuation link
        JOIN authority_operation control ON control.operation_id=link.registered_by_operation_id
        JOIN authority_operation_output_asset output ON output.operation_id=control.operation_id AND output.role='primary'
        JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id AND version.content_hash=output.content_hash
        JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE link.continuation_id=%s AND link.source_operation_id=%s AND link.project_id=%s AND link.book_id=%s
          AND control.status='SUCCEEDED' AND control.definition_name='story_planning.runtime_continuation.register'
          AND control.definition_version IN ('8.0.0','9.0.0') AND control.actor_id=%s
          AND (version.content#>>'{target_runtime,preparation_handoff,contract_version}'='planning-unsent-preparation-query-handoff.v1'
            OR control.definition_version='9.0.0' AND version.content#>>'{target_runtime,preparation_handoff,contract_version}'='planning-unsent-preparation-lineage-handoff.v1')
          AND asset.project_id=link.project_id AND asset.asset_type='planning_runtime_continuation'""",
        [member['continuation_id'],operation_id,frozen['project_id'],frozen['book_id'],frozen['actor_id']])
    rows = uow.cursor.fetchall()
    if len(rows) != 1 or canonical_hash(rows[0][0]) != rows[0][1]:
        raise rejected
    receipt = rows[0][0]
    if receipt.get('successor_command') != member['command'] or receipt.get('target_runtime') != member['target'] or receipt.get('source_operation_id') != operation_id:
        raise rejected
    source = require_source(uow, source_operation_id=operation_id, project_id=frozen['project_id'])
    if source.get('completed_preparation') != handoff:
        raise rejected
    return True


def isolated_preparation_source(uow, *, source_operation_id, frozen):
    from copy import deepcopy
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_terminal_preparation_success_in_uow, read_retained_generation_stage_success_in_uow
    from novel_forge.modules.book_authority.manuscript import historical_working_inputs
    from novel_forge.modules.chapter_group_authority.replan_retirement import lock_replan_roots
    from novel_forge.modules.worldbuilding.actor_isolation import ACTOR_STAGES

    if not frozen.get('runtime_continuation_id'):
        return None
    rejected = KernelError('PLANNING_PREPARATION_HANDOFF_UNSAFE', 'Isolated preparation requires exact stopped ancestry, current Book inputs, verified settled siblings and revoked old submission rights')
    semantic = {k: v for k, v in frozen.items() if k not in {'runtime_continuation_id', 'idempotency_key'}}
    current, chain, anchor = source_operation_id, [], None
    seen = set()
    while current not in seen:
        seen.add(current)
        uow.cursor.execute('''SELECT link.continuation_id,link.source_operation_id,link.source_command,link.successor_command,link.target_runtime,
            operation.status,operation.actor_id,operation.workspace_id,generation.book_id,generation.candidate_asset_version_id,
            operation.command_payload->'payload',to_jsonb(operation)
            FROM authority_story_planning_runtime_continuation link
            JOIN authority_operation operation ON operation.operation_id=link.successor_operation_id
            JOIN authority_story_planning_generation generation ON generation.operation_id=operation.operation_id
            WHERE link.successor_operation_id=%s AND link.project_id=%s FOR UPDATE OF operation''', [current, frozen['project_id']])
        row = uow.cursor.fetchone()
        if not row:
            break
        if any({k: v for k, v in command.items() if k not in {'runtime_continuation_id', 'idempotency_key'}} != semantic for command in (row[2], row[3])) or row[3] != row[10]:
            raise rejected
        if row[5] != 'FAILED_FINAL' or (row[6], row[7], row[8]) != (frozen['actor_id'], frozen['workspace_id'], frozen['book_id']) or row[9]:
            raise rejected
        allocation = row[4].get('planning_capacity', {})
        context = allocation.get('context_revalidation', {})
        if context.get('contract_version') != 'same-capacity-semantic-preparation.v1':
            if chain:
                raise rejected
            return None
        chain.append(dict(operation_id=current, source_operation_id=row[1], command=row[3], continuation_id=row[0], target=row[4], operation=row[11]))
        handoff = row[4].get('preparation_handoff', {})
        if handoff.get('contract_version') == 'planning-terminal-preparation-handoff.v1':
            anchor = deepcopy(handoff)
            break
        current = row[1]
    if anchor is None:
        return None
    context_boundary = anchor['preparation_source_boundary']
    context_identity = (anchor['context_asset_version_id'], anchor['context_content_hash'])
    for member in chain:
        allocation = member['target']['planning_capacity']
        revalidation = allocation['context_revalidation']
        if (revalidation.get('context_asset_version_id'), revalidation.get('context_content_hash')) != context_identity or revalidation != chain[0]['target']['planning_capacity']['context_revalidation']:
            raise rejected
    working = frozen['arc_working_set']['working_manuscript']
    uow.cursor.execute('SELECT root_operation_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s',
        [working['book_run_id'], frozen['project_id'], frozen['workspace_id'], frozen['book_id']])
    owner = uow.cursor.fetchone()
    if not owner:
        raise rejected
    lock_replan_roots(uow.cursor, project_id=frozen['project_id'], book_root=owner[0])
    uow.cursor.execute('''SELECT current_chapter,accepted_through_chapter,input_snapshot_id,state,active_chapter_request_id
        FROM authority_book_production WHERE book_run_id=%s FOR UPDATE''', [working['book_run_id']])
    book = uow.cursor.fetchone()
    if not book or book[:3] != (anchor['current_chapter'], anchor['accepted_through_chapter'], anchor['input_snapshot_id']) or book[3] not in {'READY', 'PAUSED'} or book[4] is not None or historical_working_inputs(uow, chain[0]['operation'])[0] != frozen['book_id']:
        raise rejected
    receipts = [{**item, 'operation_id': anchor['source_operation_id'], 'receipt_contract': 'TERMINAL_PREPARATION'} for item in anchor['retained_preparation']]
    operations = [anchor['source_operation_id']] + [member['operation_id'] for member in reversed(chain)]
    for operation_id in operations:
        carrier = next((member for member in chain if member['source_operation_id'] == operation_id and member['target'].get('preparation_handoff', {}).get('contract_version') in UNSENT_HANDOFF_CONTRACTS), None)
        if carrier is not None and _require_unsent_carrier(uow, member=carrier, operation_id=operation_id, frozen=frozen, rejected=rejected):
            continue
        if operation_id != anchor['source_operation_id']:
            uow.cursor.execute("SELECT proof FROM authority_generation_isolation WHERE operation_id=%s", [operation_id])
            isolation = uow.cursor.fetchone()
            if not isolation or any(isolation[0].get(key) != expected for key, expected in (
                ('contract_version', 'pure-generation-isolation.v1'), ('business_commit_right', 'REVOKED'), ('activation_right', 'REVOKED'))):
                raise rejected
        uow.cursor.execute('''SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) WHERE attempt.operation_id=%s AND lease.status='HELD')
            OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status<>%s)
            OR EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id IN (%s,%s))
            OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s)''', [operation_id, operation_id, 'FAILED_FINAL' if operation_id == anchor['source_operation_id'] else 'CANCELLED', operation_id, owner[0], operation_id])
        if uow.cursor.fetchone()[0]:
            raise rejected
        uow.cursor.execute('''SELECT to_jsonb(effect),reservation.status,authority_generation_isolated(effect.external_effect_id)
            FROM authority_external_effect effect LEFT JOIN authority_budget_reservation reservation USING(external_effect_id)
            WHERE effect.operation_id=%s ORDER BY effect.external_effect_id FOR UPDATE OF effect''', [operation_id])
        rows = uow.cursor.fetchall()
        if any(effect['request_payload'].get('stage') in {'chapter_plan.generate', 'chapter_group_plan.generate'} for effect, _, _ in rows):
            return None
        context = EffectCommandContext(operation_id, frozen['project_id'], frozen['actor_id'], frozen['trace_id'], frozen['correlation_id'])
        for effect, budget, isolated in rows:
            payload = effect['request_payload']
            stage = payload.get('stage', '')
            if effect['effect_type'] != 'model.invoke' or stage not in {'context_compress', 'context_fidelity', 'world_candidates.generate', 'world_candidates.evaluate', *ACTOR_STAGES}:
                raise rejected
            if isolated:
                if effect['status'] not in {'UNKNOWN', 'RECONCILIATION_REQUIRED', 'FAILED_RETRYABLE'}:
                    raise rejected
                continue
            if effect['status'] != 'SUCCEEDED' or budget != 'SETTLED':
                raise rejected
            if stage not in {'context_compress', 'context_fidelity'}:
                continue
            task = payload.get('input', {}).get('context_compression_task', {})
            if task.get('frozen_input_boundary') != context_boundary or task.get('task', {}).get('source_projection_hash') != anchor['preparation_source_projection_hash']:
                raise rejected
            read = read_terminal_preparation_success_in_uow if operation_id == anchor['source_operation_id'] else read_retained_generation_stage_success_in_uow
            receipt = read(uow, context, effect_id=effect['external_effect_id'])
            if not receipt or receipt['budget_reservation_status'] != 'SETTLED':
                raise rejected
            item = dict(external_effect_id=effect['external_effect_id'], operation_id=operation_id, stage=stage,
                request_hash=effect['request_hash'], task_hash=canonical_hash(task), result_hash=canonical_hash(receipt['provider_evidence']['result']),
                receipt_contract='TERMINAL_PREPARATION' if operation_id == anchor['source_operation_id'] else 'ISOLATED_GENERATION_SIBLING')
            previous = next((old for old in receipts if old['external_effect_id'] == item['external_effect_id']), None)
            if previous is not None and previous != item:
                raise rejected
            if previous is None:
                receipts.append(item)
    return {**anchor, 'contract_version': ISOLATED_HANDOFF, 'retained_preparation': receipts,
        'isolation_source_operation_id': source_operation_id, 'source_submission_rights': 'REVOKED_BY_GENERATION_ISOLATION',
        'inherited_continuation_ids': [member['continuation_id'] for member in chain], 'original_handoff_hash': canonical_hash(anchor)}




def unsent_query_source(uow, *, source_operation_id, row, frozen, attempt):
    from .runtime_continuation import require_binding
    from novel_forge.modules.book_authority.manuscript import historical_working_inputs
    from novel_forge.modules.chapter_group_authority.replan_retirement import lock_replan_roots

    if not frozen.get('runtime_continuation_id'):
        return None
    binding = require_binding(uow.database_url, frozen['runtime_continuation_id'])
    inherited = binding['target_runtime'].get('preparation_handoff', {})
    if inherited.get('contract_version') not in MULTI_OWNER_HANDOFF_CONTRACTS:
        return None
    rejected = KernelError('PLANNING_PREPARATION_QUERY_HANDOFF_UNSAFE', 'Retain exact registered preparation custody and Context, terminal query failure, zero budgets or Effects and released submission rights')
    lineage_failure = attempt[2] == dict(error_code='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED',
        error_message='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth', failure_class='retryable', failure_details={})
    terminal_status = 'FAILED_RETRYABLE' if lineage_failure else 'FAILED_FINAL'
    contract = LINEAGE_HANDOFF if lineage_failure else QUERY_HANDOFF
    failure_key = 'unsent_lineage_failure' if lineage_failure else 'unsent_query_failure'
    if (row[0] not in ({'FAILED_RETRYABLE', 'FAILED_FINAL'} if lineage_failure else {'FAILED_FINAL'}) or attempt[0] != terminal_status
            or not lineage_failure and attempt[2] != dict(error_code='PROGRAMMING_BUG', error_message='canceling statement due to statement timeout', failure_class='programming_bug', failure_details={})
            or binding['successor_operation_id'] != source_operation_id or binding['successor_command'] != frozen):
        raise rejected
    uow.cursor.execute('''SELECT to_jsonb(operation),EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status<>%s)
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id) WHERE attempt.operation_id=%s AND lease.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s)
        FROM authority_operation operation WHERE operation_id=%s''', [source_operation_id] * 3 + [terminal_status] + [source_operation_id] * 4)
    operation, unsafe = uow.cursor.fetchone()
    if unsafe or (operation['actor_id'], operation['workspace_id']) != (frozen['actor_id'], frozen['workspace_id']):
        raise rejected
    uow.cursor.execute('SELECT asset_version_id,content_hash,output_key,role FROM authority_operation_output_asset WHERE operation_id=%s', [source_operation_id])
    source_outputs = uow.cursor.fetchall()
    source_contexts = [item for item in source_outputs if item[2] == 'planning.context_bundle']
    local_preparation = [item for item in source_outputs if item[2] != 'planning.context_bundle']
    if len(source_contexts) > 1 or any(item[1] != inherited['context_content_hash'] or item[2] != 'planning.context_bundle' or item[3] != 'context_bundle' for item in source_contexts):
        raise rejected
    working = frozen['arc_working_set']['working_manuscript']
    uow.cursor.execute('SELECT root_operation_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s',
        [working['book_run_id'], frozen['project_id'], frozen['workspace_id'], frozen['book_id']])
    owner = uow.cursor.fetchone()
    if not owner:
        raise rejected
    lock_replan_roots(uow.cursor, project_id=frozen['project_id'], book_root=owner[0])
    uow.cursor.execute('''SELECT current_chapter,accepted_through_chapter,input_snapshot_id,state,active_chapter_request_id,
        EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id)
        FROM authority_book_production book WHERE book_run_id=%s FOR UPDATE''', [working['book_run_id']])
    book = uow.cursor.fetchone()
    if (not book or book[:3] != (inherited['current_chapter'], inherited['accepted_through_chapter'], inherited['input_snapshot_id'])
            or book[3] not in {'READY', 'PAUSED'} or book[4] is not None or book[5]
            or historical_working_inputs(uow, operation)[0] != frozen['book_id']):
        raise rejected
    uow.cursor.execute('''SELECT snapshot_payload,snapshot_id,snapshot_hash,attempt_id FROM authority_attempt_capability_pack_snapshot
        WHERE operation_id=%s AND attempt_id=(SELECT attempt_id FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1)''', [source_operation_id] * 2)
    snapshots = uow.cursor.fetchall()
    if len(snapshots) != 1 or snapshots[0][0]['context_policy_ref'] != 'context-policy:chapter-generation-pack:v4':
        raise rejected
    retained_local = []
    for output in local_preparation:
        document = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=output[0])
        materialization = document.content.get('contract', {})
        identity = materialization.get('attempt_snapshot', {})
        if (output[3] != 'execution_contract' or not output[2].startswith('production_execution.contract.capability_materialization_manifest.')
                or document.asset_type != 'capability_materialization_manifest' or document.content_hash != output[1]
                or canonical_hash(document.content) != output[1] or materialization.get('schema_version') != 'novelos.planning_capability_materialization.v1'
                or materialization.get('stage') not in {'context_compress', 'context_fidelity'}
                or materialization.get('materialization_hash') != canonical_hash({key:value for key,value in materialization.items() if key != 'materialization_hash'})
                or any(identity.get(key) != value for key,value in dict(operation_id=source_operation_id,attempt_id=snapshots[0][3],snapshot_id=snapshots[0][1],snapshot_hash=snapshots[0][2]).items())
                or materialization.get('pack_identity') != {key:snapshots[0][0][key] for key in ('pack_id','pack_version','manifest_hash','compilation_hash','catalog_snapshot_hash','binding_set_id','binding_set_hash')}):
            raise rejected
        retained_local.append(dict(asset_version_id=output[0],content_hash=output[1],output_key=output[2],role=output[3],asset_type=document.asset_type,stage=materialization['stage']))
    uow.cursor.execute('SELECT input_snapshot FROM authority_story_planning_generation WHERE operation_id=%s', [source_operation_id])
    inputs = uow.cursor.fetchone()[0]
    context = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=inherited['context_asset_version_id'])
    if context.content_hash != inherited['context_content_hash'] or context.content['arc_working_set'] != frozen['arc_working_set']:
        raise rejected
    for retained_context in source_contexts:
        saved = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=retained_context[0])
        if saved.asset_type != 'context_bundle' or saved.content_hash != context.content_hash or canonical_hash(saved.content) != context.content_hash:
            raise rejected
    original = {item['role']: item for item in context.content['input_versions']}
    for item in inputs:
        document = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=item['asset_version_id'])
        if document.content_hash != item['content_hash'] or document.asset_type != item['asset_type'] or any(original.get(item['role'], {}).get(key) != item[key] for key in ('asset_version_id','content_hash','asset_type')):
            raise rejected
    uow.cursor.execute('SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s', [source_operation_id])
    depth = int(uow.cursor.fetchone()[0]) + 1
    from copy import deepcopy
    proof = {**deepcopy(inherited), 'contract_version': contract,
        failure_key: dict(source_operation_id=source_operation_id, source_attempt_id=snapshots[0][3],
            original_failure=attempt[2], original_failure_hash=canonical_hash(attempt[2]),
            source_context=dict(asset_version_id=source_contexts[0][0], content_hash=source_contexts[0][1]) if source_contexts else None,
            inherited_preparation_hash=canonical_hash(inherited), inherited_preparation=inherited),
        'source_submission_rights': 'RELEASED_BY_UNSENT_LINEAGE_FAILURE' if lineage_failure else 'RELEASED_BY_UNSENT_QUERY_FAILURE'}
    proof.pop('retained_local_preparation', None)
    if retained_local:
        proof['retained_local_preparation'] = retained_local
    allocation = binding['target_runtime']['planning_capacity']
    return dict(mode='PRE_SEND_CAPACITY', source_operation_id=source_operation_id, command=frozen, version=int(row[1]),
        evidence_asset_version_id=context.asset_version_id, evidence_hash=context.content_hash,
        snapshot=snapshots[0][0], snapshot_id=snapshots[0][1], snapshot_hash=snapshots[0][2], attempt_id=snapshots[0][3],
        inputs=inputs, failure=allocation['source_failure'], depth=depth, source_operation_status=row[0],
        context_revalidation=allocation['context_revalidation'], completed_preparation=proof)
