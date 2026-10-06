from dataclasses import replace

import pytest

from novel_forge.modules.authority_handler_runtime.contracts import (
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_creative_baseline,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.creative.style_projection import compile_foundation_style
from tests.unit.test_work_intent_consistency import work_input


def compilation(status):
    creative = AuthorityInputAsset(
        "creative:v1",
        "creative_foundation",
        "sha256:creative",
        {
            "book_id": "book-1",
            "candidate_payload": {
                "style_profile": {
                    "constraints": ["克制观察"],
                    "narrator": "observations",
                    "pov": "limited",
                    "genre_conventions": [],
                },
                "serialization_potential": "selected serial"
                if status == "APPLICABLE"
                else None,
                "applicability": [
                    {
                        "field_path": "$.serialization_potential",
                        "status": status,
                        "rationale": "Explicit approved work choice",
                    }
                ],
            },
        },
    )
    cast = AuthorityInputAsset(
        "cast:v1",
        "character_cast",
        "sha256:cast",
        {"candidate_payload": {"characters": []}},
    )
    design = AuthorityInputAsset(
        "design:v1",
        "book_design",
        "sha256:design",
        {
            "schema_version": "book-design.v7",
            "foundation_set": {
                "bindings": [
                    {
                        "role": role,
                        "asset_version_id": source.asset_version_id,
                        "content_hash": source.content_hash,
                    }
                    for role, source in [
                        ("CREATIVE_FOUNDATION", creative),
                        ("CHARACTER_CAST", cast),
                    ]
                ]
            },
        },
    )
    return AuthorityHandlerRequest(
        "op",
        "project-1",
        "workspace",
        "author",
        "trace",
        "correlation",
        "chapter.style_policy.compile",
        "2.1.4",
        {},
        (design, creative, cast),
    )


@pytest.mark.parametrize(
    "status", ["APPLICABLE", "NOT_APPLICABLE", "PROHIBITED", "UNDETERMINED"]
)
def test_exact_approved_foundation_choice_reaches_work_baseline(status):
    style = compile_foundation_style(compilation(status))
    plan, context, _ = work_input("克制观察")
    plan.update(
        book_id="book-1",
        chapter_contract_schema_version="chapter-mission-scene.v3",
        serialization_function="serial progress" if status == "APPLICABLE" else None,
    )
    context["book_id"] = "book-1"
    context["context_segments"][-1]["structured_facts"] = style["structured_facts"]
    baseline = build_creative_baseline(plan, context)
    assert baseline["method_requirements"]["serialization_function"]["status"] == status
    assert (
        baseline["method_requirements"]["serialization_function"]["work_requirement"][
            "source_asset_version_id"
        ]
        == "creative:v1"
    )
    assert style["contract_version"] == "foundation-style-projection.v4"


@pytest.mark.parametrize("mutation", ["unselected", "book", "source"])
def test_unselected_foreign_or_unbound_style_cannot_change_work_decisions(mutation):
    style = compile_foundation_style(compilation("PROHIBITED"))
    plan, context, _ = work_input("克制观察")
    plan.update(
        book_id="book-1",
        chapter_contract_schema_version="chapter-mission-scene.v3",
        serialization_function=None,
    )
    context["book_id"] = "book-1"
    segment = context["context_segments"][-1]
    segment["structured_facts"] = style["structured_facts"]
    declaration = next(
        item["value"]
        for item in style["structured_facts"]
        if item.get("key") == "work_applicability"
    )
    if mutation == "unselected":
        segment["asset_version_id"] = "other-style:v1"
    elif mutation == "book":
        declaration["book_id"] = "book-2"
    else:
        declaration["source_content_hash"] = "other-source"
    with pytest.raises(KernelError, match="WORK_APPLICABILITY_SOURCE_INVALID"):
        build_creative_baseline(plan, context)


def test_selected_chapter_method_conflicts_with_book_prohibition():
    style = compile_foundation_style(compilation("PROHIBITED"))
    plan, context, _ = work_input("克制观察")
    plan.update(
        book_id="book-1",
        chapter_contract_schema_version="chapter-mission-scene.v3",
        serialization_function="serial progress",
    )
    context["book_id"] = "book-1"
    context["context_segments"][-1]["structured_facts"] = style["structured_facts"]
    with pytest.raises(KernelError, match="QUALITY_APPLICABILITY_CONFLICT"):
        build_creative_baseline(plan, context)


def test_frozen_style_definition_retains_v3_instead_of_silent_upgrade():
    request = compilation("PROHIBITED")
    old = compile_foundation_style(replace(request, definition_version="2.1.1"))
    assert old["contract_version"] == "foundation-style-projection.v3"
    assert not any(
        item.get("key") == "work_applicability" for item in old["structured_facts"]
    )
    assert compile_foundation_style(request) != old


def test_book_requirement_cannot_be_evaded_by_chapter_not_applicable():
    style = compile_foundation_style(compilation("APPLICABLE"))
    plan, context, _ = work_input("克制观察")
    plan.update(
        book_id="book-1",
        chapter_contract_schema_version="chapter-mission-scene.v3",
        serialization_function=None,
    )
    context["book_id"] = "book-1"
    context["context_segments"][-1]["structured_facts"] = style["structured_facts"]
    with pytest.raises(KernelError, match="QUALITY_APPLICABILITY_CONFLICT"):
        build_creative_baseline(plan, context)


def test_activated_work_projection_does_not_invent_unselected_literary_methods():
    from novel_forge.modules.story_planning_runtime.application import (
        _chapter_runtime_projection,
    )
    from tests.unit.test_chapter_mission_scene_contracts import chapter_contract

    candidate = chapter_contract()
    candidate.update(
        chapter_contract_schema_version="chapter-mission-scene.v3",
        primary_function="observation",
        constraint_envelope={"creative_requirements_contract": "work-requirements.v2"},
        reward_action=None,
        ending_hook=None,
        promise_action=None,
        required_payoffs=[],
        objective="Observe a public archive",
        title="Archive",
    )
    projected = _chapter_runtime_projection(candidate, projection_version="2.0.0")
    for name in ("chapter_hook", "protagonist_charm_mechanism", "antagonist_pressure"):
        assert projected[name] is None
    for name in (
        "reward_setup",
        "reward_payoff",
        "emotional_curve",
        "suspense_curve",
        "conflict_escalation",
    ):
        assert projected[name] == []
    assert projected["scene_sequence"] == candidate["scene_plan"]
    frozen = _chapter_runtime_projection(candidate, projection_version="1.0.0")
    assert frozen["reward_setup"] and frozen["chapter_hook"]
    assert frozen != projected
    candidate.update(
        ending_hook="Selected quiet question",
        reward_action="Selected payoff",
        emotional_curve=["calm", "reflection"],
        protagonist_charm_mechanism="Selected compassion",
    )
    selected = _chapter_runtime_projection(candidate, projection_version="2.0.0")
    assert selected["chapter_hook"] == candidate["ending_hook"]
    assert selected["emotional_curve"] == candidate["emotional_curve"]
    assert selected["reward_action"] == candidate["reward_action"]


@pytest.mark.parametrize("selected", [None, "EXACT_SELECTED_REWARD_SENTINEL"])
def test_exact_method_choices_reach_draft_review_and_quality_after_runtime_normalization(
    selected,
):
    import json
    from novel_forge.modules.chapter_authority.chapter_plan_views import (
        normalize_authoritative_chapter_plan,
        build_draft_plan_view,
        qualification_profile_for_plan,
    )
    from novel_forge.modules.story_planning_runtime.application import (
        _chapter_runtime_projection,
    )
    from novel_forge.modules.chapter_quality_authority.context_views import (
        build_quality_context_view,
    )
    from tests.unit.test_chapter_mission_scene_contracts import chapter_contract
    from tests.unit.test_work_intent_consistency import final_input

    candidate = chapter_contract()
    candidate.update(
        chapter_contract_schema_version="chapter-mission-scene.v3",
        constraint_envelope={"creative_requirements_contract": "work-requirements.v2"},
        reward_action=selected,
        ending_hook=None,
        promise_action=None,
        objective="Observe an archive",
        premise="An archive opens",
        title="Archive",
    )
    projected = _chapter_runtime_projection(candidate)
    plan, _ = normalize_authoritative_chapter_plan(
        project_id="project-1",
        expected_chapter=2,
        content=projected,
        asset_version_id="plan:v1",
        content_hash="sha256:plan",
        qualification_profile=qualification_profile_for_plan(projected),
    )
    view = build_draft_plan_view(plan, work_requirements=True)
    assert view["contract_version"] == "draft-plan-view-v3"
    assert view["method_choices"]["reward_action"] == selected
    _, context, _ = work_input("观察")
    revision = dict(
        chapter=2,
        text="观察档案。",
        creative_baseline=build_creative_baseline(plan, context),
    )
    quality = build_quality_context_view(
        group="commercial",
        revision=revision,
        revision_asset_version_id="draft:v1",
        chapter_plan=plan,
        chapter_plan_asset_version_id="plan:v1",
        context_bundle=context,
        context_bundle_asset_version_id="context:v1",
        canon={},
        canon_asset_version_id="canon:v1",
        work_requirements=True,
    )
    requirement = quality["creative_baseline"]["method_requirements"]["reward"]
    assert requirement["status"] == (
        "NOT_APPLICABLE" if selected is None else "APPLICABLE"
    )
    assert requirement["selected_values"]["reward_action"] == selected
    for stage in ("draft", "review", "revision", "rereview"):
        prompt, _ = final_input(
            stage,
            "观察",
            {"reward_action": selected, "promise_action": None, "ending_hook": None},
        )
        if selected:
            assert selected in prompt
        else:
            assert "EXACT_SELECTED_REWARD_SENTINEL" not in prompt
    assert selected is None or selected in json.dumps(quality)


def test_current_plan_entry_rejects_known_legacy_runtime_projection_before_normalization():
    from novel_forge.modules.chapter_authority.handlers import _PlanHandler
    from novel_forge.modules.chapter_authority.contracts import (
        ChapterHandlerRequest,
        ChapterInputAsset,
    )

    request = ChapterHandlerRequest(
        operation_id="operation",
        project_id="project-1",
        workspace_id="workspace",
        trace_id="trace",
        correlation_id="correlation",
        definition_version="3.8.0",
        command={
            "chapter": 1,
            "chapter_plan_asset_version_id": "legacy:v1",
            "chapter_plan_content_hash": "sha256:legacy",
        },
        inputs=(
            ChapterInputAsset(
                "legacy:v1",
                "chapter_plan",
                "sha256:legacy",
                {
                    "source_planning_candidate_asset_version_id": "candidate:v1",
                    "chapter": 1,
                    "chapter_hook": "invented",
                },
            ),
        ),
    )
    with pytest.raises(KernelError, match="CHAPTER_PLAN_PROJECTION_MIGRATION_REQUIRED"):
        _PlanHandler().execute(request)


def execution_style_request(
    style_version, definition_version="3.8.0", source_version=""
):
    from novel_forge.modules.chapter_authority.contracts import (
        ChapterHandlerRequest,
        ChapterInputAsset,
    )
    from tests.unit.test_chapter_execution_artifacts import _plan

    style = compile_foundation_style(
        replace(compilation("APPLICABLE"), definition_version=style_version)
    )
    plan = {
        **_plan(),
        "source_chapter_plan_asset_version_id": "plan:v1",
        "source_chapter_plan_content_hash": "sha256:" + "a" * 64,
    }
    return ChapterHandlerRequest(
        operation_id="execution-intent",
        project_id="project-1",
        workspace_id="workspace",
        trace_id="trace",
        correlation_id="correlation",
        command={"chapter": 5},
        definition_version=definition_version,
        source_definition_version=source_version,
        inputs=(
            ChapterInputAsset("plan:v1", "chapter_plan", "sha256:" + "a" * 64, plan),
            ChapterInputAsset("style:v1", "style_policy", "sha256:" + "b" * 64, style),
        ),
    )


@pytest.mark.parametrize(
    "definition,source",
    [
        ("3.8.0", ""),
        ("3.8.0-author-input.v2", ""),
        ("2.2.0", "3.8.0"),
    ],
)
def test_current_execution_entry_rejects_selected_legacy_style_before_writer(
    definition, source
):
    from novel_forge.modules.chapter_authority.handlers import _ExecutionIntentHandler

    with pytest.raises(KernelError, match="STYLE_PROJECTION_MIGRATION_REQUIRED"):
        _ExecutionIntentHandler().execute(
            execution_style_request("2.1.1", definition, source)
        )
    output = _ExecutionIntentHandler().execute(
        execution_style_request("2.1.4", definition, source)
    )
    assert output.content["contract_version"] == "chapter-execution-intent-v4"


@pytest.mark.parametrize("definition", ["3.6.0", "3.7.0", "3.7.0-author-input.v2"])
def test_frozen_execution_preserves_selected_legacy_style_without_silent_replacement(
    definition,
):
    from novel_forge.modules.chapter_authority.handlers import _ExecutionIntentHandler

    request = execution_style_request("2.1.1", definition)
    output = _ExecutionIntentHandler().execute(request)
    assert (
        output.content["creative_requirements"]["style"]["policies"][0][
            "asset_version_id"
        ]
        == "style:v1"
    )
    assert (
        request.inputs[1].content["contract_version"]
        == "foundation-style-projection.v3"
    )


@pytest.mark.parametrize('selected', ['serial progress', None])
def test_explicit_v4_serialization_method_keeps_frozen_work_requirement(selected):
    style = compile_foundation_style(compilation('APPLICABLE'))
    plan, context, _ = work_input('克制观察')
    plan.update(book_id='book-1', chapter_contract_schema_version='chapter-mission-scene.v4',
                runtime_projection_version='3.0.0', primary_function='progression', serialization_function=selected)
    context['book_id'] = 'book-1'
    context['context_segments'][-1]['structured_facts'] = style['structured_facts']
    if selected is None:
        with pytest.raises(KernelError, match='QUALITY_APPLICABILITY_CONFLICT'):
            build_creative_baseline(plan, context)
    else:
        from novel_forge.modules.chapter_authority.chapter_plan_views import build_draft_plan_view
        baseline = build_creative_baseline(plan, context)
        assert baseline['method_requirements']['serialization_function']['status'] == 'APPLICABLE'
        view = build_draft_plan_view(plan, work_requirements=True)
        assert view['contract_version'] == 'draft-plan-view-v4'
        assert view['method_choices']['serialization_function'] == selected


@pytest.mark.parametrize('version, semantic, enabled', [
    ('3.9.16', '3.9.0', True),
    ('3.8.0', '3.8.0', True),
    ('3.9.17', '3.9.17', False),
])
def test_plan_contract_retains_exact_work_semantics_without_future_version_inheritance(version, semantic, enabled):
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
    request = ChapterHandlerRequest('op', 'project', 'workspace', 'trace', 'correlation', {}, (),
                                   definition_version=version)
    assert request.semantic_definition_version == semantic
    assert request.work_requirements_enabled is enabled


@pytest.mark.parametrize('version', ['3.8.0', '3.9.16'])
def test_plan_fallback_manifest_binds_style_exactly_before_work_context_delivery(monkeypatch, version):
    from dataclasses import dataclass
    from novel_forge.modules.chapter_authority import handlers
    from novel_forge.modules.chapter_authority.chapter_plan_views import build_draft_style_view
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset

    @dataclass
    class Qualification:
        status: str = 'QUALIFIED'

    monkeypatch.setattr(handlers, 'normalize_authoritative_chapter_plan',
                        lambda **kwargs: ({'chapter': 1}, Qualification()))
    plan = ChapterInputAsset('plan:v1', 'chapter_plan', 'sha256:plan', {'chapter': 1})
    request = ChapterHandlerRequest('op', 'project', 'workspace', 'trace', 'correlation', {
        'chapter': 1, 'chapter_plan_asset_version_id': plan.asset_version_id,
        'chapter_plan_content_hash': plan.content_hash,
        'context_candidates': [{'asset_version_id': 'style:selected', 'asset_type': 'style_policy',
                                'content_hash': 'sha256:selected'}],
    }, (plan,), definition_version=version)
    output = handlers._PlanHandler().execute(request)
    manifest = next(item.content for item in output.auxiliary_outputs
                    if item.asset_type == 'production_input_manifest')
    assert manifest['style_policy_version_id'] == 'style:selected'
    context = {'production_input_manifest': manifest, 'context_segments': [
        {'asset_type': 'style_policy', 'asset_version_id': 'style:selected'},
    ]}
    assert build_draft_style_view(context, work_requirements=True)['style_policy_version_id'] == 'style:selected'
    context['context_segments'][0]['asset_version_id'] = 'style:unselected'
    with pytest.raises(KernelError, match='WORK_STYLE_SELECTION_INVALID'):
        build_draft_style_view(context, work_requirements=True)
