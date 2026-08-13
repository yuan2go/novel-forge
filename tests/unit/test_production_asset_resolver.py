from __future__ import annotations

from novel_forge.modules.production_preparation.contracts import (
    ResolvedProductionAsset,
)
from novel_forge.modules.production_preparation.resolver import (
    PostgresProductionAssetResolver,
)


def test_acceptance_binding_supplies_ephemeral_snapshot_chapter_metadata() -> None:
    asset = ResolvedProductionAsset(
        project_id="project-1",
        asset_id="story-state-1",
        asset_version_id="story-state-1:v1",
        asset_type="story_state_snapshot",
        content={"type": "StoryStateSnapshot", "state_version": 1},
        content_hash="sha256:story-state",
        qualification="ELIGIBLE",
        selected_reason="explicit audited AssetVersion override",
    )

    bound = PostgresProductionAssetResolver._bind_acceptance_scope(
        asset, "book-1", 1, "acceptance-1"
    )

    assert bound.content["chapter"] == 1
    assert bound.content["chapter_number"] == 1
    assert bound.content["accepted_through_chapter"] == 1
    assert bound.content["book_id"] == "book-1"
    assert bound.content["acceptance_id"] == "acceptance-1"
    assert bound.content["_authority_acceptance_bound"] is True
    assert "chapter" not in asset.content


def test_book_input_binding_supplies_ephemeral_initial_state_authority() -> None:
    asset = ResolvedProductionAsset(
        project_id="project-1",
        asset_id="initial-story-state-1",
        asset_version_id="initial-story-state-1:v1",
        asset_type="story_state_snapshot",
        content={
            "type": "StoryStateSnapshot",
            "contract_version": "story-state-snapshot-v2",
            "accepted_through_chapter": 0,
            "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
        },
        content_hash="sha256:initial-story-state",
        qualification="ELIGIBLE",
        selected_reason="explicit audited AssetVersion override",
    )

    bound = PostgresProductionAssetResolver._bind_initial_state_scope(
        asset, "book-1", "book-input-binding-1"
    )

    assert bound.content["chapter"] == 0
    assert bound.content["chapter_number"] == 0
    assert bound.content["accepted_through_chapter"] == 0
    assert bound.content["book_id"] == "book-1"
    assert bound.content["book_input_binding_id"] == "book-input-binding-1"
    assert bound.content["_authority_acceptance_bound"] is True
    assert "chapter" not in asset.content
