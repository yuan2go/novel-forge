from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


MODEL_DISPATCH_EFFECT_TYPES = frozenset({"model.invoke", "agent_model_turn", "provider.qualification.basic", "provider.qualification.invoke"})


class RuntimeDispatchPaused(KernelError):
    def __init__(self, message: str, evidence: dict[str, Any]):
        super().__init__("RUNTIME_DISPATCH_PAUSED", message)
        self.control_evidence = {"contract_version": "runtime-dispatch-control.v1", "request_sent": False, **evidence}


def confirmed_dispatch_pause(cursor: Any, cause: BaseException | None, project_id: str) -> dict[str, Any] | None:
    if not isinstance(cause, RuntimeDispatchPaused) or cause.control_evidence.get("project_id") != project_id:
        return None
    evidence = cause.control_evidence
    if evidence["scope"] == "PROCESS":
        return dict(evidence) if evidence.get("process_id") == os.getpid() and process_dispatch_suspended() else None
    cursor.execute("SELECT 1 FROM authority_runtime_dispatch_event WHERE project_id=%s AND version=%s AND state='PAUSED'",
        [project_id, evidence["version"]])
    return dict(evidence) if cursor.fetchone() else None


def process_dispatch_suspended() -> bool:
    value = os.environ.get("NOVEL_FORGE_NO_MODEL_DISPATCH", "").strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def require_dispatch_enabled(cursor: Any, project_id: str) -> None:
    if process_dispatch_suspended():
        raise RuntimeDispatchPaused("This process is running with model dispatch suspended", {"project_id": project_id, "scope": "PROCESS", "process_id": os.getpid()})
    cursor.execute("SELECT state,version FROM authority_runtime_dispatch_control WHERE project_id=%s", [project_id])
    row = cursor.fetchone()
    if row is not None and row[0] == "PAUSED":
        raise RuntimeDispatchPaused("The project has a durable operator dispatch pause", {"project_id": project_id, "scope": "PROJECT", "version": int(row[1])})


def assert_dispatch_enabled(database_url: str, project_id: str) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        require_dispatch_enabled(uow.cursor, project_id)


def dispatch_control_status(database_url: str, *, project_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SET TRANSACTION READ ONLY")
        uow.cursor.execute("SELECT 1 FROM authority_project WHERE project_id=%s", [project_id])
        if uow.cursor.fetchone() is None:
            raise KernelError("RUNTIME_PROJECT_NOT_FOUND", "The project is absent from this ledger")
        uow.cursor.execute("SELECT state,version,updated_at FROM authority_runtime_dispatch_control WHERE project_id=%s", [project_id])
        row = uow.cursor.fetchone()
        uow.cursor.execute("""SELECT event_id,version,idempotency_key,state,previous_version,actor_id,reason,release_identity,created_at
            FROM authority_runtime_dispatch_event WHERE project_id=%s ORDER BY version""", [project_id])
        events = [dict(zip(("event_id", "version", "idempotency_key", "state", "previous_version", "actor_id", "reason", "release_identity", "created_at"), event, strict=True)) for event in uow.cursor.fetchall()]
        uow.cursor.execute("""SELECT runtime_job_id,runtime_group,status,attempt_count,max_attempts,paused_attempt_count,last_error->>'disposition'
            FROM authority_runtime_job WHERE project_id=%s AND status='RETRY_WAIT'
              AND last_error @> '{"dispatch_pause_contract":"runtime-dispatch-control.v1","code":"RUNTIME_DISPATCH_PAUSED","request_sent":false}'::jsonb
            ORDER BY created_at,runtime_job_id""", [project_id])
        waiting = [dict(zip(("runtime_job_id", "runtime_group", "status", "attempt_count", "max_attempts", "paused_attempt_count", "disposition"), job, strict=True)) for job in uow.cursor.fetchall()]
    suspended = process_dispatch_suspended()
    return {"schema_version": "runtime-dispatch-control.v1", "project_id": project_id,
            "state": row[0] if row else "UNMANAGED", "version": int(row[1]) if row else 0,
            "updated_at": row[2] if row else None, "process_dispatch_suspended": suspended,
            "new_dispatch_allowed_by_control": not suspended and (not row or row[0] != "PAUSED"),
            "authorization": "CONTROL_IS_NOT_BUDGET_OR_TASK_ADMISSION", "events": events, "waiting_for_dispatch_control": waiting}


def change_dispatch_control(
    database_url: str, *, project_id: str, principal: Any, state: str,
    expected_version: int, idempotency_key: str, reason: str,
    release_identity: dict[str, Any],
) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
    if state not in {"PAUSED", "RUNNING"} or expected_version < 0 or not idempotency_key.strip() or not reason.strip():
        raise KernelError("COMMAND_SCHEMA_INVALID", "A valid state, expected version, idempotency key and reason are required")
    with AuthorityUnitOfWork(database_url) as uow:
        cur = uow.cursor
        # INVARIANT: The Project row serializes first insertion and later CAS decisions.
        cur.execute("SELECT 1 FROM authority_project WHERE project_id=%s FOR UPDATE", [project_id])
        if cur.fetchone() is None:
            raise KernelError("RUNTIME_PROJECT_NOT_FOUND", "The project is absent from this ledger")
        cur.execute("""SELECT state,previous_version,actor_id,reason,release_identity FROM authority_runtime_dispatch_event
            WHERE project_id=%s AND idempotency_key=%s""", [project_id, idempotency_key])
        replay = cur.fetchone()
        expected = (state, expected_version, principal.principal_id, reason, release_identity)
        if replay is not None:
            if tuple(replay) != expected:
                raise KernelError("RUNTIME_CONTROL_IDEMPOTENCY_CONFLICT", "The key identifies a different immutable operator decision")
        else:
            cur.execute("SELECT version FROM authority_runtime_dispatch_control WHERE project_id=%s FOR UPDATE", [project_id])
            current = cur.fetchone()
            if (int(current[0]) if current else 0) != expected_version:
                raise KernelError("RUNTIME_CONTROL_VERSION_CONFLICT", "Inspect the current control before making a new decision")
            if current is None and state == "RUNNING":
                raise KernelError("RUNTIME_CONTROL_PAUSE_REQUIRED", "Initialize a controlled deployment with an explicit pause")
            version = expected_version + 1
            cur.execute("""INSERT INTO authority_runtime_dispatch_control(project_id,state,version) VALUES (%s,%s,%s)
                ON CONFLICT(project_id) DO UPDATE SET state=EXCLUDED.state,version=EXCLUDED.version,updated_at=NOW()""", [project_id, state, version])
            cur.execute("""INSERT INTO authority_runtime_dispatch_event(event_id,project_id,version,idempotency_key,state,previous_version,actor_id,reason,release_identity)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [str(uuid4()), project_id, version, idempotency_key, state, expected_version, principal.principal_id, reason, Jsonb(release_identity)])
        uow.commit()
    result = dispatch_control_status(database_url, project_id=project_id)
    result["replayed"] = replay is not None
    return result
