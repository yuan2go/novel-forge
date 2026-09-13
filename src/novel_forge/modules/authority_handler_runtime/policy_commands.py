from __future__ import annotations

import re
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
    if owner == "CREATIVE_EXPERIMENT_BUDGET":
        from novel_forge.modules.command_kernel.creative_budget_contract import PRODUCTION_BOOK_VERSION, SINGLE_BOOK_VERSION, V1_POLICY_SCHEMA, V2_POLICY_SCHEMA, V3_POLICY_SCHEMA
        single_book_budget = not content or content.get("comparison_budget", {}).get("contract_version") == SINGLE_BOOK_VERSION
        production_book_budget = content.get("comparison_budget", {}).get("contract_version") == PRODUCTION_BOOK_VERSION
        policy_schema = V3_POLICY_SCHEMA if production_book_budget else V2_POLICY_SCHEMA if single_book_budget else V1_POLICY_SCHEMA
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
    return {
        "name": name,
        "definition_version": "1.3.0" if production_book_budget else "1.2.0" if single_book_budget else DEFINITION_VERSION,
        "family": owner.lower(),
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": f"{name}.command.v3" if production_book_budget else f"{name}.command.v2" if single_book_budget else f"{name}.command.v1",
        "result_schema_version": f"{name}.result.v3" if production_book_budget else f"{name}.result.v2" if single_book_budget else f"{name}.result.v1",
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
) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
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
            "input": {"project_id": project_id, "owner": owner, "policy": content},
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
