
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
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


def _context_projection_hash(context):
    content = context if isinstance(context, Mapping) else context.content
    return canonical_hash(content["context_manifest"]["provider_context_view"])


def runtime_continuation_definition(
    *, application_build_id: str, commit_sha: str, definition_version: str = "1.0.0"
) -> dict[str, Any]:
    if definition_version not in {"1.0.0", "2.0.0", "3.0.0", "4.0.0"}:
        raise ValueError("Unsupported runtime continuation definition")
    schema = {"type": "object"}
    return {
        "name": DEFINITION_NAME,
        "definition_version": definition_version,
        "family": "story_planning_runtime",
        "command_schema_version": "planning-runtime-continuation.command.v" + definition_version[0],
        "result_schema_version": "planning-runtime-continuation.result.v" + definition_version[0],
        "enabled": True,
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "asset_type": "planning_runtime_continuation",
            "output_key": OUTPUT_KEY,
        },
        "handler_key": HANDLER_KEY,
        "handler_contract_version": "planning-runtime-continuation.v" + definition_version[0],
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["story_planning.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "trusted_operator_required": True,
            "zero_dispatch_required": definition_version == "1.0.0",
            **({'unstarted_isolated_successor_required': True} if definition_version == '4.0.0' else {}),
            **({'unsent_main_call_required': True, 'verified_preparation_required': True} if definition_version == '3.0.0' else {}),
            **({"world_contract_successor": "world-agency.v2", "settled_causal_lineage_required": True, "preserve_content_repair_counter": True} if definition_version == "2.0.0" else {}),
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
    uow: AuthorityUnitOfWork, *, source_operation_id: str, project_id: str, active_successor_operation_id: str = ""
) -> dict[str, Any]:
    uow.cursor.execute(
        "SELECT op.status, op.version, op.workspace_id, op.command_payload->'payload', g.book_id, g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.operation_id=%s AND op.project_id=%s FOR UPDATE OF op",
        [source_operation_id, project_id],
    )
    row = uow.cursor.fetchone()
    if (
        row is None
        or not ((row[0] in {"CANCELLED", "FAILED_RETRYABLE", "FAILED_FINAL", "DEAD_LETTER"} and not row[5]) or (row[0] == "SUCCEEDED" and row[5]))
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
    uow.cursor.execute("SELECT proof FROM authority_generation_isolation WHERE operation_id=%s", [source_operation_id])
    isolation_row = uow.cursor.fetchone()
    if isolation_row:
        proof = isolation_row[0]
        from novel_forge.modules.command_kernel.generation_isolation import require_generation_retry_budget
        retry_usage = require_generation_retry_budget(uow.cursor,operation_id=source_operation_id)
        uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s", [source_operation_id])
        prior = uow.cursor.fetchone()
        depth = (int(prior[0]) if prior else 0) + 1
        uow.cursor.execute("""WITH RECURSIVE ancestors AS (
            SELECT %s::text operation_id UNION ALL
            SELECT link.source_operation_id FROM authority_story_planning_runtime_continuation link
              JOIN ancestors ON link.successor_operation_id=ancestors.operation_id)
            SELECT count(DISTINCT i.operation_id) FROM authority_generation_isolation i
              JOIN ancestors USING(operation_id)""", [source_operation_id])
        recovery_number = int(uow.cursor.fetchone()[0])
        return {"mode": "ISOLATED_PURE_GENERATION", "source_operation_id": source_operation_id,
            "command": frozen, "version": int(row[1]), "evidence_asset_version_id": proof["evidence_asset_version_id"],
            "evidence_hash": uow.repositories.asset_documents.require(project_id=project_id,
                asset_version_id=proof["evidence_asset_version_id"]).content_hash,
            "snapshot": proof["pack_snapshot"], "depth": depth, "generation_isolation": proof,
            "generation_recovery_number": recovery_number,"failure_retry_counter":retry_usage}
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
    if row[0] == "FAILED_FINAL" and attempt and attempt[0] == "FAILED_FINAL" and dict(attempt[2] or {}).get("failure_details", {}).get("cause_code") == "PROVIDER_SCHEMA_REJECTED":
        from .schema_recovery import require_source as require_schema_source
        return require_schema_source(uow, source_operation_id=source_operation_id, row=row, frozen=frozen)
    if row[0] == "SUCCEEDED":
        if not attempt or attempt[0] != "SUCCEEDED" or frozen.get("execution_contract_version") != "1.19.0":
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID", "Only exact settled historical reference source is admitted")
        _require_world_lineage_settled(uow, source_operation_id=source_operation_id, project_id=project_id, book_id=str(row[4]), active_successor_operation_id=active_successor_operation_id)
        native = _require_rejected_reference_owner(uow, source_operation_id=source_operation_id, row=row, frozen=frozen)
        source = _planning_reference_contract_source(uow, source_operation_id=source_operation_id, row=row)
        source["reference_contract_proof"].update(native)
        source["diagnostic"] = source["reference_contract_proof"]
        return source
    if attempt and attempt[0] == "FAILED_FINAL":
        mode = None
        if row[0] == "FAILED_FINAL" and failure_code == "WORLD_ISOLATED_RECEIPT_INVALID" and frozen.get("execution_contract_version") == "1.21.0":
            return _isolated_world_source_correction(uow,source_operation_id=source_operation_id,row=row,frozen=frozen)
        if row[0] == "FAILED_FINAL" and failure_code == "PROGRAMMING_BUG" and dict(attempt[2] or {}).get("error_message") == "'frozen_source'" and frozen.get("repair_reason") == "WORLD_HOST_REVALIDATION_SUCCESSOR" and frozen.get("execution_contract_version") == "1.21.0":
            mode = _world_projection_source
        elif row[0] in {"FAILED_FINAL", "DEAD_LETTER"} and failure_code == "WORLD_PREPARATION_RESULT_INVALID":
            if frozen.get("execution_contract_version") == "1.21.0":
                try:
                    source = _world_foundation_source(uow, source_operation_id=source_operation_id, row=row, frozen=frozen)
                except KernelError as error:
                    if error.code != "WORLD_FOUNDATION_REVALIDATION_NOT_APPLICABLE":
                        raise
                else:
                    _require_world_lineage_settled(uow, source_operation_id=source_operation_id, project_id=project_id,
                        book_id=str(row[4]), active_successor_operation_id=active_successor_operation_id,
                        verified_complete_effect_ids=source["world_host_revalidation"]["retained_effect_ids"])
                    return source
                mode = _world_host_source
            elif frozen.get("execution_contract_version") in {"1.18.0", "1.19.0"}:
                mode = _world_agency_source
        elif row[0] == "FAILED_FINAL" and failure_code == "WORLD_DISCLOSURE_FIELDS_INVALID" and frozen.get("execution_contract_version") == "1.21.0":
            mode = _world_disclosure_source
        if mode:
            if mode is _world_disclosure_source:
                source = mode(uow,source_operation_id=source_operation_id,row=row,frozen=frozen)
                _require_world_lineage_settled(uow,source_operation_id=source_operation_id,project_id=project_id,
                    book_id=str(row[4]),active_successor_operation_id=active_successor_operation_id,
                    verified_complete_effect_ids=source["world_host_revalidation"]["retained_effect_ids"])
                return source
            _require_world_lineage_settled(uow, source_operation_id=source_operation_id, project_id=project_id, book_id=str(row[4]), active_successor_operation_id=active_successor_operation_id)
            return mode(uow, source_operation_id=source_operation_id, row=row, frozen=frozen)
    if (
        (row[0] in {"FAILED_FINAL", "DEAD_LETTER"} and failure_code == "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED")
        or (row[0] in {"FAILED_RETRYABLE", "FAILED_FINAL", "DEAD_LETTER"} and failure_code == "PROVIDER_ROUTING_BLOCKED"
            and frozen.get("generator_operation_name") in {"arc_plan.generate", "chapter_group_plan.generate", "chapter_plan.generate"})
    ):
        return _pre_send_capacity_source(
            uow,
            source_operation_id=source_operation_id,
            row=row,
            frozen=frozen,
            attempt=attempt,
            route_preflight=failure_code == "PROVIDER_ROUTING_BLOCKED",
        )
    if attempt and attempt[0] in {"FAILED_RETRYABLE", "FAILED_FINAL"} and (
        row[0] == "CANCELLED" and failure_code in {"PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "PROVIDER_ROUTING_BLOCKED"}
        or row[0] == "FAILED_FINAL" and failure_code == "NATIVE_PLANNING_REPAIR_SOURCE_INVALID"
    ):
        from .preflight_continuation import require_capacity_source
        return require_capacity_source(uow, source_operation_id=source_operation_id, project_id=project_id,
            frozen=frozen, version=int(row[1]), routing_failure=failure_code == "PROVIDER_ROUTING_BLOCKED",
            input_order_failure=failure_code == "NATIVE_PLANNING_REPAIR_SOURCE_INVALID")
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
        not in {"EXECUTION_CONTRACT_FROZEN_CONFLICT", "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "PROVIDER_ROUTING_BLOCKED", "NATIVE_PLANNING_REPAIR_SOURCE_INVALID"}
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED",
            "only a retained execution-contract or undispatched result-repair Context failure permits runtime continuation",
        )
    preflight_code = dict(attempt[1] or {}).get("error_code") or dict(attempt[2] or {}).get("error_code")
    if (row[0] == "FAILED_FINAL") != (preflight_code == "NATIVE_PLANNING_REPAIR_SOURCE_INVALID"):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SOURCE_INVALID","Terminal history only permits the proven undispatched input-order recovery")
    if preflight_code in {"PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED","PROVIDER_ROUTING_BLOCKED","NATIVE_PLANNING_REPAIR_SOURCE_INVALID"}:
        from .preflight_continuation import require_capacity_source
        return require_capacity_source(uow, source_operation_id=source_operation_id, project_id=project_id,
            frozen=frozen, version=int(row[1]),routing_failure=preflight_code == "PROVIDER_ROUTING_BLOCKED",
            input_order_failure=preflight_code == "NATIVE_PLANNING_REPAIR_SOURCE_INVALID")
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


def _world_disclosure_source(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from .world_preparation import require_world_disclosure_revalidation

    command = _command_from_payload(frozen)
    proof = require_world_disclosure_revalidation(uow.database_url,command=command,operation_id=source_operation_id)
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1", [source_operation_id])
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING", "Field-address recovery requires its original exact Pack snapshot")
    uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s", [source_operation_id])
    prior = uow.cursor.fetchone()
    return {"source_operation_id":source_operation_id,"command":frozen,"version":int(row[1]),
        "evidence_asset_version_id":proof["generation"]["asset_version_id"],"evidence_hash":proof["generation"]["content_hash"],
        "snapshot":dict(snapshot[0]),"depth":(int(prior[0]) if prior else 0)+1,
        "mode":"WORLD_DISCLOSURE_REVALIDATION","world_host_revalidation":proof}


def _world_foundation_source(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from .world_preparation import require_world_foundation_revalidation

    proof = require_world_foundation_revalidation(uow.database_url, command=_command_from_payload(frozen), operation_id=source_operation_id)
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1", [source_operation_id])
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING", "Background correction retains its original failed Pack snapshot")
    uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s", [source_operation_id])
    prior = uow.cursor.fetchone()
    return {"source_operation_id": source_operation_id, "command": frozen, "version": int(row[1]),
        "evidence_asset_version_id": proof["generation"]["asset_version_id"], "evidence_hash": proof["generation"]["content_hash"],
        "snapshot": dict(snapshot[0]), "depth": (int(prior[0]) if prior else 0) + 1,
        "mode": "WORLD_FOUNDATION_REVALIDATION", "world_host_revalidation": proof}


def _isolated_world_source_correction(uow, *, source_operation_id, row, frozen):
    from .application import _command_from_payload
    from .world_preparation import require_isolated_world_source_correction

    proof = require_isolated_world_source_correction(uow.database_url,command=_command_from_payload(frozen),operation_id=source_operation_id)
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",[source_operation_id])
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING", "Source correction retains the exact failed Pack")
    uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s",[source_operation_id])
    prior = uow.cursor.fetchone()
    return {"mode":"ISOLATED_WORLD_SOURCE_CORRECTION","source_operation_id":source_operation_id,"command":frozen,
        "version":int(row[1]),"snapshot":snapshot[0],"depth":int(prior[0])+1 if prior else 1,
        "world_source_correction":proof,"evidence_asset_version_id":proof["generation"]["asset_version_id"],
        "evidence_hash":proof["generation"]["content_hash"]}


def recover_world_result_frontier(application, book, *, principal):
    if book["state"] != "CHAPTER_PLAN_REQUIRED" or book.get("active_chapter_request_id"):
        return False
    principal.require("story_planning.authority.execute",book["project_id"])
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute("SELECT frozen_stage_inputs#>'{generation_policy,auto_authorization}' FROM authority_story_formation_run WHERE project_id=%s AND workspace_id=%s AND book_id=%s AND formation_run_id||':production'=%s",
            [book["project_id"],book["workspace_id"],book["book_id"],book["stable_idempotency_key"]])
        authorized = uow.cursor.fetchone()
        auth = authorized[0] if authorized else {}
        if (auth.get("contract_version") != "formation-auto-authorization.v1" or auth.get("authorized_by_principal_id") != principal.principal_id
                or (auth.get("project_id"),auth.get("workspace_id"),auth.get("book_id")) != (book["project_id"],book["workspace_id"],book["book_id"])
                or not auth.get("authorization_ref")):
            return False
        uow.cursor.execute("""SELECT op.operation_id,op.version,EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r WHERE r.source_operation_id=op.operation_id)
            FROM authority_story_planning_generation g JOIN authority_operation op USING(operation_id)
            JOIN LATERAL (SELECT status,result FROM authority_attempt WHERE operation_id=op.operation_id ORDER BY attempt_number DESC LIMIT 1) last ON true
            LEFT JOIN authority_asset_locator source_locator ON source_locator.project_id=g.project_id AND source_locator.logical_ref='world_preparation/'||op.operation_id||'/source'
            LEFT JOIN authority_asset_version source ON source.asset_version_id=source_locator.current_asset_version_id
            WHERE g.project_id=%s AND g.book_id=%s AND g.logical_key=%s AND g.generator_operation_name='chapter_plan.generate'
              AND op.status='FAILED_FINAL' AND last.status='FAILED_FINAL'
              AND op.command_payload#>>'{payload,world_preparation_request,book_run_id}'=%s
              AND ((last.result->>'error_code'='WORLD_DISCLOSURE_FIELDS_INVALID' AND source.content#>>'{contract,contract_version}'='world-preparation-source.v2')
                OR last.result->>'error_code'='WORLD_ISOLATED_RECEIPT_INVALID'
                OR (last.result->>'error_code'='WORLD_PREPARATION_RESULT_INVALID' AND op.definition_version='1.21.0'
                    AND EXISTS(SELECT 1 FROM authority_asset_locator action_locator
                        JOIN authority_asset_version action ON action.asset_version_id=action_locator.current_asset_version_id
                        JOIN authority_asset_version frozen ON frozen.asset_version_id=action.content#>>'{contract,source,asset_version_id}'
                        WHERE action_locator.project_id=g.project_id AND action_locator.logical_ref='world_preparation/'||op.operation_id||'/action'
                          AND frozen.content#>>'{contract,contract_version}'='world-preparation-source.v3'
                          AND frozen.content#>>'{contract,reality,baseline_kind}'='APPROVED_FOUNDATION'
                          AND EXISTS(SELECT 1 FROM jsonb_array_elements(action.content#>'{contract,world_plan,rejected_paths}') path
                              WHERE path#>>'{rejection,code}'='WORLD_COMPILED_RULE_VIOLATION'))))
            ORDER BY g.created_at DESC LIMIT 1""", [book["project_id"],book["book_id"],f"chapter:{book['current_chapter']+1}",book["book_run_id"]])
        row = uow.cursor.fetchone()
    if not row or row[2]:
        return False
    application.register_runtime_continuation(row[0],project_id=book["project_id"],expected_source_version=int(row[1]),
        decision_evidence={"reason":"Revalidate exact complete World results under the corrected field/source binding contract; preserve source history",
            "authorization_ref":auth["authorization_ref"],"source_book_run_id":book["book_run_id"]},principal=principal,
        trace_id=row[0]+":world-result-revalidation",correlation_id=book["root_operation_id"])
    return True


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


def _world_agency_pack_profile(version, operation_hash, *, repository_root):
    from novel_forge.modules.capability_packs.longform_profiles import (
        LongformCapabilityPackProfile,
    )

    manifest = deepcopy(version["manifest"])
    manifest["identity"]["version"] = "2.13.0"
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
        if node["operation_definition_ref"] not in {"story_planning.generate@1.18.0", "story_planning.generate@1.19.0"}:
            raise KernelError(
                "PLANNING_WORLD_CONTRACT_PACK_INVALID",
                "source Pack must contain only the affected native Planning contract",
            )
        node["operation_definition_ref"] = "story_planning.generate@1.21.0"
        node["operation_definition_hash"] = operation_hash
        if node.get("agent_definition_ref"):
            node["agent_definition_ref"] = (
                f"{node['agent_definition_ref'].rpartition('@')[0]}@{generation}"
            )
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    current = build_story_planning_pack_profile(repository_root, operation_definition_hash=operation_hash, execution_contract_version="1.21.0", narrative_intent_boundary=False)
    manifest["prompt_binding"] = {**manifest["prompt_binding"], **{key: current.manifest["prompt_binding"][key] for key in ("system_instruction_ref", "system_instruction_version", "system_instruction_hash")}}
    catalog = deepcopy(version["artifact_catalog"])
    system = next(item for item in current.artifact_catalog["artifacts"] if item["ref"] == manifest["prompt_binding"]["system_instruction_ref"] and item["version"] == "v11")
    catalog["artifacts"].append(deepcopy(system))
    workflow = manifest["workflow_template"]
    return LongformCapabilityPackProfile(
        pack_id=manifest["identity"]["pack_id"],
        workflow_ref=f"{workflow['workflow_id']}@{workflow['workflow_version']}",
        manifest=manifest,
        artifact_catalog=catalog,
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
    expected, _ = _world_agency_pack_profile(old, str(definition[0]), repository_root=Path(__file__).resolve().parents[4])
    if (
        new["manifest"] != expected.manifest
        or new["artifact_catalog"] != expected.artifact_catalog
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
        version, definition_hash(definition), repository_root=Path(__file__).resolve().parents[4]
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



def require_capacity_route_candidates(decision, *, frozen, source_operation_id):
    candidates = decision.get("candidates", [])
    eligible_scope = [item for item in candidates
        if "TEMPLATE_MODEL_UNAUTHORIZED" not in item.get("rejected_reasons", [])]
    task = decision.get("task", {})
    if (decision.get("status") != "BLOCKED" or not eligible_scope
        or task.get("project_id") != frozen["project_id"]
        or task.get("work_id") != frozen["book_id"]
        or task.get("operation_id") != source_operation_id
        or any("CONTEXT_CAPACITY_EXCEEDED" not in item.get("rejected_reasons", [])
            or any(reason not in {'CONTEXT_CAPACITY_EXCEEDED', 'BUDGET_HARD_LIMIT', 'PROVIDER_MODEL_CAPACITY_UNAVAILABLE'}
                and not (isinstance(reason, str) and reason.startswith('PROVIDER_UNAVAILABLE:PROVIDER_MODEL_CAPACITY_UNAVAILABLE:'))
                for reason in item['rejected_reasons'])
            for item in eligible_scope)):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED", "Retained routing failure is not solely a proven request capacity failure for an authorized candidate")


def _pre_send_capacity_source(
    uow: Any,
    *,
    source_operation_id: str,
    row: Any,
    frozen: dict[str, Any],
    attempt: Any,
    route_preflight: bool = False,
) -> dict[str, Any]:
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    projection_revalidation, retained_world, world_owner = None, None, source_operation_id
    if route_preflight:
        uow.cursor.execute("""SELECT version.content FROM authority_operation_output_asset output
            JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE output.operation_id=%s AND asset.asset_type='routing_decision' ORDER BY version.created_at DESC LIMIT 1""", [source_operation_id])
        decision = uow.cursor.fetchone()
        if not decision:
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED", "Retained routing decision is absent")
        require_capacity_route_candidates(decision[0], frozen=frozen, source_operation_id=source_operation_id)
        group = frozen.get("generator_operation_name") == "chapter_group_plan.generate"
        projection_revalidation = {"contract_version": "planning-exact-value-reference.v1" if frozen.get("generator_operation_name") == "chapter_plan.generate" else "typed-planning-window-projection.v1" if group else "typed-volume-context-projection.v1",
            "blocked_decision_id": decision[0]["decision_id"], "source_operation_status": str(row[0]),
            "reason": "Retain typed planning fields and audit material outside the exact frozen narrative horizon" if group else "Arc scope VolumePlans use the existing typed VolumePlan field contract with audited omissions"}
        uow.cursor.execute("""SELECT output.asset_version_id,output.content_hash FROM authority_operation_output_asset output
            WHERE output.operation_id=%s AND output.output_key='planning.context_bundle'""", [source_operation_id])
        context = uow.cursor.fetchone()
        if not context:
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_MISSING", "Routing capacity failure must retain its frozen Context")
        projection_revalidation.update(context_asset_version_id=context[0],context_content_hash=context[1])
    uow.cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s) OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND output_key='planning.context_bundle')",
        [source_operation_id] * 3,
    )
    unsafe = uow.cursor.fetchone()[0]
    if route_preflight:
        from .application import _command_from_payload
        from .schema_recovery import retained_world_action
        action, retained_world = retained_world_action(uow.database_url,
            command=_command_from_payload(frozen), source_operation_id=source_operation_id)
        receipts = []
        if action is not None:
            query = AuthorityAssetQuery(uow.database_url)
            from .world_preparation import PlanningWorldPreparation
            world_owner = PlanningWorldPreparation._source_operation(uow.database_url,
                frozen['project_id'], retained_world['generation']['asset_version_id'])
            receipts = [query.require(project_id=frozen['project_id'],
                asset_version_id=retained_world[key]['asset_version_id']).content['contract']['evidence']['external_receipt_ref']
                for key in ('generation', 'evaluation')]
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s
              AND (NOT (external_effect_id=ANY(%s)) OR effect_type<>'model.invoke' OR status<>'SUCCEEDED'))
            OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s
              AND (external_effect_id IS NULL OR NOT (external_effect_id=ANY(%s))))
            OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status IN ('LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED'))
            OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
              WHERE attempt.operation_id=%s AND lease.status='HELD')""",
            [source_operation_id, receipts, source_operation_id, receipts, source_operation_id, source_operation_id])
        unsafe = uow.cursor.fetchone()[0]
    if unsafe:
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE",
            "Capacity continuation requires an unsent main call, verified completed preparation and no active Attempt",
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
    inherited, world_revalidation, world_correction = None, None, None
    if frozen.get("runtime_continuation_id"):
        uow.cursor.execute("""SELECT link.target_runtime->'world_host_revalidation',link.target_runtime->'world_source_correction',link.target_runtime->'generation_isolation'
            FROM authority_story_planning_runtime_continuation link
            JOIN authority_operation registration ON registration.operation_id=link.registered_by_operation_id
            WHERE link.continuation_id=%s AND link.successor_operation_id=%s AND link.successor_command=%s
              AND link.project_id=%s AND link.workspace_id=%s AND link.book_id=%s
              AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
              AND registration.actor_id=%s AND registration.project_id=link.project_id AND registration.workspace_id=link.workspace_id""",
            [frozen["runtime_continuation_id"],source_operation_id,Jsonb(frozen),frozen["project_id"],frozen["workspace_id"],frozen["book_id"],frozen["actor_id"]])
        bound_world = uow.cursor.fetchone()
        if bound_world and bound_world[0]:
            from .application import _command_from_payload
            from .world_preparation import require_world_host_revalidation

            world_revalidation = require_world_host_revalidation(uow.database_url,command=_command_from_payload(frozen),operation_id=bound_world[0]["source_operation_id"])
            if world_revalidation != bound_world[0]:
                raise KernelError("WORLD_HOST_REVALIDATION_DRIFT", "Capacity recovery must retain the prior exact completed World proof")
        if bound_world and bound_world[1]:
            from .application import _command_from_payload
            from .world_preparation import require_isolated_world_source_correction

            retained_correction = bound_world[1]
            uow.cursor.execute("""SELECT original.command_payload->'payload' FROM authority_operation original
                JOIN authority_story_planning_generation origin USING(operation_id)
                JOIN authority_story_planning_generation current ON current.operation_id=%s
                WHERE original.operation_id=%s AND original.actor_id=%s AND original.project_id=%s AND original.workspace_id=%s
                  AND origin.book_id=current.book_id AND origin.logical_key=current.logical_key
                  AND origin.generator_operation_name=current.generator_operation_name AND origin.planning_scope=current.planning_scope
                  AND origin.input_snapshot=current.input_snapshot AND origin.input_snapshot_hash=current.input_snapshot_hash""",
                [source_operation_id,retained_correction["source_operation_id"],frozen["actor_id"],frozen["project_id"],frozen["workspace_id"]])
            original = uow.cursor.fetchone()
            controls = {"runtime_continuation_id","idempotency_key","opening_execution_binding"}
            if not original or {key:value for key,value in original[0].items() if key not in controls} != {key:value for key,value in frozen.items() if key not in controls}:
                raise KernelError("WORLD_ISOLATED_SOURCE_CORRECTION_DRIFT", "Capacity recovery must bind the same frozen story inputs and creator")
            world_correction = require_isolated_world_source_correction(uow.database_url,
                command=_command_from_payload(original[0]),operation_id=retained_correction["source_operation_id"])
            if world_correction != retained_correction or bound_world[2] != world_correction["isolation"]:
                raise KernelError("WORLD_ISOLATED_SOURCE_CORRECTION_DRIFT", "Capacity recovery must retain the exact complete sibling and original isolation")
        uow.cursor.execute("""SELECT isolation.proof, capacity.target_runtime->'planning_capacity'
            FROM authority_story_planning_runtime_continuation link
            JOIN authority_generation_isolation isolation ON isolation.operation_id=link.source_operation_id
            JOIN authority_operation original ON original.operation_id=isolation.operation_id
            JOIN authority_story_planning_runtime_continuation capacity ON capacity.continuation_id=original.command_payload#>>'{payload,runtime_continuation_id}'
            WHERE link.successor_operation_id=%s AND link.target_runtime#>>'{generation_isolation,external_effect_id}'=isolation.external_effect_id""", [source_operation_id])
        retained = uow.cursor.fetchone()
        if retained and retained[1]:
            inherited = {"contract_version": "generation-capacity-inheritance.v1", "generation_isolation": retained[0], "allocation": retained[1]}
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
        **({"capacity_inheritance": inherited} if inherited else {}),
        **({"inherited_world_host_revalidation":world_revalidation} if world_revalidation else {}),
        **({"inherited_world_source_correction":world_correction} if world_correction else {}),
        **({'retained_world_action': {'source_operation_id': world_owner, 'world_action': retained_world}} if retained_world else {}),
        "failure": dict(attempt[2] or attempt[1] or {}),
        "depth": depth + 1,
        **({"context_revalidation": projection_revalidation} if projection_revalidation else {}),
    }


def _require_version_only_pack_successor(uow, *, project_id, original, target):
    from novel_forge.storage.capability_pack_authority_repositories import CapabilityPackAuthorityRepository

    if not original.get("pack_id") or original.get("pack_id") != target.get("pack_id"):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT", "Capacity continuation must retain the owning Pack")
    repository = CapabilityPackAuthorityRepository(uow.cursor)
    retained = []
    for snapshot in (original, target):
        version = repository.require_version(snapshot["pack_id"], snapshot["pack_version"], project_id=project_id)
        manifest = deepcopy(version["manifest"])
        if canonical_hash(manifest) != snapshot["manifest_hash"] or version["manifest_hash"] != snapshot["manifest_hash"]:
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT", "Pack successor manifest differs from its persisted snapshot")
        manifest["identity"].pop("version")
        retained.append(manifest)
    if retained[0] != retained[1]:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT", "Capacity continuation cannot change Pack contracts")
    return {"contract_version": "version-only-pack-successor.v1", "source_manifest_hash": original["manifest_hash"],
        "target_manifest_hash": target["manifest_hash"], "retained_contract_hash": canonical_hash(retained[0])}


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

    if source.get("inherited_world_host_revalidation") and target.get("world_host_revalidation") != source["inherited_world_host_revalidation"]:
        raise KernelError("WORLD_HOST_REVALIDATION_DRIFT", "Capacity authorization retains the exact already-verified World proof")
    correction = source.get("inherited_world_source_correction")
    if correction and (target.get("world_source_correction") != correction or target.get("generation_isolation") != correction["isolation"]):
        raise KernelError("WORLD_ISOLATED_SOURCE_CORRECTION_DRIFT", "Capacity authorization must retain the exact complete sibling and isolation")
    uow.cursor.execute(
        "SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s AND frozen_stage_inputs #>> '{generation_policy,contract_version}' IN ('formation-generation.v5','formation-generation.v7')",
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
        or successor.actor_id != source["command"]["actor_id"]
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
    if source.get("mode") in {"WORLD_AGENCY_CONTRACT", "PLANNING_REFERENCE_CONTRACT"}:
        _require_world_agency_pack(uow, source=source, successor=successor, target=target)
    version_successor = None
    strict_pack = source.get("mode") not in {"WORLD_AGENCY_CONTRACT", "PLANNING_REFERENCE_CONTRACT"} and not source.get("capacity_inheritance")
    if strict_pack and source["snapshot"].get("manifest_hash") != target["pack_snapshot"].get("manifest_hash"):
        version_successor = _require_version_only_pack_successor(uow, project_id=successor.project_id,
            original=source["snapshot"], target=target["pack_snapshot"])
    if any(
        source["snapshot"].get(key) != target["pack_snapshot"].get(key)
        for key in (
            *(("prompt_bundle_hash",) if strict_pack else ()),
            "route_policy_hash",
            "context_policy_hash",
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
        **({"pack_version_successor": version_successor} if version_successor else {}),
        **({"capacity_inheritance": "generation-capacity-inheritance.v1"} if source.get("capacity_inheritance") else {}),
        **({"world_revalidation_inheritance":"world-revalidation-inheritance.v1"} if source.get("inherited_world_host_revalidation") else {}),
        **({"world_source_inheritance":"world-source-inheritance.v1"} if correction else {}),
    }


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
    allocated = min(baseline * 2, ceiling)
    if source.get("capacity_inheritance"):
        allocated = int(source["capacity_inheritance"]["allocation"]["allocated_task_tokens"])
        if allocated > ceiling:
            raise KernelError("PLANNING_CAPACITY_ALLOCATION_EXHAUSTED", "Inherited allocation exceeds the current authorized model capacity")
    if allocated <= baseline and not source.get("context_revalidation"):
        raise KernelError(
            "PLANNING_CAPACITY_ALLOCATION_EXHAUSTED",
            "No authorized single-request capacity remains",
        )
    while True:
        try:
            if source.get("context_revalidation"):
                proof = source["context_revalidation"]
                original_context = preparer.query.require(project_id=successor.project_id,asset_version_id=proof["context_asset_version_id"])
                original_inputs = {item["role"]:item for item in original_context.content["input_versions"]}
                if original_context.content_hash != proof["context_content_hash"] or any(
                    any(original_inputs.get(item["role"], {}).get(key) != item[key] for key in ("asset_version_id","content_hash","asset_type"))
                    for item in source["inputs"]):
                    raise KernelError("PLANNING_CONTEXT_REVALIDATION_SOURCE_DRIFT", "Context successor must retain every original input version")
                context = preparer._reproject_frozen_context(original_context.content,command=successor,task_tokens=allocated)
            else:
                context, _ = preparer._context_bundle(
                operation_id=source["source_operation_id"],
                attempt_id=source["attempt_id"],
                command=successor,
                inputs=tuple(FrozenPlanningInput(**value) for value in source["inputs"]),
                context_policy_ref=source["snapshot"]["context_policy_ref"],
                planning_task_token_budget=allocated,
                preflight_only=True,
            )
            break
        except KernelError as error:
            if error.code != "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED":
                raise
            if allocated == ceiling or source.get("capacity_inheritance"):
                raise KernelError("PLANNING_CAPACITY_ALLOCATION_EXHAUSTED",
                    "The retained task cannot fit its authorized single-request capacity",details=error.details) from error
            allocated=min(allocated*2,ceiling)
    allocation = {
        "version": "planning-capacity-allocation.v1",
        "prior_task_tokens": baseline,
        "allocated_task_tokens": allocated,
        "single_request_ceiling": ceiling,
        "projection_hash": _context_projection_hash(context),
        "source_failure": source["failure"],
        "external_intents_at_source": 2 if source.get('retained_world_action', {}).get('source_operation_id') == source['source_operation_id'] else 0,
        **({'retained_world_action': source['retained_world_action']} if source.get('retained_world_action') else {}),
        **({"context_revalidation": source["context_revalidation"]} if source.get("context_revalidation") else {}),
    }
    if source.get("capacity_inheritance"):
        target = {**target, "generation_isolation": source["capacity_inheritance"]["generation_isolation"]}
        authorization = {**authorization, "capacity_inheritance": "generation-capacity-inheritance.v1"}
    if source.get("inherited_world_host_revalidation"):
        target = {**target,"world_host_revalidation":source["inherited_world_host_revalidation"]}
    if source.get("inherited_world_source_correction"):
        correction = source["inherited_world_source_correction"]
        target = {**target,"world_source_correction":correction,"generation_isolation":correction["isolation"]}
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
    if source.get("preflight_failure"):
        if (source["source_auth_profile_ref"] != target["auth_profile_ref"]
                or source["source_backend_id"] != target["model_backend_id"]
                or source["source_reasoning_effort"] != target["reasoning_effort"]
                or target["cost_accounting_basis"] != "ACCOUNT_ENTITLEMENT" or not target["account"]):
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_ACCOUNT_DRIFT", "Capacity successors must retain the original authenticated membership binding and reasoning")
        if source["preflight_failure"].get("contract_version") in {"planning-repair-route-preflight.v1","planning-input-order-preflight.v1"}:
            from novel_forge.modules.production_execution.execution_template import selected_book_template, decision_template
            admission = selected_book_template(uow.cursor,project_id=source["command"]["project_id"],book_id=source["command"]["book_id"])
            template = decision_template({"task":{"work_id":source["command"]["book_id"],
                "policy_snapshot":admission["policy_snapshot"]}}) if admission else None
            repair = source["preflight_failure"]["blocked_decision"]["native_repair_evidence"]
            if (not template or template['version'] not in {'creative-execution-template.v2','creative-execution-template.v3','creative-execution-template.v4','creative-execution-template.v5','creative-execution-template.v6','creative-execution-template.v7','creative-execution-template.v8','creative-execution-template.v9','creative-execution-template.v10','creative-execution-template.v11'}
                    or not template.get('repair_routing')
                    or repair.get('stage_repair_number', repair['repair_number']) > template['repair_routing']['max_same_route_repairs']
                    or repair['repair_number'] > 4
                    or repair['parent_candidate_id'] not in template['allowed_candidates']):
                raise KernelError("PLANNING_RUNTIME_CONTINUATION_POLICY_REQUIRED","Routing successor requires the explicit trusted v2 native repair policy")
            decision["target_repair_template"] = admission
        return {**decision,"account_evidence_source":"ORIGINAL_SETTLED_NATIVE_RESULT_ROUTE",
            "source_auth_profile_ref":source["source_auth_profile_ref"],"source_result_operation_id":source["route_evidence_operation_id"],
            "account_runtime_hash":canonical_hash(target["account"])}
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
        [source.get("route_evidence_operation_id", source["source_operation_id"]), command["project_id"]],
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
        uow.cursor.execute("""SELECT link.continuation_id,operation.operation_id,operation.status,link.target_release_sha,
            output.asset_version_id,output.content_hash FROM authority_story_planning_runtime_continuation link
            JOIN authority_operation operation ON operation.operation_id=link.registered_by_operation_id
            JOIN authority_operation_output_asset output ON output.operation_id=operation.operation_id AND output.output_key=%s
            WHERE link.source_operation_id=%s AND link.project_id=%s AND operation.actor_id=%s""",
            [OUTPUT_KEY,source_operation_id,project_id,principal.principal_id])
        registered=uow.cursor.fetchone()
        if registered:
            return {"operation_id":registered[1],"status":registered[2],"continuation_id":registered[0],
                "target_release_sha":registered[3],"asset_version_id":registered[4],"content_hash":registered[5],
                "source_operation_id":source_operation_id,"replayed":True}
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
    reference_contract = source.get("mode") == "PLANNING_REFERENCE_CONTRACT"
    world_source_correction = source.get("mode") == "ISOLATED_WORLD_SOURCE_CORRECTION"
    isolated_generation = source.get("mode") == "ISOLATED_PURE_GENERATION"
    contract_change = source.get("mode") in {"WORLD_AGENCY_CONTRACT", "PLANNING_REFERENCE_CONTRACT"}
    schema_correction = source.get("mode") == "PROVIDER_SCHEMA_CORRECTION"
    host_revalidation = source.get("mode") in {
        "PROVIDER_SCHEMA_CORRECTION",
        "WORLD_HOST_REVALIDATION",
        "WORLD_HOST_PROJECTION",
        "WORLD_DISCLOSURE_REVALIDATION",
        "WORLD_FOUNDATION_REVALIDATION",
    }
    successor = replace(
        original,
        execution_contract_version="1.21.0"
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
            if contract_change or (host_revalidation and not schema_correction)
            else {}
        ),
        runtime_continuation_id=continuation_id,
        idempotency_key=f"{original.idempotency_key}:runtime-continuation:{source['depth']}",
    )
    application._register_definitions(successor.execution_contract_version)
    if contract_change:
        _ensure_world_agency_pack(application, source, original, successor, principal)
    target = resolve_target(application, successor)
    if source.get("inherited_world_host_revalidation"):
        target = {**target,"world_host_revalidation":source["inherited_world_host_revalidation"]}
    if source.get("inherited_world_source_correction"):
        correction = source["inherited_world_source_correction"]
        target = {**target,"world_source_correction":correction,"generation_isolation":correction["isolation"]}
    if world_source_correction:
        proof = source["world_source_correction"]
        target = {**target,"world_source_correction":proof,"generation_isolation":proof["isolation"]}
        if proof["planning_capacity"]:
            target["planning_capacity"] = proof["planning_capacity"]
    if schema_correction:
        target = {**target, "provider_schema_correction": source["provider_schema_correction"]}
        if original.runtime_continuation_id:
            prior_capacity = require_binding(application.database_url, original.runtime_continuation_id)["target_runtime"].get("planning_capacity")
            if prior_capacity:
                target["planning_capacity"] = prior_capacity
    elif host_revalidation:
        target = {
            **target,
            "world_host_revalidation": source["world_host_revalidation"],
        }
    if reference_contract:
        target = {**target, "planning_reference_contract": source["reference_contract_proof"], "planning_capacity": source["source_planning_capacity"]}
    capacity = source.get("mode") == "PRE_SEND_CAPACITY"
    if (
        not capacity
        and not isolated_generation
        and not contract_change
        and not host_revalidation
        and not world_source_correction
        and source["snapshot"]["release_sha"] == application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_RELEASE_UNCHANGED",
            "same-release failures use native Attempt recovery",
        )
    if (
        not capacity
        and not isolated_generation
        and not contract_change
        and not host_revalidation
        and not world_source_correction
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
    capacity_decision = None
    if source.get("preflight_failure"):
        from .preflight_continuation import require_capacity_target
        capacity_decision = require_capacity_target(source, target)
    if isolated_generation:
        target = {**target, "generation_isolation": source["generation_isolation"]}
        if original.runtime_continuation_id:
            prior_runtime = require_binding(application.database_url, original.runtime_continuation_id)["target_runtime"]
            prior_capacity = prior_runtime.get("planning_capacity")
            if prior_capacity:
                preparer = application.execution_binder.resolver.execution_preparer
                route = preparer.planning_route
                allocated = int(prior_capacity["allocated_task_tokens"])
                ceiling = min(512000, route.model_context_limit-route.model_output_limit-route.token_safety_margin-route.token_framing_overhead)
                if allocated > ceiling:
                    raise KernelError("PLANNING_CAPACITY_ALLOCATION_EXHAUSTED", "The authorized successor model cannot retain original task capacity")
                context, _ = preparer._context_bundle(operation_id=source_operation_id,
                    attempt_id=source["generation_isolation"]["local_execution"]["attempt_id"], command=successor,
                    inputs=application._resolve_inputs(successor), context_policy_ref=target["pack_snapshot"]["context_policy_ref"],
                    planning_task_token_budget=allocated, preflight_only=True)
                target["planning_capacity"] = {**prior_capacity, "projection_hash": _context_projection_hash(context)}
        route_evidence = {"recovery_kind": "ISOLATED_PURE_GENERATION", "remote_outcome": "UNKNOWN",
            "usage": "UNKNOWN", "preserved_repair_number": original.repair_number,
            "recovery_attempt_number": source["generation_recovery_number"],
            "failure_retry_counter":source["failure_retry_counter"]}
    elif host_revalidation or world_source_correction:
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
            "host_revalidation": "world-isolated-source-correction.v1" if world_source_correction else "provider-schema-correction.v1" if schema_correction else source["world_host_revalidation"]["contract_version"],
            **({"failure_retry_counter": source["provider_schema_correction"]["failure_retry_counter"]} if schema_correction else {}),
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
            "changed_contract": "planning-host-source-selectors.v2" if reference_contract else "world-agency.v2",
            "preserved_repair_number": original.repair_number,
            "original_diagnostic": source["diagnostic"],
            **({} if reference_contract else {"source_world": source["source_world"]}),
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
    continuation_version = '3.0.0' if source.get('retained_world_action') else '2.0.0' if contract_change or host_revalidation or world_source_correction else '1.0.0'
    definition = runtime_continuation_definition(
        application_build_id=application.application_build_id,
        commit_sha=application.commit_sha,
        definition_version=continuation_version,
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
        "contract_version": 'planning-runtime-continuation.v' + continuation_version[0],
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
        **({"source_preflight_failure": source["preflight_failure"], "capacity_decision": capacity_decision} if source.get("preflight_failure") else {}),
        "control_evidence_only": True,
    }

    def materialize(uow, registration_operation_id, checkpoint):
        if source.get("mode") in {"WORLD_DISCLOSURE_REVALIDATION","WORLD_FOUNDATION_REVALIDATION","ISOLATED_WORLD_SOURCE_CORRECTION"}:
            uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s ORDER BY formation_run_id FOR UPDATE",
                [project_id,original.book_id])
            uow.cursor.fetchall()
        from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
        require_known_cli_lineage(uow.cursor, project_id=project_id, operation_id=source_operation_id)
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
                (host_revalidation or world_source_correction)
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
                        "failure_retry_counter",
                    }
                }
                | {"capacity_only": True}
            )
            or (
                not capacity
                and not isolated_generation
                and not contract_change
                and not host_revalidation
                and not world_source_correction
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
        if (source.get("context_revalidation") or {}).get("source_operation_status") == "FAILED_RETRYABLE":
            from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow

            transition_operation_in_uow(uow, OperationTransitionCommand(
                operation_id=source_operation_id, project_id=project_id, expected_version=source["version"],
                expected_status="FAILED_RETRYABLE", target_status="FAILED_FINAL", actor_id=principal.principal_id,
                reason="Retain failed unsent request and atomically register its audited Context contract successor",
                trace_id=trace_id, correlation_id=correlation_id, causation_id=registration_operation_id))
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=registration_operation_id,
                project_id=project_id,
                asset_id=continuation_id,
                asset_type="planning_runtime_continuation",
                schema_version=content["contract_version"],
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
            "definition_version": continuation_version,
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




def require_binding(database_url: str, continuation_id: str, *, effective: bool = True) -> dict[str, Any]:
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
    binding = dict(
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
    if effective:
        from .runtime_deployment import effective_binding
        return effective_binding(database_url, binding)
    return binding


def require_successor(
    application: Any, command: StoryPlanningGenerationCommand, *, validate_runtime: bool = True
) -> dict[str, Any]:
    from .application import _command_payload

    binding = require_binding(application.database_url, command.runtime_continuation_id)
    if (
        binding["successor_command"] != _command_payload(command)
        or validate_runtime and binding["target_release_sha"] != application.commit_sha
    ):
        raise KernelError(
            "PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT",
            "successor must use the registered frozen task and actual approved release",
        )
    expected_runtime = {
        key: value
        for key, value in binding["target_runtime"].items()
        if key not in {"planning_capacity", "world_host_revalidation", "world_source_correction", "planning_reference_contract", "generation_isolation", "provider_schema_correction"}
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
    execution_probe: Any = None,
):
    from .application import _command_from_payload, _command_payload

    application._probe(execution_probe)
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
        _command_from_payload(dict(row[1])), principal=principal, execution_probe=execution_probe
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


def _require_world_lineage_settled(uow, *, source_operation_id, project_id, book_id, active_successor_operation_id="", verified_complete_effect_ids=()):
    uow.cursor.execute("""WITH RECURSIVE lineage(operation_id) AS (
        SELECT operation_id FROM authority_operation
        WHERE operation_id=%s AND project_id=%s AND command_payload #>> '{payload,book_id}'=%s
        UNION SELECT o.operation_id FROM authority_operation o
        JOIN lineage l ON (o.causation_operation_id=l.operation_id OR o.operation_id=(SELECT causation_operation_id FROM authority_operation WHERE operation_id=l.operation_id))
        WHERE o.definition_name='story_planning.generate' AND o.project_id=%s AND o.command_payload #>> '{payload,book_id}'=%s)
        SELECT EXISTS(SELECT 1 FROM authority_external_effect e JOIN lineage l USING(operation_id)
            WHERE e.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED') AND NOT authority_generation_isolated(e.external_effect_id))
        OR EXISTS(SELECT 1 FROM authority_budget_reservation b JOIN lineage l USING(operation_id)
            LEFT JOIN authority_external_effect complete ON complete.external_effect_id=b.external_effect_id
            WHERE b.status NOT IN ('SETTLED','RELEASED') AND NOT COALESCE(authority_generation_isolated(b.external_effect_id),FALSE)
                AND NOT COALESCE((b.status='HELD_UNKNOWN' AND complete.status='SUCCEEDED'
                AND complete.external_effect_id=ANY(%s)),FALSE))
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt a USING(attempt_id) JOIN lineage l USING(operation_id) WHERE lease.status='HELD' AND NOT (a.operation_id=%s AND a.status='RUNNING'
            AND a.attempt_number=(SELECT max(active.attempt_number) FROM authority_attempt active WHERE active.operation_id=a.operation_id) AND EXISTS (
            SELECT 1 FROM authority_operation child
            JOIN authority_story_planning_runtime_continuation r ON r.successor_operation_id=child.operation_id
            JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id
            WHERE child.operation_id=a.operation_id AND child.status='EXECUTING' AND child.causation_operation_id=r.source_operation_id
              AND child.project_id=%s AND r.project_id=child.project_id AND r.book_id=%s
              AND child.workspace_id=r.workspace_id AND child.actor_id=registration.actor_id
              AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
              AND ((r.source_operation_id=%s AND registration.definition_version='2.0.0') OR (
                r.target_runtime#>>'{world_host_revalidation,contract_version}'='world-host-revalidation.v3'
                AND r.target_runtime#>>'{world_host_revalidation,source_operation_id}'=%s AND r.decision_evidence->>'capacity_only'='true'
                AND registration.definition_version IN ('1.0.0','2.0.0','3.0.0')))
              AND child.command_payload->'payload'=r.successor_command
              AND child.command_payload #>> '{payload,runtime_continuation_id}'=r.continuation_id)))
        OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state IN ('ABORTED','COMPLETED','CANCELLED'))
        OR EXISTS(SELECT 1 FROM authority_story_creation_cancellation c JOIN authority_book_production book ON book.stable_idempotency_key=c.formation_run_id || ':production' WHERE c.project_id=book.project_id AND book.project_id=%s AND book.book_id=%s)
        """, [source_operation_id, project_id, book_id, project_id, book_id, list(verified_complete_effect_ids), active_successor_operation_id, project_id, book_id, source_operation_id, source_operation_id, project_id, book_id, project_id, book_id])
    if uow.cursor.fetchone()[0]:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE", "World contract succession requires settled live lineage; only the exact registered running child may hold its execution lease")
    from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
    require_known_cli_lineage(uow.cursor, project_id=project_id, operation_id=source_operation_id)

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
    if not snapshot:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING", "Reference recovery retains the original Pack")
    proof = {
        "contract_version": "planning-reference-contract-successor.v2",
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


def _require_rejected_reference_owner(uow, *, source_operation_id, row, frozen):
    uow.cursor.execute("""SELECT owner.lifecycle,owner.qualification,owner.approval,owner.freshness,owner.created_by_operation_id,
        candidate.content_hash,report.status,report.report,report.report_hash
        FROM authority_story_design_version_state owner JOIN authority_asset_version candidate USING(asset_version_id)
        JOIN LATERAL (SELECT status,report,report_hash,generation_operation_id FROM authority_story_planning_validation_report
            WHERE candidate_asset_version_id=owner.asset_version_id ORDER BY created_at DESC,validation_report_id DESC LIMIT 1) report ON TRUE
        WHERE owner.project_id=%s AND owner.asset_version_id=%s AND report.generation_operation_id=%s FOR SHARE OF owner,candidate""", [frozen["project_id"],row[5],source_operation_id])
    owner = uow.cursor.fetchone()
    if not owner or owner[:2] != ("REJECTED", "FAILED") or owner[2] not in {"NOT_REQUESTED","PENDING"} or owner[3] != "CURRENT" or owner[4] != source_operation_id or owner[6] != "FAIL" or owner[7].get("error_code") != "WORLD_REALIZATION_REFERENCE_INVALID":
        raise KernelError("PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID", "Exact latest native validation rejection required; author disposition is preserved")
    uow.cursor.execute("""SELECT jsonb_build_object('book_run_id',book_run_id,'accepted_through_chapter',accepted_through_chapter,'current_chapter',current_chapter,
        'book_plan_version',book_plan_version,'longform_context_versions',longform_context_versions,'active_chapter_request_id',active_chapter_request_id)
        FROM authority_book_production WHERE project_id=%s AND workspace_id=%s AND book_id=%s FOR SHARE""", [frozen["project_id"],frozen["workspace_id"],frozen["book_id"]])
    books = uow.cursor.fetchall()
    if len(books) > 1:
        raise KernelError("PLANNING_REFERENCE_CONTRACT_SOURCE_INVALID", "Host recovery cannot choose an ambiguous Book edition frontier")
    return {"source_candidate_hash": owner[5], "validation_report_hash": owner[8], "source_book_frontier": books[0][0] if books else None}
