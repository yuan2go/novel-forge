from __future__ import annotations

import hashlib
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.handlers import (
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.context_builder.production_retrieval import (
    build_retrieval_query_plan,
    discover_accepted_retrieval_candidates,
)
from novel_forge.modules.context_builder.retrieval_campaign import (
    RetrievalCampaignPolicy,
    build_retrieval_coverage_contract,
    evaluate_retrieval_coverage,
)
from novel_forge.modules.context_builder.retrieval_campaign_store import (
    complete_retrieval_campaign,
    freeze_retrieval_round,
    load_retrieval_campaign,
    load_retrieval_rounds,
    start_retrieval_campaign,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _seed_campaign(required_facts=("fact:origin",)) -> dict[str, object]:
    ensure_migrated()
    project_id = identifier("retrieval-campaign-project")
    book_id = f"book:{project_id}"
    seed_authority_project_book(
        project_id=project_id,
        workspace_id=f"workspace:{project_id}",
        book_id=book_id,
    )
    definition_name = identifier("retrieval-campaign-definition")
    operation_id = identifier("retrieval-campaign-operation")
    intent_asset_version_id = identifier("retrieval-intent-version")
    memo_asset_version_id = identifier("retrieval-memo-version")
    intent = {
        "chapter": 41,
        "project_id": project_id,
        "intent_fingerprint": _sha("intent"),
        "accepted_boundary": {"accepted_through_chapter": 40},
        "required_arc_contributions": [],
        "active_obligations": [],
        "required_long_distance_fact_ids": list(required_facts),
        "retrieval_graph": {
            "entity_ids": ["entity:key"],
            "character_ids": [],
            "relationship_ids": [],
        },
    }
    memo = {
        "chapter": 41,
        "qualification": "QUALIFIED",
        "memo_fingerprint": _sha("memo"),
        "accepted_boundary": {"accepted_through_chapter": 40},
        "retrieval_queries": ["recent crossing"],
        "arc_actions": [],
        "obligation_actions": [],
    }
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=project_id,
            status="READY",
        )
        for label, version_id, content, asset_type in (
            ("intent", intent_asset_version_id, intent, "chapter_execution_intent"),
            ("memo", memo_asset_version_id, memo, "chapter_memo"),
        ):
            asset_id = identifier(f"retrieval-{label}-asset")
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [version_id, asset_id, Jsonb(content), _sha(label), f"{asset_type}.v1"],
            )
    attempt_id = str(
        create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=identifier("retrieval-campaign-trace"),
            correlation_id=operation_id,
        )["attempt_id"]
    )
    queue_attempt(
        DATABASE_URL,
        attempt_id=attempt_id,
        project_id=project_id,
        trace_id=identifier("retrieval-campaign-queue"),
        correlation_id=operation_id,
    )
    worker_id = identifier("retrieval-campaign-worker")
    lease = acquire_attempt_lease(
        DATABASE_URL,
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id=worker_id,
        lease_seconds=60,
        trace_id=identifier("retrieval-campaign-lease"),
        correlation_id=operation_id,
    )
    worker = WorkerLeaseCommand(
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id=worker_id,
        fencing_token=int(lease["fencing_token"]),
        trace_id=identifier("retrieval-campaign-start"),
        correlation_id=operation_id,
        causation_id=operation_id,
    )
    start_attempt(DATABASE_URL, worker)
    return {
        "project_id": project_id,
        "book_id": book_id,
        "operation_id": operation_id,
        "intent_asset_version_id": intent_asset_version_id,
        "memo_asset_version_id": memo_asset_version_id,
        "intent": intent,
        "memo": memo,
        "worker": worker,
    }


class _ExpansionPort:
    external_effect_backed = True

    def __init__(self, target="fact:origin") -> None:
        self.target = target
        self.adapter = SimpleNamespace(routes={"retrieval_query_expansion": object()})
        self.calls = 0

    def invoke(self, request, *, stage, payload, **kwargs):  # type: ignore[no-untyped-def]
        assert stage == "retrieval_query_expansion"
        assert payload["accepted_boundary"] == {"accepted_through_chapter": 40}
        self.calls += 1
        return ModelProviderResult(
            output={
                "contract_version": "retrieval-expansion-plan-v1",
                "queries": [
                    {
                        "query_id": f"query:origin:{self.calls}",
                        "text": "bridge oath origin",
                        "reason": "recover the missing accepted provenance",
                        "targets": ["fact:" + self.target],
                        "selectors": {},
                        "temporal_range": {
                            "from_chapter": 1,
                            "to_chapter": 40,
                        },
                    }
                ],
            },
            provider_id="fixture-expansion-provider",
            model_id="fixture-expansion-model-v1",
            prompt_version="retrieval-query-expansion-v1",
            skill_version="context-builder-source-isolation-v1",
            input_tokens=30,
            output_tokens=10,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


def test_campaign_rounds_are_fenced_immutable_and_replay_exactly() -> None:
    fixture = _seed_campaign()
    worker = fixture["worker"]
    assert isinstance(worker, WorkerLeaseCommand)
    policy = RetrievalCampaignPolicy()
    coverage_contract = build_retrieval_coverage_contract(
        intent=fixture["intent"], memo=fixture["memo"]
    )
    campaign = start_retrieval_campaign(
        DATABASE_URL,
        project_id=str(fixture["project_id"]),
        book_id=str(fixture["book_id"]),
        operation_id=str(fixture["operation_id"]),
        attempt_id=worker.attempt_id,
        fencing_token=worker.fencing_token,
        worker_id=worker.worker_id,
        chapter=41,
        intent_asset_version_id=str(fixture["intent_asset_version_id"]),
        memo_asset_version_id=str(fixture["memo_asset_version_id"]),
        intent_fingerprint=str(fixture["intent"]["intent_fingerprint"]),
        memo_fingerprint=str(fixture["memo"]["memo_fingerprint"]),
        accepted_boundary={"accepted_through_chapter": 40},
        policy=policy,
        coverage_contract=coverage_contract,
    )
    replayed_campaign = start_retrieval_campaign(
        DATABASE_URL,
        project_id=str(fixture["project_id"]),
        book_id=str(fixture["book_id"]),
        operation_id=str(fixture["operation_id"]),
        attempt_id=worker.attempt_id,
        fencing_token=worker.fencing_token,
        worker_id=worker.worker_id,
        chapter=41,
        intent_asset_version_id=str(fixture["intent_asset_version_id"]),
        memo_asset_version_id=str(fixture["memo_asset_version_id"]),
        intent_fingerprint=str(fixture["intent"]["intent_fingerprint"]),
        memo_fingerprint=str(fixture["memo"]["memo_fingerprint"]),
        accepted_boundary={"accepted_through_chapter": 40},
        policy=policy,
        coverage_contract=coverage_contract,
    )
    assert replayed_campaign["campaign_id"] == campaign["campaign_id"]
    assert replayed_campaign["input_fingerprint"] == campaign["input_fingerprint"]

    document = {
        "retrieval_document_id": "retrieval:origin",
        "source_asset_version_id": str(fixture["intent_asset_version_id"]),
        "source_content_hash": _sha("intent"),
        "projection_hash": _sha("projection"),
        "accepted_from_chapter": 1,
        "accepted_to_chapter": None,
        "memory_layer": "L2",
        "content_text": "the key originated at the bridge",
        "fact_ids": ["fact:origin"],
        "entity_ids": ["entity:key"],
        "relationship_ids": [],
        "character_ids": [],
        "arc_plan_version_ids": [],
        "obligation_ids": [],
        "candidate_channels": ["FTS"],
    }
    before = evaluate_retrieval_coverage(contract=coverage_contract, documents=[])
    after = evaluate_retrieval_coverage(
        contract=coverage_contract, documents=[document]
    )
    query_plan = {
        "query_plan_fingerprint": _sha("query-plan"),
        "candidate_projection_cutoff": "2026-09-03T00:00:00+00:00",
        "accepted_boundary": {"accepted_through_chapter": 40},
    }
    frozen = freeze_retrieval_round(
        DATABASE_URL,
        campaign_id=str(campaign["campaign_id"]),
        project_id=str(fixture["project_id"]),
        book_id=str(fixture["book_id"]),
        operation_id=str(fixture["operation_id"]),
        attempt_id=worker.attempt_id,
        fencing_token=worker.fencing_token,
        worker_id=worker.worker_id,
        round_number=0,
        query_plan=query_plan,
        documents=[document],
        rejected_documents=[],
        semantic_status={"status": "RETRIEVAL_SEMANTIC_DISABLED"},
        coverage_before=before,
        coverage_after=after,
        new_evidence_count=1,
    )
    replayed = freeze_retrieval_round(
        DATABASE_URL,
        campaign_id=str(campaign["campaign_id"]),
        project_id=str(fixture["project_id"]),
        book_id=str(fixture["book_id"]),
        operation_id=str(fixture["operation_id"]),
        attempt_id=worker.attempt_id,
        fencing_token=worker.fencing_token,
        worker_id=worker.worker_id,
        round_number=0,
        query_plan=query_plan,
        documents=[document],
        rejected_documents=[],
        semantic_status={"status": "RETRIEVAL_SEMANTIC_DISABLED"},
        coverage_before=before,
        coverage_after=after,
        new_evidence_count=1,
    )
    assert replayed["replayed"] is True
    assert replayed["snapshot_hash"] == frozen["snapshot_hash"]

    with pytest.raises(psycopg.errors.CheckViolation):
        freeze_retrieval_round(
            DATABASE_URL,
            campaign_id=str(campaign["campaign_id"]),
            project_id=str(fixture["project_id"]),
            book_id=str(fixture["book_id"]),
            operation_id=str(fixture["operation_id"]),
            attempt_id=worker.attempt_id,
            fencing_token=worker.fencing_token,
            worker_id=worker.worker_id,
            round_number=2,
            query_plan={
                **query_plan,
                "query_plan_fingerprint": _sha("query-plan-2"),
            },
            expansion_plan={
                "expansion_plan_fingerprint": _sha("expansion-2"),
                "queries": [{"query_fingerprint": _sha("query-2")}],
            },
            expansion_reason="missing fact",
            documents=[],
            rejected_documents=[],
            semantic_status={},
            coverage_before=after,
            coverage_after=after,
            new_evidence_count=0,
        )

    with pytest.raises(KernelError) as stale:
        freeze_retrieval_round(
            DATABASE_URL,
            campaign_id=str(campaign["campaign_id"]),
            project_id=str(fixture["project_id"]),
            book_id=str(fixture["book_id"]),
            operation_id=str(fixture["operation_id"]),
            attempt_id=worker.attempt_id,
            fencing_token=worker.fencing_token,
            worker_id="stale-worker",
            round_number=1,
            query_plan={
                **query_plan,
                "query_plan_fingerprint": _sha("query-plan-1"),
            },
            expansion_plan={
                "expansion_plan_fingerprint": _sha("expansion"),
                "queries": [{"query_fingerprint": _sha("query")}],
            },
            expansion_reason="missing fact",
            documents=[],
            rejected_documents=[],
            semantic_status={},
            coverage_before=after,
            coverage_after=after,
            new_evidence_count=0,
        )
    assert stale.value.code == "RETRIEVAL_CAMPAIGN_FENCE_STALE"

    final = complete_retrieval_campaign(
        DATABASE_URL,
        campaign_id=str(campaign["campaign_id"]),
        project_id=str(fixture["project_id"]),
        operation_id=str(fixture["operation_id"]),
        attempt_id=worker.attempt_id,
        fencing_token=worker.fencing_token,
        worker_id=worker.worker_id,
        status="COMPLETED",
        termination_reason="REQUIRED_EVIDENCE_SATISFIED",
        final_result_fingerprint=_sha("result"),
        final_evidence_identity=_sha("evidence"),
    )
    assert final["status"] == "COMPLETED"
    assert (
        len(
            load_retrieval_rounds(
                DATABASE_URL, campaign_id=str(campaign["campaign_id"])
            )
        )
        == 1
    )
    assert load_retrieval_campaign(
        DATABASE_URL, campaign_id=str(campaign["campaign_id"])
    )["final_evidence_identity"] == _sha("evidence")

    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_retrieval_round SET latency_ms=1 WHERE round_id=%s",
                [frozen["round_id"]],
            )


@pytest.mark.parametrize("stop_duplicate", [False, True])
def test_retrieval_handler_expands_one_round_and_replays_the_frozen_union(stop_duplicate) -> None:
    fixture = _seed_campaign(("fact:origin", "fact:missing") if stop_duplicate else ("fact:origin",))
    worker = fixture["worker"]
    assert isinstance(worker, WorkerLeaseCommand)
    project_id = str(fixture["project_id"])
    book_id = str(fixture["book_id"])
    plan_content = {
        "project_id": project_id,
        "book_id": book_id,
        "chapter": 41,
    }
    plan_version_id = identifier("retrieval-plan-version")
    source_version_id = identifier("retrieval-source-version")
    source_content = {"safe_summary": "The bridge oath established the key origin."}
    with transaction() as connection, connection.cursor() as cursor:
        for label, version_id, content, asset_type in (
            ("plan", plan_version_id, plan_content, "chapter_plan"),
            ("source", source_version_id, source_content, "canon_snapshot"),
        ):
            asset_id = identifier(f"retrieval-{label}-asset")
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [version_id, asset_id, Jsonb(content), _sha(label), f"{asset_type}.v1"],
            )
        cursor.execute(
            """
            INSERT INTO authority_narrative_retrieval_document(
                retrieval_document_id,project_id,book_id,source_asset_version_id,
                source_artifact_type,accepted_from_chapter,memory_layer,content_text,
                entity_ids,relationship_ids,character_ids,arc_plan_version_ids,
                obligation_ids,temporal_coordinate,metadata,projection_hash,
                created_by_operation_id
            ) VALUES (
                %s,%s,%s,%s,'canon_snapshot',10,'L2',%s,
                '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,
                '[]'::jsonb,%s,%s,%s,%s
            )
            """,
            [
                identifier("retrieval-origin-document"),
                project_id,
                book_id,
                source_version_id,
                "bridge oath origin accepted provenance",
                Jsonb({"accepted_chapter": 10}),
                Jsonb(
                    {
                        "fact_ids": ["fact:origin"],
                        "structured_facts": [
                            {"fact_id": "fact:origin", "value": "bridge oath"}
                        ],
                    }
                ),
                _sha("origin-projection"),
                fixture["operation_id"],
            ],
        )

    from novel_forge.modules.context_builder.retrieval_rebuild import plan_writer_index_rebuild, apply_writer_index_rebuild
    rebuild = plan_writer_index_rebuild(DATABASE_URL, project_id=project_id, book_id=book_id, from_chapter=10, to_chapter=10)
    apply_writer_index_rebuild(DATABASE_URL, rebuild)

    intent = dict(fixture["intent"])
    memo = dict(fixture["memo"])
    query_plan = build_retrieval_query_plan(
        intent=intent,
        memo=memo,
        semantic_policy="DISABLED",
    )
    discovery = discover_accepted_retrieval_candidates(
        DATABASE_URL,
        project_id=project_id,
        book_id=book_id,
        query_plan=query_plan,
    )
    assert discovery.documents == ()
    port = _ExpansionPort("fact:missing" if stop_duplicate else "fact:origin")
    handler = build_chapter_handler_registry(port).require(ChapterNode.RETRIEVAL)
    request = ChapterHandlerRequest(
        operation_id=str(fixture["operation_id"]),
        project_id=project_id,
        workspace_id=f"workspace:{project_id}",
        trace_id=identifier("retrieval-handler-trace"),
        correlation_id=str(fixture["operation_id"]),
        command={
            "book_id": book_id,
            "retrieval_snapshot": {
                "query_plan": discovery.query_plan,
                "documents": [],
                "rejected_documents": [],
                "semantic_status": discovery.semantic_status,
            },
        },
        inputs=(
            ChapterInputAsset(
                asset_version_id=plan_version_id,
                asset_type="chapter_plan",
                content_hash=_sha("plan"),
                content=plan_content,
            ),
            ChapterInputAsset(
                asset_version_id=str(fixture["intent_asset_version_id"]),
                asset_type="chapter_execution_intent",
                content_hash=_sha("intent"),
                content=intent,
            ),
            ChapterInputAsset(
                asset_version_id=str(fixture["memo_asset_version_id"]),
                asset_type="chapter_memo",
                content_hash=_sha("memo"),
                content=memo,
            ),
        ),
        attempt_id=worker.attempt_id,
        fencing_token=worker.fencing_token,
        worker_id=worker.worker_id,
        database_url=DATABASE_URL,
    )

    first = handler.execute(request)
    replay_port = _ExpansionPort()
    def forbidden(*args, **kwargs):
        raise AssertionError("Terminal replay must not start another Provider call")
    replay_port.invoke = forbidden
    replay = build_chapter_handler_registry(replay_port).require(ChapterNode.RETRIEVAL).execute(request)

    assert first.content == replay.content
    assert first.content["retrieval_campaign"]["round_count"] == 2
    assert first.content["retrieval_campaign"]["termination_reason"] == (
        "NO_NOVEL_QUERY" if stop_duplicate else "REQUIRED_EVIDENCE_SATISFIED"
    )
    assert first.content["retrieval_campaign"]["coverage"]["sufficient"] is (not stop_duplicate)
    assert [
        item["source_asset_version_id"] for item in first.content["selected_documents"]
    ] == [source_version_id]
    assert port.calls == (2 if stop_duplicate else 1)
    assert replay_port.calls == 0
    if stop_duplicate:
        assert first.content["retrieval_campaign"]["stopped_expansion"]["provider_evidence"]
        assert first.content["retrieval_campaign"]["usage"]["provider_calls"] == 2
    assert (
        len(
            load_retrieval_rounds(
                DATABASE_URL,
                campaign_id=first.content["retrieval_campaign"]["campaign_id"],
            )
        )
        == 2
    )


def test_fourth_expansion_round_preserves_unknown_usage_and_scope():
    fixture = _seed_campaign()
    worker = fixture["worker"]
    policy = RetrievalCampaignPolicy()
    contract = build_retrieval_coverage_contract(intent=fixture["intent"], memo=fixture["memo"])
    common = dict(project_id=fixture["project_id"], book_id=fixture["book_id"], operation_id=fixture["operation_id"],
        attempt_id=worker.attempt_id, fencing_token=worker.fencing_token, worker_id=worker.worker_id)
    campaign = start_retrieval_campaign(DATABASE_URL, **common, chapter=41,
        intent_asset_version_id=fixture["intent_asset_version_id"], memo_asset_version_id=fixture["memo_asset_version_id"],
        intent_fingerprint=fixture["intent"]["intent_fingerprint"], memo_fingerprint=fixture["memo"]["memo_fingerprint"],
        accepted_boundary={"accepted_through_chapter": 40}, policy=policy, coverage_contract=contract)
    coverage = evaluate_retrieval_coverage(contract=contract, documents=[])
    for number in range(5):
        query = {"query_plan_fingerprint": _sha(f"round-{number}"), "candidate_projection_cutoff": "2026-09-03T00:00:00+00:00",
            "accepted_boundary": {"accepted_through_chapter": 40}}
        round_data = freeze_retrieval_round(DATABASE_URL, **common, campaign_id=campaign["campaign_id"],
            round_number=number, query_plan=query, documents=[], rejected_documents=[], semantic_status={},
            coverage_before=coverage, coverage_after=coverage, new_evidence_count=0,
            expansion_plan={"expansion_plan_fingerprint": _sha(f"expansion-{number}")} if number else None,
            expansion_reason="DETERMINISTIC_COVERAGE_GAP" if number else "",
            cost_amount="10" if number == 3 else None, currency="USD" if number == 3 else "UNKNOWN")
        assert round_data["contract_version"] == "retrieval-round-snapshot-v2"
        assert round_data["usage"]["cost_amount"] == ("10" if number == 3 else None)
        assert round_data["usage"]["input_tokens"] is None
    replay = load_retrieval_rounds(DATABASE_URL, campaign_id=campaign["campaign_id"])
    assert len(replay) == 5 and replay[4]["round_number"] == 4
    with pytest.raises((psycopg.errors.CheckViolation, KernelError)):
        freeze_retrieval_round(DATABASE_URL, **{**common, "book_id": "foreign"}, campaign_id=campaign["campaign_id"],
            round_number=5, query_plan={**query, "query_plan_fingerprint": _sha("foreign")}, documents=[],
            rejected_documents=[], semantic_status={}, coverage_before=coverage, coverage_after=coverage,
            new_evidence_count=0, expansion_plan={"expansion_plan_fingerprint": _sha("foreign-expansion")}, expansion_reason="gap")
