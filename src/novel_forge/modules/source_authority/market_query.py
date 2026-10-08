from __future__ import annotations
from datetime import datetime, timezone
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_market_records import SourceMarketRecords
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.modules.command_kernel.errors import KernelError
from .market import observation_status, rank_changes
from .market_application import require_market_current


def query_ranks(
    database: str,
    project: str,
    *,
    after: str = "",
    limit: int = 20,
    category: str = "",
    definition_id: str = "",
) -> dict:
    if not 1 <= limit <= 100 or category not in {
        "",
        "ALL",
        "XUANHUAN",
        "WUXIA",
        "XIANXIA",
    }:
        raise ValueError("Invalid market query range/category")
    with AuthorityUnitOfWork(database) as uow:
        records = SourceMarketRecords(uow.cursor)
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(project)
        definitions = (
            [records.definition(project, definition_id)]
            if definition_id
            else records.definitions(project, after, limit + 1, category)
        )
        items = []
        for definition in definitions[:limit]:
            valid = records.attempts(
                project, definition["definition_id"], limit=2, complete=True
            )
            recent = records.attempts(project, definition["definition_id"])
            status = "NOT_OBSERVED"
            eligible, reason = True, ""
            try:
                require_market_current(repository, records, project, definition)
            except KernelError as exc:
                eligible, reason, status = False, str(exc), "REVOKED"
            latest = valid[0] if valid else None
            if latest and eligible:
                status = observation_status(
                    latest["payload"],
                    definition["payload"]["definition"],
                    datetime.now(timezone.utc),
                )
            elif recent and eligible:
                status = recent[0]["status"]
            entries = []
            if latest and eligible:
                from .corpus import corpus_identity

                entries = [
                    {
                        **e,
                        "page": page["page"],
                        "book_source_id": corpus_identity(
                            "book", definition["source_id"], e["work_id"]
                        ),
                    }
                    for page in latest["payload"]["pages"]
                    for e in page["entries"]
                ]
            comparison = (
                rank_changes(
                    valid[1]["payload"],
                    valid[0]["payload"],
                    definition["payload"]["definition"],
                )
                if len(valid) == 2 and eligible
                else {
                    "comparable": False,
                    "changes": [],
                    "reason": "Two eligible complete snapshots required",
                }
            )
            items.append(
                {
                    "definition_id": definition["definition_id"],
                    "source_id": definition["source_id"],
                    "definition": definition["payload"]["definition"],
                    "use_scope": definition["payload"]["use_scope"],
                    "status": status,
                    "unavailable_reason": reason,
                    "last_valid_snapshot": latest
                    if eligible
                    else (
                        {
                            k: latest[k]
                            for k in (
                                "attempt_record_id",
                                "observed_at",
                                "acquired_at",
                                "status",
                            )
                        }
                        if latest
                        else None
                    ),
                    "latest_attempt": recent[0]
                    if recent and eligible
                    else (
                        {
                            k: recent[0][k]
                            for k in (
                                "attempt_record_id",
                                "observed_at",
                                "acquired_at",
                                "status",
                            )
                        }
                        if recent
                        else None
                    ),
                    "entries": entries,
                    "comparison": comparison,
                    "evidence_class": "MARKET_OBSERVATION_NOT_CAUSAL_OR_READER_EVIDENCE",
                    "generation_context_allowed": False,
                }
            )
        return {
            "items": items,
            "next_after": definitions[limit - 1]["definition_id"]
            if len(definitions) > limit
            else "",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "raw_response_retained": False,
        }


def query_market_work(database: str, project: str, book: str) -> dict:
    with AuthorityUnitOfWork(database) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(project)
        identity = repository.corpus_record("book_identity", project, book)
        records = SourceMarketRecords(uow.cursor)
        repository.cursor.execute(
            """SELECT to_jsonb(d) FROM authority_source_market_definition d
            WHERE d.project_id=%s AND d.source_id=%s AND NOT EXISTS (
                SELECT 1 FROM authority_source_market_definition n WHERE n.previous_definition_id=d.definition_id)""",
            [project, identity["source_id"]],
        )
        definitions = [row[0] for row in repository.cursor.fetchall()]
        valid = False
        for definition in definitions:
            try:
                require_market_current(repository, records, project, definition)
                valid = True
                break
            except KernelError:
                continue
        if not valid:
            return {
                "identity": {
                    key: identity[key] for key in ("source_id", "book_source_id")
                },
                "status": "REVOKED",
                "metadata_versions": [],
                "editions": [],
                "source_works": [],
                "knowledge_cards": [],
                "rights_requirements": "Source or current purpose rights changed; adjust the explicit reference",
            }
        data = records.work(project, book)
        repository.cursor.execute(
            """SELECT DISTINCT card.asset_version_id
            FROM authority_source_market_edition_link l
            JOIN authority_source_document d ON d.corpus_edition_id=l.edition_id AND d.project_id=l.project_id
            JOIN authority_source_chunk chunk ON chunk.source_document_id=d.source_document_id AND chunk.project_id=d.project_id
            JOIN authority_mkaos_evidence_span e ON e.source_chunk_id=chunk.source_chunk_id AND e.project_id=chunk.project_id
            JOIN authority_mkaos_knowledge_card card ON card.candidate_asset_version_id=e.candidate_asset_version_id AND card.project_id=e.project_id
            WHERE l.project_id=%s AND l.book_source_id=%s ORDER BY card.asset_version_id LIMIT 101""",
            [project, book],
        )
        card_ids = [r[0] for r in repository.cursor.fetchall()]
        repository.cursor.execute(
            """SELECT w.asset_version_id,w.corpus_edition_id,w.source_document_id,w.created_at
            FROM authority_source_work_version w JOIN authority_source_market_edition_link l ON l.edition_id=w.corpus_edition_id
            WHERE l.project_id=%s AND l.book_source_id=%s ORDER BY w.created_at DESC LIMIT 100""",
            [project, book],
        )
        works = [
            dict(
                zip(
                    (
                        "source_work_asset_version_id",
                        "edition_id",
                        "source_document_id",
                        "created_at",
                    ),
                    r,
                    strict=True,
                )
            )
            for r in repository.cursor.fetchall()
        ]
    from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery

    cards = (
        MkaosAuthorityQuery(database)._planning_cards(
            project_id=project, allowed_asset_version_ids=tuple(card_ids[:100])
        )
        if card_ids
        else []
    )
    available = [
        card
        for card in cards
        if card["lifecycle"] == "ACTIVE"
        and card["eligibility"] in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
        and card["governance"] == "CLEAR"
    ]
    unavailable = sorted(
        set(card_ids[:100]) - {card["asset_version_id"] for card in available}
    )
    return {
        "identity": identity,
        **data,
        "source_works": works,
        "knowledge_cards": available,
        "unavailable_card_asset_version_ids": unavailable,
        "card_scope_bounded": len(card_ids) > 100,
        "analysis_route": "/product/source-imports/corpus/jobs/{job_id}/reading-targets",
        "source_lineage_route": "/product/source-governance/corpus/lineage/{edition_id}",
        "knowledge_trace_route": "/product/mkaos/knowledge-cards/{asset_version_id}/trace",
        "rights_requirements": "Text/cloud analysis/abstract use require their own current Corpus rights; rank metadata grants none",
    }
