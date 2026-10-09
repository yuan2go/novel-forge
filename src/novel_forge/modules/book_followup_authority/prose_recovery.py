from __future__ import annotations

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.generation_root_successor import replace_stopped_generation_root
from .definitions import book_followup_operation_definitions


def recover_prose_review(coordinator, *, run_id, project_id, workspace_id, book_run_id, principal):
    from .prose_coordinator import load_review_run, load_review_sources
    principal.require('book.authority.execute', project_id)
    principal.require('external_effect.resolve', project_id)
    principal.require('book.followup:longform.prose_review', project_id)
    followup = coordinator.followup
    binder = getattr(getattr(followup,'prose_model_port',None), 'capability_binder', None)
    if binder is None:
        return []
    if binder is not None:
        from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results
        with AuthorityUnitOfWork(coordinator.database_url) as uow:
            uow.cursor.execute('SELECT book_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s',[book_run_id,project_id])
            book_id = uow.cursor.fetchone()[0]
        recover_saved_local_results(followup.prose_model_port.adapter,
            database_url=coordinator.database_url,project_id=project_id,book_id=book_id,principal=principal)
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
        current = load_review_sources(uow,book_run_id,project_id)
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
