from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from novel_forge.modules.book_design_authority.domain import BookDesignPayload
from novel_forge.modules.book_design_authority.formation_domain import (
    StoryFormationInput,
)
from novel_forge.modules.book_followup_authority.prose_review import freeze_manifest
from novel_forge.modules.capability_packs.longform_profiles import (
    build_story_planning_pack_profile,
)
from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_creative_baseline,
)
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
)
from novel_forge.modules.chapter_authority.domain_handlers import (
    normalize_review_result,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
)
from novel_forge.modules.chapter_authority.handlers import _RevisionHandler
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.chapter_authority.prompt_methods import project_skill_method
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    is_targeted_revision_schema_ref,
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_task_view,
    project_longform_prose_review_context_input,
)
from novel_forge.modules.chapter_authority.realization_composition import (
    compile_realization_contract,
    integrate_realization,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.domain import PlanContractType
from novel_forge.modules.review.prose_window import freeze_review_window
from novel_forge.modules.story_design_authority.qualification import (
    qualification_profile_options,
    qualification_provider_schema,
    required_qualification_profiles,
    scripted_qualification,
    validate_narrative_qualification,
)
from novel_forge.modules.story_planning_runtime.domain import (
    canonical_book_volume_allocation,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_provider_output_schema,
)
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    FOUNDATION_INPUT_ROLES,
    foundation_task,
)
from novel_forge.modules.story_planning_runtime.result_recovery import (
    validate_raw_result,
)
from tests.unit.test_book_design_authority_domain import valid_design
from tests.unit.test_cross_chapter_prose_review import source_snapshot
from tests.unit.test_story_planning_runtime import (
    _chapter_schedule_row,
    _realization_slice,
)
from tests.unit.test_work_foundation_contract import ending_payload
from tests.unit.test_work_intent_consistency import work_input

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("stage", ["review", "rereview"])
@pytest.mark.parametrize(
    "judgment", ["AESTHETIC_SUGGESTION", "UNCERTAIN", "SEMANTIC_CONFLICT"]
)
def test_current_review_normalization_distinguishes_advice_and_selected_failures(
    stage, judgment
):
    from novel_forge.modules.chapter_authority.model_effects import (
        normalize_model_output,
    )

    draft, _, _ = review_candidate(judgment)
    raw = {
        "score": 45,
        "issues": [
            {
                "code": "diagnosis",
                "severity": "blocking"
                if judgment == "SEMANTIC_CONFLICT"
                else "minor"
                if judgment == "AESTHETIC_SUGGESTION"
                else "major",
                "message": "Explicit kind matters",
                "judgment_kind": judgment,
                "category": "STYLE_PREFERENCE",
                "evidence": {"start": 0, "end": 11, "quote": "Snow falls."},
                "violated_constraint": "Frozen commitment"
                if judgment == "SEMANTIC_CONFLICT"
                else "None",
                "revision_goal": "Respect the current work",
                "preserve": ["Voice"],
                "acceptance_criteria": ["Keep author requirements"],
            }
        ],
        "resolution_checks": [],
    }
    _, current_ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage=stage,
        request_payload={"input": {"draft": draft}},
        prompt_contract_version="v9",
    )
    normalized = normalize_model_output(stage, raw, output_schema_ref=current_ref)
    expected = "NEEDS_REVISION" if judgment == "SEMANTIC_CONFLICT" else "PASSED"
    assert normalized["decision"] == expected
    assert normalized["score"] == 45
    assert normalized["issues"][0]["severity"] == raw["issues"][0]["severity"]
    review = normalize_review_result(
        draft=draft,
        draft_asset_version_id="draft",
        result=normalized,
        provider_evidence={},
    )
    assert review["decision"] == expected
    assert review["blocking_issue_count"] == int(judgment == "SEMANTIC_CONFLICT")
    assert review["review_decision_contract"] == "work-review-decision.v1"
    _, old_ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage=stage,
        request_payload={"input": {"draft": draft}},
        prompt_contract_version="v8",
    )
    assert old_ref != current_ref
    assert (
        normalize_model_output(stage, raw, output_schema_ref=old_ref)["decision"]
        == "NEEDS_REVISION"
    )


def test_current_chapter_manifest_binds_exact_definition_hashes():
    import json

    from novel_forge.modules.chapter_authority.definitions import (
        chapter_operation_definitions,
    )
    from novel_forge.storage.authority_repositories import definition_hash

    definitions = {
        item["name"]: item
        for item in chapter_operation_definitions(
            application_build_id="unit",
            commit_sha="0" * 40,
            model_effects_required=True,
            coordinated_contract=True,
        )
    }
    manifest = json.loads(
        (ROOT / "config/capability_packs/chapter_generation_pack.json").read_text()
    )
    for node in manifest["workflow_template"]["nodes"]:
        definition = definitions[node["operation_name"]]
        assert (
            node["operation_definition_ref"]
            == definition["name"] + "@" + definition["definition_version"]
        )
        assert node["operation_definition_hash"] == definition_hash(definition)


def test_noop_revision_survives_actual_provider_normalization():
    from novel_forge.modules.chapter_authority.model_effects import (
        normalize_model_output,
    )

    draft, review, _ = review_candidate("AESTHETIC_SUGGESTION")
    raw = {"edits": [], "resolved_issue_codes": []}
    _, current_ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="revision",
        request_payload={"input": {"draft": draft, "review": review}},
        prompt_contract_version="v9",
    )
    assert normalize_model_output("revision", raw, output_schema_ref=current_ref) == raw
    _, old_ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="revision",
        request_payload={"input": {"draft": draft, "review": review}},
        prompt_contract_version="v8",
    )
    with pytest.raises(KernelError, match="revision response has no revised prose"):
        normalize_model_output("revision", raw, output_schema_ref=old_ref)
    with pytest.raises(KernelError, match="revision response has no revised prose"):
        normalize_model_output(
            "revision", raw, output_schema_ref=current_ref + ":quality-targeted-v2"
        )


def test_longform_rejects_another_chapter_creative_baseline():
    source = {
        "chapter_number": 2,
        "acceptance_id": "accepted",
        "asset_version_id": "draft:2",
        "asset_hash": "hash",
        "text": "观察冬雪。",
        "creative_baseline": work_input("观察")[2]["creative_baseline"],
    }
    with pytest.raises(KernelError, match="SOURCE_BASELINE_DRIFT"):
        freeze_manifest(
            project_id="p",
            workspace_id="w",
            book_run_id="book",
            sources=[source],
            policy={
                "policy_version": "test",
                "window_codepoints": 1000,
                "overlap_codepoints": 0,
                "context_token_budget": 2048,
                "maximum_windows": 1,
            },
        )


@pytest.mark.parametrize("scope", list(PlanContractType))
def test_optional_schema_transform_does_not_mutate_required_aliases(scope):
    args = dict(
        logical_key="plan",
        parent_version_id="parent",
        arc_plan_version_id="arc",
        work_requirements=True,
    )
    if scope is PlanContractType.CHAPTER:
        args.update(
            narrative_realization=_realization_slice(),
            chapter_schedule_row=_chapter_schedule_row(),
        )
    legacy = planning_provider_output_schema(scope, **args, aligned_methods=False)
    current = planning_provider_output_schema(scope, **args, aligned_methods=True)
    assert legacy["properties"]["objective"]["type"] == ["string", "null"]
    assert current["properties"]["objective"] == {"type": "string", "minLength": 1}
    assert (
        current["properties"]["objective"]
        is not current["properties"]["entry_state_ref"]
    )
    schema = {"$schema": current["$schema"], **current["properties"]["objective"]}
    with pytest.raises(KernelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_chapter_provider_output_against_schema("planning", schema, None)
    validate_chapter_provider_output_against_schema(
        "planning", schema, "Observe this work"
    )
    if scope is PlanContractType.CHAPTER:
        fields = current["properties"]["scene_plan"]["items"]["properties"]
        assert fields["conflict"]["type"] == ["string", "null"]
        assert fields["goal"]["type"] == "string"
    again = planning_provider_output_schema(scope, **args, aligned_methods=True)
    assert again == current


@pytest.mark.parametrize(
    "stage,skill,heading",
    [
        ("theme.candidates.generate", "narrative-beat-design", "Theme question"),
        ("ending.intent.generate", "long-outline", "Ending intent"),
        ("book_plan.generate", "long-outline", "Book planning"),
        ("volume_plan.generate", "long-outline", "Volume planning"),
    ],
)
def test_actual_pack_selects_aligned_stage_method_and_retains_frozen_predecessor(
    stage, skill, heading
):
    from novel_forge.modules.capability_pack_authority.application import (
        _select_capability_skill,
    )
    from novel_forge.modules.story_design_authority.domain import GENERATOR_CATALOG

    current = build_story_planning_pack_profile(
        ROOT, operation_definition_hash="sha256:" + "a" * 64,
        execution_contract_version="1.21.0",
    )
    old = build_story_planning_pack_profile(
        ROOT,
        operation_definition_hash="sha256:" + "a" * 64,
        execution_contract_version="1.17.0",
    )
    frozen_main = build_story_planning_pack_profile(
        ROOT, operation_definition_hash="sha256:" + "a" * 64,
        execution_contract_version="1.19.0",
    )
    assert current.manifest["identity"]["version"] == "2.13.0"
    assert frozen_main.manifest["identity"]["version"] == "2.11.0"
    assert old.manifest["identity"]["version"] == "2.9.0"
    assert {node["operation_definition_ref"] for node in current.manifest["workflow_template"]["nodes"]} == {"story_planning.generate@1.21.0"}
    assert {node["operation_definition_ref"] for node in frozen_main.manifest["workflow_template"]["nodes"]} == {"story_planning.generate@1.19.0"}

    def select(profile):
        binding = profile.manifest["prompt_binding"]
        return _select_capability_skill(
            profile.manifest["skill_binding"]["skills"],
            capability_id=GENERATOR_CATALOG[stage].capability,
            input_contract_ref=binding["input_schema_ref"],
            output_contract_ref=binding["output_schema_ref"],
        )

    current_binding = select(current)
    old_binding = select(old)
    frozen_main_binding = select(frozen_main)

    def method(profile, binding):
        artifact = next(
            a
            for a in profile.artifact_catalog["artifacts"]
            if a["kind"] == "SKILL"
            and a["ref"] == binding["skill_ref"]
            and a["version"] == binding["version"]
        )
        return project_skill_method(
            artifact["content"]["text"],
            ref=skill,
            version=binding["version"],
            stage=stage,
            targeted=False,
        )

    assert current_binding["version"] != old_binding["version"]
    new, legacy = method(current, current_binding), method(old, old_binding)
    assert f"## {heading}" in new
    assert (
        "when selected" in new
        or "when the work selects" in new
        or "where the work commits" in new
    )
    assert new != legacy
    assert frozen_main_binding == current_binding
    assert method(frozen_main, frozen_main_binding) == new
    assert "Return the declared" in new or "declared schema" in new


@pytest.mark.parametrize(
    "generator,criterion",
    [
        ("theme.candidates.generate", "THEME_METHOD_WORK_ALIGNMENT"),
        ("ending.intent.generate", "ENDING_THEME_WORK_ALIGNMENT"),
    ],
)
def test_new_profile_checks_work_alignment_and_never_repairs_a_pass(
    generator, criterion
):
    content = {"constraint_envelope": {"contract_version": "foundation-generation.v3"}}
    options = qualification_profile_options(content)
    assert options == {"work_requirements": True, "profile_version": "3.0.0"}
    profile = required_qualification_profiles(generator, **options)[0]
    assert criterion in profile.criteria
    assert "absent" in profile.criterion_semantics[criterion]
    assert "missing/contradictory execution" in profile.criterion_semantics[criterion]
    result = scripted_qualification(generator, **options)
    item = next(
        c for c in result["evaluations"][0]["criteria"] if c["criterion"] == criterion
    )
    item.update(
        rationale="Observed work has no selected choice/closure method; its stated alternative aligns.",
        evidence_refs=["candidate:observational-theme", "frozen:author-direction"],
    )
    assert (
        validate_narrative_qualification(
            generator_operation_name=generator, value=result, **options
        ).status
        == "PASS"
    )
    assert all(
        c["repair_directive"] == ""
        for e in result["evaluations"]
        for c in e["criteria"]
    )
    task = build_provider_task_view(
        "narrative_semantic_evaluation",
        {
            "evaluation_target": {
                "candidate_asset_version_id": "candidate",
                "candidate_content_hash": "hash",
                "generation_operation_id": "generation",
                "generator_operation_name": generator,
            },
            "qualification_profiles": [
                {
                    **asdict(profile),
                    "criterion_semantics": profile.criterion_semantics,
                    "profile_hash": profile.profile_hash,
                }
            ],
        },
    )
    assert profile.criterion_semantics[criterion] in str(task)
    selected_failure = deepcopy(result)
    missing = next(
        c
        for c in selected_failure["evaluations"][0]["criteria"]
        if c["criterion"] == criterion
    )
    missing.update(
        verdict="FAIL",
        rationale="This work selected a promise that its candidate fails to realize.",
        repair_directive="Restore the exact selected commitment, without adding a new method.",
    )
    assert (
        validate_narrative_qualification(
            generator_operation_name=generator,
            value=selected_failure,
            require_pass=False,
            **options,
        ).status
        == "FAIL"
    )
    with pytest.raises(KernelError, match="QUALIFICATION_FAILED"):
        validate_narrative_qualification(
            generator_operation_name=generator, value=selected_failure, **options
        )
    # A PASS cannot smuggle a repair, and old receipts cannot qualify the new contract.
    item["repair_directive"] = "Invent closure"
    with pytest.raises(KernelError, match="EVALUATION_INVALID"):
        validate_narrative_qualification(
            generator_operation_name=generator, value=result, **options
        )
    with pytest.raises(KernelError, match="PROFILE_DRIFT"):
        validate_narrative_qualification(
            generator_operation_name=generator,
            value=scripted_qualification(generator, work_requirements=True),
            **options,
        )
    schema = qualification_provider_schema(generator, **options)
    assert (
        schema["properties"]["evaluations"]["items"]["properties"]["profile_version"][
            "const"
        ]
        == "3.0.0"
    )


def test_foundation_task_and_repair_consume_exact_new_contract():
    raw = ending_payload()
    raw.pop("constraint_envelope")
    raw.pop("foundation_parent_bindings")
    assert (
        validate_raw_result(
            "ending.intent.generate", raw, work_requirements=True, aligned_methods=True
        )["protagonist_cost"]
        is None
    )
    inputs = {
        "planning_command": {
            "planning_scope": "NOT_APPLICABLE",
            "creative_requirements_contract": "work-requirements.v2",
        },
        "frozen_inputs": [
            {"role": r} for r in FOUNDATION_INPUT_ROLES["ending.intent.generate"]
        ],
        "foundation_task": foundation_task(
            "ending.intent.generate", work_requirements=True, aligned_methods=True
        ),
    }
    assert "foundation-generation.v3" in str(
        build_provider_task_view("ending.intent.generate", inputs)
    )
    inputs["foundation_task"] = foundation_task(
        "ending.intent.generate", work_requirements=True
    )
    with pytest.raises(KernelError, match="FOUNDATION_PROVIDER_TASK_INVALID"):
        build_provider_task_view("ending.intent.generate", inputs)


def review_candidate(judgment):
    plan, context, _ = work_input("保留克制观察性长句，不要求转化")
    plan["chapter"] = 2
    contract = compile_realization_contract(
        {
            "scene_plan": [
                {"scene_id": "quiet", "goal": "Observe", "beats": [{"beat_id": "one"}]}
            ]
        },
        {},
    )
    text = "Snow falls.\n\nThe river waits."
    artifacts = [
        {"slot_id": contract["slots"][0]["slot_id"], "text": text, "used_fact_ids": []}
    ]
    draft = {
        "chapter": 2,
        "title": "观察",
        "text": text,
        "creative_baseline": build_creative_baseline(plan, context),
        **integrate_realization(contract=contract, artifacts=artifacts, text=text),
    }
    window = freeze_review_window(
        source_snapshot(texts=("The river was quiet.",)),
        candidate_id="draft:2",
        text=text,
        context_token_budget=16000,
        protected_context={},
    )
    issues = (
        []
        if judgment == "CLEAN"
        else [
            {
                "code": "finding",
                "severity": "blocking" if judgment == "SEMANTIC_CONFLICT" else "minor",
                "message": "Check exact work commitment",
                "category": "STYLE_PREFERENCE",
                "judgment_kind": judgment,
                "violated_constraint": "Frozen author commitment"
                if judgment == "SEMANTIC_CONFLICT"
                else "No mandatory constraint",
                "evidence": {"start": 0, "end": 11, "quote": "Snow falls."},
                "revision_goal": "Restore selected commitment",
                "preserve": ["Current voice"],
                "acceptance_criteria": ["Keep author choice"],
            }
        ]
    )
    review = normalize_review_result(
        draft=draft,
        draft_asset_version_id="draft:2",
        project_id="p",
        context_bundle_version_id="context:2",
        result={
            "diagnostic_contract_version": "actionable-diagnostics.v1",
            "decision": "NEEDS_REVISION"
            if judgment == "SEMANTIC_CONFLICT"
            else "PASSED",
            "score": 99,
            "issues": issues,
            "knowledge_checks": [],
        },
        provider_evidence={},
        cross_chapter_window=window,
    )
    return draft, review, context


@pytest.mark.parametrize("judgment", ["CLEAN", "AESTHETIC_SUGGESTION", "UNCERTAIN"])
def test_formal_revision_handler_keeps_exact_prose_in_window_with_no_actionable_diagnosis(
    judgment,
):
    draft, review, context = review_candidate(judgment)

    class OfflineProvider:
        def invoke(self, request, *, stage, payload):
            assert stage == "revision"
            schema, ref = (
                PostgresChapterExecutionContractBinder._provider_output_contract(
                    stage=stage,
                    request_payload={"input": payload},
                    prompt_contract_version="v9",
                )
            )
            assert is_targeted_revision_schema_ref(ref)
            result = {"edits": [], "resolved_issue_codes": []}
            validate_chapter_provider_output_against_schema(stage, schema, result)
            return ModelProviderResult(
                result, "offline", "fixture", "v9", "v4", 0, 0, "0", "USD", False
            )

    request = ChapterHandlerRequest(
        "revision-operation",
        "p",
        "w",
        "trace",
        "correlation",
        {"payload": {}},
        (
            ChapterInputAsset("draft:2", "draft_chapter", "hash", draft),
            ChapterInputAsset("review:2", "review_report", "hash", review),
            ChapterInputAsset("context:2", "context_bundle", "hash", context),
        ),
        definition_version="3.7.0",
    )
    output = _RevisionHandler(OfflineProvider()).execute(request).content
    assert output["text"] == draft["text"]
    assert output["scene_artifacts"] == draft["scene_artifacts"]
    assert output["source_draft_version_id"] == "draft:2"
    assert output["creative_baseline"] == draft["creative_baseline"]
    assert output["resolved_issue_codes"] == []
    assert all(i["to_status"] == "OPEN" for i in output["issue_resolutions"])


def test_selected_blocking_finding_cannot_be_discarded_by_empty_revision():
    from novel_forge.modules.revision.domain import apply_revision_result

    draft, review, _ = review_candidate("SEMANTIC_CONFLICT")
    with pytest.raises(KernelError, match="CHAPTER_REVISION_INCOMPLETE"):
        apply_revision_result(
            project_id="p",
            draft=draft,
            review=review,
            draft_asset_version_id="draft:2",
            review_asset_version_id="review:2",
            context_bundle_version_id="context:2",
            result={"edits": [], "resolved_issue_codes": []},
            provider_evidence={},
        )
    edited = apply_revision_result(
        project_id="p",
        draft=draft,
        review=review,
        draft_asset_version_id="draft:2",
        review_asset_version_id="review:2",
        context_bundle_version_id="context:2",
        result={
            "edits": [
                {
                    "quote": "Snow falls.",
                    "replacement": "Rain falls.",
                    "issue_codes": ["finding"],
                }
            ],
            "resolved_issue_codes": ["finding"],
        },
        provider_evidence={},
    )
    assert edited["text"] == draft["text"].replace("Snow", "Rain")


def test_frozen_v8_empty_edit_contract_is_not_silently_rewritten():
    draft, review, _ = review_candidate("AESTHETIC_SUGGESTION")
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(
        stage="revision",
        request_payload={"input": {"draft": draft, "review": review}},
        prompt_contract_version="v8",
    )
    assert schema["properties"]["edits"]["minItems"] == 1
    with pytest.raises(KernelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_chapter_provider_output_against_schema(
            "revision", schema, {"edits": [], "resolved_issue_codes": []}
        )


@pytest.mark.parametrize("chapters", [1, 2, 3, 10000])
def test_formation_design_and_volume_allocation_preserve_positive_author_length(
    chapters,
):
    frozen = StoryFormationInput(
        creative_brief_asset_version_id="brief",
        creative_brief_content_hash="sha256:" + "a" * 64,
        generation_policy={
            "contract_version": "formation-generation.v1",
            "approval_mode": "REVIEW_PLAN",
            "creative_candidates": 2,
            "target_chapters": chapters,
            "title": "观察",
        },
    )
    design = BookDesignPayload.from_mapping(
        valid_design(target_chapters=frozen.generation_policy["target_chapters"])
    )
    volumes, target = canonical_book_volume_allocation(
        {
            "volume_skeleton": [{"volume": 1}],
            "length_strategy": {"target_chapters": design.target_chapters},
        }
    )
    assert target == chapters and volumes[0]["chapter_range"] == [1, chapters]


@pytest.mark.parametrize("chapters", [0, 10001, True])
def test_invalid_length_rejects_at_both_boundaries(chapters):
    with pytest.raises(ValueError):
        StoryFormationInput(
            creative_brief_asset_version_id="brief",
            creative_brief_content_hash="sha256:" + "a" * 64,
            generation_policy={
                "contract_version": "formation-generation.v1",
                "approval_mode": "REVIEW_PLAN",
                "creative_candidates": 2,
                "target_chapters": chapters,
                "title": "观察",
            },
        )
    with pytest.raises(KernelError, match="BOOK_DESIGN_INVALID"):
        BookDesignPayload.from_mapping(valid_design(target_chapters=chapters))


@pytest.mark.parametrize(
    "direction",
    [
        "严肃现实群像，观察性开放结尾，人物保持稳定",
        "轻松幻想冒险，人物通过选择成长，兑现已选承诺",
        None,
    ],
)
def test_longform_window_freezes_source_work_and_legacy_rebuild_identity(direction):
    baseline = work_input(direction)[2]["creative_baseline"] if direction else None
    source = {
        "chapter_number": 1,
        "acceptance_id": "accepted",
        "asset_version_id": "draft:1",
        "asset_hash": "hash",
        "text": "人物坐在河边，想起家中的旧事。",
        "creative_baseline": baseline,
    }
    policy = {
        "policy_version": "test",
        "window_codepoints": 1000,
        "overlap_codepoints": 0,
        "context_token_budget": 2048,
        "maximum_windows": 1,
    }
    frozen = freeze_manifest(
        project_id="p",
        workspace_id="w",
        book_run_id="book",
        sources=[source],
        policy=policy,
    )
    content = {
        "schema_version": "longform-prose-window.v2",
        "manifest_digest": frozen["manifest_digest"],
        "window": frozen["windows"][0],
        "policy": policy,
        "source_isolation": "ACCEPTED_PROSE_ONLY",
    }
    projection = project_longform_prose_review_context_input(
        "longform_prose_review_window", content
    )
    view = build_provider_context_view(
        "longform_prose_review",
        {
            "schema_version": "novelos.longform_prose_review_context_bundle.v2",
            "selected_inputs": [
                {"asset_type": "longform_prose_review_window", "projection": projection}
            ],
        },
        {},
    )
    assert "中文玄幻/武侠正文" not in view["instruction"]
    span = view["frozen_prose"]["window"]["spans"][0]
    assert span["creative_baseline"] == baseline
    if direction:
        assert direction in str(span)
    else:
        assert span["work_intent_status"] == "UNKNOWN_LEGACY_BASELINE"
    legacy = freeze_manifest(
        project_id="p",
        workspace_id="w",
        book_run_id="book",
        sources=[source],
        policy=policy,
        work_intent=False,
    )
    source.pop("creative_baseline")
    assert legacy == freeze_manifest(
        project_id="p",
        workspace_id="w",
        book_run_id="book",
        sources=[source],
        policy=policy,
        work_intent=False,
    )
    assert legacy["manifest_digest"] != frozen["manifest_digest"]


@pytest.mark.parametrize("chapters", [1, 2, 3])
@pytest.mark.parametrize("version", ["book-design.v6", "book-design.v7"])
def test_current_foundation_design_preserves_short_scope_and_explicit_zero_methods(
    chapters, version
):
    from tests.unit.test_foundation_hierarchy import _foundation_set

    value = {
        "schema_version": version,
        "title": "观察短篇",
        "target_chapters": chapters,
        "foundation_set": _foundation_set().to_dict(),
        "book_invariants": [],
        "cross_layer_synthesis": [
            {
                "synthesis_id": "observe",
                "source_roles": ["CREATIVE_FOUNDATION", "THEME_CONTRACT"],
                "narrative_function": "观察城市",
                "constraint": "保留含混",
                "downstream_scope": "BOOK",
            }
        ],
        "narrative_dna": {
            "core_question": "谁记得城市？",
            "recurring_choice": None,
            "cost_logic": None,
            "distinctive_mechanism": "并置观察",
            "emotional_contract": "克制留白",
        },
    }
    design = BookDesignPayload.from_mapping(value)
    assert design.to_dict() == value
    assert qualification_profile_options(value)["profile_version"] == (
        "3.0.0" if version == "book-design.v7" else "2.0.0"
    )


@pytest.mark.parametrize(
    "stage,author,old_method",
    [
        (
            "theme.candidates.generate",
            "严肃现实观察小说；通过观察和含混表达主题，不使用竞争性选择。",
            "Form a dramatic question that characters can test through competing choices and consequences.",
        ),
        (
            "ending.intent.generate",
            "开放式观察小说；终章保持人物状态，不强行解决主题。",
            "Connect the ending to consequential character choices and the reader promise.",
        ),
    ],
)
def test_foundation_actual_final_assembly_uses_work_methods(stage, author, old_method):
    from novel_forge.modules.capability_pack_authority.application import (
        _select_capability_skill,
    )
    from novel_forge.modules.chapter_authority.execution_gateway import (
        _materialize_production_codex_prompt,
    )
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    from novel_forge.modules.story_design_authority.domain import GENERATOR_CATALOG
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        foundation_output_schema,
    )
    from tests.unit.test_capability_pack_artifact_materialization import (
        _prompt_materialization,
    )
    from tests.unit.test_production_execution_gateway import contracts

    profile = build_story_planning_pack_profile(
        ROOT, operation_definition_hash="sha256:" + "a" * 64
    )
    binding = profile.manifest["prompt_binding"]
    skill = _select_capability_skill(
        profile.manifest["skill_binding"]["skills"],
        capability_id=GENERATOR_CATALOG[stage].capability,
        input_contract_ref=binding["input_schema_ref"],
        output_contract_ref=binding["output_schema_ref"],
    )

    def artifact(ref, version):
        return next(
            a
            for a in profile.artifact_catalog["artifacts"]
            if a["ref"] == ref and a["version"] == version
        )

    inputs = {
        "planning_command": {
            "planning_scope": "NOT_APPLICABLE",
            "creative_requirements_contract": "work-requirements.v2",
        },
        "frozen_inputs": [
            {"role": r, "content": {"constraints": [author], "premise": "观察城市"}}
            for r in FOUNDATION_INPUT_ROLES[stage]
        ],
        "foundation_task": foundation_task(
            stage, work_requirements=True, aligned_methods=True
        ),
    }
    context = {
        "schema_version": "novelos.planning_context_bundle.v1",
        "book_id": "book",
        "logical_key": stage,
        "planning_scope": "NOT_APPLICABLE",
        "token_budget": 16000,
        "input_versions": [
            {
                "role": i["role"],
                "asset_version_id": i["role"],
                "asset_type": i["role"],
                "content_hash": "sha256:" + "a" * 64,
                "content": i["content"],
            }
            for i in inputs["frozen_inputs"]
        ],
    }
    materialization = _prompt_materialization(context)
    materialization["pack_artifacts"] = {
        "system_instruction": artifact(
            binding["system_instruction_ref"], binding["system_instruction_version"]
        ),
        "prompt_template": artifact(
            binding["template_ref"], binding["template_version"]
        ),
        "skill": artifact(skill["skill_ref"], skill["version"]),
    }
    materialization["knowledge_selection"] = [
        artifact("knowledge:chapter-causal-cost:v2", "v2")
    ]
    materialization["output_schema"] = {
        "ref": "schema:foundation-provider-output:test:v3",
        "content": foundation_output_schema(stage, work_requirements=True),
        "content_hash": "sha256:" + "b" * 64,
    }
    *_, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
    )
    prompt, _ = _materialize_production_codex_prompt(
        request=request, stage=stage, inputs=inputs, materialization=materialization
    )
    assert author in prompt and old_method not in prompt
    assert "when selected" in prompt and "foundation-generation.v3" in prompt
    assert "## Beat planning" not in prompt and "## Book planning" not in prompt
