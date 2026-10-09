from __future__ import annotations

from .errors import KernelError

CONTRACT = "chapter-unsent-context-transport.v1"


def require_unsent_context_transport(cursor, source, policy):
    if policy.get('contract_version') != CONTRACT:
        return False
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND result->>'error_code' IS DISTINCT FROM 'PROVIDER_ROUTING_BLOCKED'),
        EXISTS(SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset a USING(asset_id)
          JOIN authority_asset_version v USING(asset_version_id) WHERE output.operation_id=%s
          AND a.asset_type='capability_materialization_manifest'
          AND v.content #>> '{contract,pack_artifacts,prompt_template,version}'='v12'
          AND v.content #>> '{contract,tool_permissions,default}'='DENY'
          AND v.content #> '{contract,tool_permissions,allowed}'='["model.provider.invoke"]'::jsonb)""", [source['operation_id']] * 4)
    external, budget, other_failure, old_transport = cursor.fetchone()
    if external or budget or other_failure or not old_transport or source['definition_name'] not in {'chapter.draft.generate', 'chapter.revision.apply'} or source['definition_version'] != '3.10.0':
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Require a proven unsent current Chapter capacity failure with its original v12 transport')
    if source.get('status') == 'FAILED_RETRYABLE':
        from .execution_window import continued_attempt_limit
        limit = continued_attempt_limit(cursor, operation_id=source['operation_id'], project_id=source['project_id'],
            original_limit=int(source['definition_snapshot']['retry_policy']['max_attempts']))
        cursor.execute('SELECT count(*) FROM authority_attempt WHERE operation_id=%s', [source['operation_id']])
        if cursor.fetchone()[0] < limit:
            raise KernelError('CHAPTER_UNSENT_TRANSPORT_RETRY_REMAINS', 'Use the original remaining Attempt allowance before a formal transport successor')
    cursor.execute("""SELECT v.content FROM authority_operation_output_asset output JOIN authority_asset a USING(asset_id)
        JOIN authority_asset_version v USING(asset_version_id) WHERE output.operation_id=%s AND a.asset_type='routing_decision'""", [source['operation_id']])
    routes = [row[0] for row in cursor.fetchall()]
    if not routes or any(route.get('status') != 'BLOCKED' or not route.get('candidates') or
        any(set(item.get('rejected_reasons', [])) != {'CONTEXT_CAPACITY_EXCEEDED', 'BUDGET_HARD_LIMIT'} for item in route['candidates']) for route in routes):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_ROUTE_UNPROVEN', 'Every route must prove Context capacity failure without an authentication, permission or paid-budget failure')
    cursor.execute("""SELECT deployment.deployment_id FROM authority_capability_pack_activation activation
        JOIN authority_capability_pack_deployment deployment ON deployment.deployment_id=activation.active_deployment_id
        JOIN authority_capability_pack_compilation compilation USING(compilation_id)
        JOIN authority_capability_pack_version version ON version.pack_id=deployment.pack_id AND version.pack_version=deployment.pack_version
        JOIN authority_asset_version manifest ON manifest.asset_version_id=version.manifest_asset_version_id
        WHERE activation.project_id=%s AND activation.workspace_id=%s AND activation.book_id=%s
          AND activation.workflow_definition_ref='chapter_authority_slice@3.10.0'
          AND deployment.deployment_id=%s AND deployment.deployment_status='ACTIVE'
          AND compilation.release_sha=%s AND manifest.content #>> '{prompt_binding,template_version}'='v13'
          FOR SHARE OF activation,deployment""", [source['project_id'],source['workspace_id'],source['command_payload']['book_id'],policy.get('target_deployment_id'),policy.get('release_sha')])
    if cursor.fetchone() != (policy.get('target_deployment_id'),):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_TARGET_UNPROVEN', 'Require the exact active compiled v13 Pack for the same Book and release')
    cursor.execute("""WITH RECURSIVE ancestors(operation_id) AS (SELECT %s::text UNION
        SELECT edge.predecessor_operation_id FROM authority_saga_step_successor edge JOIN ancestors
          ON edge.successor_operation_id=ancestors.operation_id)
        SELECT count(*) FROM authority_saga_step_successor edge JOIN ancestors ON edge.successor_operation_id=ancestors.operation_id
          WHERE edge.policy_evidence->>'contract_version'=%s""", [source['operation_id'], CONTRACT])
    if cursor.fetchone()[0]:
        raise KernelError('GENERATION_ROUTE_RECOVERY_EXHAUSTED', 'The persisted logical task already used its exact Context transport correction')
    from novel_forge.modules.command_kernel.generation_isolation import require_generation_retry_budget
    require_generation_retry_budget(cursor, operation_id=source['operation_id'])
    return True

