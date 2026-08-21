"""Unified immutable Artifact lineage and semantic invalidation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class InvalidationPolicy(StrEnum):
    PROPAGATE = "PROPAGATE"
    REQUALIFY = "REQUALIFY"
    INFORMATIONAL = "INFORMATIONAL"
    IMMUNE_ACCEPTED_HISTORY = "IMMUNE_ACCEPTED_HISTORY"


class InvalidationStatus(StrEnum):
    OPEN = "OPEN"
    REGENERATING = "REGENERATING"
    REQUALIFIED = "REQUALIFIED"
    RESOLVED = "RESOLVED"
    IMMUNE = "IMMUNE"


ACCEPTED_HISTORY_TYPES = frozenset(
    {
        "accepted_chapter",
        "accepted_canon_snapshot",
        "accepted_story_state",
        "chapter_outcome",
    }
)


@dataclass(frozen=True, slots=True)
class ArtifactLineageEdge:
    project_id: str
    book_id: str
    upstream_asset_version_id: str
    downstream_asset_version_id: str
    relationship_type: str
    semantic_dimensions: tuple[str, ...]
    invalidation_policy: InvalidationPolicy
    context_fingerprint: str
    created_by_operation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invalidation_policy", InvalidationPolicy(self.invalidation_policy)
        )
        required = (
            self.project_id,
            self.upstream_asset_version_id,
            self.downstream_asset_version_id,
            self.relationship_type,
            self.created_by_operation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Artifact lineage edge is incomplete")
        if self.upstream_asset_version_id == self.downstream_asset_version_id:
            raise ValueError("Artifact lineage cannot self-reference")
        if not self.semantic_dimensions:
            raise ValueError("Artifact lineage requires semantic dimensions")

    @property
    def lineage_edge_id(self) -> str:
        identity = ":".join(
            (
                self.project_id,
                self.upstream_asset_version_id,
                self.downstream_asset_version_id,
                self.relationship_type,
            )
        )
        return str(uuid5(NAMESPACE_URL, f"novel-forge:lineage:{identity}"))


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    source_asset_version_id: str
    dimensions: tuple[str, ...]
    summary: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if (
            not self.source_asset_version_id.strip()
            or not self.dimensions
            or not self.summary.strip()
        ):
            raise ValueError("semantic diff is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_asset_version_id": self.source_asset_version_id,
            "dimensions": list(self.dimensions),
            "summary": self.summary,
            "evidence": dict(self.evidence),
        }


class PostgresArtifactLineageRepository:
    """Cursor-bound append-only lineage and invalidation repository."""

    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def record_edge(self, edge: ArtifactLineageEdge) -> ArtifactLineageEdge:
        self.cursor.execute(
            """
            INSERT INTO authority_artifact_lineage_edge(
                lineage_edge_id, project_id, book_id,
                upstream_asset_version_id, downstream_asset_version_id,
                relationship_type, semantic_dimensions, invalidation_policy,
                context_fingerprint, created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(project_id, upstream_asset_version_id,
                        downstream_asset_version_id, relationship_type) DO NOTHING
            """,
            [
                edge.lineage_edge_id,
                edge.project_id,
                edge.book_id or None,
                edge.upstream_asset_version_id,
                edge.downstream_asset_version_id,
                edge.relationship_type,
                Jsonb(list(edge.semantic_dimensions)),
                edge.invalidation_policy.value,
                edge.context_fingerprint or None,
                edge.created_by_operation_id,
            ],
        )
        self.cursor.execute(
            """
            SELECT invalidation_policy, semantic_dimensions,
                   COALESCE(context_fingerprint, '')
            FROM authority_artifact_lineage_edge
            WHERE lineage_edge_id=%s
            """,
            [edge.lineage_edge_id],
        )
        row = self.cursor.fetchone()
        if row is None or (
            str(row[0]), tuple(row[1] or ()), str(row[2])
        ) != (
            edge.invalidation_policy.value,
            edge.semantic_dimensions,
            edge.context_fingerprint,
        ):
            raise KernelError(
                "ARTIFACT_LINEAGE_CONFLICT", "lineage identity has different semantics"
            )
        return edge

    def invalidate_downstream(
        self,
        *,
        project_id: str,
        book_id: str,
        semantic_diff: SemanticDiff,
        reason: str,
        created_by_operation_id: str,
    ) -> tuple[dict[str, Any], ...]:
        """Traverse dependencies selectively by intersecting semantic dimensions."""

        if not reason.strip() or not created_by_operation_id.strip():
            raise ValueError("semantic invalidation command is incomplete")
        self.cursor.execute(
            """
            WITH RECURSIVE impact AS (
                SELECT edge.downstream_asset_version_id AS target_id,
                       edge.invalidation_policy, edge.semantic_dimensions, 1 AS depth,
                       ARRAY[edge.upstream_asset_version_id,
                             edge.downstream_asset_version_id]::TEXT[] AS path
                FROM authority_artifact_lineage_edge AS edge
                WHERE edge.project_id=%s
                  AND edge.upstream_asset_version_id=%s
                  AND edge.invalidation_policy<>'INFORMATIONAL'
                  AND edge.semantic_dimensions ?| %s::TEXT[]
                UNION ALL
                SELECT edge.downstream_asset_version_id,
                       edge.invalidation_policy, edge.semantic_dimensions,
                       impact.depth + 1,
                       impact.path || edge.downstream_asset_version_id
                FROM impact
                JOIN authority_artifact_lineage_edge AS edge
                  ON edge.project_id=%s
                 AND edge.upstream_asset_version_id=impact.target_id
                WHERE edge.invalidation_policy<>'INFORMATIONAL'
                  AND edge.semantic_dimensions ?| %s::TEXT[]
                  AND NOT edge.downstream_asset_version_id=ANY(impact.path)
            )
            SELECT DISTINCT ON (impact.target_id)
                   impact.target_id, impact.invalidation_policy,
                   asset.asset_type, impact.depth,
                   COALESCE(binding.execution_scope, '')
            FROM impact
            JOIN authority_asset_version AS version
              ON version.asset_version_id=impact.target_id
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            LEFT JOIN story_plan_binding AS binding
              ON binding.project_id=%s
             AND binding.asset_version_id=impact.target_id
            ORDER BY impact.target_id, impact.depth
            """,
            [
                project_id,
                semantic_diff.source_asset_version_id,
                list(semantic_diff.dimensions),
                project_id,
                list(semantic_diff.dimensions),
                project_id,
            ],
        )
        affected: list[dict[str, Any]] = []
        for (
            target_id,
            raw_policy,
            asset_type,
            depth,
            execution_scope,
        ) in self.cursor.fetchall():
            policy = InvalidationPolicy(str(raw_policy))
            immutable = (
                policy is InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
                or str(asset_type) in ACCEPTED_HISTORY_TYPES
                or str(execution_scope) == "EXECUTED"
            )
            status = (
                InvalidationStatus.IMMUNE if immutable else InvalidationStatus.OPEN
            )
            invalidation_id = str(
                uuid5(
                    NAMESPACE_URL,
                    "novel-forge:invalidation:"
                    f"{project_id}:{semantic_diff.source_asset_version_id}:{target_id}",
                )
            )
            self.cursor.execute(
                """
                INSERT INTO authority_artifact_invalidation(
                    invalidation_id, project_id, book_id,
                    target_asset_version_id, source_asset_version_id,
                    semantic_diff, status, reason, created_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(project_id, target_asset_version_id,
                            source_asset_version_id, status) DO NOTHING
                """,
                [
                    invalidation_id,
                    project_id,
                    book_id or None,
                    str(target_id),
                    semantic_diff.source_asset_version_id,
                    Jsonb(semantic_diff.to_dict()),
                    status.value,
                    reason,
                    created_by_operation_id,
                ],
            )
            affected.append(
                {
                    "target_asset_version_id": str(target_id),
                    "asset_type": str(asset_type),
                    "policy": policy.value,
                    "status": status.value,
                    "depth": int(depth),
                }
            )
        return tuple(affected)

    def record_requalification(
        self,
        *,
        invalidation_id: str,
        replacement_asset_version_id: str,
        resolved_by_operation_id: str,
    ) -> None:
        """Resolve evidence only; never reactivate an old active pointer."""

        self.cursor.execute(
            """
            SELECT project_id, target_asset_version_id, status
            FROM authority_artifact_invalidation
            WHERE invalidation_id=%s FOR UPDATE
            """,
            [invalidation_id],
        )
        row = self.cursor.fetchone()
        if row is None or str(row[2]) not in {"OPEN", "REGENERATING"}:
            raise KernelError(
                "ARTIFACT_INVALIDATION_NOT_OPEN", "invalidation is not requalifiable"
            )
        self.cursor.execute(
            """
            SELECT 1 FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE version.asset_version_id=%s AND asset.project_id=%s
              AND version.lifecycle IN ('ACTIVE','CANDIDATE')
              AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'
            """,
            [replacement_asset_version_id, str(row[0])],
        )
        if self.cursor.fetchone() is None:
            raise KernelError(
                "ARTIFACT_REQUALIFICATION_EVIDENCE_INVALID",
                "replacement AssetVersion is not qualified",
            )
        self.cursor.execute(
            """
            UPDATE authority_artifact_invalidation
            SET status='REQUALIFIED', resolved_by_operation_id=%s, resolved_at=NOW(),
                semantic_diff=semantic_diff || jsonb_build_object(
                    'replacement_asset_version_id', %s::TEXT
                )
            WHERE invalidation_id=%s AND status IN ('OPEN','REGENERATING')
            """,
            [resolved_by_operation_id, replacement_asset_version_id, invalidation_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "ARTIFACT_INVALIDATION_CAS_CONFLICT", "invalidation changed concurrently"
            )


def lineage_policy_for(asset_type: str) -> InvalidationPolicy:
    return (
        InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
        if asset_type in ACCEPTED_HISTORY_TYPES
        else InvalidationPolicy.REQUALIFY
        if asset_type in {"context_bundle", "context_manifest"}
        else InvalidationPolicy.PROPAGATE
    )


def semantic_dimensions_for(asset_types: tuple[str, ...]) -> tuple[str, ...]:
    dimensions = {"narrative"}
    for asset_type in asset_types:
        lowered = asset_type.lower()
        dimensions.add(lowered)
        for marker in (
            "world",
            "character",
            "relationship",
            "arc",
            "obligation",
            "plan",
            "context",
            "canon",
            "state",
            "scene",
            "chapter",
            "quality",
        ):
            if marker in lowered:
                dimensions.add(marker)
    return tuple(sorted(dimensions))


__all__ = [
    "ACCEPTED_HISTORY_TYPES",
    "ArtifactLineageEdge",
    "InvalidationPolicy",
    "InvalidationStatus",
    "PostgresArtifactLineageRepository",
    "SemanticDiff",
    "lineage_policy_for",
    "semantic_dimensions_for",
]
