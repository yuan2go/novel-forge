from __future__ import annotations

from typing import Any
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.artifact_lineage import (
    PostgresArtifactLineageRepository,
    SemanticDiff,
    semantic_dimensions_for,
)


class PlanChangeRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create_proposal(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_plan_change_proposal(
                proposal_id, project_id, book_id, source_type,
                source_evidence_version_id, target_asset_version_id,
                proposed_asset_version_id, target_contract_type,
                target_logical_key, target_execution_scope,
                semantic_diff, risk, status, proposal_operation_id,
                stable_idempotency_key
            ) VALUES (
                %(proposal_id)s, %(project_id)s, %(book_id)s,
                %(source_type)s, %(source_evidence_version_id)s,
                %(target_asset_version_id)s,
                %(proposed_asset_version_id)s, %(target_contract_type)s,
                %(target_logical_key)s, %(target_execution_scope)s,
                %(semantic_diff)s, %(risk)s, 'PENDING_APPROVAL',
                %(proposal_operation_id)s, %(stable_idempotency_key)s
            )
            ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
            """,
            {**row, "semantic_diff": Jsonb(row["semantic_diff"])},
        )

    def decide(
        self,
        *,
        proposal_id: str,
        project_id: str,
        decision: str,
        operation_id: str,
        authority_type: str,
        authority_version: str,
        evidence: dict[str, Any],
        decided_by: str,
    ) -> None:
        self.cursor.execute(
            """
            SELECT status FROM authority_plan_change_proposal
            WHERE proposal_id=%s AND project_id=%s
            FOR UPDATE
            """,
            [proposal_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLAN_CHANGE_NOT_FOUND", "PlanChangeProposal does not exist"
            )
        if str(row[0]) not in {
            "PENDING_APPROVAL",
            "APPROVED",
            "REJECTED",
        }:
            raise KernelError(
                "PLAN_CHANGE_DECISION_CONFLICT",
                "PlanChangeProposal cannot be decided in its current state",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_plan_change_decision(
                decision_id, proposal_id, project_id, decision,
                authority_type, authority_version, decision_operation_id,
                evidence, decided_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(proposal_id) DO NOTHING
            """,
            [
                f"plan-change-decision:{proposal_id}",
                proposal_id,
                project_id,
                decision,
                authority_type,
                authority_version,
                operation_id,
                Jsonb(evidence),
                decided_by,
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_plan_change_proposal
            SET status=%s, approval_operation_id=%s,
                version=version+1, updated_at=NOW()
            WHERE proposal_id=%s
              AND status IN ('PENDING_APPROVAL', %s)
            """,
            [decision, operation_id, proposal_id, decision],
        )

    def mark_activation_pending(self, proposal_id: str, operation_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_plan_change_proposal
            SET status='ACTIVATION_PENDING', activation_operation_id=%s,
                version=version+1, updated_at=NOW()
            WHERE proposal_id=%s AND status IN ('APPROVED', 'ACTIVATION_PENDING')
            """,
            [operation_id, proposal_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "PLAN_CHANGE_NOT_APPROVED",
                "PlanChange activation requires an approved decision",
            )

    def record_impacts(
        self,
        *,
        proposal_id: str,
        project_id: str,
        source_asset_version_id: str,
        operation_id: str,
    ) -> int:
        self.cursor.execute(
            """
            WITH RECURSIVE impact(
                impacted_asset_version_id, dependency_path,
                invalidation_path
            ) AS (
                SELECT edge.dependent_asset_version_id,
                       ARRAY[
                           edge.source_asset_version_id,
                           edge.dependent_asset_version_id
                       ]::TEXT[],
                       ARRAY[edge.invalidation_policy]::TEXT[]
                FROM asset_dependency_edge AS edge
                WHERE edge.project_id=%s
                  AND edge.source_asset_version_id=%s
                  AND edge.invalidation_policy<>'NONE'
                UNION ALL
                SELECT edge.dependent_asset_version_id,
                       impact.dependency_path
                           || edge.dependent_asset_version_id,
                       impact.invalidation_path || edge.invalidation_policy
                FROM impact
                JOIN asset_dependency_edge AS edge
                  ON edge.project_id=%s
                 AND edge.source_asset_version_id=
                     impact.impacted_asset_version_id
                WHERE NOT edge.dependent_asset_version_id=
                          ANY(impact.dependency_path)
                  AND edge.invalidation_policy<>'NONE'
            )
            SELECT DISTINCT ON (ranked.impacted_asset_version_id)
                   ranked.impacted_asset_version_id,
                   ranked.dependency_path,
                   ranked.execution_scope,
                   ranked.freshness,
                   ranked.must_mark_stale
            FROM (
                SELECT impact.impacted_asset_version_id,
                       impact.dependency_path,
                       binding.execution_scope,
                       binding.freshness,
                       BOOL_OR(
                           'MARK_STALE'=ANY(impact.invalidation_path)
                       ) OVER (
                           PARTITION BY impact.impacted_asset_version_id
                       ) AS must_mark_stale
                FROM impact
                JOIN story_plan_binding AS binding
                  ON binding.project_id=%s
                 AND binding.asset_version_id=
                     impact.impacted_asset_version_id
            ) AS ranked
            ORDER BY ranked.impacted_asset_version_id,
                     cardinality(ranked.dependency_path),
                     ranked.dependency_path
            """,
            [
                project_id,
                source_asset_version_id,
                project_id,
                project_id,
            ],
        )
        impacts = self.cursor.fetchall()
        for (
            impacted_version,
            path,
            execution_scope,
            freshness,
            must_mark_stale,
        ) in impacts:
            scope = str(execution_scope)
            previous = str(freshness)
            target = (
                previous
                if scope == "EXECUTED"
                else "STALE"
                if bool(must_mark_stale)
                and scope in {"PLANNED", "SPECULATIVE"}
                else "IMPACTED"
            )
            automatic = scope == "SPECULATIVE"
            self.cursor.execute(
                """
                INSERT INTO authority_plan_change_impact(
                    impact_id, proposal_id, project_id,
                    source_asset_version_id, impacted_asset_version_id,
                    dependency_path, execution_scope, previous_freshness,
                    target_freshness, automatic_mutation_allowed,
                    recorded_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(proposal_id, impacted_asset_version_id)
                DO NOTHING
                """,
                [
                    f"plan-impact:{proposal_id}:{impacted_version}",
                    proposal_id,
                    project_id,
                    source_asset_version_id,
                    str(impacted_version),
                    Jsonb(list(path)),
                    scope,
                    previous,
                    target,
                    automatic,
                    operation_id,
                ],
            )
            if scope != "EXECUTED":
                self.cursor.execute(
                    """
                    UPDATE story_plan_binding
                    SET freshness=%s, version=version+1
                    WHERE project_id=%s AND asset_version_id=%s
                      AND freshness<>%s
                    """,
                    [
                        target,
                        project_id,
                        str(impacted_version),
                        target,
                    ],
                )
                self.cursor.execute(
                    """
                    DELETE FROM active_story_plan_version AS active
                    USING story_plan_binding AS binding
                    WHERE active.binding_id=binding.binding_id
                      AND binding.project_id=%s
                      AND binding.asset_version_id=%s
                      AND binding.freshness IN ('IMPACTED','STALE')
                    """,
                    [project_id, str(impacted_version)],
                )
        self.cursor.execute(
            """
            SELECT book_id, semantic_diff
            FROM authority_plan_change_proposal
            WHERE proposal_id=%s AND project_id=%s
            """,
            [proposal_id, project_id],
        )
        proposal = self.cursor.fetchone()
        if proposal is None:
            raise KernelError(
                "PLAN_CHANGE_NOT_FOUND", "PlanChangeProposal disappeared during impact"
            )
        raw_diff = tuple(dict(item) for item in proposal[1] or ())
        fields = tuple(str(item.get("field") or "") for item in raw_diff)
        dimensions = semantic_dimensions_for(
            ("planning", *(item for item in fields if item))
        )
        PostgresArtifactLineageRepository(self.cursor).invalidate_downstream(
            project_id=project_id,
            book_id=str(proposal[0]),
            semantic_diff=SemanticDiff(
                source_asset_version_id=source_asset_version_id,
                dimensions=dimensions,
                summary="approved PlanChange semantic impact",
                evidence={"proposal_id": proposal_id, "changes": list(raw_diff)},
            ),
            reason=f"approved PlanChange {proposal_id}",
            created_by_operation_id=operation_id,
        )
        return len(impacts)

    def mark_active(self, proposal_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_plan_change_proposal
            SET status='ACTIVE', failure_reason='',
                version=version+1, updated_at=NOW()
            WHERE proposal_id=%s AND status='ACTIVATION_PENDING'
            """,
            [proposal_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "PLAN_CHANGE_ACTIVATION_CONFLICT",
                "PlanChange activation checkpoint is inconsistent",
            )

    def revalidate(
        self,
        *,
        project_id: str,
        asset_version_id: str,
        evidence_version_id: str,
        operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            SELECT evidence.content, evidence.eligibility, evidence.governance,
                   asset.asset_type
            FROM authority_asset_version AS evidence
            JOIN authority_asset AS asset ON asset.asset_id=evidence.asset_id
            WHERE evidence.asset_version_id=%s AND asset.project_id=%s
            """,
            [evidence_version_id, project_id],
        )
        evidence = self.cursor.fetchone()
        content = dict(evidence[0] or {}) if evidence is not None else {}
        if (
            evidence is None
            or str(evidence[3]) != "plan_requalification_evidence"
            or str(evidence[1]) != "ELIGIBLE"
            or str(evidence[2]) != "CLEAR"
            or str(content.get("target_asset_version_id") or "")
            != asset_version_id
            or str(content.get("resolution_status") or "") != "QUALIFIED"
        ):
            raise KernelError(
                "PLAN_REVALIDATION_EVIDENCE_INVALID",
                "revalidation requires qualified evidence for the exact stale plan",
            )
        self.cursor.execute(
            """
            SELECT invalidation_id
            FROM authority_artifact_invalidation
            WHERE project_id=%s AND target_asset_version_id=%s
              AND status IN ('OPEN','REGENERATING')
            FOR UPDATE
            """,
            [project_id, asset_version_id],
        )
        invalidation_ids = tuple(str(row[0]) for row in self.cursor.fetchall())
        if not invalidation_ids:
            raise KernelError(
                "PLAN_REVALIDATION_EVIDENCE_INVALID",
                "plan has no open semantic invalidation to resolve",
            )
        declared = {str(item) for item in content.get("invalidation_ids") or ()}
        if not set(invalidation_ids).issubset(declared):
            raise KernelError(
                "PLAN_REVALIDATION_EVIDENCE_INCOMPLETE",
                "requalification evidence does not cover every open invalidation",
            )
        lineage = PostgresArtifactLineageRepository(self.cursor)
        for invalidation_id in invalidation_ids:
            lineage.record_requalification(
                invalidation_id=invalidation_id,
                replacement_asset_version_id=asset_version_id,
                resolved_by_operation_id=operation_id,
            )
        self.cursor.execute(
            """
            UPDATE story_plan_binding
            SET freshness='CURRENT', version=version+1
            WHERE project_id=%s AND asset_version_id=%s
              AND freshness IN ('IMPACTED', 'STALE')
              AND execution_scope <> 'EXECUTED'
            """,
            [project_id, asset_version_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "PLAN_REVALIDATION_NOT_REQUIRED",
                "plan is not stale or impacted",
            )

    def require(self, proposal_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT proposal_id, project_id, book_id, source_type,
                   source_evidence_version_id, target_asset_version_id,
                   proposed_asset_version_id, target_contract_type,
                   target_logical_key, target_execution_scope,
                   semantic_diff, risk, status, proposal_operation_id,
                   approval_operation_id, activation_operation_id,
                   stable_idempotency_key, failure_reason, version
            FROM authority_plan_change_proposal
            WHERE proposal_id=%s
            """,
            [proposal_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLAN_CHANGE_NOT_FOUND", "PlanChangeProposal does not exist"
            )
        fields = (
            "proposal_id",
            "project_id",
            "book_id",
            "source_type",
            "source_evidence_version_id",
            "target_asset_version_id",
            "proposed_asset_version_id",
            "target_contract_type",
            "target_logical_key",
            "target_execution_scope",
            "semantic_diff",
            "risk",
            "status",
            "proposal_operation_id",
            "approval_operation_id",
            "activation_operation_id",
            "stable_idempotency_key",
            "failure_reason",
            "version",
        )
        return dict(zip(fields, row, strict=True))


__all__ = ["PlanChangeRepository"]
