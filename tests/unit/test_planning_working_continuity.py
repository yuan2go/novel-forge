from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_task_view,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from tests.unit.test_provider_task_views import (
    _arc_working_set,
    _authoritative_load,
    _narrative_intelligence,
)


def inputs():
    snapshot = {
        "version": "working-manuscript-context.v1",
        "book_run_id": "run:original",
        "project_id": "project:original",
        "book_id": "book:original",
        "target_chapter": 8,
        "accepted_through_chapter": 0,
        "authority": "AUTHOR_WORKING_PROSE_ONLY",
        "structured_facts": [],
        "sources": [
            {
                "chapter": 7,
                "asset_version_id": "draft:7:selected",
                "content_hash": "sha256:content",
                "text_hash": "sha256:text",
                "excerpt": "他听见答复，接过已经办妥的纸，明日到课。",
                "status": "UNREVIEWED_WORKING_PROSE",
                "character_knowledge": "NOT_VERIFIED",
                "dependency_changes": [{"source_chapter": 6, "status": "CHANGED"}],
            }
        ],
    }
    snapshot["snapshot_hash"] = canonical_hash(snapshot)
    working = {**_arc_working_set(), "working_manuscript": snapshot}
    task = {
        "planning_command": {
            "project_id": "project:original",
            "book_id": "book:original",
            "logical_key": "chapter-group:containing:8",
            "planning_scope": "CHAPTER_GROUP",
        },
        "frozen_inputs": [{"role": "volume_plan", "asset_version_id": "volume:v1"}],
        "authoritative_narrative_load": _authoritative_load(),
        "arc_working_set": working,
        "narrative_intelligence": _narrative_intelligence(),
        "working_continuity_projection_version": "planning-working-continuity.v1",
    }
    context = {
        "schema_version": "novelos.planning_context_bundle.v1",
        **task["planning_command"],
        "arc_working_set": deepcopy(working),
        "working_continuity_projection_version": "planning-working-continuity.v1",
        "input_versions": [
            {
                "role": "story_state",
                "asset_version_id": "state:0",
                "content": {"accepted_through_chapter": 0, "current_state": {}},
            }
        ],
    }
    return task, context


def test_selected_working_continuity_has_no_acceptance_or_knowledge_promotion():
    raw, context = inputs()
    before = deepcopy(raw)
    task = build_provider_task_view("chapter_group_plan.generate", raw)
    view = build_provider_context_view("chapter_group_plan.generate", context, task)
    assert task["working_continuity"] == view["working_continuity"]
    assert view["accepted_state_boundary"] == {"accepted_through_chapter": 0}
    assert (
        task["arc_working_set"]["working_manuscript"]
        == raw["arc_working_set"]["working_manuscript"]
    )
    assert raw == before
    assert task["working_continuity"]["target_chapter"] == 8
    assert (
        "lack of formal acceptance alone" in task["working_continuity"]["instruction"]
    )
    assert "unresolved dependency changes" in task["working_continuity"]["instruction"]
    assert "grants no accepted fact IDs" in task["working_continuity"]["instruction"]


@pytest.mark.parametrize(
    "drift",
    [
        "other_book",
        "other_project",
        "hash",
        "accepted_facts",
        "knowledge",
        "target",
        "duplicates",
        "version",
    ],
)
def test_working_continuity_rejects_cross_scope_or_false_promotion(drift):
    raw, _ = inputs()
    working = raw["arc_working_set"]["working_manuscript"]
    if drift == "other_book":
        working["book_id"] = "foreign"
    elif drift == "other_project":
        working["project_id"] = "foreign"
    elif drift == "hash":
        working["sources"][0]["excerpt"] = "Changed selected prose."
    elif drift == "accepted_facts":
        working["structured_facts"] = [{"fact_id": "invented"}]
    elif drift == "knowledge":
        working["sources"][0]["character_knowledge"] = "VERIFIED"
    elif drift == "target":
        working["target_chapter"] = 7
    elif drift == "duplicates":
        working["sources"].append(deepcopy(working["sources"][0]))
    elif drift == "version":
        raw["working_continuity_projection_version"] = "latest"
    if drift != "hash":
        working["snapshot_hash"] = canonical_hash(
            {k: v for k, v in working.items() if k != "snapshot_hash"}
        )
    with pytest.raises(KernelError, match="PLANNING_WORKING_CONTINUITY_DRIFT"):
        build_provider_task_view("chapter_group_plan.generate", raw)


def test_task_and_context_cannot_mix_selected_working_versions():
    raw, context = inputs()
    task = build_provider_task_view("chapter_group_plan.generate", raw)
    working = context["arc_working_set"]["working_manuscript"]
    working["sources"][0]["asset_version_id"] = "draft:7:different"
    working["snapshot_hash"] = canonical_hash(
        {k: v for k, v in working.items() if k != "snapshot_hash"}
    )
    with pytest.raises(KernelError, match="PLANNING_WORKING_CONTINUITY_DRIFT"):
        build_provider_context_view("chapter_group_plan.generate", context, task)


def test_working_prefix_cannot_override_actual_accepted_state_boundary():
    raw, context = inputs()
    task = build_provider_task_view("chapter_group_plan.generate", raw)
    context["input_versions"][0]["content"]["accepted_through_chapter"] = 2
    with pytest.raises(KernelError, match="PLANNING_WORKING_CONTINUITY_DRIFT"):
        build_provider_context_view("chapter_group_plan.generate", context, task)


def test_historical_projection_keeps_its_original_view():
    raw, context = inputs()
    raw.pop("working_continuity_projection_version")
    context.pop("working_continuity_projection_version")
    task = build_provider_task_view("chapter_group_plan.generate", raw)
    view = build_provider_context_view("chapter_group_plan.generate", context, task)
    assert "working_continuity" not in task and "working_continuity" not in view
    assert (
        task["arc_working_set"]["working_manuscript"]["accepted_through_chapter"] == 0
    )


def test_v2_continues_working_experiences_without_changing_v1_contract():
    raw, context = inputs()
    legacy=build_provider_task_view('chapter_group_plan.generate', raw)['working_continuity']
    for item in (raw,context):
        item['working_continuity_projection_version']='planning-working-continuity.v2'
    task=build_provider_task_view('chapter_group_plan.generate', raw)
    view=build_provider_context_view('chapter_group_plan.generate', context,task)
    assert task['working_continuity']==view['working_continuity']
    assert task['working_continuity']['snapshot_hash']==legacy['snapshot_hash']
    assert task['working_continuity']['instruction'].startswith(legacy['instruction'])
    assert 'entry_state' not in legacy['instruction']
    assert 'accessible_knowledge' in task['working_continuity']['instruction']
    assert view['accepted_state_boundary']=={'accepted_through_chapter':0}
