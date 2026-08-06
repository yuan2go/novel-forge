"""Transactional plan-change proposal, decision and impact persistence."""

from __future__ import annotations

from typing import Any
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


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
                impacted_asset_version_id, dependency_path
            ) AS (
                SELECT edge.dependent_asset_version_id,
                       ARRAY[
                           edge.source_asset_version_id,
                           edge.dependent_asset_version_id
                       ]::TEXT[]
                FROM asset_dependency_edge AS edge
                WHERE edge.project_id=%s
                  AND edge.source_asset_version_id=%s
                UNION ALL
                SELECT edge.dependent_asset_version_id,
                       impact.dependency_path
                           || edge.dependent_asset_version_id
                FROM impact
                JOIN asset_dependency_edge AS edge
                  ON edge.project_id=%s
                 AND edge.source_asset_version_id=
                     impact.impacted_asset_version_id
                WHERE NOT edge.dependent_asset_version_id=
                          ANY(impact.dependency_path)
            )
            SELECT DISTINCT ON (impact.impacted_asset_version_id)
                   impact.impacted_asset_version_id,
                   impact.dependency_path,
                   binding.execution_scope,
                   binding.freshness
            FROM impact
            JOIN story_plan_binding AS binding
              ON binding.project_id=%s
             AND binding.asset_version_id=
                 impact.impacted_asset_version_id
            ORDER BY impact.impacted_asset_version_id,
                     cardinality(impact.dependency_path)
            """,
            [
                project_id,
                source_asset_version_id,
                project_id,
                project_id,
            ],
        )
        impacts = self.cursor.fetchall()
        for impacted_version, path, execution_scope, freshness in impacts:
            scope = str(execution_scope)
            previous = str(freshness)
            target = {
                "EXECUTED": previous,
                "FROZEN": "IMPACTED",
                "PLANNED": "STALE",
                "SPECULATIVE": "STALE",
            }[scope]
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
        operation_id: str,
    ) -> None:
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
