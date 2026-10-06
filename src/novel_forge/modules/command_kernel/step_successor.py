from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    _record,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "kernel-failed-step-successor.v1"


def has_candidate_domain_outputs(cursor, operation_id):
    cursor.execute("""SELECT a.asset_type,o.role FROM authority_operation_output_asset o
        JOIN authority_asset a USING(asset_id) WHERE o.operation_id=%s""", [operation_id])
    contract_types = {'capability_materialization_manifest','execution_commit_policy','execution_context_policy',
        'execution_source_policy','execution_validation_policy','fallback_policy','input_manifest','model_profile',
        'prompt_bundle','provider_request_admission_manifest','route_policy','route_snapshot','skill_bundle','tool_permission_snapshot'}
    allowed = {(t,'execution_contract') for t in contract_types}
    allowed |= {('execution_evidence',r) for r in ('cost-receipt','normalized-output','output-manifest','process-receipt',
        'raw-output','usage-receipt','validation-manifest')}
    allowed |= {('cost_ledger','cost_evidence'),('execution_recovery_session','execution_recovery_projection'),
        ('model_call_log','model_evidence'),('routing_decision','routing_evidence')}
    return any(tuple(row) not in allowed for row in cursor.fetchall())



def replace_failed_step(
    database_url,
    *,
    predecessor_id,
    target_version,
    context: AdmissionContext,
    policy_evidence,
    expected_failure_code,
    settled_candidate_effects=(),
    transaction_guard=None,
):
    digest = hashlib.sha256(
        json.dumps(
            {
                "predecessor": predecessor_id,
                "target": target_version,
                "policy": policy_evidence,
                "failure_code": expected_failure_code,
                **({"settled_candidate_effects": settled_candidate_effects} if settled_candidate_effects else {}),
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE",
            [predecessor_id],
        )
        row = cursor.fetchone()
        if not row:
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_MISSING", "Missing native predecessor"
            )
        source = row[0]
        project = source["project_id"]
        if source["actor_id"] != context.actor_id:
            raise KernelError("STEP_SUCCESSOR_SOURCE_INVALID", "Recovery requires the original actor")
        if not set(source["definition_snapshot"]["permissions"]).issubset(context.permissions):
            raise KernelError("PERMISSION_DENIED", "Recovery requires the original command permissions")
        cursor.execute(
            "SELECT request_digest,successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s",
            [predecessor_id],
        )
        existing = cursor.fetchone()
        if existing:
            if existing[0] != digest:
                raise KernelError(
                    "STEP_SUCCESSOR_IDEMPOTENCY_CONFLICT", "Recovery command changed"
                )
            return {"operation_id": existing[1], "replayed": True}
        if transaction_guard is not None:
            transaction_guard(uow)
        repo = uow.repositories.operation_graph
        saga = repo.saga_for_update(source["saga_id"], project)
        repo.operation(source["root_operation_id"], project, lock=True)
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [source["root_operation_id"]],
        )
        root = cursor.fetchone()[0]
        cursor.execute(
            "SELECT to_jsonb(s) FROM authority_saga_step s WHERE operation_id=%s AND saga_id=%s FOR UPDATE",
            [predecessor_id, saga["saga_id"]],
        )
        row = cursor.fetchone()
        final_review_repair = bool(settled_candidate_effects and policy_evidence.get("contract_version") == "chapter-review-output-repair.v1"
            and source["definition_name"] == "chapter.review.evaluate" and source["definition_version"] == "3.9.0"
            and expected_failure_code in {"REVIEW_KNOWLEDGE_CHECK_INVALID", "REVIEW_KNOWLEDGE_CHECK_REQUIRED"})
        if (
            not row
            or source["status"] != ("CANCELLATION_REQUESTED" if settled_candidate_effects and not final_review_repair else "FAILED_FINAL")
            or root["status"] != "WAITING_CHILDREN"
            or saga["status"] != "RUNNING"
            or source["actor_id"] != context.actor_id
            or root["actor_id"] != context.actor_id
            or source["definition_version"] == target_version
        ):
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_INVALID",
                "Only an owned failed child of a live graph can be replaced",
            )
        step = row[0]
        if step["compensation_status"] != "NOT_REQUIRED" or step.get(
            "compensation_operation_id"
        ):
            raise KernelError(
                "STEP_SUCCESSOR_COMPENSATION_PRESENT",
                "Compensation retains its original recovery owner",
            )
        cursor.execute(
            "SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s",
            [root["operation_id"]],
        )
        deadline = cursor.fetchone()[0]
        if deadline and deadline <= datetime.now(timezone.utc):
            raise KernelError(
                "OPERATION_BUSINESS_TIMEOUT",
                "The frozen Root deadline remains authoritative",
            )
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
            EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s),
            EXISTS(SELECT 1 FROM authority_operation_dependency WHERE depends_on_operation_id=%s),
            EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
                WHERE a.operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW())""",
            [predecessor_id] * 4,
        )
        external, output, dependent, live_lease = cursor.fetchone()
        if settled_candidate_effects:
            output = has_candidate_domain_outputs(cursor, predecessor_id)
        if external and settled_candidate_effects:
            cursor.execute("SELECT e.external_effect_id,e.request_hash,e.status,r.status,e.effect_type FROM authority_external_effect e LEFT JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id", [predecessor_id])
            effects = cursor.fetchall()
            if effects != [(effect, digest, "SUCCEEDED", "SETTLED", "model.invoke") for effect, digest in sorted(settled_candidate_effects)]:
                raise KernelError("STEP_SUCCESSOR_CANDIDATE_UNSETTLED", "Only exact known succeeded settled candidates may be superseded")
            external = False
        if external or output or dependent or live_lease:
            raise KernelError(
                "STEP_SUCCESSOR_EXTERNAL_OR_DEPENDENT_WORK",
                "Effects, outputs, dependents or leases prevent step succession",
            )
        cursor.execute(
            "SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number",
            [predecessor_id],
        )
        attempts = [r[0] for r in cursor.fetchall()]
        if (
            not attempts
            or attempts[-1]["result"].get("error_code") != expected_failure_code
        ):
            raise KernelError(
                "STEP_SUCCESSOR_FAILURE_MISMATCH",
                "Recovery must bind the exact recorded local failure",
            )
        target = uow.repositories.definitions.get(
            source["definition_name"], target_version
        )
        old_definition = source["definition_snapshot"]
        if (
            not target
            or target["handler_key"] != old_definition["handler_key"]
            or target["permissions"] != old_definition["permissions"]
            or target["completion_contract"] != old_definition["completion_contract"]
            or target["command_schema"] != old_definition["command_schema"]
            or target["result_schema"] != old_definition["result_schema"]
            or target["external_capabilities"]
            != old_definition["external_capabilities"]
        ):
            raise KernelError(
                "STEP_SUCCESSOR_CONTRACT_CHANGED",
                "Successor cannot relax completion, permissions or external execution requirements",
            )
        if final_review_repair and target["policy"].get("review_knowledge_scope") != "delivered-card-scope.v1":
            raise KernelError("STEP_SUCCESSOR_CONTRACT_CHANGED", "Review recovery requires its versioned delivered scope")
        if policy_evidence.get("contract_version") == "chapter-length-output-repair.v1" and (target["policy"].get("chapter_length_scope") != "chapter-length-repair.v1" or source["definition_name"] != "chapter.revision.apply" or expected_failure_code != "REVISION_OUTSIDE_DIAGNOSIS_SCOPE"):
            raise KernelError("STEP_SUCCESSOR_CONTRACT_CHANGED", "Length recovery requires its exact versioned correction scope")
        if settled_candidate_effects and not final_review_repair:
            from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
            transition_operation_in_uow(uow, OperationTransitionCommand(operation_id=predecessor_id,
                project_id=project, expected_version=source['version'], expected_status='CANCELLATION_REQUESTED',
                target_status='CANCELLED', actor_id=context.actor_id,
                reason='Known settled model candidate superseded; receipts and settlement retained',
                trace_id=source['trace_id'], correlation_id=source['correlation_id'], causation_id=predecessor_id))
        graph_context = GraphCommandContext(
            project,
            context.actor_id,
            source["trace_id"],
            source["correlation_id"],
            predecessor_id,
        )
        lease = repo.acquire_coordinator(
            saga, owner=context.actor_id, lease_id=str(uuid4()), lease_seconds=30
        )
        command = {
            "definition_name": source["definition_name"],
            "definition_version": target_version,
            "project_id": project,
            "workspace_id": source["workspace_id"],
            "actor_id": context.actor_id,
            "idempotency_scope": source["idempotency_scope"],
            "idempotency_key": source["idempotency_key"]
            + ":successor:"
            + target_version,
            "trace_id": source["trace_id"],
            "span_id": str(uuid4()),
            "correlation_id": source["correlation_id"],
            "causation_id": predecessor_id,
            "input": source["command_payload"],
            "input_assets": source["input_asset_snapshot"],
            "root_operation_id": source["root_operation_id"],
            "parent_operation_id": source["parent_operation_id"],
            "causation_operation_id": predecessor_id,
        }
        admitted = admit_command_in_uow(uow, command, context=context)
        successor = admitted["operation_id"]
        cursor.execute(
            "SELECT depends_on_operation_id,dependency_condition FROM authority_operation_dependency WHERE operation_id=%s",
            [predecessor_id],
        )
        for dependency, condition in cursor.fetchall():
            repo.add_dependency(successor, dependency, condition)
        cursor.execute(
            """INSERT INTO authority_saga_step_successor(successor_id,project_id,saga_id,
            predecessor_operation_id,successor_operation_id,actor_id,contract_version,request_digest,
            source_step_snapshot,source_failure_snapshot,policy_evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                str(uuid4()),
                project,
                saga["saga_id"],
                predecessor_id,
                successor,
                context.actor_id,
                CONTRACT,
                digest,
                Jsonb(step),
                Jsonb({"operation": source, "attempts": attempts}),
                Jsonb(policy_evidence),
            ],
        )
        cursor.execute(
            "UPDATE authority_saga_step SET operation_id=%s WHERE saga_id=%s AND operation_id=%s",
            [successor, saga["saga_id"], predecessor_id],
        )
        if cursor.rowcount != 1:
            raise KernelError(
                "STEP_SUCCESSOR_BINDING_CONFLICT", "Current Saga reference changed"
            )
        cursor.execute(
            "UPDATE authority_operation SET saga_id=%s,step_key=%s WHERE operation_id=%s AND status='ADMITTED'",
            [saga["saga_id"], step["step_key"], successor],
        )
        if cursor.rowcount != 1:
            raise KernelError(
                "STEP_SUCCESSOR_BINDING_CONFLICT", "Current Saga reference changed"
            )
        cursor.execute("UPDATE authority_operation SET version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'", [root["operation_id"], root["version"]])
        if cursor.rowcount != 1:
            raise KernelError("STEP_SUCCESSOR_ROOT_CHANGED", "The current graph fence changed")
        repo.update_saga(saga["saga_id"], saga["version"], saga["status"])
        _record(
            repo,
            graph_context,
            predecessor_id,
            "authority.saga.failed_step_superseded",
            {
                "contract_version": CONTRACT,
                "successor_operation_id": successor,
                "source_step": step,
                "policy_evidence": policy_evidence,
                "provider_invoked": False,
            },
            aggregate_type="authority_saga",
            aggregate_id=saga["saga_id"],
        )
        repo.release_coordinator(
            saga["saga_id"], context.actor_id, lease["fencing_token"]
        )
        uow.commit()
    return {"operation_id": successor, "replayed": False}
