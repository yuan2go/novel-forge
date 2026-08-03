"""Strong PostgreSQL queries for MKAOS Candidate/Decision/Card/Pack assets."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class MkaosAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def list_candidates(
        self, *, project_id: str, status: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT candidate.knowledge_candidate_id, candidate.project_id,
                       candidate.workspace_id, candidate.asset_version_id,
                       candidate.execution_asset_version_id,
                       candidate.candidate_hash,
                       candidate.abstraction_policy_version, candidate.status,
                       candidate.created_by_operation_id,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, candidate.created_at
                FROM authority_mkaos_knowledge_candidate AS candidate
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = candidate.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = candidate.created_by_operation_id
                WHERE candidate.project_id = %s
                  AND (%s = '' OR candidate.status = %s)
                ORDER BY candidate.created_at DESC,
                         candidate.knowledge_candidate_id
                LIMIT %s
                """,
                [project_id, status, status, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "knowledge_candidate_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "execution_asset_version_id",
            "candidate_hash",
            "abstraction_policy_version",
            "candidate_status",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_cards(
        self, *, project_id: str, status: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT card.knowledge_card_id, card.project_id,
                       card.workspace_id, card.asset_version_id,
                       card.candidate_asset_version_id,
                       card.governance_decision_asset_version_id,
                       card.created_by_operation_id, card.content_hash,
                       card.status, version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, card.created_at
                FROM authority_mkaos_knowledge_card AS card
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = card.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = card.created_by_operation_id
                WHERE card.project_id = %s
                  AND (%s = '' OR card.status = %s)
                ORDER BY card.created_at DESC, card.knowledge_card_id
                LIMIT %s
                """,
                [project_id, status, status, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "knowledge_card_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "candidate_asset_version_id",
            "governance_decision_asset_version_id",
            "created_by_operation_id",
            "content_hash",
            "card_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_packs(
        self,
        *,
        project_id: str,
        target_asset_version_id: str = "",
        knowledge_pack_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pack.knowledge_pack_id, pack.project_id,
                       pack.workspace_id, pack.asset_version_id,
                       pack.target_asset_version_id,
                       pack.created_by_operation_id,
                       pack.selector_policy_version,
                       pack.selector_policy_hash, pack.selection_hash,
                       pack.item_count, pack.status,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, pack.created_at
                FROM authority_mkaos_knowledge_pack AS pack
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = pack.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = pack.created_by_operation_id
                WHERE pack.project_id = %s
                  AND (%s = '' OR pack.target_asset_version_id = %s)
                  AND (%s = '' OR pack.knowledge_pack_id = %s)
                ORDER BY pack.created_at DESC, pack.knowledge_pack_id
                LIMIT %s
                """,
                [
                    project_id,
                    target_asset_version_id,
                    target_asset_version_id,
                    knowledge_pack_id,
                    knowledge_pack_id,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "knowledge_pack_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "target_asset_version_id",
            "created_by_operation_id",
            "selector_policy_version",
            "selector_policy_hash",
            "selection_hash",
            "item_count",
            "pack_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def require_pack(
        self, *, project_id: str, knowledge_pack_id: str
    ) -> dict[str, Any]:
        if not knowledge_pack_id:
            raise ValueError("knowledge_pack_id is required")
        matches = self.list_packs(
            project_id=project_id,
            knowledge_pack_id=knowledge_pack_id,
            limit=1,
        )
        if not matches:
            raise KernelError(
                "MKAOS_PACK_NOT_FOUND", "KnowledgePack does not exist in project"
            )
        return matches[0]


def _validate(project_id: str, limit: int) -> None:
    if not project_id or limit < 1 or limit > 500:
        raise ValueError("project_id and a limit between 1 and 500 are required")


__all__ = ["MkaosAuthorityQuery"]
