"""Resumable Legacy import coordinator and reconciliation queries."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.legacy_migration.application import (
    LegacyImportApplication,
    LegacyImportCommand,
)
from novel_forge.modules.legacy_migration.scanner import (
    LegacySnapshotRecord,
    scan_legacy_snapshot,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
    ProjectAuthorityQuery,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class LegacyMigrationService:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        actor_id: str = "authority-migration-operator",
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.actor_id = actor_id

    def import_snapshot(
        self,
        root: str | Path,
        *,
        dry_run: bool = False,
        resume: bool = True,
        require_read_only: bool = True,
    ) -> dict[str, Any]:
        snapshot_root = Path(root).resolve()
        scan = scan_legacy_snapshot(snapshot_root)
        if dry_run:
            return {
                "mode": "DRY_RUN",
                "snapshot_hash": scan.snapshot_hash,
                "counts": scan.counts,
                "records": [asdict(record) for record in scan.records],
                "production_mutation_performed": False,
            }
        if require_read_only and snapshot_root.stat().st_mode & 0o222:
            raise KernelError(
                "LEGACY_SNAPSHOT_NOT_FROZEN",
                "non-dry-run import requires a read-only frozen snapshot root",
            )
        run_id = _stable_id("migration-run", scan.snapshot_hash)
        self._start_run(run_id, scan.snapshot_hash, str(snapshot_root), resume=resume)
        existing_run = self.status(run_id)
        if existing_run["status"] == "SUCCEEDED":
            return existing_run
        project_workspaces = self._bootstrap_projects(scan.records, run_id)
        imported, quarantined, skipped = self._resume_counts(run_id)
        failed = 0
        importer = LegacyImportApplication(
            self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        for ordinal, record in enumerate(scan.records, start=1):
            existing = self._existing_item(run_id, record.source_ref)
            if existing in {"IMPORTED", "NEEDS_REVIEW", "INELIGIBLE", "QUARANTINED", "SKIPPED_DUPLICATE"}:
                continue
            self._upsert_item(run_id, record, status="DISCOVERED", decision=record.decision)
            if record.decision != "IMPORT":
                if record.status in {"QUARANTINED", "INELIGIBLE"}:
                    self._quarantine(run_id, record)
                    quarantined += 1
                else:
                    skipped += 1
                self._upsert_item(
                    run_id,
                    record,
                    status=record.status,
                    decision=record.decision,
                    error_code=record.error_code,
                )
                self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
                continue
            workspace_id = project_workspaces.get(record.project_id)
            if not workspace_id:
                missing = _with_error(record, "AUTHORITY_PROJECT_MISSING", "project shell was not imported")
                self._quarantine(run_id, missing)
                self._upsert_item(
                    run_id,
                    missing,
                    status="QUARANTINED",
                    decision="QUARANTINE",
                    error_code=missing.error_code,
                )
                quarantined += 1
                self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
                continue
            try:
                result = importer.execute(
                    LegacyImportCommand(
                        project_id=record.project_id,
                        workspace_id=workspace_id,
                        actor_id=self.actor_id,
                        trace_id=f"trace:{run_id}",
                        correlation_id=f"correlation:{run_id}",
                        idempotency_key=(
                            f"legacy-import:{record.project_id}:{record.stable_business_key}"
                        ),
                        source_ref=record.source_ref,
                        source_hash=record.source_hash,
                        source_asset_type=record.source_asset_type,
                        stable_business_key=record.stable_business_key,
                        payload=dict(record.payload or {}),
                    )
                )
                self._upsert_item(
                    run_id,
                    record,
                    status="NEEDS_REVIEW",
                    decision="IMPORT",
                    operation_id=result["operation_id"],
                    target_asset_id=result["asset_id"],
                    target_asset_version_id=result["asset_version_id"],
                    evidence={
                        "source_hash": record.source_hash,
                        "target_content_hash": result["content_hash"],
                        "replayed": result["replayed"],
                        "production_context_eligible": False,
                    },
                )
                imported += 1
            except Exception as exc:
                conflict = _with_error(
                    record,
                    "IMPORT_OPERATION_FAILED",
                    f"{type(exc).__name__}: {exc}",
                )
                self._quarantine(run_id, conflict)
                self._upsert_item(
                    run_id,
                    conflict,
                    status="FAILED",
                    decision="QUARANTINE",
                    error_code=conflict.error_code,
                )
                failed += 1
            self._checkpoint(run_id, ordinal, imported, quarantined, skipped, failed)
        status = "FAILED" if failed else ("QUARANTINED" if quarantined else "SUCCEEDED")
        self._finish_run(run_id, status, imported, quarantined, skipped, failed)
        return self.status(run_id)

    def status(self, migration_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT migration_run_id, source_kind, source_hash, status, report,
                       workspace_id, snapshot_hash, mode, idempotency_key,
                       cursor_state, counts, created_at, updated_at, finished_at
                FROM authority_migration_run WHERE migration_run_id = %s
                """,
                [migration_run_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError("MIGRATION_RUN_NOT_FOUND", "migration run does not exist")
            uow.cursor.execute(
                """
                SELECT status, COUNT(*) FROM authority_legacy_migration_item
                WHERE migration_run_id = %s GROUP BY status ORDER BY status
                """,
                [migration_run_id],
            )
            item_counts = {status: int(count) for status, count in uow.cursor.fetchall()}
        return {
            "migration_run_id": row[0],
            "source_kind": row[1],
            "source_hash": row[2],
            "status": row[3],
            "report": row[4],
            "workspace_id": row[5],
            "snapshot_hash": row[6],
            "mode": row[7],
            "idempotency_key": row[8],
            "cursor_state": row[9],
            "counts": row[10],
            "created_at": str(row[11]),
            "updated_at": str(row[12]),
            "finished_at": str(row[13]) if row[13] else None,
            "item_counts": item_counts,
        }

    def verify(
        self, migration_run_id: str, *, snapshot_root: str | Path | None = None
    ) -> dict[str, Any]:
        status = self.status(migration_run_id)
        hash_matches = True
        actual_hash = status["snapshot_hash"]
        if snapshot_root is not None:
            actual_hash = scan_legacy_snapshot(snapshot_root).snapshot_hash
            hash_matches = actual_hash == status["snapshot_hash"]
        counts = status["item_counts"]
        terminal = sum(
            counts.get(value, 0)
            for value in (
                "IMPORTED", "NEEDS_REVIEW", "INELIGIBLE", "QUARANTINED",
                "SKIPPED_DUPLICATE", "FAILED",
            )
        )
        total = sum(counts.values())
        return {
            "migration_run_id": migration_run_id,
            "status": "PASS" if hash_matches and terminal == total else "FAIL",
            "expected_snapshot_hash": status["snapshot_hash"],
            "actual_snapshot_hash": actual_hash,
            "hash_matches": hash_matches,
            "item_count": total,
            "terminal_item_count": terminal,
            "reconciled": terminal == total,
            "production_assets_activated": 0,
            "needs_review_count": counts.get("NEEDS_REVIEW", 0),
            "quarantine_count": counts.get("QUARANTINED", 0) + counts.get("FAILED", 0),
        }

    def quarantine_list(
        self, *, migration_run_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses = ["resolution_status = 'OPEN'"]
        params: list[Any] = []
        if migration_run_id:
            clauses.append("migration_run_id = %s")
            params.append(migration_run_id)
        params.append(limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT quarantine_id, migration_run_id, project_id, workspace_id,
                       category, source_ref, reason_code, payload_hash, payload,
                       resolution_status, created_at
                FROM authority_data_quarantine WHERE """
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC, quarantine_id LIMIT %s",
                params,
            )
            rows = uow.cursor.fetchall()
        keys = (
            "quarantine_id", "migration_run_id", "project_id", "workspace_id",
            "category", "source_ref", "reason_code", "payload_hash", "payload",
            "resolution_status", "created_at",
        )
        return [dict(zip(keys, (*row[:-1], str(row[-1])), strict=True)) for row in rows]

    def _bootstrap_projects(
        self, records: tuple[LegacySnapshotRecord, ...], run_id: str
    ) -> dict[str, str]:
        query = ProjectAuthorityQuery(self.database_url)
        application = ProjectAuthorityApplication(
            self.database_url,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            worker_id="legacy-project-migration-worker",
        )
        workspaces: dict[str, str] = {}
        for record in records:
            if record.payload is None or record.source_asset_type != "project_workspace_state":
                continue
            workspace_id = record.workspace_id or f"workspace:{record.project_id}"
            try:
                existing = query.require_project(record.project_id)
                workspaces[record.project_id] = str(existing["workspace_id"])
                continue
            except KernelError as exc:
                if exc.code != "PROJECT_NOT_FOUND":
                    raise
            content = record.payload.get("content") or {}
            memory = content.get("memory") if isinstance(content.get("memory"), dict) else {}
            metadata = record.payload.get("metadata") or {}
            project_config = _remove_paths(content.get("project_config") or {})
            result = application.execute(
                ProjectAuthorityCommand(
                    definition_name="project_lifecycle.create",
                    project_id=record.project_id,
                    workspace_id=workspace_id,
                    actor_id=self.actor_id,
                    idempotency_key=f"legacy-project-shell:{record.project_id}",
                    trace_id=f"trace:{run_id}",
                    correlation_id=f"correlation:{run_id}",
                    payload={
                        "title": str(memory.get("project_title") or record.payload.get("title") or record.project_id),
                        "series_title": str(memory.get("series_title") or metadata.get("series_title") or ""),
                        "book_number": memory.get("book_number") or metadata.get("book_number"),
                        "health": "BLOCKED",
                        "stage": "DESIGN",
                        "config": {
                            **project_config,
                            "legacy_import_run_id": run_id,
                            "migration_review_required": True,
                        },
                    },
                )
            )
            detail = query.require_project(record.project_id)
            application.execute(
                ProjectAuthorityCommand(
                    definition_name="project_lifecycle.transition",
                    project_id=record.project_id,
                    workspace_id=workspace_id,
                    actor_id=self.actor_id,
                    idempotency_key=f"legacy-project-shell-pause:{record.project_id}",
                    trace_id=f"trace:{run_id}",
                    correlation_id=f"correlation:{run_id}",
                    payload={"target_status": "PAUSED"},
                    expected_version=detail["version"],
                    expected_current_asset_version_id=detail["asset_version_id"],
                )
            )
            workspaces[record.project_id] = str(result["workspace_id"])
        return workspaces

    def _start_run(
        self, run_id: str, snapshot_hash: str, source_root: str, *, resume: bool
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_migration_run(
                    migration_run_id, source_kind, source_hash, status, report,
                    snapshot_hash, mode, idempotency_key, cursor_state, counts
                ) VALUES (%s, 'legacy_localstorage_snapshot', %s, 'RUNNING', %s,
                          %s, 'IMPORT', %s, '{}'::jsonb, '{}'::jsonb)
                ON CONFLICT (migration_run_id) DO NOTHING
                """,
                [run_id, snapshot_hash, Jsonb({"source_root": source_root}), snapshot_hash, snapshot_hash],
            )
            if uow.cursor.rowcount == 0 and not resume:
                raise KernelError("MIGRATION_RUN_EXISTS", "migration run already exists; use resume")
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET status = 'RUNNING', updated_at = NOW()
                WHERE migration_run_id = %s
                  AND status NOT IN ('SUCCEEDED')
                """,
                [run_id],
            )
            uow.commit()

    def _existing_item(self, run_id: str, source_ref: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT status FROM authority_legacy_migration_item WHERE migration_run_id=%s AND source_ref=%s",
                [run_id, source_ref],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row else ""

    def _resume_counts(self, run_id: str) -> tuple[int, int, int]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('IMPORTED','NEEDS_REVIEW')),
                    COUNT(*) FILTER (WHERE status IN ('QUARANTINED','INELIGIBLE')),
                    COUNT(*) FILTER (WHERE status = 'SKIPPED_DUPLICATE')
                FROM authority_legacy_migration_item
                WHERE migration_run_id = %s
                """,
                [run_id],
            )
            row = uow.cursor.fetchone()
        return int(row[0]), int(row[1]), int(row[2])

    def _upsert_item(
        self,
        run_id: str,
        record: LegacySnapshotRecord,
        *,
        status: str,
        decision: str,
        error_code: str = "",
        operation_id: str | None = None,
        target_asset_id: str | None = None,
        target_asset_version_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        item_id = _stable_id("migration-item", run_id, record.source_ref)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_legacy_migration_item(
                    migration_item_id, migration_run_id, project_id, workspace_id,
                    source_ref, source_category, source_hash, stable_business_key,
                    operation_id, target_asset_id, target_asset_version_id,
                    status, decision, error_code, evidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s)
                ON CONFLICT (migration_run_id, source_ref) DO UPDATE
                SET operation_id=COALESCE(EXCLUDED.operation_id, authority_legacy_migration_item.operation_id),
                    target_asset_id=COALESCE(EXCLUDED.target_asset_id, authority_legacy_migration_item.target_asset_id),
                    target_asset_version_id=COALESCE(EXCLUDED.target_asset_version_id, authority_legacy_migration_item.target_asset_version_id),
                    status=EXCLUDED.status, decision=EXCLUDED.decision,
                    error_code=EXCLUDED.error_code, evidence=EXCLUDED.evidence,
                    updated_at=NOW()
                """,
                [
                    item_id, run_id, record.project_id, record.workspace_id,
                    record.source_ref, record.category, record.source_hash,
                    record.stable_business_key, operation_id, target_asset_id,
                    target_asset_version_id, status, decision, error_code,
                    Jsonb(evidence or {"errors": list(record.errors)}),
                ],
            )
            uow.commit()

    def _quarantine(self, run_id: str, record: LegacySnapshotRecord) -> None:
        quarantine_id = _stable_id("quarantine", run_id, record.source_ref, record.source_hash)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_data_quarantine(
                    quarantine_id, migration_run_id, source_ref, reason_code,
                    payload_hash, payload, project_id, workspace_id, category
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (quarantine_id) DO NOTHING
                """,
                [
                    quarantine_id, run_id, record.source_ref,
                    record.error_code or "MIGRATION_POLICY_REJECTED", record.source_hash,
                    Jsonb({"errors": list(record.errors), "metadata": asdict(record)}),
                    record.project_id, record.workspace_id, record.category,
                ],
            )
            uow.commit()

    def _checkpoint(
        self, run_id: str, ordinal: int, imported: int, quarantined: int, skipped: int, failed: int
    ) -> None:
        counts = {"imported": imported, "quarantined": quarantined, "skipped": skipped, "failed": failed}
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET cursor_state=%s, counts=%s, updated_at=NOW()
                WHERE migration_run_id=%s
                """,
                [Jsonb({"last_ordinal": ordinal}), Jsonb(counts), run_id],
            )
            uow.commit()

    def _finish_run(
        self, run_id: str, status: str, imported: int, quarantined: int, skipped: int, failed: int
    ) -> None:
        counts = {"imported": imported, "quarantined": quarantined, "skipped": skipped, "failed": failed}
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_migration_run
                SET status=%s, counts=%s, report=%s, updated_at=NOW(), finished_at=NOW()
                WHERE migration_run_id=%s
                """,
                [status, Jsonb(counts), Jsonb({"counts": counts, "auto_activated": 0}), run_id],
            )
            uow.commit()


def _remove_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_paths(child)
            for key, child in value.items()
            if not str(key).lower().endswith(("_path", "_file", "_directory"))
        }
    if isinstance(value, list):
        return [_remove_paths(child) for child in value]
    return value


def _with_error(record: LegacySnapshotRecord, code: str, message: str) -> LegacySnapshotRecord:
    from dataclasses import replace

    return replace(
        record,
        decision="QUARANTINE",
        status="QUARANTINED",
        error_code=code,
        errors=(*record.errors, message),
    )


def _stable_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, "\x1f".join(parts)))


__all__ = ["LegacyMigrationService"]
