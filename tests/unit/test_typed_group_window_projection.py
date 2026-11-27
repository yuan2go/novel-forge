from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.provider_views import _project_planning_content, compile_planning_provider_context
from novel_forge.modules.command_kernel.errors import KernelError


def test_group_projection_keeps_overlapping_segments_and_global_constraints_with_audit():
    content = {"hard_constraints": ["Keep the author's sky-travel objective"],
        "arc_segments": [{"chapter_range": [1, 2], "objective": "Departure"},
            {"chapter_range": [3, 8], "objective": "Flight"},
            {"chapter_range": [9, 48], "objective": "Later journey"}]}
    original = deepcopy(content)
    losses = []
    projected, _, _ = _project_planning_content(stage="chapter_group_plan.generate", role="arc_plans",
        content=content, chapter=0, selectors=frozenset(), loss_records=losses,
        source={"asset_version_id": "arc-original", "content_hash": "arc-hash"}, planning_window=[1, 3])
    assert projected["arc_segments"] == content["arc_segments"][:2]
    assert projected["hard_constraints"] == content["hard_constraints"]
    assert content == original
    assert losses[0]["path"] == "/arc_segments"
    assert losses[0]["removed_item_count"] == 1
    assert losses[0]["source_content_hash"] == "arc-hash"


@pytest.mark.parametrize("horizon,stage", [({}, "chapter_group_plan.generate"),
    ({"level": "CHAPTER_GROUP", "chapter_range": [3, 1]}, "chapter_group_plan.generate"),
    ({"level": "CHAPTER_GROUP", "chapter_range": [True, 3]}, "chapter_group_plan.generate"),
    ({"level": "CHAPTER_GROUP", "chapter_range": [1, 3]}, "arc_plan.generate")])
def test_window_projection_requires_exact_frozen_group_horizon(horizon, stage):
    with pytest.raises(KernelError, match="PLANNING_PROVIDER_CONTEXT_VIEW_INVALID"):
        compile_planning_provider_context(stage, {"schema_version": "novelos.planning_context_bundle.v1",
            "typed_window_projection_version": "typed-planning-window-projection.v1",
            "narrative_search": {"planning_horizon": horizon}})
