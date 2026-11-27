from __future__ import annotations

import json
from typing import Any

from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .projections import build_chapter_transaction_workspace


class PostgresAuthoringQuery:

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.chapter_query = ChapterAuthorityQuery(database_url)

    def recent_trail(
        self,
        *,
        project_id: str,
        book_id: str,
        through_chapter: int,
        limit: int = 8,
    ) -> dict[str, Any]:
        if not project_id or not book_id or through_chapter <= 0:
            raise ValueError(
                "Recent Trail requires project, book, and accepted boundary"
            )
        if limit < 1 or limit > 50:
            raise ValueError("Recent Trail limit must be between 1 and 50")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content_text, retrieval_document_id,
                       source_asset_version_id, projection_hash,
                       accepted_from_chapter, metadata
                FROM authority_narrative_retrieval_document
                WHERE project_id=%s AND book_id=%s
                  AND accepted_from_chapter <= %s
                  AND metadata->>'authoring_projection_kind'='accepted_recent_trail'
                ORDER BY accepted_from_chapter DESC, retrieval_document_id
                LIMIT %s
                """,
                [project_id, book_id, through_chapter, limit],
            )
            rows = uow.cursor.fetchall()
        entries = [json.loads(str(row[0])) for row in reversed(rows)]
        return {
            "type": "RecentTrail",
            "contract_version": "recent-trail-v1",
            "authority": "NONE_REBUILDABLE_PROJECTION",
            "project_id": project_id,
            "book_id": book_id,
            "accepted_through_chapter": through_chapter,
            "entries": entries,
            "projection_evidence": [
                {
                    "retrieval_document_id": str(row[1]),
                    "source_asset_version_id": str(row[2]),
                    "projection_hash": str(row[3]),
                    "accepted_from_chapter": int(row[4]),
                    "accepted_boundary": dict(
                        (row[5] or {}).get("accepted_boundary") or {}
                    ),
                }
                for row in reversed(rows)
            ],
        }

    def hook_debt(
        self,
        *,
        project_id: str,
        book_id: str,
        through_chapter: int,
    ) -> dict[str, Any]:
        if not project_id or not book_id or through_chapter <= 0:
            raise ValueError("Hook Debt requires project, book, and accepted boundary")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content_text, retrieval_document_id,
                       source_asset_version_id, projection_hash,
                       accepted_from_chapter, metadata
                FROM authority_narrative_retrieval_document
                WHERE project_id=%s AND book_id=%s
                  AND accepted_from_chapter <= %s
                  AND metadata->>'authoring_projection_kind'='accepted_hook_debt'
                ORDER BY accepted_from_chapter DESC, retrieval_document_id
                LIMIT 1
                """,
                [project_id, book_id, through_chapter],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "HOOK_DEBT_ACCEPTED_PROJECTION_MISSING",
                "no accepted Hook Debt projection exists at this boundary",
            )
        projection = json.loads(str(row[0]))
        return {
            **projection,
            "retrieval_projection_evidence": {
                "retrieval_document_id": str(row[1]),
                "source_asset_version_id": str(row[2]),
                "projection_hash": str(row[3]),
                "accepted_from_chapter": int(row[4]),
                "accepted_boundary": dict(
                    (row[5] or {}).get("accepted_boundary") or {}
                ),
            },
        }

    def chapter_transaction_workspace(
        self,
        *,
        project_id: str,
        root_operation_id: str,
    ) -> dict[str, Any]:
        run = self.chapter_query.require_acceptance_evidence(
            project_id=project_id,
            root_operation_id=root_operation_id,
        )
        accepted, followups = self._book_evidence(
            project_id=project_id,
            root_operation_id=root_operation_id,
        )
        recent_trail: dict[str, Any] = {}
        hook_debt: dict[str, Any] = {}
        if accepted.get("acceptance_id"):
            recent_trail = self.recent_trail(
                project_id=project_id,
                book_id=str(accepted["book_id"]),
                through_chapter=int(accepted["chapter_number"]),
            )
            hook_debt = self.hook_debt(
                project_id=project_id,
                book_id=str(accepted["book_id"]),
                through_chapter=int(accepted["chapter_number"]),
            )
        return build_chapter_transaction_workspace(
            chapter_run=run,
            accepted_evidence=accepted,
            followup_evidence=followups,
            recent_trail=recent_trail,
            hook_debt=hook_debt,
        )

    def _book_evidence(
        self, *, project_id: str, root_operation_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT request.chapter_request_id, request.book_run_id,
                       production.book_id, request.chapter_number,
                       request.chapter_plan_version,
                       acceptance.acceptance_id,
                       acceptance.acceptance_operation_id,
                       acceptance.chapter_outcome_asset_version_id,
                       acceptance.story_state_asset_version_id,
                       acceptance.canon_snapshot_asset_version_id,
                       acceptance.longform_projection_set_id,
                       acceptance.status, acceptance.evidence
                FROM authority_book_chapter_request AS request
                JOIN authority_book_production AS production
                  ON production.book_run_id=request.book_run_id
                LEFT JOIN authority_book_chapter_acceptance AS acceptance
                  ON acceptance.chapter_request_id=request.chapter_request_id
                 AND acceptance.status='COMMITTED'
                WHERE request.project_id=%s
                  AND request.chapter_root_operation_id=%s
                """,
                [project_id, root_operation_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                return {}, []
            accepted = {
                "chapter_request_id": str(row[0]),
                "book_run_id": str(row[1]),
                "book_id": str(row[2]),
                "chapter_number": int(row[3]),
                "chapter_plan_asset_version_id": str(row[4]),
                "acceptance_id": str(row[5] or ""),
                "acceptance_operation_id": str(row[6] or ""),
                "chapter_outcome_asset_version_id": str(row[7] or ""),
                "story_state_asset_version_id": str(row[8] or ""),
                "canon_snapshot_asset_version_id": str(row[9] or ""),
                "longform_projection_set_id": str(row[10] or ""),
                "status": str(row[11] or "NOT_ACCEPTED"),
                "evidence": dict(row[12] or {}),
            }
            uow.cursor.execute(
                """
                SELECT followup.followup_id, followup.decision, followup.status,
                       followup.reason_evidence, followup.target_plan_version_ids,
                       followup.checkpoint_id, followup.projection_set_id,
                       followup.plan_change_id, followup.last_error,
                       COALESCE(
                           jsonb_agg(
                               jsonb_build_object(
                                   'impact_id', impact.impact_id,
                                   'impacted_asset_version_id',
                                       impact.impacted_asset_version_id,
                                   'execution_scope', impact.execution_scope,
                                   'previous_freshness', impact.previous_freshness,
                                   'target_freshness', impact.target_freshness,
                                   'automatic_mutation_allowed',
                                       impact.automatic_mutation_allowed
                               ) ORDER BY impact.impact_id
                           ) FILTER (WHERE impact.impact_id IS NOT NULL),
                           '[]'::jsonb
                       )
                FROM authority_arc_checkpoint_followup AS followup
                LEFT JOIN authority_plan_change_impact AS impact
                  ON impact.proposal_id=followup.plan_change_id
                WHERE followup.project_id=%s AND followup.book_run_id=%s
                  AND followup.accepted_through_chapter=%s
                GROUP BY followup.followup_id
                ORDER BY followup.created_at, followup.followup_id
                """,
                [project_id, str(row[1]), int(row[3])],
            )
            followups = [
                {
                    "followup_id": str(value[0]),
                    "decision": str(value[1]),
                    "status": str(value[2]),
                    "reason_evidence": dict(value[3] or {}),
                    "target_plan_version_ids": list(value[4] or ()),
                    "checkpoint_id": str(value[5]),
                    "projection_set_id": str(value[6]),
                    "plan_change_id": str(value[7] or ""),
                    "last_error": dict(value[8] or {}),
                    "plan_impacts": list(value[9] or ()),
                }
                for value in uow.cursor.fetchall()
            ]
            uow.cursor.execute(
                """
                SELECT stale.binding_id, stale.contract_type, stale.logical_key,
                       stale.asset_version_id, stale.execution_scope,
                       stale.freshness, stale.version,
                       stale.created_by_operation_id,
                       COALESCE(
                           jsonb_agg(
                               jsonb_build_object(
                                   'binding_id', replacement.binding_id,
                                   'asset_version_id', replacement.asset_version_id,
                                   'execution_scope', replacement.execution_scope,
                                   'freshness', replacement.freshness,
                                   'created_by_operation_id',
                                       replacement.created_by_operation_id
                               ) ORDER BY replacement.created_at,
                                          replacement.binding_id
                           ) FILTER (WHERE replacement.binding_id IS NOT NULL),
                           '[]'::jsonb
                       )
                FROM story_plan_binding AS stale
                LEFT JOIN story_plan_binding AS replacement
                  ON replacement.project_id=stale.project_id
                 AND replacement.book_id=stale.book_id
                 AND replacement.contract_type=stale.contract_type
                 AND replacement.logical_key=stale.logical_key
                 AND replacement.binding_id<>stale.binding_id
                 AND replacement.freshness='CURRENT'
                WHERE stale.project_id=%s AND stale.book_id=%s
                  AND stale.freshness='STALE'
                GROUP BY stale.binding_id
                ORDER BY stale.created_at, stale.binding_id
                """,
                [project_id, str(row[2])],
            )
            followups.extend(
                {
                    "evidence_type": "PLAN_BINDING_FRESHNESS_PROJECTION",
                    "decision": "PLAN_BECAME_STALE",
                    "status": "OBSERVED",
                    "binding_id": str(value[0]),
                    "contract_type": str(value[1]),
                    "logical_key": str(value[2]),
                    "target_plan_version_ids": [str(value[3])],
                    "execution_scope": str(value[4]),
                    "freshness": str(value[5]),
                    "binding_version": int(value[6]),
                    "created_by_operation_id": str(value[7]),
                    "replacements": list(value[8] or ()),
                    "authority": "PLANNING_AUTHORITY_READ_ONLY",
                }
                for value in uow.cursor.fetchall()
            )
        return accepted, followups


__all__ = ["PostgresAuthoringQuery"]
