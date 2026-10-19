from __future__ import annotations

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.generation_root_successor import replace_stopped_generation_root
from .definitions import book_followup_operation_definitions


def literal_citation_retry_feedback(request, *, source, payload):
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, _read_verified_success
    from .prose_review import CHAPTER_LITERAL_CITATION_CONTRACT, completion_digest, validate_window_report
    if (not request.database_url or not request.attempt_id or request.definition_name != 'longform.prose_review'
            or request.definition_version != '1.1.0'
            or source.content.get('policy', {}).get('citation_locator_contract') != CHAPTER_LITERAL_CITATION_CONTRACT):
        return {}
    rejected = KernelError('LONGFORM_PROSE_CITATION_REPAIR_UNSAFE',
        'Report correction requires the exact rejected literal report, settled verified receipt, same actor/window and released prior execution')
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute('''SELECT o.actor_id,o.workspace_id,o.input_asset_snapshot,o.definition_name,
            a.attempt_id,a.result,e.external_effect_id,e.request_hash,e.request_payload,e.status,
            EXISTS(SELECT 1 FROM authority_lease_acquisition l WHERE l.attempt_id=a.attempt_id AND l.status='HELD')
            OR EXISTS(SELECT 1 FROM authority_external_effect risk WHERE risk.operation_id=o.operation_id
                AND risk.status IN ('READY','DISPATCHING','DISPATCHED','UNKNOWN','FAILED_RETRYABLE','RECONCILIATION_REQUIRED','CANCELLATION_REQUESTED'))
            OR EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=o.operation_id)
            OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=o.operation_id)
            FROM authority_operation o JOIN authority_attempt a USING(operation_id)
            LEFT JOIN authority_external_effect e ON e.operation_id=o.operation_id AND e.effect_type='model.invoke'
                AND e.request_payload#>>'{_production_execution,attempt_id}'=a.attempt_id
                AND e.request_payload->>'stage'='longform_prose_review'
            WHERE o.operation_id=%s AND o.project_id=%s AND a.attempt_id<>%s AND a.status='FAILED_RETRYABLE'
              AND a.result->>'error_code'='LONGFORM_PROSE_CITATION_NOT_UNIQUE'
            ORDER BY a.attempt_number DESC''', [request.operation_id, request.project_id, request.attempt_id])
        rows = uow.cursor.fetchall()
        if not rows:
            return {}
        if len(rows) != 1:
            raise rejected
        actor, workspace, inputs, definition, attempt, failure, effect_id, request_hash, frozen, status, unsafe = rows[0]
        metadata = (frozen or {}).get('_production_execution', {})
        if (actor != request.actor_id or workspace != request.workspace_id or definition != 'longform.prose_review'
                or len(inputs) != 1 or any(inputs[0].get(key) != getattr(source, key) for key in ('asset_version_id', 'content_hash'))
                or completion_digest(source.content) != source.content_hash or status != 'SUCCEEDED' or unsafe
                or metadata.get('book_id') != request.command['payload'].get('book_id')
                or metadata.get('attempt_id') != attempt or metadata.get('operation_id') != request.operation_id
                or metadata.get('project_id') != request.project_id
                or frozen.get('input') != payload or completion_digest(frozen) != request_hash):
            raise rejected
        verified = _read_verified_success(uow, uow.repositories.external_effects,
            EffectCommandContext(request.operation_id, request.project_id, actor, request.trace_id, request.correlation_id),
            effect_id)
        if not verified or verified['budget_reservation_status'] != 'SETTLED':
            raise rejected
        raw = verified['provider_evidence'].get('result')
        if not isinstance(raw, dict):
            raise rejected
        try:
            validate_window_report(raw, manifest=source.content, window=source.content['window'])
        except KernelError as error:
            if error.code != failure['error_code']:
                raise rejected from error
        else:
            return {}
    return {'prose_citation_repair': {'contract_version': 'prose-citation-output-repair.v1',
        'source_attempt_id': attempt, 'source_effect_id': effect_id, 'source_request_hash': request_hash,
        'source_report_hash': completion_digest(raw), 'source_window_asset_version_id': source.asset_version_id,
        'source_window_content_hash': source.content_hash, 'diagnostic': failure, 'rejected_report': raw,
        'authority': 'REJECTED_MODEL_OBSERVATION_ONLY',
        'instruction': 'Correct this rejected report against the unchanged complete frozen prose window. '
            'Copy each quote exactly, including punctuation and internal line breaks; JSON must escape actual newlines. '
            'Do not combine separate passages, add a subject, paraphrase, guess coordinates or manufacture evidence. '
            'Keep supported observations and all required dimensions; reconsider unsupported claims explicitly. '
            'The prior report is untrusted model observation, not story evidence, author choice, Canon or permission to revise prose. '
            'Uncertain causes still require INVESTIGATE. All literal, identity and repair-scope gates remain unchanged.'}}


def recover_prose_review(coordinator, *, run_id, project_id, workspace_id, book_run_id, principal):
    from .prose_coordinator import load_review_run, load_review_sources
    principal.require('book.authority.execute', project_id)
    principal.require('book.followup:longform.prose_review', project_id)
    followup = coordinator.followup
    binder = getattr(getattr(followup,'prose_model_port',None), 'capability_binder', None)
    if binder is None:
        return []
    from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results
    with AuthorityUnitOfWork(coordinator.database_url) as uow:
        load_review_run(uow,run_id=run_id,project_id=project_id,workspace_id=workspace_id,book_run_id=book_run_id)
        uow.cursor.execute('SELECT book_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s',[book_run_id,project_id])
        book_id = uow.cursor.fetchone()[0]
        uow.cursor.execute("""SELECT operation.operation_id,operation.actor_id FROM authority_book_prose_review_event event
            JOIN authority_operation operation ON operation.operation_id=authority_generation_current_operation(event.content->>'operation_id')
            WHERE event.run_id=%s AND event.kind='WINDOW_ADMITTED' AND operation.project_id=%s
            AND (operation.status IN ('WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED') OR EXISTS(
                SELECT 1 FROM authority_external_effect effect
                LEFT JOIN authority_budget_reservation budget USING(external_effect_id)
                WHERE effect.operation_id=operation.operation_id AND effect.effect_type='model.invoke'
                  AND NOT authority_generation_isolated(effect.external_effect_id)
                  AND (effect.status IN ('DISPATCHING','DISPATCHED','UNKNOWN','RECONCILIATION_REQUIRED')
                    OR (effect.status='SUCCEEDED' AND budget.status IN ('RESERVED','HELD_UNKNOWN')))))""",[run_id,project_id])
        frozen_rows = uow.cursor.fetchall()
        if not frozen_rows:
            return []
        principal.require('external_effect.resolve', project_id)
        for _, actor_id in frozen_rows:
            principal.require_recovery_actor(actor_id)
        frozen_operations = tuple(row[0] for row in frozen_rows)
    if frozen_operations:
        for reconciliation_attempt in range(2):
            try:
                recover_saved_local_results(followup.prose_model_port.adapter,database_url=coordinator.database_url,
                    project_id=project_id,book_id=book_id,principal=principal,operation_ids=frozen_operations)
                break
            except KernelError as exc:
                if exc.code!='AUTHORITY_ASSET_VERSION_CONFLICT' or reconciliation_attempt:
                    raise
    from .application import BookFollowupAdmission
    for operation_id in frozen_operations:
        with AuthorityUnitOfWork(coordinator.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
        if state['status'] not in {'WAITING_EXTERNAL_RESULT', 'RECONCILIATION_REQUIRED'}:
            continue
        try:
            followup.run_or_recover(BookFollowupAdmission(operation_id, project_id, True))
        except KernelError as exc:
            if exc.code not in {'EXTERNAL_EFFECT_RECONCILIATION_REQUIRED', 'CONTENT_EXTERNAL_RECONCILIATION_REQUIRED'}:
                raise
    with AuthorityUnitOfWork(coordinator.database_url) as uow:
        load_review_run(uow,run_id=run_id,project_id=project_id,workspace_id=workspace_id,book_run_id=book_run_id)
        uow.cursor.execute("""SELECT authority_generation_current_operation(content->>'operation_id')
            FROM authority_book_prose_review_event WHERE run_id=%s AND kind='WINDOW_ADMITTED'
            AND EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=authority_generation_current_operation(content->>'operation_id')
              AND status IN ('UNKNOWN','RECONCILIATION_REQUIRED'))""", [run_id])
        ids = [row[0] for row in uow.cursor.fetchall()]
        if not ids:
            return []
        for definition in book_followup_operation_definitions(application_build_id=coordinator.application_build_id,commit_sha=coordinator.commit_sha):
            uow.repositories.definitions.register(definition)
        uow.commit()
    def guard(uow, source):
        locked = load_review_run(uow,run_id=run_id,project_id=project_id,workspace_id=workspace_id,book_run_id=book_run_id)
        uow.cursor.execute('SELECT kind FROM authority_book_prose_review_event WHERE run_id=%s AND kind IN (\'PAUSED\',\'RESUMED\') ORDER BY event_version DESC LIMIT 1', [run_id])
        control = uow.cursor.fetchone()
        if control and control[0]=='PAUSED':
            raise KernelError('LONGFORM_PROSE_PAUSED','Review cancellation remains authoritative')
        from .prose_review import freeze_manifest
        current = freeze_manifest(project_id=project_id,workspace_id=workspace_id,book_run_id=book_run_id,
            sources=load_review_sources(uow,book_run_id,project_id),policy=locked['manifest']['policy'],
            work_intent=locked['manifest']['schema_version'] in {'longform-prose-manifest.v2','longform-prose-manifest.v3'})['sources']
        if locked['manifest']['sources'] != current[:len(locked['manifest']['sources'])] or source['workspace_id'] != workspace_id:
            raise KernelError('LONGFORM_PROSE_SOURCE_STALE','The frozen manuscript or workspace changed')
        bindings = source['input_asset_snapshot']
        if len(bindings)!=1:
            raise KernelError('LONGFORM_PROSE_SCOPE_INVALID','Require one original frozen review window')
        document = uow.repositories.asset_documents.require(project_id=project_id,asset_version_id=bindings[0]['asset_version_id'])
        if (document.asset_type!='longform_prose_review_window' or document.content_hash!=bindings[0]['content_hash']
            or document.content.get('manifest_digest')!=locked['manifest_digest']
            or document.content.get('book_run_id')!=book_run_id):
            raise KernelError('LONGFORM_PROSE_SCOPE_INVALID','Original window identity must be retained')
    decisions = []
    for source_id in ids:
        with AuthorityUnitOfWork(coordinator.database_url) as uow:
            uow.cursor.execute("""SELECT status,trace_id,correlation_id FROM authority_operation WHERE operation_id=%s
                AND EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status IN ('UNKNOWN','RECONCILIATION_REQUIRED'))""", [source_id,source_id])
            row = uow.cursor.fetchone()
        if not row or row[0] not in {'WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED','FAILED_FINAL','DEAD_LETTER'}:
            continue
        decisions.append(replace_stopped_generation_root(coordinator.database_url,source_id=source_id,project_id=project_id,
            context=AdmissionContext(principal.principal_id,frozenset({'book.followup:longform.prose_review'}),followup.registry.available_handler_keys,
                coordinator.application_build_id,coordinator.commit_sha),scope_guard=guard))
    return decisions


def run_review_with_recovery(coordinator, operation_id, *, principal, scope):
    from .application import BookFollowupAdmission
    while True:
        try:
            coordinator.followup.run_or_recover(BookFollowupAdmission(operation_id,scope['project_id'],True))
            return
        except KernelError as exc:
            if not exc.code.startswith('MODEL_EFFECT_OUTCOME_UNKNOWN'):
                raise
            decisions = recover_prose_review(coordinator,principal=principal,**scope)
            if not decisions or any(item.get('recovery_state')=='EXHAUSTED' for item in decisions):
                return
            operation_id = decisions[0]['operation_id']


def reuse_known_literal_windows(coordinator, uow, *, run_id, manifest, operation_id, principal):
    from .prose_budget import frozen_prose_budget_scope
    from .prose_review import revalidate_legacy_citation_report, completion_digest, review_sources_current
    from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand

    if manifest["policy"].get("citation_locator_contract") != "literal-prose-citation.v1":
        return
    uow.cursor.execute("""SELECT to_jsonb(source),old.manifest,old.run_id,effect.external_effect_id,effect.request_hash,
            receipt.receipt_id,receipt.payload,old.exact_release_sha,effect.request_payload,event.content->>'operation_id'
        FROM authority_book_prose_review_run old
        JOIN authority_book_prose_review_event event ON event.run_id=old.run_id AND event.kind='WINDOW_ADMITTED'
        JOIN authority_operation source ON source.operation_id=authority_generation_current_operation(event.content->>'operation_id')
        JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
            AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
        JOIN authority_external_effect effect ON effect.operation_id=source.operation_id AND effect.effect_type='model.invoke' AND effect.status='SUCCEEDED'
        JOIN authority_external_effect_dispatch dispatch ON dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED'
        JOIN authority_external_receipt receipt ON receipt.dispatch_id=dispatch.dispatch_id AND receipt.status='VERIFIED'
        WHERE old.book_run_id=%s AND old.project_id=%s AND old.workspace_id=%s AND old.run_id<>%s
          AND source.definition_name='longform.prose_review' AND source.status='FAILED_FINAL' AND source.actor_id=%s
          AND attempt.status='FAILED_FINAL' AND attempt.result->>'error_code'='LONGFORM_PROSE_CITATION_INVALID'
          AND receipt.payload->'evidence'=dispatch.evidence
          AND NOT EXISTS(SELECT 1 FROM authority_external_effect other WHERE other.operation_id=source.operation_id AND other.external_effect_id<>effect.external_effect_id)
          AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt active USING(attempt_id) WHERE active.operation_id=source.operation_id AND lease.status='HELD')
          AND COALESCE((SELECT kind FROM authority_book_prose_review_event control WHERE control.run_id=old.run_id AND kind IN ('PAUSED','RESUMED') ORDER BY event_version DESC LIMIT 1),'RESUMED')<>'PAUSED'
        ORDER BY old.created_at DESC,receipt.received_at DESC""",
        [manifest['book_run_id'],manifest['project_id'],manifest['workspace_id'],run_id,principal.principal_id])
    rows = uow.cursor.fetchall()
    uow.cursor.execute('SELECT content->>\'window_id\' FROM authority_book_prose_review_event WHERE run_id=%s',[run_id])
    used = {row[0] for row in uow.cursor.fetchall()}
    for source, old_manifest, old_run, effect_id, request_hash, receipt_id, receipt, old_release, request_payload, admitted_operation_id in rows:
        if not review_sources_current(old_manifest['sources'],manifest['sources'],old_manifest['policy']):
            continue
        bindings = source['input_asset_snapshot']
        if len(bindings) != 1:
            continue
        frozen = uow.repositories.asset_documents.require(project_id=manifest['project_id'],asset_version_id=bindings[0]['asset_version_id'])
        content = frozen.content
        if (frozen.asset_type != 'longform_prose_review_window' or frozen.content_hash != bindings[0]['content_hash']
            or content.get('manifest_digest') != old_manifest['manifest_digest'] or content.get('book_run_id') != manifest['book_run_id']):
            continue
        old_window = content['window']
        window = next((item for item in manifest['windows'] if item['spans']==old_window['spans'] and item['window_id'] not in used),None)
        if window is None:
            continue
        raw = receipt.get('evidence',{}).get('result')
        if not isinstance(raw,dict):
            continue
        try:
            frozen_prose_budget_scope(uow.cursor, {'operation_id': source['operation_id'], 'source_operation_id': admitted_operation_id,
                'command_payload': source['command_payload'], 'request_payload': request_payload}, project_id=manifest['project_id'])
            resolved,proof = revalidate_legacy_citation_report(raw,source_manifest=old_manifest,source_window=old_window,
                target_manifest=manifest,target_window=window)
        except KernelError:
            continue
        proof.update(source_operation_id=source['operation_id'],source_run_id=old_run,source_release_sha=old_release,
            source_window_ref={'asset_version_id':frozen.asset_version_id,'content_hash':frozen.content_hash},
            source_effect_id=effect_id,source_request_hash=request_hash,source_receipt_id=receipt_id,
            source_receipt_hash=completion_digest(receipt),target_release_sha=coordinator.commit_sha,
            model_provider=receipt['evidence'].get('provider_id'),model_id=receipt['evidence'].get('model_id'),
            prompt_version=receipt['evidence'].get('prompt_version'),skill_version=receipt['evidence'].get('skill_version'))
        prefix=f'longform_prose/{run_id}/{window["window_id"][7:]}/citation_revalidation'
        def store(kind,key,value,policy):
            return uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(operation_id=operation_id,
                project_id=manifest['project_id'],asset_id=prefix+':'+kind,asset_type=kind,schema_version=value.get('schema_version', 'prose-citation-revalidation.v1'),
                logical_ref=prefix+'/'+kind,category='longform_prose_review',output_key=key,role='derived',content=value,
                qualification_policy=policy,trace_id=source['trace_id'],correlation_id=source['correlation_id'],reference_asset_ids=(frozen.asset_id,)))
        token=window['window_id']
        stored_proof=store('prose_citation_revalidation','longform.prose_review.citation_proof:'+token,proof,'prose-citation-revalidation.v1')
        stored_report=store('longform_prose_review_report','longform.prose_review.revalidated_report:'+token,resolved,'longform-prose-literal-review.v1')
        uow.cursor.execute('SELECT COALESCE(max(event_version),0)+1 FROM authority_book_prose_review_event WHERE run_id=%s',[run_id])
        version=uow.cursor.fetchone()[0]
        coordinator._event(uow,run_id,version,'WINDOW_REVALIDATED',{'contract_version':'prose-citation-revalidation.v1',
            'window_id':token,'operation_id':operation_id,'source_operation_id':source['operation_id'],
            'source_run_id':old_run,
            'report_asset_version_id':stored_report.asset_version_id,'proof_asset_version_id':stored_proof.asset_version_id},operation_id)
        used.add(token)
