from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import GraphCommandContext, _record
from novel_forge.modules.command_kernel.step_successor import has_candidate_domain_outputs
from novel_forge.modules.production_execution.execution_template import selected_book_template, selected_template
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

EVENT = 'authority.operation.execution_window_continued'


def continue_candidate_execution_window(database_url, *, root_id, predecessor_id, target_version, book_run_id, principal,
                                       clock=lambda: datetime.now(timezone.utc), start_repair_phase=False):
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute('SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE', [root_id])
        row = cursor.fetchone()
        if not row:
            raise KernelError('OPERATION_NOT_FOUND', 'Missing continuation Root')
        root = row[0]
        principal.require('chapter.authority.execute', root['project_id'])
        principal.require('book.authority.execute', root['project_id'])
        if root['actor_id'] != principal.principal_id or root['status'] != 'WAITING_CHILDREN' or root['definition_name'] != 'chapter.slice.run':
            raise KernelError('EXECUTION_WINDOW_ROOT_INVALID', 'Only an owned unfinished Chapter Root can continue')
        cursor.execute('SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s', [root_id])
        deadline = cursor.fetchone()[0]
        now = clock()
        if not deadline or (deadline > now and not start_repair_phase):
            return {'continued':False,'deadline':deadline}
        cursor.execute('SELECT project_id,book_id,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE', [book_run_id])
        book = cursor.fetchone()
        if not book or book[0] != root['project_id']:
            raise KernelError('EXECUTION_WINDOW_BOOK_INVALID','Continuation must bind the exact Book')
        cursor.execute('SELECT chapter_root_operation_id,chapter_number FROM authority_book_chapter_request WHERE chapter_request_id=%s', [book[2]])
        if cursor.fetchone() != (root_id,book[3]+1):
            raise KernelError('EXECUTION_WINDOW_FRONTIER_INVALID','Only the current unaccepted Chapter can continue')
        admission = selected_book_template(cursor,project_id=book[0],book_id=book[1])
        template = selected_template(admission['policy_snapshot']['policy'],book[1]) if admission else None
        if not template or template.get('chapter_contract_recovery') != 'KNOWN_SETTLED_CONTRACT_REPAIR':
            raise KernelError('EXECUTION_WINDOW_POLICY_REQUIRED','An explicit trusted creative continuation policy is required')
        if any(key in root['command_payload'] for key in ('business_deadline_at','author_deadline_at')):
            raise KernelError('EXECUTION_WINDOW_AUTHOR_DEADLINE','An author deadline cannot be extended by execution recovery')
        cursor.execute("SELECT o.status,a.result->>'error_code',o.actor_id,o.definition_name FROM authority_operation o JOIN authority_attempt a USING(operation_id) JOIN authority_saga_step s USING(operation_id) WHERE o.operation_id=%s AND o.root_operation_id=%s ORDER BY a.attempt_number DESC LIMIT 1", [predecessor_id,root_id])
        source = cursor.fetchone()
        corrections = {
            ('chapter.draft.generate','CANCELLATION_REQUESTED','REALIZATION_EPISTEMIC_SCOPE_VIOLATION'):('3.9.2','scene_information_flow','scene-information-flow.v1'),
            ('chapter.review.evaluate','FAILED_FINAL','REVIEW_KNOWLEDGE_CHECK_INVALID'):('3.9.3','review_knowledge_scope','delivered-card-scope.v1'),
            ('chapter.review.evaluate','FAILED_FINAL','REVIEW_KNOWLEDGE_CHECK_REQUIRED'):('3.9.3','review_knowledge_scope','delivered-card-scope.v1'),
            ('chapter.revision.apply','CANCELLATION_REQUESTED','REVISION_OUTSIDE_DIAGNOSIS_SCOPE'):('3.9.4','chapter_length_scope','chapter-length-repair.v1'),
            ('chapter.revision.apply','FAILED_RETRYABLE','CHAPTER_LENGTH_REPAIR_INCOMPLETE'):('3.9.4','chapter_length_scope','chapter-length-repair.v1'),
            ('chapter.revision.apply','FAILED_RETRYABLE','OPERATION_BUSINESS_TIMEOUT'):('3.9.4','chapter_length_scope','chapter-length-repair.v1'),
            ('chapter.canon.extract','CANCELLATION_REQUESTED','PROVIDER_ROUTING_BLOCKED'):('3.9.5','canon_schema_projection','canon-provider-shared-types.v1'),
            ('chapter.canon.extract','FAILED_RETRYABLE','PROVIDER_ROUTING_BLOCKED'):('3.9.0',None,None),
        }
        correction = corrections.get((source[3],source[0],source[1])) if source else None
        if source and source[1] == 'OPERATION_BUSINESS_TIMEOUT' and not start_repair_phase:
            raise KernelError('EXECUTION_PHASE_SOURCE_INVALID','A known no-send timeout requires its explicit bounded control recovery')
        if not correction or source[2] != principal.principal_id or correction[0] != target_version or has_candidate_domain_outputs(cursor,predecessor_id):
            raise KernelError('EXECUTION_WINDOW_CANDIDATE_INVALID','Only the recorded failed contract and exact correction can authorize a window')
        target = uow.repositories.definitions.get(source[3],target_version)
        if not target or (correction[1] and target['policy'].get(correction[1]) != correction[2]):
            raise KernelError('EXECUTION_WINDOW_TARGET_INVALID','The unexecuted successor requires the declared correction')
        cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_external_effect e LEFT JOIN authority_budget_reservation r ON r.external_effect_id=e.external_effect_id JOIN authority_operation o ON o.operation_id=e.operation_id WHERE o.root_operation_id=%s AND (e.status<>'SUCCEEDED' OR r.status IS DISTINCT FROM 'SETTLED')), EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())", [root_id,root_id])
        if any(cursor.fetchone()):
            raise KernelError('EXECUTION_WINDOW_UNSETTLED','Uncertain effects or live leases prevent continuation')
        key_parts = [root_id,predecessor_id,target_version,admission['policy_snapshot']['policy_hash']]
        child = None
        control_recovery_limit = None
        canon_capacity = bool(source[3] == 'chapter.canon.extract' and source[1] == 'PROVIDER_ROUTING_BLOCKED')
        if canon_capacity and source[0] == 'CANCELLATION_REQUESTED':
            cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation WHERE operation_id=%s AND definition_version='3.9.0'),
                NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
                NOT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND (status<>'FAILED_RETRYABLE' OR result->>'error_code' IS DISTINCT FROM 'PROVIDER_ROUTING_BLOCKED')),
                EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset x USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
                    WHERE oa.operation_id=%s AND x.asset_type='routing_decision' AND v.content #>> '{candidates,0,rejected_reasons}' LIKE '%%CONTEXT_CAPACITY_EXCEEDED%%'),
                EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset x USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
                    WHERE oa.operation_id=%s AND x.asset_type='capability_materialization_manifest' AND v.content #>> '{contract,output_schema,ref}'
                        IN ('schema:chapter-provider-output:canon_extraction:v22','schema:chapter-provider-output:canon_extraction:v23'))""", [predecessor_id]*5)
            if not all(cursor.fetchone()):
                raise KernelError('EXECUTION_WINDOW_CAPACITY_PROOF_REQUIRED','Canon succession requires only exact no-send legacy capacity refusals')
        if canon_capacity and source[0] != 'CANCELLATION_REQUESTED' and not start_repair_phase:
            raise KernelError('EXECUTION_PHASE_SOURCE_INVALID','Canon capacity recovery requires its explicit bounded phase')
        if start_repair_phase:
            if source[0] != 'FAILED_RETRYABLE' or (not canon_capacity and source[1] not in {'CHAPTER_LENGTH_REPAIR_INCOMPLETE','OPERATION_BUSINESS_TIMEOUT'}):
                raise KernelError('EXECUTION_PHASE_SOURCE_INVALID','Only a known settled bounded length retry may start a new phase')
            cursor.execute('SELECT to_jsonb(o),business_deadline_at FROM authority_operation o WHERE operation_id=%s FOR UPDATE',[predecessor_id])
            child,child_deadline = cursor.fetchone()
            if child['definition_version'] != ('3.9.0' if canon_capacity else '3.9.4') or any(k in child['command_payload'] for k in ('business_deadline_at','author_deadline_at')):
                raise KernelError('EXECUTION_PHASE_CHILD_INVALID','Only the exact derived length retry window can continue')
            cursor.execute("SELECT a.attempt_id,a.attempt_number,(o.definition_snapshot #>> '{retry_policy,max_attempts}')::int FROM authority_attempt a JOIN authority_operation o USING(operation_id) WHERE o.operation_id=%s ORDER BY a.attempt_number DESC LIMIT 1",[predecessor_id])
            failed_attempt,number,maximum = cursor.fetchone()
            if canon_capacity:
                cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
                    EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset a ON a.asset_id=oa.asset_id JOIN authority_asset_version v USING(asset_version_id)
                        WHERE oa.operation_id=%s AND a.asset_type='routing_decision' AND v.content #>> '{candidates,0,rejected_reasons}' LIKE '%%CONTEXT_CAPACITY_EXCEEDED%%'),
                    EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset a ON a.asset_id=oa.asset_id JOIN authority_asset_version v USING(asset_version_id)
                        WHERE oa.operation_id=%s AND a.asset_type='capability_materialization_manifest' AND v.content #>> '{contract,output_schema,ref}' IN ('schema:chapter-provider-output:canon_extraction:v22','schema:chapter-provider-output:canon_extraction:v23'))""",[predecessor_id,predecessor_id,predecessor_id])
                sent,capacity,inline_schema = cursor.fetchone()
                if sent or not capacity or not inline_schema:
                    raise KernelError('EXECUTION_PHASE_CAPACITY_PROOF_REQUIRED','Only exact no-send rendered-capacity failures can continue')
            if source[1] == 'OPERATION_BUSINESS_TIMEOUT':
                cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND request_payload #>> '{_production_execution,attempt_id}'=%s),
                    EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND attempt_number=%s AND status='FAILED_RETRYABLE' AND result->>'error_code'='CHAPTER_LENGTH_REPAIR_INCOMPLETE'),
                    (SELECT count(*) FROM authority_external_effect WHERE operation_id=%s),
                    (SELECT count(*) FROM authority_attempt WHERE operation_id=%s AND result->>'error_code'='OPERATION_BUSINESS_TIMEOUT')""",[predecessor_id,failed_attempt,predecessor_id,number-1,predecessor_id,predecessor_id])
                sent,known_length,calls,timeouts = cursor.fetchone()
                if sent or not known_length or calls>=maximum or timeouts!=1 or number>maximum:
                    raise KernelError('EXECUTION_PHASE_NO_SEND_PROOF_REQUIRED','One known pre-dispatch timeout with remaining original Provider capacity is required')
                control_recovery_limit = maximum+1
            elif number>=maximum:
                raise KernelError('EXECUTION_PHASE_RETRY_EXHAUSTED','A new execution phase cannot reset retry exhaustion')
            key_parts.extend(['chapter-execution-window-renewal.v4' if canon_capacity else 'chapter-execution-window-renewal.v3',failed_attempt])
        key = hashlib.sha256(json.dumps(key_parts,sort_keys=True).encode()).hexdigest()
        cursor.execute('SELECT payload FROM audit_log WHERE operation_id=%s AND action=%s AND payload->>\'continuation_key\'=%s', [root_id,EVENT,key])
        previous = cursor.fetchone()
        if previous:
            return {'continued':True,'replayed':True,'deadline':previous[0]['new_deadline']}
        duration = int(root['definition_snapshot']['timeout_policy']['operation_timeout_seconds'])
        if not 0 < duration <= 3600:
            raise KernelError('EXECUTION_WINDOW_BOUND_INVALID','Continuation retains the original bounded Root window')
        renewed = max(deadline,now + timedelta(seconds=duration))
        child_after = None
        if child is not None:
            child_duration = int(child['definition_snapshot']['timeout_policy']['operation_timeout_seconds'])
            if not child_deadline or not 0 < child_duration <= duration:
                raise KernelError('EXECUTION_PHASE_CHILD_BOUND_INVALID','Retry retains its original bounded child duration')
            child_renewed = min(renewed,max(child_deadline,now+timedelta(seconds=child_duration)))
            cursor.execute("UPDATE authority_operation SET business_deadline_at=%s,version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status='FAILED_RETRYABLE' RETURNING to_jsonb(authority_operation)",[child_renewed,predecessor_id,child['version']])
            child_after = cursor.fetchone()
            if not child_after:
                raise KernelError('EXECUTION_PHASE_CHILD_CONFLICT','Reload the exact retry child')
        cursor.execute('UPDATE authority_operation SET business_deadline_at=%s,version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status=\'WAITING_CHILDREN\'', [renewed,root_id,root['version']])
        if cursor.rowcount != 1:
            raise KernelError('EXECUTION_WINDOW_VERSION_CONFLICT','Reload the current Root fence')
        _record(uow.repositories.operation_graph,GraphCommandContext(root['project_id'],principal.principal_id,root['trace_id'],root['correlation_id'],predecessor_id), root_id,EVENT,
                {'contract_version':('chapter-execution-window-renewal.v4' if canon_capacity else 'chapter-execution-window-renewal.v3') if start_repair_phase else 'chapter-execution-window-renewal.v1','continuation_key':key,'source_root':root,
                 'predecessor_operation_id':predecessor_id,'target_definition_version':target_version,
                 'policy_admission':admission,'original_deadline':deadline.isoformat(),'new_deadline':renewed.isoformat(),
                 **({'source_child':child,'continued_child':child_after[0],'failed_attempt_id':failed_attempt,
                     'original_attempt_limit':maximum,'control_recovery_attempt_limit':control_recovery_limit} if child is not None else {}),
                 'preserved':'TERMINAL_ATTEMPTS_EFFECT_DEADLINES_RECEIPTS_USAGE_ACCEPTANCE'})
        uow.commit()
    return {'continued':True,'replayed':False,'deadline':renewed}


def continued_attempt_limit(cursor, *, operation_id, project_id, original_limit):
    cursor.execute("""SELECT j.payload FROM audit_log j JOIN authority_operation o ON o.root_operation_id=j.operation_id
        JOIN authority_attempt a ON a.operation_id=o.operation_id
        WHERE o.operation_id=%s AND o.project_id=%s AND o.status IN ('READY','FAILED_RETRYABLE')
        AND o.definition_name='chapter.revision.apply' AND o.definition_version='3.9.4'
        AND j.action=%s AND j.payload->>'contract_version'='chapter-execution-window-renewal.v3'
        AND j.payload->>'predecessor_operation_id'=o.operation_id
        AND j.payload->>'failed_attempt_id'=a.attempt_id AND a.status='FAILED_RETRYABLE'
        AND a.result->>'error_code'='OPERATION_BUSINESS_TIMEOUT'
        AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=o.operation_id)
        AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=o.operation_id AND e.request_payload #>> '{_production_execution,attempt_id}'=a.attempt_id)
        ORDER BY j.created_at DESC LIMIT 1""",[operation_id,project_id,EVENT])
    row = cursor.fetchone()
    if not row:
        return original_limit
    evidence = row[0]
    if evidence.get('original_attempt_limit') != original_limit or evidence.get('control_recovery_attempt_limit') != original_limit+1:
        return original_limit
    return original_limit+1
