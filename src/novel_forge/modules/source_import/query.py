from __future__ import annotations

from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_import_repositories import SourceImportRepository


class SourceImportQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def import_job(
        self,
        *,
        project_id: str,
        import_job_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._require(principal, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            job = repository.job(project_id=project_id, import_job_id=import_job_id)
            work = repository.list_work(
                project_id=project_id, import_job_id=import_job_id
            )
            files = (
                repository.snapshot_files(
                    project_id=project_id,
                    snapshot_asset_version_id=str(
                        job["repository_snapshot_asset_version_id"]
                    ),
                )
                if job["repository_snapshot_asset_version_id"]
                else []
            )
        work_counts = _counts(work, "status")
        work_kind_counts = _counts(work, "work_kind")
        file_counts = _counts(files, "status")
        effective_status = str(job["status"])
        if effective_status == "PROCESSING":
            pending = sum(
                file_counts.get(key, 0)
                for key in ("DISCOVERED", "QUEUED", "PROCESSING", "ANALYZING")
            ) + sum(
                work_counts.get(key, 0)
                for key in ("PLANNED", "RUNNING", "FAILED_RETRYABLE")
            )
            if pending == 0:
                effective_status = (
                    "AWAITING_GOVERNANCE"
                    if work_kind_counts.get("MKAOS_EXTRACTION", 0)
                    else "IMPORTED"
                )
        return {
            **_serializable(job),
            "effective_status": effective_status,
            "work_counts": work_counts,
            "work_kind_counts": work_kind_counts,
            "file_counts": file_counts,
            "downstream": self.downstream_status(
                project_id=project_id,
                import_job_id=import_job_id,
                principal=principal,
            ),
        }

    def list_imports(
        self,
        *,
        project_id: str,
        status: str = "",
        limit: int = 100,
        principal: Principal | None = None,
    ) -> list[dict[str, Any]]:
        self._require(principal, project_id)
        if not 1 <= limit <= 500:
            raise ValueError("query limit must be within 1..500")
        with AuthorityUnitOfWork(self.database_url) as uow:
            rows = SourceImportRepository(uow.cursor).list_jobs(
                project_id=project_id, status=status, limit=limit
            )
        return [_serializable(row) for row in rows]

    def files(
        self,
        *,
        project_id: str,
        import_job_id: str,
        principal: Principal | None = None,
    ) -> list[dict[str, Any]]:
        self._require(principal, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            job = repository.job(project_id=project_id, import_job_id=import_job_id)
            if not job["repository_snapshot_asset_version_id"]:
                return []
            rows = repository.snapshot_files(
                project_id=project_id,
                snapshot_asset_version_id=str(
                    job["repository_snapshot_asset_version_id"]
                ),
            )
            profile_ids = sorted(
                {
                    str(row["source_content_profile_asset_version_id"])
                    for row in rows
                    if row.get("source_content_profile_asset_version_id")
                }
            )
            plan_ids = sorted(
                {
                    str(row["source_analysis_plan_asset_version_id"])
                    for row in rows
                    if row.get("source_analysis_plan_asset_version_id")
                }
            )
            profiles = self._profile_summaries(uow, project_id, profile_ids)
            plans = self._plan_summaries(uow, project_id, plan_ids)
        return [
            {
                **_serializable(row),
                "source_profile": profiles.get(
                    str(row.get("source_content_profile_asset_version_id") or "")
                ),
                "analysis_plan": plans.get(
                    str(row.get("source_analysis_plan_asset_version_id") or "")
                ),
            }
            for row in rows
        ]

    def work(
        self,
        *,
        project_id: str,
        import_job_id: str,
        principal: Principal | None = None,
    ) -> list[dict[str, Any]]:
        self._require(principal, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            rows = SourceImportRepository(uow.cursor).list_work(
                project_id=project_id, import_job_id=import_job_id
            )
        return [_serializable(row) for row in rows]

    def preview(
        self,
        *,
        project_id: str,
        import_job_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        job = self.import_job(
            project_id=project_id,
            import_job_id=import_job_id,
            principal=principal,
        )
        findings: list[dict[str, Any]] = []
        snapshot_id = str(job.get("repository_snapshot_asset_version_id") or "")
        if snapshot_id:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT content->'license_findings'
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s
                    """,
                    [snapshot_id, project_id],
                )
                row = uow.cursor.fetchone()
            if row and isinstance(row[0], list):
                findings = list(row[0])
        return {
            "import_job_id": import_job_id,
            "status": job["status"],
            "effective_status": job["effective_status"],
            "resolved_commit_sha": self._snapshot_value(
                project_id, snapshot_id, "resolved_commit_sha"
            ),
            "manifest_hash": self._snapshot_value(
                project_id, snapshot_id, "manifest_hash"
            ),
            **dict(job.get("counters") or {}),
            "license_findings": findings,
            "preview_has_provider_execution": False,
            "creates_knowledge_assets": False,
        }

    def downstream_status(
        self,
        *,
        project_id: str,
        import_job_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._require(principal, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            job = repository.job(project_id=project_id, import_job_id=import_job_id)
            snapshot = str(job["repository_snapshot_asset_version_id"] or "")
            if not snapshot:
                return {
                    "source_documents": 0,
                    "transforms": 0,
                    "content_profiles": 0,
                    "analysis_plans": 0,
                    "observations": 0,
                    "knowledge_candidates": 0,
                    "review_required": 0,
                    "knowledge_cards": 0,
                    "knowledge_packs": 0,
                }
            uow.cursor.execute(
                """
                WITH imported AS (
                    SELECT DISTINCT source_document_id, source_transform_id
                    FROM authority_source_repository_file
                    WHERE project_id=%s
                      AND repository_snapshot_asset_version_id=%s
                      AND source_document_id IS NOT NULL
                ), profiles AS (
                    SELECT DISTINCT file.source_content_profile_asset_version_id
                    FROM authority_source_repository_file AS file
                    WHERE file.project_id=%s
                      AND file.repository_snapshot_asset_version_id=%s
                      AND file.source_content_profile_asset_version_id IS NOT NULL
                ), plans AS (
                    SELECT DISTINCT file.source_analysis_plan_asset_version_id
                    FROM authority_source_repository_file AS file
                    WHERE file.project_id=%s
                      AND file.repository_snapshot_asset_version_id=%s
                      AND file.source_analysis_plan_asset_version_id IS NOT NULL
                ), observations AS (
                    SELECT DISTINCT observation.asset_version_id
                    FROM authority_source_deconstruction_observation AS observation
                    JOIN plans ON plans.source_analysis_plan_asset_version_id=
                      observation.analysis_plan_asset_version_id
                    WHERE observation.project_id=%s
                ), candidates AS (
                    SELECT DISTINCT candidate.asset_version_id, candidate.status
                    FROM authority_mkaos_knowledge_candidate AS candidate
                    JOIN authority_asset_version AS candidate_version
                      ON candidate_version.asset_version_id=
                         candidate.asset_version_id
                    JOIN LATERAL jsonb_array_elements_text(
                        COALESCE(
                            candidate_version.content->'lineage'
                                ->'observation_asset_version_ids',
                            '[]'::jsonb
                        )
                    ) AS lineage(observation_asset_version_id) ON TRUE
                    JOIN observations
                      ON observations.asset_version_id=
                         lineage.observation_asset_version_id
                    WHERE candidate.project_id=%s
                ), cards AS (
                    SELECT DISTINCT card.asset_version_id
                    FROM authority_mkaos_knowledge_card AS card
                    JOIN candidates
                      ON candidates.asset_version_id=card.candidate_asset_version_id
                    WHERE card.project_id=%s
                )
                SELECT
                    (SELECT COUNT(DISTINCT source_document_id) FROM imported),
                    (SELECT COUNT(DISTINCT source_transform_id) FROM imported),
                    (SELECT COUNT(*) FROM profiles),
                    (SELECT COUNT(*) FROM plans),
                    (SELECT COUNT(*) FROM observations),
                    (SELECT COUNT(*) FROM candidates),
                    (SELECT COUNT(*) FROM candidates WHERE status='NEEDS_REVIEW'),
                    (SELECT COUNT(*) FROM cards),
                    (SELECT COUNT(DISTINCT item.knowledge_pack_asset_version_id)
                     FROM authority_mkaos_knowledge_pack_item AS item
                     JOIN cards ON cards.asset_version_id=
                         item.knowledge_card_asset_version_id)
                """,
                [
                    project_id,
                    snapshot,
                    project_id,
                    snapshot,
                    project_id,
                    snapshot,
                    project_id,
                    project_id,
                    project_id,
                ],
            )
            row = uow.cursor.fetchone()
        keys = (
            "source_documents",
            "transforms",
            "content_profiles",
            "analysis_plans",
            "observations",
            "knowledge_candidates",
            "review_required",
            "knowledge_cards",
            "knowledge_packs",
        )
        return dict(zip(keys, (int(value) for value in row), strict=True))

    def reprocessing_plan(
        self,
        *,
        project_id: str,
        plan_asset_version_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._require(principal, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT plan.reprocessing_plan_id, plan.asset_version_id,
                       version.content->>'cause_type', plan.status,
                       plan.desired_state_hash,
                       plan.created_at
                FROM authority_source_reprocessing_plan AS plan
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=plan.asset_version_id
                WHERE plan.project_id=%s AND plan.asset_version_id=%s
                """,
                [project_id, plan_asset_version_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KeyError("reprocessing plan not found")
            uow.cursor.execute(
                """
                SELECT ordinal, action, target_key, reason, dependency_ids,
                       execution_spec, status, child_operation_id,
                       attempt_count, last_error, result, updated_at
                FROM authority_source_reprocessing_plan_item
                WHERE reprocessing_plan_asset_version_id=%s
                ORDER BY ordinal
                """,
                [plan_asset_version_id],
            )
            items = [
                dict(
                    zip(
                        (
                            "ordinal",
                            "action",
                            "target_key",
                            "reason",
                            "dependency_ids",
                            "execution_spec",
                            "status",
                            "child_operation_id",
                            "attempt_count",
                            "last_error",
                            "result",
                            "updated_at",
                        ),
                        item,
                        strict=True,
                    )
                )
                for item in uow.cursor.fetchall()
            ]
        return {
            "reprocessing_plan_id": row[0],
            "asset_version_id": row[1],
            "cause_type": row[2],
            "status": row[3],
            "desired_state_hash": row[4],
            "created_at": row[5].isoformat(),
            "items": [_serializable(item) for item in items],
        }

    @staticmethod
    def _profile_summaries(
        uow: AuthorityUnitOfWork,
        project_id: str,
        asset_version_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not asset_version_ids:
            return {}
        uow.cursor.execute(
            """
            SELECT asset_version_id, logical_document_scope_hash,
                   classifier_id, classifier_version,
                   classifier_prompt_version, classifier_schema_version,
                   classifier_contract_hash, intelligence_policy_hash,
                   classification_input_hash, classification_output_hash,
                   evidence, predicted_content_type, resolved_content_type,
                   confidence, margin, resolution_mode, resolution_reasons,
                   override_contract_hash, override_decision_ref,
                   status, manual_review_required, evidence_class,
                   execution_asset_version_id, created_by_operation_id
            FROM authority_source_content_profile
            WHERE project_id=%s AND asset_version_id=ANY(%s)
            """,
            [project_id, asset_version_ids],
        )
        keys = (
            "asset_version_id",
            "logical_document_scope_hash",
            "classifier_id",
            "classifier_version",
            "classifier_prompt_version",
            "classifier_schema_version",
            "classifier_contract_hash",
            "intelligence_policy_hash",
            "classification_input_hash",
            "classification_output_hash",
            "evidence",
            "predicted_content_type",
            "resolved_content_type",
            "confidence",
            "margin",
            "resolution_mode",
            "resolution_reasons",
            "override_contract_hash",
            "override_decision_ref",
            "status",
            "manual_review_required",
            "evidence_class",
            "execution_asset_version_id",
            "created_by_operation_id",
        )
        return {
            str(row[0]): _serializable(dict(zip(keys, row, strict=True)))
            for row in uow.cursor.fetchall()
        }

    @staticmethod
    def _plan_summaries(
        uow: AuthorityUnitOfWork,
        project_id: str,
        asset_version_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not asset_version_ids:
            return {}
        uow.cursor.execute(
            """
            SELECT asset_version_id, profile_asset_version_id,
                   logical_document_scope_hash, resolved_content_type,
                   routing_policy_version, profile_id, profile_version,
                   strategy_contract_hash, methodology_contract_hash,
                   methodologies, mkaos_capability,
                   abstraction_policy_version, status,
                   created_by_operation_id
            FROM authority_source_analysis_plan
            WHERE project_id=%s AND asset_version_id=ANY(%s)
            """,
            [project_id, asset_version_ids],
        )
        keys = (
            "asset_version_id",
            "profile_asset_version_id",
            "logical_document_scope_hash",
            "resolved_content_type",
            "routing_policy_version",
            "profile_id",
            "profile_version",
            "strategy_contract_hash",
            "methodology_contract_hash",
            "methodologies",
            "mkaos_capability",
            "abstraction_policy_version",
            "status",
            "created_by_operation_id",
        )
        return {
            str(row[0]): _serializable(dict(zip(keys, row, strict=True)))
            for row in uow.cursor.fetchall()
        }

    def _snapshot_value(self, project_id: str, asset_version_id: str, key: str) -> str:
        if not asset_version_id:
            return ""
        if key not in {"resolved_commit_sha", "manifest_hash"}:
            raise ValueError("unsupported snapshot projection")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT {key} FROM authority_source_repository_snapshot
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row else ""

    @staticmethod
    def _require(principal: Principal | None, project_id: str) -> None:
        if principal is not None:
            principal.require("source.authority.query", project_id)


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row[key])
        result[value] = result.get(value, 0) + 1
    return result


def _serializable(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


__all__ = ["SourceImportQuery"]
