"""Focused repositories for authoritative Operation admission."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


class IdempotencyConflictError(ValueError):
    code = "idempotency_conflict"


class OperationDefinitionRepository:
    def __init__(self, cursor: Any) -> None: self.cursor = cursor
    def get(self, name: str, version: str) -> dict[str, Any] | None:
        self.cursor.execute("SELECT enabled,command_schema,result_schema,policy,completion_contract FROM authority_operation_definition WHERE name=%s AND definition_version=%s", [name, version])
        row = self.cursor.fetchone()
        return None if row is None else {"enabled": row[0], "command_schema": row[1], "result_schema": row[2], "policy": row[3], "completion_contract": row[4]}
    def register(self, row: dict[str, Any]) -> None:
        self.cursor.execute("INSERT INTO authority_operation_definition(name,definition_version,family,enabled,command_schema,result_schema,policy,completion_contract) VALUES (%(name)s,%(definition_version)s,%(family)s,%(enabled)s,%(command_schema)s,%(result_schema)s,%(policy)s,%(completion_contract)s) ON CONFLICT(name,definition_version) DO NOTHING", {**row, "command_schema": Jsonb(row["command_schema"]), "result_schema": Jsonb(row["result_schema"]), "policy": Jsonb(row["policy"]), "completion_contract": Jsonb(row["completion_contract"])})


class OperationRepository:
    def __init__(self, cursor: Any) -> None: self.cursor = cursor
    def get_idempotency(self, scope: str, key: str) -> tuple[str, str] | None:
        self.cursor.execute("SELECT operation_id,request_digest FROM authority_operation WHERE idempotency_scope=%s AND idempotency_key=%s", [scope, key]); return self.cursor.fetchone()
    def create(self, row: dict[str, Any]) -> None:
        self.cursor.execute("INSERT INTO authority_operation(operation_id,definition_name,definition_version,project_id,status,root_operation_id,idempotency_scope,idempotency_key,request_digest,definition_snapshot,completion_contract_snapshot,policy_snapshot,metadata) VALUES (%(operation_id)s,%(definition_name)s,%(definition_version)s,%(project_id)s,'ADMITTED',%(root_operation_id)s,%(idempotency_scope)s,%(idempotency_key)s,%(request_digest)s,%(definition_snapshot)s,%(completion_contract_snapshot)s,%(policy_snapshot)s,%(metadata)s)", {**row, "definition_snapshot": Jsonb(row["definition_snapshot"]), "completion_contract_snapshot": Jsonb(row["completion_contract_snapshot"]), "policy_snapshot": Jsonb(row["policy_snapshot"]), "metadata": Jsonb(row.get("metadata", {}))})


class AuthorityRepositories:
    def __init__(self, cursor: Any) -> None:
        self.definitions = OperationDefinitionRepository(cursor)
        self.operations = OperationRepository(cursor)
