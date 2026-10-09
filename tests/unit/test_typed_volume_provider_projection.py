from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.provider_views import _project_planning_content
from novel_forge.modules.command_kernel.errors import KernelError


def test_arc_volume_projection_preserves_story_constraints_and_audits_metadata():
    content = {"objective": "Find a route to the sky", "chapter_range": [1, 48],
        "hard_constraints": ["Preserve the chosen protagonist"], "planning_scope": "VOLUME",
        "generator_operation_name": "volume_plan.generate", "diagnostic_notes": "retained original operational notes"}
    original = deepcopy(content)
    source = {"role": "arc_scope_volume:1", "asset_type": "planning_generation_candidate",
        "asset_version_id": "original-volume", "content_hash": "original-hash"}
    losses = []
    projected, _, _ = _project_planning_content(stage="arc_plan.generate", role=source["role"],
        content=content, chapter=0, selectors=frozenset(), source=source,
        loss_records=losses, typed_volume_sources=True)
    assert projected["objective"] == content["objective"]
    assert projected["chapter_range"] == [1, 48]
    assert projected["hard_constraints"] == content["hard_constraints"]
    assert "diagnostic_notes" not in projected
    assert any(loss["path"] == "/diagnostic_notes" for loss in losses)
    assert content == original


@pytest.mark.parametrize("asset_type,scope", [("draft_version", "VOLUME"), ("planning_generation_candidate", "CHAPTER")])
def test_arc_volume_projection_rejects_foreign_asset_types(asset_type, scope):
    with pytest.raises(KernelError, match="PLANNING_PROVIDER_CONTEXT_VIEW_INVALID"):
        _project_planning_content(stage="arc_plan.generate", role="arc_scope_volume:1",
            content={"planning_scope": scope, "generator_operation_name": "volume_plan.generate"},
            chapter=0, selectors=frozenset(), source={"asset_type": asset_type}, typed_volume_sources=True)
