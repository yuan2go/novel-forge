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

    def diff_packs(
        self,
        *,
        project_id: str,
        knowledge_pack_id: str,
        against_knowledge_pack_id: str,
    ) -> dict[str, Any]:
        current = self.require_pack(
            project_id=project_id, knowledge_pack_id=knowledge_pack_id
        )
        baseline = self.require_pack(
            project_id=project_id, knowledge_pack_id=against_knowledge_pack_id
        )
        current_items = _pack_items(current)
        baseline_items = _pack_items(baseline)
        added = sorted(set(current_items) - set(baseline_items))
        removed = sorted(set(baseline_items) - set(current_items))
        changed = sorted(
            identity
            for identity in set(current_items) & set(baseline_items)
            if current_items[identity] != baseline_items[identity]
        )
        unchanged = sorted(
            identity
            for identity in set(current_items) & set(baseline_items)
            if current_items[identity] == baseline_items[identity]
        )
        current_lineage = dict(current["content"].get("lineage") or {})
        baseline_lineage = dict(baseline["content"].get("lineage") or {})
        return {
            "schema_version": "mkaos-knowledge-pack-diff.v1",
            "project_id": project_id,
            "knowledge_pack_id": knowledge_pack_id,
            "against_knowledge_pack_id": against_knowledge_pack_id,
            "target_changed": (
                current["target_asset_version_id"]
                != baseline["target_asset_version_id"]
            ),
            "selector_policy_changed": (
                current["selector_policy_version"]
                != baseline["selector_policy_version"]
                or current["selector_policy_hash"] != baseline["selector_policy_hash"]
            ),
            "directly_supersedes_baseline": (
                current_lineage.get("supersedes_pack_asset_version_id")
                == baseline["asset_version_id"]
            ),
            "baseline_directly_supersedes_current": (
                baseline_lineage.get("supersedes_pack_asset_version_id")
                == current["asset_version_id"]
            ),
            "added": [current_items[identity] for identity in added],
            "removed": [baseline_items[identity] for identity in removed],
            "changed": [
                {
                    "knowledge_card_asset_version_id": identity,
                    "before": baseline_items[identity],
                    "after": current_items[identity],
                }
                for identity in changed
            ],
            "unchanged_count": len(unchanged),
        }

    def list_runtime_usage(
        self,
        *,
        project_id: str,
        book_id: str = "",
        target_capability_id: str = "",
        result_asset_version_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Trace cards through a frozen Context and successful Provider effect."""
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, book_id,
                       context_bundle_asset_version_id,
                       context_build_operation_id,
                       consumer_operation_id,
                       consumer_definition_name,
                       attempt_id, external_effect_id, provider, model_id,
                       provider_request_id, capability_id,
                       capability_pack_snapshot_id,
                       capability_pack_id, capability_pack_version,
                       result_asset_version_id, result_asset_type,
                       target_capability_id, narrative_position, trace_id,
                       knowledge_pack_id,
                       knowledge_pack_asset_version_id,
                       knowledge_card_asset_version_id,
                       usage_role, frozen_weight,
                       inclusion_reason, narrative_function, consumed_at
                FROM authority_mkaos_runtime_usage_projection
                WHERE project_id=%s
                  AND (%s='' OR book_id=%s)
                  AND (%s='' OR target_capability_id=%s)
                  AND (%s='' OR result_asset_version_id=%s)
                ORDER BY consumed_at DESC, context_bundle_asset_version_id,
                         knowledge_pack_id, knowledge_card_asset_version_id
                LIMIT %s
                """,
                [
                    project_id,
                    book_id,
                    book_id,
                    target_capability_id,
                    target_capability_id,
                    result_asset_version_id,
                    result_asset_version_id,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "project_id",
            "book_id",
            "context_bundle_asset_version_id",
            "context_build_operation_id",
            "consumer_operation_id",
            "consumer_definition_name",
            "attempt_id",
            "external_effect_id",
            "provider",
            "model_id",
            "provider_request_id",
            "capability_id",
            "capability_pack_snapshot_id",
            "capability_pack_id",
            "capability_pack_version",
            "result_asset_version_id",
            "result_asset_type",
            "target_capability_id",
            "narrative_position",
            "trace_id",
            "knowledge_pack_id",
            "knowledge_pack_asset_version_id",
            "knowledge_card_asset_version_id",
            "usage_role",
            "frozen_weight",
            "inclusion_reason",
            "narrative_function",
            "consumed_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_runtime_selections(
        self,
        *,
        project_id: str,
        book_id: str = "",
        target_capability_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List Context-frozen selections without claiming Provider consumption."""
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, book_id,
                       context_bundle_asset_version_id,
                       context_build_operation_id, trace_id,
                       target_capability_id, narrative_position,
                       knowledge_pack_id,
                       knowledge_pack_asset_version_id,
                       knowledge_card_asset_version_id,
                       usage_role, frozen_weight,
                       inclusion_reason, narrative_function, selected_at
                FROM authority_mkaos_runtime_selection_projection
                WHERE project_id=%s
                  AND (%s='' OR book_id=%s)
                  AND (%s='' OR target_capability_id=%s)
                ORDER BY selected_at DESC, context_bundle_asset_version_id,
                         knowledge_pack_id, knowledge_card_asset_version_id
                LIMIT %s
                """,
                [
                    project_id,
                    book_id,
                    book_id,
                    target_capability_id,
                    target_capability_id,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "project_id",
            "book_id",
            "context_bundle_asset_version_id",
            "context_build_operation_id",
            "trace_id",
            "target_capability_id",
            "narrative_position",
            "knowledge_pack_id",
            "knowledge_pack_asset_version_id",
            "knowledge_card_asset_version_id",
            "usage_role",
            "frozen_weight",
            "inclusion_reason",
            "narrative_function",
            "selected_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]


def _validate(project_id: str, limit: int) -> None:
    if not project_id or limit < 1 or limit > 500:
        raise ValueError("project_id and a limit between 1 and 500 are required")


def _pack_items(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    content = dict(pack.get("content") or {})
    items = content.get("items")
    if not isinstance(items, list):
        raise KernelError(
            "MKAOS_PACK_CONTENT_INVALID",
            "KnowledgePack does not expose its immutable item composition",
        )
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise KernelError(
                "MKAOS_PACK_CONTENT_INVALID",
                "KnowledgePack item composition is malformed",
            )
        identity = str(item.get("knowledge_card_asset_version_id") or "")
        if not identity or identity in result:
            raise KernelError(
                "MKAOS_PACK_CONTENT_INVALID",
                "KnowledgePack item identities are incomplete or duplicated",
            )
        result[identity] = {
            "knowledge_card_asset_version_id": identity,
            "content_hash": str(item.get("content_hash") or ""),
            "usage_role": str(item.get("usage_role") or ""),
            "frozen_weight": str(item.get("frozen_weight") or ""),
            "ordinal": int(item.get("ordinal") or 0),
        }
    return result


__all__ = ["MkaosAuthorityQuery"]
