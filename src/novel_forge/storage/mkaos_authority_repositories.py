"""PostgreSQL projections and locks for MKAOS Authority operations."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class MkaosAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def require_scope(self, *, project_id: str, workspace_id: str) -> None:
        self.cursor.execute(
            """
            SELECT project.status, workspace.status
            FROM authority_project AS project
            JOIN authority_workspace AS workspace
              ON workspace.workspace_id = %s
             AND workspace.project_id = project.project_id
            WHERE project.project_id = %s
            FOR SHARE OF project, workspace
            """,
            [workspace_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MKAOS_PROJECT_SCOPE_INVALID",
                "MKAOS workspace does not belong to the Authority project",
            )
        if "DELETED" in row or "ARCHIVED" in row:
            raise KernelError(
                "MKAOS_PROJECT_LIFECYCLE_BLOCKED",
                "archived or deleted Project/Workspace cannot accept MKAOS writes",
            )

    def execution_evidence(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT version.asset_version_id, asset.asset_type,
                   asset.project_id, version.lifecycle,
                   version.eligibility, version.governance,
                   version.content_hash, version.content
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
            WHERE version.asset_version_id = %s
            FOR SHARE OF version, asset
            """,
            [asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MKAOS_EXECUTION_EVIDENCE_NOT_FOUND",
                "MKAOS candidate requires an execution evidence AssetVersion",
            )
        result = dict(
            zip(
                (
                    "asset_version_id",
                    "asset_type",
                    "project_id",
                    "lifecycle",
                    "eligibility",
                    "governance",
                    "content_hash",
                    "content",
                ),
                row,
                strict=True,
            )
        )
        if result["project_id"] != project_id:
            raise KernelError(
                "CROSS_PROJECT_REFERENCE",
                "execution evidence belongs to another project",
            )
        if result["asset_type"] not in {
            "model_call_log",
            "execution_commit_manifest",
            "agent_run",
        }:
            raise KernelError(
                "MKAOS_EXECUTION_EVIDENCE_INVALID",
                "candidate evidence is not a governed execution AssetVersion",
            )
        if (
            result["lifecycle"],
            result["eligibility"],
            result["governance"],
        ) != ("ACTIVE", "ELIGIBLE", "CLEAR"):
            raise KernelError(
                "MKAOS_EXECUTION_EVIDENCE_INELIGIBLE",
                "execution evidence is not production eligible",
            )
        return result

    def source_chunks(
        self, *, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT chunk.asset_version_id, chunk.source_chunk_id,
                   chunk.byte_size, chunk.content_hash,
                   version.content_hash,
                   chunk.source_document_id, chunk.source_transform_id,
                   version.lifecycle, version.eligibility, version.governance,
                   source.governance_status
            FROM authority_source_chunk AS chunk
            JOIN authority_asset_version AS version
              ON version.asset_version_id = chunk.asset_version_id
            JOIN authority_source_document AS source
              ON source.source_document_id = chunk.source_document_id
            WHERE chunk.project_id = %s
              AND chunk.asset_version_id = ANY(%s)
            ORDER BY chunk.asset_version_id
            FOR SHARE OF chunk, version, source
            """,
            [project_id, list(asset_version_ids)],
        )
        keys = (
            "asset_version_id",
            "source_chunk_id",
            "byte_size",
            "content_hash",
            "asset_content_hash",
            "source_document_id",
            "source_transform_id",
            "lifecycle",
            "eligibility",
            "governance",
            "source_governance_status",
        )
        rows = {
            str(row[0]): dict(zip(keys, row, strict=True))
            for row in self.cursor.fetchall()
        }
        for row in rows.values():
            if (
                row["lifecycle"] != "ACTIVE"
                or row["governance"] != "CLEAR"
                or row["source_governance_status"] != "ELIGIBLE"
            ):
                raise KernelError(
                    "MKAOS_SOURCE_CHUNK_INELIGIBLE",
                    "SourceChunk lineage is no longer governed and active",
                )
        return rows

    def candidate_for_approval(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT candidate.knowledge_candidate_id, candidate.project_id,
                   candidate.workspace_id, candidate.asset_version_id,
                   candidate.execution_asset_version_id,
                   candidate.candidate_hash,
                   candidate.abstraction_policy_version, candidate.status,
                   candidate.created_by_operation_id,
                   version.lifecycle, version.eligibility,
                   version.governance, version.content_hash, version.content
            FROM authority_mkaos_knowledge_candidate AS candidate
            JOIN authority_asset_version AS version
              ON version.asset_version_id = candidate.asset_version_id
            WHERE candidate.project_id = %s
              AND candidate.asset_version_id = %s
            FOR UPDATE OF candidate, version
            """,
            [project_id, asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MKAOS_CANDIDATE_NOT_FOUND",
                "knowledge candidate does not exist in the Authority project",
            )
        keys = (
            "knowledge_candidate_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "execution_asset_version_id",
            "candidate_hash",
            "abstraction_policy_version",
            "status",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content_hash",
            "content",
        )
        return dict(zip(keys, row, strict=True))

    def target_asset(
        self,
        *,
        project_id: str,
        asset_version_id: str,
        for_update: bool = False,
    ) -> dict[str, Any]:
        lock_clause = "FOR UPDATE OF version, asset" if for_update else "FOR SHARE OF version, asset"
        self.cursor.execute(
            f"""
            SELECT version.asset_version_id, asset.asset_type,
                   asset.project_id, version.content_hash,
                   version.lifecycle, version.eligibility, version.governance
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
            WHERE version.asset_version_id = %s
            {lock_clause}
            """,
            [asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "MKAOS_TARGET_NOT_FOUND", "KnowledgePack target AssetVersion is missing"
            )
        keys = (
            "asset_version_id",
            "asset_type",
            "project_id",
            "content_hash",
            "lifecycle",
            "eligibility",
            "governance",
        )
        result = dict(zip(keys, row, strict=True))
        if result["project_id"] != project_id:
            raise KernelError(
                "CROSS_PROJECT_REFERENCE", "KnowledgePack target belongs to another project"
            )
        if result["lifecycle"] not in {"ACTIVE", "CANDIDATE"}:
            raise KernelError(
                "MKAOS_TARGET_LIFECYCLE_INVALID",
                "KnowledgePack target must be an addressable Active or Candidate version",
            )
        if result["eligibility"] not in {"ELIGIBLE", "PENDING_EVALUATION"} or result[
            "governance"
        ] != "CLEAR":
            raise KernelError(
                "MKAOS_TARGET_GOVERNANCE_INVALID",
                "KnowledgePack target must be clear and not ineligible or revoked",
            )
        return result

    def active_pack_for_target(
        self, *, project_id: str, target_asset_version_id: str
    ) -> dict[str, Any] | None:
        return self._existing(
            """
            SELECT pack.knowledge_pack_id, pack.asset_version_id,
                   pack.selection_hash, pack.created_by_operation_id,
                   operation.status
            FROM authority_mkaos_knowledge_pack AS pack
            JOIN authority_operation AS operation
              ON operation.operation_id = pack.created_by_operation_id
            WHERE pack.project_id = %s
              AND pack.target_asset_version_id = %s
              AND pack.status = 'ACTIVE'
            """,
            [project_id, target_asset_version_id],
            (
                "knowledge_pack_id",
                "asset_version_id",
                "selection_hash",
                "operation_id",
                "operation_status",
            ),
        )

    def knowledge_cards(
        self, *, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT card.asset_version_id, card.knowledge_card_id,
                   card.content_hash, card.status,
                   card.candidate_asset_version_id,
                   version.lifecycle, version.eligibility,
                   version.governance, version.content
            FROM authority_mkaos_knowledge_card AS card
            JOIN authority_asset_version AS version
              ON version.asset_version_id = card.asset_version_id
            WHERE card.project_id = %s
              AND card.asset_version_id = ANY(%s)
            ORDER BY card.asset_version_id
            FOR SHARE OF card, version
            """,
            [project_id, list(asset_version_ids)],
        )
        keys = (
            "asset_version_id",
            "knowledge_card_id",
            "content_hash",
            "status",
            "candidate_asset_version_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
        )
        return {
            str(row[0]): dict(zip(keys, row, strict=True))
            for row in self.cursor.fetchall()
        }

    def register_candidate(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_mkaos_knowledge_candidate (
                knowledge_candidate_id, project_id, workspace_id,
                asset_version_id, execution_asset_version_id,
                created_by_operation_id, candidate_hash,
                abstraction_policy_version, status
            ) VALUES (
                %(knowledge_candidate_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(execution_asset_version_id)s,
                %(created_by_operation_id)s, %(candidate_hash)s,
                %(abstraction_policy_version)s, 'NEEDS_REVIEW'
            )
            """,
            row,
        )

    def register_evidence_span(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_mkaos_evidence_span (
                evidence_span_id, project_id, candidate_asset_version_id,
                source_chunk_id, source_chunk_asset_version_id,
                chunk_byte_start, chunk_byte_end, evidence_hash,
                created_by_operation_id
            ) VALUES (
                %(evidence_span_id)s, %(project_id)s,
                %(candidate_asset_version_id)s, %(source_chunk_id)s,
                %(source_chunk_asset_version_id)s, %(chunk_byte_start)s,
                %(chunk_byte_end)s, %(evidence_hash)s,
                %(created_by_operation_id)s
            )
            """,
            row,
        )

    def register_decision(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_mkaos_governance_decision (
                governance_decision_id, project_id, workspace_id,
                asset_version_id, candidate_asset_version_id,
                created_by_operation_id, decision, reviewer_id,
                policy_version, rationale_hash
            ) VALUES (
                %(governance_decision_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(candidate_asset_version_id)s,
                %(created_by_operation_id)s, %(decision)s, %(reviewer_id)s,
                %(policy_version)s, %(rationale_hash)s
            )
            """,
            row,
        )

    def register_card(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_mkaos_knowledge_card (
                knowledge_card_id, project_id, workspace_id,
                asset_version_id, candidate_asset_version_id,
                governance_decision_asset_version_id,
                created_by_operation_id, content_hash, status
            ) VALUES (
                %(knowledge_card_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(candidate_asset_version_id)s,
                %(governance_decision_asset_version_id)s,
                %(created_by_operation_id)s, %(content_hash)s, 'ACTIVE'
            )
            """,
            row,
        )
        self.cursor.execute(
            """
            UPDATE authority_mkaos_knowledge_candidate
            SET status = 'APPROVED'
            WHERE asset_version_id = %(candidate_asset_version_id)s
              AND status = 'NEEDS_REVIEW'
            """,
            row,
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "MKAOS_CANDIDATE_STATUS_CONFLICT",
                "candidate is no longer awaiting governance review",
            )

    def register_pack(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_mkaos_knowledge_pack (
                knowledge_pack_id, project_id, workspace_id,
                asset_version_id, target_asset_version_id,
                created_by_operation_id, selector_policy_version,
                selector_policy_hash, selection_hash, item_count, status
            ) VALUES (
                %(knowledge_pack_id)s, %(project_id)s, %(workspace_id)s,
                %(asset_version_id)s, %(target_asset_version_id)s,
                %(created_by_operation_id)s, %(selector_policy_version)s,
                %(selector_policy_hash)s, %(selection_hash)s,
                %(item_count)s, 'ACTIVE'
            )
            """,
            row,
        )

    def register_pack_item(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_mkaos_knowledge_pack_item (
                knowledge_pack_id, knowledge_pack_asset_version_id,
                knowledge_card_asset_version_id, ordinal,
                usage_role, frozen_weight, created_by_operation_id
            ) VALUES (
                %(knowledge_pack_id)s, %(knowledge_pack_asset_version_id)s,
                %(knowledge_card_asset_version_id)s, %(ordinal)s,
                %(usage_role)s, %(frozen_weight)s,
                %(created_by_operation_id)s
            )
            """,
            row,
        )

    def existing_candidate(
        self, *, project_id: str, candidate_hash: str
    ) -> dict[str, Any] | None:
        return self._existing(
            """
            SELECT candidate.knowledge_candidate_id, candidate.asset_version_id,
                   candidate.created_by_operation_id, operation.status
            FROM authority_mkaos_knowledge_candidate AS candidate
            JOIN authority_operation AS operation
              ON operation.operation_id = candidate.created_by_operation_id
            WHERE candidate.project_id = %s AND candidate.candidate_hash = %s
            """,
            [project_id, candidate_hash],
            ("knowledge_candidate_id", "asset_version_id", "operation_id", "operation_status"),
        )

    def existing_approval(
        self, *, project_id: str, candidate_asset_version_id: str
    ) -> dict[str, Any] | None:
        return self._existing(
            """
            SELECT card.knowledge_card_id, card.asset_version_id,
                   card.governance_decision_asset_version_id,
                   card.created_by_operation_id, operation.status
            FROM authority_mkaos_knowledge_card AS card
            JOIN authority_operation AS operation
              ON operation.operation_id = card.created_by_operation_id
            WHERE card.project_id = %s
              AND card.candidate_asset_version_id = %s
            """,
            [project_id, candidate_asset_version_id],
            (
                "knowledge_card_id",
                "asset_version_id",
                "governance_decision_asset_version_id",
                "operation_id",
                "operation_status",
            ),
        )

    def existing_pack(
        self,
        *,
        project_id: str,
        target_asset_version_id: str,
        selection_hash: str,
    ) -> dict[str, Any] | None:
        return self._existing(
            """
            SELECT pack.knowledge_pack_id, pack.asset_version_id,
                   pack.created_by_operation_id, operation.status
            FROM authority_mkaos_knowledge_pack AS pack
            JOIN authority_operation AS operation
              ON operation.operation_id = pack.created_by_operation_id
            WHERE pack.project_id = %s
              AND pack.target_asset_version_id = %s
              AND pack.selection_hash = %s
            """,
            [project_id, target_asset_version_id, selection_hash],
            ("knowledge_pack_id", "asset_version_id", "operation_id", "operation_status"),
        )

    def _existing(
        self, sql: str, params: list[Any], keys: tuple[str, ...]
    ) -> dict[str, Any] | None:
        self.cursor.execute(sql, params)
        row = self.cursor.fetchone()
        return None if row is None else dict(zip(keys, row, strict=True))


__all__ = ["MkaosAuthorityRepository"]
