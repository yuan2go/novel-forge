from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from .prose_budget import frozen_prose_budget_scope
from .prose_review import completion_digest, revalidate_legacy_citation_report


def require_revalidated_report(uow, *, run, event):
    content = event['content']
    rejected = KernelError('LONGFORM_PROSE_REVALIDATION_DRIFT', 'Derived reading evidence must retain its complete original model receipt and exact source window')
    if (content.get('contract_version') != 'prose-citation-revalidation.v1'
        or event['created_by_operation_id'] != content['operation_id']
        or run['created_by_operation_id'] != content['operation_id']):
        raise rejected
    proof_doc = uow.repositories.asset_documents.require(project_id=run['project_id'],asset_version_id=content['proof_asset_version_id'])
    report_doc = uow.repositories.asset_documents.require(project_id=run['project_id'],asset_version_id=content['report_asset_version_id'])
    proof = proof_doc.content
    if (proof_doc.asset_type != 'prose_citation_revalidation' or report_doc.asset_type != 'longform_prose_review_report'
        or proof.get('contract_version') != 'prose-citation-revalidation.v1' or proof.get('target_release_sha') != run['exact_release_sha']
        or proof.get('source_operation_id') != content['source_operation_id']):
        raise rejected
    for document in (proof_doc,report_doc):
        uow.cursor.execute('SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND asset_version_id=%s AND content_hash=%s',
            [content['operation_id'],document.asset_version_id,document.content_hash])
        if not uow.cursor.fetchone():
            raise rejected
    uow.cursor.execute("""SELECT to_jsonb(source),old.manifest,old.exact_release_sha,effect.request_hash,receipt.payload,
            owner.actor_id,owner.definition_name,owner.definition_version,owner.status,owner.command_payload,effect.request_payload,
            admitted.content->>'operation_id'
        FROM authority_operation source
        JOIN authority_book_prose_review_run old ON old.run_id=%s AND old.project_id=source.project_id AND old.workspace_id=source.workspace_id
        JOIN authority_book_prose_review_event admitted ON admitted.run_id=old.run_id AND admitted.kind='WINDOW_ADMITTED'
            AND authority_generation_current_operation(admitted.content->>'operation_id')=source.operation_id
        JOIN authority_attempt attempt ON attempt.operation_id=source.operation_id
            AND attempt.attempt_number=(SELECT max(attempt_number) FROM authority_attempt WHERE operation_id=source.operation_id)
        JOIN authority_external_effect effect ON effect.operation_id=source.operation_id AND effect.external_effect_id=%s
        JOIN authority_external_effect_dispatch dispatch ON dispatch.external_effect_id=effect.external_effect_id AND dispatch.status='SUCCEEDED'
        JOIN authority_external_receipt receipt ON receipt.dispatch_id=dispatch.dispatch_id AND receipt.receipt_id=%s AND receipt.status='VERIFIED'
        JOIN authority_operation owner ON owner.operation_id=%s AND owner.project_id=source.project_id AND owner.workspace_id=source.workspace_id
        WHERE source.operation_id=%s AND source.project_id=%s AND source.workspace_id=%s AND old.book_run_id=%s
          AND source.definition_name='longform.prose_review' AND source.status='FAILED_FINAL' AND attempt.status='FAILED_FINAL'
          AND attempt.result->>'error_code'='LONGFORM_PROSE_CITATION_INVALID'
          AND effect.status='SUCCEEDED' AND effect.effect_type='model.invoke' AND receipt.payload->'evidence'=dispatch.evidence
          AND NOT EXISTS(SELECT 1 FROM authority_external_effect other WHERE other.operation_id=source.operation_id AND other.external_effect_id<>effect.external_effect_id)
          AND NOT EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt active USING(attempt_id) WHERE active.operation_id=source.operation_id AND lease.status='HELD')""",
        [proof['source_run_id'],proof['source_effect_id'],proof['source_receipt_id'],content['operation_id'],content['source_operation_id'],
            run['project_id'],run['workspace_id'],run['book_run_id']])
    rows = uow.cursor.fetchall()
    if len(rows) != 1:
        raise rejected
    source,old_manifest,old_release,request_hash,receipt,actor,definition,version,status,owner_command,request_payload,admitted_operation_id = rows[0]
    owner_scope = owner_command.get('payload',owner_command)
    if (source['actor_id'] != actor or definition != 'book.prose_review.start' or status != 'SUCCEEDED'
        or any(owner_scope.get(key) != run[key] for key in ('project_id','workspace_id','book_run_id'))
        or request_hash != proof['source_request_hash'] or old_release != proof['source_release_sha']
        or completion_digest(receipt) != proof['source_receipt_hash']
        or uow.repositories.definitions.get_release(definition,version,commit_sha=run['exact_release_sha']) is None):
        raise rejected
    try:
        frozen_prose_budget_scope(uow.cursor, {'operation_id': source['operation_id'], 'source_operation_id': admitted_operation_id,
            'command_payload': source['command_payload'], 'request_payload': request_payload}, project_id=run['project_id'])
    except KernelError as exc:
        raise rejected from exc
    if any(proof.get(key) != receipt['evidence'].get(field) for key,field in
        (('model_provider','provider_id'),('model_id','model_id'),('prompt_version','prompt_version'),('skill_version','skill_version'))):
        raise rejected
    bindings = source['input_asset_snapshot']
    if len(bindings) != 1 or {key:bindings[0][key] for key in ('asset_version_id','content_hash')} != proof['source_window_ref']:
        raise rejected
    frozen = uow.repositories.asset_documents.require(project_id=run['project_id'],asset_version_id=bindings[0]['asset_version_id'])
    if (frozen.asset_type != 'longform_prose_review_window' or frozen.content_hash != bindings[0]['content_hash']
        or frozen.content['book_run_id'] != run['book_run_id'] or frozen.content['manifest_digest'] != old_manifest['manifest_digest']):
        raise rejected
    target = next((window for window in run['manifest']['windows'] if window['window_id']==content['window_id']),None)
    if target is None:
        raise rejected
    expected, rebuilt = revalidate_legacy_citation_report(receipt['evidence']['result'],source_manifest=old_manifest,
        source_window=frozen.content['window'],target_manifest=run['manifest'],target_window=target)
    if report_doc.content != expected or any(proof.get(key) != value for key,value in rebuilt.items()):
        raise rejected
    return expected
