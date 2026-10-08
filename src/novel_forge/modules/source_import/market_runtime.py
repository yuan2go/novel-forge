from __future__ import annotations
from datetime import datetime, timezone
import time
from typing import Any

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import corpus_hash, corpus_identity
from novel_forge.modules.source_authority.market import (
    MarketContract,
    Text,
    ObserveMarketRank,
)
from novel_forge.modules.source_authority.market_application import (
    require_market_current,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_market_records import SourceMarketRecords
from .market_adapter import QidianRankAdapter

OPERATION = "source.import.market.refresh"
OUTPUT = "source.market.record"


class MarketRefreshRequest(MarketContract):
    project_id: Text
    workspace_id: Text
    definition_id: Text
    run_key: Text
    period_value: Text


def admit_market_refresh(
    app: Any, request: MarketRefreshRequest, principal=None
) -> dict:
    if principal:
        principal.require("source.authority.execute", request.project_id)
    actor = principal.principal_id if principal else app.worker_id
    app._register_definitions()
    key = "market-refresh:" + corpus_hash(
        [request.project_id, request.workspace_id, request.run_key]
    )
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        sources = SourceAuthorityRepository(uow.cursor)
        sources.require_scope(
            project_id=request.project_id, workspace_id=request.workspace_id
        )
        sources.corpus_authorization_lock(request.project_id)
        records = SourceMarketRecords(uow.cursor)
        uow.cursor.execute(
            "SELECT operation_id,command_payload->'payload'->'requested_manifest' FROM authority_operation WHERE project_id=%s AND workspace_id=%s AND definition_name=%s AND idempotency_key=%s",
            [request.project_id, request.workspace_id, OPERATION, key],
        )
        previous_request = uow.cursor.fetchone()
        if previous_request:
            if previous_request[1] != request.model_dump(mode="json"):
                raise KernelError(
                    "IDEMPOTENCY_PAYLOAD_CONFLICT",
                    "Market run key binds different inputs",
                )
            return {
                "operation_id": previous_request[0],
                "project_id": request.project_id,
                "replayed": True,
            }
        uow.cursor.execute(
            """SELECT operation_id,status FROM authority_operation
            WHERE project_id=%s AND definition_name=%s
            AND command_payload->'payload'->>'definition_id'=%s
            AND status NOT IN ('SUCCEEDED','FAILED_FINAL','DEAD_LETTER','CANCELLED')
            ORDER BY created_at LIMIT 1""",
            [request.project_id, OPERATION, request.definition_id],
        )
        active = uow.cursor.fetchone()
        if active:
            raise KernelError(
                "MARKET_REFRESH_ACTIVE",
                "Recover the original Operation: "
                + str(active[0])
                + "; state: "
                + str(active[1]),
            )
        definition = records.definition(request.project_id, request.definition_id)
        source = sources.corpus_record(
            "source", request.project_id, definition["source_id"]
        )
        if source["workspace_id"] != request.workspace_id:
            raise KernelError(
                "CORPUS_WORKSPACE_INVALID", "Rank source belongs to another workspace"
            )
        require_market_current(sources, records, request.project_id, definition)
        details = definition["payload"]
        if details["definition"]["support"] != "VERIFIED":
            raise KernelError(
                "MARKET_DEFINITION_UNVERIFIED",
                "Verify official navigation before refreshing",
            )
        previous = records.attempts(
            request.project_id, request.definition_id, complete=True
        )
        payload = {
            "requested_manifest": request.model_dump(mode="json"),
            "source_id": definition["source_id"],
            "definition_id": request.definition_id,
            "period_value": request.period_value,
            "definition": details["definition"],
            "use_scope": details["use_scope"],
            "etag": previous[0]["payload"]["etag"] if previous else "",
            "last_modified": previous[0]["payload"]["last_modified"]
            if previous
            else "",
        }
        admitted = app._admit_child(
            definition_name=OPERATION,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            actor_id=actor,
            idempotency_key=key,
            trace_id=key,
            correlation_id=key,
            causation_id=definition["created_by_operation_id"],
            parent_operation_id=definition["created_by_operation_id"],
            payload=payload,
            input_assets=(),
            ready=True,
        )
        uow.commit()
    return {"operation_id": admitted, "project_id": request.project_id}


def site_slot(database: str, interval: int) -> None:
    with AuthorityUnitOfWork(database) as uow:
        uow.cursor.execute("""INSERT INTO authority_source_market_site(host,next_request_at)
            VALUES ('www.qidian.com',NOW()) ON CONFLICT(host) DO NOTHING""")
        uow.cursor.execute(
            "SELECT next_request_at,stopped_reason,blocked_until FROM authority_source_market_site WHERE host='www.qidian.com' FOR UPDATE"
        )
        next_at, stopped, blocked = uow.cursor.fetchone()
        now = datetime.now(timezone.utc)
        if stopped and (blocked is None or blocked > now):
            raise KernelError("MARKET_SITE_STOPPED", stopped)
        wait = max(0, (next_at - now).total_seconds())
        if wait > 60:
            raise KernelError(
                "MARKET_SITE_BACKOFF",
                "Retry-After/site slot exceeds this attempt; do not busy retry",
            )
        uow.cursor.execute(
            "UPDATE authority_source_market_site SET next_request_at=GREATEST(next_request_at,NOW())+%s*interval '1 second' WHERE host='www.qidian.com'",
            [interval],
        )
        uow.commit()
    if wait:
        time.sleep(wait)


def stop_site(database: str, status: str, delay: float) -> None:
    with AuthorityUnitOfWork(database) as uow:
        uow.cursor.execute(
            """UPDATE authority_source_market_site SET stopped_reason=%s,stopped_at=NOW(),
            blocked_until=CASE WHEN %s='RATE_LIMITED' THEN GREATEST(blocked_until,NOW()+%s*interval '1 second') ELSE NULL END
            WHERE host='www.qidian.com'""",
            [status, status, max(60, delay)],
        )
        uow.commit()


def market_adapter(app: Any) -> QidianRankAdapter:
    adapter = getattr(app, "market_adapter", None)
    if adapter is None:
        adapter = QidianRankAdapter(
            site_slot=lambda interval: site_slot(app.database_url, interval),
            stop_site=lambda status, delay: stop_site(app.database_url, status, delay),
        )
        app.market_adapter = adapter
    return adapter


def execute_market_refresh(app: Any, worker: Any) -> dict:
    with AuthorityUnitOfWork(app.database_url) as uow:
        require_current_fence(uow, worker)
        sources = SourceAuthorityRepository(uow.cursor)
        uow.cursor.execute(
            "SELECT command_payload FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [worker.causation_id, worker.project_id],
        )
        command = uow.cursor.fetchone()[0]
        uow.cursor.execute(
            "SELECT v.content,v.asset_version_id FROM authority_operation_output_asset a JOIN authority_asset_version v USING(asset_version_id) WHERE a.operation_id=%s AND a.output_key=%s",
            [worker.causation_id, OUTPUT],
        )
        row = uow.cursor.fetchone()
        existing = {**row[0], "asset_version_id": row[1]} if row else {}
        if existing:
            return existing
        records = SourceMarketRecords(uow.cursor)
        definition = records.definition(
            worker.project_id, command["payload"]["definition_id"]
        )
        require_market_current(sources, records, worker.project_id, definition)
    payload = command["payload"]
    result = app._execute_external_effect(
        worker=worker,
        effect_type="SOURCE_MARKET_FETCH",
        capability="source.remote.fetch",
        stable_key=f"market-fetch:{worker.causation_id}",
        request_payload=payload,
        adapter=market_adapter(app),
        max_attempts=1,
        timeout_seconds=payload["definition"]["update"]["timeout_seconds"],
        pre_send_assertion=lambda: assert_market_current(
            app, worker.project_id, payload["definition_id"]
        ),
    )
    observation = ObserveMarketRank.model_validate(result["observation"])
    from .corpus_ingestion.runtime import CorpusIngestionRuntime

    committed = CorpusIngestionRuntime(app)._corpus(
        worker,
        {"workspace_id": command["workspace_id"]},
        observation.model_dump(mode="json"),
    )
    with AuthorityUnitOfWork(app.database_url) as uow:
        require_current_fence(uow, worker)
        sources = SourceAuthorityRepository(uow.cursor)
        sources.corpus_authorization_lock(worker.project_id, write=True)
        version = corpus_identity("market-result", worker.causation_id) + ":v1"
        content = {
            "schema_version": "source-market-result.v1",
            **committed,
            "corpus_output_asset_version_id": committed["asset_version_id"],
            "raw_response_retained": False,
        }
        uow.repositories.chapter_authority.materialize_output(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            asset_id=version.removesuffix(":v1"),
            asset_version_id=version,
            qualification_id=version + ":contract",
            asset_type="corpus_record",
            output_key=OUTPUT,
            role="evidence",
            content=content,
            content_hash=corpus_hash(content),
            qualification_policy="source-market-observation.v1",
            qualification_evidence={
                "attempt_id": worker.attempt_id,
                "fencing_token": worker.fencing_token,
                "generation_context_allowed": False,
            },
            lifecycle="ACTIVE",
            eligibility="INELIGIBLE",
            governance="CLEAR",
        )
        app._record_event(
            uow,
            worker,
            aggregate_type="authority_corpus_source",
            aggregate_id=observation.source_id,
            event_type="authority.source.market.observed",
            payload={"asset_version_id": version, "status": observation.status},
        )
        uow.commit()
    return {**content, "asset_version_id": version}


def assert_market_current(app, project: str, identity: str) -> None:
    with AuthorityUnitOfWork(app.database_url) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(project)
        records = SourceMarketRecords(uow.cursor)
        require_market_current(
            repository, records, project, records.definition(project, identity)
        )


def market_result(app, operation: str, project: str) -> dict:
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute(
            """SELECT v.content,v.asset_version_id FROM authority_operation_output_asset a
            JOIN authority_asset_version v USING(asset_version_id) JOIN authority_operation o USING(operation_id)
            WHERE a.operation_id=%s AND o.project_id=%s AND a.output_key=%s""",
            [operation, project, OUTPUT],
        )
        row = uow.cursor.fetchone()
        return {**row[0], "asset_version_id": row[1]} if row else {}


def enqueue_market_updates(app, *, limit: int = 20) -> list[dict]:
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute(
            """SELECT d.project_id,s.workspace_id,d.definition_id,d.payload,
            (extract(epoch FROM NOW())::bigint / (d.payload#>>'{definition,update,interval_seconds}')::bigint)::text
            FROM authority_source_market_definition d JOIN authority_corpus_source s USING(project_id,source_id)
            LEFT JOIN LATERAL (SELECT status,acquired_at FROM authority_source_market_attempt a
                WHERE a.project_id=d.project_id AND a.definition_id=d.definition_id ORDER BY acquired_at DESC LIMIT 1) last ON true
            WHERE d.payload#>>'{definition,update,enabled}'='true'
            AND NOT EXISTS(SELECT 1 FROM authority_source_market_definition n WHERE n.previous_definition_id=d.definition_id)
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_retirement r WHERE r.source_id=d.source_id)
            AND COALESCE(last.status,'') NOT IN ('ACCESS_DENIED','RATE_LIMITED','CHALLENGE','LOGIN_REQUIRED','PARSE_DRIFT','REMOVED','REVOKED')
            AND (last.acquired_at IS NULL OR last.acquired_at + (d.payload#>>'{definition,update,interval_seconds}')::bigint * interval '1 second' <= NOW())
            AND NOT EXISTS(SELECT 1 FROM authority_operation o WHERE o.project_id=d.project_id
                AND o.definition_name=%s AND o.command_payload->'payload'->>'definition_id'=d.definition_id
                AND o.status NOT IN ('SUCCEEDED','FAILED_FINAL','DEAD_LETTER','CANCELLED'))
            ORDER BY last.acquired_at NULLS FIRST,d.definition_id LIMIT %s""",
            [OPERATION, limit],
        )
        due = uow.cursor.fetchall()
    results = []
    for project, workspace, identity, payload, slot in due:
        try:
            results.append(
                admit_market_refresh(
                    app,
                    MarketRefreshRequest(
                        project_id=project,
                        workspace_id=workspace,
                        definition_id=identity,
                        run_key=f"scheduled:{identity}:{slot}",
                        period_value=payload["definition"]["period"],
                    ),
                )
            )
        except (KernelError, ValueError):
            continue
    return results
