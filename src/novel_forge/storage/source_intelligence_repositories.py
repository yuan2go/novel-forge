"""PostgreSQL projections for Source Deconstruction and selective replay."""
from __future__ import annotations

from typing import Any, Iterable

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class SourceIntelligenceRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def asset_versions(
        self, *, project_id: str, asset_version_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        identities = tuple(dict.fromkeys(str(item) for item in asset_version_ids if str(item)))
        if not identities:
            return {}
        self.cursor.execute(
            """
            SELECT version.asset_version_id, version.asset_id, asset.asset_type,
                   version.content_hash, version.content, version.lifecycle,
                   version.eligibility, version.governance
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
            ORDER BY version.asset_version_id
            """,
            [project_id, list(identities)],
        )
        keys = (
            "asset_version_id",
            "asset_id",
            "asset_type",
            "content_hash",
            "content",
            "lifecycle",
            "eligibility",
            "governance",
        )
        return {
            str(row[0]): dict(zip(keys, row, strict=True))
            for row in self.cursor.fetchall()
        }

    def source_chunks(
        self, *, project_id: str, asset_version_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        identities = tuple(dict.fromkeys(str(item) for item in asset_version_ids if str(item)))
        if not identities:
            return {}
        self.cursor.execute(
            """
            SELECT chunk.asset_version_id, chunk.source_chunk_id,
                   chunk.source_transform_id, chunk.source_document_id,
                   chunk.chunk_index, chunk.byte_size, chunk.content_hash,
                   version.content_hash, version.lifecycle,
                   source.governance_status, transform.status
            FROM authority_source_chunk AS chunk
            JOIN authority_asset_version AS version
              ON version.asset_version_id=chunk.asset_version_id
            JOIN authority_source_document AS source
              ON source.source_document_id=chunk.source_document_id
             AND source.project_id=chunk.project_id
            JOIN authority_source_transform AS transform
              ON transform.source_transform_id=chunk.source_transform_id
             AND transform.project_id=chunk.project_id
            WHERE chunk.project_id=%s AND chunk.asset_version_id=ANY(%s)
            ORDER BY chunk.asset_version_id
            FOR SHARE OF chunk, version, source, transform
            """,
            [project_id, list(identities)],
        )
        keys = (
            "asset_version_id",
            "source_chunk_id",
            "source_transform_id",
            "source_document_id",
            "chunk_index",
            "byte_size",
            "content_hash",
            "asset_content_hash",
            "lifecycle",
            "source_governance_status",
            "transform_status",
        )
        rows = {
            str(row[0]): dict(zip(keys, row, strict=True))
            for row in self.cursor.fetchall()
        }
        for row in rows.values():
            if (
                row["lifecycle"],
                row["source_governance_status"],
                row["transform_status"],
            ) != ("ACTIVE", "ELIGIBLE", "ACTIVE"):
                raise KernelError(
                    "DECONSTRUCTION_SOURCE_CHUNK_INELIGIBLE",
                    "Observation requires an active governed SourceChunk version",
                )
        return rows

    def observations(
        self, *, project_id: str, asset_version_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        identities = tuple(dict.fromkeys(str(item) for item in asset_version_ids if str(item)))
        if not identities:
            return {}
        self.cursor.execute(
            """
            SELECT observation.asset_version_id, observation.observation_id,
                   observation.scope, observation.scope_hash,
                   observation.dimension, observation.scale,
                   observation.analyzer_id, observation.analyzer_contract_hash,
                   observation.observation_hash, observation.evidence_class,
                   version.content_hash, version.lifecycle,
                   version.eligibility, version.governance
            FROM authority_source_deconstruction_observation AS observation
            JOIN authority_asset_version AS version
              ON version.asset_version_id=observation.asset_version_id
            WHERE observation.project_id=%s
              AND observation.asset_version_id=ANY(%s)
            ORDER BY observation.asset_version_id
            FOR SHARE OF observation, version
            """,
            [project_id, list(identities)],
        )
        keys = (
            "asset_version_id",
            "observation_id",
            "scope",
            "scope_hash",
            "dimension",
            "scale",
            "analyzer_id",
            "analyzer_contract_hash",
            "observation_hash",
            "evidence_class",
            "content_hash",
            "lifecycle",
            "eligibility",
            "governance",
        )
        return {
            str(row[0]): dict(zip(keys, row, strict=True))
            for row in self.cursor.fetchall()
        }

    def observation_source_chunk_inputs(
        self, *, project_id: str, asset_version_ids: Iterable[str]
    ) -> dict[str, set[str]]:
        identities = tuple(
            dict.fromkeys(str(item) for item in asset_version_ids if str(item))
        )
        result = {identity: set() for identity in identities}
        if not identities:
            return result
        self.cursor.execute(
            """
            WITH RECURSIVE observation_tree(
                root_asset_version_id, observation_asset_version_id, path
            ) AS (
                SELECT identity, identity, ARRAY[identity]
                FROM unnest(%s::TEXT[]) AS identity
                UNION ALL
                SELECT tree.root_asset_version_id,
                       input.input_asset_version_id,
                       tree.path || input.input_asset_version_id
                FROM observation_tree AS tree
                JOIN authority_source_deconstruction_observation_input AS input
                  ON input.project_id=%s
                 AND input.observation_asset_version_id=
                     tree.observation_asset_version_id
                 AND input.role='LOWER_SCALE_OBSERVATION'
                WHERE NOT input.input_asset_version_id=ANY(tree.path)
                  AND cardinality(tree.path)<32
            )
            SELECT tree.root_asset_version_id, input.input_asset_version_id
            FROM observation_tree AS tree
            JOIN authority_source_deconstruction_observation_input AS input
              ON input.project_id=%s
             AND input.observation_asset_version_id=
                 tree.observation_asset_version_id
             AND input.role='SOURCE_CHUNK_EVIDENCE'
            ORDER BY tree.root_asset_version_id, input.input_asset_version_id
            """,
            [list(identities), project_id, project_id],
        )
        for root_asset_version_id, source_chunk_asset_version_id in self.cursor.fetchall():
            result[str(root_asset_version_id)].add(
                str(source_chunk_asset_version_id)
            )
        return result

    def current_observation(
        self,
        *,
        project_id: str,
        scope_hash: str,
        analyzer_id: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT observation.observation_id, observation.asset_version_id,
                   observation.analyzer_contract_hash,
                   observation.observation_hash, observation.dimension,
                   observation.scale, observation.created_by_operation_id,
                   operation.status, version.content_hash, version.content
            FROM authority_source_deconstruction_observation AS observation
            JOIN authority_asset_version AS version
              ON version.asset_version_id=observation.asset_version_id
             AND version.lifecycle='ACTIVE'
            JOIN authority_operation AS operation
              ON operation.operation_id=observation.created_by_operation_id
            WHERE observation.project_id=%s AND observation.scope_hash=%s
              AND observation.analyzer_id=%s
            """,
            [project_id, scope_hash, analyzer_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        keys = (
            "observation_id",
            "asset_version_id",
            "analyzer_contract_hash",
            "observation_hash",
            "dimension",
            "scale",
            "operation_id",
            "operation_status",
            "content_hash",
            "content",
        )
        return dict(zip(keys, row, strict=True))

    def existing_observation(
        self,
        *,
        project_id: str,
        scope_hash: str,
        analyzer_contract_hash: str,
        observation_hash: str,
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT observation.observation_id, observation.asset_version_id,
                   observation.created_by_operation_id, operation.status,
                   version.content_hash
            FROM authority_source_deconstruction_observation AS observation
            JOIN authority_operation AS operation
              ON operation.operation_id=observation.created_by_operation_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=observation.asset_version_id
            WHERE observation.project_id=%s AND observation.scope_hash=%s
              AND observation.analyzer_contract_hash=%s
              AND observation.observation_hash=%s
            """,
            [project_id, scope_hash, analyzer_contract_hash, observation_hash],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(
            zip(
                (
                    "observation_id",
                    "asset_version_id",
                    "operation_id",
                    "operation_status",
                    "content_hash",
                ),
                row,
                strict=True,
            )
        )

    def operation_output(
        self, *, project_id: str, operation_id: str, output_key: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT output.asset_id, output.asset_version_id, output.content_hash
            FROM authority_operation_output_asset AS output
            JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
            WHERE output.operation_id=%s AND operation.project_id=%s
              AND output.output_key=%s
            ORDER BY output.created_at DESC
            LIMIT 1
            """,
            [operation_id, project_id, output_key],
        )
        row = self.cursor.fetchone()
        return (
            None
            if row is None
            else {
                "asset_id": row[0],
                "asset_version_id": row[1],
                "content_hash": row[2],
            }
        )

    def register_evidence_span(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_evidence_span (
                evidence_span_id, project_id, source_document_id,
                source_transform_id, source_chunk_id,
                source_chunk_asset_version_id, chunk_byte_start,
                chunk_byte_end, evidence_hash, created_by_operation_id
            ) VALUES (
                %(evidence_span_id)s, %(project_id)s, %(source_document_id)s,
                %(source_transform_id)s, %(source_chunk_id)s,
                %(source_chunk_asset_version_id)s, %(chunk_byte_start)s,
                %(chunk_byte_end)s, %(evidence_hash)s,
                %(created_by_operation_id)s
            )
            ON CONFLICT (evidence_span_id) DO NOTHING
            """,
            row,
        )
        self.cursor.execute(
            """
            SELECT project_id, source_chunk_asset_version_id,
                   chunk_byte_start, chunk_byte_end, evidence_hash
            FROM authority_source_evidence_span WHERE evidence_span_id=%s
            """,
            [row["evidence_span_id"]],
        )
        stored = self.cursor.fetchone()
        expected = (
            row["project_id"],
            row["source_chunk_asset_version_id"],
            row["chunk_byte_start"],
            row["chunk_byte_end"],
            row["evidence_hash"],
        )
        if stored != expected:
            raise KernelError(
                "DECONSTRUCTION_EVIDENCE_REPLAY_CONFLICT",
                "stable EvidenceSpan identity has different content",
            )

    def register_observation(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_deconstruction_observation (
                observation_id, project_id, workspace_id, asset_version_id,
                execution_asset_version_id, scope, scope_hash, dimension,
                scale, analyzer_id, analyzer_version,
                analyzer_contract_hash, prompt_id, prompt_version, skill_id,
                skill_version, capability_id, capability_version,
                provider_policy_version, aggregation_policy_version,
                observation_schema_version, observation_hash, confidence,
                evidence_class, created_by_operation_id
            ) VALUES (
                %(observation_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(execution_asset_version_id)s,
                %(scope)s, %(scope_hash)s, %(dimension)s, %(scale)s,
                %(analyzer_id)s, %(analyzer_version)s,
                %(analyzer_contract_hash)s, %(prompt_id)s,
                %(prompt_version)s, %(skill_id)s, %(skill_version)s,
                %(capability_id)s, %(capability_version)s,
                %(provider_policy_version)s, %(aggregation_policy_version)s,
                %(observation_schema_version)s, %(observation_hash)s,
                %(confidence)s, %(evidence_class)s,
                %(created_by_operation_id)s
            )
            """,
            {**row, "scope": Jsonb(row["scope"])},
        )

    def register_observation_input(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_deconstruction_observation_input (
                observation_asset_version_id, project_id,
                input_asset_version_id, evidence_span_id, role, ordinal,
                created_by_operation_id
            ) VALUES (
                %(observation_asset_version_id)s, %(project_id)s,
                %(input_asset_version_id)s, %(evidence_span_id)s,
                %(role)s, %(ordinal)s, %(created_by_operation_id)s
            )
            """,
            row,
        )

    def record_dependency(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_content_dependency (
                dependency_id, project_id, upstream_asset_version_id,
                downstream_asset_version_id, relationship, selector_key,
                created_by_operation_id
            ) VALUES (
                %(dependency_id)s, %(project_id)s,
                %(upstream_asset_version_id)s,
                %(downstream_asset_version_id)s, %(relationship)s,
                %(selector_key)s, %(created_by_operation_id)s
            ) ON CONFLICT (
                upstream_asset_version_id, downstream_asset_version_id,
                relationship, selector_key
            ) DO NOTHING
            """,
            row,
        )

    def descendants(
        self, *, project_id: str, upstream_asset_version_id: str
    ) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            WITH RECURSIVE descendants AS (
                SELECT dependency.downstream_asset_version_id,
                       dependency.relationship, 1 AS depth,
                       ARRAY[dependency.upstream_asset_version_id,
                             dependency.downstream_asset_version_id] AS path
                FROM authority_content_dependency AS dependency
                WHERE dependency.project_id=%s
                  AND dependency.upstream_asset_version_id=%s
                UNION ALL
                SELECT dependency.downstream_asset_version_id,
                       dependency.relationship, descendants.depth + 1,
                       descendants.path || dependency.downstream_asset_version_id
                FROM descendants
                JOIN authority_content_dependency AS dependency
                  ON dependency.project_id=%s
                 AND dependency.upstream_asset_version_id=
                     descendants.downstream_asset_version_id
                WHERE NOT dependency.downstream_asset_version_id=ANY(descendants.path)
                  AND descendants.depth < 32
            )
            SELECT DISTINCT ON (descendants.downstream_asset_version_id)
                   descendants.downstream_asset_version_id,
                   descendants.relationship, descendants.depth,
                   asset.asset_type, version.lifecycle
            FROM descendants
            JOIN authority_asset_version AS version
              ON version.asset_version_id=descendants.downstream_asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            ORDER BY descendants.downstream_asset_version_id,
                     descendants.depth ASC
            """,
            [project_id, upstream_asset_version_id, project_id],
        )
        keys = (
            "asset_version_id",
            "relationship",
            "depth",
            "asset_type",
            "lifecycle",
        )
        return [dict(zip(keys, row, strict=True)) for row in self.cursor.fetchall()]

    def record_invalidation(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_content_invalidation (
                invalidation_id, project_id, target_asset_version_id,
                cause_type, cause_ref, dimension, status,
                created_by_operation_id
            ) VALUES (
                %(invalidation_id)s, %(project_id)s,
                %(target_asset_version_id)s, %(cause_type)s,
                %(cause_ref)s, %(dimension)s, 'OPEN',
                %(created_by_operation_id)s
            ) ON CONFLICT (target_asset_version_id, cause_type, cause_ref)
              DO NOTHING
            """,
            row,
        )

    def resolve_invalidations(
        self,
        *,
        project_id: str,
        target_asset_version_id: str,
        resolved_by_operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_content_invalidation
            SET status='RESOLVED', resolved_at=NOW(),
                resolved_by_operation_id=%s
            WHERE project_id=%s AND target_asset_version_id=%s
              AND status='OPEN'
            """,
            [resolved_by_operation_id, project_id, target_asset_version_id],
        )

    def existing_plan(
        self, *, project_id: str, desired_state_hash: str, plan_hash: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT plan.reprocessing_plan_id, plan.asset_version_id,
                   plan.created_by_operation_id, operation.status,
                   version.content_hash
            FROM authority_source_reprocessing_plan AS plan
            JOIN authority_operation AS operation
              ON operation.operation_id=plan.created_by_operation_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=plan.asset_version_id
            WHERE plan.project_id=%s AND plan.desired_state_hash=%s
              AND plan.plan_hash=%s
            """,
            [project_id, desired_state_hash, plan_hash],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(
            zip(
                (
                    "reprocessing_plan_id",
                    "asset_version_id",
                    "operation_id",
                    "operation_status",
                    "content_hash",
                ),
                row,
                strict=True,
            )
        )

    def register_plan(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_reprocessing_plan (
                reprocessing_plan_id, project_id, workspace_id,
                asset_version_id, source_transform_id, desired_state_hash,
                plan_hash, item_count, status, created_by_operation_id
            ) VALUES (
                %(reprocessing_plan_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(source_transform_id)s,
                %(desired_state_hash)s, %(plan_hash)s, %(item_count)s,
                'PLANNED', %(created_by_operation_id)s
            )
            """,
            row,
        )

    def register_plan_item(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_source_reprocessing_plan_item (
                reprocessing_plan_asset_version_id, project_id, ordinal,
                target_key, dimension, scale, action,
                current_asset_version_id, desired_analyzer_contract_hash,
                reason, created_by_operation_id
            ) VALUES (
                %(reprocessing_plan_asset_version_id)s, %(project_id)s,
                %(ordinal)s, %(target_key)s, %(dimension)s, %(scale)s,
                %(action)s, %(current_asset_version_id)s,
                %(desired_analyzer_contract_hash)s, %(reason)s,
                %(created_by_operation_id)s
            )
            """,
            row,
        )


__all__ = ["SourceIntelligenceRepository"]
