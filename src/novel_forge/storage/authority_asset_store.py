from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class AuthorityAssetRef:
    project_id: str
    logical_ref: str
    asset_id: str
    asset_version_id: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class AuthorityAssetDocument:
    project_id: str
    logical_ref: str
    category: str
    asset_id: str
    asset_type: str
    asset_version_id: str
    version_number: int
    lifecycle: str
    eligibility: str
    governance: str
    content_hash: str
    content: dict[str, Any]
    updated_at: str

    @property
    def ref(self) -> AuthorityAssetRef:
        return AuthorityAssetRef(
            project_id=self.project_id,
            logical_ref=self.logical_ref,
            asset_id=self.asset_id,
            asset_version_id=self.asset_version_id,
            content_hash=self.content_hash,
        )


class AuthorityAssetDocumentRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def materialize_output(self, command: AuthorityAssetWriteCommand) -> AuthorityAssetDocument:
        self._lock_identity(command.project_id, command.logical_ref)
        self._require_executing_operation(command.operation_id, command.project_id, recovery_fact=command)
        self._require_project_references(command.project_id, command.reference_asset_ids)
        locator = self._locator_for_update(command.project_id, command.logical_ref)
        if locator is not None and locator["asset_id"] != command.asset_id:
            raise KernelError(
                "AUTHORITY_ASSET_LOCATOR_CONFLICT",
                "logical asset reference is already bound to a different Asset",
            )
        current_version_id = locator["asset_version_id"] if locator else None
        if current_version_id != command.expected_current_asset_version_id:
            raise KernelError(
                "AUTHORITY_ASSET_VERSION_CONFLICT",
                "expected current AssetVersion does not match PostgreSQL authority",
            )

        self._ensure_asset(command.asset_id, command.project_id, command.asset_type)
        version_number = self._next_version_number(command.asset_id)
        asset_version_id = str(uuid4())
        content_hash = _content_hash(command.content)
        if current_version_id is not None:
            self.cursor.execute(
                """
                UPDATE authority_asset_version
                SET lifecycle = 'SUPERSEDED'
                WHERE asset_version_id = %s AND asset_id = %s AND lifecycle = 'ACTIVE'
                """,
                [current_version_id, command.asset_id],
            )
            if self.cursor.rowcount != 1:
                raise KernelError(
                    "AUTHORITY_ASSET_VERSION_CONFLICT",
                    "current AssetVersion is no longer ACTIVE",
                )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version (
                asset_version_id, asset_id, version_number, lifecycle,
                eligibility, governance, content, content_hash, schema_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                asset_version_id,
                command.asset_id,
                version_number,
                command.lifecycle,
                command.eligibility,
                command.governance,
                Jsonb(command.content),
                content_hash,
                command.schema_version,
            ],
        )
        qualification_id = str(uuid4())
        self.cursor.execute(
            """
            INSERT INTO authority_asset_qualification (
                qualification_id, asset_version_id, policy_version, decision, evidence
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            [
                qualification_id,
                asset_version_id,
                command.qualification_policy,
                command.eligibility,
                Jsonb(
                    {
                        "operation_id": command.operation_id,
                        "trace_id": command.trace_id,
                        "content_hash": content_hash,
                        "reference_asset_ids": list(command.reference_asset_ids),
                    }
                ),
            ],
        )
        if locator is None:
            self.cursor.execute(
                """
                INSERT INTO authority_asset_locator (
                    project_id, logical_ref, category, asset_id, current_asset_version_id
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    command.project_id,
                    command.logical_ref,
                    command.category,
                    command.asset_id,
                    asset_version_id,
                ],
            )
        else:
            self.cursor.execute(
                """
                UPDATE authority_asset_locator
                SET category = %s, current_asset_version_id = %s, updated_at = NOW()
                WHERE project_id = %s AND logical_ref = %s AND asset_id = %s
                """,
                [
                    command.category,
                    asset_version_id,
                    command.project_id,
                    command.logical_ref,
                    command.asset_id,
                ],
            )
            if self.cursor.rowcount != 1:
                raise KernelError(
                    "AUTHORITY_ASSET_LOCATOR_CONFLICT",
                    "logical asset locator changed during materialization",
                )
        self.cursor.execute(
            """
            INSERT INTO authority_operation_output_asset (
                operation_id, asset_id, asset_version_id, output_key, role, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                command.operation_id,
                command.asset_id,
                asset_version_id,
                command.output_key,
                command.role,
                content_hash,
            ],
        )
        return self.require(project_id=command.project_id, asset_version_id=asset_version_id)

    def require(
        self,
        *,
        project_id: str,
        logical_ref: str | None = None,
        asset_id: str | None = None,
        asset_version_id: str | None = None,
    ) -> AuthorityAssetDocument:
        selectors = [logical_ref is not None, asset_id is not None, asset_version_id is not None]
        if sum(selectors) != 1:
            raise ValueError("exactly one authority asset selector is required")
        if asset_version_id is not None:
            self.cursor.execute(
                _VERSION_DOCUMENT_SELECT
                + " WHERE asset.project_id = %s AND version.asset_version_id = %s",
                [project_id, asset_version_id],
            )
            row = self.cursor.fetchone()
            if row is None:
                raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "authority asset document does not exist")
            return _document(row)
        clause: str
        value: str
        if logical_ref is not None:
            clause, value = "locator.logical_ref = %s", logical_ref
        elif asset_id is not None:
            clause, value = "locator.asset_id = %s", asset_id
        else:  # pragma: no cover - selector count above makes this unreachable
            raise AssertionError("authority asset selector resolution failed")
        self.cursor.execute(_DOCUMENT_SELECT + f" WHERE locator.project_id = %s AND {clause}", [project_id, value])
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "authority asset document does not exist")
        return _document(row)

    def list(
        self,
        *,
        project_id: str,
        category: str | None = None,
        asset_type: str | None = None,
        limit: int = 100,
    ) -> list[AuthorityAssetDocument]:
        if limit < 1 or limit > 1000:
            raise ValueError("authority asset list limit must be between 1 and 1000")
        clauses = ["locator.project_id = %s"]
        params: list[Any] = [project_id]
        if category is not None:
            clauses.append("locator.category = %s")
            params.append(category)
        if asset_type is not None:
            clauses.append("asset.asset_type = %s")
            params.append(asset_type)
        params.append(limit)
        self.cursor.execute(
            _DOCUMENT_SELECT
            + f" WHERE {' AND '.join(clauses)} ORDER BY locator.updated_at DESC, locator.logical_ref LIMIT %s",
            params,
        )
        return [_document(row) for row in self.cursor.fetchall()]

    def list_versions(self, *, project_id: str, asset_type: str, limit: int = 100) -> list[AuthorityAssetDocument]:
        if not project_id or not asset_type or not 1 <= limit <= 500:
            raise ValueError("version export requires a project, asset type and limit in 1..500")
        self.cursor.execute(
            """SELECT asset.project_id, 'asset-version:' || version.asset_version_id,
                      asset.asset_type, asset.asset_id, asset.asset_type,
                      version.asset_version_id, version.version_number, version.lifecycle,
                      version.eligibility, version.governance, version.content_hash,
                      version.content, version.created_at
               FROM authority_asset asset
               JOIN authority_asset_version version USING(asset_id)
               WHERE asset.project_id=%s AND asset.asset_type=%s
               ORDER BY version.created_at DESC, version.asset_version_id
               LIMIT %s""",
            [project_id, asset_type, limit],
        )
        return [_document(row) for row in self.cursor.fetchall()]

    def count(self, *, project_id: str, category: str | None = None) -> int:
        if category is None:
            self.cursor.execute(
                "SELECT COUNT(*) FROM authority_asset_locator WHERE project_id = %s",
                [project_id],
            )
        else:
            self.cursor.execute(
                "SELECT COUNT(*) FROM authority_asset_locator WHERE project_id = %s AND category = %s",
                [project_id, category],
            )
        return int(self.cursor.fetchone()[0])

    def _lock_identity(self, project_id: str, logical_ref: str) -> None:
        self.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"authority_asset_locator:{project_id}:{logical_ref}"],
        )

    def _require_executing_operation(self, operation_id: str, project_id: str, *, recovery_fact=None) -> None:
        self.cursor.execute(
            """
            SELECT status,
                   definition_snapshot->>'execution_mode',
                   policy_snapshot->>'execution_classification'
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "asset output Operation does not exist")
        transaction_admitted = (
            row[0] == "ADMITTED"
            and row[1] == "transactional"
            and row[2] == "transaction_command"
        )
        retained_execution_fact = False
        if recovery_fact is not None and recovery_fact.role != "primary" and (
            recovery_fact.asset_type, recovery_fact.schema_version, recovery_fact.category
        ) in {
            ("execution_evidence", "authority-execution-evidence.v1", "production_execution_evidence"),
            ("execution_recovery_session", "authority-execution-recovery.v1", "production_execution_recovery"),
        }:
            self.cursor.execute("""SELECT 1 FROM authority_asset_version version
                JOIN authority_asset asset USING(asset_id)
                WHERE asset.project_id=%s AND asset.asset_type='execution_recovery_session'
                  AND version.content->>'execution_id'=%s
                  AND version.content #>> '{record,request,operation_id}'=%s
                  AND version.content #>> '{record,request,project_id}'=%s
                  AND (%s='execution_evidence' OR version.content->>'request_contract_hash'=%s)
                LIMIT 1""", [project_id, recovery_fact.content.get("execution_id"), operation_id,
                    project_id, recovery_fact.asset_type, recovery_fact.content.get("request_contract_hash")])
            retained_execution_fact = self.cursor.fetchone() is not None
        if row[0] != "EXECUTING" and not transaction_admitted and not retained_execution_fact:
            raise KernelError(
                "OPERATION_STATUS_CONFLICT",
                "asset output requires EXECUTING durable work or an ADMITTED "
                f"transaction command, current status {row[0]}",
            )

    def _require_project_references(self, project_id: str, asset_ids: tuple[str, ...]) -> None:
        if not asset_ids:
            return
        self.cursor.execute(
            "SELECT asset_id, project_id FROM authority_asset WHERE asset_id = ANY(%s) ORDER BY asset_id FOR SHARE",
            [list(asset_ids)],
        )
        rows = self.cursor.fetchall()
        found = {row[0]: row[1] for row in rows}
        if set(found) != set(asset_ids):
            raise KernelError("AUTHORITY_ASSET_REFERENCE_NOT_FOUND", "referenced Asset does not exist")
        if any(owner != project_id for owner in found.values()):
            raise KernelError("CROSS_PROJECT_REFERENCE", "referenced Asset belongs to another project")

    def _locator_for_update(self, project_id: str, logical_ref: str) -> dict[str, str] | None:
        self.cursor.execute(
            """
            SELECT asset_id, current_asset_version_id
            FROM authority_asset_locator
            WHERE project_id = %s AND logical_ref = %s
            FOR UPDATE
            """,
            [project_id, logical_ref],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {"asset_id": row[0], "asset_version_id": row[1]}

    def _ensure_asset(self, asset_id: str, project_id: str, asset_type: str) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_asset (asset_id, project_id, asset_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (asset_id) DO NOTHING
            """,
            [asset_id, project_id, asset_type],
        )
        self.cursor.execute(
            "SELECT project_id, asset_type FROM authority_asset WHERE asset_id = %s FOR UPDATE",
            [asset_id],
        )
        if self.cursor.fetchone() != (project_id, asset_type):
            raise KernelError("CROSS_PROJECT_REFERENCE", "Asset identity belongs to another project or type")

    def _next_version_number(self, asset_id: str) -> int:
        self.cursor.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM authority_asset_version WHERE asset_id = %s",
            [asset_id],
        )
        return int(self.cursor.fetchone()[0])


class AuthorityAssetWriter:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def materialize_output(self, command: AuthorityAssetWriteCommand, *, materialization_guard: Callable[[AuthorityUnitOfWork, AuthorityAssetWriteCommand], None] | None = None) -> AuthorityAssetDocument:
        with AuthorityUnitOfWork(self.database_url) as uow:
            if materialization_guard is not None:
                materialization_guard(uow, command)
            document = uow.repositories.asset_documents.materialize_output(command)
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_asset",
                    "aggregate_id": command.asset_id,
                    "operation_id": command.operation_id,
                    "project_id": command.project_id,
                    "event_type": "authority.asset.materialized",
                    "correlation_id": command.correlation_id,
                    "causation_id": command.causation_id,
                    "payload": {
                        "operation_id": command.operation_id,
                        "asset_id": document.asset_id,
                        "asset_version_id": document.asset_version_id,
                        "logical_ref": document.logical_ref,
                        "category": document.category,
                        "content_hash": document.content_hash,
                        "output_key": command.output_key,
                        "role": command.role,
                        "trace_id": command.trace_id,
                    },
                }
            )
            uow.commit()
            return document


class AuthorityAssetQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def require(
        self,
        *,
        project_id: str,
        logical_ref: str | None = None,
        asset_id: str | None = None,
        asset_version_id: str | None = None,
    ) -> AuthorityAssetDocument:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.asset_documents.require(
                project_id=project_id,
                logical_ref=logical_ref,
                asset_id=asset_id,
                asset_version_id=asset_version_id,
            )

    def list(
        self,
        *,
        project_id: str,
        category: str | None = None,
        asset_type: str | None = None,
        limit: int = 100,
    ) -> list[AuthorityAssetDocument]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.asset_documents.list(
                project_id=project_id,
                category=category,
                asset_type=asset_type,
                limit=limit,
            )

    def latest(self, *, project_id: str, category: str) -> AuthorityAssetDocument:
        rows = self.list(project_id=project_id, category=category, limit=1)
        if not rows:
            raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "authority asset category is empty")
        return rows[0]

    def list_versions(self, *, project_id: str, asset_type: str, limit: int = 100) -> list[AuthorityAssetDocument]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.asset_documents.list_versions(
                project_id=project_id, asset_type=asset_type, limit=limit)

    def count(self, *, project_id: str, category: str | None = None) -> int:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.asset_documents.count(project_id=project_id, category=category)


_DOCUMENT_SELECT = """
SELECT locator.project_id, locator.logical_ref, locator.category,
       asset.asset_id, asset.asset_type, version.asset_version_id,
       version.version_number, version.lifecycle, version.eligibility,
       version.governance, version.content_hash, version.content,
       locator.updated_at
FROM authority_asset_locator AS locator
JOIN authority_asset AS asset ON asset.asset_id = locator.asset_id
JOIN authority_asset_version AS version
  ON version.asset_version_id = locator.current_asset_version_id
 AND version.asset_id = locator.asset_id
"""

_VERSION_DOCUMENT_SELECT = """
SELECT asset.project_id,
       COALESCE(locator.logical_ref, 'asset-version:' || version.asset_version_id),
       COALESCE(locator.category, asset.asset_type),
       asset.asset_id, asset.asset_type, version.asset_version_id,
       version.version_number, version.lifecycle, version.eligibility,
       version.governance, version.content_hash, version.content,
       COALESCE(locator.updated_at, version.created_at)
FROM authority_asset_version AS version
JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
LEFT JOIN authority_asset_locator AS locator
  ON locator.asset_id = asset.asset_id
 AND locator.current_asset_version_id = version.asset_version_id
"""


def _document(row: tuple[Any, ...]) -> AuthorityAssetDocument:
    return AuthorityAssetDocument(
        project_id=row[0],
        logical_ref=row[1],
        category=row[2],
        asset_id=row[3],
        asset_type=row[4],
        asset_version_id=row[5],
        version_number=int(row[6]),
        lifecycle=row[7],
        eligibility=row[8],
        governance=row[9],
        content_hash=row[10],
        content=row[11],
        updated_at=str(row[12]),
    )


def _content_hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AuthorityAssetDocument",
    "AuthorityAssetQuery",
    "AuthorityAssetRef",
    "AuthorityAssetWriter",
]
