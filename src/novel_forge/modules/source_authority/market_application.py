from __future__ import annotations
from datetime import datetime, timezone
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.source_market_records import SourceMarketRecords
from .market import DefineMarketRank, ObserveMarketRank, LinkMarketEdition, UseScope
from .corpus import (
    corpus_hash,
    corpus_identity,
    RightsDeclaration,
    CorpusPurpose,
    corpus_admission,
    effective_work_rights,
)


def require_market_current(
    repository, records, project: str, definition: dict, *, now=None
) -> None:
    payload = definition["payload"]
    source = repository.corpus_source_lock(project, definition["source_id"])
    if (
        source["retired"]
        or records.current(project, definition["rank_key"])["definition_id"]
        != definition["definition_id"]
    ):
        raise KernelError(
            "MARKET_REFERENCE_INVALIDATED",
            "Source retired or definition superseded; adjust the explicit reference",
        )
    rights_id = repository.corpus_latest("rights", project, source["source_id"])
    if rights_id != payload["rights_id"]:
        raise KernelError(
            "MARKET_RIGHTS_CHANGED",
            "Inspect current rights before acquiring or using old metadata",
        )
    rights = RightsDeclaration.model_validate(
        repository.corpus_record("rights", project, rights_id)["declaration"]
    )
    allowed = corpus_admission(
        rights=rights,
        source_purpose=CorpusPurpose(source["purpose"]),
        requested_purpose=CorpusPurpose.MARKET_INTELLIGENCE,
        retired=False,
        rights_current=True,
    )
    if allowed["decision"] != "ALLOW":
        raise KernelError(
            "MARKET_USE_NOT_AUTHORIZED",
            "Corpus rights do not permit market intelligence",
        )
    try:
        UseScope.model_validate(payload["use_scope"]).require_metadata(
            now or datetime.now(timezone.utc)
        )
    except ValueError as exc:
        raise KernelError("MARKET_USE_NOT_AUTHORIZED", str(exc)) from exc


def apply_market_action(
    repository,
    action,
    *,
    project_id: str,
    workspace_id: str,
    operation_id: str,
    asset_version_id: str = "",
) -> dict:
    repository.corpus_authorization_lock(project_id, write=True)
    source = repository.corpus_source_lock(project_id, action.source_id)
    if source["workspace_id"] != workspace_id:
        raise KernelError(
            "CORPUS_WORKSPACE_INVALID", "Market source belongs to another workspace"
        )
    records = SourceMarketRecords(repository.cursor)
    version = asset_version_id or corpus_identity("result", operation_id) + ":v1"
    payload = action.model_dump(mode="json")
    common = {"project_id": project_id, "created_by_operation_id": operation_id}
    if isinstance(action, DefineMarketRank):
        records.platform(project_id, action.source_id)
        key = corpus_hash(
            [
                action.definition.key,
                action.definition.category,
                action.definition.period,
            ]
        )
        rights_id = repository.corpus_latest("rights", project_id, action.source_id)
        if not rights_id:
            raise KernelError(
                "MARKET_RIGHTS_REQUIRED",
                "Declare explicit Corpus rights before rank definitions",
            )
        payload["rights_id"] = rights_id
        identity = corpus_identity("market-definition", project_id, payload)
        current = records.current(project_id, key)
        if not current or current["definition_id"] != identity:
            if (
                current["definition_id"] if current else ""
            ) != action.previous_definition_id:
                raise KernelError(
                    "MARKET_DEFINITION_STALE",
                    "Revision must bind the current exact definition",
                )
        row = {
            **common,
            "source_id": action.source_id,
            "definition_id": identity,
            "rank_key": key,
            "previous_definition_id": action.previous_definition_id or None,
            "asset_version_id": version,
            "payload": payload,
        }
        if action.definition.update.enabled:
            if source["retired"]:
                raise KernelError("MARKET_REFERENCE_INVALIDATED", "Source retired")
            action.use_scope.require_metadata(datetime.now(timezone.utc))
        if action.resume_access:
            if (
                not action.definition.update.enabled
                or action.definition.support != "VERIFIED"
            ):
                raise KernelError(
                    "MARKET_ACCESS_REVIEW_REQUIRED",
                    "Resume requires a newly reviewed enabled official definition",
                )
            repository.cursor.execute(
                "SELECT stopped_at,blocked_until FROM authority_source_market_site WHERE host='www.qidian.com' FOR UPDATE"
            )
            stopped = repository.cursor.fetchone()
            if stopped and stopped[1] and stopped[1] > datetime.now(timezone.utc):
                raise KernelError(
                    "MARKET_RETRY_AFTER_ACTIVE", "Retained Retry-After has not elapsed"
                )
            if stopped and stopped[0] and action.use_scope.reviewed_at <= stopped[0]:
                raise KernelError(
                    "MARKET_ACCESS_REVIEW_REQUIRED",
                    "Access rules must be reviewed after the retained stop",
                )
            repository.cursor.execute(
                "UPDATE authority_source_market_site SET stopped_reason='',blocked_until=NULL WHERE host='www.qidian.com'"
            )
        records.insert_definition(row)
        return {
            "source_id": action.source_id,
            "definition_id": identity,
            "definition": payload,
        }
    if isinstance(action, LinkMarketEdition):
        book = repository.corpus_record(
            "book_identity", project_id, action.book_source_id
        )
        edition = repository.corpus_record("edition", project_id, action.edition_id)
        if book["source_id"] != action.source_id or source["retired"]:
            raise KernelError(
                "MARKET_LINK_INVALID", "Exact current platform book identity required"
            )
        snapshot = repository.corpus_record(
            "snapshot", project_id, edition["snapshot_id"]
        )
        text_book = repository.corpus_record(
            "book_identity", project_id, edition["book_source_id"]
        )
        declaration = RightsDeclaration.model_validate(
            repository.corpus_record("rights", project_id, snapshot["rights_id"])[
                "declaration"
            ]
        )
        if not effective_work_rights(
            declaration, text_book["external_work_id"]
        ).use_scope:
            raise KernelError(
                "MARKET_TEXT_USE_SCOPE_REQUIRED",
                "Declare separate text acquisition, storage, analysis, cloud, abstraction and training scopes before linking",
            )
        records.link(
            project_id,
            action.source_id,
            action.book_source_id,
            edition["edition_id"],
            action.evidence_ref,
            operation_id,
        )
        return {
            "source_id": action.source_id,
            "book_source_id": action.book_source_id,
            "edition_id": action.edition_id,
        }
    if not isinstance(action, ObserveMarketRank):
        raise ValueError("unsupported market action")
    if action.acquisition == "OFFICIAL_PUBLIC_PAGE":
        repository.cursor.execute(
            """SELECT d.evidence FROM authority_external_effect e
            JOIN authority_operation o ON o.operation_id=e.operation_id
            JOIN authority_operation child ON child.operation_id=%s AND child.parent_operation_id=o.operation_id
            JOIN authority_external_effect_dispatch d ON d.external_effect_id=e.external_effect_id
            WHERE o.project_id=%s AND o.operation_id=%s AND o.definition_name='source.import.market.refresh'
            AND e.status='SUCCEEDED' AND e.stable_idempotency_key=%s ORDER BY d.generation DESC LIMIT 1""",
            [operation_id, project_id, action.fetch_operation_id, action.receipt_ref],
        )
        receipt = repository.cursor.fetchone()
        if not receipt or receipt[0].get("observation") != payload:
            raise KernelError(
                "MARKET_NATIVE_RECEIPT_REQUIRED",
                "Official observations require the exact successful parent fetch receipt",
            )
    definition = records.definition(project_id, action.definition_id)
    if definition["source_id"] != action.source_id:
        raise KernelError(
            "MARKET_SOURCE_MISMATCH", "Observation changed platform Source"
        )
    if action.acquired_at > datetime.now(timezone.utc):
        raise KernelError("MARKET_TIME_INVALID", "Acquisition time is in the future")
    if action.status in {"COMPLETE", "PARTIAL", "NOT_MODIFIED"}:
        require_market_current(repository, records, project_id, definition)
        if definition["payload"]["definition"]["support"] != "VERIFIED":
            raise KernelError(
                "MARKET_DEFINITION_UNVERIFIED",
                "Official name/filter/period must be evidenced before importing ranks",
            )
    if action.status == "NOT_MODIFIED" and not records.attempts(
        project_id, action.definition_id, complete=True
    ):
        raise KernelError(
            "MARKET_CONDITIONAL_BASE_MISSING", "304 needs an existing valid snapshot"
        )
    snapshot_id = corpus_identity("market-observation", project_id, payload)
    entries = []
    for page in action.pages:
        for item in page.entries:
            book_id = corpus_identity("book", action.source_id, item.work_id)
            repository.corpus_insert(
                "book_identity",
                {
                    **common,
                    "source_id": action.source_id,
                    "book_source_id": book_id,
                    "external_work_id": item.work_id,
                },
            )
            data = item.model_dump(
                mode="json", exclude={"rank", "public_metrics", "field_sources"}
            )
            digest = corpus_hash(data)
            metadata_id = corpus_identity("market-metadata", book_id, digest)
            records.insert_metadata(
                {
                    **common,
                    "source_id": action.source_id,
                    "book_source_id": book_id,
                    "metadata_id": metadata_id,
                    "content_hash": digest,
                    "payload": data,
                }
            )
            entries.append(
                {
                    **item.model_dump(mode="json"),
                    "book_source_id": book_id,
                    "metadata_id": metadata_id,
                    "page": page.page,
                }
            )
    records.insert_attempt(
        {
            **common,
            "attempt_record_id": snapshot_id,
            "definition_id": action.definition_id,
            "asset_version_id": version,
            "status": action.status,
            "observed_at": action.observed_at,
            "acquired_at": action.acquired_at,
            "payload": payload,
        }
    )
    return {
        "source_id": action.source_id,
        "definition_id": action.definition_id,
        "attempt_record_id": snapshot_id,
        "snapshot_id": snapshot_id
        if action.status in {"COMPLETE", "PARTIAL"}
        else None,
        "observation": payload,
        "entries": entries,
        "generation_context_allowed": False,
    }
