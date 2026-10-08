import pytest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.market_query import (
    query_ranks,
    query_market_work,
)
import psycopg
from novel_forge.modules.source_import import (
    SourceImportApplication,
    SourceImportScheduler,
)
from novel_forge.modules.source_import.market_runtime import (
    MarketRefreshRequest,
    admit_market_refresh,
)
from novel_forge.modules.source_import.market_adapter import QidianRankAdapter

from tests.integration.authority_postgres_support import DATABASE_URL
from tests.unit.test_source_market import (
    definition,
    use_scope,
    observation,
    Transport,
    HTML,
)

pytest_plugins = ["tests.integration.test_corpus_foundation_postgres"]


def prepare(corpus, key="monthly", enabled=False):
    source = corpus.source(purpose="MARKET_INTELLIGENCE", external="qidian:official")
    corpus.run(
        {
            "action": "declare_rights",
            "source_id": source,
            "dataset_license": "fixture:fact-import",
            "underlying_rights": "PERMISSION_GRANTED",
            "allowed_purposes": ["MARKET_INTELLIGENCE"],
            "allowed_uses": ["LOCAL_PROCESSING"],
            "evidence_refs": ["fixture:metadata-only"],
            "copyright_boundary": "Metadata only; no text or cloud-model permission",
            "scope": "ALL_WORKS_IN_SNAPSHOT",
        }
    )
    result = corpus.run(
        {
            "action": "define_market_rank",
            "source_id": source,
            "definition": definition(key=key, update={"enabled": enabled, "top_n": 2}),
            "use_scope": use_scope(),
        }
    )
    return source, result["definition_id"]


def test_native_author_import_identity_snapshots_idempotency_failures_and_revocation(
    corpus,
):
    source, rank = prepare(corpus)
    raw = observation(source_id=source, definition_id=rank)
    first = corpus.run(raw, key="same-import")
    replay = corpus.run(raw, key="same-import")
    assert first["asset_version_id"] == replay["asset_version_id"]
    second = corpus.run(raw, key="different-key-same-content")
    assert first["attempt_record_id"] == second["attempt_record_id"]
    ids = [e["book_source_id"] for e in first["entries"]]
    assert len(set(ids)) == 2
    work = query_market_work(DATABASE_URL, corpus.project, ids[0])
    assert len(work["metadata_versions"]) == 1 and not work["knowledge_cards"]
    another = corpus.run(
        {
            "action": "define_market_rank",
            "source_id": source,
            "definition": definition(
                key="sales",
                official_name="畅销榜",
                url="https://www.qidian.com/rank/hotsales/",
            ),
            "use_scope": use_scope(),
        }
    )
    cross = corpus.run(
        observation(source_id=source, definition_id=another["definition_id"])
    )
    assert [e["book_source_id"] for e in cross["entries"]] == ids
    corpus.run(
        observation(
            source_id=source,
            definition_id=rank,
            status="ACCESS_DENIED",
            pages=[],
            missing_reasons=["403"],
        )
    )
    view = query_ranks(DATABASE_URL, corpus.project, definition_id=rank)["items"][0]
    assert (
        view["last_valid_snapshot"]["attempt_record_id"] == first["attempt_record_id"]
    )
    assert len(view["entries"]) == 2
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE authority_source_market_attempt SET status='PARTIAL' WHERE attempt_record_id=%s",
                [first["attempt_record_id"]],
            )
        connection.rollback()
    corpus.run(
        {"action": "retire_source", "source_id": source, "reason": "rights withdrawn"}
    )
    view = query_ranks(DATABASE_URL, corpus.project, definition_id=rank)["items"][0]
    assert view["status"] == "REVOKED" and not view["entries"]
    assert "payload" not in view["last_valid_snapshot"]
    assert (
        query_market_work(DATABASE_URL, corpus.project, ids[0])["status"] == "REVOKED"
    )
    with pytest.raises(KernelError):
        corpus.run(observation(source_id=source, definition_id=rank))


def test_native_fetch_receipt_replay_and_source_data_ineligible(corpus):
    source, rank = prepare(corpus)
    app = SourceImportApplication(
        DATABASE_URL, application_build_id="corpus-test", commit_sha="e" * 40
    )
    transport = Transport([(200, "User-agent: *\nAllow: /", {}), (200, HTML, {})])
    app.market_adapter = QidianRankAdapter(transport=transport)
    request = MarketRefreshRequest(
        project_id=corpus.project,
        workspace_id=corpus.workspace,
        definition_id=rank,
        run_key="fetch1",
        period_value="2026-10",
    )
    admitted = admit_market_refresh(app, request)
    scheduler = SourceImportScheduler(app, worker_id="market-fixture-worker")
    result = scheduler.run_or_recover(
        operation_id=admitted["operation_id"], project_id=corpus.project
    )
    assert (
        result["status"] == "SUCCEEDED"
        and result["observation"]["status"] == "COMPLETE"
    )
    assert not result["generation_context_allowed"]
    replay = admit_market_refresh(app, request)
    assert replay["operation_id"] == admitted["operation_id"]
    scheduler.run_or_recover(
        operation_id=replay["operation_id"], project_id=corpus.project
    )
    assert len(transport.requests) == 2
    with pytest.raises(KernelError):
        admit_market_refresh(
            app, request.model_copy(update={"period_value": "different"})
        )
    forged = observation(
        source_id=source, definition_id=rank, acquisition="OFFICIAL_PUBLIC_PAGE"
    )
    response = corpus.client.post(
        "/product/source-governance/corpus/commands",
        json={
            "project_id": corpus.project,
            "workspace_id": corpus.workspace,
            "idempotency_key": "forged",
            "action": forged,
        },
    )
    assert (
        response.status_code == 409
        and response.json()["detail"]["code"] == "MARKET_NATIVE_RECEIPT_REQUIRED"
    )


def test_native_unknown_fetch_never_redispatches_or_creates_new_scheduled_task(corpus):
    from novel_forge.modules.command_kernel.external_effect_adapters import (
        ProviderResult,
    )
    from novel_forge.modules.source_import.market_runtime import enqueue_market_updates

    source, rank = prepare(corpus, enabled=True)

    class UnknownAdapter(QidianRankAdapter):
        sends = 0

        def execute(self, **kwargs):
            self.sends += 1
            return ProviderResult(
                "unknown",
                kwargs["stable_idempotency_key"],
                {"reason": "controlled unknown receipt"},
            )

    app = SourceImportApplication(
        DATABASE_URL, application_build_id="corpus-test", commit_sha="e" * 40
    )
    adapter = UnknownAdapter()
    app.market_adapter = adapter
    request = MarketRefreshRequest(
        project_id=corpus.project,
        workspace_id=corpus.workspace,
        definition_id=rank,
        run_key="uncertain-fetch",
        period_value="2026-10",
    )
    original = admit_market_refresh(app, request)["operation_id"]
    scheduler = SourceImportScheduler(app, worker_id="uncertain-market-worker")
    for expected in ("EFFECT_EXTERNAL_STATE_UNKNOWN", "RECONCILIATION_OUTCOME_INVALID"):
        with pytest.raises(KernelError, match=expected):
            scheduler.run_or_recover(operation_id=original, project_id=corpus.project)
    assert adapter.sends == 1
    assert admit_market_refresh(app, request)["operation_id"] == original
    with pytest.raises(KernelError, match="MARKET_REFRESH_ACTIVE"):
        admit_market_refresh(
            app, request.model_copy(update={"run_key": "forbidden-replacement"})
        )
    assert not enqueue_market_updates(app)
    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM authority_source_market_attempt WHERE project_id=%s",
                [corpus.project],
            ).fetchone()[0]
            == 0
        )
