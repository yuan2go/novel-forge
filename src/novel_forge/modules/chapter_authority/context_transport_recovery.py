from __future__ import annotations

from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor_v2 import replace_failed_step
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from novel_forge.modules.command_kernel.context_transport_recovery import CONTRACT, require_unsent_context_transport


def recover_unsent_context_transport(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute', book['project_id'])
    principal.require('chapter.authority.execute', book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step step USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.status IN ('FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER')
            AND (o.status<>'FAILED_RETRYABLE' OR (SELECT count(*) FROM authority_attempt attempt WHERE attempt.operation_id=o.operation_id)>=(o.definition_snapshot #>> '{retry_policy,max_attempts}')::int)
            AND o.definition_version='3.10.0' AND o.definition_name IN ('chapter.draft.generate','chapter.revision.apply')
            AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=o.operation_id
              AND attempt.result->>'error_code'='PROVIDER_ROUTING_BLOCKED')
            AND NOT EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=o.operation_id
              AND attempt.result->>'error_code' IS DISTINCT FROM 'PROVIDER_ROUTING_BLOCKED')
            AND EXISTS(SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset a ON a.asset_id=output.asset_id
              JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id WHERE output.operation_id=o.operation_id
              AND a.asset_type='capability_materialization_manifest'
              AND v.content #>> '{contract,pack_artifacts,prompt_template,version}'='v12')
            AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor edge WHERE edge.predecessor_operation_id=o.operation_id)
            ORDER BY o.created_at LIMIT 1""", [request['chapter_root_operation_id'], book['project_id']])
        row = u.cursor.fetchone()
        if not row:
            return False
        source = row[0]
        u.cursor.execute("""SELECT deployment.deployment_id FROM authority_capability_pack_activation activation
            JOIN authority_capability_pack_deployment deployment ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_compilation compilation USING(compilation_id)
            WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
              AND activation.workflow_definition_ref='chapter_authority_slice@3.10.0'
              AND compilation.release_sha=%s AND deployment.deployment_status='ACTIVE'""",
            [book['project_id'],book['workspace_id'],book['book_id'],authority.commit_sha])
        deployments = u.cursor.fetchall()
        if len(deployments) != 1:
            return False
        policy = {'contract_version':CONTRACT,'book_run_id':book_run_id,'chapter_request_id':request['chapter_request_id'],
            'target_deployment_id':deployments[0][0],'release_sha':authority.commit_sha,'input_snapshot':source['input_asset_snapshot'],
            'transport_projection':'provider-context-exact-value-reference.v1','completion_checks':'UNCHANGED'}
        require_unsent_context_transport(u.cursor, source, policy)
    replace_failed_step(authority.database_url, predecessor_id=source['operation_id'],target_version='3.10.0',
        context=AdmissionContext(principal.principal_id,principal.permissions,authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,authority.commit_sha),policy_evidence=policy,expected_failure_code='PROVIDER_ROUTING_BLOCKED')
    return True
