from __future__ import annotations

from dataclasses import asdict, replace

from novel_forge.modules.command_kernel.errors import KernelError

ROOT_VERSION = '3.10.0-working-regeneration.v1'
CONTRACT = 'working-plan-regeneration.v1'
BINDING = 'working_plan_regeneration'


def require_correction_scope(uow, *, book, chapter, proposal_id, plan_id, actor_id=None):
    if (chapter != book['current_chapter'] or chapter <= book['accepted_through_chapter']
            or book['state'] not in {'READY', 'PAUSED'} or book.get('active_chapter_request_id')):
        raise KernelError('MANUSCRIPT_REGENERATION_FRONTIER_INVALID', 'Correct only the idle delivered unaccepted frontier')
    uow.cursor.execute('''SELECT to_jsonb(proposal),plan.content_hash,binding.parent_version_id,
        delivery.chapter_request_id,request.chapter_root_operation_id,activation.actor_id
        FROM authority_plan_change_proposal proposal
        JOIN authority_operation activation ON activation.operation_id=proposal.activation_operation_id
        JOIN authority_book_manuscript_delivery delivery ON delivery.book_run_id=%s AND delivery.chapter_number=%s
        JOIN authority_book_chapter_request request USING(chapter_request_id)
        JOIN authority_operation original ON original.operation_id=request.chapter_root_operation_id
        JOIN authority_asset_version plan ON plan.asset_version_id=%s
        JOIN story_plan_binding binding ON binding.asset_version_id=plan.asset_version_id
            AND binding.project_id=proposal.project_id AND binding.book_id=proposal.book_id
        JOIN active_story_plan_version active ON active.binding_id=binding.binding_id
        WHERE proposal.proposal_id=%s AND proposal.project_id=%s AND proposal.book_id=%s
          AND proposal.status='ACTIVE' AND activation.status='SUCCEEDED'
          AND activation.project_id=proposal.project_id AND activation.workspace_id=%s
          AND activation.actor_id=original.actor_id AND original.status='SUCCEEDED'
          AND binding.contract_type='CHAPTER' AND binding.execution_scope='FROZEN' AND binding.freshness='CURRENT'
          AND (plan.content->>'chapter_number')::integer=%s AND request.chapter_plan_version<>plan.asset_version_id
          AND ((proposal.target_contract_type='CHAPTER' AND proposal.target_asset_version_id=request.chapter_plan_version
              AND proposal.proposed_asset_version_id=plan.asset_version_id)
            OR (proposal.target_contract_type='CHAPTER_GROUP' AND proposal.proposed_asset_version_id=binding.parent_version_id
              AND authority_working_group_prefix_preserved(proposal.project_id,proposal.book_id,proposal.proposed_asset_version_id,request.parent_group_version_id,activation.actor_id,activation.workspace_id,%s)))
          AND NOT EXISTS(SELECT 1 FROM authority_book_chapter_acceptance accepted
              WHERE accepted.book_run_id=delivery.book_run_id AND accepted.chapter_number=delivery.chapter_number AND accepted.status='COMMITTED')''',
        [book['book_run_id'], chapter, plan_id, proposal_id, book['project_id'], book['book_id'], book['workspace_id'], chapter, chapter])
    row = uow.cursor.fetchone()
    if not row or actor_id is not None and row[5] != actor_id:
        raise KernelError('MANUSCRIPT_REGENERATION_PLAN_INVALID', 'Bind the same actor and exact active PlanChange to its corrected Frozen Chapter and original delivery')
    proposal = row[0]
    return {'contract_version': CONTRACT, 'proposal_id': proposal_id,
        'activation_operation_id': proposal['activation_operation_id'],
        'target_plan_version_id': proposal['target_asset_version_id'],
        'proposed_plan_version_id': proposal['proposed_asset_version_id'],
        'corrected_chapter_plan_version_id': plan_id, 'corrected_chapter_plan_content_hash': row[1],
        'parent_group_version_id': row[2], 'predecessor_request_id': row[3],
        'predecessor_root_operation_id': row[4], 'actor_id': row[5]}


def require_frontier(uow, *, root, book):
    if root.get('status') in {'CANCELLED', 'CANCELLATION_REQUESTED', 'FAILED_FINAL', 'DEAD_LETTER'}:
        raise KernelError('MANUSCRIPT_REGENERATION_FRONTIER_INVALID', 'Stopped regeneration cannot retain execution or selection rights')
    proof = (root['command_payload'].get('preparation_report') or {}).get(BINDING) or {}
    actual = require_correction_scope(uow, book=book, chapter=root['command_payload']['chapter'],
        proposal_id=proof.get('proposal_id'), plan_id=proof.get('corrected_chapter_plan_version_id'), actor_id=root['actor_id'])
    if book['state'] != 'READY' or actual != proof:
        raise KernelError('MANUSCRIPT_REGENERATION_PLAN_INVALID', 'Retain the exact authorized correction and runnable Book checkpoint')


def prepare_regeneration(app, *, supervisor, uow, book, source, original, proposal_id, plan_id, principal):
    from novel_forge.modules.book_authority.chapter_dispatch import reserved_chapter_command
    from novel_forge.modules.book_authority.manuscript import freeze_working_context, effective_workflow

    proof = require_correction_scope(uow, book=book, chapter=original.chapter,
        proposal_id=proposal_id, plan_id=plan_id, actor_id=principal.principal_id)
    uow.cursor.execute('''SELECT EXISTS(SELECT 1 FROM authority_operation root
        WHERE root.command_payload#>>'{preparation_report,working_revision,book_run_id}'=%s
          AND root.command_payload#>>'{preparation_report,working_revision,source_asset_version_id}'=%s
          AND root.status NOT IN ('SUCCEEDED','CANCELLED','FAILED_FINAL','DEAD_LETTER')),
        EXISTS(SELECT 1 FROM authority_external_effect effect JOIN authority_operation op USING(operation_id)
          WHERE op.root_operation_id=%s AND NOT authority_generation_isolated(effect.external_effect_id)
            AND effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')),
        EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
          JOIN authority_operation op USING(operation_id) WHERE op.root_operation_id=%s AND lease.status='HELD'),
        EXISTS(SELECT 1 FROM authority_budget_reservation reservation JOIN authority_operation op USING(operation_id)
          WHERE op.root_operation_id=%s AND NOT authority_generation_isolated(reservation.external_effect_id)
            AND reservation.status NOT IN ('SETTLED','RELEASED','REJECTED'))''',
        [book['book_run_id'], source.asset_version_id, proof['predecessor_root_operation_id'], proof['predecessor_root_operation_id'], proof['predecessor_root_operation_id']])
    if any(uow.cursor.fetchone()):
        raise KernelError('MANUSCRIPT_REGENERATION_PREDECESSOR_UNSETTLED', 'Revoke unfinished revision rights and reconcile original effects before regeneration')
    group = supervisor._active_plan(book, 'CHAPTER_GROUP', original.chapter)
    plan = supervisor._active_plan(book, 'CHAPTER', original.chapter)
    if not group or not plan or group['asset_version_id'] != proof['parent_group_version_id'] or plan['asset_version_id'] != plan_id:
        raise KernelError('MANUSCRIPT_REGENERATION_PLAN_INVALID', 'The native current plan projection must match the exact correction')
    realization = supervisor.realizations.require_current_for_chapter(project_id=book['project_id'], book_id=book['book_id'],
        chapter_group_plan_version_id=group['asset_version_id'], chapter_number=original.chapter)
    book = {**book, 'author_workflow': effective_workflow(uow.cursor, book)}
    prepared = supervisor.prepare_chapter_command(book=book, group=group, chapter_plan=plan,
        realization=realization, chapter_number=original.chapter, working_regeneration_proposal_id=proposal_id)
    report = {**dict(prepared.preparation_report or {}), 'working_manuscript': freeze_working_context(uow, book, original.chapter)}
    prepared = replace(prepared, preparation_report=report)
    request = reserved_chapter_command(app.database_url, book=book,
        persisted={'command_payload': asdict(prepared), 'chapter_number': original.chapter, 'stable_idempotency_key': original.idempotency_key},
        actor_id=principal.principal_id, application_build_id=app.application_build_id, commit_sha=app.commit_sha)
    return request, proof


def admission_guard(uow, *, request, expected_version):
    from novel_forge.modules.book_authority.manuscript import selected_source
    from .working_revision import ROOT_VERSIONS
    report = request.preparation_report
    binding, proof = report['working_revision'], report.get(BINDING)
    uow.cursor.execute('SELECT to_jsonb(book) FROM authority_book_production book WHERE book_run_id=%s FOR UPDATE', [binding['book_run_id']])
    row = uow.cursor.fetchone()
    book = row[0] if row else None
    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_operation WHERE project_id=%s AND idempotency_scope='project:chapter-slice' AND idempotency_key=%s)",
        [request.project_id, request.idempotency_key])
    if uow.cursor.fetchone() == (True,):
        return
    if not book or book['version'] != expected_version or book['state'] != 'READY':
        raise KernelError('MANUSCRIPT_REGENERATION_FRONTIER_INVALID', 'Book changed before atomic regeneration admission')
    actual = require_correction_scope(uow, book=book, chapter=request.chapter, proposal_id=proof['proposal_id'],
        plan_id=proof['corrected_chapter_plan_version_id'], actor_id=request.actor_id) if proof else None
    current = selected_source(uow, book, request.chapter)
    if actual != proof or (current.asset_version_id, current.content_hash) != (binding['source_asset_version_id'], binding['source_content_hash']):
        raise KernelError('MANUSCRIPT_REGENERATION_FRONTIER_INVALID', 'Selected source or PlanChange changed before admission')
    uow.cursor.execute('''SELECT EXISTS(SELECT 1 FROM authority_operation root WHERE root.project_id=%s
        AND root.definition_name='chapter.slice.run' AND root.definition_version=ANY(%s)
        AND root.command_payload#>>'{preparation_report,working_revision,book_run_id}'=%s
        AND root.command_payload->>'chapter'=%s AND root.status NOT IN ('SUCCEEDED','FAILED_FINAL','DEAD_LETTER','CANCELLED'))''',
        [book['project_id'], list(ROOT_VERSIONS) if proof else [ROOT_VERSION], book['book_run_id'], str(request.chapter)])
    if uow.cursor.fetchone() != (False,):
        raise KernelError('MANUSCRIPT_REGENERATION_CONCURRENT', 'Reconcile the current regeneration instead of admitting another writer')
