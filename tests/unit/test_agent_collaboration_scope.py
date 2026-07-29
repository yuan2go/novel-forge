from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from novel_forge.modules.agent_collaboration import (
    AgentOutputEnvelope,
    AgentScopeContract,
    AssetReadScope,
    AuthorityScope,
    KnowledgeVisibility,
    KnowledgeVisibilityScope,
    NarrativeScope,
    NarrativeScopeType,
    ProposalScope,
    ProposedAssetChange,
    ScopePolicy,
    TemporalScope,
)


def book_scope() -> AgentScopeContract:
    return AgentScopeContract(
        scope_contract_id="scope-contract:core-advantage",
        version=1,
        narrative=NarrativeScope(
            kind=NarrativeScopeType.BOOK,
            book_id="book:1",
        ),
        asset_read=AssetReadScope(
            allowed_asset_types=(
                "book_design_candidate",
                "character_card",
                "plot_plan",
            ),
            asset_version_ids=(
                "asset-version:character:1",
                "asset-version:plot:1",
            ),
        ),
        proposal=ProposalScope(
            allowed_asset_types=("book_design_candidate",),
            allowed_change_types=(
                "core_advantage.create",
                "core_advantage.revise",
            ),
            forbidden_asset_types=("canon", "published_chapter"),
            forbidden_change_types=("ending.replace", "canon.mutate"),
        ),
        authority=AuthorityScope(
            authority_type="BOOK_DESIGN_AUTHORITY",
            allowed_narrative_scopes=(NarrativeScopeType.BOOK,),
            allowed_change_types=(
                "core_advantage.create",
                "core_advantage.revise",
            ),
        ),
        temporal=TemporalScope(
            past_locked_through=0,
            active_range=(1, 120),
            forecast_horizon=120,
            published_boundary=0,
        ),
        knowledge=KnowledgeVisibilityScope(
            allowed=(
                KnowledgeVisibility.AUTHOR_KNOWLEDGE,
                KnowledgeVisibility.PUBLIC_CANON,
                KnowledgeVisibility.HIDDEN_PLANNING,
            )
        ),
    )


class AgentScopeContractTests(unittest.TestCase):
    def test_narrative_scope_contains_only_same_book_descendants(self) -> None:
        container = NarrativeScope(kind="BOOK", book_id="book:1")
        chapter = NarrativeScope(
            kind="CHAPTER",
            book_id="book:1",
            volume_id="volume:1",
            arc_id="arc:1",
            chapter_group_id="chapter-group:1",
            chapter_id="chapter:12",
        )
        other_book = NarrativeScope(
            kind="CHAPTER",
            book_id="book:2",
            volume_id="volume:1",
            arc_id="arc:1",
            chapter_group_id="chapter-group:1",
            chapter_id="chapter:12",
        )

        self.assertTrue(container.contains(chapter))
        self.assertFalse(chapter.contains(container))
        self.assertFalse(container.contains(other_book))

    def test_narrative_scope_requires_every_ancestor(self) -> None:
        with self.assertRaisesRegex(ValueError, "volume_id"):
            NarrativeScope(
                kind=NarrativeScopeType.ARC,
                book_id="book:1",
                arc_id="arc:1",
            )

    def test_temporal_scope_rejects_inverted_or_published_active_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "active range"):
            TemporalScope(
                past_locked_through=10,
                active_range=(8, 20),
                forecast_horizon=20,
                published_boundary=10,
            )
        with self.assertRaisesRegex(ValueError, "forecast horizon"):
            TemporalScope(
                past_locked_through=0,
                active_range=(1, 21),
                forecast_horizon=20,
                published_boundary=0,
            )

    def test_scope_snapshot_is_stable_and_immutable(self) -> None:
        contract = book_scope()
        first = contract.freeze(
            snapshot_id="scope-snapshot:1",
            authority_id="book-design-authority:1",
        )
        second = contract.freeze(
            snapshot_id="scope-snapshot:2",
            authority_id="book-design-authority:1",
        )

        self.assertEqual(first.scope_hash, second.scope_hash)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        with self.assertRaises(FrozenInstanceError):
            first.authority_id = "mutated"  # type: ignore[misc]

    def test_valid_proposal_passes_all_six_scope_dimensions(self) -> None:
        snapshot = book_scope().freeze(
            snapshot_id="scope-snapshot:1",
            authority_id="book-design-authority:1",
        )
        envelope = _envelope(
            changes=(
                ProposedAssetChange(
                    asset_type="book_design_candidate",
                    asset_version_id="",
                    narrative_scope=NarrativeScope(
                        kind="BOOK",
                        book_id="book:1",
                    ),
                    change_type="core_advantage.create",
                    knowledge_visibility=KnowledgeVisibility.HIDDEN_PLANNING,
                    chapter_number=None,
                    touches_published_content=False,
                ),
            )
        )

        result = ScopePolicy.validate_output(snapshot, envelope)

        self.assertTrue(result.compliant)
        self.assertEqual(result.violations, ())

    def test_chapter_agent_cannot_modify_arc_or_expand_scope(self) -> None:
        contract = book_scope()
        chapter_contract = AgentScopeContract(
            scope_contract_id=contract.scope_contract_id,
            version=2,
            narrative=NarrativeScope(
                kind="CHAPTER",
                book_id="book:1",
                volume_id="volume:1",
                arc_id="arc:1",
                chapter_group_id="chapter-group:1",
                chapter_id="chapter:12",
            ),
            asset_read=contract.asset_read,
            proposal=contract.proposal,
            authority=contract.authority,
            temporal=contract.temporal,
            knowledge=contract.knowledge,
        )
        envelope = _envelope(
            changes=(
                ProposedAssetChange(
                    asset_type="book_design_candidate",
                    asset_version_id="asset-version:plot:1",
                    narrative_scope=NarrativeScope(
                        kind="ARC",
                        book_id="book:1",
                        volume_id="volume:1",
                        arc_id="arc:1",
                    ),
                    change_type="core_advantage.revise",
                    knowledge_visibility=KnowledgeVisibility.HIDDEN_PLANNING,
                ),
            )
        )

        result = ScopePolicy.validate_output(
            chapter_contract.freeze(
                snapshot_id="scope-snapshot:chapter",
                authority_id="chapter-authority:1",
            ),
            envelope,
        )

        self.assertFalse(result.compliant)
        self.assertTrue(result.requires_scope_expansion)
        self.assertIn("NARRATIVE_SCOPE_VIOLATION", result.violations)

    def test_reader_agent_cannot_read_hidden_ending(self) -> None:
        contract = book_scope()
        reader_contract = AgentScopeContract(
            scope_contract_id=contract.scope_contract_id,
            version=3,
            narrative=contract.narrative,
            asset_read=contract.asset_read,
            proposal=contract.proposal,
            authority=contract.authority,
            temporal=contract.temporal,
            knowledge=KnowledgeVisibilityScope(
                allowed=(
                    KnowledgeVisibility.READER_KNOWLEDGE,
                    KnowledgeVisibility.PUBLIC_CANON,
                )
            ),
        )
        envelope = _envelope(
            accessed_knowledge=(KnowledgeVisibility.HIDDEN_PLANNING,)
        )

        result = ScopePolicy.validate_output(
            reader_contract.freeze(
                snapshot_id="scope-snapshot:reader",
                authority_id="book-design-authority:1",
            ),
            envelope,
        )

        self.assertFalse(result.compliant)
        self.assertIn("KNOWLEDGE_VISIBILITY_VIOLATION", result.violations)

    def test_character_agent_cannot_modify_canon_or_published_chapter(self) -> None:
        snapshot = book_scope().freeze(
            snapshot_id="scope-snapshot:1",
            authority_id="book-design-authority:1",
        )
        canon = ProposedAssetChange(
            asset_type="canon",
            asset_version_id="canon:1",
            narrative_scope=snapshot.contract.narrative,
            change_type="canon.mutate",
            knowledge_visibility=KnowledgeVisibility.PUBLIC_CANON,
        )
        published = ProposedAssetChange(
            asset_type="published_chapter",
            asset_version_id="chapter:1:v3",
            narrative_scope=NarrativeScope(
                kind="CHAPTER",
                book_id="book:1",
                volume_id="volume:1",
                arc_id="arc:1",
                chapter_group_id="chapter-group:1",
                chapter_id="chapter:1",
            ),
            change_type="core_advantage.revise",
            knowledge_visibility=KnowledgeVisibility.PUBLIC_CANON,
            chapter_number=1,
            touches_published_content=True,
        )

        result = ScopePolicy.validate_output(
            snapshot,
            _envelope(changes=(canon, published)),
        )

        self.assertFalse(result.compliant)
        self.assertIn("PROPOSAL_SCOPE_VIOLATION", result.violations)
        self.assertIn("PUBLISHED_BOUNDARY_VIOLATION", result.violations)


def _envelope(
    *,
    changes: tuple[ProposedAssetChange, ...] = (),
    accessed_knowledge: tuple[KnowledgeVisibility, ...] = (),
) -> AgentOutputEnvelope:
    return AgentOutputEnvelope(
        output_id="output:1",
        session_id="session:1",
        turn_id="turn:1",
        agent_id="agent:character",
        message_type="PROPOSAL",
        structured_payload={"claim": "bounded proposal"},
        natural_language_explanation="A bounded explanation.",
        source_asset_versions=("asset-version:character:1",),
        evidence_refs=("evidence:1",),
        assumptions=("The book remains unpublished.",),
        confidence=0.8,
        affected_assets=tuple(change.asset_type for change in changes),
        proposed_changes=changes,
        preserved_constraints=("ending remains unchanged",),
        accessed_knowledge=accessed_knowledge,
        unresolved_questions=(),
        risk_level="MEDIUM",
        requested_next_action="CHALLENGE",
        execution_evidence_ref="execution-evidence:1",
    )

if __name__ == "__main__":
    unittest.main()
