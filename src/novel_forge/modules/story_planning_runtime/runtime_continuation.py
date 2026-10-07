from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .domain import StoryPlanningGenerationCommand, canonical_hash

DEFINITION_NAME = "story_planning.runtime_continuation.register"
HANDLER_KEY = "novel_forge.story_planning.runtime_continuation.register"
OUTPUT_KEY = "story_planning.runtime_continuation"


def runtime_continuation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": DEFINITION_NAME,
        "definition_version": "1.0.0",
        "family": "story_planning_runtime",
        "command_schema_version": "planning-runtime-continuation.command.v1",
        "result_schema_version": "planning-runtime-continuation.result.v1",
        "enabled": True,
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "asset_type": "planning_runtime_continuation",
            "output_key": OUTPUT_KEY,
        },
        "handler_key": HANDLER_KEY,
        "handler_contract_version": "planning-runtime-continuation.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["story_planning.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "trusted_operator_required": True,
            "zero_dispatch_required": True,
        },
        "idempotency_scope": "book:planning-runtime-continuation",
        "concurrency_key_template": "book:{book_id}:planning-runtime-continuation",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable_atomic"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable continuation registration",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["story_planning_runtime"],
        "migration_owner": "story-planning-runtime",
        "completion_contract": {
            "version": "planning-runtime-continuation-completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "planning_runtime_continuation",
                    "output_key": OUTPUT_KEY,
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [
                "story_planning.runtime_continuation.registered"
            ],
        },
    }


def require_source(
    uow: AuthorityUnitOfWork, *, source_operation_id: str, project_id: str
) -> dict[str, Any]:
    uow.cursor.execute(
        "SELECT op.status, op.version, op.workspace_id, op.command_payload->'payload', g.book_id, g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.operation_id=%s AND op.project_id=%s FOR UPDATE OF op",
        [source_operation_id, project_id],
    )
    row = uow.cursor.fetchone()
    if row and row[0]=='SUCCEEDED' and row[5]:
        return _planning_reference_contract_source(uow,source_operation_id=source_operation_id,row=row)
    if (
        row is None
        or row[0] not in {"CANCELLED", "FAILED_FINAL", "DEAD_LETTER"}
        or row[5]
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID",
            "source must be this project's cancelled generation with no Candidate",
        )
    frozen = dict(row[3])
    if (
        frozen.get("project_id"),
        frozen.get("workspace_id"),
        frozen.get("book_id"),
    ) != (project_id, str(row[2]), str(row[4])):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SCOPE_INVALID",
            "source command differs from its native Book scope",
        )
    uow.cursor.execute(
        "SELECT status, error, result FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1",
        [source_operation_id],
    )
    attempt = uow.cursor.fetchone()
    failure_code = (
        (
            dict(attempt[1] or {}).get("error_code")
            or dict(attempt[2] or {}).get("error_code")
        )
        if attempt
        else ""
    )
    if (
        row[0] == "FAILED_FINAL"
        and failure_code == "PROGRAMMING_BUG"
        and dict(attempt[2] or {}).get("error_message") == "'frozen_source'"
        and frozen.get("repair_reason") == "WORLD_HOST_REVALIDATION_SUCCESSOR"
    ):
        return _world_projection_source(
            uow, source_operation_id=source_operation_id, row=row, frozen=frozen
        )
    if row[0] in {"FAILED_FINAL", "DEAD_LETTER"} and failure_code == "PROVIDER_ROUTING_BLOCKED":
        return _arc_role_context_source(uow, source_operation_id=source_operation_id, row=row, frozen=frozen, attempt=attempt)
    if (
        row[0] in {"FAILED_FINAL", "DEAD_LETTER"}
        and failure_code == "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"
    ):
        return _pre_send_capacity_source(
            uow,
            source_operation_id=source_operation_id,
            row=row,
            frozen=frozen,
            attempt=attempt,
        )
    if (row[0] == "FAILED_FINAL" and failure_code == "PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID"
        and frozen.get("execution_contract_version") == "1.19.0"):
        return _recap_context_source(uow, source_operation_id=source_operation_id, row=row, frozen=frozen)
    if (
        row[0] in {"FAILED_FINAL", "DEAD_LETTER"}
        and failure_code == "WORLD_PREPARATION_RESULT_INVALID"
        and frozen.get("execution_contract_version") == "1.19.0"
    ):
        return _world_host_source(
            uow, source_operation_id=source_operation_id, row=row, frozen=frozen
        )
    if (
        row[0] in {"FAILED_FINAL", "DEAD_LETTER"}
        and failure_code == "WORLD_PREPARATION_RESULT_INVALID"
        and frozen.get("execution_contract_version") == "1.18.0"
    ):
        return _world_agency_source(
            uow, source_operation_id=source_operation_id, row=row, frozen=frozen
        )
    if row[0] != "CANCELLED":
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID",
            "Only the exact pre-send capacity failure permits a terminal source",
        )
    if (
        attempt is None
        or attempt[0] not in {"FAILED_RETRYABLE", "FAILED_FINAL"}
        or (
            dict(attempt[1] or {}).get("error_code")
            or dict(attempt[2] or {}).get("error_code")
        )
        != "EXECUTION_CONTRACT_FROZEN_CONFLICT"
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED",
            "only the retained frozen execution-contract failure permits runtime continuation",
        )
    uow.cursor.execute(
        "SELECT external_effect_id, status, provider, model_id, request_payload FROM authority_external_effect WHERE operation_id=%s AND project_id=%s ORDER BY external_effect_id FOR UPDATE",
        [source_operation_id, project_id],
    )
    effects = uow.cursor.fetchall()
    uow.cursor.execute(
        "SELECT count(*) FROM authority_external_effect_dispatch dispatch JOIN authority_external_effect effect USING(external_effect_id) WHERE effect.operation_id=%s AND effect.project_id=%s",
        [source_operation_id, project_id],
    )
    dispatched = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        "SELECT status FROM authority_budget_reservation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
        [source_operation_id, project_id],
    )
    reservations = uow.cursor.fetchall()
    if (
        not effects
        or any(effect[1] != "CANCELLED" for effect in effects)
        or dispatched
        or not reservations
        or any(reservation[0] != "RELEASED" for reservation in reservations)
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "continuation requires cancelled zero-dispatch Effects and released reservations",
        )
    if len(effects) != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_EFFECT_SCOPE_INVALID",
            "this bounded continuation supports one frozen Planning Provider intent",
        )
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot_row = uow.cursor.fetchone()
    if snapshot_row is None:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING",
            "the failed runtime must have retained its exact Pack snapshot",
        )
    snapshot = dict(snapshot_row[0])
    request = dict(effects[0][4])
    capability = dict(
        dict(request.get("_production_execution") or {}).get("capability_runtime") or {}
    )
    evidence_id = str(capability.get("provider_admission_asset_version_id") or "")
    uow.cursor.execute(
        "SELECT version.content_hash, asset.asset_type, version.content FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=%s AND output.asset_version_id=%s",
        [source_operation_id, evidence_id],
    )
    evidence = uow.cursor.fetchone()
    if (
        evidence is None
        or evidence[1] != "provider_request_admission_manifest"
        or str(evidence[0]) != capability.get("provider_admission_content_hash")
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_EVIDENCE_MISSING",
            "source must retain its exact native Provider admission evidence",
        )
    identity = dict(dict(evidence[2]).get("contract", evidence[2])).get(
        "provider_request_identity", {}
    )
    if (
        not isinstance(identity, Mapping)
        or not identity.get("provider")
        or identity.get("model") != str(effects[0][3])
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID",
            "native admission must identify the actual Provider model behind its gateway",
        )
    depth = 0
    if frozen.get("runtime_continuation_id"):
        uow.cursor.execute(
            "SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s",
            [frozen["runtime_continuation_id"], source_operation_id],
        )
        prior = uow.cursor.fetchone()
        if prior is None:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_LINEAGE_INVALID",
                "source continuation lineage is incomplete",
            )
        depth = int(prior[0])
    if depth >= 2:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED",
            "runtime continuation cannot exceed two successors",
        )
    return {
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": evidence_id,
        "evidence_hash": str(evidence[0]),
        "snapshot": snapshot,
        "provider": str(identity["provider"]),
        "model_id": str(effects[0][3]),
        "depth": depth + 1,
    }


def _recap_context_source(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from novel_forge.modules.story_planning_runtime.recap_sources import (
        require_arc_recap_change_evidence,
    )
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    command = _command_from_payload(frozen)
    if command.runtime_continuation_id:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED",
            "Recap Context contract correction may occur only once",
        )
    uow.cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state IN ('ABORTED','CANCELLED'))
        OR EXISTS(SELECT 1 FROM authority_story_formation_run formation JOIN authority_story_creation_cancellation cancel USING(formation_run_id)
                  WHERE formation.project_id=%s AND formation.book_id=%s)""",
        [
            source_operation_id,
            source_operation_id,
            command.project_id,
            command.book_id,
            command.project_id,
            command.book_id,
        ],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "Recap correction requires zero intents, zero reservations and a live original creation",
        )
    query = AuthorityAssetQuery(uow.database_url)
    proposals = [
        query.require(project_id=command.project_id, asset_version_id=item)
        for item in command.change_evidence_version_ids
    ]
    arcs = [item for item in proposals if item.asset_type == "arc_revision_candidate"]
    if len(arcs) != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID",
            "Failure must retain one exact native Arc Recap proposal",
        )
    evidence = arcs[0]
    require_arc_recap_change_evidence(
        uow.database_url, command, evidence.asset_version_id, dict(evidence.content)
    )
    uow.cursor.execute(
        "SELECT operation.definition_snapshot->>'commit_sha',generation.input_snapshot_hash FROM authority_operation operation JOIN authority_story_planning_generation generation USING(operation_id) WHERE operation.operation_id=%s",
        [source_operation_id],
    )
    release, input_hash = uow.cursor.fetchone()
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot = uow.cursor.fetchone()
    return {
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": evidence.asset_version_id,
        "evidence_hash": evidence.content_hash,
        "snapshot": dict(snapshot[0])
        if snapshot
        else {
            "release_sha": release,
            "pack_snapshot_status": "NOT_CREATED",
            "input_snapshot_hash": input_hash,
        },
        "depth": 1,
        "mode": "RECAP_CONTEXT_REVALIDATION",
    }


def _world_projection_source(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from .world_preparation import require_world_host_revalidation
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    command = _command_from_payload(frozen)
    uow.cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s) OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state='ABORTED')",
        [source_operation_id, source_operation_id, command.project_id, command.book_id],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "public projection recovery requires a zero-intent failed task and an uncancelled Book",
        )
    uow.cursor.execute(
        "SELECT chain_depth,target_runtime FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s",
        [source_operation_id],
    )
    prior = uow.cursor.fetchone()
    if not prior or prior[0] != 2 or not prior[1].get("world_host_revalidation"):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED",
            "public projection recovery applies once after the known-result revalidation",
        )
    retained = prior[1]["world_host_revalidation"]
    proof = require_world_host_revalidation(
        uow.database_url, command=command, operation_id=retained["source_operation_id"]
    )
    action = AuthorityAssetQuery(uow.database_url).require(
        project_id=command.project_id,
        logical_ref=f"world_preparation/{source_operation_id}/action",
    )
    if (
        proof != retained
        or action.content["contract"]["world_plan"]["plan_digest"]
        != proof["plan_digest"]
    ):
        raise KernelError(
            "WORLD_HOST_REVALIDATION_DRIFT",
            "public projection recovery must preserve the already validated immutable action",
        )
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING",
            "public projection recovery retains the failed task's Pack",
        )
    return {
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": action.asset_version_id,
        "evidence_hash": action.content_hash,
        "snapshot": dict(snapshot[0]),
        "depth": 3,
        "mode": "WORLD_HOST_PROJECTION",
        "world_host_revalidation": proof,
    }


def _world_host_source(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from .world_preparation import require_world_host_revalidation

    command = _command_from_payload(frozen)
    uow.cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state='ABORTED') OR EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status NOT IN ('SETTLED','RELEASED'))",
        [command.project_id, command.book_id, source_operation_id, source_operation_id],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "cancelled Book or unresolved original effects cannot acquire a known-result successor",
        )
    uow.cursor.execute(
        "SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s",
        [source_operation_id],
    )
    prior = uow.cursor.fetchone()
    if not prior or prior[0] != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED",
            "host revalidation permits one accounted successor after the original agency contract",
        )
    proof = require_world_host_revalidation(
        uow.database_url, command=command, operation_id=source_operation_id
    )
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING",
            "host revalidation requires the failed task's exact Pack snapshot",
        )
    return {
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": proof["generation"]["asset_version_id"],
        "evidence_hash": proof["generation"]["content_hash"],
        "snapshot": dict(snapshot[0]),
        "depth": 2,
        "mode": "WORLD_HOST_REVALIDATION",
        "world_host_revalidation": proof,
    }


def _world_agency_source(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from .result_recovery import require_result_repair_source
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    command = _command_from_payload(frozen)
    uow.cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state='ABORTED')",
        [command.project_id, command.book_id],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_CANCELLED",
            "cancelled Book cannot acquire an automatic contract successor",
        )
    if (
        command.generator_operation_name != "chapter_plan.generate"
        or not command.world_preparation_request
    ):
        raise KernelError(
            "PLANNING_WORLD_CONTRACT_SUCCESSOR_INVALID",
            "only the native Chapter Planning World contract is affected",
        )
    retained = require_result_repair_source(
        uow.database_url, command=command, operation_id=source_operation_id
    )
    query = AuthorityAssetQuery(uow.database_url)
    action = query.require(
        project_id=command.project_id,
        logical_ref=f"world_preparation/{source_operation_id}/action",
    )
    plan = action.content["contract"]["world_plan"]
    rejections = [
        entry.get("rejection", {}).get("code")
        for entry in [*plan["candidate_futures"], *plan["rejected_paths"]]
    ]
    if (
        "WORLD_CHARACTER_DECISION_BASIS_REQUIRED" not in rejections
        or plan["disposition"] != "BLOCKED"
    ):
        raise KernelError(
            "PLANNING_WORLD_CONTRACT_FAILURE_NOT_ALLOWED",
            "successor requires the reproduced blanket character-agency rejection",
        )
    generation = query.require(
        project_id=command.project_id, asset_version_id=retained["asset_version_id"]
    )
    world_source = query.require(
        project_id=command.project_id,
        asset_version_id=generation.content["contract"]["source"]["asset_version_id"],
    )
    if world_source.content["contract"].get("actor_experiment") or world_source.content[
        "contract"
    ]["reality"].get("epistemic_contract"):
        raise KernelError(
            "PLANNING_WORLD_CONTRACT_ALREADY_CURRENT",
            "isolated private-actor contracts and current agency contracts retain their own recovery",
        )
    uow.cursor.execute(
        "SELECT count(*) FROM authority_external_effect WHERE operation_id=%s AND status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')",
        [source_operation_id],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "reconcile every unknown or in-flight effect before contract succession",
        )
    uow.cursor.execute(
        "SELECT count(*) FROM authority_budget_reservation WHERE operation_id=%s AND status NOT IN ('SETTLED','RELEASED')",
        [source_operation_id],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BUDGET_UNSETTLED",
            "original usage remains accounted before successor admission",
        )
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING",
            "contract succession requires the original Pack snapshot",
        )
    return {
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": retained["asset_version_id"],
        "evidence_hash": retained["content_hash"],
        "snapshot": dict(snapshot[0]),
        "depth": 1,
        "mode": "WORLD_AGENCY_CONTRACT",
        "diagnostic": retained["diagnostic"],
        "source_world": generation.content["contract"]["source"],
    }


def _pre_send_capacity_source(
    uow: Any,
    *,
    source_operation_id: str,
    row: Any,
    frozen: dict[str, Any],
    attempt: Any,
    allow_frozen_context: bool = False,
) -> dict[str, Any]:
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    uow.cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)"
        + ("" if allow_frozen_context else " OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='planning.context_bundle')"),
        [source_operation_id] * (2 if allow_frozen_context else 3),
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "Capacity continuation requires no external intent, reservation or frozen Context",
        )
    uow.cursor.execute(
        "SELECT snapshot_payload,attempt_id,snapshot_id,snapshot_hash FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot = uow.cursor.fetchone()
    if snapshot is None:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING",
            "Capacity failure must retain its native Pack snapshot",
        )
    uow.cursor.execute(
        "SELECT input_snapshot FROM authority_story_planning_generation WHERE operation_id=%s",
        [source_operation_id],
    )
    inputs = uow.cursor.fetchone()[0]
    evidence_id = frozen.get("repair_of_candidate_id") or inputs[0]["asset_version_id"]
    evidence = AuthorityAssetQuery(uow.database_url).require(
        project_id=frozen["project_id"], asset_version_id=evidence_id
    )
    depth = 0
    if frozen.get("runtime_continuation_id"):
        uow.cursor.execute(
            "SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s",
            [frozen["runtime_continuation_id"], source_operation_id],
        )
        prior = uow.cursor.fetchone()
        if prior is None:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_LINEAGE_INVALID",
                "Capacity source lost its prior continuation",
            )
        depth = int(prior[0])
    if depth >= 2:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED",
            "Capacity continuation exhausted two successors",
        )
    return {
        "mode": "PRE_SEND_CAPACITY",
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": evidence_id,
        "evidence_hash": evidence.content_hash,
        "snapshot": snapshot[0],
        "attempt_id": snapshot[1],
        "snapshot_id": snapshot[2],
        "snapshot_hash": snapshot[3],
        "inputs": inputs,
        "failure": dict(attempt[2] or attempt[1] or {}),
        "depth": depth + 1,
    }


def _arc_role_context_source(uow, *, source_operation_id, row, frozen, attempt):
    from novel_forge.modules.chapter_authority.provider_views import (
        compile_planning_provider_context,
    )

    if frozen.get("generator_operation_name") not in {
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }:
        raise KernelError(
            "PLANNING_ARC_CONTEXT_SOURCE_INVALID",
            "Only near-term Planning may correct historical Arc role projection",
        )
    uow.cursor.execute(
        """SELECT version.asset_version_id,version.content_hash,version.content FROM authority_operation_output_asset output
        JOIN authority_asset_version version USING(asset_version_id)
        WHERE output.operation_id=%s AND output.output_key='planning.context_bundle'""",
        [source_operation_id],
    )
    context = uow.cursor.fetchone()
    if context is None:
        raise KernelError(
            "PLANNING_ARC_CONTEXT_SOURCE_INVALID",
            "The rejected request requires its exact frozen Context",
        )
    view, _ = compile_planning_provider_context(
        frozen["generator_operation_name"], context[2]
    )
    affected = [
        segment
        for segment in view.get("segments", [])
        if segment.get("role", "").startswith(("related_arc:", "dependent_arc:"))
        and segment.get("content", {}).get("generator_operation_name")
        == "arc_plan.generate"
        and "narrative_search_projection" in segment.get("content", {})
    ]
    if not affected:
        raise KernelError(
            "PLANNING_ARC_CONTEXT_SOURCE_INVALID",
            "Frozen Context must reproduce the untyped Arc Search projection",
        )
    uow.cursor.execute(
        """SELECT version.asset_version_id,version.content_hash,version.content FROM authority_operation_output_asset output
        JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id
        WHERE output.operation_id=%s AND asset.asset_type='routing_decision' ORDER BY version.created_at DESC LIMIT 1""",
        [source_operation_id],
    )
    decision = uow.cursor.fetchone()
    candidates = decision[2].get("candidates", []) if decision else []
    if (
        not decision
        or decision[2].get("status") != "BLOCKED"
        or decision[2].get("mode") != "CREATIVE_VALIDATION"
        or decision[2].get("task", {}).get("operation_id") != source_operation_id
        or not candidates
        or any(
            "CONTEXT_CAPACITY_EXCEEDED" not in candidate.get("rejected_reasons", [])
            or not set(candidate["rejected_reasons"])
            <= {"CONTEXT_CAPACITY_EXCEEDED", "BUDGET_HARD_LIMIT"}
            for candidate in candidates
        )
    ):
        raise KernelError(
            "PLANNING_ARC_CONTEXT_SOURCE_INVALID",
            "A different routing failure cannot borrow a Context-contract continuation",
        )
    source = _pre_send_capacity_source(
        uow,
        source_operation_id=source_operation_id,
        row=row,
        frozen=frozen,
        attempt=attempt,
        allow_frozen_context=True,
    )
    expected = {
        (item["role"], item["asset_version_id"], item["content_hash"])
        for item in source["inputs"]
    }
    actual = {
        (item["role"], item["asset_version_id"], item["content_hash"])
        for item in context[2]["input_versions"]
    }
    if not expected <= actual:
        raise KernelError(
            "PLANNING_ARC_CONTEXT_SOURCE_INVALID",
            "Context no longer binds all frozen semantic inputs",
        )
    return {
        **source,
        "mode": "ARC_ROLE_CONTEXT_REVALIDATION",
        "arc_context_proof": {
            "contract_version": "typed-arc-context-revalidation.v1",
            "context_asset_version_id": context[0],
            "context_content_hash": context[1],
            "routing_decision_asset_version_id": decision[0],
            "routing_decision_content_hash": decision[1],
            "affected_sources": [
                {
                    key: segment[key]
                    for key in ("role", "asset_version_id", "content_hash")
                }
                for segment in affected
            ],
        },
    }


def _capacity_authorization(
    uow: Any,
    *,
    source: dict[str, Any],
    successor: StoryPlanningGenerationCommand,
    principal: Principal,
    target: dict[str, Any],
) -> dict[str, Any]:
    from novel_forge.modules.production_execution.execution_template import (
        selected_book_template,
        selected_template,
    )
    from novel_forge.storage.story_formation_repositories import (
        StoryFormationRepository,
    )

    uow.cursor.execute(
        "SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s AND frozen_stage_inputs #>> '{generation_policy,contract_version}'='formation-generation.v5'",
        [successor.project_id, successor.book_id],
    )
    formations = uow.cursor.fetchall()
    if len(formations) != 1:
        raise KernelError(
            "PLANNING_CAPACITY_CONTINUATION_AUTHORIZATION_REQUIRED",
            "Capacity allocation requires one admitted continuous creation",
        )
    run = StoryFormationRepository(uow.cursor).require(formations[0][0])
    auth = run["frozen_input"]["generation_policy"]["auto_authorization"]
    template_binding = selected_book_template(
        uow.cursor, project_id=successor.project_id, book_id=successor.book_id
    )
    template = (
        selected_template(
            template_binding["policy_snapshot"]["policy"], successor.book_id
        )
        if template_binding
        else None
    )
    candidate = (
        f"{target['model_provider']}:{target['model_id']}:{target['reasoning_effort']}"
    )
    if (
        auth.get("authorized_by_principal_id") != principal.principal_id
        or successor.actor_id != principal.principal_id
        or run["workspace_id"] != successor.workspace_id
        or StoryFormationRepository(uow.cursor).cancellation(run["formation_run_id"])
        or not template
        or candidate not in template["allowed_candidates"]
        or target["cost_accounting_basis"] != "ACCOUNT_ENTITLEMENT"
        or target["account"].get("entitlement", {}).get("authorization_ref")
        != template["member_authorization_ref"]
    ):
        raise KernelError(
            "PLANNING_CAPACITY_CONTINUATION_AUTHORIZATION_REQUIRED",
            "Allocation must retain the original author, active membership authorization and allowed route",
        )
    if source.get("mode") in {"WORLD_AGENCY_CONTRACT","PLANNING_REFERENCE_CONTRACT"}:
        _require_world_agency_pack(
            uow, source=source, successor=successor, target=target
        )
    if any(
        source["snapshot"].get(key) != target["pack_snapshot"].get(key)
        for key in (
            *(
                ()
                if source.get("mode") in {"WORLD_AGENCY_CONTRACT","PLANNING_REFERENCE_CONTRACT"}
                else ("manifest_hash",)
            ),
            "route_policy_hash",
            "context_policy_hash",
            "prompt_bundle_hash",
            "skill_bundle_hash",
            "tool_policy_hash",
        )
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT",
            "Capacity allocation cannot replace the frozen Pack, prompt or model route",
        )
    return {
        "authorization_reference": auth["authorization_ref"],
        "formation_run_id": run["formation_run_id"],
        "account_evidence_source": "NATIVE_CONTINUOUS_CREATION_TEMPLATE",
        "template_policy_hash": template_binding["policy_snapshot"]["policy_hash"],
        "independent_human_review": "NOT_REVIEWED",
        "capacity_only": True,
    }


def _world_agency_pack_profile(version, operation_hash, *, source_version="1.18.0", target_version="1.19.0"):
    from novel_forge.modules.capability_packs.longform_profiles import (
        LongformCapabilityPackProfile,
    )

    manifest = deepcopy(version["manifest"])
    major, minor, _ = map(int, manifest["identity"]["version"].split("."))
    manifest["identity"]["version"] = f"{major}.{minor + 1}.0"
    nodes = manifest["workflow_template"]["nodes"]
    generation = (
        max(
            (
                int(node["agent_definition_ref"].rpartition("@")[2])
                for node in nodes
                if node.get("agent_definition_ref")
            ),
            default=0,
        )
        + 1
    )
    for node in nodes:
        if node["operation_definition_ref"] != f"story_planning.generate@{source_version}":
            raise KernelError(
                "PLANNING_WORLD_CONTRACT_PACK_INVALID",
                "source Pack must contain only the affected native Planning contract",
            )
        node["operation_definition_ref"] = f"story_planning.generate@{target_version}"
        node["operation_definition_hash"] = operation_hash
        if node.get("agent_definition_ref"):
            node["agent_definition_ref"] = (
                f"{node['agent_definition_ref'].rpartition('@')[0]}@{generation}"
            )
    workflow = manifest["workflow_template"]
    return LongformCapabilityPackProfile(
        pack_id=manifest["identity"]["pack_id"],
        workflow_ref=f"{workflow['workflow_id']}@{workflow['workflow_version']}",
        manifest=manifest,
        artifact_catalog=deepcopy(version["artifact_catalog"]),
        agent_skill_ref=manifest["skill_binding"]["skills"][0]["skill_ref"],
    ), generation


def _require_world_agency_pack(uow, *, source, successor, target):
    old = uow.repositories.capability_packs.require_version(
        source["snapshot"]["pack_id"], source["snapshot"]["pack_version"]
    )
    new = uow.repositories.capability_packs.require_version(
        target["pack_snapshot"]["pack_id"], target["pack_snapshot"]["pack_version"]
    )
    uow.cursor.execute(
        "SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s",
        ["story_planning.generate", successor.execution_contract_version],
    )
    definition = uow.cursor.fetchone()
    if not definition:
        raise KernelError(
            "PLANNING_WORLD_CONTRACT_PACK_INVALID",
            "successor definition must be registered",
        )
    expected, _ = _world_agency_pack_profile(old,str(definition[0]),**({'source_version':'1.19.0','target_version':'1.20.0'} if source.get('mode')=='PLANNING_REFERENCE_CONTRACT' else {}))
    if (
        new["manifest"] != expected.manifest
        or new["artifact_catalog"] != old["artifact_catalog"]
    ):
        raise KernelError(
            "PLANNING_WORLD_CONTRACT_PACK_DRIFT",
            "contract succession cannot change frozen content, policy or workflow semantics",
        )


def _ensure_world_agency_pack(application, source, original, successor, principal):
    from novel_forge.modules.capability_packs.validation_deployment import (
        install_longform_validation_pack,
    )
    from novel_forge.storage.authority_repositories import definition_hash
    from .application import story_planning_generation_definition

    try:
        existing = resolve_target(application, successor)
    except KernelError as error:
        if error.code != "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT":
            raise
    else:
        with AuthorityUnitOfWork(application.database_url) as uow:
            _capacity_authorization(
                uow,
                source=source,
                successor=successor,
                principal=principal,
                target=existing,
            )
        return
    old_target = resolve_target(application, original)
    with AuthorityUnitOfWork(application.database_url) as uow:
        _capacity_authorization(
            uow,
            source={**source, "mode": "PRE_SEND_CAPACITY"},
            successor=original,
            principal=principal,
            target=old_target,
        )
        version = uow.repositories.capability_packs.require_version(
            source["snapshot"]["pack_id"], source["snapshot"]["pack_version"]
        )
    definition = story_planning_generation_definition(
        application_build_id=application.application_build_id,
        commit_sha=application.commit_sha,
        definition_version=successor.execution_contract_version,
    )
    profile, generation = _world_agency_pack_profile(
        version, definition_hash(definition),**({'source_version':'1.19.0','target_version':'1.20.0'} if source.get('mode')=='PLANNING_REFERENCE_CONTRACT' else {})
    )
    resolver = application.execution_binder.resolver
    if resolver.environment != "validation":
        raise KernelError(
            "PLANNING_WORLD_CONTRACT_PACK_ADMISSION_REQUIRED",
            "this creation contract upgrade uses the existing validation template admission",
        )
    install_longform_validation_pack(
        application.database_url,
        profile=profile,
        pack_version=profile.manifest["identity"]["version"],
        agent_generation=generation,
        expected_activation_version=old_target["pack_snapshot"]["activation_version"],
        project_id=successor.project_id,
        workspace_id=successor.workspace_id,
        book_id=successor.book_id,
        application_build_id=application.application_build_id,
        commit_sha=application.commit_sha,
        compiler=principal,
        approver=principal,
        agent_admin=principal,
        agent_domain="story_planning",
        agent_scope_type="BOOK",
        runtime_environment=resolver.environment,
    )


def _capacity_target(
    application: Any,
    source: dict[str, Any],
    successor: StoryPlanningGenerationCommand,
    principal: Principal,
    target: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .domain import FrozenPlanningInput

    resolver = application.execution_binder.resolver
    preparer = resolver.execution_preparer
    with AuthorityUnitOfWork(application.database_url) as uow:
        authorization = _capacity_authorization(
            uow, source=source, successor=successor, principal=principal, target=target
        )
    snapshot = preparer.pack_runtime.require_attempt_snapshot(
        attempt_id=source["attempt_id"],
        snapshot_id=source["snapshot_id"],
        snapshot_hash=source["snapshot_hash"],
    )
    policy = preparer.pack_runtime.materialize_attempt_artifacts(
        snapshot
    ).context_policy.content
    baseline = policy["planning_task_token_budget"]
    if source["command"].get("runtime_continuation_id"):
        prior = require_binding(
            application.database_url, source["command"]["runtime_continuation_id"]
        )
        baseline = (
            prior["target_runtime"]
            .get("planning_capacity", {})
            .get("allocated_task_tokens", baseline)
        )
    route = preparer.planning_route
    ceiling = min(
        512_000,
        route.model_context_limit
        - route.model_output_limit
        - route.token_safety_margin
        - route.token_framing_overhead,
    )
    arc_context = source.get('mode') == 'ARC_ROLE_CONTEXT_REVALIDATION'
    allocated = min(baseline if arc_context else baseline * 2, ceiling)
    if allocated <= baseline and not arc_context:
        raise KernelError(
            "PLANNING_CAPACITY_ALLOCATION_EXHAUSTED",
            "No authorized single-request capacity remains",
        )
    try:
        context, _ = preparer._context_bundle(
            operation_id=source["source_operation_id"],
            attempt_id=source["attempt_id"],
            command=successor,
            inputs=tuple(FrozenPlanningInput(**value) for value in source["inputs"]),
            context_policy_ref=source["snapshot"]["context_policy_ref"],
            planning_task_token_budget=allocated,
            preflight_only=True,
        )
    except KernelError as exc:
        if (
            exc.code != "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"
            or allocated >= ceiling
        ):
            raise
        allocated = ceiling
        context, _ = preparer._context_bundle(
            operation_id=source["source_operation_id"],
            attempt_id=source["attempt_id"],
            command=successor,
            inputs=tuple(FrozenPlanningInput(**value) for value in source["inputs"]),
            context_policy_ref=source["snapshot"]["context_policy_ref"],
            planning_task_token_budget=allocated,
            preflight_only=True,
        )
    if arc_context:
        context = preparer._reproject_frozen_context(context.content, command=successor, task_tokens=allocated)
    allocation = {
        "version": "planning-capacity-allocation.v1",
        "prior_task_tokens": baseline,
        "allocated_task_tokens": allocated,
        "single_request_ceiling": ceiling,
        "projection_hash": canonical_hash(
            context["context_manifest"]["provider_context_view"]
        ),
        "source_failure": source["failure"],
        "external_intents_at_source": 0,
        **({'context_revalidation':source['arc_context_proof']} if arc_context else {}),
    }
    return {**target, "planning_capacity": allocation}, authorization


def resolve_target(
    application: Any, command: StoryPlanningGenerationCommand
) -> dict[str, Any]:
    from .binder import PostgresPlanningExecutionBundleResolver

    resolver = getattr(application.execution_binder, "resolver", None)
    if (
        not isinstance(resolver, PostgresPlanningExecutionBundleResolver)
        or resolver.release_sha != application.commit_sha
        or resolver.execution_preparer.planning_route.release_sha
        != application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RUNTIME_INVALID",
            "continuation requires the native resolver at the actual current release",
        )
    snapshot = resolver.pack_resolver.resolve_workflow_node(
        CapabilityPackResolutionRequest(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            workflow_definition_ref=resolver.workflow_definition_ref,
            workflow_node_id=command.generator_operation_name,
            environment=resolver.environment,
            runtime_profile=resolver.runtime_profile,
            release_channel=resolver.release_channel,
            release_sha=application.commit_sha,
            operation_definition_ref=f"story_planning.generate@{command.execution_contract_version}",
            pack_id=resolver.pack_id,
        )
    )
    model = resolver.execution_preparer.planning_route.model_profile
    account = {}
    if model.model_provider == "codex-cli":
        from novel_forge.modules.production_execution.codex_configuration import (
            codex_account_binding_evidence,
        )

        session = resolver.execution_preparer.execution_transport.session_for_project(
            command.project_id
        )
        backend = session.gateway.backends.resolve(model.backend_id)
        try:
            account = codex_account_binding_evidence(backend)
        except ValueError as error:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_REQUIRED",
                "Codex continuation requires the existing native account-entitlement backend",
            ) from error
    return {
        "pack_snapshot": snapshot.to_dict(),
        "model_provider": model.model_provider,
        "model_id": model.model_id,
        "reasoning_effort": model.reasoning_effort,
        "runtime_class": model.runtime_class.value,
        "model_backend_id": model.backend_id,
        "auth_profile_ref": resolver.execution_preparer.planning_route.auth_profile_ref,
        "cost_accounting_basis": resolver.execution_preparer.cost_accounting_basis,
        "account": account,
    }


def require_route_evidence(
    uow: AuthorityUnitOfWork,
    *,
    source: dict[str, Any],
    target: dict[str, Any],
    authorized_reasoning_effort: str,
) -> dict[str, Any]:
    if (
        authorized_reasoning_effort not in {"low", "medium", "high", "xhigh"}
        or target["reasoning_effort"] != authorized_reasoning_effort
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_REASONING_UNAUTHORIZED",
            "the current explicit author decision must match the actual Planning reasoning effort",
        )
    decision = {
        "reasoning_evidence_source": "CURRENT_USER_DECISION",
        "authorized_reasoning_effort": authorized_reasoning_effort,
    }
    if (
        source["provider"] == "scripted_provider_v2"
        and target["runtime_class"] == "SCRIPTED_FIXTURE"
    ):
        return {**decision, "account_evidence_source": "SCRIPTED_FIXTURE_ONLY"}
    command = source["command"]
    if command.get("runtime_continuation_id"):
        uow.cursor.execute(
            "SELECT target_runtime FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s",
            [command["runtime_continuation_id"], source["source_operation_id"]],
        )
        previous = uow.cursor.fetchone()
        if previous is None:
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_LINEAGE_INVALID",
                "source has no prior frozen runtime approval",
            )
        prior = dict(previous[0])
        compared = (
            "model_provider",
            "model_id",
            "reasoning_effort",
            "runtime_class",
            "model_backend_id",
            "cost_accounting_basis",
        )

        def stable_account(runtime):
            account = dict(runtime.get("account") or {})
            account["entitlement"] = {
                key: value
                for key, value in dict(account.get("entitlement") or {}).items()
                if key != "authorization_ref"
            }
            return account

        if any(prior.get(key) != target.get(key) for key in compared) or stable_account(
            prior
        ) != stable_account(target):
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
                "a subsequent continuation must retain the prior registered account, backend and reasoning",
            )
        return {
            **decision,
            "account_evidence_source": "PRIOR_REGISTERED_RUNTIME",
            "source_runtime_hash": canonical_hash(prior),
            "authorization_reference_change": "NATIVE_BUDGET_SUCCESSOR_ALLOWED",
        }
    uow.cursor.execute(
        "SELECT runtime_policy FROM authority_book WHERE project_id=%s AND workspace_id=%s AND book_id=%s",
        [command["project_id"], command["workspace_id"], command["book_id"]],
    )
    row = uow.cursor.fetchone()
    frozen = dict(row[0] or {}).get("creation_pilot") if row else None
    if (
        not isinstance(frozen, Mapping)
        or not isinstance(frozen.get("models"), Mapping)
        or not frozen["models"]
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_REQUIRED",
            "this bounded continuation requires the original native Book model and account policy",
        )
    routes = list(frozen["models"].values())
    if any(
        not isinstance(route, Mapping)
        or not isinstance(route.get("model_profile"), Mapping)
        for route in routes
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_INVALID",
            "Book model policy must contain typed frozen route objects",
        )
    expected = {
        (
            str(route["model_profile"].get("backend_id") or ""),
            str(route["model_profile"].get("runtime_class") or ""),
            str(route.get("auth_profile_ref") or ""),
        )
        for route in routes
    }
    if len(expected) != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_INVALID",
            "Book routes must share one frozen backend and account",
        )
    backend_id, runtime_class, auth_profile = next(iter(expected))
    if (
        (backend_id, runtime_class)
        != (target["model_backend_id"], target["runtime_class"])
        or target["model_provider"] != "codex-cli"
        or (frozen.get("cost_accounting") or {}).get("accounting_basis")
        != target["cost_accounting_basis"]
        or target["cost_accounting_basis"] != "ACCOUNT_ENTITLEMENT"
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
            "continuation cannot change the Book backend, runtime or accounting basis",
        )
    settings = frozen.get("runtime_settings") or {}
    fields = {
        "account_identity_ref": "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF",
        "cli_version": "NOVEL_FORGE_CODEX_CLI_VERSION",
        "executable_sha256": "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256",
        "configuration_ref": "NOVEL_FORGE_CODEX_CONFIGURATION_REF",
    }
    account = dict(target["account"])
    entitlement = dict(account.get("entitlement") or {})
    if any(
        not isinstance(settings.get(key), str)
        or not settings[key]
        or entitlement.get(field) != settings[key]
        for field, key in fields.items()
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
            "native Book account, CLI and configuration identity must remain exact",
        )
    uow.cursor.execute(
        "SELECT evidence->>'cost_authorization_ref' FROM authority_budget_reservation WHERE operation_id=%s AND project_id=%s ORDER BY created_at",
        [source["source_operation_id"], command["project_id"]],
    )
    references = {str(row[0] or "") for row in uow.cursor.fetchall()}
    if len(references) != 1 or not next(iter(references)):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_REQUIRED",
            "the released source budget must retain its original authorization reference",
        )
    from novel_forge.modules.production_execution.codex_configuration import (
        codex_local_binding_hash,
    )

    prior_entitlement = {**entitlement, "authorization_ref": next(iter(references))}
    expected_suffix = codex_local_binding_hash(
        codex_home=account["codex_home"],
        executable=account["executable"],
        entitlement=prior_entitlement,
        retry_policy=str(account.get("retry_policy") or ""),
    )
    if not auth_profile.endswith(":codex:" + expected_suffix):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT",
            "current executable and account directory do not reconstruct the original Book authentication binding",
        )
    return {
        **decision,
        "account_evidence_source": "BOOK_RUNTIME_POLICY_CREATION_PILOT",
        "book_route_policy_hash": canonical_hash(
            {
                "models": frozen["models"],
                "runtime_settings": settings,
                "cost_accounting": frozen.get("cost_accounting"),
            }
        ),
        "source_auth_profile_ref": auth_profile,
        "preserved_account_fields": list(fields),
        "authorization_reference_change": "NATIVE_BUDGET_SUCCESSOR_ALLOWED",
    }


def register(
    application: Any,
    source_operation_id: str,
    *,
    project_id: str,
    principal: Principal,
    expected_source_version: int,
    decision_evidence: Mapping[str, Any],
    trace_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    from .application import (
        _command_from_payload,
        _command_payload,
    )

    principal.require("story_planning.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError(
            "runtime continuation registration requires the existing trusted local operator"
        )
    if (
        not isinstance(decision_evidence, Mapping)
        or not isinstance(decision_evidence.get("authorization_ref"), str)
        or not decision_evidence["authorization_ref"].strip()
        or not isinstance(decision_evidence.get("reason"), str)
        or not decision_evidence["reason"].strip()
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DECISION_REQUIRED",
            "operator registration must cite the actual authorization and failure reason",
        )
    with AuthorityUnitOfWork(application.database_url) as uow:
        source = require_source(
            uow, source_operation_id=source_operation_id, project_id=project_id
        )
    if source["version"] != expected_source_version:
        raise KernelError(
            "OPERATION_VERSION_CONFLICT",
            "cancelled source version differs from the requested registration",
        )
    original = _command_from_payload(source["command"])
    continuation_id = f"planning-runtime-continuation:{source_operation_id}"
    reference_contract = source.get('mode')=='PLANNING_REFERENCE_CONTRACT'
    contract_change = source.get("mode") in {"WORLD_AGENCY_CONTRACT","PLANNING_REFERENCE_CONTRACT"} or reference_contract
    host_revalidation = source.get("mode") in {
        "WORLD_HOST_REVALIDATION",
        "WORLD_HOST_PROJECTION",
    }
    recap_revalidation = source.get("mode") == "RECAP_CONTEXT_REVALIDATION"
    local_revalidation = host_revalidation or recap_revalidation
    successor = replace(
        original,
        execution_contract_version=("1.20.0" if reference_contract else "1.19.0")
        if contract_change
        else original.execution_contract_version,
        **(
            {
                "repair_of_operation_id": "",
                "repair_result_asset_version_id": "",
                "repair_result_diagnostic": None,
                "repair_of_candidate_id": "",
                "repair_reason": "WORLD_HOST_PROJECTION_SUCCESSOR"
                if source.get("mode") == "WORLD_HOST_PROJECTION"
                else "WORLD_HOST_REVALIDATION_SUCCESSOR"
                if host_revalidation
                else "PLANNING_REFERENCE_CONTRACT_SUCCESSOR" if reference_contract else "WORLD_AGENCY_CONTRACT_SUCCESSOR",
                "parent_agent_session_operation_id": "",
            }
            if contract_change or host_revalidation
            else {}
        ),
        runtime_continuation_id=continuation_id,
        idempotency_key=f"{original.idempotency_key}:runtime-continuation:{source['depth']}",
    )
    application._register_definitions(successor.execution_contract_version)
    if contract_change:
        _ensure_world_agency_pack(application, source, original, successor, principal)
    target = resolve_target(application, successor)
    if reference_contract:
        proof=source['reference_contract_proof']
        target={**target,'planning_reference_contract':proof,'planning_capacity':{**source['source_planning_capacity'],
            'context_revalidation':{key:proof[key] for key in ('context_asset_version_id','context_content_hash')}}}
    if host_revalidation:
        target = {
            **target,
            "world_host_revalidation": source["world_host_revalidation"],
        }
    if recap_revalidation:
        target = {**target, "recap_context_revalidation": {"contract_version": "recap-context-revalidation.v1",
                  "source_operation_id": source_operation_id, "source_evidence_hash": source["evidence_hash"]}}
    capacity = source.get("mode") in {"PRE_SEND_CAPACITY", "ARC_ROLE_CONTEXT_REVALIDATION"}
    if (
        not capacity
        and not contract_change
        and not local_revalidation
        and source["snapshot"]["release_sha"] == application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RELEASE_UNCHANGED",
            "same-release failures use native Attempt recovery",
        )
    if (
        not capacity
        and not contract_change
        and not local_revalidation
        and (
            (source["provider"], source["model_id"])
            != (
                target["model_provider"],
                target["model_id"],
            )
            or source["snapshot"]["route_policy_hash"]
            != target["pack_snapshot"]["route_policy_hash"]
        )
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT",
            "runtime continuation cannot switch the frozen Provider model or routing policy",
        )
    if recap_revalidation:
        with AuthorityUnitOfWork(application.database_url) as uow:
            route_evidence = _capacity_authorization(uow, source=source, successor=successor, principal=principal, target=target)
        route_evidence = {**route_evidence, "recap_context_revalidation": "recap-context-revalidation.v1",
                          "preserved_repair_number": original.repair_number}
    elif host_revalidation:
        with AuthorityUnitOfWork(application.database_url) as uow:
            route_evidence = _capacity_authorization(
                uow,
                source=source,
                successor=successor,
                principal=principal,
                target=target,
            )
        route_evidence = {
            **route_evidence,
            "capacity_only": False,
            "host_revalidation": "world-host-revalidation.v1",
            "preserved_repair_number": original.repair_number,
            **(
                {"projection_revalidation": "world-direction-projection.v1"}
                if source.get("mode") == "WORLD_HOST_PROJECTION"
                else {}
            ),
        }
    elif contract_change:
        with AuthorityUnitOfWork(application.database_url) as uow:
            route_evidence = _capacity_authorization(
                uow,
                source=source,
                successor=successor,
                principal=principal,
                target=target,
            )
        route_evidence = {
            **route_evidence,
            "capacity_only": False,
            "changed_contract": "planning-host-source-selectors.v1" if reference_contract else "world-agency.v2",
            "preserved_repair_number": original.repair_number,
            "original_diagnostic": source["diagnostic"],
            "source_world": source.get("source_world",{}),
        }
    elif capacity:
        target, route_evidence = _capacity_target(
            application, source, successor, principal, target
        )
    else:
        with AuthorityUnitOfWork(application.database_url) as uow:
            route_evidence = require_route_evidence(
                uow,
                source=source,
                target=target,
                authorized_reasoning_effort=str(
                    decision_evidence.get("authorized_reasoning_effort") or ""
                ),
            )
    definition = runtime_continuation_definition(
        application_build_id=application.application_build_id,
        commit_sha=application.commit_sha,
    )
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()
    frozen_successor = _command_payload(successor)
    decision = {
        **dict(decision_evidence),
        **route_evidence,
        "registered_by": principal.principal_id,
        "registered_by_agent": True,
        "independent_human_review": "NOT_REVIEWED",
    }
    content = {
        "contract_version": "planning-runtime-continuation.v1",
        "continuation_id": continuation_id,
        "source_operation_id": source_operation_id,
        "source_evidence_asset_version_id": source["evidence_asset_version_id"],
        "project_id": project_id,
        "workspace_id": original.workspace_id,
        "book_id": original.book_id,
        "source_command": source["command"],
        "successor_command": frozen_successor,
        "target_runtime": target,
        "decision_evidence": decision,
        "source_release_sha": source["snapshot"]["release_sha"],
        "target_release_sha": application.commit_sha,
        "chain_depth": source["depth"],
        "control_evidence_only": True,
    }

    def materialize(uow, registration_operation_id, checkpoint):
        current = require_source(
            uow, source_operation_id=source_operation_id, project_id=project_id
        )
        if (
            current != source
            or (
                contract_change
                and _capacity_authorization(
                    uow,
                    source=current,
                    successor=successor,
                    principal=principal,
                    target=target,
                )
                != {
                    key: value
                    for key, value in route_evidence.items()
                    if key
                    not in {
                        "changed_contract",
                        "preserved_repair_number",
                        "original_diagnostic",
                        "source_world",
                    }
                }
                | {"capacity_only": True}
            )
            or (
                capacity
                and _capacity_authorization(
                    uow,
                    source=current,
                    successor=successor,
                    principal=principal,
                    target=target,
                )
                != route_evidence
            )
            or (
                host_revalidation
                and _capacity_authorization(
                    uow,
                    source=current,
                    successor=successor,
                    principal=principal,
                    target=target,
                )
                != {
                    key: value
                    for key, value in route_evidence.items()
                    if key
                    not in {
                        "host_revalidation",
                        "preserved_repair_number",
                        "projection_revalidation",
                    }
                }
                | {"capacity_only": True}
            )
            or (
                recap_revalidation
                and _capacity_authorization(uow, source=current, successor=successor, principal=principal, target=target)
                != {key: value for key, value in route_evidence.items()
                    if key not in {"recap_context_revalidation", "preserved_repair_number"}}
            )
            or (
                not capacity
                and not contract_change
                and not local_revalidation
                and require_route_evidence(
                    uow,
                    source=current,
                    target=target,
                    authorized_reasoning_effort=route_evidence[
                        "authorized_reasoning_effort"
                    ],
                )
                != route_evidence
            )
        ):
            raise KernelError(
                "PLANNING_RUNTIME_CONTINUATION_SOURCE_DRIFT",
                "source changed before continuation registration",
            )
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_operation_id,
                project_id=project_id,
                asset_id=continuation_id,
                asset_type="planning_runtime_continuation",
                schema_version="planning-runtime-continuation.v1",
                logical_ref=f"planning/runtime_continuations/{source_operation_id}.json",
                category="runs",
                output_key=OUTPUT_KEY,
                role="primary",
                content=content,
                qualification_policy="planning-runtime-continuation-operator-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
                causation_id=source_operation_id,
            )
        )
        uow.cursor.execute(
            "INSERT INTO authority_story_planning_runtime_continuation(continuation_id,project_id,workspace_id,book_id,source_operation_id,source_evidence_asset_version_id,registered_by_operation_id,source_command,successor_command,target_runtime,decision_evidence,source_release_sha,target_release_sha,chain_depth) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                continuation_id,
                project_id,
                original.workspace_id,
                original.book_id,
                source_operation_id,
                source["evidence_asset_version_id"],
                registration_operation_id,
                Jsonb(source["command"]),
                Jsonb(frozen_successor),
                Jsonb(target),
                Jsonb(decision),
                source["snapshot"]["release_sha"],
                application.commit_sha,
                source["depth"],
            ],
        )
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "planning_runtime_continuation",
                "aggregate_id": continuation_id,
                "operation_id": registration_operation_id,
                "project_id": project_id,
                "event_type": "story_planning.runtime_continuation.registered",
                "correlation_id": correlation_id,
                "causation_id": source_operation_id,
                "payload": {
                    "operation_id": registration_operation_id,
                    "trace_id": trace_id,
                    "continuation_id": continuation_id,
                    "asset_version_id": document.asset_version_id,
                    "source_operation_id": source_operation_id,
                    "target_release_sha": application.commit_sha,
                },
            }
        )
        return {
            "continuation_id": continuation_id,
            "asset_version_id": document.asset_version_id,
            "content_hash": document.content_hash,
            "source_operation_id": source_operation_id,
            "target_release_sha": application.commit_sha,
        }

    return execute_transaction_command(
        application.database_url,
        {
            "definition_name": DEFINITION_NAME,
            "definition_version": "1.0.0",
            "project_id": project_id,
            "workspace_id": original.workspace_id,
            "book_id": original.book_id,
            "actor_id": principal.principal_id,
            "idempotency_scope": "book:planning-runtime-continuation",
            "idempotency_key": continuation_id,
            "trace_id": trace_id,
            "span_id": str(uuid4()),
            "correlation_id": correlation_id,
            "causation_id": source_operation_id,
            "causation_operation_id": source_operation_id,
            "input": content,
            "input_assets": [
                {
                    "asset_version_id": source["evidence_asset_version_id"],
                    "content_hash": source["evidence_hash"],
                }
            ],
        },
        context=AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"story_planning.authority.execute"}),
            available_handlers=frozenset({HANDLER_KEY}),
            application_build_id=application.application_build_id,
            commit_sha=application.commit_sha,
        ),
        handler=materialize,
    )


def require_binding(database_url: str, continuation_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT project_id, workspace_id, book_id, source_operation_id, source_command, successor_command, target_runtime, target_release_sha, successor_operation_id FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s",
            [continuation_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_NOT_REGISTERED",
            "a worker may only follow an operator-registered continuation",
        )
    return dict(
        zip(
            (
                "project_id",
                "workspace_id",
                "book_id",
                "source_operation_id",
                "source_command",
                "successor_command",
                "target_runtime",
                "target_release_sha",
                "successor_operation_id",
            ),
            row,
            strict=True,
        )
    )


def require_successor(
    application: Any,
    command: StoryPlanningGenerationCommand,
    *,
    validate_runtime: bool = True,
) -> dict[str, Any]:
    from .application import _command_payload

    binding = require_binding(application.database_url, command.runtime_continuation_id)
    if (
        binding["successor_command"] != _command_payload(command)
        or binding["target_release_sha"] != application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT",
            "successor must use the registered frozen task and actual approved release",
        )
    expected_runtime = {
        key: value
        for key, value in binding["target_runtime"].items()
        if key not in {"planning_capacity", "world_host_revalidation", "recap_context_revalidation", "planning_reference_contract"}
    }
    if (
        validate_runtime
        and not binding["successor_operation_id"]
        and resolve_target(application, command) != expected_runtime
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RUNTIME_DRIFT",
            "the exact registered Pack and model route changed",
        )
    return binding


def require_snapshot(
    database_url: str, command: StoryPlanningGenerationCommand, snapshot: Any
) -> None:
    binding = require_binding(database_url, command.runtime_continuation_id)
    if (
        snapshot.execution_snapshot.to_dict()
        != binding["target_runtime"]["pack_snapshot"]
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_DRIFT",
            "the Attempt must freeze the exact operator-registered runtime",
        )


def follow(
    application: Any,
    source_operation_id: str,
    command: StoryPlanningGenerationCommand,
    *,
    principal: Principal,
):
    from .application import _command_from_payload, _command_payload

    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute(
            "SELECT source_command, successor_command FROM authority_story_planning_runtime_continuation WHERE source_operation_id=%s AND project_id=%s",
            [source_operation_id, command.project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return None
    if row[0] != _command_payload(command):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT",
            "original-stage replay must retain the exact registered source task",
        )
    return application.generate(
        _command_from_payload(dict(row[1])), principal=principal
    )


def attach_successor(
    uow: AuthorityUnitOfWork, command: StoryPlanningGenerationCommand, operation_id: str
) -> None:
    uow.cursor.execute(
        "UPDATE authority_story_planning_runtime_continuation SET successor_operation_id=%s WHERE continuation_id=%s AND (successor_operation_id IS NULL OR successor_operation_id=%s)",
        [operation_id, command.runtime_continuation_id, operation_id],
    )
    if uow.cursor.rowcount != 1:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_SUCCESSOR_CONFLICT",
            "only one successor Operation may bind the registered continuation",
        )


def _planning_reference_contract_source(uow, *, source_operation_id, row):
    from copy import deepcopy
    from .application import _command_from_payload, _validate_frozen_arc_references
    from novel_forge.modules.command_kernel.external_effect_runtime import (
        EffectCommandContext,
        read_completed_operation_success,
    )
    from novel_forge.modules.hierarchical_planning.domain import (
        validate_planning_contract,
        PlanContractType,
        PlanExecutionScope,
    )
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    frozen = dict(row[3])
    command = _command_from_payload(frozen)
    uow.cursor.execute(
        "SELECT chain_depth,target_runtime FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s",
        [source_operation_id],
    )
    prior = uow.cursor.fetchone()
    if (
        command.execution_contract_version != "1.19.0"
        or command.generator_operation_name != "chapter_group_plan.generate"
        or not prior
        or prior[0] != 2
        or not prior[1].get("planning_capacity", {}).get("context_revalidation")
    ):
        raise KernelError(
            "PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID",
            "Only the exact historical second Arc Context successor can change this contract",
        )
    uow.cursor.execute(
        "SELECT report FROM authority_story_planning_validation_report WHERE candidate_asset_version_id=%s ORDER BY created_at DESC,validation_report_id DESC LIMIT 1",
        [row[5]],
    )
    report = uow.cursor.fetchone()
    if (
        not report
        or report[0].get("error_code") != "WORLD_REALIZATION_REFERENCE_INVALID"
    ):
        raise KernelError(
            "PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID",
            "Source must retain the exact host identity failure",
        )
    uow.cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state='ABORTED')
        OR EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancel JOIN authority_story_formation_run formation USING(formation_run_id)
            WHERE cancel.project_id=%s AND formation.book_id=%s)
        OR EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status<>'SUCCEEDED')
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED')""",
        [
            command.project_id,
            command.book_id,
            command.project_id,
            command.book_id,
            source_operation_id,
            source_operation_id,
        ],
    )
    if uow.cursor.fetchone()[0]:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "Cancellation and unresolved original consumption prohibit contract succession",
        )
    query = AuthorityAssetQuery(uow.database_url)
    candidate = query.require(project_id=command.project_id, asset_version_id=row[5])
    evidence = candidate.content["execution_evidence"]
    context = query.require(
        project_id=command.project_id,
        asset_version_id=evidence["context_bundle_asset_version_id"],
    )
    catalog = context.content["realization_reference_contract"]["references_by_domain"]
    parent = command.runtime_continuation_id.removeprefix(
        "planning-runtime-continuation:"
    )
    if context.content_hash != evidence["context_bundle_hash"] or {
        ref["frozen_by_operation_id"] for refs in catalog.values() for ref in refs
    } != {parent}:
        raise KernelError(
            "PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID",
            "Frozen Context must reproduce its parent identity defect",
        )
    corrected = deepcopy(candidate.content)
    for manifest in ("world_realization", "character_realization"):
        for entity in corrected[manifest]:
            for field in (
                "invariant_refs",
                "structure_refs",
                "state_ref",
                "identity_ref",
                "trajectory_ref",
            ):
                rows = entity.get(field, [])
                rows = rows if isinstance(rows, list) else [rows]
                for reference in rows:
                    if reference not in catalog.get(reference.get("domain_type"), []):
                        raise KernelError(
                            "PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID",
                            "Content cannot borrow a different source as a host defect",
                        )
                    reference["frozen_by_operation_id"] = source_operation_id
    validate_planning_contract(
        project_id=command.project_id,
        book_id=command.book_id,
        contract_type=PlanContractType.CHAPTER_GROUP,
        asset_version_id=row[5],
        parent_version_id=command.parent_version_id,
        execution_scope=PlanExecutionScope.PLANNED,
        content=corrected,
        require_current_chapter_contract=True,
    )
    try:
        _validate_frozen_arc_references(command, corrected)
    except KernelError as error:
        if error.code != "PLANNING_ARC_PORTFOLIO_MISMATCH":
            raise
        portfolio_error = error.code
    else:
        raise KernelError(
            "PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID",
            "Host-only materialization must not dispatch when no content correction is needed",
        )
    receipt = read_completed_operation_success(
        uow.database_url,
        EffectCommandContext(
            operation_id=source_operation_id,
            project_id=command.project_id,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        ),
        effect_id=evidence["external_receipt_ref"],
    )
    if not receipt or receipt["budget_reservation_status"] != "SETTLED":
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "Exact verified original receipt and settled consumption required",
        )
    uow.cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [source_operation_id],
    )
    snapshot = uow.cursor.fetchone()
    proof = {
        "contract_version": "planning-reference-contract-successor.v1",
        "context_asset_version_id": context.asset_version_id,
        "context_content_hash": context.content_hash,
        "source_external_effect_id": evidence["external_receipt_ref"],
        "source_raw_result_hash": canonical_hash(
            receipt["provider_evidence"]["result"]
        ),
        "diagnosed_errors": ["WORLD_REALIZATION_REFERENCE_INVALID", portfolio_error],
        "required_arc_ids": [
            command.input_versions["arc_plans"],
            *command.related_arc_plan_version_ids,
        ],
        "repair_number": command.repair_number,
        "provider_model_unchanged": True,
    }
    return {
        "mode": "PLANNING_REFERENCE_CONTRACT",
        "source_operation_id": source_operation_id,
        "command": frozen,
        "version": int(row[1]),
        "evidence_asset_version_id": row[5],
        "evidence_hash": candidate.content_hash,
        "snapshot": snapshot[0],
        "depth": 3,
        "diagnostic": proof,
        "reference_contract_proof": proof,
        "source_planning_capacity": prior[1]["planning_capacity"],
    }
