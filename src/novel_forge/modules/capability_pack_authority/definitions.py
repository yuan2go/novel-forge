from __future__ import annotations

from typing import Any


CAPABILITY_PACK_DEFINITION_VERSION = "1.0.0"
CAPABILITY_PACK_ADMIN_HANDLER_KEY = "novel_forge.capability_pack_authority.admin"
CAPABILITY_PACK_COMPILER_VERSION = "novel-forge-capability-pack-compiler.v2"

CAPABILITY_PACK_AUTHORITY_OPERATIONS = (
    "capability_pack.manifest.register",
    "capability_pack.manifest.validate",
    "capability_pack.compile",
    "capability_pack.approval.decide",
    "capability_pack.deployment.create",
    "capability_pack.deployment.activate",
    "capability_pack.deployment.disable",
    "capability_pack.rollout.start",
    "capability_pack.rollout.pause",
    "capability_pack.rollout.resume",
    "capability_pack.rollout.complete",
    "capability_pack.rollback",
    "capability_pack.deprecate",
    "capability_pack.retire",
    "capability_pack.revoke",
)

_PERMISSIONS = {
    "capability_pack.manifest.register": "capability_pack.authority.register",
    "capability_pack.manifest.validate": "capability_pack.authority.register",
    "capability_pack.compile": "capability_pack.authority.compile",
    "capability_pack.approval.decide": "capability_pack.authority.approve",
    "capability_pack.deployment.create": "capability_pack.authority.deploy",
    "capability_pack.deployment.activate": "capability_pack.authority.activate",
    "capability_pack.deployment.disable": "capability_pack.authority.deploy",
    "capability_pack.rollout.start": "capability_pack.authority.deploy",
    "capability_pack.rollout.pause": "capability_pack.authority.deploy",
    "capability_pack.rollout.resume": "capability_pack.authority.deploy",
    "capability_pack.rollout.complete": "capability_pack.authority.deploy",
    "capability_pack.rollback": "capability_pack.authority.rollback",
    "capability_pack.deprecate": "capability_pack.authority.retire",
    "capability_pack.retire": "capability_pack.authority.retire",
    "capability_pack.revoke": "capability_pack.authority.retire",
}


def capability_pack_operation_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    if not application_build_id or len(commit_sha) != 40:
        raise ValueError(
            "Capability Pack Authority requires application_build_id and full commit SHA"
        )
    return tuple(
        _definition(
            name,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )
        for name in CAPABILITY_PACK_AUTHORITY_OPERATIONS
    )


def _definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    permission = _PERMISSIONS[name]
    result_schema = {"type": "object"}
    return {
        "name": name,
        "definition_version": CAPABILITY_PACK_DEFINITION_VERSION,
        "family": "capability_pack_authority",
        "enabled": True,
        "command_schema": _command_schema(),
        "result_schema": result_schema,
        "input_contract": _command_schema(),
        "output_contract": result_schema,
        "handler_key": CAPABILITY_PACK_ADMIN_HANDLER_KEY,
        "handler_contract_version": "1.0.0",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": [permission],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:capability-pack-authority",
        "concurrency_key_template": (
            "capability-pack:{pack_id}:{pack_version}:{environment}"
        ),
        "retry_policy": {"max_attempts": 1, "dead_letter_on_exhausted": False},
        "timeout_policy": {"operation_timeout_seconds": 60},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "append_only_pack_authority_and_cas_activation",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "definition_status": "enabled",
        "evidence_status": {
            "documented": True,
            "implemented": True,
            "handler_bound": True,
            "integration_proven": False,
            "real_provider_call_evidence_count": 0,
            "real_provider_call_evidence_present": False,
            "provider_vertical_qualification_status": "NOT_STARTED",
            "longform_proven": False,
            "production_verified": False,
        },
        "projection_consumers": [
            "capability_pack_query",
            "capability_pack_runtime_resolver",
        ],
        "migration_owner": "capability-pack-authority",
        "legacy_entrypoints": ["agent.chapter_binding.register:inline-compiled-pack"],
        "policy": {
            "execution_classification": "transaction_command",
            "authority": "postgresql",
            "pack_run_state": "forbidden",
            "attempt_owner": "command_kernel",
            "operation_definition_override": False,
            "compiler_transaction_boundary": "outside_write_transaction",
            "local_storage_writes": "forbidden",
        },
        "completion_contract": {
            "version": f"{name}.completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [f"authority.{name}.committed"],
        },
    }


def _command_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["pack_id", "payload"],
        "properties": {
            "pack_id": {"type": "string", "minLength": 1},
            "pack_version": {"type": "string"},
            "compilation_id": {"type": "string"},
            "deployment_id": {"type": "string"},
            "rollout_id": {"type": "string"},
            "expected_activation_version": {"type": "integer", "minimum": 0},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }


__all__ = [
    "CAPABILITY_PACK_ADMIN_HANDLER_KEY",
    "CAPABILITY_PACK_AUTHORITY_OPERATIONS",
    "CAPABILITY_PACK_COMPILER_VERSION",
    "CAPABILITY_PACK_DEFINITION_VERSION",
    "capability_pack_operation_definitions",
]
