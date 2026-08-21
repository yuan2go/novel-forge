from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import (
    build_retrieval_query_plan,
    build_retrieval_result,
)


def _intent() -> dict[str, object]:
    return {
        "chapter": 9,
        "intent_fingerprint": "sha256:" + "1" * 64,
        "accepted_boundary": {"accepted_through_chapter": 8},
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc:trust:v3"}
        ],
        "active_obligations": [
            {"state": {"obligation_id": "promise:return-key"}}
        ],
        "retrieval_graph": {
            "entity_ids": ["key:red"],
            "character_ids": ["character:mei"],
            "relationship_ids": ["relationship:mei-ren"],
        },
    }


def _memo() -> dict[str, object]:
    return {
        "chapter": 9,
        "qualification": "QUALIFIED",
        "memo_fingerprint": "sha256:" + "2" * 64,
        "accepted_boundary": {"accepted_through_chapter": 8},
        "retrieval_queries": ["red key promise", "Mei and Ren trust"],
        "arc_actions": [{"arc_plan_version_id": "arc:trust:v3"}],
        "obligation_actions": [{"obligation_id": "promise:return-key"}],
    }


def _document() -> dict[str, object]:
    return {
        "retrieval_document_id": "retrieval:accepted:7",
        "source_asset_version_id": "draft:accepted:7:v1",
        "source_artifact_type": "best_draft_candidate",
        "source_content_hash": "sha256:" + "3" * 64,
        "projection_hash": "sha256:" + "4" * 64,
        "accepted_from_chapter": 7,
        "accepted_to_chapter": None,
        "memory_layer": "L0",
        "content_text": "Mei returns the red key but Ren no longer trusts the promise.",
        "postgresql_fts_rank": 0.8,
        "entity_ids": ["key:red"],
        "character_ids": ["character:mei"],
        "relationship_ids": ["relationship:mei-ren"],
        "arc_plan_version_ids": ["arc:trust:v3"],
        "obligation_ids": ["promise:return-key"],
        "temporal_coordinate": {"accepted_chapter": 7},
        "metadata": {"projection_kind": "recent_accepted_prose"},
        "embedding": [1.0, 0.0],
        "embedding_model": "embedding-production-v1",
        "embedding_provider": "production-provider",
        "embedding_dimensions": 2,
        "embedding_route_snapshot_id": "route:embedding:v1",
        "embedding_receipt_id": "receipt:embedding:7",
        "embedding_projection_version": "accepted-retrieval-embedding-v1",
    }


def test_memo_is_the_authoritative_retrieval_query_input() -> None:
    plan = build_retrieval_query_plan(intent=_intent(), memo=_memo())

    assert plan["queries"] == ["red key promise", "Mei and Ren trust"]
    assert plan["accepted_boundary"] == {"accepted_through_chapter": 8}
    assert plan["arc_plan_version_ids"] == ["arc:trust:v3"]
    assert plan["obligation_ids"] == ["promise:return-key"]
    assert plan["semantic_policy"] == "FALLBACK_ALLOWED"


def test_retrieval_result_is_reproducible_and_records_all_ranking_provenance() -> None:
    plan = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    arguments = {
        "project_id": "project:novel",
        "book_id": "book:novel",
        "intent_asset_version_id": "intent:v1",
        "memo_asset_version_id": "memo:v1",
        "query_plan": plan,
        "documents": [_document()],
        "discovery_rejections": [
            {
                "retrieval_document_id": "retrieval:future:10",
                "source_asset_version_id": "draft:future:10",
                "source_content_hash": "sha256:" + "5" * 64,
                "accepted_from_chapter": 10,
                "accepted_to_chapter": None,
                "reason": "FUTURE_ACCEPTED_BOUNDARY",
            }
        ],
        "semantic_status": {
            "policy": "FALLBACK_ALLOWED",
            "status": "RETRIEVAL_SEMANTIC_PROJECTION_READY",
        },
        "query_embedding": [1.0, 0.0],
        "query_embedding_evidence": {
            "provider_id": "production-provider",
            "model_id": "embedding-production-v1",
            "receipt_id": "receipt:query:9",
        },
    }

    first = build_retrieval_result(**arguments)
    second = build_retrieval_result(**arguments)

    assert first == second
    assert first["result_fingerprint"].startswith("sha256:")
    selected = first["selected_documents"][0]
    assert {
        "postgresql_fts",
        "embedding",
        "entity",
        "relationship",
        "character_timeline",
        "temporal",
        "arc",
        "obligation",
    }.issubset(selected["retrieval_scores"])
    assert selected["compression_provenance"]["source_content_hash"] == (
        "sha256:" + "3" * 64
    )
    assert first["rejected_documents"][0]["reason"] == (
        "FUTURE_ACCEPTED_BOUNDARY"
    )


def test_semantic_required_policy_is_explicit_not_a_silent_fallback() -> None:
    plan = build_retrieval_query_plan(
        intent=_intent(), memo=_memo(), semantic_policy="REQUIRED"
    )
    assert plan["semantic_policy"] == "REQUIRED"

    with pytest.raises(KernelError, match="semantic retrieval policy"):
        build_retrieval_query_plan(
            intent=_intent(), memo=_memo(), semantic_policy="BEST_EFFORT"
        )
