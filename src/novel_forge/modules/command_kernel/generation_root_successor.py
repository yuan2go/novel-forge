from __future__ import annotations

from uuid import uuid4
from types import SimpleNamespace
from psycopg.types.json import Jsonb

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .errors import KernelError
from .generation_isolation import append_isolation, generation_retry_usage
from .runtime import OperationTransitionCommand, transition_operation_in_uow
from .service import admit_command_in_uow
from .operation_graph import GraphCommandContext, _record


def replace_stopped_generation_root(database_url, *, source_id, project_id, context, scope_guard):
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute('SELECT saga_id FROM authority_operation WHERE operation_id=%s', [source_id])
        row = cursor.fetchone()
        if not row or not row[0]:
            raise KernelError('GENERATION_ROOT_SOURCE_MISSING','Require the original native sidecar Saga')
        saga_id = row[0]
        saga = uow.repositories.operation_graph.saga_for_update(saga_id, project_id)
        cursor.execute('SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE', [source_id])
        source = cursor.fetchone()[0]
        graph_context = GraphCommandContext(project_id,context.actor_id,source['trace_id'],source['correlation_id'])
        if source['actor_id'] != context.actor_id or source['project_id'] != project_id:
            raise KernelError('GENERATION_ROOT_SCOPE_CONFLICT', 'Recovery requires the original actor and project')
        cursor.execute('SELECT successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s', [source_id])
        existing = cursor.fetchone()
        if existing:
            return {'operation_id': existing[0], 'replayed': True}
        definition = source['definition_snapshot']
        if (source['root_operation_id'] != source_id or source['parent_operation_id']
                or source['definition_name'] != 'longform.prose_review'
                or definition['family'] != 'book_followup_authority'
                or definition['policy'].get('body_mutation_allowed') is not False
                or definition['policy'].get('plan_mutation_allowed') is not False
                or definition['irreversible_effect_policy'].get('allowed') is not False
                or not set(definition['permissions']).issubset(context.permissions)
                or source['status'] not in {'WAITING_EXTERNAL_RESULT', 'RECONCILIATION_REQUIRED', 'FAILED_FINAL', 'DEAD_LETTER'}):
            raise KernelError('GENERATION_ROOT_SCOPE_UNSAFE', 'Only an owned stopped read-only review sidecar can continue')
        scope_guard(uow, source)
        cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation_dependency WHERE depends_on_operation_id=%s),
            EXISTS(SELECT 1 FROM authority_saga_step WHERE saga_id=%s),
            EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)""", [source_id,saga_id,source_id])
        if any(cursor.fetchone()):
            raise KernelError('GENERATION_ROOT_ACTIVE_DEPENDENCY', 'Dependencies, child work and cancellation retain their owners')
        cursor.execute('SELECT to_jsonb(e) FROM authority_external_effect e WHERE operation_id=%s FOR UPDATE', [source_id])
        effects = [row[0] for row in cursor.fetchall()]
        if len(effects) != 1 or effects[0]['effect_type'] != 'model.invoke':
            raise KernelError('GENERATION_ROOT_EFFECT_SCOPE_UNSAFE', 'Require one original native model invocation')
        effect = effects[0]
        authorization = effect['request_payload'].get('_production_execution', {}).get('capability_runtime', {}).get('routing_decision', {}).get('selected', {}).get('candidate', {}).get('authorization_ref')
        proof = append_isolation(uow, effect, SimpleNamespace(actor_id=context.actor_id,project_id=project_id,
            reason='Preserve stopped review and continue its frozen logical window', evidence={'authorization_ref':authorization},
            trace_id=source['trace_id'],correlation_id=source['correlation_id']))
        retry = generation_retry_usage(cursor, operation_id=source_id)
        if retry['failure_attempts'] >= retry['maximum_failure_attempts']:
            cursor.execute("SELECT 1 FROM state_event WHERE aggregate_type='authority_operation' AND aggregate_id=%s AND event_type='authority.generation.recovery_exhausted'",[source_id])
            previous = bool(cursor.fetchone())
            if not previous:
                _record(uow.repositories.operation_graph,graph_context,source_id,'authority.generation.recovery_exhausted',
                    {'error_code':'GENERATION_RECOVERY_EXHAUSTED',**retry})
            uow.commit()
            return {'operation_id': source_id, 'replayed': previous, 'recovery_state':'EXHAUSTED', 'retry':retry}
        admitted = admit_command_in_uow(uow, {
            'definition_name':source['definition_name'],'definition_version':source['definition_version'],
            'project_id':source['project_id'],'workspace_id':source['workspace_id'],'actor_id':context.actor_id,
            'idempotency_scope':source['idempotency_scope'],'idempotency_key':'generation-root-successor:'+source_id,
            'trace_id':source['trace_id'],'span_id':str(uuid4()),'correlation_id':source['correlation_id'],
            'causation_id':source_id,'causation_operation_id':source_id,'input':source['command_payload'],
            'input_assets':source['input_asset_snapshot'],
        }, context=context)
        successor = admitted['operation_id']
        state = uow.repositories.attempt_runtime.operation_state(successor, project_id)
        transition_operation_in_uow(uow, OperationTransitionCommand(successor, project_id, state['version'],
            'ADMITTED','READY',context.actor_id,'Linked native read-only generation successor',source['trace_id'],source['correlation_id'],source_id))
        new_saga = uow.repositories.operation_graph.start_saga(str(uuid4()),successor,project_id,source['trace_id'],source['correlation_id'])
        cursor.execute('SELECT request_digest FROM authority_operation WHERE operation_id=%s',[successor])
        request_digest = cursor.fetchone()[0]
        cursor.execute("""INSERT INTO authority_saga_step_successor(successor_id,project_id,saga_id,predecessor_operation_id,
            successor_operation_id,actor_id,contract_version,request_digest,source_saga_snapshot,source_step_snapshot,
            source_failure_snapshot,policy_evidence) VALUES (%s,%s,%s,%s,%s,%s,'kernel-failed-step-successor.v2',%s,%s,%s,%s,%s)""",
            [str(uuid4()),project_id,saga_id,source_id,successor,context.actor_id,
                request_digest,
                Jsonb(saga),Jsonb({'operation_id':source_id,'role':'SAGA_ROOT'}),Jsonb({'operation':source}),
                Jsonb({'contract_version':'pure-generation-root-successor.v1','isolation':proof,'retry':retry,'successor_saga_id':new_saga['saga_id']})])
        _record(uow.repositories.operation_graph,graph_context,source_id,'authority.generation.root_successor_registered',
            {'successor_operation_id':successor,'schedule_intent':'NATIVE_AUTHORITY_SCHEDULER'})
        uow.commit()
        return {'operation_id':successor,'replayed':False}
