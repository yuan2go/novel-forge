"""PostgreSQL Canon approval commands and strong queries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from novel_forge.modules.canon_graph.approval_domain import (
    CANON_DECISIONS,
    validate_edited_canon_payload,
)
from novel_forge.modules.canon_graph.reextraction_policy import CanonReextractionPolicy
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    transition_saga_gate,
)
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


CANON_APPROVAL_DEFINITION_NAME = "canon.change.approve"
CANON_APPROVAL_DEFINITION_VERSION = "1.0.0"
CANON_APPROVAL_HANDLER_KEY = "novel_forge.canon.change.approve"


@dataclass(frozen=True, slots=True)
class CanonApprovalContext:
    project_id: str
    principal_id: str
    trace_id: str
    correlation_id: str


def ensure_canon_approval_requests(database_url: str, context: CanonApprovalContext, *, root_operation_id: str, saga_id: str, proposal_asset_version_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal.get("project_id") != context.project_id:
        raise KernelError("CROSS_PROJECT_REFERENCE", "Canon proposal belongs to another project")
    required = [item for item in proposal.get("changes", []) if item.get("approval_requirement") == "REQUIRED"]
    if not required:
        return {"waiting": False, "approval_request_ids": []}
    ids: list[str] = []
    generation = int(proposal.get("generation") or 1)
    with AuthorityUnitOfWork(database_url) as uow:
        for change in required:
            request_id = "canon-approval:" + hashlib.sha256(f"{context.project_id}:{proposal_asset_version_id}:{change['change_id']}".encode()).hexdigest()
            uow.cursor.execute(
                """
                INSERT INTO authority_canon_approval_request (
                    approval_request_id, project_id, root_operation_id, saga_id,
                    proposal_asset_version_id, change_id, change_type, risk, expires_at,
                    proposal_generation
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW() + INTERVAL '24 hours',%s)
                ON CONFLICT (project_id, proposal_asset_version_id, change_id) DO NOTHING
                """,
                [request_id, context.project_id, root_operation_id, saga_id, proposal_asset_version_id, change["change_id"], change["change_type"], json.dumps({"impact_level": change["impact_level"], "confidence": change["confidence"], "evidence_digest": change["evidence_digest"]}), generation],
            )
            ids.append(request_id)
        uow.cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id = %s AND project_id = %s FOR UPDATE",
            [root_operation_id, context.project_id],
        )
        root = uow.cursor.fetchone()
        if root is None:
            raise KernelError("OPERATION_NOT_FOUND", "Canon gate root Operation is missing")
        uow.cursor.execute("SELECT COUNT(*) FROM authority_canon_approval_request WHERE root_operation_id = %s AND status NOT IN ('APPROVED','REJECTED','EDITED_AND_APPROVED','INVALIDATED','EXPIRED')", [root_operation_id])
        unresolved = int(uow.cursor.fetchone()[0])
        _event(uow, context, root_operation_id, "canon.approval.requested", {"proposal_asset_version_id": proposal_asset_version_id, "approval_request_ids": ids})
        uow.commit()
    if unresolved == 0:
        return {"waiting": False, "approval_request_ids": ids}
    if root[0] != "WAITING_GATE":
        with AuthorityUnitOfWork(database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(root_operation_id, context.project_id)
        transition_operation(database_url, OperationTransitionCommand(
            operation_id=root_operation_id, project_id=context.project_id,
            expected_version=int(state["version"]), expected_status=str(state["status"]),
            target_status="WAITING_GATE", actor_id=context.principal_id,
            reason="high-impact Canon changes require per-change approval",
            trace_id=context.trace_id, correlation_id=context.correlation_id,
            causation_id=proposal_asset_version_id,
        ))
    transition_saga_gate(
        database_url,
        _graph_context(context, proposal_asset_version_id),
        saga_id,
        target_status="WAITING_GATE",
        reason="high-impact Canon changes require per-change approval",
    )
    return {"waiting": True, "approval_request_ids": ids}


def decide_canon_approval(database_url: str, context: CanonApprovalContext, *, approval_request_id: str, expected_version: int, decision: str, reason: str, evidence: dict[str, Any], edited_payload: dict[str, Any] | None, idempotency_key: str, reextraction_policy: CanonReextractionPolicy | None = None) -> dict[str, Any]:
    if decision not in CANON_DECISIONS or not reason.strip() or not idempotency_key.strip():
        raise KernelError("CANON_APPROVAL_COMMAND_INVALID", "decision, reason, and idempotency key are required")
    policy = reextraction_policy or CanonReextractionPolicy()
    if decision == "REQUEST_REEXTRACTION":
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                "SELECT root_operation_id FROM authority_canon_approval_request WHERE approval_request_id=%s AND project_id=%s",
                [approval_request_id, context.project_id],
            )
            root_row = uow.cursor.fetchone()
            if root_row is None:
                raise KernelError("CANON_APPROVAL_NOT_FOUND", "Canon approval request does not exist")
            uow.cursor.execute(
                "SELECT COALESCE(MAX(proposal_generation), 1) + 1 FROM authority_canon_approval_request WHERE root_operation_id=%s",
                [root_row[0]],
            )
            policy.require_generation(int(uow.cursor.fetchone()[0]))
    operation = _admit_decision_operation(
        database_url,
        context,
        approval_request_id=approval_request_id,
        expected_version=expected_version,
        decision=decision,
        reason=reason,
        evidence=evidence,
        edited_payload=edited_payload,
        idempotency_key=idempotency_key,
    )
    if operation.get("completed_result") is not None:
        return dict(operation["completed_result"])
    lease_command = _start_decision_attempt(database_url, context, operation)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT project_id, root_operation_id, saga_id, proposal_asset_version_id, change_id, status, version, expires_at FROM authority_canon_approval_request WHERE approval_request_id = %s FOR UPDATE", [approval_request_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("CANON_APPROVAL_NOT_FOUND", "Canon approval request does not exist")
        project_id, root_id, saga_id, proposal_id, change_id, status, version, expires_at = row
        if project_id != context.project_id:
            raise KernelError("CROSS_PROJECT_REFERENCE", "Canon approval belongs to another project")
        digest_payload = {"decision": decision, "reason": reason, "evidence": evidence, "edited_payload": edited_payload}
        request_digest = "sha256:" + hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        uow.cursor.execute("SELECT request_digest, asset_version_id FROM authority_canon_approval_decision WHERE project_id = %s AND approval_request_id = %s AND idempotency_key = %s", [project_id, approval_request_id, idempotency_key])
        replay = uow.cursor.fetchone()
        if replay:
            if replay[0] != request_digest:
                raise KernelError("IDEMPOTENCY_CONFLICT", "Canon approval idempotency key payload changed")
            return {"approval_request_id": approval_request_id, "decision": decision, "asset_version_id": replay[1], "replayed": True}
        if int(version) != expected_version or status != "PENDING":
            raise KernelError("CANON_APPROVAL_VERSION_CONFLICT", "Canon approval request changed")
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise KernelError("CANON_APPROVAL_EXPIRED", "Canon approval request expired")
        if decision == "EDIT_AND_APPROVE" and not edited_payload:
            raise KernelError("CANON_EDITED_PAYLOAD_REQUIRED", "edited approval requires a payload")
        uow.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id = %s",
            [proposal_id],
        )
        proposal_content = dict(uow.cursor.fetchone()[0])
        change = next(
            (item for item in proposal_content.get("changes", []) if item.get("change_id") == change_id),
            None,
        )
        if change is None:
            raise KernelError("CANON_CHANGE_NOT_FOUND", "approval change is absent from proposal")
        resolution = None
        resolution_asset_version_id = None
        if decision == "EDIT_AND_APPROVE":
            resolution = validate_edited_canon_payload(
                project_id=project_id,
                change=dict(change),
                edited_payload=dict(edited_payload or {}),
            )
        defer_until = None
        required_information = ""
        assigned_operator = ""
        expiry_policy = "REOPEN"
        if decision == "DEFER":
            try:
                defer_until = datetime.fromisoformat(
                    str(evidence["defer_until"]).replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError) as error:
                raise KernelError(
                    "CANON_DEFER_POLICY_INVALID",
                    "DEFER requires an ISO defer_until timestamp",
                ) from error
            if defer_until.tzinfo is None:
                defer_until = defer_until.replace(tzinfo=timezone.utc)
            required_information = str(evidence.get("required_information") or "").strip()
            assigned_operator = str(evidence.get("assigned_operator") or "").strip()
            expiry_policy = str(evidence.get("expiry_policy") or "REOPEN").upper()
            if (
                defer_until <= datetime.now(timezone.utc)
                or not required_information
                or not assigned_operator
                or expiry_policy not in {"REOPEN", "EXPIRE"}
            ):
                raise KernelError(
                    "CANON_DEFER_POLICY_INVALID",
                    "DEFER requires a future deadline, information, operator, and expiry policy",
                )
        content = {
            "type": "CanonApprovalDecision", "project_id": project_id,
            "approval_request_id": approval_request_id, "proposal_asset_version_id": proposal_id,
            "change_id": change_id, "decision": decision, "reason": reason,
            "evidence": evidence, "edited_payload": edited_payload or {},
            "change_resolution": resolution or {},
            "principal_id": context.principal_id, "contract_version": "canon-approval-decision-v1",
        }
        content_hash = "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        asset_id = "canon-decision-asset:" + hashlib.sha256(
            f"{project_id}:{approval_request_id}:{request_digest}".encode()
        ).hexdigest()
        asset_version_id = "canon-decision-version:" + hashlib.sha256(f"{approval_request_id}:{request_digest}".encode()).hexdigest()
        created = uow.repositories.chapter_authority.materialize_output(
            operation_id=str(operation["operation_id"]), project_id=project_id, asset_id=asset_id,
            asset_version_id=asset_version_id, qualification_id=f"{asset_version_id}:qualification",
            asset_type="canon_approval_decision", output_key=f"canon.approval.decision.{change_id}",
            role="approval_decision", content=content, content_hash=content_hash,
            qualification_policy="canon-approval-decision-v1",
            qualification_evidence={"principal_id": context.principal_id, "decision": decision},
        )
        if resolution is not None:
            resolution_hash = "sha256:" + hashlib.sha256(
                json.dumps(resolution, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            resolution_asset_version_id = "canon-resolution-version:" + hashlib.sha256(
                f"{approval_request_id}:{request_digest}".encode()
            ).hexdigest()
            uow.repositories.chapter_authority.materialize_output(
                operation_id=str(operation["operation_id"]), project_id=project_id,
                asset_id="canon-resolution-asset:" + hashlib.sha256(
                    f"{project_id}:{approval_request_id}:{request_digest}".encode()
                ).hexdigest(),
                asset_version_id=resolution_asset_version_id,
                qualification_id=f"{resolution_asset_version_id}:qualification",
                asset_type="canon_change_resolution",
                output_key=f"canon.approval.resolution.{change_id}",
                role="approval_resolution", content=resolution,
                content_hash=resolution_hash,
                qualification_policy="canon-change-resolution-v1",
                qualification_evidence={"change_id": change_id, "validated": True},
            )
        status_target = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "EDIT_AND_APPROVE": "EDITED_AND_APPROVED", "DEFER": "DEFERRED", "REQUEST_REEXTRACTION": "REEXTRACTION_REQUESTED"}[decision]
        uow.cursor.execute("UPDATE authority_canon_approval_request SET status = %s, version = version + 1, defer_until=%s, required_information=%s, assigned_operator=%s, expiry_policy=%s, updated_at = NOW() WHERE approval_request_id = %s AND version = %s", [status_target, defer_until, required_information, assigned_operator, expiry_policy, approval_request_id, expected_version])
        uow.cursor.execute("INSERT INTO authority_canon_approval_decision (approval_decision_id, approval_request_id, project_id, decision, reason, evidence, edited_payload, principal_id, idempotency_key, request_digest, asset_version_id, decision_operation_id, resolution_asset_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [str(uuid4()), approval_request_id, project_id, decision, reason, json.dumps(evidence), json.dumps(edited_payload) if edited_payload else None, context.principal_id, idempotency_key, request_digest, asset_version_id, operation["operation_id"], resolution_asset_version_id])
        if decision == "REQUEST_REEXTRACTION":
            uow.cursor.execute(
                "SELECT COALESCE(MAX(proposal_generation), 1) + 1 FROM authority_canon_approval_request WHERE root_operation_id = %s",
                [root_id],
            )
            next_generation = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                "UPDATE authority_canon_approval_request SET status='INVALIDATED', version=version+1, updated_at=NOW() WHERE root_operation_id=%s AND proposal_asset_version_id=%s",
                [root_id, proposal_id],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_canon_reextraction_generation (
                    reextraction_generation_id, project_id, root_operation_id,
                    saga_id, generation, status,
                    supersedes_proposal_asset_version_id, invalidation_reason,
                    created_by_decision_asset_version_id, policy_snapshot, deadline_at
                ) VALUES (%s,%s,%s,%s,%s,'REEXTRACTION_PENDING',%s,%s,%s,%s,%s)
                ON CONFLICT (project_id, root_operation_id, generation) DO NOTHING
                """,
                [
                    str(uuid4()), project_id, root_id, saga_id, next_generation,
                    proposal_id, reason, asset_version_id, json.dumps(policy.snapshot()),
                    datetime.now(timezone.utc) + timedelta(seconds=policy.generation_timeout_seconds),
                ],
            )
        _event(uow, context, str(operation["operation_id"]), "canon.approval.decided", {"approval_request_id": approval_request_id, "change_id": change_id, "decision": decision, "asset_version_id": asset_version_id, "root_operation_id": root_id})
        uow.cursor.execute("SELECT COUNT(*) FILTER (WHERE status NOT IN ('APPROVED','REJECTED','EDITED_AND_APPROVED','INVALIDATED','EXPIRED')), COUNT(*) FROM authority_canon_approval_request WHERE root_operation_id = %s", [root_id])
        unresolved, total = uow.cursor.fetchone()
        if decision != "REQUEST_REEXTRACTION" and total and not unresolved:
            uow.cursor.execute(
                """
                UPDATE authority_canon_reextraction_generation
                   SET status='RESOLVED', updated_at=NOW()
                 WHERE project_id=%s AND root_operation_id=%s
                   AND proposal_asset_version_id=%s
                   AND status='WAITING_APPROVAL'
                """,
                [project_id, root_id, proposal_id],
            )
        uow.commit()
    with AuthorityUnitOfWork(database_url) as uow:
        operation_state = uow.repositories.attempt_runtime.operation_state(
            str(operation["operation_id"]), project_id
        )
    submit_attempt_result(
        database_url,
        WorkerResultCommand(
            **lease_command.__dict__,
            expected_operation_version=int(operation_state["version"]),
            expected_operation_status=str(operation_state["status"]),
        ),
        outcome="success",
        result={"asset_version_id": asset_version_id, "content_hash": content_hash},
    )
    if decision != "REQUEST_REEXTRACTION" and total and not unresolved:
        with AuthorityUnitOfWork(database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(root_id, project_id)
        transition_operation(database_url, OperationTransitionCommand(
            operation_id=root_id, project_id=project_id, expected_version=int(state["version"]),
            expected_status=str(state["status"]), target_status="WAITING_CHILDREN",
            actor_id=context.principal_id, reason="Canon approval gate resolved",
            trace_id=context.trace_id, correlation_id=context.correlation_id,
            causation_id=approval_request_id,
        ))
        transition_saga_gate(
            database_url,
            _graph_context(context, approval_request_id),
            saga_id,
            target_status="RUNNING",
            reason="all Canon approval changes have terminal decisions",
        )
    return {"approval_request_id": approval_request_id, "decision": decision, "asset_version_id": asset_version_id, "resolution_asset_version_id": resolution_asset_version_id or "", "decision_operation_id": operation["operation_id"], "replayed": not created, "gate_resumed": bool(decision != "REQUEST_REEXTRACTION" and total and not unresolved), "reextraction_requested": decision == "REQUEST_REEXTRACTION"}


def _admit_decision_operation(
    database_url: str,
    context: CanonApprovalContext,
    *,
    approval_request_id: str,
    expected_version: int,
    decision: str,
    reason: str,
    evidence: dict[str, Any],
    edited_payload: dict[str, Any] | None,
    idempotency_key: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT request.project_id, request.root_operation_id,
                   request.proposal_asset_version_id, root.workspace_id,
                   root.definition_snapshot, proposal.content_hash,
                   request.status, request.version, request.expires_at
            FROM authority_canon_approval_request request
            JOIN authority_operation root ON root.operation_id = request.root_operation_id
            JOIN authority_asset_version proposal
              ON proposal.asset_version_id = request.proposal_asset_version_id
            WHERE request.approval_request_id = %s
            """,
            [approval_request_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("CANON_APPROVAL_NOT_FOUND", "Canon approval request does not exist")
        project_id, root_id, proposal_id, workspace_id, snapshot, proposal_hash, request_status, request_version, expires_at = row
        if project_id != context.project_id:
            raise KernelError("CROSS_PROJECT_REFERENCE", "Canon approval belongs to another project")
        requested_digest = "sha256:" + hashlib.sha256(
            json.dumps(
                {"decision": decision, "reason": reason, "evidence": evidence, "edited_payload": edited_payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        uow.cursor.execute(
            """
            SELECT decision, asset_version_id, decision_operation_id, request_digest
            FROM authority_canon_approval_decision
            WHERE project_id = %s AND approval_request_id = %s AND idempotency_key = %s
            """,
            [project_id, approval_request_id, idempotency_key],
        )
        existing_decision = uow.cursor.fetchone()
        if existing_decision:
            if existing_decision[3] != requested_digest:
                raise KernelError("IDEMPOTENCY_CONFLICT", "Canon approval idempotency key payload changed")
            return {
                "operation_id": existing_decision[2],
                "completed_result": {
                    "approval_request_id": approval_request_id,
                    "decision": existing_decision[0],
                    "asset_version_id": existing_decision[1],
                    "decision_operation_id": existing_decision[2],
                    "replayed": True,
                    "gate_resumed": existing_decision[0] in {
                        "APPROVE", "REJECT", "EDIT_AND_APPROVE"
                    },
                    "reextraction_requested": existing_decision[0]
                    == "REQUEST_REEXTRACTION",
                },
            }
        if int(request_version) != expected_version or request_status != "PENDING":
            raise KernelError("CANON_APPROVAL_VERSION_CONFLICT", "Canon approval request changed")
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise KernelError("CANON_APPROVAL_EXPIRED", "Canon approval request expired")
        definition = canon_approval_operation_definition(
            application_build_id=str(snapshot["application_build_id"]),
            commit_sha=str(snapshot["commit_sha"]),
        )
        uow.repositories.definitions.register(definition)
        uow.commit()
    admitted = admit_command(
        database_url,
        {
            "definition_name": CANON_APPROVAL_DEFINITION_NAME,
            "definition_version": CANON_APPROVAL_DEFINITION_VERSION,
            "project_id": context.project_id,
            "workspace_id": str(workspace_id),
            "actor_id": context.principal_id,
            "idempotency_scope": "project:canon-approval",
            "idempotency_key": f"{approval_request_id}:{idempotency_key}",
            "trace_id": context.trace_id,
            "span_id": str(uuid4()),
            "correlation_id": context.correlation_id,
            "causation_id": approval_request_id,
            "parent_operation_id": root_id,
            "root_operation_id": root_id,
            "causation_operation_id": root_id,
            "input": {
                "approval_request_id": approval_request_id,
                "expected_version": expected_version,
                "decision": decision,
                "reason": reason,
                "evidence": evidence,
                "edited_payload": edited_payload or {},
            },
            "input_assets": [{"asset_version_id": proposal_id, "content_hash": proposal_hash}],
        },
        context=AdmissionContext(
            actor_id=context.principal_id,
            permissions=frozenset({"canon.authority.approve"}),
            available_handlers=frozenset({CANON_APPROVAL_HANDLER_KEY}),
            application_build_id=str(snapshot["application_build_id"]),
            commit_sha=str(snapshot["commit_sha"]),
        ),
    )
    operation_id = str(admitted["operation_id"])
    if admitted["replayed"]:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                "SELECT decision, asset_version_id FROM authority_canon_approval_decision WHERE decision_operation_id = %s",
                [operation_id],
            )
            completed = uow.cursor.fetchone()
        if completed:
            return {
                "operation_id": operation_id,
                "completed_result": {
                    "approval_request_id": approval_request_id,
                    "decision": completed[0],
                    "asset_version_id": completed[1],
                    "decision_operation_id": operation_id,
                    "replayed": True,
                    "gate_resumed": completed[0] in {
                        "APPROVE", "REJECT", "EDIT_AND_APPROVE"
                    },
                    "reextraction_requested": completed[0]
                    == "REQUEST_REEXTRACTION",
                },
            }
    with AuthorityUnitOfWork(database_url) as uow:
        state = uow.repositories.attempt_runtime.operation_state(operation_id, context.project_id)
    if state["status"] == "ADMITTED":
        transition_operation(database_url, OperationTransitionCommand(
            operation_id=operation_id, project_id=context.project_id,
            expected_version=int(state["version"]), expected_status="ADMITTED",
            target_status="READY", actor_id=context.principal_id,
            reason="Canon approval decision ready", trace_id=context.trace_id,
            correlation_id=context.correlation_id, causation_id=approval_request_id,
        ))
    return {"operation_id": operation_id, "project_id": context.project_id, "completed_result": None}


def _start_decision_attempt(database_url: str, context: CanonApprovalContext, operation: dict[str, Any]) -> WorkerLeaseCommand:
    attempt = create_attempt(
        database_url, operation_id=str(operation["operation_id"]), project_id=context.project_id,
        max_attempts=1, trace_id=context.trace_id, correlation_id=context.correlation_id,
    )
    attempt_id = str(attempt["attempt_id"])
    queue_attempt(database_url, attempt_id=attempt_id, project_id=context.project_id, trace_id=context.trace_id, correlation_id=context.correlation_id)
    worker_id = f"canon-approval:{context.principal_id}"
    lease = acquire_attempt_lease(database_url, attempt_id=attempt_id, project_id=context.project_id, worker_id=worker_id, lease_seconds=30, trace_id=context.trace_id, correlation_id=context.correlation_id)
    command = WorkerLeaseCommand(attempt_id=attempt_id, project_id=context.project_id, worker_id=worker_id, fencing_token=int(lease["fencing_token"]), trace_id=context.trace_id, correlation_id=context.correlation_id, causation_id=str(operation["operation_id"]))
    start_attempt(database_url, command)
    return command


def canon_approval_operation_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["approval_request_id", "expected_version", "decision", "reason", "evidence", "edited_payload"],
        "properties": {
            "approval_request_id": {"type": "string"}, "expected_version": {"type": "integer"},
            "decision": {"type": "string"}, "reason": {"type": "string"},
            "evidence": {"type": "object"}, "edited_payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    return {
        "name": CANON_APPROVAL_DEFINITION_NAME, "definition_version": CANON_APPROVAL_DEFINITION_VERSION,
        "family": "canon", "enabled": True, "command_schema": schema,
        "result_schema": {"type": "object"}, "handler_key": CANON_APPROVAL_HANDLER_KEY,
        "handler_contract_version": "1.0.0", "application_build_id": application_build_id,
        "commit_sha": commit_sha, "execution_mode": "transactional",
        "permissions": ["canon.authority.approve"], "approval_policy": {"required": False},
        "idempotency_scope": "project:canon-approval",
        "concurrency_key_template": "project:{project_id}:canon-approval",
        "retry_policy": {"max_attempts": 1}, "timeout_policy": {"operation_timeout_seconds": 60},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {"supported": False, "reason": "append_only_decision"},
        "irreversible_effect_policy": {"allowed": False}, "external_capabilities": [],
        "policy": {"authority": "postgresql", "local_storage_writes": "forbidden"},
        "completion_contract": {
            "version": "canon.change.approve.completion.v1",
            "required_asset_selectors": [{"selector": "canon_approval_decision", "role": "approval_decision", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}],
            "required_qualifications": ["production_eligible"], "required_evidence": ["trace", "audit"],
        },
    }


def _graph_context(context: CanonApprovalContext, causation_id: str) -> GraphCommandContext:
    return GraphCommandContext(project_id=context.project_id, actor_id=context.principal_id, trace_id=context.trace_id, correlation_id=context.correlation_id, causation_id=causation_id)


def reopen_canon_approval(
    database_url: str,
    context: CanonApprovalContext,
    *,
    approval_request_id: str,
    expected_version: int,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if not reason.strip() or not idempotency_key.strip():
        raise KernelError(
            "CANON_APPROVAL_REOPEN_INVALID", "reopen reason and idempotency key are required"
        )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT project_id, root_operation_id, status, version FROM authority_canon_approval_request WHERE approval_request_id=%s FOR UPDATE",
            [approval_request_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("CANON_APPROVAL_NOT_FOUND", "Canon approval request does not exist")
        project_id, root_id, status, version = row
        if project_id != context.project_id:
            raise KernelError("CROSS_PROJECT_REFERENCE", "Canon approval belongs to another project")
        uow.cursor.execute(
            "SELECT to_status FROM authority_canon_approval_transition WHERE project_id=%s AND approval_request_id=%s AND idempotency_key=%s",
            [project_id, approval_request_id, idempotency_key],
        )
        replay = uow.cursor.fetchone()
        if replay:
            return {
                "approval_request_id": approval_request_id,
                "status": replay[0],
                "replayed": True,
            }
        if status != "DEFERRED" or int(version) != expected_version:
            raise KernelError(
                "CANON_APPROVAL_VERSION_CONFLICT", "only the current deferred request can reopen"
            )
        uow.cursor.execute(
            "UPDATE authority_canon_approval_request SET status='PENDING', version=version+1, defer_until=NULL, required_information='', assigned_operator='', updated_at=NOW() WHERE approval_request_id=%s AND version=%s",
            [approval_request_id, expected_version],
        )
        uow.cursor.execute(
            "INSERT INTO authority_canon_approval_transition (transition_id, approval_request_id, project_id, from_status, to_status, actor_id, reason, idempotency_key, expected_version, trace_id, correlation_id) VALUES (%s,%s,%s,'DEFERRED','PENDING',%s,%s,%s,%s,%s,%s)",
            [str(uuid4()), approval_request_id, project_id, context.principal_id, reason, idempotency_key, expected_version, context.trace_id, context.correlation_id],
        )
        _event(
            uow, context, root_id, "canon.approval.reopened",
            {"approval_request_id": approval_request_id, "reason": reason},
        )
        uow.commit()
    return {
        "approval_request_id": approval_request_id,
        "status": "PENDING",
        "version": expected_version + 1,
        "replayed": False,
    }


def expire_deferred_canon_approvals(
    database_url: str, context: CanonApprovalContext, *, limit: int = 100
) -> tuple[dict[str, Any], ...]:
    if limit <= 0:
        raise ValueError("expiry scan limit must be positive")
    results: list[dict[str, Any]] = []
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT approval_request_id, root_operation_id, version, expiry_policy FROM authority_canon_approval_request WHERE project_id=%s AND status='DEFERRED' AND defer_until <= NOW() ORDER BY defer_until LIMIT %s FOR UPDATE SKIP LOCKED",
            [context.project_id, limit],
        )
        rows = uow.cursor.fetchall()
        for approval_id, root_id, version, policy in rows:
            target = "PENDING" if policy == "REOPEN" else "EXPIRED"
            uow.cursor.execute(
                "UPDATE authority_canon_approval_request SET status=%s, version=version+1, updated_at=NOW() WHERE approval_request_id=%s AND version=%s",
                [target, approval_id, version],
            )
            _event(
                uow, context, root_id, "canon.approval.defer_expired",
                {"approval_request_id": approval_id, "target_status": target},
            )
            results.append({"approval_request_id": approval_id, "status": target})
        uow.commit()
    return tuple(results)


def pending_canon_reextraction(
    database_url: str, *, project_id: str, root_operation_id: str
) -> dict[str, Any] | None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT reextraction_generation_id, generation, status, supersedes_proposal_asset_version_id, extraction_operation_id, extraction_asset_version_id, proposal_operation_id, proposal_asset_version_id, policy_snapshot, deadline_at, no_progress_count, escalation_reason FROM authority_canon_reextraction_generation WHERE project_id=%s AND root_operation_id=%s AND status NOT IN ('RESOLVED','CANCELLED') ORDER BY generation DESC LIMIT 1",
            [project_id, root_operation_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return None
    keys = (
        "reextraction_generation_id", "generation", "status",
        "supersedes_proposal_asset_version_id", "extraction_operation_id",
        "extraction_asset_version_id", "proposal_operation_id",
        "proposal_asset_version_id", "policy_snapshot", "deadline_at",
        "no_progress_count", "escalation_reason",
    )
    return dict(zip(keys, row, strict=True))


def advance_canon_reextraction(
    database_url: str,
    context: CanonApprovalContext,
    *,
    generation_id: str,
    expected_status: str,
    target_status: str,
    extraction_operation_id: str = "",
    extraction_asset_version_id: str = "",
    proposal_operation_id: str = "",
    proposal_asset_version_id: str = "",
) -> str:
    allowed = {
        ("REEXTRACTION_PENDING", "EXTRACTION_RUNNING"),
        ("EXTRACTION_RUNNING", "PROPOSAL_PENDING"),
        ("PROPOSAL_PENDING", "PROPOSAL_RUNNING"),
        ("PROPOSAL_RUNNING", "WAITING_APPROVAL"),
        ("WAITING_APPROVAL", "RESOLVED"),
    }
    if (expected_status, target_status) not in allowed:
        raise KernelError("CANON_REEXTRACTION_TRANSITION_INVALID", "invalid re-extraction transition")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT root_operation_id, policy_snapshot, deadline_at FROM authority_canon_reextraction_generation WHERE reextraction_generation_id=%s AND project_id=%s FOR UPDATE",
            [generation_id, context.project_id],
        )
        generation_row = uow.cursor.fetchone()
        if generation_row is None:
            raise KernelError("CANON_REEXTRACTION_NOT_FOUND", "re-extraction generation is missing")
        root_operation_id = str(generation_row[0])
        policy_snapshot = dict(generation_row[1] or {})
        deadline_at = generation_row[2]
        if deadline_at is not None and deadline_at <= datetime.now(timezone.utc):
            target_status = "WAITING_OPERATOR"
        extraction_digest = ""
        proposal_digest = ""
        change_set_digest = ""
        conflict_set_digest = ""
        no_progress_count = 0
        escalation_reason = ""
        if extraction_asset_version_id:
            uow.cursor.execute(
                "SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s",
                [extraction_asset_version_id],
            )
            digest_row = uow.cursor.fetchone()
            extraction_digest = str(digest_row[0]) if digest_row else ""
        if proposal_asset_version_id:
            uow.cursor.execute(
                "SELECT content, content_hash FROM authority_asset_version WHERE asset_version_id=%s",
                [proposal_asset_version_id],
            )
            proposal_row = uow.cursor.fetchone()
            if proposal_row:
                proposal_content = dict(proposal_row[0] or {})
                proposal_digest = str(proposal_row[1])
                change_set_digest = _stable_digest(proposal_content.get("changes", []))
                conflict_set_digest = _stable_digest(proposal_content.get("conflicts", []))
                uow.cursor.execute(
                    "SELECT COUNT(*) FROM authority_canon_reextraction_generation WHERE project_id=%s AND root_operation_id=%s AND reextraction_generation_id<>%s AND (change_set_digest=%s OR proposal_digest=%s)",
                    [context.project_id, root_operation_id, generation_id, change_set_digest, proposal_digest],
                )
                no_progress_count = int(uow.cursor.fetchone()[0]) + 1
                limit = min(
                    int(policy_snapshot.get("same_digest_limit") or 2),
                    int(policy_snapshot.get("no_progress_limit") or 2),
                )
                if no_progress_count >= limit:
                    target_status = "WAITING_OPERATOR"
                    escalation_reason = "CANON_REEXTRACTION_NO_PROGRESS"
        if target_status == "WAITING_OPERATOR" and not escalation_reason:
            escalation_reason = "CANON_REEXTRACTION_DEADLINE_EXCEEDED"
        uow.cursor.execute(
            "UPDATE authority_canon_reextraction_generation SET status=%s, extraction_operation_id=COALESCE(NULLIF(%s,''), extraction_operation_id), extraction_asset_version_id=COALESCE(NULLIF(%s,''), extraction_asset_version_id), proposal_operation_id=COALESCE(NULLIF(%s,''), proposal_operation_id), proposal_asset_version_id=COALESCE(NULLIF(%s,''), proposal_asset_version_id), extraction_digest=COALESCE(NULLIF(%s,''), extraction_digest), proposal_digest=COALESCE(NULLIF(%s,''), proposal_digest), change_set_digest=COALESCE(NULLIF(%s,''), change_set_digest), conflict_set_digest=COALESCE(NULLIF(%s,''), conflict_set_digest), no_progress_count=GREATEST(no_progress_count,%s), escalation_reason=COALESCE(NULLIF(%s,''), escalation_reason), updated_at=NOW() WHERE reextraction_generation_id=%s AND project_id=%s AND status=%s",
            [target_status, extraction_operation_id, extraction_asset_version_id, proposal_operation_id, proposal_asset_version_id, extraction_digest, proposal_digest, change_set_digest, conflict_set_digest, no_progress_count, escalation_reason, generation_id, context.project_id, expected_status],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError("CANON_REEXTRACTION_STATE_CONFLICT", "re-extraction generation changed")
        _event(
            uow, context, root_operation_id, "canon.reextraction.advanced",
            {"from": expected_status, "to": target_status, "no_progress_count": no_progress_count, "escalation_reason": escalation_reason},
        )
        uow.commit()
    return target_status


def _stable_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def list_canon_approvals(database_url: str, *, project_id: str, approval_request_id: str = "") -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        query = "SELECT approval_request_id, project_id, root_operation_id, saga_id, proposal_asset_version_id, change_id, change_type, risk, status, version, expires_at, created_at, proposal_generation, defer_until, required_information, assigned_operator, expiry_policy FROM authority_canon_approval_request WHERE project_id = %s"
        params: list[Any] = [project_id]
        if approval_request_id:
            query += " AND approval_request_id = %s"
            params.append(approval_request_id)
        query += " ORDER BY created_at DESC"
        uow.cursor.execute(query, params)
        rows = uow.cursor.fetchall()
    keys = ("approval_request_id", "project_id", "root_operation_id", "saga_id", "proposal_asset_version_id", "change_id", "change_type", "risk", "status", "version", "expires_at", "created_at", "proposal_generation", "defer_until", "required_information", "assigned_operator", "expiry_policy")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def decision_asset_versions(database_url: str, *, project_id: str, root_operation_id: str) -> tuple[dict[str, str], ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT decision.asset_version_id, version.content_hash FROM authority_canon_approval_decision decision JOIN authority_canon_approval_request request ON request.approval_request_id = decision.approval_request_id JOIN authority_asset_version version ON version.asset_version_id = decision.asset_version_id WHERE request.project_id = %s AND request.root_operation_id = %s AND request.status IN ('APPROVED','REJECTED','EDITED_AND_APPROVED') ORDER BY request.change_id", [project_id, root_operation_id])
        return tuple({"asset_version_id": row[0], "content_hash": row[1]} for row in uow.cursor.fetchall())


def _event(uow: AuthorityUnitOfWork, context: CanonApprovalContext, operation_id: str, event_type: str, payload: dict[str, Any]) -> None:
    uow.repositories.operation_graph.record_event({
        "event_id": str(uuid4()), "audit_id": str(uuid4()), "outbox_id": str(uuid4()),
        "aggregate_type": "authority_operation", "aggregate_id": operation_id,
        "project_id": context.project_id, "operation_id": operation_id,
        "event_type": event_type, "correlation_id": context.correlation_id,
        "causation_id": operation_id, "payload": {**payload, "trace_id": context.trace_id},
    })


__all__ = [
    "CanonApprovalContext", "advance_canon_reextraction",
    "canon_approval_operation_definition", "decide_canon_approval",
    "decision_asset_versions", "ensure_canon_approval_requests",
    "expire_deferred_canon_approvals", "list_canon_approvals",
    "pending_canon_reextraction", "reopen_canon_approval",
]
