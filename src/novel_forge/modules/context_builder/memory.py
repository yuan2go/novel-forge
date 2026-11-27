from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NarrativeMemoryLayer(StrEnum):
    L0_RECENT_VERBATIM = "L0"
    L1_ACCEPTED_CURRENT_STATE = "L1"
    L2_CANON_FACT_GRAPH = "L2"
    L3_CHARACTER_RELATIONSHIP_TIMELINE = "L3"
    L4_NARRATIVE_OBLIGATION_GRAPH = "L4"
    L5_ARC_NARRATIVE_DEBT = "L5"
    L6_EPISODIC_SUMMARIES = "L6"
    L7_SEMANTIC_RETRIEVAL_INDEX = "L7"
    L8_FULL_HISTORICAL_ARCHIVE = "L8"
    L9_EXTERNAL_KNOWLEDGE = "L9"


@dataclass(frozen=True, slots=True)
class MemoryLayerContract:
    layer: NarrativeMemoryLayer
    authoritative_source: str
    owner: str
    mutation_rule: str
    lifecycle: str
    index_policy: str
    retrieval_responsibility: str
    protected: bool


MEMORY_LAYER_CONTRACTS = {
    NarrativeMemoryLayer.L0_RECENT_VERBATIM: MemoryLayerContract(
        NarrativeMemoryLayer.L0_RECENT_VERBATIM, "accepted_chapter_text", "BookAuthority",
        "append_on_book_acceptance", "rolling_window", "verbatim_window",
        "local continuity and voice", True,
    ),
    NarrativeMemoryLayer.L1_ACCEPTED_CURRENT_STATE: MemoryLayerContract(
        NarrativeMemoryLayer.L1_ACCEPTED_CURRENT_STATE, "accepted_story_state", "BookAuthority",
        "deterministic_acceptance_reducer", "current_pointer_plus_history", "none",
        "current narrative facts", True,
    ),
    NarrativeMemoryLayer.L2_CANON_FACT_GRAPH: MemoryLayerContract(
        NarrativeMemoryLayer.L2_CANON_FACT_GRAPH, "accepted_canon", "BookAuthority",
        "deterministic_acceptance_reducer", "append_only_versions", "entity_graph",
        "world and continuity truth", True,
    ),
    NarrativeMemoryLayer.L3_CHARACTER_RELATIONSHIP_TIMELINE: MemoryLayerContract(
        NarrativeMemoryLayer.L3_CHARACTER_RELATIONSHIP_TIMELINE, "accepted_state_projection", "BookAuthority",
        "rebuildable_projection", "accepted_history", "entity_relationship_temporal",
        "character and relationship history", False,
    ),
    NarrativeMemoryLayer.L4_NARRATIVE_OBLIGATION_GRAPH: MemoryLayerContract(
        NarrativeMemoryLayer.L4_NARRATIVE_OBLIGATION_GRAPH, "accepted_obligation_state", "BookAuthority",
        "deterministic_acceptance_reducer", "current_plus_history", "obligation_graph",
        "setup payoff and reader promise", True,
    ),
    NarrativeMemoryLayer.L5_ARC_NARRATIVE_DEBT: MemoryLayerContract(
        NarrativeMemoryLayer.L5_ARC_NARRATIVE_DEBT, "accepted_arc_projection", "BookAuthority",
        "deterministic_acceptance_reducer", "current_plus_checkpoints", "arc_graph",
        "long-form progress and debt", True,
    ),
    NarrativeMemoryLayer.L6_EPISODIC_SUMMARIES: MemoryLayerContract(
        NarrativeMemoryLayer.L6_EPISODIC_SUMMARIES, "accepted_chapter_outcome", "BookFollowupAuthority",
        "candidate_before_acceptance_or_sidecar_after", "append_only", "lexical_temporal",
        "episodic recall", False,
    ),
    NarrativeMemoryLayer.L7_SEMANTIC_RETRIEVAL_INDEX: MemoryLayerContract(
        NarrativeMemoryLayer.L7_SEMANTIC_RETRIEVAL_INDEX, "accepted_artifact_projection", "RetrievalProjection",
        "rebuildable_only", "replaceable_index", "embedding_and_rerank",
        "semantic candidate retrieval", False,
    ),
    NarrativeMemoryLayer.L8_FULL_HISTORICAL_ARCHIVE: MemoryLayerContract(
        NarrativeMemoryLayer.L8_FULL_HISTORICAL_ARCHIVE, "accepted_asset_versions", "AssetAuthority",
        "immutable_append", "permanent", "archive_locator",
        "exact historical evidence", False,
    ),
    NarrativeMemoryLayer.L9_EXTERNAL_KNOWLEDGE: MemoryLayerContract(
        NarrativeMemoryLayer.L9_EXTERNAL_KNOWLEDGE, "governed_knowledge_assets", "MKAOSAuthority",
        "authority_qualified_versions_only", "versioned", "lexical_semantic",
        "research and reference knowledge", False,
    ),
}


__all__ = ["MEMORY_LAYER_CONTRACTS", "MemoryLayerContract", "NarrativeMemoryLayer"]
