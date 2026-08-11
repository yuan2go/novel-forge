"""PostgreSQL projections for Source Profile and AnalysisPlan AssetVersions."""

from __future__ import annotations

from typing import Any, Iterable

from psycopg.types.json import Jsonb


class SourceProfileRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def transform_scope(
        self, *, project_id: str, workspace_id: str, source_transform_id: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT transform.source_transform_id, transform.asset_version_id,
                   transform.source_document_id, transform.workspace_id,
                   transform.status, version.content_hash, version.lifecycle
            FROM authority_source_transform AS transform
            JOIN authority_asset_version AS version
              ON version.asset_version_id=transform.asset_version_id
            WHERE transform.project_id=%s AND transform.workspace_id=%s
              AND transform.source_transform_id=%s
            FOR SHARE OF transform, version
            """,
            [project_id, workspace_id, source_transform_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(
            zip(
                (
                    "source_transform_id",
                    "asset_version_id",
                    "source_document_id",
                    "workspace_id",
                    "status",
                    "content_hash",
                    "lifecycle",
                ),
                row,
                strict=True,
            )
        )

    def chunks(
        self, *, project_id: str, source_transform_id: str
    ) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT chunk.asset_version_id, chunk.source_chunk_id,
                   chunk.source_document_id, chunk.chunk_index,
                   chunk.byte_size, chunk.content_hash,
                   version.content_hash, version.lifecycle
            FROM authority_source_chunk AS chunk
            JOIN authority_asset_version AS version
              ON version.asset_version_id=chunk.asset_version_id
            WHERE chunk.project_id=%s AND chunk.source_transform_id=%s
            ORDER BY chunk.chunk_index
            FOR SHARE OF chunk, version
            """,
            [project_id, source_transform_id],
        )
        keys = (
            "asset_version_id",
            "source_chunk_id",
            "source_document_id",
            "chunk_index",
            "byte_size",
            "content_hash",
            "asset_content_hash",
            "lifecycle",
        )
        return [dict(zip(keys, row, strict=True)) for row in self.cursor.fetchall()]

    def asset_version(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT version.asset_version_id, version.asset_id, asset.asset_type,
                   version.content_hash, version.content, version.lifecycle,
                   version.eligibility, version.governance
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE asset.project_id=%s AND version.asset_version_id=%s
            """,
            [project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(
            zip(
                (
                    "asset_version_id",
                    "asset_id",
                    "asset_type",
                    "content_hash",
                    "content",
                    "lifecycle",
                    "eligibility",
                    "governance",
                ),
                row,
                strict=True,
            )
        )

    def current_profile(
        self, *, project_id: str, logical_document_scope_hash: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT profile.source_content_profile_id, profile.asset_version_id,
                   profile.classifier_contract_hash,
                   profile.intelligence_policy_hash,
                   profile.override_contract_hash,
                   profile.classification_input_hash,
                   profile.classification_output_hash, profile.status,
                   profile.resolved_content_type,
                   profile.created_by_operation_id, operation.status,
                   version.content_hash, version.content
            FROM authority_source_content_profile AS profile
            JOIN authority_asset_version AS version
              ON version.asset_version_id=profile.asset_version_id
             AND version.lifecycle='ACTIVE'
            JOIN authority_operation AS operation
              ON operation.operation_id=profile.created_by_operation_id
            WHERE profile.project_id=%s
              AND profile.logical_document_scope_hash=%s
            """,
            [project_id, logical_document_scope_hash],
        )
        return _profile_row(self.cursor.fetchone())

    def exact_profile(
        self,
        *,
        project_id: str,
        logical_document_scope_hash: str,
        classifier_contract_hash: str,
        intelligence_policy_hash: str,
        override_contract_hash: str,
        classification_input_hash: str,
        classification_output_hash: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT profile.source_content_profile_id, profile.asset_version_id,
                   profile.classifier_contract_hash,
                   profile.intelligence_policy_hash,
                   profile.override_contract_hash,
                   profile.classification_input_hash,
                   profile.classification_output_hash, profile.status,
                   profile.resolved_content_type,
                   profile.created_by_operation_id, operation.status,
                   version.content_hash, version.content
            FROM authority_source_content_profile AS profile
            JOIN authority_asset_version AS version
              ON version.asset_version_id=profile.asset_version_id
            JOIN authority_operation AS operation
              ON operation.operation_id=profile.created_by_operation_id
            WHERE profile.project_id=%s
              AND profile.logical_document_scope_hash=%s
              AND profile.classifier_contract_hash=%s
              AND profile.intelligence_policy_hash=%s
              AND profile.override_contract_hash=%s
              AND profile.classification_input_hash=%s
              AND profile.classification_output_hash=%s
              AND version.lifecycle='ACTIVE'
            """,
            [
                project_id,
                logical_document_scope_hash,
                classifier_contract_hash,
                intelligence_policy_hash,
                override_contract_hash,
                classification_input_hash,
                classification_output_hash,
            ],
        )
        return _profile_row(self.cursor.fetchone())

    def profile(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT profile.source_content_profile_id, profile.asset_version_id,
                   profile.classifier_contract_hash,
                   profile.intelligence_policy_hash,
                   profile.override_contract_hash,
                   profile.classification_input_hash,
                   profile.classification_output_hash, profile.status,
                   profile.resolved_content_type,
                   profile.created_by_operation_id, operation.status,
                   version.content_hash, version.content
            FROM authority_source_content_profile AS profile
            JOIN authority_asset_version AS version
              ON version.asset_version_id=profile.asset_version_id
            JOIN authority_operation AS operation
              ON operation.operation_id=profile.created_by_operation_id
            WHERE profile.project_id=%s AND profile.asset_version_id=%s
            """,
            [project_id, asset_version_id],
        )
        return _profile_row(self.cursor.fetchone())

    def register_profile(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_content_profile (
              source_content_profile_id, project_id, workspace_id,
              asset_version_id, source_document_id, source_transform_id,
              logical_document_scope, logical_document_scope_hash,
              boundary_policy_version, classifier_id, classifier_version,
              classifier_prompt_version, classifier_schema_version,
              classifier_contract_hash, classification_input_hash,
              classification_output_hash, intelligence_policy_hash,
              override_contract_hash, execution_asset_version_id, evidence,
              predicted_content_type, resolved_content_type, confidence,
              margin, resolution_mode, resolution_reasons,
              override_decision_ref, status, manual_review_required,
              evidence_class, created_by_operation_id
            ) VALUES (
              %(source_content_profile_id)s, %(project_id)s, %(workspace_id)s,
              %(asset_version_id)s, %(source_document_id)s,
              %(source_transform_id)s, %(logical_document_scope)s,
              %(logical_document_scope_hash)s, %(boundary_policy_version)s,
              %(classifier_id)s, %(classifier_version)s,
              %(classifier_prompt_version)s, %(classifier_schema_version)s,
              %(classifier_contract_hash)s, %(classification_input_hash)s,
              %(classification_output_hash)s, %(intelligence_policy_hash)s,
              %(override_contract_hash)s, %(execution_asset_version_id)s,
              %(evidence)s, %(predicted_content_type)s,
              %(resolved_content_type)s, %(confidence)s, %(margin)s,
              %(resolution_mode)s, %(resolution_reasons)s,
              %(override_decision_ref)s, %(status)s,
              %(manual_review_required)s, %(evidence_class)s,
              %(created_by_operation_id)s
            )
            """,
            {
                **row,
                "logical_document_scope": Jsonb(row["logical_document_scope"]),
                "evidence": Jsonb(row["evidence"]),
                "resolution_reasons": Jsonb(row["resolution_reasons"]),
            },
        )

    def register_profile_input(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_content_profile_input (
              profile_asset_version_id, project_id, input_asset_version_id,
              role, ordinal, sample_manifest, created_by_operation_id
            ) VALUES (
              %(profile_asset_version_id)s, %(project_id)s,
              %(input_asset_version_id)s, %(role)s, %(ordinal)s,
              %(sample_manifest)s, %(created_by_operation_id)s
            )
            """,
            {**row, "sample_manifest": Jsonb(row.get("sample_manifest") or {})},
        )

    def current_plan(
        self, *, project_id: str, logical_document_scope_hash: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT plan.source_analysis_plan_id, plan.asset_version_id,
                   plan.profile_asset_version_id, plan.strategy_contract_hash,
                   plan.methodology_contract_hash, plan.status,
                   plan.created_by_operation_id, operation.status,
                   version.content_hash, version.content
            FROM authority_source_analysis_plan AS plan
            JOIN authority_asset_version AS version
              ON version.asset_version_id=plan.asset_version_id
             AND version.lifecycle='ACTIVE'
            JOIN authority_operation AS operation
              ON operation.operation_id=plan.created_by_operation_id
            WHERE plan.project_id=%s AND plan.logical_document_scope_hash=%s
            """,
            [project_id, logical_document_scope_hash],
        )
        return _plan_row(self.cursor.fetchone())

    def exact_plan(
        self,
        *,
        project_id: str,
        profile_asset_version_id: str,
        strategy_contract_hash: str,
        methodology_contract_hash: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT plan.source_analysis_plan_id, plan.asset_version_id,
                   plan.profile_asset_version_id, plan.strategy_contract_hash,
                   plan.methodology_contract_hash, plan.status,
                   plan.created_by_operation_id, operation.status,
                   version.content_hash, version.content
            FROM authority_source_analysis_plan AS plan
            JOIN authority_asset_version AS version
              ON version.asset_version_id=plan.asset_version_id
            JOIN authority_operation AS operation
              ON operation.operation_id=plan.created_by_operation_id
            WHERE plan.project_id=%s AND plan.profile_asset_version_id=%s
              AND plan.strategy_contract_hash=%s
              AND plan.methodology_contract_hash=%s
              AND version.lifecycle='ACTIVE'
            """,
            [
                project_id,
                profile_asset_version_id,
                strategy_contract_hash,
                methodology_contract_hash,
            ],
        )
        return _plan_row(self.cursor.fetchone())

    def plan(self, *, project_id: str, asset_version_id: str) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT plan.source_analysis_plan_id, plan.asset_version_id,
                   plan.profile_asset_version_id, plan.strategy_contract_hash,
                   plan.methodology_contract_hash, plan.status,
                   plan.created_by_operation_id, operation.status,
                   version.content_hash, version.content
            FROM authority_source_analysis_plan AS plan
            JOIN authority_asset_version AS version
              ON version.asset_version_id=plan.asset_version_id
            JOIN authority_operation AS operation
              ON operation.operation_id=plan.created_by_operation_id
            WHERE plan.project_id=%s AND plan.asset_version_id=%s
            """,
            [project_id, asset_version_id],
        )
        return _plan_row(self.cursor.fetchone())

    def register_plan(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_analysis_plan (
              source_analysis_plan_id, project_id, workspace_id,
              asset_version_id, profile_asset_version_id,
              logical_document_scope_hash, resolved_content_type,
              routing_policy_version, profile_id, profile_version,
              strategy_contract_hash, methodology_contract_hash,
              methodologies, mkaos_capability, abstraction_policy_version,
              status, created_by_operation_id
            ) VALUES (
              %(source_analysis_plan_id)s, %(project_id)s, %(workspace_id)s,
              %(asset_version_id)s, %(profile_asset_version_id)s,
              %(logical_document_scope_hash)s, %(resolved_content_type)s,
              %(routing_policy_version)s, %(profile_id)s,
              %(profile_version)s, %(strategy_contract_hash)s,
              %(methodology_contract_hash)s, %(methodologies)s,
              %(mkaos_capability)s, %(abstraction_policy_version)s,
              %(status)s, %(created_by_operation_id)s
            )
            """,
            {**row, "methodologies": Jsonb(row["methodologies"])},
        )

    def supersede_plan(self, *, project_id: str, asset_version_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_source_analysis_plan
            SET status='SUPERSEDED'
            WHERE project_id=%s AND asset_version_id=%s AND status='ACTIVE'
            """,
            [project_id, asset_version_id],
        )
        if self.cursor.rowcount != 1:
            raise RuntimeError(
                "active Source AnalysisPlan projection was not superseded"
            )

    def descendants(
        self, *, project_id: str, upstream_asset_version_id: str
    ) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            WITH RECURSIVE tree(asset_version_id, depth, path) AS (
              SELECT dependency.downstream_asset_version_id, 1,
                     ARRAY[dependency.upstream_asset_version_id,
                           dependency.downstream_asset_version_id]
              FROM authority_content_dependency AS dependency
              WHERE dependency.project_id=%s
                AND dependency.upstream_asset_version_id=%s
              UNION ALL
              SELECT dependency.downstream_asset_version_id, tree.depth + 1,
                     tree.path || dependency.downstream_asset_version_id
              FROM tree
              JOIN authority_content_dependency AS dependency
                ON dependency.project_id=%s
               AND dependency.upstream_asset_version_id=tree.asset_version_id
              WHERE NOT dependency.downstream_asset_version_id=ANY(tree.path)
                AND tree.depth < 32
            )
            SELECT DISTINCT ON (tree.asset_version_id) tree.asset_version_id,
                   tree.depth, asset.asset_type, version.lifecycle
            FROM tree
            JOIN authority_asset_version AS version
              ON version.asset_version_id=tree.asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            ORDER BY tree.asset_version_id, tree.depth
            """,
            [project_id, upstream_asset_version_id, project_id],
        )
        keys = ("asset_version_id", "depth", "asset_type", "lifecycle")
        return [dict(zip(keys, row, strict=True)) for row in self.cursor.fetchall()]

    def operation_output(
        self, *, project_id: str, operation_id: str, output_key: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT output.asset_id, output.asset_version_id, output.content_hash
            FROM authority_operation_output_asset AS output
            JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
            WHERE operation.project_id=%s AND output.operation_id=%s
              AND output.output_key=%s
            ORDER BY output.created_at DESC LIMIT 1
            """,
            [project_id, operation_id, output_key],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {
            "asset_id": row[0],
            "asset_version_id": row[1],
            "content_hash": row[2],
        }

    def record_dependency(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_content_dependency (
              dependency_id, project_id, upstream_asset_version_id,
              downstream_asset_version_id, relationship, selector_key,
              created_by_operation_id
            ) VALUES (
              %(dependency_id)s, %(project_id)s,
              %(upstream_asset_version_id)s, %(downstream_asset_version_id)s,
              %(relationship)s, %(selector_key)s,
              %(created_by_operation_id)s
            ) ON CONFLICT (
              upstream_asset_version_id, downstream_asset_version_id,
              relationship, selector_key
            ) DO NOTHING
            """,
            row,
        )

    def record_invalidations(
        self,
        *,
        project_id: str,
        target_asset_version_ids: Iterable[str],
        cause_type: str,
        cause_ref: str,
        created_by_operation_id: str,
    ) -> None:
        from uuid import uuid4

        for target in dict.fromkeys(target_asset_version_ids):
            self.cursor.execute(
                """
                INSERT INTO authority_content_invalidation (
                  invalidation_id, project_id, target_asset_version_id,
                  cause_type, cause_ref, dimension, status,
                  created_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, '', 'OPEN', %s)
                ON CONFLICT (target_asset_version_id, cause_type, cause_ref)
                DO NOTHING
                """,
                [
                    str(uuid4()),
                    project_id,
                    target,
                    cause_type,
                    cause_ref,
                    created_by_operation_id,
                ],
            )


def _profile_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = (
        "source_content_profile_id",
        "asset_version_id",
        "classifier_contract_hash",
        "intelligence_policy_hash",
        "override_contract_hash",
        "classification_input_hash",
        "classification_output_hash",
        "status",
        "resolved_content_type",
        "operation_id",
        "operation_status",
        "content_hash",
        "content",
    )
    return dict(zip(keys, row, strict=True))


def _plan_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = (
        "source_analysis_plan_id",
        "asset_version_id",
        "profile_asset_version_id",
        "strategy_contract_hash",
        "methodology_contract_hash",
        "status",
        "operation_id",
        "operation_status",
        "content_hash",
        "content",
    )
    return dict(zip(keys, row, strict=True))


__all__ = ["SourceProfileRepository"]
