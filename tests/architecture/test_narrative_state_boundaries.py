from __future__ import annotations

from pathlib import Path

from novel_forge.modules.narrative_state import NarrativeLayer, NarrativeStateKind
from novel_forge.modules.narrative_state.reducers import (
    STATE_KIND_REDUCER_SEMANTICS,
)
from novel_forge.modules.production_preparation.policies import (
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
)


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_event_current_projection_and_intent_are_distinct_contract_layers() -> None:
    assert {
        NarrativeLayer.TRUTH,
        NarrativeLayer.ACCEPTED_ACTUAL,
        NarrativeLayer.STATE_EVENT,
        NarrativeLayer.CURRENT_STATE,
        NarrativeLayer.TEMPORAL_PROJECTION,
        NarrativeLayer.FUTURE_INTENT,
        NarrativeLayer.EXECUTION_CONTEXT,
        NarrativeLayer.RETRIEVABLE_KNOWLEDGE,
        NarrativeLayer.OBSERVATION,
    } == set(NarrativeLayer)
    assert set(STATE_KIND_REDUCER_SEMANTICS) == set(NarrativeStateKind)
    assert len(set(STATE_KIND_REDUCER_SEMANTICS.values())) >= 8


def test_continuing_context_accepts_only_compact_authoritative_v2_state() -> None:
    policies = _read(
        "src/novel_forge/modules/production_preparation/policies.py"
    )
    resolver = _read(
        "src/novel_forge/modules/production_preparation/resolver.py"
    )
    service = _read(
        "src/novel_forge/modules/production_preparation/service.py"
    )
    assert CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES == (
        "story_state_snapshot",
        "canon_snapshot",
    )
    for retired_delta_snapshot in (
        "character_state_snapshot",
        "relationship_state_snapshot",
        "timeline_snapshot",
        "promise_ledger_snapshot",
        "resource_state_snapshot",
    ):
        assert retired_delta_snapshot not in policies
    assert "authority_book_chapter_acceptance" in resolver
    assert "COMMITTED" in resolver
    assert "story-state-snapshot-v2" in service
    assert "canon-snapshot-v2" in service


def test_temporal_query_is_accepted_state_only_and_has_no_mutation_path() -> None:
    temporal = _read("src/novel_forge/modules/temporal_query/service.py")
    migration = _read(
        "src/novel_forge/storage/migrations/versions/"
        "v20260812_0082_narrative_state_contract_v2.py"
    )
    assert "authority_narrative_state_event_projection" in temporal
    assert "authority_temporal_state_event_projection" not in temporal
    assert "accepted_chapter <= %s" in temporal
    assert (
        "ORDER BY accepted_chapter, event_ordinal,\n"
        "                         chapter_outcome_asset_version_id"
    ) in temporal
    assert "recorded_at" not in temporal.split("def _event_order", 1)[1]
    for mutation in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert mutation not in temporal
    assert "authority_book_chapter_acceptance" in migration
    assert "acceptance.status='COMMITTED'" in migration
    assert "effective_from_chapter" in migration


def test_truth_actual_state_plan_context_and_knowledge_ownership_stays_separate() -> None:
    outcome = _read("src/novel_forge/modules/chapter_outcome/domain.py")
    reducer = _read("src/novel_forge/modules/narrative_state/reducers.py")
    planning = _read("src/novel_forge/modules/story_planning_runtime/domain.py")
    context = _read("src/novel_forge/modules/context_builder/domain.py")
    assert '"layer": "ACCEPTED_ACTUAL"' in outcome
    assert "PENDING_BOOK_ACCEPTANCE" in outcome
    assert "NarrativeLayer.CURRENT_STATE.value" in reducer
    assert "COMMITTED_BOOK_CHAPTER_ACCEPTANCE" in reducer
    assert '"authority.commit"' not in planning
    for forbidden in ("AuthorityUnitOfWork", "INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert forbidden not in context


def test_v2_has_one_temporal_and_supersession_vocabulary() -> None:
    contracts = _read("src/novel_forge/modules/narrative_state/contracts.py")
    event_contract = contracts.split("class NarrativeStateEvent:", 1)[1].split(
        "_PATCH_FIELDS", 1
    )[0]
    assert "source_chapter" in event_contract
    assert "effective_from_chapter" in event_contract
    assert "supersedes_event_id" in event_contract
    for legacy_alias in (
        "supersedes_version_id",
        "supersedes_asset_version_id",
        "state_version_id",
        "effective_chapter",
    ):
        assert legacy_alias not in event_contract
