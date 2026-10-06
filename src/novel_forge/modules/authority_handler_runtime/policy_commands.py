from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import (
    VersionedPolicyRepository,
    policy_hash,
)


DEFINITION_VERSION = "1.1.0"


def owned_policy_definition(
    *,
    owner: str,
    content: dict[str, Any],
    application_build_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    if not application_build_id or not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError("policy configuration requires exact implementation identity")
    name = {
        "CHAPTER_GROUP_EXECUTION": "chapter_group.execution_policy.configure",
        "READER_PROXY": "reader_proxy.policy.configure",
        "BOOK_CONTROL": "book.control_policy.configure",
        "CREATIVE_EXPERIMENT_BUDGET": "creative.experiment_budget.configure",
        "PROVIDER_ROUTING": "provider.routing_policy.configure",
    }[owner]
    handler_key = f"novel_forge.owned_policy.{name}"
    policy_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(content),
        "properties": {
            key: (
                {"type": "string", "minLength": 1}
                if key == "policy_version" or (owner == "BOOK_CONTROL" and key == "mode")
                else {"type": "integer", "minimum": 1}
                if key.endswith("_count")
                or key in {"maximum_chapters", "preferred_chapters"}
                else {"type": "number", "minimum": 0, "maximum": 1}
            )
            for key in content
        },
    }
    single_book_budget = False
    production_book_budget = False
    paired_samples_budget = False
    provider_campaign_budget = False
    campaign_monetary_amendment = False
    campaign_renewal = False
    campaign_reallocation = False
    execution_templates = owner == "PROVIDER_ROUTING" and "execution_templates" in content
    world_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10'}
        for value in content['execution_templates'])
    stage_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10'} for value in content['execution_templates'])
    contract_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10'} for value in content['execution_templates'])
    canon_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10'} for value in content['execution_templates'])
    graph_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10'} for value in content['execution_templates'])
    namespace_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10'} for value in content['execution_templates'])
    localization_templates = execution_templates and any(value.get('version') in {'creative-execution-template.v9','creative-execution-template.v10'} for value in content['execution_templates'])
    quality_templates = execution_templates and any(value.get('version') == 'creative-execution-template.v10' for value in content['execution_templates'])
    routing_sources = owner == "PROVIDER_ROUTING" and any(key in content for key in ("benchmark_exports", "benchmark_source_bindings", "author_supervised_authorizations", "author_supervised_books"))
    if owner == "PROVIDER_ROUTING":
        from novel_forge.modules.production_execution.routing_policy import POLICY_SCHEMA, LEGACY_POLICY_SCHEMA, AUTHOR_SUPERVISED_POLICY_SCHEMA
        policy_schema = AUTHOR_SUPERVISED_POLICY_SCHEMA if any(k in content for k in ("author_supervised_authorizations", "author_supervised_books")) else POLICY_SCHEMA if routing_sources or execution_templates else LEGACY_POLICY_SCHEMA
        if not quality_templates and 'execution_templates' in policy_schema['properties']:
            policy_schema = deepcopy(policy_schema)
            old_template = policy_schema['properties']['execution_templates']['items']
            old_template['properties'].pop('quality_corrections', None)
            old_template['$defs'].pop('QualityCorrectionConfiguration', None)
            old_template['properties']['version']['enum'] = ['creative-execution-template.v'+str(i) for i in range(1,10)]
        if not localization_templates and 'execution_templates' in policy_schema['properties']:
            policy_schema = deepcopy(policy_schema)
            old_template = policy_schema['properties']['execution_templates']['items']
            old_template['properties'].pop('canon_evidence_localization', None)
            old_template['properties']['version']['enum'] = ['creative-execution-template.v'+str(i) for i in range(1,9)]
            old_template['properties']['chapter_graph_recovery']['anyOf'][0]['enum'] = ['RETAIN_SETTLED_QUALITY_RANGE_RESULT', 'RETAIN_SETTLED_QUALITY_RESULT']
        if not namespace_templates and 'execution_templates' in policy_schema['properties']:
            policy_schema = deepcopy(policy_schema)
            old_template = policy_schema['properties']['execution_templates']['items']
            old_template['properties']['version']['enum'] = ['creative-execution-template.v'+str(i) for i in range(1,8)]
            recovery = old_template['properties']['chapter_graph_recovery']['anyOf'][0]
            recovery.pop('enum', None)
            recovery['const'] = 'RETAIN_SETTLED_QUALITY_RANGE_RESULT'
        if not graph_templates and 'execution_templates' in policy_schema['properties']:
            policy_schema = deepcopy(policy_schema)
            old_template = policy_schema['properties']['execution_templates']['items']
            old_template['properties'].pop('chapter_graph_recovery', None)
            old_template['properties']['version']['enum'] = ['creative-execution-template.v'+str(i) for i in range(1,7)]
        if not canon_templates and 'execution_templates' in policy_schema['properties']:
            policy_schema = deepcopy(policy_schema)
            old_template = policy_schema['properties']['execution_templates']['items']
            old_template['properties'].pop('canon_validation_contract', None)
            old_template['properties']['version']['enum'] = ['creative-execution-template.v1','creative-execution-template.v2','creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5']
        if not contract_templates and 'execution_templates' in policy_schema['properties']:
            policy_schema = deepcopy(policy_schema)
            old_template = policy_schema['properties']['execution_templates']['items']
            old_template['properties'].pop('chapter_contract_recovery', None)
            old_template['properties']['version']['enum'] = ['creative-execution-template.v1','creative-execution-template.v2','creative-execution-template.v3','creative-execution-template.v4']
        if execution_templates and not stage_templates:
            policy_schema = deepcopy(policy_schema)
            legacy = policy_schema['properties']['execution_templates']['items']
            legacy['properties']['version']['enum'] = ['creative-execution-template.v1','creative-execution-template.v2','creative-execution-template.v3']
            repair = legacy['$defs']['RepairRoutingConfiguration']['properties']['version']
            repair.pop('enum')
            repair['const'] = 'native-repair-routing.v1'
        if execution_templates and not world_templates:
            policy_schema = deepcopy(policy_schema)
            legacy = policy_schema['properties']['execution_templates']['items']
            legacy['properties']['version']['enum'] = ['creative-execution-template.v1', 'creative-execution-template.v2']
            legacy['properties'].pop('world_future_preparation')
    if owner == "CREATIVE_EXPERIMENT_BUDGET":
        from novel_forge.modules.command_kernel.creative_budget_contract import PROVIDER_REALLOCATION_VERSION, PROVIDER_REALLOCATION_POLICY_SCHEMA
        from novel_forge.modules.command_kernel.creative_budget_contract import PROVIDER_RENEWAL_VERSION, PROVIDER_RENEWAL_POLICY_SCHEMA, PAIRED_SAMPLES_VERSION, V5_POLICY_SCHEMA, PRODUCTION_BOOK_VERSION, SINGLE_BOOK_VERSION, PROVIDER_CAMPAIGN_VERSION, V1_POLICY_SCHEMA, V2_POLICY_SCHEMA, V3_POLICY_SCHEMA, V4_POLICY_SCHEMA
        single_book_budget = not content or content.get("comparison_budget", {}).get("contract_version") == SINGLE_BOOK_VERSION
        production_book_budget = content.get("comparison_budget", {}).get("contract_version") == PRODUCTION_BOOK_VERSION
        provider_campaign_budget = content.get("comparison_budget", {}).get("contract_version") == PROVIDER_CAMPAIGN_VERSION
        campaign_monetary_amendment = provider_campaign_budget and "previous_policy" in content["comparison_budget"]
        campaign_renewal = content.get("comparison_budget", {}).get("contract_version") == PROVIDER_RENEWAL_VERSION
        campaign_reallocation = content.get("comparison_budget", {}).get("contract_version") == PROVIDER_REALLOCATION_VERSION
        paired_samples_budget = content.get("comparison_budget", {}).get("contract_version") == PAIRED_SAMPLES_VERSION
        policy_schema = V5_POLICY_SCHEMA if paired_samples_budget else V4_POLICY_SCHEMA if provider_campaign_budget else V3_POLICY_SCHEMA if production_book_budget else V2_POLICY_SCHEMA if single_book_budget else V1_POLICY_SCHEMA
        if campaign_monetary_amendment:
            from novel_forge.modules.command_kernel.creative_budget_contract import V4_MONETARY_AMENDMENT_SCHEMA
            policy_schema = V4_MONETARY_AMENDMENT_SCHEMA
        if campaign_renewal:
            policy_schema = PROVIDER_RENEWAL_POLICY_SCHEMA
        if campaign_reallocation:
            policy_schema = PROVIDER_REALLOCATION_POLICY_SCHEMA
    result_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["owner", "policy", "policy_hash"],
        "properties": {
            "owner": {"const": owner},
            "policy": policy_schema,
            "policy_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    }
    command_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["project_id", "owner", "policy"],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "owner": {"const": owner},
            "policy": policy_schema,
        },
    }
    if owner == "PROVIDER_ROUTING" and any(k in content for k in ("author_supervised_authorizations", "author_supervised_books")):
        command_schema["properties"]["expected_policy_hash"] = {"type": "string"}
    return {
        "name": name,
        "definition_version": "1.15.0" if quality_templates else "1.14.0" if localization_templates else "1.13.0" if namespace_templates else "1.12.0" if graph_templates else "1.11.0" if canon_templates else "1.10.0" if contract_templates else "1.9.0" if stage_templates else "1.8.0" if world_templates else "1.7.0" if execution_templates else "1.7.0" if campaign_reallocation else "1.6.0" if campaign_renewal else "1.5.0" if owner == "PROVIDER_ROUTING" and any(k in content for k in ("author_supervised_authorizations", "author_supervised_books")) else "1.3.0" if routing_sources else "1.5.0" if paired_samples_budget else "1.4.1" if campaign_monetary_amendment else "1.4.0" if provider_campaign_budget else "1.3.0" if production_book_budget else "1.2.0" if single_book_budget or owner == "PROVIDER_ROUTING" else DEFINITION_VERSION,
        "family": owner.lower(),
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": f"{name}.command.v9" if stage_templates else f"{name}.command.v8" if world_templates else f"{name}.command.v7" if execution_templates else f"{name}.command.v7" if campaign_reallocation else f"{name}.command.v6" if campaign_renewal else f"{name}.command.v5" if owner == "PROVIDER_ROUTING" and any(k in content for k in ("author_supervised_authorizations", "author_supervised_books")) else f"{name}.command.v3" if production_book_budget or routing_sources else f"{name}.command.v2" if single_book_budget or owner == "PROVIDER_ROUTING" else f"{name}.command.v1",
        "result_schema_version": f"{name}.result.v9" if stage_templates else f"{name}.result.v8" if world_templates else f"{name}.result.v7" if execution_templates else f"{name}.result.v7" if campaign_reallocation else f"{name}.result.v6" if campaign_renewal else f"{name}.result.v5" if owner == "PROVIDER_ROUTING" and any(k in content for k in ("author_supervised_authorizations", "author_supervised_books")) else f"{name}.result.v3" if production_book_budget or routing_sources else f"{name}.result.v2" if single_book_budget or owner == "PROVIDER_ROUTING" else f"{name}.result.v1",
        "command_schema": command_schema,
        "result_schema": result_schema,
        "input_contract": command_schema,
        "output_contract": {"type": "VersionedPolicyDecision"},
        "handler_key": handler_key,
        "handler_contract_version": "owned-policy-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {"execution_classification": "transaction_command"},
        "idempotency_scope": f"project:{owner.lower()}:policy",
        "concurrency_key_template": f"project:{{project_id}}:{owner.lower()}:policy",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "frozen bindings retained",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": [owner.lower()],
        "migration_owner": owner.lower(),
        "completion_contract": {
            "version": "owned-policy-completion-v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [name],
        },
    }


def configure_owned_policy(
    *,
    database_url: str,
    owner: str,
    content: dict[str, Any],
    project_id: str,
    workspace_id: str,
    idempotency_key: str,
    trace_id: str,
    correlation_id: str,
    application_build_id: str,
    commit_sha: str,
    principal: Principal,
    fault_injector: TransactionCheckpoint | None = None,
    expected_policy_hash: str | None = None,
) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
    if owner == "PROVIDER_ROUTING":
        from novel_forge.modules.authority_security import PrincipalType
        from novel_forge.modules.production_execution.routing_policy import validate_routing_policy
        validate_routing_policy(content)
        from novel_forge.modules.production_execution.author_supervision import validate_grants
        validate_grants(content, author_id=principal.principal_id)
        if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise PermissionError("only an authenticated operator can change routing requirements")
        from novel_forge.modules.production_execution.routing_sources import require_source_permissions
        require_source_permissions(principal, project_id=project_id, content=content)
    if owner == "CREATIVE_EXPERIMENT_BUDGET":
        from novel_forge.modules.authority_security import PrincipalType
        from novel_forge.modules.command_kernel.creative_budget_contract import validate_policy
        validate_policy(content)
        if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise PermissionError("only an authenticated operator can grant experiment phase budgets")
    if owner == "BOOK_CONTROL":
        from novel_forge.modules.authority_security import PrincipalType
        from novel_forge.modules.book_authority.control_policy import ControlPolicy
        ControlPolicy(**content)
        if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise PermissionError("only an authenticated operator can change editorial ControlPolicy")
    definition = owned_policy_definition(
        owner=owner,
        content=content,
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )
    name, handler_key = definition["name"], definition["handler_key"]
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()

    def handler(
        uow: AuthorityUnitOfWork, operation_id: str, checkpoint: TransactionCheckpoint
    ) -> dict[str, Any]:
        if owner == "PROVIDER_ROUTING":
            uow.cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ["routing-policy:" + project_id])
            if expected_policy_hash is not None:
                uow.cursor.execute("""SELECT v.content_hash FROM authority_runtime_policy_selection s
                    JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
                    WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=%s FOR UPDATE OF s""", [project_id])
                previous = uow.cursor.fetchone()
                if (previous[0] if previous else "") != expected_policy_hash:
                    from novel_forge.modules.command_kernel.errors import KernelError
                    raise KernelError("ROUTING_POLICY_VERSION_CONFLICT", "Refresh the author policy before confirming another change")
            from novel_forge.modules.command_kernel.routing_bootstrap import validate_bootstrap_policy_in_uow
            validate_bootstrap_policy_in_uow(uow.cursor, project_id=project_id, content=content)
            from novel_forge.modules.production_execution.execution_template import validate_template_succession
            validate_template_succession(uow.cursor, project_id=project_id, content=content)
            from novel_forge.modules.production_execution.routing_sources import validate_sources_in_uow
            validate_sources_in_uow(uow.cursor, project_id=project_id, content=content)
        if owner == "CREATIVE_EXPERIMENT_BUDGET":
            from novel_forge.modules.command_kernel.creative_budget_runtime import validate_selection_in_uow
            validate_selection_in_uow(uow, project_id=project_id, content=content)
        VersionedPolicyRepository(
            uow.cursor, owner=owner, project_id=project_id
        ).select(content, actor_id=principal.principal_id, operation_id=operation_id)
        checkpoint("after_policy_selection")
        result = {
            "owner": owner,
            "policy": content,
            "policy_hash": policy_hash(content),
        }
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": owner.lower(),
                "aggregate_id": project_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": name,
                "correlation_id": correlation_id,
                "causation_id": operation_id,
                "payload": {"operation_id": operation_id, **result},
            }
        )
        return result

    return execute_transaction_command(
        database_url,
        {
            "definition_name": name,
            "definition_version": definition["definition_version"],
            "project_id": project_id,
            "workspace_id": workspace_id,
            "actor_id": principal.principal_id,
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "span_id": str(uuid4()),
            "correlation_id": correlation_id,
            "causation_id": "",
            "input": {"project_id": project_id, "owner": owner, "policy": content, **({"expected_policy_hash": expected_policy_hash} if expected_policy_hash is not None else {})},
            "input_assets": [],
        },
        context=AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"book.authority.execute"}),
            available_handlers=frozenset({handler_key}),
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        ),
        handler=handler,
        fault_injector=fault_injector,
    )
