from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
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

CONTRACT = "kernel-failed-step-successor.v2"


def replace_failed_step(
    database_url,
    *,
    predecessor_id,
    target_version,
    context: AdmissionContext,
    policy_evidence,
    expected_failure_code,
    transaction_guard=None,
    known_receipt_effects=(),
    known_rejected_effects=(),
    window_successor=None,
):
    digest = hashlib.sha256(
        json.dumps(
            {
                "predecessor": predecessor_id,
                "target": target_version,
                "policy": policy_evidence,
                "failure_code": expected_failure_code,
                **({"known_rejected_effects": known_rejected_effects} if known_rejected_effects else {}),
                **({"window_successor": window_successor} if window_successor else {}),
                **(
                    {"known_receipt_effects": known_receipt_effects}
                    if known_receipt_effects
                    else {}
                ),
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute(
            "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s",
            [predecessor_id],
        )
        row = cursor.fetchone()
        if not row:
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_MISSING", "Missing native predecessor"
            )
        source = row[0]
        project = source["project_id"]
        repo = uow.repositories.operation_graph
        saga = repo.saga_for_update(source["saga_id"], project)
        cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE", [predecessor_id])
        source = cursor.fetchone()[0]
        if source["actor_id"] != context.actor_id:
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_INVALID", "Recovery requires the original actor"
            )
        if not set(source["definition_snapshot"]["permissions"]).issubset(
            context.permissions
        ):
            raise KernelError(
                "PERMISSION_DENIED",
                "Recovery requires the original command permissions",
            )
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
        if (
            not row
            or source["status"] not in {"FAILED_FINAL", "DEAD_LETTER"}
            or root["status"] != "WAITING_CHILDREN"
            or saga["status"] not in {"RUNNING", "MANUAL_INTERVENTION"}
            or source["actor_id"] != context.actor_id
            or root["actor_id"] != context.actor_id
            or source["definition_version"] == target_version
        ):
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_INVALID",
                "Only an owned failed child of a live graph can be replaced",
            )
        step = row[0]
        if saga["status"] == "MANUAL_INTERVENTION":
            cursor.execute(
                """SELECT EXISTS(SELECT 1 FROM authority_saga_step s
                JOIN authority_operation o USING(operation_id) WHERE s.saga_id=%s
                AND o.operation_id<>%s AND (o.status<>'SUCCEEDED' OR s.compensation_status<>'NOT_REQUIRED'))""",
                [saga["saga_id"], predecessor_id],
            )
            if cursor.fetchone()[0]:
                raise KernelError(
                    "STEP_SUCCESSOR_OTHER_BLOCKER",
                    "Only the exact local failed step may block the stopped graph",
                )
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
        if deadline and deadline <= datetime.now(timezone.utc) and not window_successor:
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
        if output:
            output = has_domain_outputs(cursor, predecessor_id)
        if known_receipt_effects:
            cursor.execute(
                "SELECT e.external_effect_id,e.request_hash,e.status,b.status,e.effect_type FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id",
                [predecessor_id],
            )
            if cursor.fetchall() != [
                (effect, digest, "SUCCEEDED", "SETTLED", "model.invoke")
                for effect, digest in sorted(known_receipt_effects)
            ]:
                raise KernelError(
                    "STEP_SUCCESSOR_RECEIPT_UNSETTLED",
                    "Exact succeeded settled receipts are required",
                )
            external = False
            output = has_domain_outputs(cursor, predecessor_id)
        if known_rejected_effects:
            cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.status,b.status,b.accounting_basis,
                e.last_error->'production_execution'->'execution_result'->>'process_receipt_ref'
                FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id)
                WHERE e.operation_id=%s ORDER BY e.external_effect_id""", [predecessor_id])
            rejected = cursor.fetchall()
            proofs = policy_evidence.get("schema_rejection_receipts", [])
            if (len(proofs) != len(known_rejected_effects) or any(proof.get("outcome") != "PROVIDER_SCHEMA_REJECTED" for proof in proofs)
                or {(proof.get("external_effect_id"), proof.get("process_receipt_asset_version_id"), proof.get("process_receipt_hash")) for proof in proofs}
                != {(effect, receipt, receipt_hash) for effect, digest, receipt, receipt_hash in known_rejected_effects}):
                raise KernelError("STEP_SUCCESSOR_REJECTION_UNRECONCILED", "Domain reconciliation must bind each typed Schema rejection")
            if (known_receipt_effects or len(rejected) != len(known_rejected_effects)
                or any((row[0], row[1], row[5]) != (effect, digest, "authority-asset-version:" + receipt)
                    or row[2] not in {"FAILED_RETRYABLE", "FAILED_FINAL"} or row[3:5] != ("SETTLED", "ACCOUNT_ENTITLEMENT")
                    for row, (effect, digest, receipt, receipt_hash) in zip(rejected, sorted(known_rejected_effects)))):
                raise KernelError("STEP_SUCCESSOR_REJECTION_UNRECONCILED", "Exact terminal membership rejection receipts are required")
            for effect, digest, receipt, receipt_hash in known_rejected_effects:
                cursor.execute("SELECT v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s", [receipt, project])
                if cursor.fetchone() != (receipt_hash,):
                    raise KernelError("STEP_SUCCESSOR_REJECTION_UNRECONCILED", "Immutable process receipt identity changed")
            external = False
            output = has_domain_outputs(cursor, predecessor_id)
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
        window = None
        if window_successor:
            window = _corrected_contract_window(cursor, root, source, target, deadline, window_successor)
            cursor.execute("UPDATE authority_operation SET business_deadline_at=%s WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'", [window["new_deadline"], root["operation_id"], root["version"]])
            if cursor.rowcount != 1:
                raise KernelError("STEP_SUCCESSOR_ROOT_CHANGED", "The execution window fence changed")
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
            source_saga_snapshot,source_step_snapshot,source_failure_snapshot,policy_evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                str(uuid4()),
                project,
                saga["saga_id"],
                predecessor_id,
                successor,
                context.actor_id,
                CONTRACT,
                digest,
                Jsonb(saga),
                Jsonb(step),
                Jsonb({"operation": source, "attempts": attempts, **({"root": root, "execution_window": window} if window else {})}),
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
        cursor.execute(
            "UPDATE authority_operation SET version=version+1,updated_at=NOW() WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'",
            [root["operation_id"], root["version"]],
        )
        if cursor.rowcount != 1:
            raise KernelError(
                "STEP_SUCCESSOR_ROOT_CHANGED", "The current graph fence changed"
            )
        repo.update_saga(saga["saga_id"], saga["version"], "RUNNING")
        _record(
            repo,
            graph_context,
            predecessor_id,
            "authority.saga.failed_step_superseded",
            {
                "contract_version": CONTRACT,
                "successor_operation_id": successor,
                "source_step": step,
                "source_saga": saga,
                "target_saga_status": "RUNNING",
                "policy_evidence": policy_evidence,
                "provider_invoked": False,
                **({"execution_window": window} if window else {}),
            },
            aggregate_type="authority_saga",
            aggregate_id=saga["saga_id"],
        )
        repo.release_coordinator(
            saga["saga_id"], context.actor_id, lease["fencing_token"]
        )
        uow.commit()
    return {"operation_id": successor, "replayed": False}


def _corrected_contract_window(cursor, root, source, target, deadline, policy):
    key, value = policy.get("policy_key"), policy.get("policy_value")
    duration = int(root["definition_snapshot"]["timeout_policy"]["operation_timeout_seconds"])
    if (policy.get("contract_version") != "kernel-corrected-contract-window.v1"
        or not key or not value or target["policy"].get(key) != value
        or source["definition_snapshot"]["policy"].get(key) == value
        or not deadline or not 0 < duration <= 3600
        or any(k in root["command_payload"] for k in ("business_deadline_at", "author_deadline_at"))):
        raise KernelError("STEP_SUCCESSOR_WINDOW_INVALID", "Only a changed execution contract may continue a derived bounded window")
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        LEFT JOIN authority_budget_reservation b USING(external_effect_id) WHERE o.root_operation_id=%s
        AND (e.status<>'SUCCEEDED' OR b.status IS DISTINCT FROM 'SETTLED')),
        EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
        JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s
        AND l.released_at IS NULL AND l.expires_at>NOW())""", [root["operation_id"]]*2)
    if any(cursor.fetchone()):
        raise KernelError("STEP_SUCCESSOR_WINDOW_UNSETTLED", "Reconcile every effect and release every lease before continuing")
    return {**policy, "original_deadline": deadline.isoformat(),
        "new_deadline": max(deadline, datetime.now(timezone.utc)+timedelta(seconds=duration)).isoformat(),
        "duration_seconds": duration, "terminal_history": "PRESERVED", "resource_authorization": "UNCHANGED"}


def has_domain_outputs(cursor, operation_id):
    cursor.execute(
        "SELECT a.asset_type,o.role FROM authority_operation_output_asset o JOIN authority_asset a USING(asset_id) WHERE o.operation_id=%s",
        [operation_id],
    )
    contracts = {
        "capability_materialization_manifest",
        "execution_commit_policy",
        "execution_context_policy",
        "execution_source_policy",
        "execution_validation_policy",
        "fallback_policy",
        "input_manifest",
        "model_profile",
        "prompt_bundle",
        "provider_request_admission_manifest",
        "route_policy",
        "route_snapshot",
        "skill_bundle",
        "tool_permission_snapshot",
    }
    allowed = {(t, "execution_contract") for t in contracts}
    allowed |= {
        ("execution_evidence", r)
        for r in (
            "cost-receipt",
            "normalized-output",
            "output-manifest",
            "process-receipt",
            "raw-output",
            "usage-receipt",
            "validation-manifest",
        )
    }
    allowed |= {
        ("cost_ledger", "cost_evidence"),
        ("execution_recovery_session", "execution_recovery_projection"),
        ("model_call_log", "model_evidence"),
        ("model_call_log", "model_failure_evidence"),
        ("routing_decision", "routing_evidence"),
    }
    return any(tuple(row) not in allowed for row in cursor.fetchall())
