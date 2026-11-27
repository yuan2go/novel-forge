from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError


def first_chapter_reference(uow, *, source, command, formation_run_id):
    frozen = source.get('command') or {}
    request = frozen.get('world_preparation_request') or {}
    if (frozen.get('generator_operation_name') != 'chapter_plan.generate'
            or frozen.get('execution_contract_version') != '1.21.0'
            or frozen.get('logical_key') != 'chapter:1' or frozen.get('repair_number') != 0
            or frozen.get('repair_of_operation_id') or frozen.get('opening_execution_binding')
            or request.get('accepted_through_chapter') != 0
            or not request.get('book_run_id') or not request.get('input_snapshot_id')):
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_MISSING', 'Require the exact unsent first Book Chapter planning boundary')
    uow.cursor.execute("""SELECT book.version,input.binding_id,input.binding_version,snapshot.snapshot_id,
        snapshot.snapshot_hash,parent.binding_id,parent.version,version.asset_version_id,version.content_hash,
        reference.continuation_id,reference.successor_operation_id,reference.target_runtime
        FROM authority_book_production book
        JOIN authority_story_formation_run formation ON formation.formation_run_id=%s
          AND book.stable_idempotency_key=formation.formation_run_id || ':production'
          AND formation.project_id=book.project_id AND formation.workspace_id=book.workspace_id AND formation.book_id=book.book_id
        JOIN authority_book_production_input_binding input ON input.book_run_id=book.book_run_id
          AND input.project_id=book.project_id AND input.book_id=book.book_id
        JOIN authority_book_production_input_snapshot snapshot ON snapshot.snapshot_id=input.snapshot_id
          AND snapshot.project_id=book.project_id AND snapshot.workspace_id=book.workspace_id AND snapshot.book_id=book.book_id
        JOIN active_story_plan_version active ON active.project_id=book.project_id AND active.book_id=book.book_id
        JOIN story_plan_binding parent ON parent.binding_id=active.binding_id AND parent.asset_version_id=active.asset_version_id
          AND parent.project_id=book.project_id AND parent.book_id=book.book_id AND parent.contract_type='CHAPTER_GROUP'
          AND parent.freshness='CURRENT'
        JOIN authority_asset_version version ON version.asset_version_id=parent.asset_version_id
        JOIN authority_story_planning_generation generation ON generation.candidate_asset_version_id=parent.asset_version_id
          AND generation.project_id=book.project_id AND generation.workspace_id=book.workspace_id AND generation.book_id=book.book_id
          AND generation.generator_operation_name='chapter_group_plan.generate' AND generation.status='ACTIVE'
        JOIN authority_story_planning_runtime_continuation reference ON reference.successor_operation_id=generation.operation_id
          AND reference.project_id=book.project_id AND reference.workspace_id=book.workspace_id AND reference.book_id=book.book_id
        JOIN authority_operation operation ON operation.operation_id=reference.successor_operation_id
          AND operation.status='SUCCEEDED' AND operation.actor_id=%s
        WHERE book.book_run_id=%s AND book.project_id=%s AND book.workspace_id=%s AND book.book_id=%s
          AND book.input_mode='RESOLVED_AUTHORITY_INPUT' AND book.state='CHAPTER_PLAN_REQUIRED'
          AND book.current_chapter=0 AND book.accepted_through_chapter=0 AND book.active_chapter_request_id IS NULL
          AND COALESCE(book.active_story_state_version_id,'')=%s AND COALESCE(book.active_canon_snapshot_version_id,'')=%s
          AND input.snapshot_id=%s AND NOT EXISTS(SELECT 1 FROM authority_book_production_input_binding newer
              WHERE newer.book_run_id=book.book_run_id AND newer.binding_version>input.binding_version)
          AND parent.asset_version_id=%s AND (version.content->'chapter_range'->>0)::integer<=1
          AND (version.content->'chapter_range'->>1)::integer>=1
          AND NOT EXISTS(SELECT 1 FROM authority_book_chapter_acceptance WHERE book_run_id=book.book_run_id)
          AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=formation.formation_run_id)
        FOR UPDATE OF book,input,parent,active""",[formation_run_id, command.actor_id,
            request['book_run_id'],command.project_id,command.workspace_id,command.book_id,
            request.get('story_state_version_id',''),request.get('canon_version_id',''),request['input_snapshot_id'],
            frozen.get('input_versions',{}).get('chapter_group_plan','')])
    rows=uow.cursor.fetchall()
    if len(rows)!=1:
        raise KernelError('PLANNING_UNSENT_DATABASE_BOOK_BOUNDARY_DRIFT', 'Require one locked current Book input and exact active parent Group at the original first Chapter boundary')
    row=rows[0]
    if row[11].get('pack_snapshot',{}).get('route_policy_hash')!=source['snapshot'].get('route_policy_hash'):
        raise KernelError('PLANNING_UNSENT_DATABASE_ROUTE_DRIFT', 'Parent and source must retain the same frozen planning route policy')
    scope=dict(book_run_id=request['book_run_id'],book_version_at_recovery=row[0],input_binding_id=row[1],
        input_binding_version=row[2],input_snapshot_id=row[3],input_snapshot_hash=row[4],parent_binding_id=row[5],
        parent_binding_version=row[6],parent_asset_version_id=row[7],parent_content_hash=row[8],
        accepted_through_chapter=0,current_chapter=0,scope_version='book-supervisor-first-chapter-query-recovery.v1')
    return (row[9],row[10],row[11]),scope
