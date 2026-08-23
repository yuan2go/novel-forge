from __future__ import annotations

import hashlib

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
from novel_forge.modules.context_builder.production_retrieval import (
    SEMANTIC_PROJECTION_VERSION,
    build_retrieval_query_plan,
    build_retrieval_result,
    discover_accepted_retrieval_candidates,
    freeze_retrieval_candidate_union,
)
from novel_forge.modules.command_kernel.errors import KernelError
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


def _start_retrieval_attempt(project_id: str) -> tuple[str, WorkerLeaseCommand]:
    definition_name = identifier("retrieval-v3-definition")
    operation_id = identifier("retrieval-v3-operation")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=project_id,
            status="READY",
        )
    attempt_id = str(
        create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=identifier("retrieval-v3-trace"),
            correlation_id=operation_id,
        )["attempt_id"]
    )
    queue_attempt(
        DATABASE_URL,
        attempt_id=attempt_id,
        project_id=project_id,
        trace_id=identifier("retrieval-v3-queue-trace"),
        correlation_id=operation_id,
    )
    worker_id = identifier("retrieval-v3-worker")
    lease = acquire_attempt_lease(
        DATABASE_URL,
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id=worker_id,
        lease_seconds=60,
        trace_id=identifier("retrieval-v3-lease-trace"),
        correlation_id=operation_id,
    )
    command = WorkerLeaseCommand(
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id=worker_id,
        fencing_token=int(lease["fencing_token"]),
        trace_id=identifier("retrieval-v3-start-trace"),
        correlation_id=operation_id,
        causation_id=operation_id,
    )
    start_attempt(DATABASE_URL, command)
    return operation_id, command


def _seed_document(
    cursor,
    *,
    project_id: str,
    book_id: str,
    source_operation_id: str,
    label: str,
    chapter: int,
    text: str,
    vector: tuple[float, ...],
    model: str = "semantic-model-v3",
    accepted_to: int | None = None,
    entity_ids: tuple[str, ...] = (),
    projection_version: str = SEMANTIC_PROJECTION_VERSION,
) -> tuple[str, str, str]:
    asset_id = f"asset:{label}"
    asset_version_id = f"asset-version:{label}"
    content_hash = _sha(f"content:{label}")
    document_id = f"retrieval-document:{label}"
    effect_id = f"embedding-effect:{label}"
    cursor.execute(
        "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,'best_draft_candidate')",
        [asset_id, project_id],
    )
    cursor.execute(
        """
        INSERT INTO authority_asset_version(
            asset_version_id, asset_id, version_number, lifecycle,
            eligibility, governance, content, content_hash, schema_version
        ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'draft.v1')
        """,
        [asset_version_id, asset_id, Jsonb({"text": text}), content_hash],
    )
    cursor.execute(
        """
        INSERT INTO authority_narrative_retrieval_document(
            retrieval_document_id, project_id, book_id,
            source_asset_version_id, source_artifact_type,
            accepted_from_chapter, accepted_to_chapter, memory_layer,
            content_text, entity_ids, relationship_ids, character_ids,
            arc_plan_version_ids, obligation_ids, temporal_coordinate,
            metadata, projection_hash, created_by_operation_id
        ) VALUES (
            %s,%s,%s,%s,'best_draft_candidate',%s,%s,'L0',%s,%s,
            '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,%s,
            '{}'::jsonb,%s,%s
        )
        """,
        [
            document_id,
            project_id,
            book_id,
            asset_version_id,
            chapter,
            accepted_to,
            text,
            Jsonb(list(entity_ids)),
            Jsonb({"accepted_chapter": chapter}),
            _sha(f"document:{label}"),
            source_operation_id,
        ],
    )
    cursor.execute(
        """
        INSERT INTO authority_external_effect(
            external_effect_id, operation_id, effect_type,
            stable_idempotency_key, status, request_hash, project_id,
            provider, capability, model_id
        ) VALUES (%s,%s,'model.invoke',%s,'SUCCEEDED',%s,%s,
                  'production_execution_gateway','model.retrieval',%s)
        """,
        [effect_id, source_operation_id, effect_id, _sha(effect_id), project_id, model],
    )
    literal = "[" + ",".join(str(item) for item in vector) + "]"
    cursor.execute(
        """
        INSERT INTO authority_retrieval_embedding_projection(
            embedding_projection_id, project_id, book_id,
            retrieval_document_id, source_asset_version_id,
            source_content_hash, projection_version, status,
            embedding, embedding_vector, embedding_model, embedding_provider,
            embedding_dimensions, route_snapshot_id, external_effect_id,
            receipt_id, operation_id, projection_hash, evidence
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,'READY',%s,%s::vector,%s,
            'production_execution_gateway',%s,'route:semantic-v3',%s,
            %s,%s,%s,'{}'::jsonb
        )
        """,
        [
            f"embedding-projection:{label}",
            project_id,
            book_id,
            document_id,
            asset_version_id,
            content_hash,
            projection_version,
            Jsonb(list(vector)),
            literal,
            model,
            len(vector),
            effect_id,
            f"receipt:{label}",
            source_operation_id,
            _sha(f"projection:{label}"),
        ],
    )
    return document_id, asset_version_id, content_hash


def test_vector_channel_recalls_distant_accepted_document_and_freezes_union() -> None:
    ensure_migrated()
    project_id = identifier("retrieval-v3-project")
    workspace_id = f"workspace:{project_id}"
    book_id = f"book:{project_id}"
    seed_authority_project_book(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
    )
    source_definition = identifier("retrieval-source-definition")
    source_operation_id = identifier("retrieval-source-operation")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, source_definition)
        insert_operation(
            cursor,
            operation_id=source_operation_id,
            definition_name=source_definition,
            project_id=project_id,
            status="SUCCEEDED",
        )
        distant_id, distant_version_id, distant_hash = _seed_document(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source_operation_id=source_operation_id,
            label=identifier("chapter-20"),
            chapter=20,
            text="Moonlight folds around an unspoken choice at the empty bridge.",
            vector=(1.0, 0.0, 0.0),
        )
        duplicate_id, _, _ = _seed_document(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source_operation_id=source_operation_id,
            label=identifier("duplicate-channel"),
            chapter=80,
            text="A separate memory attached to the duplicate graph node.",
            vector=(0.99, 0.01, 0.0),
            entity_ids=("entity:duplicate",),
        )
        future_id, _, _ = _seed_document(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source_operation_id=source_operation_id,
            label=identifier("chapter-201"),
            chapter=201,
            text="Future evidence must never cross the boundary.",
            vector=(1.0, 0.0, 0.0),
        )
        stale_id, _, _ = _seed_document(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source_operation_id=source_operation_id,
            label=identifier("stale-document"),
            chapter=30,
            accepted_to=100,
            text="This projection is no longer valid at chapter two hundred.",
            vector=(1.0, 0.0, 0.0),
        )
        wrong_model_id, _, _ = _seed_document(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source_operation_id=source_operation_id,
            label=identifier("wrong-model"),
            chapter=40,
            text="An incompatible embedding model cannot enter vector recall.",
            vector=(1.0, 0.0, 0.0),
            model="semantic-model-v2",
        )
        wrong_version_id, _, _ = _seed_document(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source_operation_id=source_operation_id,
            label=identifier("wrong-version"),
            chapter=45,
            text="An obsolete projection version cannot enter vector recall.",
            vector=(1.0, 0.0, 0.0),
            projection_version="accepted-retrieval-embedding-v0",
        )

    intent = {
        "chapter": 200,
        "intent_fingerprint": _sha("intent"),
        "accepted_boundary": {"accepted_through_chapter": 199},
        "required_arc_contributions": [],
        "active_obligations": [],
        "retrieval_graph": {
            "entity_ids": ["entity:duplicate"],
            "character_ids": [],
            "relationship_ids": [],
        },
    }
    memo = {
        "chapter": 200,
        "qualification": "QUALIFIED",
        "memo_fingerprint": _sha("memo"),
        "accepted_boundary": {"accepted_through_chapter": 199},
        "retrieval_queries": ["silent covenant signal"],
        "arc_actions": [],
        "obligation_actions": [],
    }
    discovery = discover_accepted_retrieval_candidates(
        DATABASE_URL,
        project_id=project_id,
        book_id=book_id,
        query_plan=build_retrieval_query_plan(intent=intent, memo=memo),
    )
    base_ids = {item["retrieval_document_id"] for item in discovery.documents}
    assert distant_id not in base_ids
    assert duplicate_id in base_ids

    operation_id, worker = _start_retrieval_attempt(project_id)
    arguments = {
        "database_url": DATABASE_URL,
        "project_id": project_id,
        "book_id": book_id,
        "operation_id": operation_id,
        "attempt_id": worker.attempt_id,
        "fencing_token": worker.fencing_token,
        "worker_id": worker.worker_id,
        "query_plan": discovery.query_plan,
        "base_documents": discovery.documents,
        "semantic_status": discovery.semantic_status,
        "query_embedding": (1.0, 0.0, 0.0),
        "query_embedding_model": "semantic-model-v3",
        "query_embedding_dimensions": 3,
        "query_embedding_evidence": {
            "provider_id": "real-provider-shape-fixture",
            "model_id": "semantic-model-v3",
            "receipt_id": "query-receipt:v3",
        },
    }
    frozen = freeze_retrieval_candidate_union(**arguments)
    replay = freeze_retrieval_candidate_union(**arguments)

    assert replay.replayed is True
    assert replay.snapshot_hash == frozen.snapshot_hash
    by_id = {item["retrieval_document_id"]: item for item in frozen.documents}
    assert "VECTOR" in by_id[distant_id]["candidate_channels"]
    assert set(by_id[duplicate_id]["candidate_channels"]) == {"ENTITY", "VECTOR"}
    assert future_id not in by_id
    assert stale_id not in by_id
    assert wrong_model_id not in by_id
    assert wrong_version_id not in by_id

    result_arguments = {
        "project_id": project_id,
        "book_id": book_id,
        "intent_asset_version_id": "intent:v200",
        "memo_asset_version_id": "memo:v200",
        "query_plan": discovery.query_plan,
        "documents": frozen.documents,
        "discovery_rejections": discovery.rejected_documents,
        "semantic_status": frozen.semantic_status,
        "query_embedding": frozen.query_embedding,
        "query_embedding_evidence": frozen.query_embedding_evidence,
        "candidate_snapshot_id": frozen.candidate_snapshot_id,
        "candidate_snapshot_hash": frozen.snapshot_hash,
    }
    first = build_retrieval_result(**result_arguments)
    second = build_retrieval_result(**result_arguments)
    assert first == second
    selected_ids = {
        item["retrieval_document_id"] for item in first["selected_documents"]
    }
    assert distant_id in selected_ids
    assert (distant_version_id, distant_hash) in {
        (item["asset_version_id"], item["content_hash"])
        for item in first["candidate_asset_versions"]
    }
    assert first["ranking"]["ranking_policy_version"] == (
        "accepted-hybrid-ranking-v3"
    )
    assert first["result_fingerprint"].startswith("sha256:")
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename='authority_retrieval_embedding_projection'
              AND indexname LIKE '%hnsw%'
            ORDER BY indexname
            """
        )
        hnsw_indexes = tuple(str(row[0]) for row in cursor.fetchall())
        cursor.execute(
            """
            SELECT candidate_asset_versions, snapshot_hash
            FROM authority_retrieval_candidate_snapshot
            WHERE operation_id=%s
            """,
            [operation_id],
        )
        persisted_sources, persisted_hash = cursor.fetchone()
    assert len(hnsw_indexes) == 3
    assert str(persisted_hash) == frozen.snapshot_hash
    assert (distant_version_id, distant_hash) in {
        (item["asset_version_id"], item["content_hash"])
        for item in persisted_sources
    }
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_retrieval_candidate_snapshot
                SET book_id='book:mutated'
                WHERE operation_id=%s
                """,
                [operation_id],
            )

    stale_operation_id, stale_worker = _start_retrieval_attempt(project_id)
    with pytest.raises(KernelError) as stale:
        freeze_retrieval_candidate_union(
            DATABASE_URL,
            project_id=project_id,
            book_id=book_id,
            operation_id=stale_operation_id,
            attempt_id=stale_worker.attempt_id,
            fencing_token=stale_worker.fencing_token,
            worker_id="stale-retrieval-worker",
            query_plan=discovery.query_plan,
            base_documents=discovery.documents,
            semantic_status=discovery.semantic_status,
        )
    assert stale.value.code == "RETRIEVAL_CANDIDATE_FENCE_STALE"

    required_discovery = discover_accepted_retrieval_candidates(
        DATABASE_URL,
        project_id=project_id,
        book_id=book_id,
        query_plan=build_retrieval_query_plan(
            intent=intent,
            memo=memo,
            semantic_policy="REQUIRED",
        ),
    )
    required_operation_id, required_worker = _start_retrieval_attempt(project_id)
    with pytest.raises(KernelError) as required:
        freeze_retrieval_candidate_union(
            DATABASE_URL,
            project_id=project_id,
            book_id=book_id,
            operation_id=required_operation_id,
            attempt_id=required_worker.attempt_id,
            fencing_token=required_worker.fencing_token,
            worker_id=required_worker.worker_id,
            query_plan=required_discovery.query_plan,
            base_documents=required_discovery.documents,
            semantic_status=required_discovery.semantic_status,
            query_embedding=(1.0, 0.0, 0.0),
            query_embedding_model="semantic-model-without-compatible-projection",
            query_embedding_dimensions=3,
        )
    assert required.value.code == "RETRIEVAL_SEMANTIC_PROJECTION_REQUIRED"

    disabled_discovery = discover_accepted_retrieval_candidates(
        DATABASE_URL,
        project_id=project_id,
        book_id=book_id,
        query_plan=build_retrieval_query_plan(
            intent=intent,
            memo=memo,
            semantic_policy="DISABLED",
        ),
    )
    disabled_operation_id, disabled_worker = _start_retrieval_attempt(project_id)
    disabled = freeze_retrieval_candidate_union(
        DATABASE_URL,
        project_id=project_id,
        book_id=book_id,
        operation_id=disabled_operation_id,
        attempt_id=disabled_worker.attempt_id,
        fencing_token=disabled_worker.fencing_token,
        worker_id=disabled_worker.worker_id,
        query_plan=disabled_discovery.query_plan,
        base_documents=disabled_discovery.documents,
        semantic_status=disabled_discovery.semantic_status,
    )
    assert disabled.query_embedding == ()
    assert disabled.semantic_status["status"] == "RETRIEVAL_SEMANTIC_DISABLED"
    assert disabled.semantic_status["fallback"] == "NONE"
