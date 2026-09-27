from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.editions import (
    derived_invalidations, edition_diff, edition_manifest, require_manifest, revise_manifest,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash


def base_manifest():
    return edition_manifest({"project_id": "p", "workspace_id": "w", "book_id": "b", "book_run_id": "run"}, [
        {"acceptance_id": f"accepted-{i}", "asset_version_id": f"draft-{i}", "asset_hash": "sha256:" + str(i) * 64,
         "chapter_plan_asset_version_id": f"plan-{i}", "text": text, "title": str(i)}
        for i, text in enumerate(("沈砚答应日落前归还药匣。\n他把唯一的剑押在渡口。", "日落后，他空手回到渡口，坦言救人用尽了药。"), 1)
    ])


def test_expression_edit_keeps_exact_original_and_invalidates_suffix():
    base = base_manifest()
    original = deepcopy(base)
    units = deepcopy(base["units"])
    units[1]["text"] = units[1]["text"].replace("坦言", "低声承认")
    result = revise_manifest(base, units=units, reason="调整台词语气", change_kind="EXPRESSION")
    assert base == original
    assert result["impact"]["earliest_affected_position"] == 2
    assert result["impact"]["required_revalidation_unit_ids"] == [units[1]["unit_id"]]
    assert result["impact"]["review_signatures"] == "INVALIDATED"
    assert result["publication_authorized"] is False
    assert "低声承认" in edition_diff(base, result)["changes"][0]["diff"]
    require_manifest(result)


def test_split_and_reorder_use_source_spans_and_stable_ids():
    base = base_manifest()
    first, second = deepcopy(base["units"])
    left, right = deepcopy(first), deepcopy(first)
    split = first["text"].index("\n") + 1
    for unit, identity, start, end in ((left, "departure", 0, split), (right, "pledge", split, len(first["text"]))):
        unit["unit_id"] = identity
        unit["text"] = first["text"][start:end]
        unit["source_ranges"][0].update(start=start, end=end, text_hash=prose_hash(unit["text"]))
    result = revise_manifest(base, units=[second, left, right], reason="先呈现失约，再回溯承诺", change_kind="STRUCTURE")
    assert result["impact"]["earliest_affected_position"] == 1
    assert [unit["unit_id"] for unit in result["units"]] == [second["unit_id"], "departure", "pledge"]
    assert {item["unit_id"] for item in derived_invalidations(base, result, [first["unit_id"], second["unit_id"]])} == {first["unit_id"], second["unit_id"]}
    with pytest.raises(KernelError, match="structural"):
        revise_manifest(base, units=[second, left, right], reason="回溯", change_kind="EXPRESSION")


@pytest.mark.parametrize("fault", ["overlap", "missing", "wrong_hash", "wrong_range"])
def test_mapping_cannot_hide_source_loss_or_drift(fault):
    base = base_manifest()
    units = deepcopy(base["units"])
    if fault == "overlap":
        units[0]["source_ranges"].append(deepcopy(units[0]["source_ranges"][0]))
    elif fault == "missing":
        units.pop()
    elif fault == "wrong_hash":
        units[0]["source_ranges"][0]["asset_hash"] = "changed"
    else:
        units[0]["source_ranges"][0]["end"] -= 1
    with pytest.raises(KernelError):
        revise_manifest(base, units=units, reason="编辑", change_kind="UNKNOWN")


def test_explicit_removal_preserves_mapping_and_stale_hash_is_rejected():
    base = base_manifest()
    candidate = revise_manifest(base, units=[deepcopy(base["units"][1])],
                                removed_source_ranges=base["units"][0]["source_ranges"], reason="删去回忆场景", change_kind="STRUCTURE")
    assert candidate["removed_source_ranges"]
    candidate["units"][0]["text"] += "未冻结的改动"
    with pytest.raises(KernelError, match="digest"):
        require_manifest(candidate)


def test_following_edit_retains_prior_explicit_removal_and_original_source():
    base = base_manifest()
    removed = revise_manifest(base, units=[deepcopy(base["units"][1])], removed_source_ranges=base["units"][0]["source_ranges"],
                              reason="删去回忆场景", change_kind="STRUCTURE")
    units = deepcopy(removed["units"])
    units[0]["text"] = units[0]["text"].replace("坦言", "低声承认")
    revised = revise_manifest(removed, units=units, reason="继续修改表达", change_kind="EXPRESSION")
    assert revised["removed_source_ranges"] == removed["removed_source_ranges"]
    assert revised["sources"] == base["sources"]
    with pytest.raises(KernelError, match="EDITION_MAPPING_INCOMPLETE"):
        revise_manifest(removed, units=units, reason="不可抹去删除映射", change_kind="EXPRESSION", removed_source_ranges=[])


def test_derived_range_outside_changed_unit_is_still_exact():
    base = base_manifest()
    units = deepcopy(base["units"])
    units[1]["text"] += "他决定亲自去采药。"
    candidate = revise_manifest(base, units=units, reason="补充行动选择", change_kind="NARRATIVE_FACT")
    assert derived_invalidations(base, candidate, [units[0]["unit_id"]]) == []
    assert derived_invalidations(base, candidate, [units[1]["unit_id"]])[0]["reason"] == "SOURCE_CHANGED"


@pytest.mark.parametrize("explicit_scene_field", [True, False])
def test_expression_edit_retains_multiple_realization_slots_in_one_scene(explicit_scene_field):
    from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
    base = base_manifest()
    source = base["sources"][0]
    source["scene_artifacts"] = [{"scene_id": "scene:1", "slot_id": "scene:1:skeleton", "text": "他答应归还药匣。"},
                                 {"scene_id": "scene:1", "slot_id": "scene:1:action", "text": "他把剑押在渡口。"}]
    source["scene_mapping"] = [{"slot_id": scene["slot_id"], "scene_id": scene["scene_id"]} for scene in source["scene_artifacts"]]
    if not explicit_scene_field:
        for scene in source["scene_artifacts"]:
            del scene["scene_id"]
            scene["used_fact_ids"] = []
    source["text"] = serialize_realization(source["scene_artifacts"])
    base = edition_manifest({key: base[key] for key in ("project_id", "workspace_id", "book_id", "book_run_id")}, base["sources"])
    units = deepcopy(base["units"])
    units[0]["scene_artifacts"][1]["text"] = "他将剑轻轻压在渡口的木案上。"
    units[0]["text"] = serialize_realization(units[0]["scene_artifacts"])
    edited = revise_manifest(base, units=units, reason="调整动作表达", change_kind="EXPRESSION")
    assert len(edited["units"][0]["scene_artifacts"]) == 2
    duplicate = deepcopy(units)
    duplicate[0]["scene_artifacts"][1]["slot_id"] = "scene:1:skeleton"
    with pytest.raises(KernelError, match="EDITION_SCENE_IDENTITY_INVALID"):
        revise_manifest(base, units=duplicate, reason="重复身份", change_kind="STRUCTURE")
    units[0]["scene_artifacts"][1].update(scene_id="scene:2", slot_id="scene:2:action")
    if not explicit_scene_field:
        del units[0]["scene_artifacts"][1]["scene_id"]
    units[0]["scene_mapping"][1].update(scene_id="scene:2", slot_id="scene:2:action")
    with pytest.raises(KernelError, match="EDITION_CLASSIFICATION_CONFLICT"):
        revise_manifest(base, units=units, reason="不可伪报表达修改", change_kind="EXPRESSION")
