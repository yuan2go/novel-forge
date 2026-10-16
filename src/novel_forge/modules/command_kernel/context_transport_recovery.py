from __future__ import annotations

from .errors import KernelError

CONTRACT = "chapter-unsent-context-transport.v1"


def require_unsent_context_transport(cursor, source, policy, *, execution_sha=None):
    if policy.get('contract_version') != CONTRACT:
        return False
    from novel_forge.modules.chapter_authority.capacity_continuation import require_capacity_upgrade_source
    if require_capacity_upgrade_source(cursor, source, policy, execution_sha):
        return True
    if policy.get('transport_projection') == 'selected-prose-input-role.v1':
        _require_changed_input_role_source(cursor, source, policy, execution_sha)
        return True
    accounting = policy.get('transport_projection') == 'provider-working-intent-accounting.v1'
    if accounting:
        _require_local_context_accounting_source(cursor, source, policy, execution_sha)
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
    if not accounting and (external or budget or other_failure or not old_transport or source['definition_name'] not in {'chapter.draft.generate', 'chapter.revision.apply'} or source['definition_version'] != '3.10.0'):
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
    if not accounting and (not routes or any(route.get('status') != 'BLOCKED' or not route.get('candidates') or
        any(set(item.get('rejected_reasons', [])) != {'CONTEXT_CAPACITY_EXCEEDED', 'BUDGET_HARD_LIMIT'} for item in route['candidates']) for route in routes)):
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
    from novel_forge.modules.command_kernel.generation_isolation import require_generation_retry_budget
    require_generation_retry_budget(cursor, operation_id=source['operation_id'])
    return True


def _require_changed_input_role_source(cursor, source, policy, execution_sha):
    from novel_forge.modules.chapter_authority.working_revision import CONTRACT as WORKING, ROOT_VERSION
    from .generation_policy import pure_generation_capabilities
    if (not execution_sha or policy.get('release_sha') != execution_sha
            or not source['definition_snapshot'].get('commit_sha')
            or source['definition_snapshot'].get('commit_sha') == execution_sha
            or policy.get('input_snapshot') != source['input_asset_snapshot']
            or policy.get('completion_checks') != 'UNCHANGED'
            or not pure_generation_capabilities(source['definition_snapshot'].get('external_capabilities', []))):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Require changed host role projection with unchanged pure-generation input and completion identities')
    cursor.execute("""SELECT definition_version,command_payload#>'{preparation_report,working_revision}'
        FROM authority_operation WHERE operation_id=%s AND project_id=%s""", [source['root_operation_id'], source['project_id']])
    row = cursor.fetchone()
    binding = (row[1] or {}) if row else {}
    if (not row or row[0] != ROOT_VERSION or binding.get('contract_version') != WORKING
            or binding.get('book_run_id') != policy.get('book_run_id')
            or binding.get('source_asset_version_id') != policy.get('source_asset_version_id')):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Bind the exact current working source rather than another input or Book')
    frozen_refs = {item['asset_version_id']: item['content_hash'] for item in source['input_asset_snapshot']}
    if frozen_refs.get(binding['source_asset_version_id']) != binding['source_content_hash']:
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Retain the original selected prose in this child input snapshot')
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)""", [source['operation_id']] * 3)
    if any(cursor.fetchone()):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Input role repair requires zero effects, reservations and output assets')
    cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source['operation_id']])
    failures = [row[0] for row in cursor.fetchall()]
    if not failures or set(failures) != {'CHAPTER_CAPABILITY_CONTEXT_INVALID'}:
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Retain the exact unsent input binding failure')
    for frozen in source['input_asset_snapshot']:
        cursor.execute('SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s', [frozen['asset_version_id']])
        if cursor.fetchone() != (frozen['content_hash'],):
            raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Every frozen input must remain hash identical')
    cursor.execute("""SELECT a.asset_type FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        WHERE a.project_id=%s AND v.asset_version_id=%s AND v.content_hash=%s""",
        [source['project_id'], binding['source_asset_version_id'], binding['source_content_hash']])
    if cursor.fetchone() not in [('draft_version',), ('best_draft_candidate',), ('author_edit_candidate',)]:
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Require a retained selected prose type needing the host Draft input role')
    cursor.execute("""SELECT d.deployment_id FROM authority_capability_pack_activation a
        JOIN authority_capability_pack_deployment d ON d.deployment_id=a.active_deployment_id
        JOIN authority_capability_pack_compilation c USING(compilation_id)
        WHERE a.project_id=%s AND a.workspace_id=%s AND a.book_id=%s
          AND a.workflow_definition_ref='chapter_authority_slice@3.10.0'
          AND d.deployment_id=%s AND d.deployment_status='ACTIVE' AND c.release_sha=%s""",
        [source['project_id'], source['workspace_id'], source['command_payload']['book_id'], policy.get('target_deployment_id'), execution_sha])
    if cursor.fetchone() != (policy.get('target_deployment_id'),):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_TARGET_UNPROVEN', 'Require the changed current same-Book compiled transport')


def _require_local_context_accounting_source(cursor, source, policy, execution_sha):
    if (source['definition_name'] != 'chapter.context.build' or source['definition_version'] != '3.10.0'
        or not execution_sha or policy.get('release_sha') != execution_sha
        or policy.get('input_snapshot') != source['input_asset_snapshot']
        or policy.get('completion_checks') != 'UNCHANGED'):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Bind the unchanged frozen local Context inputs to the current accounting correction')
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)""", [source['operation_id']] * 3)
    if any(cursor.fetchone()):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Local Context accounting recovery requires zero effects, reservations and output assets')
    cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source['operation_id']])
    failures = [row[0] for row in cursor.fetchall()]
    if not failures or any(code not in {'TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED', 'TASK_CONTEXT_COMPRESSION_NOT_AUTHORIZED'} for code in failures):
        raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Only unsent exact local accounting preflight failures may use this correction')
    for frozen in source['input_asset_snapshot']:
        cursor.execute('SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s', [frozen['asset_version_id']])
        if cursor.fetchone() != (frozen['content_hash'],):
            raise KernelError('CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE', 'Every original frozen input must remain hash identical')
