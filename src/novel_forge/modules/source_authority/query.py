from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository


class SourceAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def corpus_import(self, *, project_id: str, import_job_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return SourceAuthorityRepository(uow.cursor).corpus_import_status(project_id, import_job_id)

    def corpus_operation(self, *, project_id: str, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return SourceAuthorityRepository(uow.cursor).corpus_operation_status(project_id, operation_id)

    def corpus_records(self, *, kind: str, project_id: str, parent_id: str = "", after: str = "", limit: int = 100) -> list[dict[str, Any]]:
        if kind not in {"source", "rights", "snapshot", "book_identity", "edition", "admission", "membership"}:
            raise ValueError("unsupported Corpus record kind")
        with AuthorityUnitOfWork(self.database_url) as uow:
            return SourceAuthorityRepository(uow.cursor).corpus_page(kind, project_id, parent_id=parent_id, after=after, limit=limit)

    def corpus_lineage(self, *, project_id: str, edition_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceAuthorityRepository(uow.cursor)
            edition = repository.corpus_record("edition", project_id, edition_id)
            snapshot = repository.corpus_record("snapshot", project_id, edition["snapshot_id"])
            return {
                "edition": edition, "snapshot": snapshot,
                "book_source_identity": repository.corpus_record("book_identity", project_id, edition["book_source_id"]),
                "source": repository.corpus_record("source", project_id, edition["source_id"]),
                "rights": repository.corpus_record("rights", project_id, snapshot["rights_id"]),
                "current_rights_id": repository.corpus_latest("rights", project_id, edition["source_id"]),
                "retired": repository.corpus_existing("retirement", project_id, edition["source_id"]),
                "memberships": repository.corpus_page("membership", project_id, parent_id=edition_id),
                "admissions": repository.corpus_page("admission", project_id, parent_id=edition_id),
                "admissions_page_limit": 100,
            }

    def list_documents(
        self,
        *,
        project_id: str,
        governance_status: str = "",
        source_document_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id or limit < 1 or limit > 500:
            raise ValueError("project_id and a limit between 1 and 500 are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source.source_document_id, source.project_id,
                       source.workspace_id, source.asset_version_id,
                       source.blob_id, source.source_content_hash,
                       source.source_size, source.media_type, source.title,
                       source.source_kind, source.source_uri,
                       source.rights_authorization, source.license_name,
                       source.copyright_boundary, source.governance_status,
                       source.created_by_operation_id, version.lifecycle,
                       version.eligibility, version.governance, version.content,
                       source.created_at
                FROM authority_source_document AS source
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = source.asset_version_id
                WHERE source.project_id = %s
                  AND (%s = '' OR source.governance_status = %s)
                  AND (%s = '' OR source.source_document_id = %s)
                ORDER BY source.created_at DESC, source.source_document_id
                LIMIT %s
                """,
                [
                    project_id,
                    governance_status,
                    governance_status,
                    source_document_id,
                    source_document_id,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "source_document_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "blob_id",
            "source_content_hash",
            "source_size",
            "media_type",
            "title",
            "source_kind",
            "source_uri",
            "rights_authorization",
            "license_name",
            "copyright_boundary",
            "governance_status",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def require_document(
        self, *, project_id: str, source_document_id: str
    ) -> dict[str, Any]:
        rows = self.list_documents(
            project_id=project_id,
            source_document_id=source_document_id,
            limit=1,
        )
        if not rows:
            raise KernelError(
                "SOURCE_DOCUMENT_NOT_FOUND",
                "SourceDocument does not exist in the Authority project",
            )
        return rows[0]

    def list_transforms(
        self,
        *,
        project_id: str,
        source_document_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id or not source_document_id or limit < 1 or limit > 500:
            raise ValueError("project/source identity and a valid limit are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT transform.source_transform_id, transform.project_id,
                       transform.workspace_id, transform.source_document_id,
                       transform.source_asset_version_id,
                       transform.asset_version_id,
                       transform.created_by_operation_id,
                       transform.normalization_version,
                       transform.chunking_version,
                       transform.chunking_policy_hash,
                       transform.manifest_hash, transform.chunk_count,
                       transform.total_chunk_bytes, transform.status,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, transform.created_at
                FROM authority_source_transform AS transform
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = transform.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = transform.created_by_operation_id
                WHERE transform.project_id = %s
                  AND transform.source_document_id = %s
                ORDER BY transform.created_at DESC, transform.source_transform_id
                LIMIT %s
                """,
                [project_id, source_document_id, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "source_transform_id",
            "project_id",
            "workspace_id",
            "source_document_id",
            "source_asset_version_id",
            "asset_version_id",
            "created_by_operation_id",
            "normalization_version",
            "chunking_version",
            "chunking_policy_hash",
            "manifest_hash",
            "chunk_count",
            "total_chunk_bytes",
            "transform_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_chunks(
        self,
        *,
        project_id: str,
        source_transform_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not project_id or not source_transform_id or limit < 1 or limit > 10_000:
            raise ValueError(
                "project/transform identity and a valid limit are required"
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT chunk.source_chunk_id, chunk.project_id,
                       chunk.workspace_id, chunk.source_transform_id,
                       chunk.source_document_id, chunk.asset_version_id,
                       chunk.blob_id, chunk.chunk_index, chunk.content_hash,
                       chunk.byte_size, chunk.character_count,
                       chunk.token_count, chunk.source_byte_start,
                       chunk.source_byte_end, chunk.created_by_operation_id,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content, chunk.created_at
                FROM authority_source_chunk AS chunk
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = chunk.asset_version_id
                WHERE chunk.project_id = %s
                  AND chunk.source_transform_id = %s
                ORDER BY chunk.chunk_index
                LIMIT %s
                """,
                [project_id, source_transform_id, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "source_chunk_id",
            "project_id",
            "workspace_id",
            "source_transform_id",
            "source_document_id",
            "asset_version_id",
            "blob_id",
            "chunk_index",
            "content_hash",
            "byte_size",
            "character_count",
            "token_count",
            "source_byte_start",
            "source_byte_end",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_observations(
        self,
        *,
        project_id: str,
        dimension: str = "",
        scale: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not project_id or limit < 1 or limit > 1_000:
            raise ValueError("project_id and a valid limit are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT observation.observation_id, observation.asset_version_id,
                       observation.workspace_id, observation.scope,
                       observation.scope_hash, observation.dimension,
                       observation.scale, observation.analyzer_id,
                       observation.analyzer_version,
                       observation.analyzer_contract_hash,
                       observation.prompt_id, observation.prompt_version,
                       observation.skill_id, observation.skill_version,
                       observation.capability_id,
                       observation.capability_version,
                       observation.provider_policy_version,
                       observation.aggregation_policy_version,
                       observation.observation_schema_version,
                       observation.observation_hash, observation.confidence,
                       observation.evidence_class,
                       observation.analysis_plan_asset_version_id,
                       observation.methodology_content_hash,
                       observation.analysis_lineage_version,
                       observation.execution_asset_version_id,
                       observation.created_by_operation_id,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       observation.created_at
                FROM authority_source_deconstruction_observation AS observation
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=observation.asset_version_id
                WHERE observation.project_id=%s
                  AND (%s='' OR observation.dimension=%s)
                  AND (%s='' OR observation.scale=%s)
                ORDER BY observation.created_at DESC,
                         observation.asset_version_id
                LIMIT %s
                """,
                [project_id, dimension, dimension, scale, scale, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "observation_id",
            "asset_version_id",
            "workspace_id",
            "scope",
            "scope_hash",
            "dimension",
            "scale",
            "analyzer_id",
            "analyzer_version",
            "analyzer_contract_hash",
            "prompt_id",
            "prompt_version",
            "skill_id",
            "skill_version",
            "capability_id",
            "capability_version",
            "provider_policy_version",
            "aggregation_policy_version",
            "observation_schema_version",
            "observation_hash",
            "confidence",
            "evidence_class",
            "analysis_plan_asset_version_id",
            "methodology_content_hash",
            "analysis_lineage_version",
            "execution_asset_version_id",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_reprocessing_plans(
        self, *, project_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not project_id or limit < 1 or limit > 500:
            raise ValueError("project_id and a valid limit are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT plan.reprocessing_plan_id, plan.asset_version_id,
                       plan.workspace_id, plan.source_transform_id,
                       plan.desired_state_hash, plan.plan_hash,
                       plan.item_count, plan.status,
                       plan.created_by_operation_id, version.content,
                       plan.created_at
                FROM authority_source_reprocessing_plan AS plan
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=plan.asset_version_id
                WHERE plan.project_id=%s
                ORDER BY plan.created_at DESC, plan.asset_version_id
                LIMIT %s
                """,
                [project_id, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "reprocessing_plan_id",
            "asset_version_id",
            "workspace_id",
            "source_transform_id",
            "desired_state_hash",
            "plan_hash",
            "item_count",
            "plan_status",
            "created_by_operation_id",
            "content",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_invalidations(
        self,
        *,
        project_id: str,
        status: str = "OPEN",
        dimension: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if (
            not project_id
            or status not in {"", "OPEN", "RESOLVED", "SUPERSEDED"}
            or limit < 1
            or limit > 1_000
        ):
            raise ValueError("project_id, invalidation status, and limit are invalid")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT invalidation.invalidation_id,
                       invalidation.target_asset_version_id,
                       asset.asset_type, target.lifecycle, target.eligibility,
                       invalidation.cause_type, invalidation.cause_ref,
                       invalidation.dimension, invalidation.status,
                       invalidation.created_by_operation_id,
                       invalidation.resolved_by_operation_id,
                       invalidation.created_at, invalidation.resolved_at
                FROM authority_content_invalidation AS invalidation
                JOIN authority_asset_version AS target
                  ON target.asset_version_id=invalidation.target_asset_version_id
                JOIN authority_asset AS asset
                  ON asset.asset_id=target.asset_id
                WHERE invalidation.project_id=%s
                  AND (%s='' OR invalidation.status=%s)
                  AND (%s='' OR invalidation.dimension=%s)
                ORDER BY invalidation.created_at DESC,
                         invalidation.invalidation_id
                LIMIT %s
                """,
                [project_id, status, status, dimension, dimension, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "invalidation_id",
            "target_asset_version_id",
            "target_asset_type",
            "target_lifecycle",
            "target_eligibility",
            "cause_type",
            "cause_ref",
            "dimension",
            "status",
            "created_by_operation_id",
            "resolved_by_operation_id",
            "created_at",
            "resolved_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def data_import_admission(self, *, project_id: str) -> dict[str, Any]:
        if not project_id:
            raise ValueError("project_id is required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM authority_project WHERE project_id=%s)",
                [project_id],
            )
            if not uow.cursor.fetchone()[0]:
                raise KernelError(
                    "PROJECT_NOT_FOUND", "Data Import Admission project does not exist"
                )
            counts = _admission_counts(uow.cursor, project_id)
            checks = [
                _check(
                    "repository_import_runtime",
                    counts["repository_snapshot_count"] > 0
                    and counts["invalid_repository_snapshots"] == 0,
                    counts["repository_snapshot_count"],
                    "repository snapshots freeze exact commits, manifests, and policies",
                ),
                _check(
                    "incremental_repository_import",
                    counts["incremental_snapshot_count"] > 0,
                    counts["incremental_snapshot_count"],
                    "a later snapshot proves manifest-diff reuse against its predecessor",
                ),
                _check(
                    "source_deduplication",
                    counts["source_count"] > 0 and counts["duplicate_sources"] == 0,
                    counts["source_count"],
                    "content-hash Source identity is unique within the project",
                ),
                _check(
                    "source_integrity",
                    counts["source_count"] > 0
                    and counts["invalid_source_receipts"] == 0,
                    counts["source_count"] - counts["invalid_source_receipts"],
                    "SourceDocument identities match AVAILABLE Blob receipts",
                ),
                _check(
                    "rights_copyright_governance",
                    counts["source_count"] > 0
                    and counts["governance_blocked_sources"] == 0,
                    counts["source_count"] - counts["governance_blocked_sources"],
                    "all admitted Sources are rights-eligible",
                ),
                _check(
                    "versioned_transform",
                    counts["transform_count"] > 0 and counts["invalid_transforms"] == 0,
                    counts["transform_count"],
                    "normalization/chunking versions and manifests are frozen",
                ),
                _check(
                    "stable_evidence_addressing",
                    counts["evidence_span_count"] > 0,
                    counts["evidence_span_count"],
                    "stable EvidenceSpan identities address immutable SourceChunk versions",
                ),
                _check(
                    "deconstruction_versioning",
                    counts["observation_count"] > 0
                    and counts["invalid_observations"] == 0,
                    counts["observation_count"],
                    "Observations freeze analyzer/prompt/skill/schema/provider contracts",
                ),
                _check(
                    "mkaos_lineage",
                    counts["observation_candidate_edges"] > 0
                    and counts["production_knowledge_cards"] > 0,
                    counts["observation_candidate_edges"],
                    "Observation to Candidate to approved non-fixture KnowledgeCard is proven",
                ),
                _check(
                    "replay",
                    counts["reuse_plan_items"] > 0,
                    counts["reuse_plan_items"],
                    "a persisted plan proves unchanged Observation reuse",
                ),
                _check(
                    "selective_reprocessing",
                    counts["mixed_selective_plans"] > 0,
                    counts["mixed_selective_plans"],
                    "one plan contains both REUSE and dimension-scoped RECOMPUTE",
                ),
                _check(
                    "reprocessing_execution",
                    counts["applied_reprocessing_items"] > 0,
                    counts["applied_reprocessing_items"],
                    "planned recomputation has durable APPLIED or REUSED item evidence",
                ),
                _check(
                    "invalidation",
                    counts["invalidation_count"] > 0,
                    counts["invalidation_count"],
                    "lineage-targeted invalidations are durable",
                ),
                _check(
                    "failure_recovery",
                    counts["recovered_attempts"] > 0,
                    counts["recovered_attempts"],
                    "retry or lease-takeover evidence exists for this project",
                ),
                _check(
                    "source_isolation",
                    counts["observation_count"] > 0
                    and counts["source_leakage_assets"] == 0,
                    counts["observation_count"] - counts["source_leakage_assets"],
                    "Source/Observation assets are evidence-only and carry no raw prose fields",
                ),
                _check(
                    "cross_project_isolation",
                    counts["scope_guard_count"] >= 7,
                    counts["scope_guard_count"],
                    "PostgreSQL constraint triggers enforce project/workspace lineage",
                ),
                _check(
                    "token_cost_traceability",
                    counts["observation_count"] > 0
                    and counts["untraced_or_fixture_observations"] == 0,
                    counts["observation_count"]
                    - counts["untraced_or_fixture_observations"],
                    "all Observations have non-fixture usage and cost evidence",
                ),
            ]
        ready = all(check["passed"] for check in checks)
        return {
            "schema_version": "data-import-admission.v1",
            "project_id": project_id,
            "data_import_ready": ready,
            "capability_status": "CAPABILITY_IMPLEMENTED",
            "project_qualification": (
                "PROJECT_QUALIFIED" if ready else "PROJECT_NOT_QUALIFIED"
            ),
            "decision": "ADMITTED" if ready else "BLOCKED",
            "checks": checks,
            "evidence_counts": counts,
            "evidence_ceiling": (
                "PROJECT_DATA_IMPORT_QUALIFIED"
                if ready
                else "CAPABILITY_PRESENT_PROJECT_PROOF_INCOMPLETE"
            ),
        }


def _check(name: str, passed: bool, evidence_count: int, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "evidence_count": int(evidence_count),
        "detail": detail,
    }


def _admission_counts(cursor: Any, project_id: str) -> dict[str, int]:
    queries = {
        "repository_snapshot_count": """
            SELECT COUNT(*) FROM authority_source_repository_snapshot
            WHERE project_id=%s
        """,
        "invalid_repository_snapshots": """
            SELECT COUNT(*) FROM authority_source_repository_snapshot
            WHERE project_id=%s AND (
                resolved_commit_sha !~ '^[0-9a-f]{40}$'
                OR manifest_hash !~ '^sha256:[0-9a-f]{64}$'
                OR import_policy_hash !~ '^sha256:[0-9a-f]{64}$'
            )
        """,
        "incremental_snapshot_count": """
            SELECT COUNT(DISTINCT job.repository_snapshot_asset_version_id)
            FROM authority_source_import_job AS job
            WHERE job.project_id=%s
              AND job.previous_snapshot_asset_version_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM authority_source_repository_file AS file
                  WHERE file.repository_snapshot_asset_version_id=
                        job.repository_snapshot_asset_version_id
                    AND file.diff_state IN (
                        'UNCHANGED', 'RENAMED_SAME_CONTENT', 'MODIFIED',
                        'ADDED', 'REMOVED'
                    )
              )
        """,
        "source_count": "SELECT COUNT(*) FROM authority_source_document WHERE project_id=%s",
        "duplicate_sources": """
            SELECT COUNT(*) FROM (
                SELECT source_content_hash FROM authority_source_document
                WHERE project_id=%s GROUP BY source_content_hash HAVING COUNT(*)>1
            ) AS duplicate
        """,
        "invalid_source_receipts": """
            SELECT COUNT(*) FROM authority_source_document AS source
            JOIN authority_blob AS blob ON blob.blob_id=source.blob_id
            WHERE source.project_id=%s AND (
                blob.status<>'AVAILABLE'
                OR blob.actual_hash<>source.source_content_hash
                OR blob.actual_hash<>blob.expected_hash
                OR blob.actual_size<>blob.expected_size
            )
        """,
        "governance_blocked_sources": """
            SELECT COUNT(*) FROM authority_source_document
            WHERE project_id=%s AND governance_status<>'ELIGIBLE'
        """,
        "transform_count": "SELECT COUNT(*) FROM authority_source_transform WHERE project_id=%s",
        "invalid_transforms": """
            SELECT COUNT(*) FROM authority_source_transform
            WHERE project_id=%s AND (
                normalization_version='' OR chunking_version=''
                OR chunking_policy_hash='' OR manifest_hash='' OR chunk_count<1
            )
        """,
        "evidence_span_count": "SELECT COUNT(*) FROM authority_source_evidence_span WHERE project_id=%s",
        "observation_count": "SELECT COUNT(*) FROM authority_source_deconstruction_observation WHERE project_id=%s",
        "invalid_observations": """
            SELECT COUNT(*) FROM authority_source_deconstruction_observation
            WHERE project_id=%s AND (
                analyzer_contract_hash='' OR prompt_version='' OR skill_version=''
                OR capability_version='' OR observation_schema_version=''
            )
        """,
        "observation_candidate_edges": """
            SELECT COUNT(*) FROM authority_content_dependency AS dependency
            JOIN authority_source_deconstruction_observation AS observation
              ON observation.asset_version_id=dependency.upstream_asset_version_id
            JOIN authority_mkaos_knowledge_candidate AS candidate
              ON candidate.asset_version_id=dependency.downstream_asset_version_id
            WHERE dependency.project_id=%s AND dependency.relationship='ABSTRACTS'
        """,
        "production_knowledge_cards": """
            SELECT COUNT(DISTINCT card.asset_version_id)
            FROM authority_content_dependency AS abstraction
            JOIN authority_source_deconstruction_observation AS observation
              ON observation.asset_version_id=abstraction.upstream_asset_version_id
            JOIN authority_mkaos_knowledge_candidate AS candidate
              ON candidate.asset_version_id=abstraction.downstream_asset_version_id
            JOIN authority_asset_version AS candidate_version
              ON candidate_version.asset_version_id=candidate.asset_version_id
            JOIN authority_content_dependency AS activation
              ON activation.project_id=abstraction.project_id
             AND activation.upstream_asset_version_id=candidate.asset_version_id
             AND activation.relationship='ACTIVATES'
            JOIN authority_mkaos_knowledge_card AS card
              ON card.asset_version_id=activation.downstream_asset_version_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=card.asset_version_id
            WHERE abstraction.project_id=%s
              AND abstraction.relationship='ABSTRACTS'
              AND card.status='ACTIVE'
              AND candidate_version.content->'execution_evidence'->'binding'->>'validation_status'='VERIFIED'
              AND COALESCE((version.content->'source_policy'->>'fixture_protocol_only')::boolean, TRUE)=FALSE
        """,
        "reuse_plan_items": """
            SELECT COUNT(*) FROM authority_source_reprocessing_plan_item
            WHERE project_id=%s AND action='REUSE'
        """,
        "mixed_selective_plans": """
            SELECT COUNT(*) FROM (
                SELECT reprocessing_plan_asset_version_id
                FROM authority_source_reprocessing_plan_item WHERE project_id=%s
                GROUP BY reprocessing_plan_asset_version_id
                HAVING BOOL_OR(action='REUSE') AND BOOL_OR(action='RECOMPUTE')
            ) AS plan
        """,
        "applied_reprocessing_items": """
            SELECT COUNT(*) FROM authority_source_reprocessing_plan_item
            WHERE project_id=%s AND status IN ('APPLIED', 'REUSED')
        """,
        "invalidation_count": "SELECT COUNT(*) FROM authority_content_invalidation WHERE project_id=%s",
        "recovered_attempts": """
            SELECT COUNT(*) FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id=attempt.operation_id
            WHERE operation.project_id=%s
              AND operation.definition_name IN (
                  'source.document.register', 'source.transform.commit',
                  'source.deconstruction.observation.commit',
                  'source.deconstruction.reprocessing.plan',
                  'source.import.repository.discover',
                  'source.import.file.process',
                  'source.import.deconstruction.execute',
                  'source.import.mkaos.extract',
                  'source.import.reprocessing.apply'
              ) AND (
                attempt.attempt_number>1
                OR EXISTS (
                    SELECT 1 FROM authority_lease_acquisition AS lease
                    WHERE lease.attempt_id=attempt.attempt_id
                    GROUP BY lease.attempt_id HAVING COUNT(*)>1
                )
            )
        """,
        "source_leakage_assets": """
            SELECT COUNT(*) FROM authority_source_deconstruction_observation AS observation
            JOIN authority_asset_version AS version
              ON version.asset_version_id=observation.asset_version_id
            WHERE observation.project_id=%s AND (
                version.eligibility<>'INELIGIBLE'
                OR version.content::text ~* '\"(raw_text|clean_text|source_text|excerpt|quotes?)\"[[:space:]]*:'
                OR COALESCE((version.content->'source_policy'->>'generation_context_allowed')::boolean, TRUE)
            )
        """,
        "scope_guard_count": """
            SELECT COUNT(*) FROM pg_trigger AS trigger
            JOIN pg_proc AS function ON function.oid=trigger.tgfoid
            WHERE function.proname IN (
                    'authority_validate_source_intelligence_scope',
                    'authority_validate_source_import_scope'
                  )
              AND trigger.tgenabled<>'D' AND NOT trigger.tgisinternal
        """,
        "untraced_or_fixture_observations": """
            SELECT COUNT(*)
            FROM authority_source_deconstruction_observation AS observation
            JOIN authority_asset_version AS execution
              ON execution.asset_version_id=observation.execution_asset_version_id
            WHERE observation.project_id=%s AND (
                observation.evidence_class NOT IN (
                    'DETERMINISTIC', 'PROVIDER_QUALIFIED'
                )
                OR COALESCE((execution.content->>'fixture_protocol_only')::boolean, FALSE)
                OR NOT (execution.content ? 'usage')
                OR NOT (execution.content ? 'cost')
                OR NOT (execution.content ? 'source_deconstruction_binding')
                OR (
                    observation.evidence_class='DETERMINISTIC' AND (
                        COALESCE((execution.content->>'deterministic_execution')::boolean, FALSE)=FALSE
                        OR COALESCE((execution.content->>'model_call_performed')::boolean, TRUE)
                        OR COALESCE((execution.content->'usage'->>'total_tokens')::bigint, -1)<>0
                        OR COALESCE((execution.content->'cost'->>'amount_usd')::numeric, -1)<>0
                    )
                )
            )
        """,
    }
    counts: dict[str, int] = {}
    for key, sql in queries.items():
        if key == "scope_guard_count":
            cursor.execute(sql)
        else:
            cursor.execute(sql, [project_id])
        counts[key] = int(cursor.fetchone()[0])
    return counts


__all__ = ["SourceAuthorityQuery"]
