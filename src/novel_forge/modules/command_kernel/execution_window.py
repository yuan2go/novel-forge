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
                                       clock=lambda: datetime.now(timezone.utc)):
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
        if not deadline or deadline > now:
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
        cursor.execute("SELECT o.status,a.result->>'error_code',o.actor_id FROM authority_operation o JOIN authority_attempt a USING(operation_id) JOIN authority_saga_step s USING(operation_id) WHERE o.operation_id=%s AND o.root_operation_id=%s ORDER BY a.attempt_number DESC LIMIT 1", [predecessor_id,root_id])
        if cursor.fetchone() != ('CANCELLATION_REQUESTED','REALIZATION_EPISTEMIC_SCOPE_VIOLATION',principal.principal_id) or has_candidate_domain_outputs(cursor,predecessor_id):
            raise KernelError('EXECUTION_WINDOW_CANDIDATE_INVALID','Only the recorded failed candidate contract can authorize a window')
        target = uow.repositories.definitions.get('chapter.draft.generate',target_version)
        if not target or target['policy'].get('scene_information_flow') != 'scene-information-flow.v1':
            raise KernelError('EXECUTION_WINDOW_TARGET_INVALID','The unexecuted successor requires the declared correction')
        cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_external_effect e LEFT JOIN authority_budget_reservation r ON r.external_effect_id=e.external_effect_id JOIN authority_operation o ON o.operation_id=e.operation_id WHERE o.root_operation_id=%s AND (e.status<>'SUCCEEDED' OR r.status IS DISTINCT FROM 'SETTLED')), EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())", [root_id,root_id])
        if any(cursor.fetchone()):
            raise KernelError('EXECUTION_WINDOW_UNSETTLED','Uncertain effects or live leases prevent continuation')
        key = hashlib.sha256(json.dumps([root_id,predecessor_id,target_version,admission['policy_snapshot']['policy_hash']],sort_keys=True).encode()).hexdigest()
        cursor.execute('SELECT payload FROM audit_log WHERE operation_id=%s AND action=%s AND payload->>\'continuation_key\'=%s', [root_id,EVENT,key])
        previous = cursor.fetchone()
        if previous:
            return {'continued':True,'replayed':True,'deadline':previous[0]['new_deadline']}
        duration = int(root['definition_snapshot']['timeout_policy']['operation_timeout_seconds'])
        if not 0 < duration <= 3600:
            raise KernelError('EXECUTION_WINDOW_BOUND_INVALID','Continuation retains the original bounded Root window')
        renewed = now + timedelta(seconds=duration)
        cursor.execute('UPDATE authority_operation SET business_deadline_at=%s,version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status=\'WAITING_CHILDREN\'', [renewed,root_id,root['version']])
        if cursor.rowcount != 1:
            raise KernelError('EXECUTION_WINDOW_VERSION_CONFLICT','Reload the current Root fence')
        _record(uow.repositories.operation_graph,GraphCommandContext(root['project_id'],principal.principal_id,root['trace_id'],root['correlation_id'],predecessor_id), root_id,EVENT,
                {'contract_version':'chapter-execution-window-renewal.v1','continuation_key':key,'source_root':root,
                 'predecessor_operation_id':predecessor_id,'target_definition_version':target_version,
                 'policy_admission':admission,'original_deadline':deadline.isoformat(),'new_deadline':renewed.isoformat(),
                 'preserved':'CHILD_DEADLINES_TERMINAL_ATTEMPTS_EFFECTS_RECEIPTS_USAGE_ACCEPTANCE'})
        uow.commit()
    return {'continued':True,'replayed':False,'deadline':renewed}
