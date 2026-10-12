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
            authority.application_build_id,authority.commit_sha),policy_evidence=policy,expected_failure_code='PROVIDER_ROUTING_BLOCKED',
        window_successor={'contract_version':'kernel-unsent-transport-window.v1',
            'target_deployment_id':policy['target_deployment_id'],'release_sha':policy['release_sha']})
    return True

def require_optional_memory_transport(cursor, source, policy, target_version):
    if policy.get('contract_version') != 'chapter-optional-memory-transport.v1':
        return False
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.production_execution.codex_configuration import CODEX_SCHEMA_PROJECTION_VERSION
    if (CODEX_SCHEMA_PROJECTION_VERSION not in {'codex-structured-schema.v6', 'codex-structured-schema.v7'} or target_version != '3.10.0'
        or source['definition_name'] != 'chapter.draft.generate' or source['definition_version'] not in {'3.10.0', '3.10.2'}
        or policy.get('transport_projection') != 'codex-optional-working-memory.v1'
        or policy.get('input_snapshot') != source['input_asset_snapshot']):
        raise KernelError('CHAPTER_MEMORY_TRANSPORT_INVALID', 'Bind only the exact optional memory wire correction')
    cursor.execute("""SELECT d.deployment_id FROM authority_capability_pack_deployment d
        JOIN authority_capability_pack_compilation compilation USING(compilation_id)
        JOIN authority_capability_pack_activation activation ON activation.active_deployment_id=d.deployment_id
        WHERE d.deployment_id=%s AND d.deployment_status='ACTIVE' AND activation.project_id=%s
        AND activation.book_id=%s AND activation.workflow_definition_ref='chapter_authority_slice@3.10.0'
        AND compilation.release_sha=%s""", [policy.get('target_deployment_id'), source['project_id'], source['command_payload'].get('book_id'), policy.get('release_sha')])
    if not cursor.fetchone():
        raise KernelError('CHAPTER_MEMORY_TRANSPORT_INVALID', 'Require the exact active coordinated Pack')
    cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source['operation_id']])
    failures = [row[0] for row in cursor.fetchall()]
    if source['definition_version'] == '3.10.0':
        cursor.execute("SELECT request_payload #>> '{_production_execution,capability_runtime,output_schema_ref}',last_error #>> '{production_execution,process_evidence,provider_schema_contract,version}' FROM authority_external_effect WHERE operation_id=%s", [source['operation_id']])
        schemas = cursor.fetchall()
        if (not failures or any(code != 'MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED' for code in failures)
            or not schemas or any(row != ('schema:chapter-provider-output:draft:v4:working-memory-v1', 'codex-structured-schema.v5') for row in schemas)
            or len(policy.get('schema_rejection_receipts', [])) != len(schemas)):
            raise KernelError('CHAPTER_MEMORY_TRANSPORT_INVALID', 'Require exact settled optional memory Schema rejection')
    else:
        cursor.execute("SELECT policy_evidence->>'contract_version' FROM authority_saga_step_successor WHERE successor_operation_id=%s", [source['operation_id']])
        prior = cursor.fetchone()
        cursor.execute('SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)', [source['operation_id']])
        if (prior != ('chapter-optional-memory-transport.v1',) or cursor.fetchone()[0]
            or failures != ['CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED', 'CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT']):
            raise KernelError('CHAPTER_MEMORY_TRANSPORT_INVALID', 'Only the retained undispatched Pack preflight successor may continue')
    return True


def require_changed_schema_transport(cursor, source, policy, target_version, *, execution_sha):
    if policy.get("contract_version") != "chapter-provider-schema-transport.v1":
        return False
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel.generation_policy import pure_generation_capabilities
    from novel_forge.modules.production_execution.codex_configuration import CODEX_SCHEMA_PROJECTION_VERSION
    if (policy.get("transport_projection") != "codex-supported-patterns.v1"
            or policy.get("release_sha") != execution_sha or not execution_sha
            or policy.get("target_schema_projection") != CODEX_SCHEMA_PROJECTION_VERSION
            or policy.get("source_schema_projection") == CODEX_SCHEMA_PROJECTION_VERSION
            or policy.get("input_snapshot") != source["input_asset_snapshot"]
            or target_version != source["definition_version"]
            or not pure_generation_capabilities(source["definition_snapshot"].get("external_capabilities", []))
            or policy.get("domain_schema") != "UNCHANGED" or not policy.get("schema_rejection_receipts")):
        raise KernelError("CHAPTER_SCHEMA_TRANSPORT_INVALID", "Require an actual changed transport for the exact frozen pure-generation task")
    cursor.execute("""SELECT last_error #>> '{production_execution,process_evidence,provider_schema_contract,version}'
        FROM authority_external_effect WHERE operation_id=%s""", [source["operation_id"]])
    versions = [row[0] for row in cursor.fetchall()]
    if not versions or set(versions) != {policy.get("source_schema_projection")}:
        raise KernelError("CHAPTER_SCHEMA_TRANSPORT_INVALID", "Bind the original rejected wire projection without rewriting its receipt")
    cursor.execute("""SELECT d.deployment_id FROM authority_capability_pack_activation a
        JOIN authority_capability_pack_deployment d ON d.deployment_id=a.active_deployment_id
        JOIN authority_capability_pack_compilation c USING(compilation_id)
        WHERE a.project_id=%s AND a.workspace_id=%s AND a.book_id=%s
          AND a.workflow_definition_ref='chapter_authority_slice@3.10.0'
          AND d.deployment_id=%s AND d.deployment_status='ACTIVE' AND c.release_sha=%s""",
        [source["project_id"], source["workspace_id"], source["command_payload"]["book_id"],
         policy.get("target_deployment_id"), execution_sha])
    if cursor.fetchone() != (policy.get("target_deployment_id"),):
        raise KernelError("CHAPTER_SCHEMA_TRANSPORT_INVALID", "Require the current compiled transport within the same Book authorization")
    return True


def recover_schema_transport(authority, *, book_run_id, principal, root_operation_id=None):
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.production_execution.codex_configuration import CODEX_SCHEMA_PROJECTION_VERSION
    from .canon_contract_recovery import schema_rejection_receipts
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if root_operation_id is None:
        if not book.get("active_chapter_request_id"):
            return False
        root_operation_id = authority.require_chapter_request(book["active_chapter_request_id"])["chapter_root_operation_id"]
    with AuthorityUnitOfWork(authority.database_url) as uow:
        from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
        require_live_chapter_frontier(uow.cursor, root_id=root_operation_id, project_id=book["project_id"], book_run_id=book_run_id)
        uow.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step step USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.actor_id=%s AND o.status='FAILED_FINAL'
              AND EXISTS(SELECT 1 FROM authority_attempt attempt WHERE attempt.operation_id=o.operation_id
                AND attempt.result->>'error_code'='MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED')
              AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor edge WHERE edge.predecessor_operation_id=o.operation_id)""",
            [root_operation_id, book["project_id"], principal.principal_id])
        sources = [row[0] for row in uow.cursor.fetchall()]
        uow.cursor.execute("""SELECT d.deployment_id FROM authority_capability_pack_activation a
            JOIN authority_capability_pack_deployment d ON d.deployment_id=a.active_deployment_id
            JOIN authority_capability_pack_compilation c USING(compilation_id)
            WHERE a.project_id=%s AND a.workspace_id=%s AND a.book_id=%s
              AND a.workflow_definition_ref='chapter_authority_slice@3.10.0'
              AND c.release_sha=%s AND d.deployment_status='ACTIVE'""",
            [book["project_id"], book["workspace_id"], book["book_id"], authority.commit_sha])
        deployments = uow.cursor.fetchall()
    if sources and len(deployments) != 1:
        raise KernelError("CHAPTER_SCHEMA_TRANSPORT_INVALID", "Resolve the current same-Book deployment before continuation")
    changed = False
    for source in sources:
        with AuthorityUnitOfWork(authority.database_url) as uow:
            uow.cursor.execute("""SELECT DISTINCT last_error #>> '{production_execution,process_evidence,provider_schema_contract,version}'
                FROM authority_external_effect WHERE operation_id=%s""", [source["operation_id"]])
            versions = uow.cursor.fetchall()
        if len(versions) != 1 or not versions[0][0] or versions[0][0] == CODEX_SCHEMA_PROJECTION_VERSION:
            continue
        identities, proofs = schema_rejection_receipts(authority.database_url, source)
        policy = {"contract_version": "chapter-provider-schema-transport.v1", "transport_projection": "codex-supported-patterns.v1",
            "source_schema_projection": versions[0][0], "target_schema_projection": CODEX_SCHEMA_PROJECTION_VERSION,
            "input_snapshot": source["input_asset_snapshot"], "domain_schema": "UNCHANGED", "completion_checks": "UNCHANGED",
            "schema_rejection_receipts": proofs, "target_deployment_id": deployments[0][0], "release_sha": authority.commit_sha}
        replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version=source["definition_version"],
            context=AdmissionContext(principal.principal_id, principal.permissions,
                authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
            policy_evidence=policy, expected_failure_code="MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED", known_rejected_effects=identities)
        changed = True
    return changed


def recover_optional_memory_transport(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require('book.authority.execute', book['project_id'])
    principal.require('chapter.authority.execute', book['project_id'])
    if not book.get('active_chapter_request_id'):
        return False
    request = authority.require_chapter_request(book['active_chapter_request_id'])
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step step USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.draft.generate'
            AND o.definition_version IN ('3.10.0','3.10.2') AND o.status='FAILED_FINAL'
            AND EXISTS(SELECT 1 FROM authority_attempt a WHERE a.operation_id=o.operation_id
                AND a.result->>'error_code' IN ('MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED','CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT'))
            AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor edge WHERE edge.predecessor_operation_id=o.operation_id)""",
            [request['chapter_root_operation_id'], book['project_id']])
        rows = u.cursor.fetchall()
        if len(rows) != 1:
            return False
        source = rows[0][0]
        u.cursor.execute("""SELECT d.deployment_id FROM authority_capability_pack_activation a
            JOIN authority_capability_pack_deployment d ON d.deployment_id=a.active_deployment_id
            JOIN authority_capability_pack_compilation c USING(compilation_id)
            WHERE a.project_id=%s AND a.book_id=%s AND a.workflow_definition_ref='chapter_authority_slice@3.10.0'
            AND c.release_sha=%s AND d.deployment_status='ACTIVE'""", [book['project_id'],book['book_id'],authority.commit_sha])
        deployments = u.cursor.fetchall()
        if len(deployments) != 1:
            return False
    from .canon_contract_recovery import schema_rejection_receipts
    identities, proofs = schema_rejection_receipts(authority.database_url, source) if source['definition_version']=='3.10.0' else ((), [])
    evidence = {'contract_version': 'chapter-optional-memory-transport.v1', 'book_run_id': book_run_id,
        'chapter_request_id': request['chapter_request_id'], 'schema_rejection_receipts': proofs,
        'transport_projection': 'codex-optional-working-memory.v1', 'input_snapshot': source['input_asset_snapshot'],
        'target_deployment_id': deployments[0][0], 'release_sha': authority.commit_sha,
        'completion_checks': 'UNCHANGED', 'domain_schema': 'UNCHANGED'}
    def guard(u):
        u.cursor.execute('SELECT version,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE', [book_run_id])
        if u.cursor.fetchone() != (book['version'], book['active_chapter_request_id']):
            from novel_forge.modules.command_kernel.errors import KernelError
            raise KernelError('CHAPTER_MEMORY_TRANSPORT_FRONTIER_CHANGED', 'Reload the exact Book frontier')
    replace_failed_step(authority.database_url, predecessor_id=source['operation_id'], target_version='3.10.0',
        context=AdmissionContext(principal.principal_id, principal.permissions, authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id, authority.commit_sha), policy_evidence=evidence,
        expected_failure_code='MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED' if identities else 'CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT',
        known_rejected_effects=identities, transaction_guard=guard)
    return True
