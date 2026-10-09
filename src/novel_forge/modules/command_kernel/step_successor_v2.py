from __future__ import annotations

import hashlib
from contextlib import nullcontext
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from types import SimpleNamespace

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
from .step_successor import require_live_chapter_frontier
from .external_effect_runtime import EffectCommandContext, _read_verified_success
from novel_forge.storage.external_effect_repositories import ExternalEffectRepository

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
    known_isolated_effects=(),
    window_successor=None,
    _uow=None,
    _group_ids=(),
):
    if _group_ids and _uow is None:
        raise KernelError("STEP_SUCCESSOR_GROUP_INVALID", "Grouped exclusions require the owning atomic transaction")
    digest = hashlib.sha256(
        json.dumps(
            {
                "predecessor": predecessor_id,
                "target": target_version,
                "policy": policy_evidence,
                "failure_code": expected_failure_code,
                **({"known_rejected_effects": known_rejected_effects} if known_rejected_effects else {}),
                **({"window_successor": window_successor} if window_successor else {}),
                **({"known_isolated_effects": known_isolated_effects} if known_isolated_effects else {}),
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
    with (nullcontext(_uow) if _uow is not None else AuthorityUnitOfWork(database_url)) as uow:
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
        require_live_chapter_frontier(cursor, root_id=root["operation_id"], project_id=project)
        cursor.execute(
            "SELECT to_jsonb(s) FROM authority_saga_step s WHERE operation_id=%s AND saga_id=%s FOR UPDATE",
            [predecessor_id, saga["saga_id"]],
        )
        row = cursor.fetchone()
        from .context_transport_recovery import require_unsent_context_transport
        unsent_transport = require_unsent_context_transport(cursor, source, policy_evidence)
        memo_contract_repair = bool(
            known_receipt_effects and policy_evidence.get("contract_version") == "chapter-known-receipt.v2"
            and source["definition_name"] == "chapter.memo.generate" and source["definition_version"] == "3.10.0"
            and target_version == "3.10.1" and expected_failure_code == "CHAPTER_MEMO_CHARACTER_DRIFT"
            and policy_evidence.get("character_reference_contract", {}).get("contract_version") == "frozen-character-references.v1"
        )
        memo_completion_repair = (source["definition_name"] == "chapter.memo.generate" and source["definition_version"] == "3.10.1" and target_version == "3.10.2" and policy_evidence.get("completion_revalidation") == "settled-memo-completion.v1")
        if (
            not row
            or source["status"] not in ({"FAILED_RETRYABLE", "FAILED_FINAL", "DEAD_LETTER"} if unsent_transport else {"FAILED_FINAL", "DEAD_LETTER"})
            or root["status"] != "WAITING_CHILDREN"
            or saga["status"] not in ({"RUNNING", "MANUAL_INTERVENTION", "FORWARD_RECOVERY"} if unsent_transport or memo_contract_repair or memo_completion_repair else {"RUNNING", "MANUAL_INTERVENTION"})
            or source["actor_id"] != context.actor_id
            or root["actor_id"] != context.actor_id
            or (source["definition_version"] == target_version and not known_isolated_effects and not unsent_transport)
        ):
            raise KernelError(
                "STEP_SUCCESSOR_SOURCE_INVALID",
                "Only an owned failed child of a live graph can be replaced",
            )
        _require_reconciled_graph(cursor, root_id=root["operation_id"], predecessor_id=predecessor_id)
        step = row[0]
        if saga["status"] == "MANUAL_INTERVENTION":
            cursor.execute(
                """SELECT EXISTS(SELECT 1 FROM authority_saga_step s
                JOIN authority_operation o USING(operation_id) WHERE s.saga_id=%s
                AND o.operation_id<>%s AND NOT (o.operation_id=ANY(%s)) AND (o.status<>'SUCCEEDED' OR s.compensation_status<>'NOT_REQUIRED'))""",
                [saga["saga_id"], predecessor_id, list(_group_ids)],
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
        if memo_completion_repair:
            from novel_forge.modules.chapter_authority.memo_recovery import original_memo_source
            original_memo_source(cursor, source, policy_evidence)
            cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [predecessor_id])
            if any(r[0] not in {"AUTHORITY_HANDLER_CONTRACT_STALE", "RETAINED_COMPLETION_EVIDENCE_INVALID"} for r in cursor.fetchall()):
                raise KernelError("MEMO_COMPLETION_LINEAGE_INVALID", "Only exact implementation completion failures may be revalidated")
            cursor.execute("SELECT v.content FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND o.role='primary'", [predecessor_id])
            results = cursor.fetchall()
            if len(results) != 1 or results[0][0].get("known_receipt_revalidation", {}).get("source_operation_id") != policy_evidence.get("source_operation_id"):
                raise KernelError("MEMO_COMPLETION_LINEAGE_INVALID", "Require the already qualified exact retained Memo")
            output = False
        if known_receipt_effects:
            _require_verified_receipts(cursor, source=source, expected=known_receipt_effects, isolated_siblings=bool(known_isolated_effects))
            cursor.execute(
                "SELECT e.external_effect_id,e.request_hash,e.status,b.status,e.effect_type FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.external_effect_id",
                [predecessor_id],
            )
            if [row for row in cursor.fetchall() if row[0] not in {e[0] for e in (*known_rejected_effects, *known_isolated_effects)}] != [
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
            rejected = [row for row in cursor.fetchall() if row[0] not in {e[0] for e in known_receipt_effects}]
            proofs = policy_evidence.get("schema_rejection_receipts", [])
            if (len(proofs) != len(known_rejected_effects) or any(proof.get("outcome") not in {"PROVIDER_SCHEMA_REJECTED", "COMPLETED_OUTPUT_SCHEMA_FAILURE"} for proof in proofs)
                or {(proof.get("external_effect_id"), proof.get("process_receipt_asset_version_id"), proof.get("process_receipt_hash")) for proof in proofs}
                != {(effect, receipt, receipt_hash) for effect, digest, receipt, receipt_hash in known_rejected_effects}):
                raise KernelError("STEP_SUCCESSOR_REJECTION_UNRECONCILED", "Domain reconciliation must bind each typed Schema rejection")
            if (len(rejected) != len(known_rejected_effects)
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
        if known_isolated_effects:
            from .generation_isolation import isolation
            cursor.execute("SELECT external_effect_id,request_hash FROM authority_external_effect WHERE operation_id=%s ORDER BY external_effect_id", [predecessor_id])
            original_effects = cursor.fetchall()
            isolated = [row for row in original_effects if row[0] not in {e[0] for e in known_receipt_effects}]
            proofs = [isolation(cursor, effect) for effect, request_hash in isolated]
            if (tuple(isolated) != tuple(sorted(known_isolated_effects))
                or not all(proofs) or policy_evidence.get("generation_isolations") != proofs
                or policy_evidence.get("contract_version") != "chapter-pure-generation-successor.v1"
                or any(proof["operation_id"] != predecessor_id or proof["actor_id"] != context.actor_id for proof in proofs)):
                raise KernelError("STEP_SUCCESSOR_ISOLATION_UNPROVEN", "Bind every original effect to its immutable pure generation disposition")
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
        if unsent_transport and source["status"] == "FAILED_RETRYABLE":
            from .attempt_runtime import _cas_operation
            _cas_operation(uow, operation_id=source["operation_id"], project_id=project,
                expected_status=source["status"], expected_version=source["version"], target_status="DEAD_LETTER",
                actor_id=context.actor_id, reason="Exhausted unsent v12 attempts retained before one native v13 transport successor",
                trace_id=source["trace_id"], correlation_id=source["correlation_id"])
            cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [predecessor_id])
            source = cursor.fetchone()[0]
        window = None
        if window_successor:
            window = _corrected_contract_window(cursor, root, source, target, deadline, window_successor, transport_policy=policy_evidence if unsent_transport else None)
            cursor.execute("UPDATE authority_operation SET business_deadline_at=%s WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'", [window["new_deadline"], root["operation_id"], root["version"]])
            if cursor.rowcount != 1:
                raise KernelError("STEP_SUCCESSOR_ROOT_CHANGED", "The execution window fence changed")
            if unsent_transport:
                cursor.execute("UPDATE authority_saga SET root_deadline_at=%s WHERE saga_id=%s AND version=%s", [window["new_deadline"],saga["saga_id"],saga["version"]])
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
        if _uow is None:
            uow.commit()
    return {"operation_id": successor, "replayed": False}


def _corrected_contract_window(cursor, root, source, target, deadline, policy, *, transport_policy=None):
    key, value = policy.get("policy_key"), policy.get("policy_value")
    duration = int(root["definition_snapshot"]["timeout_policy"]["operation_timeout_seconds"])
    transport = (transport_policy is not None and transport_policy.get("contract_version") == "chapter-unsent-context-transport.v1"
        and policy == {"contract_version":"kernel-unsent-transport-window.v1",
            "target_deployment_id":transport_policy.get("target_deployment_id"),"release_sha":transport_policy.get("release_sha")})
    corrected = (policy.get("contract_version") == "kernel-corrected-contract-window.v1"
        and key and value and target["policy"].get(key) == value
        and source["definition_snapshot"]["policy"].get(key) != value)
    if (not (transport or corrected)
        or not deadline or not 0 < duration <= 3600
        or any(k in root["command_payload"] for k in ("business_deadline_at", "author_deadline_at"))):
        raise KernelError("STEP_SUCCESSOR_WINDOW_INVALID", "Only a changed execution contract may continue a derived bounded window")
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
        LEFT JOIN authority_budget_reservation b USING(external_effect_id) WHERE o.root_operation_id=%s
        AND (b.status IS DISTINCT FROM 'SETTLED' OR (e.status<>'SUCCEEDED' AND NOT (
            e.status IN ('FAILED_RETRYABLE','FAILED_FINAL') AND b.accounting_basis='ACCOUNT_ENTITLEMENT'
            AND EXISTS(SELECT 1 FROM authority_saga_step_successor successor,
                jsonb_array_elements(COALESCE(successor.policy_evidence->'schema_rejection_receipts','[]'::jsonb)) proof
                WHERE successor.project_id=o.project_id AND successor.predecessor_operation_id=o.operation_id
                AND proof->>'external_effect_id'=e.external_effect_id
                AND proof->>'outcome' IN ('PROVIDER_SCHEMA_REJECTED','COMPLETED_OUTPUT_SCHEMA_FAILURE')))))),
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
            "rejected-output",
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


def replace_failed_steps(database_url, *, corrections, context, transaction_guard=None):
    if not 1 <= len(corrections) <= 5 or len({c["predecessor_id"] for c in corrections}) != len(corrections):
        raise KernelError("STEP_SUCCESSOR_GROUP_INVALID", "A bounded group needs distinct failed steps")
    from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation_in_uow
    with AuthorityUnitOfWork(database_url) as uow:
        ids = [c["predecessor_id"] for c in corrections]
        uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=ANY(%s) ORDER BY operation_id", [ids])
        sources = [row[0] for row in uow.cursor.fetchall()]
        if (len(sources) != len(ids) or len({(s["project_id"],s["root_operation_id"],s["saga_id"],s["actor_id"]) for s in sources}) != 1
            or sources[0]["actor_id"] != context.actor_id):
            raise KernelError("STEP_SUCCESSOR_GROUP_INVALID", "Every correction must belong to the same owned graph")
        uow.repositories.operation_graph.saga_for_update(sources[0]["saga_id"], sources[0]["project_id"])
        uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=ANY(%s) ORDER BY operation_id FOR UPDATE", [ids])
        sources = [row[0] for row in uow.cursor.fetchall()]
        if transaction_guard:
            transaction_guard(uow)
        for source in sources:
            if source["status"] not in {"READY", "FAILED_RETRYABLE"}:
                continue
            uow.cursor.execute("SELECT status,result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source["operation_id"]])
            attempts = uow.cursor.fetchall()
            maximum = int(source["definition_snapshot"]["retry_policy"].get("max_attempts", 1))
            correction = next(c for c in corrections if c["predecessor_id"] == source["operation_id"])
            if (len(attempts) < maximum or any(a[0] not in {"FAILED_RETRYABLE", "FAILED_FINAL"} for a in attempts)
                or attempts[-1][1] != correction["expected_failure_code"]):
                raise KernelError("STEP_SUCCESSOR_GROUP_NOT_EXHAUSTED", "Active or non-exhausted generations retain their original owner")
            transition_operation_in_uow(uow, OperationTransitionCommand(source["operation_id"],source["project_id"],source["version"],
                source["status"],"DEAD_LETTER",context.actor_id,"Frozen retry budget exhausted; corrected interface successor group",
                source["trace_id"],source["correlation_id"],source["operation_id"]))
        group, results = set(ids), []
        for correction in corrections:
            result = replace_failed_step(database_url, **correction, context=context, transaction_guard=transaction_guard,
                _uow=uow, _group_ids=group)
            group.add(result["operation_id"])
            results.append(result)
        uow.commit()
    return results


def continue_completed_contract_window(database_url, *, predecessor_id, successor_id, context, policy, transaction_guard=None):
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [predecessor_id])
        row = cursor.fetchone()
        if not row:
            raise KernelError("STEP_SUCCESSOR_SOURCE_MISSING", "Missing completed contract predecessor")
        source = row[0]
        repo = uow.repositories.operation_graph
        cursor.execute("SELECT saga_id FROM authority_saga WHERE root_operation_id=%s AND project_id=%s FOR UPDATE", [source["root_operation_id"], source["project_id"]])
        saga_row = cursor.fetchone()
        if not saga_row:
            raise KernelError("STEP_SUCCESSOR_SOURCE_INVALID", "A native owning Saga is required")
        saga = repo.saga_for_update(saga_row[0], source["project_id"])
        cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE", [source["root_operation_id"]])
        root = cursor.fetchone()[0]
        cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR SHARE", [successor_id])
        target = cursor.fetchone()
        if not target:
            raise KernelError("STEP_SUCCESSOR_SOURCE_MISSING", "Missing completed contract successor")
        target = target[0]
        if root["actor_id"] != context.actor_id or not set(source["definition_snapshot"]["permissions"]).issubset(context.permissions):
            raise KernelError("PERMISSION_DENIED", "Contract continuation requires the original owner and permissions")
        key, value = policy.get("policy_key"), policy.get("policy_value")
        cursor.execute("""SELECT payload FROM state_event WHERE aggregate_id=%s AND project_id=%s
            AND event_type='authority.operation.completed_contract_window_continued'
            AND payload->'execution_window'->>'policy_key'=%s AND payload->'execution_window'->>'policy_value'=%s""",
            [root["operation_id"], source["project_id"], key, value])
        previous = cursor.fetchone()
        if previous:
            if (previous[0].get("predecessor_operation_id") != predecessor_id
                or previous[0].get("successor_operation_id") != successor_id):
                raise KernelError("STEP_SUCCESSOR_IDEMPOTENCY_CONFLICT", "The same contract cannot renew an execution window repeatedly")
            return {"replayed": True, "execution_window": previous[0]["execution_window"]}
        if (root["status"] != "WAITING_CHILDREN" or saga["status"] != "RUNNING"
            or source["status"] != "SUCCEEDED" or target["status"] != "SUCCEEDED"
            or root["actor_id"] != context.actor_id or source["actor_id"] != context.actor_id or target["actor_id"] != context.actor_id
            or source["project_id"] != target["project_id"] or source["root_operation_id"] != target["root_operation_id"]
            or source["definition_name"] != target["definition_name"] or source["definition_version"] == target["definition_version"]
            or source["input_asset_snapshot"] != target["input_asset_snapshot"]
            or not set(source["definition_snapshot"]["permissions"]).issubset(context.permissions)):
            raise KernelError("STEP_SUCCESSOR_SOURCE_INVALID", "An owned live Root and exact completed contract lineage are required")
        for field in ("handler_key", "permissions", "command_schema", "result_schema", "completion_contract", "external_capabilities"):
            if source["definition_snapshot"][field] != target["definition_snapshot"][field]:
                raise KernelError("STEP_SUCCESSOR_CONTRACT_CHANGED", "Completed contract continuation cannot weaken execution requirements")
        cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id IN (%s,%s,%s)),
            EXISTS(SELECT 1 FROM authority_operation_dependency WHERE operation_id=%s AND depends_on_operation_id=%s AND dependency_condition='ON_SUCCESS')""",
            [root["operation_id"], predecessor_id, successor_id, successor_id, predecessor_id])
        cancelled, linked = cursor.fetchone()
        if cancelled or not linked:
            raise KernelError("STEP_SUCCESSOR_SOURCE_INVALID", "Cancellation or missing native causal linkage prevents continuation")
        require_live_chapter_frontier(cursor, root_id=root["operation_id"], project_id=source["project_id"])
        if transaction_guard is not None:
            transaction_guard(uow)
        _require_reconciled_graph(cursor, root_id=root["operation_id"], predecessor_id=predecessor_id)
        window = _corrected_contract_window(cursor, root, source, target["definition_snapshot"], datetime.fromisoformat(root["business_deadline_at"]), policy)
        cursor.execute("""UPDATE authority_operation SET business_deadline_at=%s,version=version+1,updated_at=NOW()
            WHERE operation_id=%s AND version=%s AND status='WAITING_CHILDREN'""", [window["new_deadline"], root["operation_id"], root["version"]])
        if cursor.rowcount != 1:
            raise KernelError("STEP_SUCCESSOR_ROOT_CHANGED", "The execution window fence changed")
        _record(repo, GraphCommandContext(source["project_id"], context.actor_id, root["trace_id"], root["correlation_id"], successor_id),
            root["operation_id"], "authority.operation.completed_contract_window_continued",
            {"contract_version": "kernel-completed-contract-window.v1", "predecessor_operation_id": predecessor_id,
                "successor_operation_id": successor_id, "input_asset_snapshot": source["input_asset_snapshot"],
                "execution_window": window, "domain_outputs": "PRESERVED", "resource_authorization": "UNCHANGED"})
        uow.commit()
    return {"replayed": False, "execution_window": window}


def _require_reconciled_graph(cursor, *, root_id, predecessor_id):
    from .budget_runtime import require_known_cli_lineage

    cursor.execute("SELECT project_id FROM authority_operation WHERE operation_id=%s", [root_id])
    owner = cursor.fetchone()
    if not owner:
        raise KernelError("STEP_SUCCESSOR_GRAPH_UNRECONCILED", "The original graph scope is missing")
    require_known_cli_lineage(cursor, project_id=str(owner[0]), operation_id=root_id)
    cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_external_effect e
        JOIN authority_operation o USING(operation_id)
        LEFT JOIN authority_budget_reservation b USING(external_effect_id)
        WHERE o.root_operation_id=%s AND (e.status IN
        ('UNKNOWN','DISPATCHING','RECONCILIATION_REQUIRED','PENDING')
        OR b.status IS DISTINCT FROM 'SETTLED') AND NOT authority_generation_isolated(e.external_effect_id)),
        EXISTS(SELECT 1 FROM authority_lease_acquisition l
        JOIN authority_attempt a USING(attempt_id)
        JOIN authority_operation o USING(operation_id)
        WHERE o.root_operation_id=%s AND l.released_at IS NULL AND l.expires_at>NOW()),
        EXISTS(SELECT 1 FROM authority_cancellation_command
        WHERE operation_id IN (%s,%s))""",
        [root_id,root_id,root_id,predecessor_id],
    )
    if any(cursor.fetchone()):
        raise KernelError("STEP_SUCCESSOR_GRAPH_UNRECONCILED",
                          "Reconcile every outcome, settle accounting and release leases before succession")


def _require_verified_receipts(cursor, *, source, expected, isolated_siblings=False):
    context = EffectCommandContext(operation_id=source["operation_id"],
        project_id=source["project_id"], actor_id=source["actor_id"],
        trace_id=source["trace_id"], correlation_id=source["correlation_id"])
    repository = ExternalEffectRepository(cursor)
    for effect_id, request_hash in expected:
        effect = repository.get_for_update(effect_id)
        if effect["operation_id"] != source["operation_id"] or effect["request_hash"] != request_hash:
            raise KernelError("STEP_SUCCESSOR_RECEIPT_DRIFT", "Bind the exact original effect and request")
        verified = (_read_verified_success(SimpleNamespace(cursor=cursor), repository, context, effect_id, retained_generation_stage=True) if isolated_siblings else _read_verified_success(SimpleNamespace(cursor=cursor), repository, context, effect_id))
        if verified is None or verified["budget_reservation_status"] != "SETTLED":
            raise KernelError("STEP_SUCCESSOR_RECEIPT_UNSETTLED", "Require Kernel-verified success and settled accounting")
