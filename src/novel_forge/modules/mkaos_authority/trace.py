from __future__ import annotations

from typing import Any

from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.review.knowledge import knowledge_review_targets
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .query import MkaosAuthorityQuery


def workspace_knowledge_trace(workspace: dict[str, Any]) -> dict[str, Any]:
    artifacts = workspace["artifacts"]
    selected: dict[str, list[dict[str, Any]]] = {}
    for context in artifacts.get("inputs", []):
        for item in knowledge_review_targets(context["content"]):
            identity = str(item["knowledge_card_asset_version_id"])
            selected.setdefault(identity, []).append({
                **item, "context_bundle_asset_version_id": context["asset_version_id"],
            })
    reviews: dict[str, list[dict[str, Any]]] = {}
    for review in artifacts.get("diagnoses", []):
        for check in review["content"].get("knowledge_checks", []):
            reviews.setdefault(check["knowledge_card_asset_version_id"], []).append({
                **check, "review_asset_version_id": review["asset_version_id"],
            })
    accepted: dict[str, Any] = {}
    if (workspace.get("acceptance") or {}).get("status") == "COMMITTED":
        bound = resolve_accepted_manuscript(workspace)
        for check in bound["review"]["content"].get("knowledge_checks", []):
            if check["target_text_hash"] != prose_hash(bound["candidate"]["content"]["text"]):
                raise KernelError("MKAOS_TRACE_PROSE_MISMATCH", "knowledge review differs from accepted prose")
            accepted[check["knowledge_card_asset_version_id"]] = {
                "check": check, "acceptance_id": workspace["acceptance"]["acceptance_id"],
                "candidate_asset_version_id": bound["candidate"]["asset_version_id"],
                "review_asset_version_id": bound["review"]["asset_version_id"],
                "outcome_asset_version_id": bound["outcome"]["asset_version_id"],
                "next_input_state": {
                    key: workspace["acceptance"][key]
                    for key in ("story_state_asset_version_id", "canon_snapshot_asset_version_id")
                },
            }
    return {
        "contract_version": "knowledge-prose-trace.v1", "authority": "READ_ONLY_PROJECTION",
        "project_id": workspace["project_id"], "book_id": workspace.get("book_id", ""),
        "chapter_root_operation_id": workspace["root_operation_id"],
        "cards": [{
            "knowledge_card_asset_version_id": identity,
            "selected": selected.get(identity, []), "candidate_checks": reviews.get(identity, []),
            "accepted": accepted.get(identity),
            "independent_editorial": "NOT_PROVEN",
            "delivery_evidence": "QUERY_RUNTIME_USAGE_RECEIPTS",
            "writer_claim": "NOT_INFERRED_FROM_FACT_IDS",
        } for identity in sorted(set(selected) | set(reviews) | set(accepted))],
    }


def require_knowledge_trace(
    database_url: str, *, project_id: str, knowledge_card_asset_version_id: str,
    book_id: str = "", limit: int = 50,
) -> dict[str, Any]:
    if not 1 <= limit <= 50:
        raise ValueError("knowledge trace limit must be 1..50")
    card = AuthorityAssetQuery(database_url).require(
        project_id=project_id, asset_version_id=knowledge_card_asset_version_id,
    )
    if card.asset_type != "knowledge_card":
        raise KernelError("MKAOS_TRACE_CARD_REQUIRED", "trace requires an exact KnowledgeCard version")
    query = MkaosAuthorityQuery(database_url)
    filters = dict(project_id=project_id, book_id=book_id, limit=limit,
                   knowledge_card_asset_version_id=knowledge_card_asset_version_id)
    planning = query.list_planning_usage(**filters)
    delivery = query.list_runtime_usage(**filters)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT DISTINCT operation.root_operation_id
            FROM authority_operation operation
            JOIN authority_book_chapter_request request
              ON request.chapter_root_operation_id=operation.root_operation_id
             AND request.project_id=operation.project_id
            WHERE operation.project_id=%s AND operation.operation_id=ANY(%s)
            ORDER BY operation.root_operation_id
            """, [project_id, [row["consumer_operation_id"] for row in delivery]],
        )
        roots = [row[0] for row in uow.cursor.fetchall()]
    chapters = ChapterAuthorityQuery(database_url)
    prose = [workspace_knowledge_trace(chapters.require_workspace(
        project_id=project_id, root_operation_id=root,
    )) for root in roots]
    for chapter in prose:
        chapter["cards"] = [item for item in chapter["cards"]
                            if item["knowledge_card_asset_version_id"] == knowledge_card_asset_version_id]
    return {
        "contract_version": "knowledge-creative-trace.v1", "authority": "READ_ONLY_PROJECTION",
        "project_id": project_id, "book_id": book_id,
        "knowledge_card_asset_version_id": card.asset_version_id, "content_hash": card.content_hash,
        "source_lineage": card.content.get("lineage", {}),
        "planning": planning, "delivered_requests": delivery, "prose": prose,
        "bounded": len(planning) == limit or len(delivery) == limit,
        "limit": limit, "independent_editorial": "NOT_PROVEN",
    }
