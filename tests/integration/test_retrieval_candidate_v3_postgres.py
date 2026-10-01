from __future__ import annotations

import hashlib
import json

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
    build_task_dependency_refs,
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
    metadata: dict[str, object] | None = None,
    obligation_ids: tuple[str, ...] = (),
    source_artifact_type: str = "best_draft_candidate",
    source_content: dict[str, object] | None = None,
    memory_layer: str = "L0",
) -> tuple[str, str, str]:
    asset_id = f"asset:{label}"
    asset_version_id = f"asset-version:{label}"
    content = source_content if source_content is not None else {"text": text}
    content_hash = _sha(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    document_id = f"retrieval-document:{label}"
    effect_id = f"embedding-effect:{label}"
    cursor.execute(
        "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s,%s,%s)",
        [asset_id, project_id, source_artifact_type],
    )
    cursor.execute(
        """
        INSERT INTO authority_asset_version(
            asset_version_id, asset_id, version_number, lifecycle,
            eligibility, governance, content, content_hash, schema_version
        ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'draft.v1')
        """,
        [asset_version_id, asset_id, Jsonb(content), content_hash],
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
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,%s,%s,
            %s,%s,%s
        )
        """,
        [
            document_id,
            project_id,
            book_id,
            asset_version_id,
            source_artifact_type,
            chapter,
            accepted_to,
            memory_layer,
            text,
            Jsonb(list(entity_ids)),
            Jsonb(list(obligation_ids)),
            Jsonb({"accepted_chapter": chapter}),
            Jsonb(metadata or {}),
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


def test_semantic_rerank_cannot_expand_frozen_lexical_structured_union() -> None:
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
    assert distant_id not in by_id
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
    assert distant_id not in selected_ids
    assert (distant_version_id, distant_hash) not in {
        (item["asset_version_id"], item["content_hash"])
        for item in first["candidate_asset_versions"]
    }
    assert first["ranking"]["ranking_policy_version"] == (
        "accepted-lexical-first-ranking-v4"
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
    assert (distant_version_id, distant_hash) not in {
        (item["asset_version_id"], item["content_hash"]) for item in persisted_sources
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


def test_task_dependencies_use_exact_planting_advance_and_causal_closure_outside_optional_limits() -> None:
    ensure_migrated()
    project_id = identifier("task-retrieval-project")
    book_id = f"book:{project_id}"
    seed_authority_project_book(project_id=project_id, workspace_id=f"workspace:{project_id}", book_id=book_id)
    definition = identifier("task-retrieval-source-definition")
    operation_id = identifier("task-retrieval-source-operation")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation_id, definition_name=definition, project_id=project_id, status="SUCCEEDED")
        planting_text = "Exact distant planting with voice and uncertainty. " * 150
        planting_id, _, _ = _seed_document(
            cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("task-planting"), chapter=1, text=planting_text, vector=(1.0, 0.0, 0.0),
            metadata={"fact_ids": ["fact:hook"], "structured_facts": [{"source_event_id": "event:planting", "state": {"fact_id": "fact:hook"}}]},
        )
        advance_id, _, _ = _seed_document(
            cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("task-advance"), chapter=4, text="Latest exact advance.", vector=(1.0, 0.0, 0.0),
            metadata={"fact_ids": ["fact:hook"], "structured_facts": [{"source_event_id": "event:advance", "state": {"fact_id": "fact:hook", "world_transition": {"cause_refs": ["event:causal"]}}}]},
        )
        causal_id, _, _ = _seed_document(
            cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("task-causal"), chapter=2, text="Causal predecessor without lexical similarity.", vector=(1.0, 0.0, 0.0),
            metadata={"structured_facts": [{"source_event_id": "event:causal", "state": {"proposition_id": "proposition:cause"}}]},
        )
        future_id, _, _ = _seed_document(
            cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("task-future"), chapter=301, text="Future matching identity.", vector=(1.0, 0.0, 0.0), metadata={"fact_ids": ["fact:hook"]},
        )
        stale_id, _, _ = _seed_document(
            cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("task-stale"), chapter=290, accepted_to=290, text="Stale matching identity.", vector=(1.0, 0.0, 0.0), metadata={"fact_ids": ["fact:hook"]},
        )
        for index in range(260):
            _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
                           label=identifier(f"task-optional-{index}"), chapter=10 + index,
                           text="optional search material", vector=(1.0, 0.0, 0.0))
    intent = {"chapter": 301, "intent_fingerprint": _sha("task-intent"),
              "accepted_boundary": {"accepted_through_chapter": 300},
              "required_arc_contributions": [], "active_obligations": [], "retrieval_graph": {}}
    memo = {"chapter": 301, "qualification": "QUALIFIED", "memo_fingerprint": _sha("task-memo"),
            "accepted_boundary": intent["accepted_boundary"], "retrieval_queries": ["optional search material"],
            "arc_actions": [], "obligation_actions": []}
    plan = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"required_long_distance_fact_ids": ["fact:hook"]}, current_candidates=[]))
    discovery = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=plan)
    by_id = {item["retrieval_document_id"]: item for item in discovery.documents}
    assert len(by_id) == 259
    assert {planting_id, advance_id, causal_id} <= set(by_id)
    assert future_id not in by_id and stale_id not in by_id
    assert discovery.query_plan["task_dependency_discovery"]["required_refs"] == ["event:causal", "fact:hook"]
    assert "required_dependency_planting" in by_id[planting_id]["retrieval_reasons"]
    assert "required_dependency_advance" in by_id[advance_id]["retrieval_reasons"]
    result = build_retrieval_result(project_id=project_id, book_id=book_id, intent_asset_version_id="intent:task",
        memo_asset_version_id="memo:task", query_plan=discovery.query_plan, documents=discovery.documents,
        discovery_rejections=discovery.rejected_documents, semantic_status=discovery.semantic_status)
    assert len(result["selected_documents"]) == 27
    selected = {item["retrieval_document_id"]: item for item in result["selected_documents"]}
    assert {planting_id, advance_id, causal_id} <= set(selected)
    assert selected[planting_id]["safe_summary"] == planting_text
    with transaction() as connection, connection.cursor() as cursor:
        late_id, _, _ = _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("task-created-after-cutoff"), chapter=100, text="Late projection cannot alter frozen discovery.",
            vector=(1.0, 0.0, 0.0), metadata={"fact_ids": ["fact:hook"]})
    replay = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=discovery.query_plan)
    assert late_id not in {item["retrieval_document_id"] for item in replay.documents}
    assert replay.query_plan == discovery.query_plan
    missing_plan = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"required_long_distance_fact_ids": ["missing:exact"]}, current_candidates=[]))
    with pytest.raises(KernelError) as missing:
        discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=missing_plan)
    assert missing.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"
    protected_plan = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"required_long_distance_fact_ids": ["current:exact"]}, current_candidates=[
            {"asset_type": "canon_snapshot", "asset_version_id": "canon:frozen", "content_hash": _sha("canon:frozen"),
             "structured_facts": [{"state": {"fact_id": "current:exact"}}]},
        ]))
    protected = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=protected_plan)
    assert protected.query_plan["task_dependency_discovery"]["protected_resolved_refs"] == ["current:exact"]


def test_obligation_only_dependencies_read_actual_events_not_inherited_active_ids() -> None:
    ensure_migrated()
    project_id = identifier("obligation-only-project")
    book_id = f"book:{project_id}"
    seed_authority_project_book(project_id=project_id, workspace_id=f"workspace:{project_id}", book_id=book_id)
    definition = identifier("obligation-only-definition")
    operation_id = identifier("obligation-only-operation")
    obligation = "obligation:old-promise"
    endpoints = {}
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation_id, definition_name=definition, project_id=project_id, status="SUCCEEDED")
        for chapter, event_id, status in ((1, "event:plant", "OPEN"), (4, "event:advance", "DEVELOPING")):
            event = {"event_id": event_id, "state_kind": "narrative_obligation", "identity": {"entity_key": f"obligation_id={obligation}"},
                     "coordinate": {"source_chapter": chapter}, "version": {"entity": 1 if chapter == 1 else 2},
                     "mutation": {"payload": {"obligation_id": obligation, "status": status, "priority": "LOW"}},
                     "causality": {"cause_refs": [f"draft:{chapter}"]}}
            unrelated = {**event, "event_id": f"unrelated:{chapter}", "state_kind": "character_belief",
                         "mutation": {"payload": {"subject_id": "unrelated", "belief": "Do not project this unrelated belief."}}}
            prose = f"Exact original prose {chapter}: only if the old promise remains unpaid."
            prose_id, prose_version, prose_hash = _seed_document(
                cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
                label=identifier(f"obligation-prose-{chapter}"), chapter=chapter, text=prose,
                vector=(1.0, 0.0, 0.0), obligation_ids=(obligation,),
            )
            content = {"state_events": [unrelated, event], "unrelated_metadata": "Do not require whole Outcome.",
                       "accepted_draft_asset_version_id": prose_version}
            outcome_id, outcome_version, outcome_hash = _seed_document(
                cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
                label=identifier(f"obligation-outcome-{chapter}"), chapter=chapter,
                text=json.dumps(content), vector=(1.0, 0.0, 0.0), source_artifact_type="chapter_outcome",
                source_content=content, memory_layer="L6", obligation_ids=(obligation,),
            )
            endpoints[chapter] = (outcome_id, outcome_version, outcome_hash, prose_id, prose_version, prose_hash, prose, event_id)
        for chapter in range(10, 280):
            _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
                           label=identifier(f"obligation-inherited-{chapter}"), chapter=chapter,
                           text="Recent material retaining the still-active obligation ID.", vector=(1.0, 0.0, 0.0), obligation_ids=(obligation,))
    intent = {"chapter": 301, "intent_fingerprint": _sha("obligation-intent"), "accepted_boundary": {"accepted_through_chapter": 300},
              "required_arc_contributions": [], "active_obligations": [{"state": {"obligation_id": obligation}}], "retrieval_graph": {}}
    memo = {"chapter": 301, "qualification": "QUALIFIED", "memo_fingerprint": _sha("obligation-memo"), "accepted_boundary": intent["accepted_boundary"],
            "retrieval_queries": ["Recent material"], "arc_actions": [], "obligation_actions": [{"obligation_id": obligation}]}
    plan = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"chapter": 301, "obligation_refs": [obligation]}, current_candidates=[]))
    discovery = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=plan)
    by_id = {item["retrieval_document_id"]: item for item in discovery.documents}
    endpoint_ids = {values[index] for values in endpoints.values() for index in (0, 3)}
    assert endpoint_ids <= set(by_id)
    assert len(by_id) == 260
    for outcome_id, outcome_version, outcome_hash, prose_id, prose_version, prose_hash, prose, event_id in endpoints.values():
        outcome = by_id[outcome_id]
        assert (outcome["source_asset_version_id"], outcome["source_content_hash"]) == (outcome_version, outcome_hash)
        assert outcome["metadata"]["task_dependency_projection"]["event_ids"] == [event_id]
        assert outcome["task_dependency_matched_refs"] == [event_id]
        assert "Do not project" not in outcome["content_text"] and "Do not require whole" not in outcome["content_text"]
        assert (by_id[prose_id]["source_asset_version_id"], by_id[prose_id]["source_content_hash"]) == (prose_version, prose_hash)
        assert by_id[prose_id]["content_text"] == prose
    trace = discovery.query_plan["task_dependency_discovery"]
    assert trace["required_obligation_ids"] == [obligation]
    assert set(trace["matched_documents_by_obligation"][obligation]) == endpoint_ids
    result = build_retrieval_result(project_id=project_id, book_id=book_id, intent_asset_version_id="intent:obligation", memo_asset_version_id="memo:obligation",
        query_plan=discovery.query_plan, documents=discovery.documents, discovery_rejections=discovery.rejected_documents, semantic_status=discovery.semantic_status)
    assert endpoint_ids <= {item["retrieval_document_id"] for item in result["selected_documents"]}
    assert len(result["selected_documents"]) == 28
    from novel_forge.modules.chapter_authority.provider_views import build_task_narrative_projection, project_retrieved_state_context
    for document in result["selected_documents"]:
        if document["retrieval_document_id"] in {values[0] for values in endpoints.values()}:
            projection = build_task_narrative_projection({"chapter": 301, "obligation_refs": [obligation]}, task_scoped=True)
            projection["required_event_refs"] = document["task_dependency_matched_refs"]
            consumed = project_retrieved_state_context(document["metadata"], projection=projection, chapter=301)
            assert {fact["source_event_id"] for fact in consumed["structured_facts"]} == set(document["task_dependency_matched_refs"])
    arguments = dict(project_id=project_id, book_id=book_id, intent_asset_version_id="intent:obligation", memo_asset_version_id="memo:obligation",
                     query_plan=discovery.query_plan, discovery_rejections=[], semantic_status={})
    with pytest.raises(KernelError) as omitted:
        build_retrieval_result(**arguments, documents=[item for item in discovery.documents if item["retrieval_document_id"] != endpoints[1][0]])
    assert omitted.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"
    replay = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=discovery.query_plan)
    assert replay.query_plan == discovery.query_plan
    assert replay.documents == discovery.documents
    missing = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"chapter": 301, "required_obligation_ids": ["obligation:missing"]}, current_candidates=[]))
    with pytest.raises(KernelError) as unavailable:
        discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=missing)
    assert unavailable.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"
    bad_boundary = {**intent["accepted_boundary"], "story_state_asset_version_id": "state:not-accepted", "canon_snapshot_asset_version_id": "canon:not-accepted"}
    unknown_lineage = build_retrieval_query_plan(intent={**intent, "accepted_boundary": bad_boundary}, memo={**memo, "accepted_boundary": bad_boundary}, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"chapter": 301, "obligation_refs": [obligation]}, current_candidates=[]))
    with pytest.raises(KernelError) as wrong_lineage:
        discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=unknown_lineage)
    assert wrong_lineage.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"
    retrieval_operation, worker = _start_retrieval_attempt(project_id)
    frozen_arguments = dict(database_url=DATABASE_URL, project_id=project_id, book_id=book_id,
        operation_id=retrieval_operation, attempt_id=worker.attempt_id, fencing_token=worker.fencing_token,
        worker_id=worker.worker_id, query_plan=discovery.query_plan, base_documents=discovery.documents,
        semantic_status=discovery.semantic_status)
    frozen = freeze_retrieval_candidate_union(**frozen_arguments)
    recovered = freeze_retrieval_candidate_union(**frozen_arguments)
    assert recovered.replayed and recovered.snapshot_hash == frozen.snapshot_hash
    assert recovered.documents == frozen.documents
    frozen_by_id = {item["retrieval_document_id"]: item for item in frozen.documents}
    for identity in endpoint_ids:
        for field in ("content_text", "metadata", "source_asset_version_id", "source_content_hash", "projection_hash", "task_dependency_matched_refs"):
            assert frozen_by_id[identity][field] == by_id[identity][field]
    with transaction() as connection, connection.cursor() as cursor:
        late_content = {"accepted_draft_asset_version_id": endpoints[4][4], "state_events": [
            {"event_id": "event:late-old-projection", "state_kind": "narrative_obligation", "coordinate": {"source_chapter": 1},
             "identity": {"entity_key": f"obligation_id={obligation}"}, "mutation": {"payload": {"obligation_id": obligation}}},
        ]}
        late_id, _, _ = _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("obligation-late-cutoff"), chapter=1, text=json.dumps(late_content), vector=(1.0, 0.0, 0.0),
            source_content=late_content, source_artifact_type="chapter_outcome", memory_layer="L6", obligation_ids=(obligation,))
        future_content = {**late_content, "state_events": [{**late_content["state_events"][0], "event_id": "event:future",
                          "coordinate": {"source_chapter": 301}}]}
        future_id, _, _ = _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation_id,
            label=identifier("obligation-future-cutoff"), chapter=301, text=json.dumps(future_content), vector=(1.0, 0.0, 0.0),
            source_content=future_content, source_artifact_type="chapter_outcome", memory_layer="L6", obligation_ids=(obligation,))
    replay = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=discovery.query_plan)
    assert replay.documents == discovery.documents and replay.query_plan == discovery.query_plan
    assert {late_id, future_id}.isdisjoint({item["retrieval_document_id"] for item in replay.documents})
    for version in (endpoints[1][1], endpoints[1][4]):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE authority_asset_version SET eligibility='REVOKED' WHERE asset_version_id=%s", [version])
        try:
            with pytest.raises(KernelError) as revoked:
                discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=discovery.query_plan)
            assert revoked.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"
        finally:
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute("UPDATE authority_asset_version SET eligibility='ELIGIBLE' WHERE asset_version_id=%s", [version])


@pytest.mark.parametrize("versions,expected", [
    ((3, 2, 1), {"event:plant", "event:latest"}),
    ((None, None, None), {"event:plant", "event:middle", "event:latest"}),
    ((3, 1, 1), {"event:plant", "event:middle", "event:latest"}),
    ((3, 2, 1), None),
])
def test_obligation_same_chapter_endpoints_use_entity_versions_or_keep_uncertain_boundary(versions, expected) -> None:
    ensure_migrated()
    project_id = identifier("obligation-order-project")
    book_id = f"book:{project_id}"
    seed_authority_project_book(project_id=project_id, workspace_id=f"workspace:{project_id}", book_id=book_id)
    definition, operation = identifier("obligation-order-definition"), identifier("obligation-order-operation")
    obligation = "obligation:reverse-order"
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation, definition_name=definition, project_id=project_id, status="SUCCEEDED")
        prose_id, prose_version, prose_hash = _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation,
            label=identifier("obligation-order-prose"), chapter=1, text="Exact planting and advances in one scene.", vector=(1.0, 0.0, 0.0), obligation_ids=(obligation,))
        events = [{"event_id": identity, "state_kind": "narrative_obligation", "identity": {"entity_key": f"obligation_id={obligation}"},
                   "coordinate": {"source_chapter": 1}, "version": {"entity": version} if version else {},
                   "mutation": {"payload": {"obligation_id": obligation, "status": "OPEN"}}}
                  for identity, version in zip(("event:latest", "event:middle", "event:plant"), versions)]
        if expected is None:
            events[0]["mutation"]["payload"]["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
        content = {"accepted_draft_asset_version_id": prose_version, "state_events": events}
        outcome_id, outcome_version, outcome_hash = _seed_document(cursor, project_id=project_id, book_id=book_id, source_operation_id=operation,
            label=identifier("obligation-order-outcome"), chapter=1, text=json.dumps(content), vector=(1.0, 0.0, 0.0),
            source_artifact_type="chapter_outcome", source_content=content, memory_layer="L6", obligation_ids=(obligation,))
    intent = {"chapter": 2, "intent_fingerprint": _sha("order-intent"), "accepted_boundary": {"accepted_through_chapter": 1},
              "active_obligations": [{"state": {"obligation_id": obligation}}]}
    memo = {"chapter": 2, "qualification": "QUALIFIED", "memo_fingerprint": _sha("order-memo"), "accepted_boundary": intent["accepted_boundary"],
            "retrieval_queries": ["one scene"]}
    query = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED",
        task_dependency_refs=build_task_dependency_refs(plan={"chapter": 2, "obligation_refs": [obligation]}, current_candidates=[]))
    if expected is None:
        with pytest.raises(KernelError) as hidden:
            discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=query)
        assert hidden.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"
        return
    discovery = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project_id, book_id=book_id, query_plan=query)
    by_id = {document["retrieval_document_id"]: document for document in discovery.documents}
    assert set(by_id) == {outcome_id, prose_id}
    outcome = by_id[outcome_id]
    assert set(outcome["task_dependency_matched_refs"]) == expected
    assert {event["event_id"] for event in json.loads(outcome["content_text"])["state_events"]} == expected
    assert outcome["metadata"]["task_dependency_projection"]["event_ordinals"] == [
        next(index for index, event in enumerate(events) if event["event_id"] == identity) for identity in sorted(expected)
    ]
    assert (outcome["source_asset_version_id"], outcome["source_content_hash"]) == (outcome_version, outcome_hash)
    assert (by_id[prose_id]["source_asset_version_id"], by_id[prose_id]["source_content_hash"]) == (prose_version, prose_hash)
