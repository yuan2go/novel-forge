from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from novel_forge.modules.creative.domain import validate_creative_brief
from novel_forge.modules.command_kernel.errors import KernelError


def digest(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def design():
    text = "先发可用物资。\n幕后借用真相。\n第七章旧申请不等于零需求。"
    pieces = text.splitlines()
    spans = [
        (0, len(pieces[0])),
        (len(pieces[0]) + 1, len(pieces[0]) + 1 + len(pieces[1])),
        (text.index(pieces[2]), len(text)),
    ]
    return {
        "contract_version": "author-design-input.v1",
        "project_id": "p",
        "book_id": "b",
        "version": "draft-v2",
        "evidence_class": "AI_ASSISTED_AUTHOR_INPUT",
        "source_task": "author-guided-production",
        "documents": [
            {"path": "author/outline.md", "content": text, "content_hash": digest(text)}
        ],
        "fragments": [
            {
                "fragment_id": f"f{i}",
                "source_path": "author/outline.md",
                "start": a,
                "end": z,
                "content_hash": digest(text[a:z]),
                "targets": targets,
                "chapter_range": bounds,
                "visibility": visibility,
                "strength": strength,
            }
            for i, ((a, z), targets, bounds, visibility, strength) in enumerate(
                zip(
                    spans,
                    [
                        ["CREATIVE_FOUNDATION", "BOOK", "CHAPTER"],
                        ["BOOK", "ARC"],
                        ["CHAPTER"],
                    ],
                    [[1, 6], [1, 24], [7, 7]],
                    ["SCENE_INTENT", "AUTHOR_ONLY", "SCENE_INTENT"],
                    ["REQUIRED", "DIRECTION", "REQUIRED"],
                    strict=True,
                )
            )
        ],
    }


def brief():
    return {
        "creative_brief_contract_version": "creative-brief-v3",
        "idea": "物资悬疑",
        "genre": "悬疑",
        "audience": "长篇读者",
        "constraints": ["限知"],
        "source_boundaries": ["作者输入不是 Canon"],
        "author_design": design(),
    }


def test_native_brief_accepts_versioned_author_design():
    assert validate_creative_brief(brief())["author_design"] == design()


def test_source_hash_and_scope_are_validated_before_registration():
    from novel_forge.modules.story_design_authority.author_input import (
        validate_author_design,
    )

    changed = design()
    changed["documents"][0]["content"] += "changed"
    with pytest.raises(KernelError):
        validate_author_design(changed)
    changed = design()
    changed["fragments"][1]["targets"] = ["CHAPTER"]
    with pytest.raises(KernelError):
        validate_author_design(changed)
    with pytest.raises(KernelError):
        validate_author_design(design(), project_id="other", book_id="b")


def test_exact_intents_survive_native_parent_and_scope_to_final_writer():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        gather_author_design,
    )

    binding = bind_author_design(
        design(), asset_version_id="brief-v2", content_hash="sha256:" + "a" * 64
    )
    parent = {"constraint_envelope": {"author_design": binding}}
    inherited = gather_author_design([parent], project_id="p", book_id="b")
    early = project_author_design(inherited, target="CHAPTER", chapter=1)
    assert [x["fragment_id"] for x in early["fragments"]] == ["f0"]
    assert "幕后" not in str(early) and "第七章" not in str(early)
    late = project_author_design(inherited, target="CHAPTER", chapter=7)
    assert [x["fragment_id"] for x in late["fragments"]] == ["f2"]
    assert "幕后借用真相" in str(project_author_design(inherited, target="ARC"))
    assert inherited["brief_asset_version_id"] == "brief-v2"
    assert binding == parent["constraint_envelope"]["author_design"]


def test_adoption_cannot_be_unlocated_or_silently_omit_required_input():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        validate_author_decisions,
    )

    selected = project_author_design(
        bind_author_design(
            design(), asset_version_id="v", content_hash="sha256:" + "b" * 64
        ),
        target="CHAPTER",
        chapter=1,
    )
    candidate = {
        "objective": "优先发出可用床位，查账另行进行。",
        "author_design_decisions": [
            {
                "fragment_id": "f0",
                "content_hash": design()["fragments"][0]["content_hash"],
                "decision": "ADAPT",
                "rationale": "先发床位而不耽误查账",
                "target_pointer": "/objective",
                "realization_excerpt": "优先发出可用床位",
            }
        ],
    }
    validate_author_decisions(candidate, selected)
    missing = deepcopy(candidate)
    missing["author_design_decisions"] = []
    with pytest.raises(KernelError):
        validate_author_decisions(missing, selected)
    bad = deepcopy(candidate)
    bad["author_design_decisions"][0]["realization_excerpt"] = "不存在的行动"
    with pytest.raises(KernelError):
        validate_author_decisions(bad, selected)
    bad = deepcopy(candidate)
    bad["author_design_decisions"][0]["decision"] = "REJECT"
    with pytest.raises(KernelError):
        validate_author_decisions(bad, selected)


def test_final_draft_request_gets_scoped_required_fragments_without_carrier():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
    )
    from novel_forge.modules.chapter_authority.chapter_plan_views import (
        build_draft_plan_view,
    )
    from novel_forge.modules.chapter_authority.provider_views import (
        build_provider_task_view,
    )

    source = design()
    for index in range(3, 16):
        fragment = deepcopy(source["fragments"][0])
        fragment["fragment_id"] = f"critical-{index}"
        source["fragments"].append(fragment)
    plan = {
        "chapter": 1,
        "source_chapter_plan_asset_version_id": "chapter-v1",
        "source_chapter_plan_content_hash": digest("chapter"),
        "constraint_envelope": {
            "author_design": bind_author_design(
                source, asset_version_id="brief-v2", content_hash=digest("brief")
            )
        },
    }
    before = deepcopy(plan)
    task = build_provider_task_view("draft", {"plan": build_draft_plan_view(plan)})
    assert len(task["chapter_plan"]["author_design_guidance"]["fragments"]) == 14
    assert "critical-15" in str(task)
    assert "幕后借用真相" not in str(task) and "第七章旧申请" not in str(task)
    assert "author_design" not in task["chapter_plan"].get("constraint_envelope", {})
    assert plan == before


def test_author_projection_is_counted_in_context_budget_and_replayed_exactly():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
    )
    from novel_forge.modules.story_planning_runtime.execution import (
        PostgresPlanningExecutionPreparer,
    )
    from novel_forge.modules.chapter_authority.provider_views import (
        compile_planning_provider_context,
    )
    from tests.unit.test_story_planning_runtime import _command

    command = _command("book_plan.generate")
    binding = bind_author_design(
        design(), asset_version_id="brief-v2", content_hash=digest("brief")
    )
    projection = project_author_design(binding, target="BOOK")
    selected = [
        {
            "role": "creative_foundation",
            "asset_version_id": "foundation-v2",
            "asset_type": "creative_foundation",
            "content_hash": digest("foundation"),
            "content": {
                "objective": "Action before certainty",
                "constraint_envelope": {"author_design": binding},
            },
        }
    ]
    content = {
        "schema_version": "novelos.planning_context_bundle.v1",
        "book_id": command.book_id,
        "planning_scope": command.planning_scope.value,
        "logical_key": command.logical_key,
        "input_versions": selected,
        "token_budget": 16000,
        "author_design_projection": projection,
    }
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(
        command=command, selected_inputs=selected, content=content
    )
    assert any(
        x["logical_context_kind"] == "planning_author_design_projection"
        for x in manifest["selected_inputs"]
    )
    frozen = {**content, "context_manifest": manifest}
    view, _ = compile_planning_provider_context("book_plan.generate", frozen)
    from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
    assert view["author_design_projection"] == compile_provider_author_projection(projection)
    assert view["author_design_projection"]["fragments"] == _author_semantics(projection)
    assert (
        view["segments"][0]["content"]
        .get("constraint_envelope", {})
        .get("author_design")
        is None
    )
    drift = deepcopy(frozen)
    drift["author_design_projection"]["fragments"][0]["text"] += " changed"
    with pytest.raises(KernelError, match="IDENTITY_MISMATCH"):
        compile_planning_provider_context("book_plan.generate", drift)
    huge = deepcopy(content)
    huge["author_design_projection"]["fragments"][0]["text"] = "必需行动" * 20000
    huge_fragment = huge["author_design_projection"]["fragments"][0]
    huge_fragment["content_hash"] = digest(huge_fragment["text"])
    huge_fragment["end"] = huge_fragment["start"] + len(huge_fragment["text"])
    with pytest.raises(KernelError, match="BUDGET_EXCEEDED"):
        compile_planning_provider_context("book_plan.generate", huge)


def test_near_term_author_input_requires_a_frozen_chapter_range():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        planning_author_projection,
    )

    source = design()
    source["fragments"][2]["targets"] = ["NEAR_TERM"]
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    with pytest.raises(KernelError, match="chapter range"):
        planning_author_projection(
            binding,
            generator="chapter_group_plan.generate",
            logical_key="chapter-group:containing:1",
        )


def test_evaluation_reuses_exact_generation_author_scope():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        evaluation_author_view,
    )

    source = design()
    source["fragments"][0]["targets"].append("NEAR_TERM")
    source["fragments"][2]["targets"].append("NEAR_TERM")
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    projection = project_author_design(
        binding, target="NEAR_TERM", chapter_range=(1, 3)
    )
    candidate = {
        "generator_operation_name": "chapter_group_plan.generate",
        "logical_key": "chapter-group:containing:1",
        "chapter_range": [1, 3],
        "constraint_envelope": {
            "author_design": binding,
            "author_design_projection": projection,
        },
    }
    view = evaluation_author_view(candidate)
    assert view["author_design_projection"] == projection
    assert "第七章旧申请" not in str(view)


def test_world_author_location_survives_typed_normalization():
    import json
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        validate_author_decisions,
    )
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        normalize_foundation_payload,
    )
    from tests.integration.narrative_reality_vertical_support import (
        compiled_world_fixture,
    )

    source = design()
    source["fragments"][0]["targets"] = ["WORLD_BIBLE"]
    projection = project_author_design(
        bind_author_design(
            source, asset_version_id="brief-v2", content_hash=digest("brief")
        ),
        target="WORLD_BIBLE",
    )
    world = compiled_world_fixture()
    candidate = {
        "world_foundation_json": json.dumps(world),
        "author_design_decisions": [
            {
                "fragment_id": "f0",
                "content_hash": source["fragments"][0]["content_hash"],
                "decision": "ADAPT",
                "rationale": "Bind the typed world scope",
                "target_pointer": "/world_foundation/rules/0/statement",
                "realization_excerpt": world["rules"][0]["statement"],
            }
        ],
    }
    validate_author_decisions(candidate, projection)
    normalized = normalize_foundation_payload("world.design.generate", candidate)
    validate_author_decisions(normalized, projection)
    transport_pointer = deepcopy(candidate)
    transport_pointer["author_design_decisions"][0]["target_pointer"] = (
        "/world_foundation_json"
    )
    with pytest.raises(KernelError, match="actual candidate content"):
        validate_author_decisions(transport_pointer, projection)


def test_private_adoption_cannot_populate_a_public_parent_field():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        validate_author_decisions,
    )

    source = design()
    source["fragments"] = [source["fragments"][1]]
    projection = project_author_design(
        bind_author_design(
            source, asset_version_id="brief-v2", content_hash=digest("brief")
        ),
        target="BOOK",
    )
    candidate = {
        "objective": "幕后借用真相。",
        "author_design_decisions": [
            {
                "fragment_id": "f1",
                "content_hash": source["fragments"][0]["content_hash"],
                "decision": "ADOPT",
                "rationale": "Preserve the author secret",
                "target_pointer": "/objective",
                "realization_excerpt": "幕后借用真相",
            }
        ],
    }
    with pytest.raises(KernelError, match="private"):
        validate_author_decisions(candidate, projection)


def test_actual_evaluation_provider_keeps_author_projection_before_compaction():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
    )
    from novel_forge.modules.chapter_authority.provider_views import (
        build_provider_context_view,
    )

    binding = bind_author_design(
        design(), asset_version_id="brief-v2", content_hash=digest("brief")
    )
    projection = project_author_design(binding, target="CHAPTER", chapter=1)
    candidate = {
        "generator_operation_name": "chapter_plan.generate",
        "logical_key": "chapter:1",
        "objective": "先发可用物资。",
        "constraint_envelope": {
            "author_design": binding,
            "author_design_projection": projection,
        },
    }
    context = {
        "source_isolation": "EXACT_CANDIDATE_ONLY",
        "selected_inputs": [
            {
                "asset_type": "planning_generation_candidate",
                "asset_version_id": "candidate:v1",
                "content_hash": digest("candidate"),
                "candidate": candidate,
            }
        ],
    }
    view = build_provider_context_view("narrative_semantic_evaluation", context, {})
    actual = view["selected_inputs"][0]["candidate"]
    from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
    assert actual["author_design_projection"] == compile_provider_author_projection(projection, frozen_context_pointer='/selected_inputs/0/candidate/constraint_envelope/author_design_projection')
    assert actual["author_design_projection"]["fragments"] == _author_semantics(projection)
    assert '"constraint_envelope":' not in json.dumps(view)
    assert "幕后借用真相" not in str(view) and "第七章旧申请" not in str(view)


def test_group_scope_uses_the_frozen_native_horizon_and_parent_volume():
    from dataclasses import replace
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        compile_planning_author_projection,
    )
    from tests.unit.test_story_planning_runtime import _command

    source = design()
    source["fragments"][0]["targets"].append("NEAR_TERM")
    source["fragments"][2]["targets"].append("NEAR_TERM")
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    horizon = {
        "level": "CHAPTER_GROUP",
        "chapter_range": [1, 3],
        "starts_at_chapter": 1,
        "ends_at_chapter": 3,
    }
    command = replace(
        _command("chapter_group_plan.generate"),
        logical_key="chapter-group:containing:1",
        narrative_search_id="search:v1",
        narrative_search_branch_key="future-1",
        narrative_search_strategy_directive="advance costly agency",
        narrative_search_planning_horizon=horizon,
        narrative_search_desired_transformation={"goal": "advance the Arc"},
        narrative_search_hard_constraints=("immutable accepted history",),
    )
    horizon["chapter_range"] = [1, 12]
    selected = [{"role": "volume_plan", "content": {"chapter_range": [1, 12]}}]
    projection = compile_planning_author_projection(
        binding, command=command, selected_inputs=selected
    )
    assert projection["chapter_range"] == [1, 3]
    assert [item["fragment_id"] for item in projection["fragments"]] == ["f0"]
    with pytest.raises(KernelError, match="exceeds"):
        compile_planning_author_projection(
            binding,
            command=command,
            selected_inputs=[
                {"role": "volume_plan", "content": {"chapter_range": [4, 12]}}
            ],
        )


def test_volume_and_arc_use_authoritative_parent_ranges():
    from dataclasses import replace
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        compile_planning_author_projection,
    )
    from tests.unit.test_story_planning_runtime import _command

    source = design()
    source["fragments"][0]["targets"] = ["VOLUME", "ARC"]
    source["fragments"][2]["targets"] = ["VOLUME", "ARC"]
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    volume = replace(_command("volume_plan.generate"), logical_key="volume:2")
    book = {
        "volume_skeleton": [{"volume": 1}, {"volume": 2}],
        "length_strategy": {"target_chapters": 12},
    }
    projection = compile_planning_author_projection(
        binding,
        command=volume,
        selected_inputs=[{"role": "book_plan", "content": book}],
    )
    assert projection["chapter_range"] == [7, 12]
    assert [item["fragment_id"] for item in projection["fragments"]] == ["f2"]
    arc = compile_planning_author_projection(
        binding,
        command=_command("arc_plan.generate"),
        selected_inputs=[
            {"role": "volume_plan", "content": {"chapter_range": [7, 12]}}
        ],
    )
    assert [item["fragment_id"] for item in arc["fragments"]] == ["f1", "f2"]


def test_private_guidance_remains_private_and_rejects_legacy_or_literal_leakage():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        validate_author_decisions,
    )
    from novel_forge.modules.chapter_authority.provider_views import (
        compile_planning_provider_context,
    )

    source = design()
    source["fragments"] = [source["fragments"][1]]
    source["fragments"][0]["strength"] = "REQUIRED"
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    projection = project_author_design(binding, target="BOOK")
    candidate = {
        "objective": "按证据顺序设计查证行动。",
        "constraint_envelope": {
            "author_design": binding,
            "author_design_projection": projection,
        },
        "author_design_decisions": [
            {
                "fragment_id": "f1",
                "content_hash": source["fragments"][0]["content_hash"],
                "decision": "RETAIN_PRIVATE",
                "rationale": "等待独立查证后才能安排披露",
                "target_pointer": "",
                "realization_excerpt": "",
            }
        ],
    }
    validate_author_decisions(candidate, projection)
    context = {
        "schema_version": "novelos.planning_context_bundle.v1",
        "logical_key": "chapter:1",
        "input_versions": [
            {
                "role": "book_plan",
                "asset_version_id": "book:v1",
                "content_hash": digest("book"),
                "content": candidate,
            }
        ],
        "token_budget": 16000,
    }
    view, _ = compile_planning_provider_context("chapter_plan.generate", context)
    assert "幕后借用真相" not in str(view) and "author_design_projection" not in str(
        view
    )
    malformed = deepcopy(candidate)
    malformed["author_design_decisions"][0].update(
        decision="ADOPT", target_pointer="/objective", realization_excerpt="按证据顺序"
    )
    with pytest.raises(KernelError, match="private"):
        compile_planning_provider_context(
            "chapter_plan.generate",
            {
                **context,
                "input_versions": [{"role": "book_plan", "content": malformed}],
            },
        )
    copied = deepcopy(candidate)
    copied["objective"] = "查证方向：幕后借用真相。"
    with pytest.raises(KernelError, match="private source text"):
        validate_author_decisions(copied, projection)


def test_frozen_author_evaluation_rejects_scope_or_source_drift():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        evaluation_author_view,
    )

    source = design()
    source["fragments"][0]["targets"].append("NEAR_TERM")
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    projection = project_author_design(
        binding, target="NEAR_TERM", chapter_range=(1, 3)
    )
    candidate = {
        "generator_operation_name": "chapter_group_plan.generate",
        "logical_key": "chapter-group:containing:1",
        "constraint_envelope": {
            "author_design": binding,
            "author_design_projection": projection,
        },
    }
    changed = deepcopy(candidate)
    changed["constraint_envelope"]["author_design_projection"]["fragments"][0][
        "text"
    ] += " changed"
    with pytest.raises(KernelError, match="differs"):
        evaluation_author_view(changed)
    missing = deepcopy(candidate)
    missing["constraint_envelope"].pop("author_design_projection")
    with pytest.raises(KernelError, match="frozen generation projection"):
        evaluation_author_view(missing)


def test_world_adoption_passes_the_native_foundation_second_validation():
    from novel_forge.modules.story_design_authority.author_input import (
        bind_author_design,
        project_author_design,
        validate_author_decisions,
    )
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        normalize_foundation_payload,
        validate_foundation_payload,
    )
    from tests.integration.synthesis_production_support import SynthesisTransport

    source = design()
    source["fragments"][0]["targets"] = ["WORLD_BIBLE"]
    binding = bind_author_design(
        source, asset_version_id="brief-v2", content_hash=digest("brief")
    )
    projection = project_author_design(binding, target="WORLD_BIBLE")
    raw = SynthesisTransport().planning("world.design.generate", {})
    raw["author_design_decisions"] = [
        {
            "fragment_id": "f0",
            "content_hash": source["fragments"][0]["content_hash"],
            "decision": "ADAPT",
            "rationale": "Fixture verifies exact World location, not semantic quality",
            "target_pointer": "/world_foundation/rules/0/statement",
            "realization_excerpt": "The witnessed inquiry remains open.",
        }
    ]
    validate_author_decisions(raw, projection)
    normalized = normalize_foundation_payload("world.design.generate", raw)
    validate_author_decisions(normalized, projection)
    envelope = {
        "author_design": binding,
        "author_design_projection": projection,
        "foundation_parent_bindings": {},
    }
    validate_foundation_payload(
        "world.design.generate",
        {
            "logical_key": "world:main",
            "candidate_payload": {
                **normalized,
                "constraint_envelope": envelope,
                "foundation_parent_bindings": {},
            },
        },
    )


def _world_author_context(stage_name):
    from dataclasses import replace
    from novel_forge.modules.story_design_authority.author_input import bind_author_design, project_author_design
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage
    from tests.unit.test_story_planning_runtime import _command
    command = replace(_command('chapter_plan.generate'), logical_key='chapter:1')
    task = {'contract_version':'world-provider-task.v1','fact_mutation_allowed':False,
            'role':'WORLD_REASONER' if stage_name.endswith('generate') else 'DIRECTOR',
            'accepted_through_chapter':0,'baseline_id':'baseline:v1','baseline_kind':'CANON',
            'source_ref':{'asset_version_id':'world:v1','content_hash':digest('world')},
            'projection_identity':digest('world-projection'),'policy':{'context_token_budget':16000}}
    stage = PlanningProviderStage(stage_name, task, {})
    binding = bind_author_design(design(), asset_version_id='brief-v2', content_hash=digest('brief'))
    projection = project_author_design(binding, target='CHAPTER', chapter=1)
    selected = [{'role':task['role'],'asset_version_id':'world:v1','asset_type':'world_preparation_source','content_hash':digest('world'),'content':{}}]
    content = {'project_id':command.project_id,'book_id':command.book_id,'logical_key':command.logical_key,
               'input_versions':selected,'world_preparation':task,'token_budget':16000,'author_design_projection':projection}
    return command, stage, content


@pytest.mark.parametrize('stage_name', ['world_candidates.generate','world_candidates.evaluate'])
def test_world_preparation_delivers_protected_current_author_intent(stage_name):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    command, stage, content = _world_author_context(stage_name)
    actual = build_provider_context_view(stage_name, content, {'world_preparation':stage.task})
    from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
    assert actual['author_design_projection'] == compile_provider_author_projection(content['author_design_projection'])
    assert actual['author_design_projection']['fragments'] == _author_semantics(content['author_design_projection'])
    assert actual['protected'] is True
    assert '幕后借用真相' not in str(actual) and '第七章旧申请' not in str(actual)
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(command=command,selected_inputs=content['input_versions'],content=content,provider_stage=stage)
    assert manifest['provider_context_view']['compiled_view'] == actual
    assert any(item['logical_context_kind'] == 'planning_author_design_projection' for item in manifest['selected_inputs'])
    assert manifest['token_accounting']['accepted_tokens'] <= content['token_budget']


@pytest.mark.parametrize('invalid', ['private','future','bytes','carrier','boundary'])
def test_world_preparation_rejects_unscoped_or_changed_author_input(invalid):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
    from novel_forge.modules.story_design_authority.author_input import bind_author_design
    _, stage, content = _world_author_context('world_candidates.generate')
    author = content['author_design_projection']
    binding = bind_author_design(design(), asset_version_id='brief-v2', content_hash=digest('brief'))
    if invalid in {'private','future'}:
        author['fragments'].append(binding['fragments'][1 if invalid == 'private' else 2])
    elif invalid == 'bytes':
        author['fragments'][0]['text'] += ' drift'
    elif invalid == 'carrier':
        author['documents'] = design()['documents']
    else:
        content['logical_key'] = 'chapter:2'
    with pytest.raises(KernelError, match='WORLD_AUTHOR_CONTEXT_INVALID'):
        build_provider_context_view(stage.name, content, {'world_preparation':stage.task})


def test_world_preparation_cannot_exceed_budget_by_adding_author_guidance():
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage
    command, stage, content = _world_author_context('world_candidates.generate')
    task = deepcopy(stage.task)
    task['policy']['context_token_budget'] = 200
    stage = PlanningProviderStage(stage.name, task, {})
    content.update(world_preparation=task, token_budget=200)
    with pytest.raises(KernelError, match='BUDGET_EXCEEDED'):
        PostgresPlanningExecutionPreparer._planning_context_manifest(command=command,selected_inputs=content['input_versions'],content=content,provider_stage=stage)


def _empty_world_knowledge():
    from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed, select_narrative_intelligence, resolve_book_knowledge_access_policy
    need = NarrativeIntelligenceNeed(scope='SCENE', target_stage='chapter_plan.generate',
        hard_constraints=tuple(f'Required independent condition {index:02d}' for index in range(13)),
        current_state_terms=('accepted resources stay conserved',),desired_transformation_terms=('advance the costly choice',),
        condition_sources={f'planning_role_{index}':{'asset_version_id':f'authority-output:source-operation-{index}:story_planning.candidate:v1','content_hash':digest(str(index))} for index in range(13)})
    return {**select_narrative_intelligence(need, ()), 'project_id':'project-1',
            'knowledge_access_policy':resolve_book_knowledge_access_policy(production_profile={},project_id='project-1',book_id='book-1')}


def test_empty_world_selection_replaces_only_source_directory_with_a_frozen_receipt():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view, build_provider_context_view
    _, stage, content = _world_author_context('world_candidates.generate')
    selection = _empty_world_knowledge()
    task = {**stage.task,'narrative_intelligence':selection}
    before = deepcopy(task)
    actual = build_provider_task_view(stage.name, {'world_preparation':task})
    projected = actual['world_preparation']['narrative_intelligence']
    assert 'condition_sources' not in projected['need']
    receipt = projected['need']['condition_sources_receipt']
    assert receipt['frozen_context_pointer'] == '/narrative_intelligence/need/condition_sources'
    assert receipt['selection_digest'] == selection['selection_digest']
    assert receipt['need_digest'] == selection['need']['need_digest']
    assert {k:v for k,v in projected['need'].items() if k != 'condition_sources_receipt'} == {k:v for k,v in selection['need'].items() if k != 'condition_sources'}
    assert projected['need']['hard_constraints'][12] == 'Required independent condition 12'
    assert {k:v for k,v in projected.items() if k != 'need'} == {k:v for k,v in selection.items() if k != 'need'}
    assert build_provider_task_view(stage.name, actual) == actual
    frozen = {**content,'world_preparation':actual['world_preparation'],'narrative_intelligence':selection}
    build_provider_context_view(stage.name, frozen, actual)
    assert task == before


@pytest.mark.parametrize('boundary', ['selected_card','required_card','unknown_policy','semantic_source'])
def test_world_keeps_complete_selection_inputs_when_reference_omission_is_not_safe(boundary):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    from novel_forge.modules.narrative_state.reality import narrative_hash
    _, stage, _ = _world_author_context('world_candidates.evaluate')
    selection = _empty_world_knowledge()
    if boundary == 'selected_card':
        selection['selected'] = [{'knowledge_card_asset_version_id':'card:v1','content_hash':digest('card'),
            'applicability_assessment':{'status':'CONDITIONAL','unmet_preconditions':['resource >= 3'], 'exceptions':['emergency override']}}]
        selection['selection_status'] = 'SELECTED'
    elif boundary == 'required_card':
        selection['need']['required_card_asset_version_ids'] = ['card:v1']
    elif boundary == 'unknown_policy':
        selection['knowledge_access_policy']['mode'] = 'UNKNOWN'
    else:
        selection['need']['condition_sources']['planning_role_0']['condition'] = 'Retain this actual required condition'
    selection['need']['need_digest'] = narrative_hash({k:v for k,v in selection['need'].items() if k != 'need_digest'})
    actual = build_provider_task_view(stage.name, {'world_preparation':{**stage.task,'narrative_intelligence':selection}})
    assert actual['world_preparation']['narrative_intelligence'] == selection


@pytest.mark.parametrize('drift', ['source','receipt','hard_constraint','book'])
def test_world_source_receipt_is_bound_to_complete_frozen_context(drift):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view, build_provider_context_view
    _, stage, context = _world_author_context('world_candidates.generate')
    selection = _empty_world_knowledge()
    actual = build_provider_task_view(stage.name, {'world_preparation':{**stage.task,'narrative_intelligence':selection}})
    if drift == 'source':
        selection['need']['condition_sources']['planning_role_0']['content_hash'] = digest('other source')
    elif drift == 'receipt':
        actual['world_preparation']['narrative_intelligence']['need']['condition_sources_receipt']['omitted_value_hash'] = digest('wrong omitted content')
    elif drift == 'hard_constraint':
        actual['world_preparation']['narrative_intelligence']['need']['hard_constraints'].pop()
    else:
        context['book_id'] = 'another-book'
    context.update(world_preparation=actual['world_preparation'],narrative_intelligence=selection)
    with pytest.raises(KernelError, match='WORLD_SELECTION_RECEIPT_DRIFT'):
        build_provider_context_view(stage.name, context, actual)


def _author_semantics(projection):
    fields = {'fragment_id', 'content_hash', 'visibility', 'strength', 'chapter_range', 'text'}
    return [{key: value for key, value in item.items() if key in fields} for item in projection['fragments']]


def test_author_provider_metadata_receipt_preserves_every_selected_semantic_field():
    from novel_forge.modules.story_design_authority.author_input import bind_author_design, project_author_design, compile_provider_author_projection
    from novel_forge.modules.narrative_state.reality import narrative_hash
    raw = design()
    raw['fragments'] += [{**raw['fragments'][0], 'fragment_id': f'critical-{i}'} for i in range(13)]
    source = project_author_design(bind_author_design(raw, asset_version_id='brief:v2', content_hash=digest('brief')), target='CHAPTER', chapter=1)
    before = deepcopy(source)
    compiled = compile_provider_author_projection(source)
    assert compiled['fragments'] == _author_semantics(source)
    assert len(compiled['fragments']) == 14
    assert compiled['fragments'][-1]['fragment_id'] == 'critical-12'
    assert compiled['source_receipt'] == {
        'json_pointer': '/author_design_projection', 'content_hash': narrative_hash(source),
        'excluded_count': len(source['exclusions']), 'metadata_count': len(source['fragments']),
        'reason': 'ROLE_SOURCE_METADATA_ONLY',
    }
    assert 'source_path' not in str(compiled) and 'exclusions' not in compiled
    assert compile_provider_author_projection(compiled, source_projection=source) == compiled
    assert source == before


@pytest.mark.parametrize('drift', ['source_ref', 'source_span', 'excluded', 'text', 'receipt', 'pointer'])
def test_author_provider_receipt_rejects_source_and_transport_drift(drift):
    from novel_forge.modules.story_design_authority.author_input import bind_author_design, project_author_design, compile_provider_author_projection
    source = project_author_design(bind_author_design(design(), asset_version_id='brief:v2', content_hash=digest('brief')), target='CHAPTER', chapter=1)
    compiled = compile_provider_author_projection(source)
    if drift == 'source_ref':
        source['brief_asset_version_id'] = 'brief:v3'
    elif drift == 'source_span':
        source['fragments'][0]['source_path'] = 'other/document.md'
    elif drift == 'excluded':
        source['exclusions'].pop()
    elif drift == 'text':
        compiled['fragments'][0]['text'] += ' altered'
    elif drift == 'receipt':
        compiled['source_receipt']['content_hash'] = digest('wrong source')
    else:
        compiled['source_receipt']['json_pointer'] = '/unfrozen/author'
    with pytest.raises(KernelError, match='AUTHOR_DESIGN_PROVIDER_VIEW_DRIFT'):
        compile_provider_author_projection(compiled, source_projection=source)


@pytest.mark.parametrize('drift', ['source_ref', 'metadata', 'excluded', 'required_text', 'receipt'])
def test_world_author_compiled_receipt_replays_exactly_and_rejects_frozen_drift(drift):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    command, stage, context = _world_author_context('world_candidates.evaluate')
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(command=command, selected_inputs=context['input_versions'], content=context, provider_stage=stage)
    context['context_manifest'] = manifest
    actual = build_provider_context_view(stage.name, context, {'world_preparation': stage.task})
    assert build_provider_context_view(stage.name, context, {'world_preparation': stage.task}) == actual
    selected = next(item for item in manifest['selected_inputs'] if item['logical_context_kind'] == 'planning_author_design_projection')
    assert selected['provenance']['author_projection_source_receipt'] == actual['author_design_projection']['source_receipt']
    source = context['author_design_projection']
    if drift == 'source_ref':
        source['brief_asset_version_id'] = 'other-brief:v1'
    elif drift == 'metadata':
        source['fragments'][0]['source_path'] = 'other/document.md'
    elif drift == 'excluded':
        source['exclusions'].pop()
    elif drift == 'required_text':
        fragment = source['fragments'][0]
        fragment['text'] = '改变硬约束。'
        fragment['content_hash'] = digest(fragment['text'])
        fragment['end'] = fragment['start'] + len(fragment['text'])
    else:
        manifest['provider_context_view']['compiled_view']['author_design_projection']['source_receipt']['json_pointer'] = '/missing'
    with pytest.raises(KernelError, match='WORLD_CONTEXT_IDENTITY_MISMATCH'):
        build_provider_context_view(stage.name, context, {'world_preparation': stage.task})


@pytest.mark.parametrize('chapter', range(1, 13))
def test_actual_author_package_retains_all_text_within_measured_world_role_budget(chapter):
    from dataclasses import replace
    from novel_forge.modules.story_design_authority.author_input import bind_author_design, project_author_design
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view, build_provider_task_view
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage
    from novel_forge.modules.narrative_state.reality import narrative_hash
    brief = json.loads((Path(__file__).resolve().parents[2] / 'config/production/author-guided-twelve/brief.json').read_text())
    binding = bind_author_design(brief['author_design'], asset_version_id='authority-output:5d074ee2-2384-43ca-8296-e66a56255b2d:creative.brief:v1', content_hash=narrative_hash(brief))
    source = project_author_design(binding, target='CHAPTER', chapter=chapter)
    command, stage, content = _world_author_context('world_candidates.evaluate')
    command = replace(command, logical_key=f'chapter:{chapter}')
    task = {**stage.task, 'accepted_through_chapter': chapter - 1, 'policy': {'context_token_budget': 8192}, 'intent': {'required_action': ''}}
    def serialize(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    task['intent']['required_action'] = 'x' * (29453 - len(serialize(task)))
    stage = PlanningProviderStage(stage.name, task, {})
    content.update(logical_key=command.logical_key, world_preparation=stage.task, token_budget=8192, author_design_projection=source)
    actual = build_provider_context_view(stage.name, content, {'world_preparation': stage.task})
    sent_task = build_provider_task_view(stage.name, {'world_preparation': stage.task})
    uncompiled = {**actual, 'author_design_projection': source}
    assert (len(serialize(sent_task)) + len(serialize(uncompiled)) + 3) // 4 > 8192
    assert (len(serialize(sent_task)) + len(serialize(actual)) + 3) // 4 <= 8192
    from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
    assert actual['author_design_projection'] == compile_provider_author_projection(source)
    assert actual['author_design_projection']['fragments'] == _author_semantics(source)
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(command=command, selected_inputs=content['input_versions'], content=content, provider_stage=stage)
    assert manifest['provider_context_view']['compiled_view'] == actual
    assert manifest['token_accounting']['accepted_tokens'] <= 8192
    assert content['author_design_projection'] == source
