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

    bound = PostgresProductionAssetResolver._bind_acceptance_chapter(asset, 1)

    assert bound.content["chapter"] == 1
    assert bound.content["chapter_number"] == 1
    assert bound.content["_authority_acceptance_bound"] is True
    assert "chapter" not in asset.content
