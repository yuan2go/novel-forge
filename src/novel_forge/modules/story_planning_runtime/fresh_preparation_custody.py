from __future__ import annotations

from copy import deepcopy
import json

from novel_forge.modules.command_kernel.errors import KernelError
from .domain import canonical_hash

LEGACY_CONTRACT = 'planning-first-isolated-preparation-handoff.v1'
CONTRACT = 'planning-first-isolated-preparation-handoff.v2'
CAPACITY_CONTRACT = 'planning-first-isolated-preparation-handoff.v3'
ACKNOWLEDGED_CONTRACT = 'planning-acknowledged-preparation-handoff.v1'
ACCOUNT_VERSION_CONTRACT = 'planning-acknowledged-preparation-handoff.v2'
SUPPORTED_CONTRACTS = frozenset({LEGACY_CONTRACT, CONTRACT, CAPACITY_CONTRACT, ACKNOWLEDGED_CONTRACT, ACCOUNT_VERSION_CONTRACT})
CONTEXT_CONTRACT = 'same-capacity-isolated-preparation.v1'
LINEAGE_LINK_FAILURE = dict(error_code='PLANNING_ROUTING_LINEAGE_INVALID',
    error_message='PLANNING_ROUTING_LINEAGE_INVALID: Runtime successor lacks its exact native continuation',
    failure_class='final_failure', failure_details={})
PAUSED_INTENT = dict(message='RUNTIME_DISPATCH_PAUSED: Planning preparation waits at the native Book pause checkpoint',
    error_code='RUNTIME_DISPATCH_PAUSED', error_type='KernelError', request_sent=False,
    failure_phase='pre_send_assertion', dispatch_pause_contract='runtime-dispatch-control.v1', authorization_denial_permanent=False)


def _semantic(command):
    return {key: value for key, value in command.items() if key not in {'runtime_continuation_id', 'idempotency_key'}}


def settled_capacity_projection(failure):
    if not isinstance(failure, dict) or (failure.get('error_code'), failure.get('error_message'), failure.get('failure_class')) != (
            'TASK_CONTEXT_COMPRESSION_NO_PROGRESS',
            'TASK_CONTEXT_COMPRESSION_NO_PROGRESS: All remaining source expression is required or already verified; the complete request still exceeds capacity', 'retryable'):
        return None
    projection = (failure.get('failure_details') or {}).get('projection') or {}
    measurement = projection.get('measurement') or {}
    receipt = projection.get('compression_receipt') or {}
    if (projection.get('contract_version') != 'complete-request-capacity.v1'
            or projection.get('semantic_contract') != 'source-unit-dependency-and-final-composition.v2'
            or not projection.get('original_hash') or projection.get('original_hash') != projection.get('result_hash')
            or receipt.get('fast_path') is not True
            or any(type(measurement.get(key)) is not int for key in ('before_reserved', 'after_reserved', 'limit'))
            or not 0 < measurement['limit'] < min(measurement['before_reserved'], measurement['after_reserved'])
            or measurement.get('actual_provider_tokens') is not None):
        return None
    return projection


def require_source(uow, *, source_operation_id, frozen):
    from novel_forge.modules.book_authority.manuscript import historical_working_inputs
    from novel_forge.modules.chapter_group_authority.replan_retirement import lock_replan_roots
    from novel_forge.modules.command_kernel.external_effect_runtime import (EffectCommandContext,
        read_acknowledged_preparation_success_in_uow, read_retained_generation_stage_success_in_uow)
    from novel_forge.modules.worldbuilding.actor_isolation import ACTOR_STAGES
    from .preparation_recovery import reconstruct_preparation_capture

    if frozen.get('execution_contract_version') != '1.21.0' or not frozen.get('arc_working_set', {}).get('working_manuscript'):
        return None
    rejected = KernelError('PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE',
        'First isolation custody requires stopped exact ancestry, revoked rights, current Book inputs and verified settled preparation; UNKNOWN is never a result')
    members, seen, current = [], set(), source_operation_id
    while current not in seen:
        seen.add(current)
        uow.cursor.execute('''SELECT to_jsonb(op),to_jsonb(generation),isolation.proof
            FROM authority_operation op JOIN authority_story_planning_generation generation USING(operation_id)
            LEFT JOIN authority_generation_isolation isolation USING(operation_id)
            WHERE op.operation_id=%s AND op.project_id=%s FOR UPDATE OF op''', [current, frozen['project_id']])
        row = uow.cursor.fetchone()
        if not row:
            if members:
                raise rejected
            return None
        operation, generation, isolation = row
        command = operation['command_payload']['payload']
        uow.cursor.execute('SELECT to_jsonb(link) FROM authority_story_planning_runtime_continuation link WHERE successor_operation_id=%s', [current])
        parent_row = uow.cursor.fetchone()
        parent = parent_row[0] if parent_row else None
        if parent:
            inherited = parent['target_runtime'].get('preparation_handoff', {})
            if inherited and inherited.get('contract_version') not in SUPPORTED_CONTRACTS:
                return None
        members.append(dict(operation=operation, generation=generation, isolation=isolation, parent=parent))
        if not parent:
            if command.get('runtime_continuation_id') or (not isolation and operation['status'] != 'RECONCILIATION_REQUIRED'):
                return None
            break
        current = parent['source_operation_id']
    else:
        raise rejected
    anchor = members[-1]
    original = anchor['operation']
    if frozen.get('execution_contract_version') != '1.21.0' or original['definition_version'] != '1.21.0':
        return None
    working = frozen.get('arc_working_set', {}).get('working_manuscript', {})
    if not working:
        return None
    for member in members:
        op, gen, parent = member['operation'], member['generation'], member['parent']
        command = op['command_payload']['payload']
        if _semantic(command) != _semantic(frozen) or gen.get('candidate_asset_version_id'):
            raise rejected
        if parent and (parent['successor_command'] != command or parent['continuation_id'] != command.get('runtime_continuation_id')
                or _semantic(parent['source_command']) != _semantic(frozen)):
            raise rejected
    uow.cursor.execute('SELECT root_operation_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s',
        [working.get('book_run_id'), frozen['project_id'], frozen['workspace_id'], frozen['book_id']])
    owner = uow.cursor.fetchone()
    if not owner:
        raise rejected
    lock_replan_roots(uow.cursor, project_id=frozen['project_id'], book_root=owner[0])
    uow.cursor.execute('SELECT current_chapter,accepted_through_chapter,input_snapshot_id,state,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE', [working['book_run_id']])
    book = uow.cursor.fetchone()
    if (not book or book[0] + 1 != working.get('target_chapter') or book[1] != working.get('accepted_through_chapter')
            or book[3] not in {'READY', 'PAUSED'} or book[4] is not None
            or historical_working_inputs(uow, original)[0] != frozen['book_id']):
        raise rejected
    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)", [owner[0]])
    if uow.cursor.fetchone()[0]:
        raise rejected
    uow.cursor.execute('SELECT snapshot_payload,snapshot_id,snapshot_hash,attempt_id FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s', [original['operation_id']])
    snapshots = uow.cursor.fetchall()
    uow.cursor.execute("SELECT asset_version_id,content_hash FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='planning.context_bundle'", [original['operation_id']])
    contexts = uow.cursor.fetchall()
    if len(snapshots) != 1 or len(contexts) != 1:
        raise rejected
    snapshot, snapshot_id, snapshot_hash, attempt_id = snapshots[0]
    if snapshot.get('context_policy_ref') != 'context-policy:chapter-generation-pack:v4':
        raise rejected
    context = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=contexts[0][0])
    if context.content_hash != contexts[0][1] or context.content.get('arc_working_set') != frozen['arc_working_set']:
        raise rejected
    inputs = anchor['generation']['input_snapshot']
    context_inputs = {item['role']: item for item in context.content['input_versions']}
    for item in inputs:
        asset = uow.repositories.asset_documents.require(project_id=frozen['project_id'], asset_version_id=item['asset_version_id'])
        if asset.content_hash != item['content_hash'] or asset.asset_type != item['asset_type'] or any(
                context_inputs.get(item['role'], {}).get(key) != item[key] for key in ('asset_version_id', 'content_hash', 'asset_type')):
            raise rejected
    boundary = dict(kind='FROZEN_STAGE_INPUTS', project_id=frozen['project_id'], book_id=frozen['book_id'],
        pack_snapshot_hash=snapshot_hash, sources=[dict(asset_version_id=context.asset_version_id, content_hash=context.content_hash)])
    retained, stopped, first_task, projection, original_route = [], [], None, None, None
    capacity_failures = []
    original_entitlement = None
    for member in reversed(members):
        op, gen, isolation = member['operation'], member['generation'], member['isolation']
        identity = op['operation_id']
        if (op['actor_id'], op['workspace_id'], gen['book_id'], gen['input_snapshot']) != (frozen['actor_id'], frozen['workspace_id'], frozen['book_id'], inputs):
            raise rejected
        uow.cursor.execute('SELECT attempt_id,status,result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number', [identity])
        attempts = uow.cursor.fetchall()
        uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD') OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND acknowledged_at IS NULL)", [identity, identity])
        if not attempts or uow.cursor.fetchone()[0]:
            raise rejected
        uow.cursor.execute('SELECT actor_id FROM authority_cancellation_command WHERE operation_id=%s', [identity])
        cancellations = uow.cursor.fetchall()
        if isolation:
            if (op['status'] != 'FAILED_FINAL' or any(a[1] != 'CANCELLED' for a in attempts) or cancellations
                    or any(isolation.get(k) != v for k, v in (('contract_version', 'pure-generation-isolation.v1'),
                        ('operation_id', identity), ('project_id', frozen['project_id']), ('book_id', frozen['book_id']),
                        ('actor_id', frozen['actor_id']), ('business_commit_right', 'REVOKED'), ('activation_right', 'REVOKED')))):
                raise rejected
            receipt_kind = 'ISOLATED_GENERATION_SIBLING'
            read = read_retained_generation_stage_success_in_uow
            stop = dict(operation_id=identity, kind='ISOLATED', isolation_hash=canonical_hash(isolation))
        elif op['status'] == 'RECONCILIATION_REQUIRED':
            uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND attempt_id=%s AND status='ACKNOWLEDGED' AND acknowledged_at IS NOT NULL)", [identity, attempts[-1][0]])
            if any(a[1] != 'CANCELLED' for a in attempts) or not cancellations or any(c[0] != frozen['actor_id'] for c in cancellations) or not uow.cursor.fetchone()[0]:
                raise rejected
            receipt_kind = 'ACKNOWLEDGED_PREPARATION'
            read = read_acknowledged_preparation_success_in_uow
            stop = dict(operation_id=identity, kind='ACKNOWLEDGED_CANCELLATION')
        else:
            failure = attempts[-1][2] or {}
            capacity = settled_capacity_projection(failure)
            if capacity:
                capacity_failures.append(capacity)
            allowed_failure = (failure.get('error_code'), failure.get('error_message')) in {
                ('PLANNING_ROUTING_LINEAGE_INVALID', 'PLANNING_ROUTING_LINEAGE_INVALID: Runtime successor lacks its exact native continuation'),
                ('PROGRAMMING_BUG', 'canceling statement due to statement timeout'),
                ('PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED', 'PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth')}
            if failure.get('error_code') == LINEAGE_LINK_FAILURE['error_code'] and failure != LINEAGE_LINK_FAILURE:
                raise rejected
            if op['status'] not in {'FAILED_FINAL', 'FAILED_RETRYABLE'} or cancellations or not (allowed_failure or capacity) or any(a[1] not in {'FAILED_FINAL', 'FAILED_RETRYABLE'} for a in attempts):
                raise rejected
            receipt_kind, read = 'STOPPED_GENERATION_SIBLING', read_retained_generation_stage_success_in_uow
            stop = (dict(operation_id=identity, kind='UNSENT_CAPACITY_FAILURE', failure_hash=canonical_hash(failure),
                capacity_projection_hash=canonical_hash(capacity), measurement=deepcopy(capacity['measurement'])) if capacity
                else dict(operation_id=identity, kind='UNSENT_HOST_FAILURE', failure=deepcopy(failure)))
        uow.cursor.execute('''SELECT to_jsonb(effect),reservation.status,authority_generation_isolated(effect.external_effect_id)
            FROM authority_external_effect effect LEFT JOIN authority_budget_reservation reservation USING(external_effect_id)
            WHERE effect.operation_id=%s ORDER BY effect.external_effect_id FOR UPDATE OF effect''', [identity])
        effects = uow.cursor.fetchall()
        if stop['kind'] == 'UNSENT_HOST_FAILURE' and effects:
            raise rejected
        for effect, budget, isolated in effects:
            payload = effect['request_payload']
            stage = payload.get('stage')
            if stop['kind'] == 'UNSENT_CAPACITY_FAILURE' and stage not in {'context_compress', 'context_fidelity'}:
                raise rejected
            if effect['effect_type'] != 'model.invoke' or stage not in {'context_compress', 'context_fidelity', 'world_candidates.generate', 'world_candidates.evaluate', *ACTOR_STAGES} or canonical_hash(payload) != effect['request_hash']:
                raise rejected
            if isolated:
                if not isolation or effect['status'] not in {'UNKNOWN', 'RECONCILIATION_REQUIRED', 'FAILED_RETRYABLE'}:
                    raise rejected
                continue
            if effect['status'] == 'FAILED_RETRYABLE' and stop['kind'] == 'ACKNOWLEDGED_CANCELLATION' and stage in {'context_compress', 'context_fidelity'}:
                _require_paused_intent(uow, effect, budget, rejected)
                stop.setdefault('paused_intent_ids', []).append(effect['external_effect_id'])
                continue
            if effect['status'] != 'SUCCEEDED' or budget != 'SETTLED':
                raise rejected
            ctx = EffectCommandContext(identity, frozen['project_id'], frozen['actor_id'], frozen['trace_id'], frozen['correlation_id'])
            if stage not in {'context_compress', 'context_fidelity'}:
                continue
            task = payload.get('input', {}).get('context_compression_task', {})
            if task.get('frozen_input_boundary') != boundary:
                if identity == original['operation_id'] or member['parent']['target_runtime'].get('preparation_handoff'):
                    raise rejected
                stop.setdefault('different_context_preparation_ids', []).append(effect['external_effect_id'])
                continue
            digest = task.get('task', {}).get('source_projection_hash')
            if not isinstance(digest, str) or projection is not None and projection != digest:
                raise rejected
            projection, first_task = digest, first_task or task
            receipt = read(uow, ctx, effect_id=effect['external_effect_id'])
            if not receipt or receipt['budget_reservation_status'] != 'SETTLED' or not isinstance(receipt['provider_evidence'].get('result'), dict):
                raise rejected
            if identity == original['operation_id'] and original_route is None:
                original_route = deepcopy(receipt['provider_evidence']['production_execution']['route_snapshot'])
                cost = receipt['provider_evidence'].get('cost') or {}
                original_entitlement = deepcopy(cost.get('entitlement_snapshot')) if cost.get('accounting_basis') == 'ACCOUNT_ENTITLEMENT' else None
            retained.append(dict(operation_id=identity, external_effect_id=effect['external_effect_id'], request_hash=effect['request_hash'],
                stage=stage, task_hash=canonical_hash(task), result_hash=canonical_hash(receipt['provider_evidence']['result']), receipt_contract=receipt_kind))
        stop['effect_ids'] = [effect['external_effect_id'] for effect, _, _ in effects]
        stopped.append(stop)
    if not retained:
        return None
    if canonical_hash(reconstruct_preparation_capture(context.content, first_task)) != projection:
        raise rejected
    from novel_forge.modules.chapter_authority.receipt_recovery import retained_capacity_bindings_in_uow
    bindings = retained_capacity_bindings_in_uow(uow, project_id=frozen['project_id'], operation_id=original['operation_id'],
        source_hash=projection, source_boundary=boundary, stage=anchor['generation']['generator_operation_name'])
    main = bindings.get(anchor['generation']['generator_operation_name'], {}).get('route', {})
    if not main:
        raise rejected
    capacity_members = [member for member in stopped if member['kind'] == 'UNSENT_CAPACITY_FAILURE']
    for capacity in capacity_failures:
        if (capacity['source_boundary'] != boundary or capacity['original_hash'] != projection
                or capacity['stage'] != anchor['generation']['generator_operation_name']
                or capacity['measurement']['limit'] != min(512_000, main.get('context_limit', 0))
                or capacity['measurement']['token_method'] != main.get('method')):
            raise rejected
    account_route = original_route
    original_route = {new: main[old] for new, old in (('model_provider', 'provider'), ('model_id', 'model'),
        ('backend_id', 'backend'), ('reasoning_effort', 'reasoning'))}
    if (account_route.get('model_provider'), account_route.get('backend_id')) == (main['provider'], main['backend']):
        original_route['auth_profile_ref'] = account_route['auth_profile_ref']
    acknowledged_anchor = anchor['isolation'] is None
    if acknowledged_anchor and any(member['kind'] != 'ACKNOWLEDGED_CANCELLATION' for member in stopped):
        raise rejected
    proof = dict(contract_version=ACKNOWLEDGED_CONTRACT if acknowledged_anchor else CAPACITY_CONTRACT if capacity_members else CONTRACT, source_operation_id=original['operation_id'], source_attempt_id=attempt_id,
        custody_source_operation_id=source_operation_id, book_run_id=working['book_run_id'], current_chapter=book[0],
        accepted_through_chapter=book[1], input_snapshot_id=book[2], working_snapshot_hash=working['snapshot_hash'],
        context_asset_version_id=context.asset_version_id, context_content_hash=context.content_hash,
        preparation_source_boundary=boundary, preparation_source_projection_hash=projection, retained_preparation=retained,
        main_dispatch_count=0, isolated_generation_count=sum(member['isolation'] is not None for member in members), source_submission_rights='REVOKED_OR_TERMINALLY_RELEASED', stopped_ancestry=stopped,
        original_pack_snapshot=snapshot, original_pack_snapshot_id=snapshot_id, original_pack_snapshot_hash=snapshot_hash)
    proof['original_route'] = original_route
    proof['original_capacity_bindings'] = bindings
    current_op = members[0]['operation']
    parent = members[0]['parent']
    return dict(mode='ACKNOWLEDGED_PREPARATION_CUSTODY' if acknowledged_anchor else 'FIRST_ISOLATED_PREPARATION_CUSTODY', source_operation_id=source_operation_id,
        command=frozen, version=int(current_op['version']), snapshot=snapshot, depth=(int(parent['chain_depth']) if parent else 0) + 1,
        evidence_asset_version_id=context.asset_version_id, evidence_hash=context.content_hash, fresh_preparation=proof,
        original_account_entitlement=original_entitlement, source_operation_status=current_op['status'], source_release_sha=current_op.get('definition_snapshot', {}).get('commit_sha', snapshot.get('release_sha')), provider=original_route['model_provider'], route_evidence_operation_id=original['operation_id'])


def _require_paused_intent(uow, effect, budget, rejected):
    if budget not in {'RESERVED', 'RELEASED'} or effect.get('last_error') != PAUSED_INTENT:
        raise rejected
    uow.cursor.execute('''SELECT dispatch_id,status,evidence FROM authority_external_effect_dispatch
        WHERE external_effect_id=%s ORDER BY generation''', [effect['external_effect_id']])
    rows = uow.cursor.fetchall()
    if len(rows) != 1 or rows[0][1:] != ('FAILED_RETRYABLE', PAUSED_INTENT):
        raise rejected
    uow.cursor.execute('''SELECT EXISTS(SELECT 1 FROM authority_external_receipt WHERE dispatch_id=%s)
        OR EXISTS(SELECT 1 FROM authority_effect_dispatch_lease WHERE dispatch_id=%s AND status='HELD')
        OR EXISTS(SELECT 1 FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.asset_type='execution_recovery_session' AND a.project_id=%s
            AND v.content#>>'{record,request,external_effect_id}'=%s)''', [rows[0][0], rows[0][0], effect['project_id'], effect['external_effect_id']])
    if uow.cursor.fetchone()[0]:
        raise rejected


def retire_paused_reservations(uow, source):
    from novel_forge.modules.command_kernel.budget_runtime import resolve_provider_budget_failure_in_uow
    for member in source['fresh_preparation']['stopped_ancestry']:
        for effect_id in member.get('paused_intent_ids', []):
            uow.cursor.execute('SELECT reservation_id FROM authority_budget_reservation WHERE external_effect_id=%s AND project_id=%s',
                [effect_id, source['command']['project_id']])
            rows = uow.cursor.fetchall()
            if len(rows) != 1:
                raise KernelError('PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE', 'Exact never-sent pause intent must own one reservation')
            result = resolve_provider_budget_failure_in_uow(uow, reservation_id=rows[0][0], project_id=source['command']['project_id'])
            if result['status'] != 'RELEASED':
                raise KernelError('PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE', 'A started or ambiguous call cannot release its reservation')


def retired_paused_intent(uow, *, project_id, book_id, book_run_id, effect_id):
    from .runtime_continuation import acknowledged_routing_link
    from novel_forge.modules.worldbuilding.actor_isolation import ACTOR_STAGES
    stages = ['context_compress', 'context_fidelity', 'world_candidates.generate', 'world_candidates.evaluate', *ACTOR_STAGES]
    uow.cursor.execute('''SELECT to_jsonb(effect),budget.status,link.continuation_id,link.successor_operation_id,
        link.target_runtime,link.source_command
        FROM authority_external_effect effect JOIN authority_operation source USING(operation_id)
        JOIN authority_budget_reservation budget USING(external_effect_id)
        JOIN authority_story_planning_runtime_continuation link ON link.source_operation_id=source.operation_id
        JOIN authority_operation child ON child.operation_id=link.successor_operation_id
        WHERE effect.external_effect_id=%s AND effect.project_id=%s AND link.project_id=effect.project_id
          AND source.project_id=link.project_id AND source.workspace_id=link.workspace_id AND link.book_id=%s
          AND source.definition_name='story_planning.generate' AND source.definition_version='1.21.0'
          AND source.actor_id=link.source_command->>'actor_id' AND effect.effect_type='model.invoke'
          AND effect.status='FAILED_RETRYABLE' AND budget.status='RELEASED'
          AND budget.project_id=effect.project_id AND budget.operation_id=source.operation_id
          AND source.command_payload->'payload'=link.source_command
          AND child.project_id=source.project_id AND child.workspace_id=source.workspace_id AND child.actor_id=source.actor_id
          AND child.definition_name='story_planning.generate'
          AND child.causation_operation_id=source.operation_id AND child.command_payload->'payload'=link.successor_command
          AND NOT EXISTS(SELECT 1 FROM authority_external_effect risk WHERE risk.operation_id=source.operation_id
              AND (risk.effect_type<>'model.invoke' OR COALESCE(risk.request_payload->>'stage','')<>ALL(%s)))''',
        [effect_id, project_id, book_id, stages])
    rows = uow.cursor.fetchall()
    if len(rows) != 1:
        return False
    effect, budget, continuation, successor, target, source = rows[0]
    proof = target.get('preparation_handoff', {})
    payload = effect['request_payload']
    if (proof.get('contract_version') not in SUPPORTED_CONTRACTS or proof.get('book_run_id') != book_run_id
            or proof.get('source_submission_rights') != 'REVOKED_OR_TERMINALLY_RELEASED' or proof.get('main_dispatch_count') != 0
            or (source.get('project_id'), source.get('book_id')) != (project_id, book_id)
            or payload.get('stage') not in {'context_compress', 'context_fidelity'}
            or payload.get('_production_execution', {}).get('book_id') != book_id
            or payload.get('_production_execution', {}).get('operation_id') != effect['operation_id']
            or canonical_hash(payload) != effect['request_hash']
            or not any(member.get('operation_id') == effect['operation_id'] and member.get('kind') == 'ACKNOWLEDGED_CANCELLATION'
                and effect_id in member.get('paused_intent_ids', []) for member in proof.get('stopped_ancestry', []))):
        return False
    link = acknowledged_routing_link(uow.cursor, continuation_id=continuation,
        successor_operation_id=successor, project_id=project_id, book_id=book_id)
    if not link or link[0] != effect['operation_id']:
        return False
    try:
        _require_paused_intent(uow, effect, budget,
            KernelError('PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE', 'Retirement requires its original exact never-sent pause evidence'))
    except KernelError:
        return False
    return True


def target_runtime(application, source, target):
    proof = source['fresh_preparation']
    original, selected = proof['original_pack_snapshot'], target['pack_snapshot']
    for field in ('pack_id', 'context_policy_ref', 'context_policy_hash', 'route_policy_hash', 'prompt_bundle_hash',
            'tool_policy_hash', 'approval_policy_hash', 'budget_policy_hash', 'execution_capability_hash', 'skill_bundle_hash'):
        if original.get(field) != selected.get(field):
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'First isolation custody cannot reinterpret the frozen Pack or route')
    route = proof['original_route']
    for target_key, original_key in (('model_provider', 'model_provider'), ('model_id', 'model_id'),
            ('model_backend_id', 'backend_id'), ('reasoning_effort', 'reasoning_effort')):
        if not route.get(original_key) or target.get(target_key) != route[original_key]:
            raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'First isolation custody retains the original model, reasoning, backend and authenticated account')
    reconciliation = _cli_version_reconciliation(source, target)
    if route.get('auth_profile_ref') and target.get('auth_profile_ref') != route['auth_profile_ref'] and reconciliation is None:
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'First isolation custody retains the frozen authenticated account')
    if reconciliation is not None:
        proof = {**proof, 'contract_version': ACCOUNT_VERSION_CONTRACT, 'account_version_reconciliation': reconciliation}
    allocated = json.loads(original['context_policy_payload_json'])['planning_task_token_budget']
    if type(allocated) is not int or not 0 < allocated <= 512_000:
        raise KernelError('PLANNING_PREPARATION_REUSE_DRIFT', 'Retain the original physical selection target')
    return {**target, 'preparation_handoff': proof, 'planning_capacity': dict(allocated_task_tokens=allocated,
        prior_task_tokens=allocated, context_revalidation=dict(contract_version=CONTEXT_CONTRACT,
            context_asset_version_id=proof['context_asset_version_id'], context_content_hash=proof['context_content_hash']))}



def _cli_version_reconciliation(source, target):
    from novel_forge.modules.production_execution.codex_configuration import reconcile_codex_cli_version_account
    if source.get('mode') != 'ACKNOWLEDGED_PREPARATION_CUSTODY':
        return None
    return reconcile_codex_cli_version_account(account=target.get('account') or {},
        original_entitlement=source.get('original_account_entitlement'),
        source_auth_profile_ref=source['fresh_preparation']['original_route'].get('auth_profile_ref'),
        target_auth_profile_ref=target.get('auth_profile_ref'))


def _first_route_authorization(source, target):
    from novel_forge.modules.production_execution.codex_configuration import codex_local_binding_hash
    proof = source['fresh_preparation']
    route, account = proof['original_route'], target.get('account') or {}
    ancestry = proof.get('stopped_ancestry', [])
    reference = route.get('auth_profile_ref')
    acknowledged = source.get('mode') == 'ACKNOWLEDGED_PREPARATION_CUSTODY'
    reconciliation = _cli_version_reconciliation(source, target)
    if (source.get('mode') not in {'FIRST_ISOLATED_PREPARATION_CUSTODY', 'ACKNOWLEDGED_PREPARATION_CUSTODY'}
            or proof.get('contract_version') != (ACKNOWLEDGED_CONTRACT if acknowledged else CONTRACT) or proof.get('source_operation_id') != source['source_operation_id']
            or proof.get('custody_source_operation_id') != source['source_operation_id']
            or proof.get('main_dispatch_count') != 0 or proof.get('isolated_generation_count') != (0 if acknowledged else 1)
            or proof.get('source_submission_rights') != 'REVOKED_OR_TERMINALLY_RELEASED'
            or len(ancestry) != 1 or ancestry[0].get('kind') != ('ACKNOWLEDGED_CANCELLATION' if acknowledged else 'ISOLATED')
            or ancestry[0].get('operation_id') != source['source_operation_id']
            or not proof.get('retained_preparation') or not isinstance(reference, str) or not reference
            or target.get('model_provider') != 'codex-cli' or target.get('cost_accounting_basis') != 'ACCOUNT_ENTITLEMENT'
            or not all(isinstance(account.get(key), str) and account[key] for key in ('codex_home', 'executable'))
            or not isinstance(account.get('entitlement'), dict) or not account['entitlement']
            or target.get('auth_profile_ref') != reference and reconciliation is None):
        raise KernelError('PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT',
            'First recovery requires its exact isolated owner, settled native preparation and authenticated membership route')
    target_runtime(None, source, target)
    try:
        binding = codex_local_binding_hash(codex_home=account['codex_home'], executable=account['executable'],
            entitlement=account['entitlement'], retry_policy=str(account.get('retry_policy') or ''),
            input_only_policy=str(account.get('input_only_policy') or ''))
    except (TypeError, ValueError) as error:
        raise KernelError('PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT',
            'Original membership recovery requires a supported frozen local configuration') from error
    if not target['auth_profile_ref'].endswith(':codex:' + binding):
        raise KernelError('PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT',
            'Current account, executable and configuration must reconstruct the original verified preparation authentication')
    return dict(reasoning_evidence_source='ORIGINAL_FROZEN_MAIN_ROUTE',
        authorized_reasoning_effort=route['reasoning_effort'], account_evidence_source='VERIFIED_PREPARATION_AND_MAIN_ROUTE',
        source_auth_profile_ref=reference, source_operation_id=source['source_operation_id'],
        source_pack_snapshot_hash=proof['original_pack_snapshot_hash'], account_runtime_hash=canonical_hash(account),
        **({'account_version_reconciliation': reconciliation} if reconciliation is not None else {}))


def authorization(uow, *, source, successor, principal, target):
    from .runtime_continuation import _capacity_authorization, require_route_evidence
    capacity = _capacity_authorization(uow, source=source, successor=successor, principal=principal, target=target)
    route = (require_route_evidence(uow, source=source, target=target,
        authorized_reasoning_effort=source['fresh_preparation']['original_route']['reasoning_effort'])
        if source['command'].get('runtime_continuation_id') or source['provider'] == 'scripted_provider_v2'
        else _first_route_authorization(source, target))
    return {**capacity, 'capacity_only': False, 'recovery_kind': source['mode'],
        'route_authorization': route, 'preserved_repair_number': successor.repair_number,
        'retained_preparation_count': len(source['fresh_preparation']['retained_preparation']),
        'generation_recovery_number': source['fresh_preparation']['isolated_generation_count']}
