from __future__ import annotations

import hashlib
import json
from uuid import uuid4
from typing import Any

from novel_forge.storage.authority_repositories import IdempotencyConflictError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def admit_command(database_url: str, command: dict[str, Any]) -> dict[str, Any]:
    required = ("definition_name", "definition_version", "project_id", "idempotency_scope", "idempotency_key")
    missing = [key for key in required if not str(command.get(key, ""))]
    if missing: raise ValueError(f"missing command fields: {', '.join(missing)}")
    digest = hashlib.sha256(json.dumps(command.get("input", {}), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with AuthorityUnitOfWork(database_url) as uow:
        definition = uow.repositories.definitions.get(command["definition_name"], command["definition_version"])
        if definition is None: raise ValueError("operation definition not found")
        if not definition["enabled"]: raise ValueError("operation definition is disabled")
        existing = uow.repositories.operations.get_idempotency(command["idempotency_scope"], command["idempotency_key"])
        if existing:
            if existing[1] != digest: raise IdempotencyConflictError("idempotency key belongs to a different request digest")
            return {"operation_id": existing[0], "replayed": True}
        operation_id = str(uuid4())
        uow.repositories.operations.create({**command, "operation_id": operation_id, "root_operation_id": command.get("root_operation_id") or operation_id, "request_digest": digest, "definition_snapshot": definition, "completion_contract_snapshot": definition["completion_contract"], "policy_snapshot": definition["policy"]})
        uow.commit()
    return {"operation_id": operation_id, "replayed": False}
