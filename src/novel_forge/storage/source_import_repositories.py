from __future__ import annotations

from typing import Any, Iterable

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class SourceImportRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def require_scope(self, *, project_id: str, workspace_id: str) -> None:
        self.cursor.execute(
            """
            SELECT project.status, workspace.status
            FROM authority_project AS project
            JOIN authority_workspace AS workspace
              ON workspace.workspace_id=%s
             AND workspace.project_id=project.project_id
            WHERE project.project_id=%s
            FOR SHARE OF project, workspace
            """,
            [workspace_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_IMPORT_SCOPE_INVALID",
                "Source import workspace does not belong to the Authority project",
            )
        if "DELETED" in row or "ARCHIVED" in row:
            raise KernelError(
                "SOURCE_IMPORT_SCOPE_BLOCKED",
                "archived or deleted Project/Workspace cannot accept imports",
            )

    def register_job(self, row: dict[str, Any]) -> bool:
        parameters = {
            **row,
            "corpus_snapshot_id": row.get("corpus_snapshot_id"),
            "source_locator": Jsonb(dict(row["source_locator"])),
            "import_policy": Jsonb(dict(row["import_policy"])),
            "intelligence_policy": Jsonb(dict(row["intelligence_policy"])),
            "analysis_override": Jsonb(dict(row.get("analysis_override") or {})),
            "counters": Jsonb(dict(row.get("counters") or {})),
            "failure": Jsonb(dict(row.get("failure") or {})),
        }
        self.cursor.execute(
            """
            INSERT INTO authority_source_import_job (
                import_job_id, project_id, workspace_id, source_type,
                source_locator, requested_ref, import_policy,
                import_policy_hash, intelligence_policy,
                intelligence_policy_hash, analysis_override, mode, status,
                discovery_operation_id, counters, failure, corpus_snapshot_id
            ) VALUES (
                %(import_job_id)s, %(project_id)s, %(workspace_id)s,
                %(source_type)s, %(source_locator)s, %(requested_ref)s,
                %(import_policy)s, %(import_policy_hash)s,
                %(intelligence_policy)s, %(intelligence_policy_hash)s,
                %(analysis_override)s, %(mode)s, %(status)s,
                %(discovery_operation_id)s, %(counters)s, %(failure)s, %(corpus_snapshot_id)s
            )
            ON CONFLICT (discovery_operation_id) DO NOTHING
            RETURNING import_job_id
            """,
            parameters,
        )
        return self.cursor.fetchone() is not None

    def job_for_update(self, *, project_id: str, import_job_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT import_job_id, project_id, workspace_id, source_type,
                   source_locator, requested_ref, import_policy,
                   import_policy_hash, intelligence_policy,
                   intelligence_policy_hash, analysis_override, mode, status,
                   discovery_operation_id, repository_snapshot_asset_version_id,
                   previous_snapshot_asset_version_id, counters, failure,
                   created_at, updated_at
            FROM authority_source_import_job
            WHERE project_id=%s AND import_job_id=%s
            FOR UPDATE
            """,
            [project_id, import_job_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_IMPORT_NOT_FOUND", "Source import job does not exist"
            )
        return _job_row(row)

    def job(self, *, project_id: str, import_job_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT import_job_id, project_id, workspace_id, source_type,
                   source_locator, requested_ref, import_policy,
                   import_policy_hash, intelligence_policy,
                   intelligence_policy_hash, analysis_override, mode, status,
                   discovery_operation_id, repository_snapshot_asset_version_id,
                   previous_snapshot_asset_version_id, counters, failure,
                   created_at, updated_at
            FROM authority_source_import_job
            WHERE project_id=%s AND import_job_id=%s
            """,
            [project_id, import_job_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_IMPORT_NOT_FOUND", "Source import job does not exist"
            )
        return _job_row(row)

    def list_jobs(
        self, *, project_id: str, status: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        parameters: list[Any] = [project_id]
        status_clause = ""
        if status:
            status_clause = "AND status=%s"
            parameters.append(status)
        parameters.append(limit)
        self.cursor.execute(
            f"""
            SELECT import_job_id, project_id, workspace_id, source_type,
                   source_locator, requested_ref, import_policy,
                   import_policy_hash, intelligence_policy,
                   intelligence_policy_hash, analysis_override, mode, status,
                   discovery_operation_id, repository_snapshot_asset_version_id,
                   previous_snapshot_asset_version_id, counters, failure,
                   created_at, updated_at
            FROM authority_source_import_job
            WHERE project_id=%s {status_clause}
            ORDER BY created_at DESC, import_job_id
            LIMIT %s
            """,
            parameters,
        )
        return [_job_row(row) for row in self.cursor.fetchall()]

    def transition_job(
        self,
        *,
        project_id: str,
        import_job_id: str,
        expected: Iterable[str],
        target: str,
        counters: dict[str, Any] | None = None,
        failure: dict[str, Any] | None = None,
        repository_snapshot_asset_version_id: str | None = None,
        previous_snapshot_asset_version_id: str | None = None,
    ) -> None:
        assignments = ["status=%s", "updated_at=NOW()"]
        parameters: list[Any] = [target]
        if counters is not None:
            assignments.append("counters=%s")
            parameters.append(Jsonb(dict(counters)))
        if failure is not None:
            assignments.append("failure=%s")
            parameters.append(Jsonb(dict(failure)))
        if repository_snapshot_asset_version_id is not None:
            assignments.append("repository_snapshot_asset_version_id=%s")
            parameters.append(repository_snapshot_asset_version_id or None)
        if previous_snapshot_asset_version_id is not None:
            assignments.append("previous_snapshot_asset_version_id=%s")
            parameters.append(previous_snapshot_asset_version_id or None)
        parameters.extend([project_id, import_job_id, list(expected)])
        self.cursor.execute(
            f"""
            UPDATE authority_source_import_job
            SET {", ".join(assignments)}
            WHERE project_id=%s AND import_job_id=%s AND status=ANY(%s)
            """,
            parameters,
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "SOURCE_IMPORT_STATUS_CONFLICT",
                f"Source import cannot transition to {target}",
            )

    def snapshot_by_identity(
        self,
        *,
        project_id: str,
        repository_identity: str,
        resolved_commit_sha: str,
        import_policy_hash: str,
        governance_policy_hash: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT repository_snapshot_id, project_id, workspace_id,
                   asset_version_id, repository_identity, repository_url,
                   requested_ref, resolved_commit_sha, manifest_hash,
                   import_policy_hash, governance_policy_hash,
                   file_count, repository_bytes,
                   created_by_operation_id, created_at
            FROM authority_source_repository_snapshot
            WHERE project_id=%s AND repository_identity=%s
              AND resolved_commit_sha=%s AND import_policy_hash=%s
              AND governance_policy_hash=%s
            """,
            [
                project_id,
                repository_identity,
                resolved_commit_sha,
                import_policy_hash,
                governance_policy_hash,
            ],
        )
        row = self.cursor.fetchone()
        return _snapshot_row(row) if row is not None else None

    def latest_snapshot(
        self,
        *,
        project_id: str,
        repository_identity: str,
        import_policy_hash: str,
        governance_policy_hash: str,
        excluding_commit_sha: str = "",
    ) -> dict[str, Any] | None:
        parameters: list[Any] = [
            project_id,
            repository_identity,
            import_policy_hash,
            governance_policy_hash,
        ]
        exclusion = ""
        if excluding_commit_sha:
            exclusion = "AND resolved_commit_sha<>%s"
            parameters.append(excluding_commit_sha)
        self.cursor.execute(
            f"""
            SELECT repository_snapshot_id, project_id, workspace_id,
                   asset_version_id, repository_identity, repository_url,
                   requested_ref, resolved_commit_sha, manifest_hash,
                   import_policy_hash, governance_policy_hash,
                   file_count, repository_bytes,
                   created_by_operation_id, created_at
            FROM authority_source_repository_snapshot
            WHERE project_id=%s AND repository_identity=%s
              AND import_policy_hash=%s AND governance_policy_hash=%s {exclusion}
            ORDER BY created_at DESC, repository_snapshot_id DESC
            LIMIT 1
            """,
            parameters,
        )
        row = self.cursor.fetchone()
        return _snapshot_row(row) if row is not None else None

    def snapshot(self, *, project_id: str, asset_version_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT repository_snapshot_id, project_id, workspace_id,
                   asset_version_id, repository_identity, repository_url,
                   requested_ref, resolved_commit_sha, manifest_hash,
                   import_policy_hash, governance_policy_hash,
                   file_count, repository_bytes,
                   created_by_operation_id, created_at
            FROM authority_source_repository_snapshot
            WHERE project_id=%s AND asset_version_id=%s
            """,
            [project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_IMPORT_SNAPSHOT_NOT_FOUND",
                "Source repository snapshot does not exist",
            )
        return _snapshot_row(row)

    def register_snapshot(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_repository_snapshot (
                repository_snapshot_id, project_id, workspace_id,
                asset_version_id, repository_identity, repository_url,
                requested_ref, resolved_commit_sha, manifest_hash,
                import_policy_hash, governance_policy_hash,
                file_count, repository_bytes,
                created_by_operation_id
            ) VALUES (
                %(repository_snapshot_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(repository_identity)s,
                %(repository_url)s, %(requested_ref)s,
                %(resolved_commit_sha)s, %(manifest_hash)s,
                %(import_policy_hash)s, %(governance_policy_hash)s,
                %(file_count)s,
                %(repository_bytes)s, %(created_by_operation_id)s
            )
            """,
            row,
        )

    def register_files(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.cursor.execute(
                """
                INSERT INTO authority_source_repository_file (
                    repository_snapshot_asset_version_id, project_id, path,
                    file_identity_hash, diff_state, previous_path,
                    previous_object_id, object_mode, object_type, object_id,
                    size_bytes, eligibility, block_reason, content_hash,
                    source_document_id, source_transform_id,
                    processing_operation_id, status, failure
                ) VALUES (
                    %(repository_snapshot_asset_version_id)s, %(project_id)s,
                    %(path)s, %(file_identity_hash)s, %(diff_state)s,
                    %(previous_path)s, %(previous_object_id)s, %(object_mode)s,
                    %(object_type)s, %(object_id)s, %(size_bytes)s,
                    %(eligibility)s, %(block_reason)s, %(content_hash)s,
                    %(source_document_id)s, %(source_transform_id)s,
                    %(processing_operation_id)s, %(status)s, %(failure)s
                )
                """,
                {**row, "failure": Jsonb(dict(row.get("failure") or {}))},
            )

    def snapshot_files(
        self, *, project_id: str, snapshot_asset_version_id: str
    ) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT repository_snapshot_asset_version_id, project_id, path,
                   file_identity_hash, diff_state, previous_path,
                   previous_object_id, object_mode, object_type, object_id,
                   size_bytes, eligibility, block_reason, content_hash,
                   source_document_id, source_transform_id,
                   source_content_profile_asset_version_id,
                   source_analysis_plan_asset_version_id,
                   processing_operation_id, status, failure,
                   created_at, updated_at
            FROM authority_source_repository_file
            WHERE project_id=%s AND repository_snapshot_asset_version_id=%s
            ORDER BY path
            """,
            [project_id, snapshot_asset_version_id],
        )
        return [_file_row(row) for row in self.cursor.fetchall()]

    def reusable_content(
        self, *, project_id: str, content_hash: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT file.source_document_id, file.source_transform_id,
                   file.processing_operation_id, file.path,
                   file.repository_snapshot_asset_version_id
            FROM authority_source_repository_file AS file
            JOIN authority_source_document AS source
              ON source.source_document_id=file.source_document_id
             AND source.project_id=file.project_id
             AND source.governance_status='ELIGIBLE'
            JOIN authority_source_transform AS transform
              ON transform.source_transform_id=file.source_transform_id
             AND transform.project_id=file.project_id
             AND transform.status='ACTIVE'
            WHERE file.project_id=%s AND file.content_hash=%s
              AND file.status IN (
                  'REUSED', 'TRANSFORMED', 'ANALYZING', 'CANDIDATE_READY'
              )
            ORDER BY file.updated_at DESC, file.path
            LIMIT 1
            """,
            [project_id, content_hash],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {
            "source_document_id": row[0],
            "source_transform_id": row[1],
            "processing_operation_id": row[2],
            "path": row[3],
            "repository_snapshot_asset_version_id": row[4],
        }

    def update_file(
        self,
        *,
        project_id: str,
        snapshot_asset_version_id: str,
        path: str,
        expected: Iterable[str],
        status: str,
        source_document_id: str | None = None,
        source_transform_id: str | None = None,
        processing_operation_id: str | None = None,
        failure: dict[str, Any] | None = None,
    ) -> None:
        assignments = ["status=%s", "updated_at=NOW()"]
        parameters: list[Any] = [status]
        for name, value in (
            ("source_document_id", source_document_id),
            ("source_transform_id", source_transform_id),
            ("processing_operation_id", processing_operation_id),
        ):
            if value is not None:
                assignments.append(f"{name}=%s")
                parameters.append(value or None)
        if failure is not None:
            assignments.append("failure=%s")
            parameters.append(Jsonb(dict(failure)))
        parameters.extend([project_id, snapshot_asset_version_id, path, list(expected)])
        self.cursor.execute(
            f"""
            UPDATE authority_source_repository_file
            SET {", ".join(assignments)}
            WHERE project_id=%s
              AND repository_snapshot_asset_version_id=%s
              AND path=%s AND status=ANY(%s)
            """,
            parameters,
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "SOURCE_IMPORT_FILE_STATUS_CONFLICT",
                f"Source import file cannot transition to {status}",
            )

    def update_files_by_content(
        self,
        *,
        project_id: str,
        snapshot_asset_version_id: str,
        content_hash: str,
        expected: Iterable[str],
        status: str,
        source_document_id: str | None,
        source_transform_id: str | None,
        processing_operation_id: str,
    ) -> int:
        self.cursor.execute(
            """
            UPDATE authority_source_repository_file
            SET status=%s,
                source_document_id=COALESCE(%s, source_document_id),
                source_transform_id=COALESCE(%s, source_transform_id),
                processing_operation_id=%s, failure='{}'::jsonb,
                updated_at=NOW()
            WHERE project_id=%s
              AND repository_snapshot_asset_version_id=%s
              AND content_hash=%s AND status=ANY(%s)
            """,
            [
                status,
                source_document_id,
                source_transform_id,
                processing_operation_id,
                project_id,
                snapshot_asset_version_id,
                content_hash,
                list(expected),
            ],
        )
        return int(self.cursor.rowcount)

    def update_files_analysis_by_transform(
        self,
        *,
        project_id: str,
        snapshot_asset_version_id: str,
        source_transform_id: str,
        expected: Iterable[str],
        status: str,
        processing_operation_id: str,
        profile_asset_version_id: str | None = None,
        analysis_plan_asset_version_id: str | None = None,
    ) -> int:
        assignments = [
            "status=%s",
            "processing_operation_id=%s",
            "failure='{}'::jsonb",
            "updated_at=NOW()",
        ]
        parameters: list[Any] = [status, processing_operation_id]
        if profile_asset_version_id is not None:
            assignments.append("source_content_profile_asset_version_id=%s")
            parameters.append(profile_asset_version_id or None)
        if analysis_plan_asset_version_id is not None:
            assignments.append("source_analysis_plan_asset_version_id=%s")
            parameters.append(analysis_plan_asset_version_id or None)
        parameters.extend(
            [
                project_id,
                snapshot_asset_version_id,
                source_transform_id,
                list(expected),
            ]
        )
        self.cursor.execute(
            f"""
            UPDATE authority_source_repository_file
            SET {", ".join(assignments)}
            WHERE project_id=%s
              AND repository_snapshot_asset_version_id=%s
              AND source_transform_id=%s AND status=ANY(%s)
            """,
            parameters,
        )
        return int(self.cursor.rowcount)

    def register_work(self, row: dict[str, Any]) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_source_import_work (
                work_id, import_job_id, project_id, work_kind, stable_key,
                source_path, target_asset_version_id, operation_id, status,
                result, failure
            ) VALUES (
                %(work_id)s, %(import_job_id)s, %(project_id)s,
                %(work_kind)s, %(stable_key)s, %(source_path)s,
                %(target_asset_version_id)s, %(operation_id)s, %(status)s,
                %(result)s, %(failure)s
            )
            ON CONFLICT (import_job_id, work_kind, stable_key) DO NOTHING
            RETURNING work_id
            """,
            {
                **row,
                "result": Jsonb(dict(row.get("result") or {})),
                "failure": Jsonb(dict(row.get("failure") or {})),
            },
        )
        return self.cursor.fetchone() is not None

    def update_work(
        self,
        *,
        project_id: str,
        operation_id: str,
        expected: Iterable[str],
        status: str,
        result: dict[str, Any] | None = None,
        failure: dict[str, Any] | None = None,
    ) -> None:
        assignments = ["status=%s", "updated_at=NOW()"]
        parameters: list[Any] = [status]
        if result is not None:
            assignments.append("result=%s")
            parameters.append(Jsonb(dict(result)))
        if failure is not None:
            assignments.append("failure=%s")
            parameters.append(Jsonb(dict(failure)))
        parameters.extend([project_id, operation_id, list(expected)])
        self.cursor.execute(
            f"""
            UPDATE authority_source_import_work
            SET {", ".join(assignments)}
            WHERE project_id=%s AND operation_id=%s AND status=ANY(%s)
            """,
            parameters,
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "SOURCE_IMPORT_WORK_STATUS_CONFLICT",
                f"Source import work cannot transition to {status}",
            )

    def work_by_operation(
        self, *, project_id: str, operation_id: str, for_update: bool = False
    ) -> dict[str, Any]:
        lock = "FOR UPDATE" if for_update else ""
        self.cursor.execute(
            f"""
            SELECT work_id, import_job_id, project_id, work_kind, stable_key,
                   source_path, target_asset_version_id, operation_id, status,
                   result, failure, created_at, updated_at
            FROM authority_source_import_work
            WHERE project_id=%s AND operation_id=%s {lock}
            """,
            [project_id, operation_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_IMPORT_WORK_NOT_FOUND", "Source import work does not exist"
            )
        return _work_row(row)

    def list_work(self, *, project_id: str, import_job_id: str) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT work_id, import_job_id, project_id, work_kind, stable_key,
                   source_path, target_asset_version_id, operation_id, status,
                   result, failure, created_at, updated_at
            FROM authority_source_import_work
            WHERE project_id=%s AND import_job_id=%s
            ORDER BY created_at, work_kind, stable_key
            """,
            [project_id, import_job_id],
        )
        return [_work_row(row) for row in self.cursor.fetchall()]


def _job_row(row: Any) -> dict[str, Any]:
    keys = (
        "import_job_id",
        "project_id",
        "workspace_id",
        "source_type",
        "source_locator",
        "requested_ref",
        "import_policy",
        "import_policy_hash",
        "intelligence_policy",
        "intelligence_policy_hash",
        "analysis_override",
        "mode",
        "status",
        "discovery_operation_id",
        "repository_snapshot_asset_version_id",
        "previous_snapshot_asset_version_id",
        "counters",
        "failure",
        "created_at",
        "updated_at",
    )
    return dict(zip(keys, row, strict=True))


def _snapshot_row(row: Any) -> dict[str, Any]:
    keys = (
        "repository_snapshot_id",
        "project_id",
        "workspace_id",
        "asset_version_id",
        "repository_identity",
        "repository_url",
        "requested_ref",
        "resolved_commit_sha",
        "manifest_hash",
        "import_policy_hash",
        "governance_policy_hash",
        "file_count",
        "repository_bytes",
        "created_by_operation_id",
        "created_at",
    )
    return dict(zip(keys, row, strict=True))


def _file_row(row: Any) -> dict[str, Any]:
    keys = (
        "repository_snapshot_asset_version_id",
        "project_id",
        "path",
        "file_identity_hash",
        "diff_state",
        "previous_path",
        "previous_object_id",
        "object_mode",
        "object_type",
        "object_id",
        "size_bytes",
        "eligibility",
        "block_reason",
        "content_hash",
        "source_document_id",
        "source_transform_id",
        "source_content_profile_asset_version_id",
        "source_analysis_plan_asset_version_id",
        "processing_operation_id",
        "status",
        "failure",
        "created_at",
        "updated_at",
    )
    return dict(zip(keys, row, strict=True))


def _work_row(row: Any) -> dict[str, Any]:
    keys = (
        "work_id",
        "import_job_id",
        "project_id",
        "work_kind",
        "stable_key",
        "source_path",
        "target_asset_version_id",
        "operation_id",
        "status",
        "result",
        "failure",
        "created_at",
        "updated_at",
    )
    return dict(zip(keys, row, strict=True))


__all__ = ["SourceImportRepository"]
