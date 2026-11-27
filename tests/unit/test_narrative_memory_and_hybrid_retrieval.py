from novel_forge.modules.context_builder.memory import (
    MEMORY_LAYER_CONTRACTS,
    NarrativeMemoryLayer,
)
from novel_forge.modules.context_builder.retrieval import (
    HybridRetrievalQuery,
    hybrid_retrieve,
)


def test_memory_layers_have_one_explicit_contract_and_authority_boundary() -> None:
    assert set(MEMORY_LAYER_CONTRACTS) == set(NarrativeMemoryLayer)
    assert MEMORY_LAYER_CONTRACTS[NarrativeMemoryLayer.L1_ACCEPTED_CURRENT_STATE].protected
    assert MEMORY_LAYER_CONTRACTS[NarrativeMemoryLayer.L2_CANON_FACT_GRAPH].protected
    assert MEMORY_LAYER_CONTRACTS[NarrativeMemoryLayer.L4_NARRATIVE_OBLIGATION_GRAPH].protected
    assert MEMORY_LAYER_CONTRACTS[NarrativeMemoryLayer.L5_ARC_NARRATIVE_DEBT].protected
    semantic = MEMORY_LAYER_CONTRACTS[NarrativeMemoryLayer.L7_SEMANTIC_RETRIEVAL_INDEX]
    assert semantic.mutation_rule == "rebuildable_only"
    assert semantic.protected is False


def test_hybrid_retrieval_combines_non_vector_signals_and_accepted_boundary() -> None:
    results = hybrid_retrieve(
        HybridRetrievalQuery(
            text="red key promise",
            accepted_through_chapter=20,
            entity_ids=("key",),
            relationship_ids=("rel-a",),
            character_ids=("char-a",),
            arc_plan_version_ids=("arc-a",),
            obligation_ids=("promise-a",),
            query_embedding=(1.0, 0.0),
        ),
        (
            {
                "retrieval_document_id": "multi-signal",
                "content_text": "the red key renews the promise",
                "accepted_from_chapter": 10,
                "entity_ids": ["key"],
                "relationship_ids": ["rel-a"],
                "character_ids": ["char-a"],
                "arc_plan_version_ids": ["arc-a"],
                "obligation_ids": ["promise-a"],
                "embedding": [0.0, 1.0],
            },
            {
                "retrieval_document_id": "vector-only",
                "content_text": "unrelated",
                "accepted_from_chapter": 19,
                "embedding": [1.0, 0.0],
            },
            {
                "retrieval_document_id": "future-generated",
                "content_text": "red key promise",
                "accepted_from_chapter": 21,
                "embedding": [1.0, 0.0],
            },
            {
                "retrieval_document_id": "expired-at-boundary",
                "content_text": "red key promise",
                "accepted_from_chapter": 5,
                "accepted_to_chapter": 19,
                "embedding": [1.0, 0.0],
            },
        ),
    )

    assert [item["retrieval_document_id"] for item in results] == [
        "multi-signal",
        "vector-only",
    ]
    assert "embedding" not in results[0]["retrieval_reasons"]
    assert {"lexical", "entity", "relationship", "arc", "obligation"}.issubset(
        results[0]["retrieval_reasons"]
    )
