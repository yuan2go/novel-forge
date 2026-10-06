from __future__ import annotations

from typing import Any
from uuid import uuid4
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import MODE, selected_book_template, selected_template, verify_template_provenance

from .policy import CapabilityPackApprovalScope


def record_validation_admission(repository: Any, command: Any, operation_id: str) -> dict[str, Any]:
    compilation = repository.require_compilation(command.compilation_id, project_id=command.project_id, for_update=True)
    book_id = str(command.payload.get("book_id") or "")
    policy = command.payload.get("policy_snapshot") or {}
    decision = {"task": {"project_id": command.project_id, "work_id": book_id, "policy_snapshot": policy}}
    template = verify_template_provenance(repository.cursor, decision)
    current = selected_book_template(repository.cursor, project_id=command.project_id, book_id=book_id, allow_literary_required=True)
    current_template = selected_template(current["policy_snapshot"]["policy"], book_id) if current else None
    if (compilation["runtime_profile"] != "validation"
            or compilation["release_channel"] != "VALIDATION" or template is None or template["mode"] != MODE
            or template.get("require_pack_human_approval", True)
            or current_template is None or current_template["require_pack_human_approval"]
            or compilation["compilation_hash"] != command.payload.get("compilation_hash")):
        raise KernelError("CREATIVE_PACK_ADMISSION_POLICY_REQUIRED", command.compilation_id)
    scope = CapabilityPackApprovalScope.from_payload(command.payload.get("scope") or {})
    if (scope.allowed_environments != ("validation",) or scope.allowed_runtime_profiles != ("validation",)
            or scope.allowed_release_channels != ("VALIDATION",)
            or scope.allowed_project_ids != (command.project_id,) or scope.allowed_book_ids != (book_id,)
            or tuple(value.value for value in scope.allowed_scope_types) != ("BOOK",)
            or scope.allow_canary or scope.allow_percentage_rollout):
        raise KernelError("CREATIVE_PACK_ADMISSION_SCOPE_INVALID", book_id)
    checks = {key: {"status": "NOT_RUN", "reason": "creative validation template excludes this certification objective"}
              for key in ("human_pack_approval", "compiler_approver_separation", "production_certification")}
    admission_id = str(uuid4())
    repository.cursor.execute("""INSERT INTO authority_capability_pack_validation_admission(
        admission_id,compilation_id,compilation_hash,project_id,book_id,policy_snapshot,
        admission_scope,checks,actor_id,operation_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(compilation_id,project_id,book_id) DO NOTHING""",
        [admission_id, command.compilation_id, compilation["compilation_hash"], command.project_id, book_id,
         Jsonb(policy), Jsonb(scope.to_dict()), Jsonb(checks), command.actor_id, operation_id])
    repository.cursor.execute("SELECT admission_id,compilation_hash,policy_snapshot,admission_scope FROM authority_capability_pack_validation_admission WHERE compilation_id=%s AND project_id=%s AND book_id=%s", [command.compilation_id, command.project_id, book_id])
    row = repository.cursor.fetchone()
    if row[1:] != (compilation["compilation_hash"], policy, scope.to_dict()):
        raise KernelError("CREATIVE_PACK_ADMISSION_CONFLICT", command.compilation_id)
    return {"admission_id": row[0], "checks": checks, "compilation_hash": compilation["compilation_hash"]}


def require_validation_admission(repository: Any, compilation: dict[str, Any], *, environment: str, book_id: str) -> dict[str, Any] | None:
    if environment != "validation" or compilation["runtime_profile"] != "validation" or compilation["release_channel"] != "VALIDATION":
        return None
    repository.cursor.execute("""SELECT a.admission_id,a.compilation_hash,a.project_id,a.book_id,
        a.policy_snapshot,a.admission_scope,a.checks,op.status
        FROM authority_capability_pack_validation_admission a
        JOIN authority_operation op ON op.operation_id=a.operation_id
        WHERE a.compilation_id=%s AND a.book_id=%s""", [compilation["compilation_id"], book_id])
    row = repository.cursor.fetchone()
    if not row:
        return None
    if row[1] != compilation["compilation_hash"] or row[7] != "SUCCEEDED":
        raise KernelError("CREATIVE_PACK_ADMISSION_INVALID", compilation["compilation_id"])
    template = selected_template(row[4]["policy"], book_id)
    if not template or template["mode"] != MODE:
        raise KernelError("CREATIVE_PACK_ADMISSION_INVALID", book_id)
    decision = {"task": {"project_id": row[2], "work_id": book_id, "policy_snapshot": row[4]}}
    verify_template_provenance(repository.cursor, decision)
    current = selected_book_template(repository.cursor, project_id=row[2], book_id=book_id, allow_literary_required=True)
    current_template = selected_template(current["policy_snapshot"]["policy"], book_id) if current else None
    if current_template is None or current_template["require_pack_human_approval"]:
        return None
    approval = repository.latest_approval(compilation["compilation_id"])
    if approval and approval["decision"] in {"REVOKED", "REJECTED"}:
        raise KernelError("CAPABILITY_PACK_APPROVAL_INVALID", "security rejection overrides validation selection")
    return {**compilation, "admission_id": row[0], "admission_scope": row[5],
            "checks": row[6], "structured_limitations": ()}


def require_deployment_authorization(repository: Any, deployment: Any, *, scope: Any,
                                     environment: str, runtime_profile: str,
                                     release_channel: str, workflow_definition_ref: str) -> None:
    approval = repository.latest_approval(str(deployment["compilation_id"]))
    admitted = None
    if approval is None:
        compilation = repository.require_compilation(str(deployment["compilation_id"]))
        admitted = require_validation_admission(repository, compilation, environment=environment, book_id=scope.book_id)
    if admitted is not None:
        policy_scope = admitted["admission_scope"]
        limitations = ()
    else:
        if (not approval or approval["decision"] != "APPROVED"
                or approval["compilation_hash"] != deployment["compilation_hash"]
                or approval["expires_at"] is not None and approval["expires_at"] <= datetime.now(timezone.utc)):
            raise KernelError("CAPABILITY_PACK_APPROVAL_INVALID", "Pack requires its current exact approval")
        policy_scope = approval["approval_scope"]
        limitations = tuple(approval.get("structured_limitations") or ())
    CapabilityPackApprovalScope.from_payload(dict(policy_scope)).require_admission(
        scope=scope, environment=environment, runtime_profile=runtime_profile,
        release_channel=release_channel, workflow_definition_ref=workflow_definition_ref,
        limitations=limitations)
