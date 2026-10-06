from __future__ import annotations

from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor import replace_failed_step, has_candidate_domain_outputs
from novel_forge.modules.production_execution.execution_template import selected_book_template
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def recover_information_frontier(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute', book['project_id'])
    principal.require('chapter.authority.execute', book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number'] != book['accepted_through_chapter'] + 1:
        return False
    with AuthorityUnitOfWork(authority.database_url) as uow:
        template = selected_book_template(uow.cursor, project_id=book['project_id'], book_id=book['book_id'])
        if not template:
            return False
        uow.cursor.execute("""SELECT to_jsonb(o),to_jsonb(a) FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id) JOIN authority_attempt a USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.draft.generate'
            AND o.definition_version='3.9.1' AND o.status IN ('FAILED_RETRYABLE','CANCELLATION_REQUESTED')
            AND a.result->>'error_code'='REALIZATION_EPISTEMIC_SCOPE_VIOLATION' ORDER BY a.attempt_number DESC LIMIT 1""", [request['chapter_root_operation_id'], book['project_id']])
        row = uow.cursor.fetchone()
        if not row:
            return False
        source, attempt = row
        if source['actor_id'] != principal.principal_id:
            raise KernelError('CHAPTER_CANDIDATE_RECOVERY_ACTOR_INVALID', 'Recovery requires the original actor')
        uow.cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.status,r.status FROM authority_external_effect e
            LEFT JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id""", [source['operation_id']])
        effects = uow.cursor.fetchall()
        if not effects or any(r[2:] != ('SUCCEEDED','SETTLED') for r in effects):
            raise KernelError('CHAPTER_CANDIDATE_RECOVERY_UNSETTLED', 'Reconcile original effects before candidate recovery')
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s),
            EXISTS(SELECT 1 FROM authority_operation_dependency WHERE depends_on_operation_id=%s),
            EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
                WHERE a.operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())""", [source['operation_id']]*3)
        _, dependent, lease = uow.cursor.fetchone()
        if dependent or lease or has_candidate_domain_outputs(uow.cursor, source['operation_id']):
            raise KernelError('CHAPTER_CANDIDATE_RECOVERY_STARTED', 'Outputs, dependents or live leases prevent succession')
    evidence = {'contract_version':'chapter-candidate-contract-repair.v1', 'book_run_id':book_run_id,
        'chapter_request_id':request['chapter_request_id'], 'policy_admission':template,
        'input_snapshot':source['input_asset_snapshot'], 'source_failure':attempt,
        'source_operation_before_cancellation':source, 'settled_candidate_effects':effects,
        'completion_checks':'UNCHANGED', 'accepted_cursor':book['accepted_through_chapter']}
    if source['status'] != 'CANCELLATION_REQUESTED':
        request_cancellation(authority.database_url, CancelCommand(operation_id=source['operation_id'],
            project_id=book['project_id'],actor_id=principal.principal_id,reason='Known settled candidate requires versioned information-flow repair',
            expected_version=source['version'],idempotency_key='candidate-repair:'+source['operation_id'],
            trace_id=source['trace_id'],correlation_id=source['correlation_id']))
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url, root_id=request['chapter_root_operation_id'],
        predecessor_id=source['operation_id'],target_version='3.9.2',book_run_id=book_run_id,principal=principal)
    def guard(uow):
        uow.cursor.execute('SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE', [book_run_id,book['project_id']])
        if uow.cursor.fetchone() != (book['version'],book['active_chapter_request_id'],book['accepted_through_chapter']) or selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id']) != template:
            raise KernelError('CHAPTER_CANDIDATE_RECOVERY_CONFLICT', 'Reload the exact current Book frontier')
    replace_failed_step(authority.database_url,predecessor_id=source['operation_id'],target_version='3.9.2',
        context=AdmissionContext(principal.principal_id,principal.permissions,authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,authority.commit_sha), policy_evidence=evidence,
        expected_failure_code='REALIZATION_EPISTEMIC_SCOPE_VIOLATION',
        settled_candidate_effects=tuple((r[0],r[1]) for r in effects),transaction_guard=guard)
    return True


def candidate_repair_payload(request):
    if request.definition_version not in {'3.9.2','3.9.3','3.9.4'} or not request.database_url:
        return {}
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute('''SELECT e.external_effect_id,a.attempt_id,a.result,r.payload->'evidence'
            FROM authority_attempt a JOIN authority_external_effect e ON e.operation_id=a.operation_id
                AND e.request_payload #>> '{_production_execution,attempt_id}'=a.attempt_id
            JOIN authority_budget_reservation b USING(external_effect_id)
            JOIN authority_external_effect_dispatch d USING(external_effect_id)
            JOIN authority_external_receipt r USING(dispatch_id)
            WHERE a.operation_id=%s AND e.project_id=%s AND a.attempt_id<>%s
                AND a.status='FAILED_RETRYABLE' AND (a.result->>'error_code' LIKE 'REALIZATION_%%' OR a.result->>'error_code'='CHAPTER_LENGTH_REPAIR_INCOMPLETE')
                AND e.status='SUCCEEDED' AND b.status='SETTLED'
            ORDER BY a.attempt_number DESC,r.received_at DESC LIMIT 1''',
            [request.operation_id,request.project_id,request.attempt_id])
        recent = uow.cursor.fetchone()
        if recent:
            from .model_effects import ModelProviderResult
            result = ModelProviderResult.from_evidence(recent[3])
            measured = {}
            if request.definition_version == '3.9.4':
                from .realization_composition import prose_from_output
                from novel_forge.modules.revision.domain import han_characters
                measured = {'length_observation':{'unit':'HAN_CHARACTERS_V1','observed':han_characters(prose_from_output(result.output))}}
            return {'candidate_repair': {'contract_version':'chapter-candidate-output-repair.v1',
                'source_effect_id':recent[0], 'source_attempt_id':recent[1], 'diagnostic':recent[2],
                'rejected_candidate':result.output, **measured,
                'instruction':'Repair this latest rejected candidate under the exact current slots and original work requirements. No invented facts, future knowledge, padding or fabricated approval.'}}
        uow.cursor.execute("""SELECT policy_evidence FROM authority_saga_step_successor
            WHERE project_id=%s AND successor_operation_id=%s""", [request.project_id,request.operation_id])
        row = uow.cursor.fetchone()
        if not row or row[0].get('contract_version') not in {'chapter-candidate-contract-repair.v1','chapter-review-output-repair.v1','chapter-length-output-repair.v1'}:
            return {}
        binding = row[0]
        effect_id = binding['settled_candidate_effects'][-1][0]
        uow.cursor.execute("""SELECT r.payload->'evidence' FROM authority_external_receipt r
            JOIN authority_external_effect_dispatch d USING(dispatch_id) JOIN authority_external_effect e USING(external_effect_id)
            JOIN authority_budget_reservation b USING(external_effect_id)
            WHERE e.external_effect_id=%s AND e.project_id=%s AND e.status='SUCCEEDED' AND b.status='SETTLED'
            ORDER BY r.received_at DESC LIMIT 1""", [effect_id,request.project_id])
        row = uow.cursor.fetchone()
        if not row:
            raise KernelError('CHAPTER_CANDIDATE_REPAIR_EVIDENCE_MISSING', 'Retained candidate requires its exact succeeded receipt')
    from .model_effects import ModelProviderResult
    result = ModelProviderResult.from_evidence(row[0])
    return {'candidate_repair': {'contract_version':binding['contract_version'],
        'source_effect_id':effect_id,'source_attempt_id':binding['source_failure']['attempt_id'],
        'diagnostic':binding['source_failure']['result'], 'rejected_candidate':result.output,
        'instruction':('Repair the actual review against the exact delivered knowledge_review_targets; an empty target list requires knowledge_checks=[]. Retain valid evidenced prose diagnoses; do not fabricate verification, approval or resolution.' if binding['contract_version']=='chapter-review-output-repair.v1' else 'Repair the actual retained revision under the exact chapter_length_repair_scope and supplied review; preserve scene coverage, facts, information boundaries and voice. Never claim acceptance or literary proof.' if binding['contract_version']=='chapter-length-output-repair.v1' else 'Repair the actual candidate using the new exact slot scopes. Meet the original work length without repetition or padding. Do not invent fact ids, future knowledge, approval or acceptance.')}}


def _recover_settled_output_frontier(authority, *, book_run_id, principal, definition_name, target_version, contract_version, failure_codes, statuses):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute', book['project_id'])
    principal.require('chapter.authority.execute', book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number'] != book['accepted_through_chapter'] + 1:
        return False
    from novel_forge.modules.production_execution.execution_template import selected_template
    with AuthorityUnitOfWork(authority.database_url) as uow:
        template = selected_book_template(uow.cursor, project_id=book['project_id'], book_id=book['book_id'])
        policy = selected_template(template['policy_snapshot']['policy'], book['book_id']) if template else None
        if not policy or policy.get('chapter_contract_recovery') != 'KNOWN_SETTLED_CONTRACT_REPAIR':
            return False
        uow.cursor.execute("""SELECT to_jsonb(o),to_jsonb(a) FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id)
            JOIN LATERAL (SELECT * FROM authority_attempt WHERE operation_id=o.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name=%s
            AND o.definition_version='3.9.0' AND o.status=ANY(%s)
            AND a.result->>'error_code'=ANY(%s)
            ORDER BY a.attempt_number DESC LIMIT 1""", [request['chapter_root_operation_id'], book['project_id'],definition_name,list(statuses),list(failure_codes)])
        row = uow.cursor.fetchone()
        if not row:
            return False
        source, attempt = row
        if source['actor_id'] != principal.principal_id:
            raise KernelError('CHAPTER_REVIEW_RECOVERY_ACTOR_INVALID', 'Recovery requires the original review actor')
        uow.cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.status,r.status FROM authority_external_effect e
            LEFT JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id""", [source['operation_id']])
        effects = uow.cursor.fetchall()
        if not effects or any(r[2:] != ('SUCCEEDED','SETTLED') for r in effects):
            raise KernelError('CHAPTER_REVIEW_RECOVERY_UNSETTLED', 'Reconcile original review effects before recovery')
    support_proof = None
    if contract_version == 'chapter-support-contract-repair.v1':
        from novel_forge.modules.canon_graph.support_recovery import support_kind_repair_evidence
        with AuthorityUnitOfWork(authority.database_url) as uow:
            support_proof = support_kind_repair_evidence(uow.cursor, source['operation_id'], attempt['attempt_id'])
    quality_proof = None
    if contract_version == 'chapter-quality-contract-repair.v1':
        from novel_forge.modules.chapter_quality_authority.applicability_contract import quality_applicability_repair_evidence
        with AuthorityUnitOfWork(authority.database_url) as uow:
            quality_proof=quality_applicability_repair_evidence(uow.cursor,source['operation_id'],attempt['attempt_id'])
    length_scope = None
    if contract_version == 'chapter-length-output-repair.v1':
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        from novel_forge.modules.revision.domain import freeze_chapter_length_scope
        query = AuthorityAssetQuery(authority.database_url)
        inputs = [query.require(project_id=book['project_id'],asset_version_id=a['asset_version_id']) for a in source['input_asset_snapshot']]
        if any(asset.content_hash != binding['content_hash'] for asset,binding in zip(inputs,source['input_asset_snapshot'],strict=True)):
            raise KernelError('CHAPTER_LENGTH_RECOVERY_INPUT_DRIFT', 'Length recovery requires its exact frozen inputs')
        draft = next(asset for asset in inputs if asset.asset_type=='draft_chapter')
        context = next(asset for asset in inputs if asset.asset_type=='context_bundle')
        length_scope = freeze_chapter_length_scope(draft.content,source_asset_version_id=draft.asset_version_id,
            context=context.content,context_asset_version_id=context.asset_version_id)
        if length_scope is None:
            raise KernelError('CHAPTER_LENGTH_RECOVERY_SCOPE_REQUIRED', 'A local edit violation without measured length deficiency retains its original recovery path')
    evidence = {'contract_version':contract_version, 'book_run_id':book_run_id,
        'chapter_request_id':request['chapter_request_id'], 'policy_admission':template,
        'input_snapshot':source['input_asset_snapshot'], 'source_failure':attempt,
        'source_operation':source, 'settled_candidate_effects':effects,
        **({'length_scope':length_scope} if length_scope is not None else {}),
        **({'support_kind_repair':support_proof} if support_proof is not None else {}),
        **({'quality_applicability_repair':quality_proof} if quality_proof is not None else {}),
        'completion_checks':'UNCHANGED', 'accepted_cursor':book['accepted_through_chapter']}
    def guard(uow):
        uow.cursor.execute('SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE', [book_run_id,book['project_id']])
        if uow.cursor.fetchone() != (book['version'],book['active_chapter_request_id'],book['accepted_through_chapter']) or selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id']) != template:
            raise KernelError('CHAPTER_REVIEW_RECOVERY_CONFLICT', 'Reload the exact current Book frontier')
    if source['status'] not in {'FAILED_FINAL','DEAD_LETTER','CANCELLATION_REQUESTED'}:
        request_cancellation(authority.database_url, CancelCommand(operation_id=source['operation_id'], project_id=book['project_id'],
            actor_id=principal.principal_id,reason='Known settled output requires its explicit versioned correction contract',
            expected_version=source['version'],idempotency_key='output-repair:'+source['operation_id'],
            trace_id=source['trace_id'],correlation_id=source['correlation_id']))
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url, root_id=request['chapter_root_operation_id'],
        predecessor_id=source['operation_id'],target_version=target_version,book_run_id=book_run_id,principal=principal)
    replace_failed_step(authority.database_url,predecessor_id=source['operation_id'],target_version=target_version,
        context=AdmissionContext(principal.principal_id,principal.permissions,authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,authority.commit_sha), policy_evidence=evidence,
        expected_failure_code=attempt['result']['error_code'],
        settled_candidate_effects=tuple((r[0],r[1]) for r in effects),transaction_guard=guard)
    return True


def recover_review_frontier(authority, *, book_run_id, principal):
    return _recover_settled_output_frontier(authority, book_run_id=book_run_id, principal=principal,
        definition_name='chapter.review.evaluate', target_version='3.9.3', contract_version='chapter-review-output-repair.v1',
        failure_codes=('REVIEW_KNOWLEDGE_CHECK_INVALID','REVIEW_KNOWLEDGE_CHECK_REQUIRED'), statuses=('FAILED_FINAL',))


def recover_support_frontier(authority, *, book_run_id, principal):
    return _recover_settled_output_frontier(authority, book_run_id=book_run_id, principal=principal,
        definition_name='chapter.canon.propose_changes', target_version='3.9.8', contract_version='chapter-support-contract-repair.v1',
        failure_codes=('CANON_GROUNDING_REEXTRACTION_REQUIRED',), statuses=('FAILED_RETRYABLE','CANCELLATION_REQUESTED'))


def recover_length_frontier(authority, *, book_run_id, principal):
    return _recover_settled_output_frontier(authority, book_run_id=book_run_id, principal=principal,
        definition_name='chapter.revision.apply', target_version='3.9.4', contract_version='chapter-length-output-repair.v1',
        failure_codes=('REVISION_OUTSIDE_DIAGNOSIS_SCOPE',), statuses=('FAILED_RETRYABLE','CANCELLATION_REQUESTED'))


def recover_length_retry_phase(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute',book['project_id'])
    principal.require('chapter.authority.execute',book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number'] != book['accepted_through_chapter']+1:
        return False
    from novel_forge.modules.production_execution.execution_template import selected_template
    with AuthorityUnitOfWork(authority.database_url) as uow:
        admission = selected_book_template(uow.cursor, project_id=book['project_id'], book_id=book['book_id'])
        template = selected_template(admission['policy_snapshot']['policy'],book['book_id']) if admission else None
        if not template or template.get('chapter_contract_recovery') != 'KNOWN_SETTLED_CONTRACT_REPAIR':
            return False
        uow.cursor.execute("""SELECT o.operation_id,o.actor_id,a.attempt_number,(o.definition_snapshot #>> '{retry_policy,max_attempts}')::int,a.result->>'error_code'
            FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN LATERAL (SELECT * FROM authority_attempt WHERE operation_id=o.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.revision.apply'
            AND o.definition_version='3.9.4' AND o.status='FAILED_RETRYABLE'
            AND a.result->>'error_code' IN ('CHAPTER_LENGTH_REPAIR_INCOMPLETE','OPERATION_BUSINESS_TIMEOUT')
            ORDER BY a.attempt_number DESC LIMIT 1""",[request['chapter_root_operation_id'],book['project_id']])
        row = uow.cursor.fetchone()
        if not row or row[2]>row[3] or (row[2]==row[3] and row[4]!='OPERATION_BUSINESS_TIMEOUT'):
            return False
        if row[4] == 'OPERATION_BUSINESS_TIMEOUT':
            uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND attempt_number=%s AND result->>'error_code'='CHAPTER_LENGTH_REPAIR_INCOMPLETE'),
                EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_attempt a ON a.operation_id=e.operation_id AND a.attempt_number=%s
                    WHERE e.operation_id=%s AND e.request_payload #>> '{_production_execution,attempt_id}'=a.attempt_id),
                (SELECT count(*) FROM authority_attempt WHERE operation_id=%s AND result->>'error_code'='OPERATION_BUSINESS_TIMEOUT')""",[row[0],row[2]-1,row[2],row[0],row[0]])
            known_length,sent,timeouts = uow.cursor.fetchone()
            if not known_length or sent or timeouts != 1:
                return False
        if row[1] != principal.principal_id:
            raise KernelError('CHAPTER_LENGTH_RETRY_ACTOR_INVALID','Retry requires the original actor')
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url,root_id=request['chapter_root_operation_id'],
        predecessor_id=row[0],target_version='3.9.4',book_run_id=book_run_id,principal=principal,start_repair_phase=True)
    return True


def recover_canon_capacity_phase(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute',book['project_id'])
    principal.require('chapter.authority.execute',book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number'] != book['accepted_through_chapter']+1:
        return False
    from novel_forge.modules.production_execution.execution_template import selected_template
    with AuthorityUnitOfWork(authority.database_url) as uow:
        admission = selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id'])
        template = selected_template(admission['policy_snapshot']['policy'],book['book_id']) if admission else None
        if not template or template.get('chapter_contract_recovery') != 'KNOWN_SETTLED_CONTRACT_REPAIR':
            return False
        uow.cursor.execute("""SELECT o.operation_id FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN LATERAL (SELECT * FROM authority_attempt WHERE operation_id=o.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.actor_id=%s AND o.definition_name='chapter.canon.extract'
            AND o.definition_version='3.9.0' AND o.status='FAILED_RETRYABLE' AND a.result->>'error_code'='PROVIDER_ROUTING_BLOCKED'
            AND a.attempt_number<(o.definition_snapshot #>> '{retry_policy,max_attempts}')::int
            AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=o.operation_id)
            AND EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset x ON x.asset_id=oa.asset_id
                JOIN authority_asset_version v USING(asset_version_id) WHERE oa.operation_id=o.operation_id AND x.asset_type='capability_materialization_manifest'
                AND v.content #>> '{contract,output_schema,ref}' IN ('schema:chapter-provider-output:canon_extraction:v22','schema:chapter-provider-output:canon_extraction:v23'))""",[request['chapter_root_operation_id'],book['project_id'],principal.principal_id])
        row = uow.cursor.fetchone()
        if not row:
            return False
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url,root_id=request['chapter_root_operation_id'],
        predecessor_id=row[0],target_version='3.9.0',book_run_id=book_run_id,principal=principal,start_repair_phase=True)
    return True


def recover_canon_capacity_frontier(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute', book['project_id'])
    principal.require('chapter.authority.execute', book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number'] != book['accepted_through_chapter'] + 1:
        return False
    from novel_forge.modules.production_execution.execution_template import selected_template
    with AuthorityUnitOfWork(authority.database_url) as uow:
        template = selected_book_template(uow.cursor, project_id=book['project_id'], book_id=book['book_id'])
        policy = selected_template(template['policy_snapshot']['policy'], book['book_id']) if template else None
        if not policy or policy.get('chapter_contract_recovery') != 'KNOWN_SETTLED_CONTRACT_REPAIR':
            return False
        uow.cursor.execute("""SELECT to_jsonb(o),to_jsonb(a) FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id)
            JOIN LATERAL (SELECT * FROM authority_attempt WHERE operation_id=o.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.canon.extract'
            AND o.definition_version='3.9.0' AND o.status IN ('FAILED_RETRYABLE','CANCELLATION_REQUESTED')
            AND a.result->>'error_code'='PROVIDER_ROUTING_BLOCKED'
            AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=o.operation_id)
            AND EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset x USING(asset_id)
                JOIN authority_asset_version v USING(asset_version_id) WHERE oa.operation_id=o.operation_id
                AND x.asset_type='capability_materialization_manifest'
                AND v.content #>> '{contract,output_schema,ref}' IN ('schema:chapter-provider-output:canon_extraction:v22','schema:chapter-provider-output:canon_extraction:v23'))""",
            [request['chapter_root_operation_id'], book['project_id']])
        row = uow.cursor.fetchone()
        if not row:
            return False
        source, attempt = row
        if source['actor_id'] != principal.principal_id:
            raise KernelError('CHAPTER_CANON_RECOVERY_ACTOR_INVALID', 'Recovery requires the original Canon actor')
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_operation_output_asset oa JOIN authority_asset x USING(asset_id)
            JOIN authority_asset_version v USING(asset_version_id) WHERE oa.operation_id=%s AND x.asset_type='routing_decision'
            AND v.content #>> '{candidates,0,rejected_reasons}' LIKE '%%CONTEXT_CAPACITY_EXCEEDED%%')""", [source['operation_id']])
        if not uow.cursor.fetchone()[0]:
            return False
        if has_candidate_domain_outputs(uow.cursor, source['operation_id']):
            raise KernelError('CHAPTER_CANON_RECOVERY_OUTPUT_PRESENT', 'Domain outputs retain their original recovery owner')
    evidence = {'contract_version':'chapter-canon-capacity-repair.v1', 'book_run_id':book_run_id,
        'chapter_request_id':request['chapter_request_id'], 'policy_admission':template,
        'input_snapshot':source['input_asset_snapshot'], 'source_failure':attempt,
        'source_operation':source, 'completion_checks':'UNCHANGED', 'accepted_cursor':book['accepted_through_chapter']}
    if source['status'] != 'CANCELLATION_REQUESTED':
        request_cancellation(authority.database_url, CancelCommand(operation_id=source['operation_id'],
            project_id=book['project_id'],actor_id=principal.principal_id,
            reason='No-send Canon capacity failure requires a new versioned Schema and Pack binding',
            expected_version=source['version'],idempotency_key='canon-capacity-repair:'+source['operation_id'],
            trace_id=source['trace_id'],correlation_id=source['correlation_id']))
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url, root_id=request['chapter_root_operation_id'],
        predecessor_id=source['operation_id'],target_version='3.9.7',book_run_id=book_run_id,principal=principal)
    def guard(uow):
        uow.cursor.execute('SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE', [book_run_id,book['project_id']])
        if uow.cursor.fetchone() != (book['version'],book['active_chapter_request_id'],book['accepted_through_chapter']) or selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id']) != template:
            raise KernelError('CHAPTER_CANON_RECOVERY_CONFLICT', 'Reload the exact current Book frontier')
    replace_failed_step(authority.database_url,predecessor_id=source['operation_id'],target_version='3.9.7',
        context=AdmissionContext(principal.principal_id,principal.permissions,authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,authority.commit_sha),policy_evidence=evidence,
        expected_failure_code='PROVIDER_ROUTING_BLOCKED',transaction_guard=guard)
    return True


def recover_canon_schema_retry_phase(authority, *, book_run_id, principal):
    book=authority.require(book_run_id)
    principal.require('book.authority.execute',book['project_id'])
    principal.require('chapter.authority.execute',book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request=authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number'] != book['accepted_through_chapter']+1:
        return False
    from novel_forge.modules.production_execution.codex_configuration import CODEX_SCHEMA_PROJECTION_VERSION, codex_wire_correction_evidence
    if CODEX_SCHEMA_PROJECTION_VERSION != "codex-structured-schema.v3":
        return False
    from novel_forge.modules.production_execution.execution_template import selected_template
    with AuthorityUnitOfWork(authority.database_url) as uow:
        admission=selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id'])
        template=selected_template(admission['policy_snapshot']['policy'],book['book_id']) if admission else None
        if not template or template.get('chapter_contract_recovery')!='KNOWN_SETTLED_CONTRACT_REPAIR':
            return False
        uow.cursor.execute("""SELECT o.operation_id,v.content FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_operation_output_asset oa USING(operation_id) JOIN authority_asset x USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
            JOIN authority_attempt a ON a.attempt_id=v.content->>'attempt_id' AND a.operation_id=o.operation_id
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.actor_id=%s AND o.definition_name='chapter.canon.extract'
            AND o.definition_version='3.9.5' AND o.status='FAILED_RETRYABLE' AND x.asset_type='model_call_log'
            AND oa.role='model_failure_evidence' AND a.result->>'error_code'='MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE'
            AND a.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=o.operation_id)
            AND a.attempt_number<(o.definition_snapshot #>> '{retry_policy,max_attempts}')::int""",[request['chapter_root_operation_id'],book['project_id'],principal.principal_id])
        row=uow.cursor.fetchone()
        if not row or not codex_wire_correction_evidence(row[1]['provider_evidence']['production_execution']['process_evidence']):
            return False
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url,root_id=request['chapter_root_operation_id'],
        predecessor_id=row[0],target_version='3.9.5',book_run_id=book_run_id,principal=principal,start_repair_phase=True)
    return True


def recover_canon_protocol_frontier(authority, *, book_run_id, principal):
    book=authority.require(book_run_id)
    principal.require('book.authority.execute',book['project_id'])
    principal.require('chapter.authority.execute',book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request=authority.require_chapter_request(book['active_chapter_request_id'])
    if request['chapter_number']!=book['accepted_through_chapter']+1:
        return False
    from novel_forge.modules.production_execution.execution_template import selected_template
    with AuthorityUnitOfWork(authority.database_url) as uow:
        template=selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id'])
        policy=selected_template(template['policy_snapshot']['policy'],book['book_id']) if template else None
        if not policy or policy.get('chapter_contract_recovery')!='KNOWN_SETTLED_CONTRACT_REPAIR':
            return False
        uow.cursor.execute("""SELECT to_jsonb(o),to_jsonb(a),v.asset_version_id,v.content_hash FROM authority_operation o
            JOIN authority_saga_step s USING(operation_id)
            JOIN LATERAL (SELECT * FROM authority_attempt WHERE operation_id=o.operation_id ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
            JOIN authority_operation_output_asset oa ON oa.operation_id=o.operation_id JOIN authority_asset x USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.canon.extract'
            AND o.definition_version IN ('3.9.5','3.9.6') AND o.status='FAILED_FINAL'
            AND a.result->>'error_code'='MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED' AND x.asset_type='model_call_log'
            AND v.content->>'attempt_id'=a.attempt_id AND v.content->>'failure_code'='PROVIDER_SCHEMA_REJECTED'
            AND v.content->'real_model_call'='false'::jsonb""",[request['chapter_root_operation_id'],book['project_id']])
        row=uow.cursor.fetchone()
        if not row:
            return False
        source,attempt,asset_id,asset_hash=row
        if source['actor_id']!=principal.principal_id:
            raise KernelError('CHAPTER_CANON_PROTOCOL_ACTOR_INVALID','Only the original actor can adopt a Schema successor')
        uow.cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.status,r.status,r.accounting_basis,r.evidence->>'cost_authorization_ref'
            FROM authority_external_effect e LEFT JOIN authority_budget_reservation r USING(external_effect_id)
            WHERE e.operation_id=%s ORDER BY e.external_effect_id""",[source['operation_id']])
        effects=uow.cursor.fetchall()
    evidence={'contract_version':'chapter-provider-schema-contract-repair.v1','book_run_id':book_run_id,
        'chapter_request_id':request['chapter_request_id'],'policy_admission':template,'input_snapshot':source['input_asset_snapshot'],
        'source_failure':attempt,'protocol_rejection_asset':{'asset_version_id':asset_id,'content_hash':asset_hash},
        'known_failed_effects':effects,'source_operation':source,'completion_checks':'UNCHANGED','accepted_cursor':book['accepted_through_chapter']}
    from novel_forge.modules.command_kernel.execution_window import continue_candidate_execution_window
    continue_candidate_execution_window(authority.database_url,root_id=request['chapter_root_operation_id'],
        predecessor_id=source['operation_id'],target_version='3.9.7',book_run_id=book_run_id,principal=principal)
    def guard(uow):
        uow.cursor.execute('SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s AND project_id=%s FOR UPDATE',[book_run_id,book['project_id']])
        if uow.cursor.fetchone()!=(book['version'],book['active_chapter_request_id'],book['accepted_through_chapter']) or selected_book_template(uow.cursor,project_id=book['project_id'],book_id=book['book_id'])!=template:
            raise KernelError('CHAPTER_CANON_PROTOCOL_CONFLICT','Reload the exact Book frontier')
    replace_failed_step(authority.database_url,predecessor_id=source['operation_id'],target_version='3.9.7',
        context=AdmissionContext(principal.principal_id,principal.permissions,authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,authority.commit_sha),policy_evidence=evidence,
        expected_failure_code='MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED',transaction_guard=guard)
    return True


def recover_quality_frontier(authority, *, book_run_id, principal):
    book=authority.require(book_run_id)
    if book.get('active_chapter_request_id'):
        request=authority.require_chapter_request(book['active_chapter_request_id'])
        from novel_forge.modules.canon_graph.validation_recovery import selected_validation_policy, canon_revalidation_evidence
        with AuthorityUnitOfWork(authority.database_url) as uow:
            if selected_validation_policy(uow.cursor,project_id=book['project_id'],root_operation_id=request['chapter_root_operation_id']):
                uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id) WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.update'",[request['chapter_root_operation_id']])
                row=uow.cursor.fetchone()
                if row and row[0]['definition_version']=='3.9.10':
                    return False
                if row and row[0]['status']=='SUCCEEDED':
                    try:
                        canon_revalidation_evidence(uow.cursor,row[0])
                        return False
                    except KernelError as error:
                        if error.code!='CANON_REVALIDATION_NOT_APPLICABLE':
                            raise
    changed=False
    for group in ('structural','commercial','source_originality','longform','platform'):
        changed=_recover_settled_output_frontier(authority,book_run_id=book_run_id,principal=principal,
            definition_name=f'chapter.quality.{group}.evaluate',target_version='3.9.9',contract_version='chapter-quality-contract-repair.v1',
            failure_codes=('QUALITY_APPLICABILITY_CONFLICT',),statuses=('DEAD_LETTER',)) or changed
    return changed
