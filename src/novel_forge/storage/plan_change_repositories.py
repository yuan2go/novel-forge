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

    def reconcile_replaced_target_impact(self, proposal_id: str) -> bool:
        self.cursor.execute(
            """INSERT INTO authority_plan_change_impact(
                impact_id,proposal_id,project_id,source_asset_version_id,impacted_asset_version_id,
                dependency_path,execution_scope,previous_freshness,target_freshness,automatic_mutation_allowed,recorded_by_operation_id)
            SELECT 'plan-impact:'||proposal.proposal_id||':'||old.asset_version_id,
                proposal.proposal_id,proposal.project_id,old.asset_version_id,old.asset_version_id,
                jsonb_build_array(old.asset_version_id),old.execution_scope,old.freshness,'STALE',
                old.execution_scope='SPECULATIVE',proposal.activation_operation_id
            FROM authority_plan_change_proposal proposal
            JOIN story_plan_binding old ON old.project_id=proposal.project_id AND old.book_id=proposal.book_id
              AND old.asset_version_id=proposal.target_asset_version_id AND old.freshness='STALE'
              AND old.execution_scope IN ('PLANNED','SPECULATIVE','FROZEN') AND old.execution_scope=proposal.target_execution_scope
            JOIN active_story_plan_version active ON active.project_id=proposal.project_id AND active.book_id=proposal.book_id
              AND active.logical_key=proposal.target_logical_key AND active.asset_version_id=proposal.proposed_asset_version_id
            WHERE proposal.proposal_id=%s AND proposal.status='ACTIVE'
              AND proposal.approval_operation_id IS NOT NULL AND proposal.activation_operation_id IS NOT NULL
            ON CONFLICT(proposal_id,impacted_asset_version_id) DO NOTHING""",
            [proposal_id],
        )
        return self.cursor.rowcount == 1

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
                SELECT binding.asset_version_id,
                       ARRAY[binding.asset_version_id]::TEXT[],
                       ARRAY[]::TEXT[]
                FROM story_plan_binding AS binding
                WHERE binding.project_id=%s AND binding.asset_version_id=%s
                  AND binding.execution_scope IN ('PLANNED','SPECULATIVE','FROZEN')
                UNION ALL
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
                           OR impact.impacted_asset_version_id=%s
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
                source_asset_version_id,
                project_id,
                source_asset_version_id,
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
                if str(impacted_version) == source_asset_version_id or bool(must_mark_stale) and scope in {"PLANNED", "SPECULATIVE"}
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

    @staticmethod
    def _confirmed_impacts(
        discovery: dict[str, Any],
        dispositions: list[dict[str, Any]],
    ) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        confirmed = {
            item["hypothesis_id"]
            for item in dispositions
            if item["disposition"] == "CONFIRMED"
        }
        return {
            item["asset_version_id"]: (item, hypothesis)
            for hypothesis in discovery.get("hypotheses", [])
            if hypothesis["hypothesis_id"] in confirmed
            for item in [
                hypothesis["candidate"],
                *hypothesis.get("declared_dependents", []),
            ]
        }

    def require_current_inferred_impacts(
        self,
        *,
        project_id: str,
        book_id: str,
        discovery: dict[str, Any],
        dispositions: list[dict[str, Any]],
    ) -> None:
        for version_id, (snapshot, _) in sorted(
            self._confirmed_impacts(discovery, dispositions).items()
        ):
            self.cursor.execute(
                """SELECT asset_version_id FROM active_story_plan_version
                   WHERE project_id=%s AND book_id=%s AND logical_key=%s FOR UPDATE""",
                [project_id, book_id, snapshot["logical_key"]],
            )
            self.cursor.execute(
                """SELECT binding.execution_scope,binding.version,binding.freshness,version.content_hash,
                          (SELECT active.asset_version_id FROM active_story_plan_version active
                           WHERE active.project_id=binding.project_id AND active.book_id=binding.book_id
                             AND active.logical_key=binding.logical_key)
                   FROM story_plan_binding binding JOIN authority_asset_version version USING(asset_version_id)
                   WHERE binding.project_id=%s AND binding.book_id=%s AND binding.asset_version_id=%s
                   FOR UPDATE OF binding""",
                [project_id, book_id, version_id],
            )
            row = self.cursor.fetchone()
            if row is None or tuple(row) != (
                snapshot["execution_scope"],
                snapshot["binding_version"],
                snapshot["freshness"],
                snapshot["content_hash"],
                snapshot.get("active_asset_version_id"),
            ):
                raise KernelError(
                    "PLAN_IMPACT_EVIDENCE_STALE",
                    "confirmed impact no longer matches its frozen plan version and execution boundary",
                )
            if row[0] == "FROZEN":
                raise KernelError(
                    "PLAN_IMPACT_FUTURE_ONLY",
                    "inferred changes require settlement of frozen execution before future revalidation",
                )

    def record_inferred_impacts(
        self,
        *,
        proposal_id: str,
        project_id: str,
        book_id: str,
        source_asset_version_id: str,
        operation_id: str,
        discovery: dict[str, Any],
        dispositions: list[dict[str, Any]],
    ) -> list[str]:
        impacts = self._confirmed_impacts(discovery, dispositions)
        for version_id, (snapshot, hypothesis) in sorted(impacts.items()):
            scope = snapshot["execution_scope"]
            preserved = scope == "EXECUTED"
            target = snapshot["freshness"] if preserved else "IMPACTED"
            self.cursor.execute(
                """INSERT INTO authority_plan_change_impact(
                     impact_id,proposal_id,project_id,source_asset_version_id,impacted_asset_version_id,
                     dependency_path,execution_scope,previous_freshness,target_freshness,
                     automatic_mutation_allowed,recorded_by_operation_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s)
                   ON CONFLICT(proposal_id,impacted_asset_version_id) DO NOTHING""",
                [
                    f"plan-impact:{proposal_id}:{version_id}",
                    proposal_id,
                    project_id,
                    source_asset_version_id,
                    version_id,
                    Jsonb([source_asset_version_id, version_id]),
                    scope,
                    snapshot["freshness"],
                    target,
                    operation_id,
                ],
            )
            if preserved:
                continue
            self.cursor.execute(
                """UPDATE story_plan_binding SET freshness='IMPACTED',version=version+1
                   WHERE project_id=%s AND book_id=%s AND asset_version_id=%s
                     AND execution_scope IN ('PLANNED','SPECULATIVE') AND freshness='CURRENT'""",
                [project_id, book_id, version_id],
            )
            self.cursor.execute(
                """DELETE FROM active_story_plan_version active USING story_plan_binding binding
                   WHERE active.binding_id=binding.binding_id AND binding.project_id=%s
                     AND binding.asset_version_id=%s AND binding.freshness IN ('IMPACTED','STALE')""",
                [project_id, version_id],
            )
            self.cursor.execute(
                """INSERT INTO authority_artifact_invalidation(
                     invalidation_id,project_id,book_id,target_asset_version_id,source_asset_version_id,
                     semantic_diff,status,reason,created_by_operation_id)
                   VALUES(%s,%s,%s,%s,%s,%s,'OPEN',%s,%s)
                   ON CONFLICT(project_id,target_asset_version_id,source_asset_version_id,status) DO NOTHING""",
                [
                    f"inferred-plan-impact:{proposal_id}:{version_id}",
                    project_id,
                    book_id,
                    version_id,
                    source_asset_version_id,
                    Jsonb(
                        {
                            "source_asset_version_id": source_asset_version_id,
                            "dimensions": ["planning"],
                            "summary": "Authority-confirmed inferred impact requires revalidation",
                            "evidence": {
                                "proposal_id": proposal_id,
                                "hypothesis_id": hypothesis["hypothesis_id"],
                                "corpus_digest": discovery["corpus_digest"],
                                "plan_evidence": hypothesis["plan_evidence"],
                            },
                        }
                    ),
                    f"approved inferred PlanChange {proposal_id}",
                    operation_id,
                ],
            )
            PostgresArtifactLineageRepository(self.cursor).invalidate_downstream(
                project_id=project_id,
                book_id=book_id,
                semantic_diff=SemanticDiff(
                    source_asset_version_id=version_id,
                    dimensions=semantic_dimensions_for(("planning",)),
                    summary="derived artifacts of an Authority-confirmed inferred plan impact",
                    evidence={
                        "proposal_id": proposal_id,
                        "hypothesis_id": hypothesis["hypothesis_id"],
                    },
                ),
                reason=f"approved inferred PlanChange {proposal_id}",
                created_by_operation_id=operation_id,
            )
        return sorted(impacts)

    def revalidate(
        self,
        *,
        project_id: str,
        asset_version_id: str,
        evidence_version_id: str,
        operation_id: str,
    ) -> bool:
        self.cursor.execute(
            """SELECT 1 FROM authority_artifact_invalidation
               WHERE project_id=%s AND target_asset_version_id=%s
                 AND resolved_by_operation_id=%s AND status='REQUALIFIED' LIMIT 1""",
            [project_id, asset_version_id, operation_id],
        )
        if self.cursor.fetchone() is not None:
            return False
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
            or str(content.get("target_asset_version_id") or "") != asset_version_id
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
        return True

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
