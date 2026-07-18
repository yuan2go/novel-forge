"""PostgreSQL Canon approval commands and strong queries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from novel_forge.modules.canon_graph.approval_domain import CANON_DECISIONS
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


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
    with AuthorityUnitOfWork(database_url) as uow:
        for change in required:
            request_id = "canon-approval:" + hashlib.sha256(f"{context.project_id}:{proposal_asset_version_id}:{change['change_id']}".encode()).hexdigest()
            uow.cursor.execute(
                """
                INSERT INTO authority_canon_approval_request (
                    approval_request_id, project_id, root_operation_id, saga_id,
                    proposal_asset_version_id, change_id, change_type, risk
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id, proposal_asset_version_id, change_id) DO NOTHING
                """,
                [request_id, context.project_id, root_operation_id, saga_id, proposal_asset_version_id, change["change_id"], change["change_type"], json.dumps({"impact_level": change["impact_level"], "confidence": change["confidence"], "evidence_digest": change["evidence_digest"]})],
            )
            ids.append(request_id)
        uow.cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id = %s AND project_id = %s FOR UPDATE",
            [root_operation_id, context.project_id],
        )
        root = uow.cursor.fetchone()
        if root is None:
            raise KernelError("OPERATION_NOT_FOUND", "Canon gate root Operation is missing")
        uow.cursor.execute("SELECT COUNT(*) FROM authority_canon_approval_request WHERE root_operation_id = %s AND status NOT IN ('APPROVED','REJECTED','EDITED_AND_APPROVED')", [root_operation_id])
        unresolved = int(uow.cursor.fetchone()[0])
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
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("UPDATE authority_saga SET status = 'WAITING_GATE', version = version + 1, updated_at = NOW() WHERE saga_id = %s AND project_id = %s AND status <> 'WAITING_GATE'", [saga_id, context.project_id])
        _event(uow, context, root_operation_id, "canon.approval.requested", {"proposal_asset_version_id": proposal_asset_version_id, "approval_request_ids": ids})
        uow.commit()
    return {"waiting": True, "approval_request_ids": ids}


def decide_canon_approval(database_url: str, context: CanonApprovalContext, *, approval_request_id: str, expected_version: int, decision: str, reason: str, evidence: dict[str, Any], edited_payload: dict[str, Any] | None, idempotency_key: str) -> dict[str, Any]:
    if decision not in CANON_DECISIONS or not reason.strip() or not idempotency_key.strip():
        raise KernelError("CANON_APPROVAL_COMMAND_INVALID", "decision, reason, and idempotency key are required")
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
        content = {
            "type": "CanonApprovalDecision", "project_id": project_id,
            "approval_request_id": approval_request_id, "proposal_asset_version_id": proposal_id,
            "change_id": change_id, "decision": decision, "reason": reason,
            "evidence": evidence, "edited_payload": edited_payload or {},
            "principal_id": context.principal_id, "contract_version": "canon-approval-decision-v1",
        }
        content_hash = "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        asset_id = "canon-decision-asset:" + hashlib.sha256(f"{project_id}:{approval_request_id}".encode()).hexdigest()
        asset_version_id = "canon-decision-version:" + hashlib.sha256(f"{approval_request_id}:{request_digest}".encode()).hexdigest()
        created = uow.repositories.chapter_authority.materialize_output(
            operation_id=root_id, project_id=project_id, asset_id=asset_id,
            asset_version_id=asset_version_id, qualification_id=f"{asset_version_id}:qualification",
            asset_type="canon_approval_decision", output_key=f"canon.approval.decision.{change_id}",
            role="approval_decision", content=content, content_hash=content_hash,
            qualification_policy="canon-approval-decision-v1",
            qualification_evidence={"principal_id": context.principal_id, "decision": decision},
        )
        status_target = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "EDIT_AND_APPROVE": "EDITED_AND_APPROVED", "DEFER": "DEFERRED", "REQUEST_REEXTRACTION": "REEXTRACTION_REQUESTED"}[decision]
        uow.cursor.execute("UPDATE authority_canon_approval_request SET status = %s, version = version + 1, updated_at = NOW() WHERE approval_request_id = %s AND version = %s", [status_target, approval_request_id, expected_version])
        uow.cursor.execute("INSERT INTO authority_canon_approval_decision (approval_decision_id, approval_request_id, project_id, decision, reason, evidence, edited_payload, principal_id, idempotency_key, request_digest, asset_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [str(uuid4()), approval_request_id, project_id, decision, reason, json.dumps(evidence), json.dumps(edited_payload) if edited_payload else None, context.principal_id, idempotency_key, request_digest, asset_version_id])
        _event(uow, context, root_id, "canon.approval.decided", {"approval_request_id": approval_request_id, "change_id": change_id, "decision": decision, "asset_version_id": asset_version_id})
        uow.cursor.execute("SELECT COUNT(*) FILTER (WHERE status NOT IN ('APPROVED','REJECTED','EDITED_AND_APPROVED')), COUNT(*) FROM authority_canon_approval_request WHERE root_operation_id = %s", [root_id])
        unresolved, total = uow.cursor.fetchone()
        uow.commit()
    if total and not unresolved:
        with AuthorityUnitOfWork(database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(root_id, project_id)
        transition_operation(database_url, OperationTransitionCommand(
            operation_id=root_id, project_id=project_id, expected_version=int(state["version"]),
            expected_status=str(state["status"]), target_status="WAITING_CHILDREN",
            actor_id=context.principal_id, reason="Canon approval gate resolved",
            trace_id=context.trace_id, correlation_id=context.correlation_id,
            causation_id=approval_request_id,
        ))
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("UPDATE authority_saga SET status = 'RUNNING', version = version + 1, updated_at = NOW() WHERE saga_id = %s AND project_id = %s", [saga_id, project_id])
            uow.commit()
    return {"approval_request_id": approval_request_id, "decision": decision, "asset_version_id": asset_version_id, "replayed": not created, "gate_resumed": bool(total and not unresolved)}


def list_canon_approvals(database_url: str, *, project_id: str, approval_request_id: str = "") -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        query = "SELECT approval_request_id, project_id, root_operation_id, saga_id, proposal_asset_version_id, change_id, change_type, risk, status, version, expires_at, created_at FROM authority_canon_approval_request WHERE project_id = %s"
        params: list[Any] = [project_id]
        if approval_request_id:
            query += " AND approval_request_id = %s"
            params.append(approval_request_id)
        query += " ORDER BY created_at DESC"
        uow.cursor.execute(query, params)
        rows = uow.cursor.fetchall()
    keys = ("approval_request_id", "project_id", "root_operation_id", "saga_id", "proposal_asset_version_id", "change_id", "change_type", "risk", "status", "version", "expires_at", "created_at")
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


__all__ = ["CanonApprovalContext", "decide_canon_approval", "decision_asset_versions", "ensure_canon_approval_requests", "list_canon_approvals"]
