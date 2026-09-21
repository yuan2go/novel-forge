from __future__ import annotations

from dataclasses import fields
import hashlib
from typing import Any

from novel_forge.modules.chapter_authority.author_draft import freeze_author_adoption
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = 'book-author-replacement.v1'


def require_author_replacement_dispatch(database_url: str, *, command_payload: dict[str, Any], root_operation_id: str) -> None:
    report = command_payload.get('preparation_report') or {}
    if not isinstance(report,dict):
        raise KernelError('BOOK_AUTHOR_REPLACEMENT_INVALID', 'Preparation report must be an object')
    binding = report.get('author_book_replacement')
    if binding is None:
        return
    if (not isinstance(binding, dict) or set(binding) != {'contract_version','book_run_id','chapter_request_id','predecessor_request_id','predecessor_root_operation_id','generation'}
        or binding.get('contract_version') != CONTRACT or type(binding.get('generation')) is not int or binding['generation'] < 2
        or any(not isinstance(binding[key],str) or not binding[key] for key in ('book_run_id','chapter_request_id','predecessor_request_id','predecessor_root_operation_id'))):
        raise KernelError('BOOK_AUTHOR_REPLACEMENT_INVALID', 'Author replacement requires its exact frozen Book generation binding')
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute('''SELECT r.chapter_root_operation_id,b.active_chapter_request_id,d.superseded_at,
            r.generation,r.predecessor_request_id,b.accepted_through_chapter,r.chapter_number,r.command_payload,
            EXISTS(SELECT 1 FROM authority_book_chapter_acceptance a WHERE a.chapter_request_id=r.chapter_request_id AND a.status='COMMITTED'),
            (SELECT status FROM authority_operation WHERE operation_id=r.chapter_root_operation_id),d.delegation_id
            FROM authority_book_chapter_request r JOIN authority_book_production b USING(book_run_id)
            LEFT JOIN authority_child_delegation d USING(chapter_request_id)
            WHERE r.chapter_request_id=%s AND r.book_run_id=%s''', [binding.get('chapter_request_id'),binding.get('book_run_id')])
        row = uow.cursor.fetchone()
    exact = (row is not None and row[0] == root_operation_id and row[10] is not None
        and row[3] == binding['generation'] and row[4] == binding['predecessor_request_id']
        and binding == (row[7].get('preparation_report') or {}).get('author_book_replacement'))
    if exact and row[8] and row[9] == 'SUCCEEDED':
        return
    if not exact or row[1] != binding['chapter_request_id'] or row[2] is not None or row[5] >= row[6]:
        raise KernelError('BOOK_AUTHOR_REPLACEMENT_UNLINKED', 'Author replacement must be the current atomically linked unaccepted Book child before any execution')


def replace_author_chapter(authority, *, chapter_request_id: str, expected_book_version: int,
                           expected_root_operation_id: str, candidate_asset_version_id: str,
                           decision_asset_version_id: str, idempotency_key: str, principal) -> dict[str, Any]:
    previous = authority.require_chapter_request(chapter_request_id)
    book = authority.require(previous['book_run_id'])
    principal.require('book.authority.execute', book['project_id'])
    principal.require('chapter.authority.execute', book['project_id'])
    stable = 'book-author:' + hashlib.sha256(f"{chapter_request_id}:{decision_asset_version_id}".encode()).hexdigest()
    new_id = 'chapter-request:' + stable
    refs = authority.resolve_asset_refs(project_id=book['project_id'], asset_version_ids=(candidate_asset_version_id, decision_asset_version_id))

    def reserve(uow, operation_id, checkpoint):
        uow.cursor.execute('SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE', [book['book_run_id']])
        current = uow.cursor.fetchone()[0]
        uow.cursor.execute('SELECT to_jsonb(r) FROM authority_book_chapter_request r WHERE chapter_request_id=%s FOR UPDATE', [chapter_request_id])
        old = uow.cursor.fetchone()[0]
        if current['state'] not in {'CHAPTER_SUBMITTED','CHAPTER_RUNNING','CHAPTER_WAITING_RETRY',
            'CHAPTER_COMPLETED','CHAPTER_ACCEPTANCE_PENDING','CHAPTER_FAILED_RETRYABLE'}:
            raise KernelError('BOOK_AUTHOR_REPLACEMENT_STATE_BLOCKED', 'Book must be in an editable Chapter state; paused or terminal runs require their existing explicit control policy')
        if (current['version'] != expected_book_version or current['active_chapter_request_id'] != chapter_request_id
            or old['chapter_root_operation_id'] != expected_root_operation_id or current['accepted_through_chapter'] >= old['chapter_number']
            or old['chapter_number'] != current['accepted_through_chapter'] + 1):
            raise KernelError('BOOK_AUTHOR_REPLACEMENT_CONFLICT', 'Book cursor or exact predecessor changed; keep author input and reload')
        uow.cursor.execute('''SELECT status,command_payload FROM authority_operation WHERE operation_id=%s AND project_id=%s FOR SHARE''',
                           [expected_root_operation_id, book['project_id']])
        original = uow.cursor.fetchone()
        if original is None or original[0] not in {'SUCCEEDED','FAILED_FINAL','CANCELLED','DEAD_LETTER'}:
            raise KernelError('BOOK_AUTHOR_PREDECESSOR_NOT_SETTLED', 'Finish or explicitly cancel and reconcile the old Chapter before replacement')
        uow.cursor.execute('''SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
            WHERE o.root_operation_id=%s AND e.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED') LIMIT 1''', [expected_root_operation_id])
        if uow.cursor.fetchone() is not None:
            raise KernelError('BOOK_AUTHOR_EFFECT_RECONCILIATION_REQUIRED', 'Old external effects must be reconciled before replacement')
        adoption = freeze_author_adoption(authority.database_url, project_id=book['project_id'], workspace_id=book['workspace_id'],
            book_id=book['book_id'], chapter=previous['chapter_number'], candidate_asset_version_id=candidate_asset_version_id,
            decision_asset_version_id=decision_asset_version_id, principal=principal)
        uow.cursor.execute('''SELECT 1 FROM authority_operation_output_asset a JOIN authority_operation o USING(operation_id)
            WHERE a.asset_version_id=%s AND o.root_operation_id=%s''', [adoption['base_asset_version_id'], expected_root_operation_id])
        if uow.cursor.fetchone() is None:
            raise KernelError('BOOK_AUTHOR_SOURCE_SCOPE_CONFLICT', 'Candidate source must belong to the exact replaced Chapter run')
        binding = {'contract_version': CONTRACT, 'book_run_id': book['book_run_id'], 'chapter_request_id': new_id,
                   'predecessor_request_id': chapter_request_id, 'predecessor_root_operation_id': expected_root_operation_id,
                   'generation': old['generation'] + 1}
        frozen = dict(original[1])
        frozen.update(project_id=book['project_id'], workspace_id=book['workspace_id'], book_id=book['book_id'], actor_id=principal.principal_id,
            preparation_report={**dict(frozen.get('preparation_report') or {}), 'author_draft_adoption': adoption, 'author_book_replacement': binding},
            idempotency_key=stable, application_build_id=authority.application_build_id, commit_sha=authority.commit_sha,
            trace_id=f'{stable}:review', correlation_id=book['root_operation_id'])
        payload = {**old['command_payload'], 'preparation_report': frozen['preparation_report'], 'author_replacement_chapter_command': frozen}
        row = {**old, 'chapter_request_id': new_id, 'stable_idempotency_key': stable, 'command_payload': payload}
        uow.repositories.book_authority.create_chapter_request(row, generation=binding['generation'], predecessor_request_id=chapter_request_id)
        uow.cursor.execute('''UPDATE authority_child_delegation SET superseded_at=NOW(),version=version+1,updated_at=NOW()
            WHERE chapter_request_id=%s AND superseded_at IS NULL AND status<>'ACCEPTED' ''', [chapter_request_id])
        uow.cursor.execute('''UPDATE authority_book_production SET active_chapter_request_id=%s,active_child_delegation_id=NULL,
            state='CHAPTER_SUBMITTED',paused_reason='',failure_reason='',version=version+1,updated_at=NOW()
            WHERE book_run_id=%s AND version=%s''', [new_id,book['book_run_id'],expected_book_version])
        if uow.cursor.rowcount != 1:
            raise KernelError('BOOK_AUTHOR_REPLACEMENT_CONFLICT', 'Book replacement reservation changed')
        evidence = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
            operation_id=operation_id,project_id=book['project_id'],asset_id='author-replacement:'+operation_id,
            asset_type='author_chapter_replacement',schema_version=CONTRACT,logical_ref='author-replacements/'+operation_id,
            category='author-editor',output_key='book.author_replacement',role='completion_evidence',
            content={**binding,'adoption':adoption,'predecessor_request':old,'authority':'BOOK_UNACCEPTED_CHILD_REPLACEMENT','book_acceptance':'NOT_GRANTED'},
            qualification_policy=CONTRACT,trace_id=f'{stable}:reserve',correlation_id=book['root_operation_id']))
        checkpoint('after_author_replacement_reservation')
        return {'chapter_request_id':new_id,'replacement_evidence_version_id':evidence.asset_version_id,'generation':binding['generation']}

    authority._execute_mutation(book=book, action='author_chapter_replace', event_type='book.author_chapter.replacement_reserved',
        idempotency_key=idempotency_key,actor_id=principal.principal_id,trace_id=f'{stable}:reserve',correlation_id=book['root_operation_id'],
        causation_id=expected_root_operation_id,payload={'predecessor_request_id':chapter_request_id,'candidate_asset_version_id':candidate_asset_version_id,
        'decision_asset_version_id':decision_asset_version_id,'expected_book_version':expected_book_version,'expected_root_operation_id':expected_root_operation_id},
        handler=reserve,input_assets=refs)
    return resume_author_chapter_replacement(authority, chapter_request_id=new_id, principal=principal)


def resume_author_chapter_replacement(authority, *, chapter_request_id: str, principal) -> dict[str, Any]:
    request = authority.require_chapter_request(chapter_request_id)
    principal.require('book.authority.execute', request['project_id'])
    frozen = request['command_payload'].get('author_replacement_chapter_command')
    if not frozen:
        raise KernelError('BOOK_AUTHOR_REPLACEMENT_MISSING', 'No frozen author replacement request')
    if request['chapter_root_operation_id']:
        return request
    book = authority.require(request['book_run_id'])
    if book['active_chapter_request_id'] != chapter_request_id:
        raise KernelError('BOOK_AUTHOR_REPLACEMENT_CONFLICT', 'Replacement is no longer the active Book child')
    command = {item.name:frozen[item.name] for item in fields(SingleChapterRequest) if item.name in frozen}
    command['context_candidates'] = tuple(command.get('context_candidates') or ())
    command['actor_id'] = principal.principal_id
    admission = authority.chapter_port.submit(SingleChapterRequest(**command), principal=principal)
    authority._probe('after_author_replacement_admission')
    current = authority.require(request['book_run_id'])
    delegation_id = 'child-delegation:' + request['stable_idempotency_key']

    def link(uow, operation_id, checkpoint):
        uow.cursor.execute('SELECT active_chapter_request_id,version,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE',[request['book_run_id']])
        active = uow.cursor.fetchone()
        if active[0] != chapter_request_id or active[1] != current['version'] or active[2] >= request['chapter_number']:
            raise KernelError('BOOK_AUTHOR_REPLACEMENT_CONFLICT', 'Book changed before author replacement link')
        uow.repositories.book_authority.link_chapter(chapter_request_id=chapter_request_id,book_run_id=request['book_run_id'],project_id=request['project_id'],
            chapter_number=request['chapter_number'],chapter_plan_version=request['chapter_plan_version'],stable_idempotency_key=request['stable_idempotency_key'],
            delegation_id=delegation_id,root_operation_id=admission.root_operation_id,saga_id=admission.saga_id,expected_book_version=current['version'])
        from novel_forge.modules.chapter_group_authority.author_revision import replace_unaccepted_child_reference
        replace_unaccepted_child_reference(uow, request=request, root_operation_id=admission.root_operation_id, delegation_id=delegation_id)
        checkpoint('after_author_replacement_link')
        return {'chapter_request_id':chapter_request_id,'root_operation_id':admission.root_operation_id,'chapter_root_operation_id':admission.root_operation_id}

    authority._execute_mutation(book=current,action='author_chapter_replace_link',event_type='book.author_chapter.replacement_linked',
        idempotency_key=request['stable_idempotency_key']+':link',actor_id=principal.principal_id,trace_id=request['stable_idempotency_key']+':link',
        correlation_id=book['root_operation_id'],causation_id=admission.root_operation_id,payload={'chapter_request_id':chapter_request_id},handler=link)
    return authority.require_chapter_request(chapter_request_id)
