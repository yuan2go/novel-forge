from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    authorization_hash,
    load_bootstrap_authorization,
    validate_bootstrap_scope,
)
from novel_forge.modules.production_execution.routing_policy import (
    validate_routing_policy,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import policy_hash


def freeze_planning_bootstrap_authorization(
    *,
    database_url: str,
    command_payload: Mapping[str, Any],
    principal: Principal,
    environment: str,
) -> Mapping[str, Any]:
    return freeze_bootstrap_authorization(
        database_url=database_url, command_payload=command_payload,
        principal=principal, environment=environment,
        permission="story_planning.authority.execute",
        idempotency_scope="book:story-planning-generation",
    )


def freeze_bootstrap_authorization(
    *, database_url: str, command_payload: Mapping[str, Any], principal: Principal,
    environment: str, permission: str, idempotency_scope: str,
) -> Mapping[str, Any]:
    project_id = str(command_payload["project_id"])
    principal.require(permission, project_id)
    if environment != "validation":
        raise KernelError(
            "ROUTING_BOOTSTRAP_ENVIRONMENT_FORBIDDEN",
            "benchmark challengers require the validation runtime",
        )
    if command_payload.get("world_preparation_request"):
        raise KernelError(
            "ROUTING_BOOTSTRAP_MULTISTAGE_FORBIDDEN",
            "benchmark authorization covers one Planning generation stage",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT operation_id,command_payload->'payload' FROM authority_operation WHERE project_id=%s AND idempotency_scope=%s AND idempotency_key=%s",
            [project_id, idempotency_scope, command_payload["idempotency_key"]],
        )
        existing = uow.cursor.fetchone()
        if existing:
            if {
                key: value
                for key, value in existing[1].items()
                if key != "routing_bootstrap_authorization"
            } != dict(command_payload):
                raise KernelError(
                    "PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT",
                    "benchmark replay requires its original command",
                )
            snapshot = load_bootstrap_authorization(
                uow.cursor,
                project_id=project_id,
                operation_id=existing[0],
                check_expiry=False,
            )
            if snapshot is None:
                raise KernelError(
                    "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                    "benchmark replay lacks its original grant",
                )
            return snapshot
        if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise PermissionError(
                "only an authenticated operator can admit benchmark challengers"
            )
        uow.cursor.execute(
            """SELECT v.content,v.content_hash,v.actor_id,v.created_by_operation_id FROM authority_runtime_policy_selection s JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version) WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=%s""",
            [project_id],
        )
        row = uow.cursor.fetchone()
        if row is None or policy_hash(row[0]) != row[1]:
            raise KernelError(
                "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                "benchmark challenger requires a governed policy grant",
            )
        validate_routing_policy(row[0])
        grants = [
            grant
            for grant in row[0].get("bootstrap_authorizations", [])
            if grant["authorization_id"]
            == command_payload["routing_bootstrap_authorization_id"]
        ]
        if len(grants) != 1 or not row[3]:
            raise KernelError(
                "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                "benchmark challenger requires an audited policy grant",
            )
        snapshot = {
            "policy_version": row[0]["policy_version"],
            "policy_hash": row[1],
            "policy_actor_id": row[2],
            "policy_operation_id": row[3],
            "project_id": project_id,
            "environment": environment,
            "authorization": grants[0],
            "authorization_hash": authorization_hash(grants[0]),
        }
        validate_bootstrap_scope(snapshot, command_payload)
        return snapshot
