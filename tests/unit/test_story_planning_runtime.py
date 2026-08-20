from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
    validate_planning_contract,
)
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionEvidence,
)
from novel_forge.modules.story_design_authority import (
    GENERATOR_CATALOG,
    DesignTransition,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    CapabilityPackBackedPlanningExecutionBinder,
    FrozenPlanningInput,
    PlanningExecutionBundle,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    STORY_PLANNING_GENERATION_VERSION,
    StoryPlanningGenerationCommand,
    build_planning_constraint_envelope,
    canonical_hash,
    story_planning_generation_definition,
)
from novel_forge.modules.story_planning_runtime.execution import (
    PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS,
    _realization_reference_contract,
    planning_fixture_response as _planning_fixture_response,
    planning_provider_output_schema,
)
from novel_forge.modules.story_planning_runtime.application import (
    _AUTHORITY_INPUT_ASSET_TYPES,
    _validate_frozen_arc_references,
    StoryPlanningGenerationApplication,
)


HASH = "sha256:" + "a" * 64


def test_story_design_transition_idempotency_is_scoped_to_expected_version() -> None:
    captured: list[object] = []

    class StoryDesignCapture:
        def transition(self, command: object, *, principal: object) -> dict[str, int]:
            captured.append(command)
            return {"version": 8}

    application = object.__new__(StoryPlanningGenerationApplication)
    application.story_design = StoryDesignCapture()
    command = _command("book_plan.generate")

    result = application._transition(
        command,
        object(),
        "candidate:v1",
        HASH,
        DesignTransition.STRUCTURAL_VALIDATE,
        expected_version=7,
        evidence={"passed": True},
    )

    assert result == {"version": 8}
    transition = captured[0]
    assert transition.idempotency_key.endswith(
        ":story-design:STRUCTURAL_VALIDATE:candidate:v1:v7"
    )


def planning_fixture_response(
    stage: str, inputs: dict[str, object]
) -> dict[str, object]:
    """Build an explicitly test-only fixture with exact frozen reference lineage."""

    content = _planning_fixture_response(stage, inputs)
    command = dict(inputs.get("planning_command") or {})
    operation_id = str(
        command.get("generation_operation_id") or "operation:fixture-generation"
    )
    references: dict[tuple[str, str], dict[str, str]] = {}
    for manifest_name in ("world_realization", "character_realization"):
        for entity in content.get(manifest_name) or ():
            for field in (
                "invariant_refs",
                "structure_refs",
                "state_ref",
                "identity_ref",
                "trajectory_ref",
            ):
                value = entity.get(field)
                values = value if isinstance(value, list) else [value]
                for reference in values:
                    if not isinstance(reference, dict):
                        continue
                    frozen = {
                        "role": str(reference["authority_role"]),
                        "asset_version_id": str(reference["asset_version_id"]),
                        "content_hash": str(reference["content_hash"]),
                        "asset_type": str(reference["asset_type"]),
                    }
                    references[(frozen["asset_version_id"], frozen["role"])] = frozen
    frozen_inputs = list(references.values())
    content["frozen_inputs"] = frozen_inputs
    policy = _inherited_load_policy()
    content["constraint_envelope"] = {
        "generation_operation_id": operation_id,
        "parent_versions": [dict(item) for item in frozen_inputs],
        "narrative_load_policy": policy,
        "narrative_load_policy_lineage": {
            "type": "NarrativeLoadPolicyLineage",
            "contract_version": "narrative-load-policy-lineage-v1",
            "frozen_by_generation_operation_id": operation_id,
            "inherited_from": [
                {
                    "role": "production_profile",
                    "asset_version_id": policy["source_asset_version_id"],
                    "content_hash": policy["source_content_hash"],
                }
            ],
            "policy_hash": policy["policy_hash"],
        },
    }
    return content


def _inherited_load_policy() -> dict[str, object]:
    body: dict[str, object] = {
        "type": "NarrativeLoadPolicy",
        "contract_version": "narrative-load-policy-v1",
        "project_id": "project-1",
        "book_id": "book-1",
        "policy_id": "test-production-policy",
        "policy_version": 1,
        "source_role": "production_profile",
        "source_asset_version_id": "asset:production_profile:v1",
        "source_content_hash": HASH,
        "limits": {
            "max_active_arcs": 3,
            "max_dormant_arc_age": 30,
            "max_open_obligations": 12,
            "max_overdue_obligations": 0,
            "max_payoff_congestion": 3,
            "max_character_appearance_gap": 10,
            "max_new_concepts": 4,
            "max_major_state_transitions": 8,
        },
        "governed_overrides": [],
    }
    return {**body, "policy_hash": canonical_hash(body)}


def _with_inherited_load_policy(content: dict[str, object]) -> dict[str, object]:
    return {
        **content,
        "constraint_envelope": {
            "narrative_load_policy": _inherited_load_policy(),
        },
    }


def test_real_planning_definition_versions_the_bounded_xhigh_timeout() -> None:
    definition = story_planning_generation_definition(
        application_build_id="unit-test-build",
        commit_sha="a" * 40,
    )

    assert definition["definition_version"] == STORY_PLANNING_GENERATION_VERSION
    assert definition["timeout_policy"] == {
        "operation_timeout_seconds": STORY_PLANNING_OPERATION_TIMEOUT_SECONDS
    }


def test_planning_provider_effect_shares_the_operation_retry_budget() -> None:
    definition = story_planning_generation_definition(
        application_build_id="unit-test-build",
        commit_sha="a" * 40,
    )

    assert PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS == 3
    assert (
        definition["retry_policy"]["max_attempts"]
        == PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS
    )


@pytest.mark.parametrize(
    ("role", "runtime_asset_type"),
    (
        ("character_state", "character_state_snapshot"),
        ("foreshadowing_state", "foreshadow_snapshot"),
        ("reward_ledger", "reward_ledger_snapshot"),
        ("promise_ledger", "promise_ledger_snapshot"),
    ),
)
def test_chapter_planning_accepts_authoritative_runtime_snapshot_types(
    role: str, runtime_asset_type: str
) -> None:
    assert runtime_asset_type in _AUTHORITY_INPUT_ASSET_TYPES[role]


def test_production_planning_composition_is_available_at_the_authority_boundary() -> (
    None
):
    from novel_forge.api.authority_dependencies import (
        build_story_planning_generation_application,
    )
    from novel_forge.modules.story_planning_runtime import (
        PostgresPlanningExecutionPreparer,
    )

    assert callable(build_story_planning_generation_application)
    assert PostgresPlanningExecutionPreparer.production_execution_gateway_backed is True


def test_scripted_semantic_evaluation_requires_explicit_test_runtime() -> None:
    from novel_forge.api.authority_dependencies import (
        _scripted_narrative_evaluation_fixture_enabled,
    )
    from novel_forge.infrastructure.environment import RuntimeEnvironment

    flag = {"NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true"}
    assert not _scripted_narrative_evaluation_fixture_enabled(
        RuntimeEnvironment.DEVELOPMENT, flag
    )
    assert not _scripted_narrative_evaluation_fixture_enabled(
        RuntimeEnvironment.TEST, {}
    )
    assert _scripted_narrative_evaluation_fixture_enabled(RuntimeEnvironment.TEST, flag)


@pytest.mark.parametrize("contract_type", list(PlanContractType))
def test_planning_provider_schema_is_codex_strict(
    contract_type: PlanContractType,
) -> None:
    schema = planning_provider_output_schema(
        contract_type,
        logical_key="logical:proof",
        parent_version_id="parent:v1",
        arc_plan_version_id="arc:v1",
        dependency_version_ids=("input:a", "input:b"),
    )

    def assert_strict(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
                assert set(value.get("required") or ()) == set(
                    (value.get("properties") or {}).keys()
                )
            for child in value.values():
                assert_strict(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict(child)

    assert_strict(schema)
    assert schema["properties"]["logical_key"]["const"] == "logical:proof"
    assert schema["properties"]["canon_dependencies"]["items"]["enum"] == [
        "input:a",
        "input:b",
    ]
    world = schema["properties"]["world_realization"]["items"]["properties"]
    character = schema["properties"]["character_realization"]["items"][
        "properties"
    ]
    assert world["invariant_refs"]["items"]["properties"]["domain_type"] == {
        "type": "string",
        "const": "WORLD_INVARIANT",
    }
    assert "world_invariant" not in world["invariant_refs"]["items"][
        "properties"
    ]["authority_role"]["enum"]
    assert "book_design" not in character["state_ref"]["properties"][
        "authority_role"
    ]["enum"]
    if contract_type not in {PlanContractType.BOOK, PlanContractType.ARC}:
        assert schema["properties"]["parent_version_id"]["const"] == "parent:v1"
    if contract_type is PlanContractType.ARC:
        assert "parent_version_id" not in schema["properties"]
        assert schema["properties"]["thread_id"]["minLength"] == 1
        assert schema["properties"]["arc_segments"]["minItems"] == 1
    if contract_type in {PlanContractType.VOLUME, PlanContractType.CHAPTER_GROUP}:
        assert schema["properties"]["chapter_range"]["minItems"] == 2
        assert schema["properties"]["chapter_range"]["maxItems"] == 2
    if contract_type is PlanContractType.CHAPTER:
        assert schema["properties"]["required_arc_contributions"]["maxItems"] == 1
        assert schema["properties"]["arc_schedule"]["maxItems"] == 1
        assert (
            schema["properties"]["arc_schedule"]["items"]["properties"][
                "arc_plan_version_id"
            ]["const"]
            == "arc:v1"
        )
        assert (
            "never repeat one Arc"
            in (
                schema["properties"]["arc_schedule"]["items"]["properties"]["role"][
                    "description"
                ]
            )
        )
        assert schema["properties"]["title"]["maxLength"] == 120
        assert schema["properties"]["premise"]["maxLength"] == 320
        assert "reader-facing" in schema["properties"]["title"]["description"]
        state_kinds = schema["properties"]["required_state_transitions"]["items"][
            "properties"
        ]["state_kind"]["enum"]
        assert "character_arc" in state_kinds
        assert "reader_knowledge" not in state_kinds
        assert "official_record_status" not in state_kinds
        knowledge = schema["properties"]["knowledge_boundaries"]
        assert knowledge["maxItems"] == 12
        assert knowledge["items"]["properties"]["status"]["enum"] == [
            "TRUE",
            "FALSE",
            "UNKNOWN",
            "HINTED",
            "SUSPECTED",
            "KNOWN",
            "MISDIRECTED",
            "WITHHELD",
            "FORGOTTEN",
            "BELIEVES",
            "DOUBTS",
            "DISBELIEVES",
            "UNCERTAIN",
        ]
        assert schema["properties"]["required_state_transitions"]["maxItems"] == 8


def test_realization_reference_contract_exposes_exact_frozen_authority_choices() -> None:
    contract = _realization_reference_contract(
        project_id="project-1",
        book_id="book-1",
        frozen_by_operation_id="operation:planning",
        inputs=(
            FrozenPlanningInput("world_bible", "world:v1", HASH, "world_bible"),
            FrozenPlanningInput(
                "character_cast", "cast:v1", HASH, "character_cast"
            ),
        ),
    )

    world = contract["references_by_domain"]["WORLD_STATE"]
    character = contract["references_by_domain"]["CHARACTER_STATE"]
    assert world == [
        {
            "project_id": "project-1",
            "book_id": "book-1",
            "authority_role": "world_bible",
            "asset_version_id": "world:v1",
            "asset_type": "world_bible",
            "content_hash": HASH,
            "domain_type": "WORLD_STATE",
            "freshness": "CURRENT",
            "frozen_by_operation_id": "operation:planning",
        }
    ]
    assert character[0]["authority_role"] == "character_cast"
    assert character[0]["asset_version_id"] == "cast:v1"


def test_volume_and_chapter_provider_contracts_bind_timeline_segments() -> None:
    volume = planning_provider_output_schema(PlanContractType.VOLUME)
    chapter = planning_provider_output_schema(
        PlanContractType.CHAPTER,
        parent_version_id="group:v1",
        arc_plan_version_id="arc:v1",
    )

    assert volume["properties"]["narrative_segments"]["minItems"] == 1
    assert set(volume["properties"]["narrative_segments"]["items"]["required"]) == {
        "segment_id",
        "objective",
        "chapter_range",
        "entry_state_ref",
        "exit_state_spec",
        "arc_checkpoint_refs",
    }
    assert set(chapter["properties"]["narrative_segment_ref"]["required"]) == {
        "volume_plan_version_id",
        "segment_id",
    }
    for field in (
        "chapter_intent",
        "arc_schedule",
        "setups",
        "payoffs",
        "character_participation",
        "knowledge_boundaries",
        "disclosures",
        "required_state_transitions",
        "reader_experience",
        "scene_plan",
        "expected_exit_state",
    ):
        assert field in chapter["required"]

    assert "narrative_qualification" not in chapter["properties"]


@pytest.mark.parametrize(
    ("contract_type", "expected_horizon", "expected_realization"),
    (
        (PlanContractType.BOOK, "STRATEGIC", "ANCHOR"),
        (PlanContractType.VOLUME, "STRATEGIC", "DEFINED"),
        (PlanContractType.ARC, "STRATEGIC", "DEFINED"),
        (PlanContractType.CHAPTER_GROUP, "TACTICAL", "DETAILED"),
        (PlanContractType.CHAPTER, "OPERATIONAL", "ACTIVE"),
    ),
)
def test_canonical_contracts_freeze_progressive_horizon_and_realization(
    contract_type: PlanContractType,
    expected_horizon: str,
    expected_realization: str,
) -> None:
    stage = {
        PlanContractType.BOOK: "book_plan.generate",
        PlanContractType.VOLUME: "volume_plan.generate",
        PlanContractType.ARC: "arc_plan.generate",
        PlanContractType.CHAPTER_GROUP: "chapter_group_plan.generate",
        PlanContractType.CHAPTER: "chapter_plan.generate",
    }[contract_type]
    parent = (
        ""
        if contract_type in {PlanContractType.BOOK, PlanContractType.ARC}
        else "parent:v1"
    )
    content = planning_fixture_response(
        stage,
        {
            "planning_command": {
                "logical_key": f"{contract_type.value.lower()}:proof",
                "parent_version_id": parent,
                "input_versions": {
                    "arc_plans": "arc:v1",
                    "volume_plan": "volume:v1",
                },
            }
        },
    )

    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=contract_type,
        asset_version_id=f"{contract_type.value.lower()}:v1",
        parent_version_id=parent,
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )

    assert contract.content["planning_horizon"] == expected_horizon
    assert contract.content["realization_level"] == expected_realization
    assert (
        contract.content["world_realization"][0]["realization_level"]
        == expected_realization
    )
    assert (
        contract.content["character_realization"][0]["realization_level"]
        == expected_realization
    )


def test_operational_plan_fails_closed_on_open_design_space_and_load_overrun() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["commitment_contract"][1]["level"] = "OPEN_DESIGN_SPACE"

    with pytest.raises(KernelError, match="PLANNING_OPERATIONAL_COMMITMENT_OPEN"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_operational_plan_consumes_accepted_narrative_debt_projection() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["constraint_envelope"]["narrative_load_projection"] = {
        "status": "MEASURED",
        "accepted_through_chapter": 1,
        "metrics": {"overdue_obligation_count": 1},
        "overdue_obligation_ids": ["obligation:overdue-x"],
    }

    with pytest.raises(KernelError, match="NARRATIVE_DEBT_PAYDOWN_REQUIRED"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )

    content["payoffs"][0]["action"] = "PAYOFF"
    with pytest.raises(KernelError, match="NARRATIVE_DEBT_PAYDOWN_REQUIRED"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:unrelated-payoff",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )

    content["payoffs"].append(
        {
            "obligation_id": "obligation:overdue-x",
            "action": "RESCHEDULE",
            "opened_chapter": 1,
            "due_chapter": 4,
        }
    )
    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.CHAPTER,
        asset_version_id="chapter:v2",
        parent_version_id="chapter-group:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )
    assert contract.logical_key == "chapter:2"

    content["narrative_load_budget"] = {"max_major_state_transitions": 99}
    with pytest.raises(KernelError, match="CANDIDATE_NARRATIVE_LOAD_POLICY_FORBIDDEN"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:self-raised-guardrail",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )
    content.pop("narrative_load_budget")
    content["payoffs"].extend(
        {
            "obligation_id": f"obligation:congestion:{index}",
            "action": "ADVANCE",
            "opened_chapter": 1,
            "due_chapter": 4,
        }
        for index in range(2)
    )
    with pytest.raises(KernelError, match="NARRATIVE_LOAD_BUDGET_EXCEEDED"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_overdue_identity_requires_action_even_within_numeric_allowance() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    policy = _inherited_load_policy()
    policy["limits"]["max_overdue_obligations"] = 1  # type: ignore[index]
    policy_body = {key: value for key, value in policy.items() if key != "policy_hash"}
    policy["policy_hash"] = canonical_hash(policy_body)
    content["constraint_envelope"].update(
        {
            "narrative_load_policy": policy,
            "narrative_load_policy_lineage": {
                "policy_hash": policy["policy_hash"],
                "frozen_by_generation_operation_id": "operation:fixture-generation",
                "inherited_from": [policy["source_asset_version_id"]],
            },
            "narrative_load_projection": {
                "status": "MEASURED",
                "accepted_through_chapter": 1,
                "metrics": {
                    "open_obligation_count": 1,
                    "overdue_obligation_count": 1,
                },
                "open_obligation_ids": ["obligation:overdue-x"],
                "overdue_obligation_ids": ["obligation:overdue-x"],
            },
        }
    )

    with pytest.raises(KernelError, match="NARRATIVE_DEBT_PAYDOWN_REQUIRED"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:within-overdue-allowance",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )

    content["payoffs"].append(
        {
            "obligation_id": "obligation:overdue-x",
            "action": "EXPLICIT_GOVERNANCE_ACTION",
            "opened_chapter": 1,
            "due_chapter": 2,
            "governance_action_asset_version_id": "governance:overdue-x:v1",
            "governance_action_content_hash": "sha256:" + "f" * 64,
        }
    )
    governance_input = {
        "role": "narrative_governance_action",
        "asset_version_id": "governance:overdue-x:v1",
        "content_hash": "sha256:" + "f" * 64,
        "asset_type": "narrative_governance_action",
    }
    content["frozen_inputs"].append(governance_input)
    content["constraint_envelope"]["parent_versions"].append(governance_input)
    validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.CHAPTER,
        asset_version_id="chapter:governed-overdue",
        parent_version_id="chapter-group:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )


def test_chapter_provider_contract_accepts_only_the_frozen_arc_portfolio() -> None:
    schema = planning_provider_output_schema(
        PlanContractType.CHAPTER,
        parent_version_id="group:v1",
        arc_plan_version_id="arc:v1",
        related_arc_plan_version_ids=("arc:v2", "arc:v3"),
    )

    assert schema["properties"]["arc_schedule"]["maxItems"] == 3
    assert schema["properties"]["arc_schedule"]["items"]["properties"][
        "arc_plan_version_id"
    ]["enum"] == ["arc:v1", "arc:v2", "arc:v3"]
    assert schema["properties"]["required_arc_contributions"]["maxItems"] == 3


def test_chapter_group_contract_rejects_non_pair_range_as_governed_error() -> None:
    content = planning_fixture_response(
        "chapter_group_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter-group:1-3",
                "parent_version_id": "volume:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["chapter_range"] = [1, 2, 3]

    with pytest.raises(KernelError, match="CHAPTER_GROUP_RANGE_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER_GROUP,
            asset_version_id="chapter-group:v1",
            parent_version_id="volume:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_chapter_contract_rejects_duplicate_arc_contribution_identity() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["required_arc_contributions"] = [
        {"arc_plan_version_id": "arc:v1", "contribution": "advance choice"},
        {"arc_plan_version_id": "arc:v1", "contribution": "accept cost"},
    ]

    with pytest.raises(
        KernelError, match="PLANNING_ARC_CONTRIBUTION_IDENTITY_DUPLICATE"
    ):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_chapter_contract_rejects_noncanonical_state_kind() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["required_state_transitions"][0]["state_kind"] = "official_record_status"

    with pytest.raises(KernelError, match="CHAPTER_STATE_TRANSITION_KIND_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_chapter_contract_derives_reader_knowledge_from_disclosure_mode() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["knowledge_boundaries"][0]["status"] = "KNOWN"
    content["disclosures"][0]["mode"] = "HINT"

    with pytest.raises(
        KernelError, match="CHAPTER_READER_KNOWLEDGE_DERIVATION_INVALID"
    ):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_chapter_contract_accepts_withheld_reader_boundary_without_state_advance() -> (
    None
):
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["knowledge_boundaries"][0]["status"] = "WITHHELD"
    content["disclosures"][0]["mode"] = "WITHHOLD"

    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.CHAPTER,
        asset_version_id="chapter:v2",
        parent_version_id="chapter-group:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )

    assert contract.content["knowledge_boundaries"][0]["status"] == "WITHHELD"


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    (
        (
            lambda content: content["knowledge_boundaries"][0].update(
                {"available_from_chapter": content["chapter_number"] + 1}
            ),
            "CHAPTER_KNOWLEDGE_FUTURE_LEAK",
        ),
        (
            lambda content: content["required_state_transitions"][0].update(
                {"to_state": content["required_state_transitions"][0]["from_state"]}
            ),
            "CHAPTER_STATE_TRANSITION_NOOP",
        ),
        (
            lambda content: content["scene_plan"].append(
                dict(content["scene_plan"][0])
            ),
            "SCENE_ARCHITECTURE_IDENTITY_DUPLICATE",
        ),
    ),
)
def test_chapter_contract_rejects_temporal_and_scene_structural_failures(
    mutate, error_code: str
) -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    mutate(content)

    with pytest.raises(KernelError, match=error_code):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_scene_contract_enforces_pov_time_relation_and_spatial_access() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["scene_plan"][0]["accessible_knowledge"] = ["fact:hidden-cost"]
    with pytest.raises(KernelError, match="SCENE_HIDDEN_KNOWLEDGE_LEAK"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )

    content["character_participation"][0]["known_fact_ids"] = ["fact:hidden-cost"]
    content["scene_plan"].append(
        {
            **content["scene_plan"][0],
            "scene_id": "chapter:2:scene:2",
            "entry_state": content["scene_plan"][0]["exit_state"],
            "narrative_time_relation": "FLASHBACK",
            "story_time": {
                **content["scene_plan"][0]["story_time"],
                "start_ordinal": 1,
                "end_ordinal": 2,
            },
        }
    )
    validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.CHAPTER,
        asset_version_id="chapter:v2",
        parent_version_id="chapter-group:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )

    content["scene_plan"][1]["narrative_time_relation"] = "ADVANCES"
    with pytest.raises(KernelError, match="SCENE_STORY_TIME_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )

    content["scene_plan"][1]["narrative_time_relation"] = "FLASHBACK"
    content["scene_plan"][1]["location_id"] = "location:unreachable"
    with pytest.raises(KernelError, match="SCENE_SPATIAL_ACCESS_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:v2",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_progressive_realization_can_refine_strategic_versions() -> None:
    content = planning_fixture_response(
        "volume_plan.generate",
        {
            "planning_command": {
                "logical_key": "volume:1",
                "parent_version_id": "book-plan:v1",
                "input_versions": {},
            }
        },
    )
    for level in ("ANCHOR", "ACTIVE"):
        content["realization_level"] = level
        for item in (
            *content["world_realization"],
            *content["character_realization"],
        ):
            item["realization_level"] = level
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.VOLUME,
            asset_version_id=f"volume:{level.lower()}",
            parent_version_id="book-plan:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )

    chapter = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    chapter["realization_level"] = "ANCHOR"
    for item in (*chapter["world_realization"], *chapter["character_realization"]):
        item["realization_level"] = "ANCHOR"
    with pytest.raises(KernelError, match="PLANNING_REALIZATION_LEVEL_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:anchor",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=chapter,
        )


def test_one_plan_supports_entity_specific_progressive_realization() -> None:
    content = planning_fixture_response(
        "volume_plan.generate",
        {
            "planning_command": {
                "logical_key": "volume:1",
                "parent_version_id": "book-plan:v1",
                "input_versions": {},
            }
        },
    )
    city = content["world_realization"][0]
    city["world_id"] = "world:current-city"
    city["realization_level"] = "ACTIVE"
    nearby_faction = deepcopy(city)
    nearby_faction.update(
        {
            "world_id": "world:nearby-faction",
            "realization_level": "DETAILED",
            "narrative_relevance": "NEAR_FUTURE",
        }
    )
    distant_empire = deepcopy(city)
    distant_empire.update(
        {
            "world_id": "world:distant-empire",
            "realization_level": "ANCHOR",
            "narrative_relevance": "FUTURE",
        }
    )
    content["world_realization"].extend([nearby_faction, distant_empire])
    protagonist = content["character_realization"][0]
    protagonist["realization_level"] = "ACTIVE"
    next_volume_actor = deepcopy(protagonist)
    next_volume_actor.update(
        {
            "character_id": "character:next-volume-actor",
            "realization_level": "DEFINED",
            "narrative_relevance": "FUTURE",
        }
    )
    content["character_realization"].append(next_volume_actor)

    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.VOLUME,
        asset_version_id="volume:mixed-realization",
        parent_version_id="book-plan:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )

    assert {
        item["realization_level"] for item in contract.content["world_realization"]
    } == {"ACTIVE", "DETAILED", "ANCHOR"}
    assert {
        item["realization_level"] for item in contract.content["character_realization"]
    } == {"ACTIVE", "DEFINED"}


def test_current_entity_cannot_be_less_realized_than_plan_horizon() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["character_realization"][0]["realization_level"] = "ANCHOR"

    with pytest.raises(KernelError, match="CHARACTER_REALIZATION_HORIZON_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:under-realized",
            parent_version_id="chapter-group:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_realization_reference_must_match_frozen_authority_version_and_hash() -> None:
    command = _command("volume_plan.generate")
    inputs = _inputs(command)
    generation_operation_id = "operation:realization-lineage"
    frozen = [
        {
            "role": item.role,
            "asset_version_id": item.asset_version_id,
            "content_hash": item.content_hash,
            "asset_type": item.asset_type,
        }
        for item in inputs
    ]
    content = planning_fixture_response(
        command.generator_operation_name,
        {
            "planning_command": {
                "project_id": command.project_id,
                "book_id": command.book_id,
                "generation_operation_id": generation_operation_id,
                "logical_key": command.logical_key,
                "parent_version_id": "book-plan:v1",
                "input_versions": dict(command.input_versions),
            },
            "frozen_inputs": frozen,
        },
    )
    content["frozen_inputs"] = frozen
    content["constraint_envelope"] = build_planning_constraint_envelope(
        project_id=command.project_id,
        book_id=command.book_id,
        generation_operation_id=generation_operation_id,
        generator_operation_name=command.generator_operation_name,
        frozen_inputs=inputs,
        input_contents={
            item.role: (
                _with_inherited_load_policy({}) if item.role == "book_plan" else {}
            )
            for item in inputs
        },
        candidate_payload=content,
    )

    validate_planning_contract(
        project_id=command.project_id,
        book_id=command.book_id,
        contract_type=PlanContractType.VOLUME,
        asset_version_id="volume:lineage-valid",
        parent_version_id="book-plan:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )
    content["world_realization"][0]["state_ref"]["content_hash"] = "sha256:" + "b" * 64
    with pytest.raises(KernelError, match="WORLD_REALIZATION_REFERENCE_STALE"):
        validate_planning_contract(
            project_id=command.project_id,
            book_id=command.book_id,
            contract_type=PlanContractType.VOLUME,
            asset_version_id="volume:lineage-stale",
            parent_version_id="book-plan:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_realization_domain_cannot_be_self_asserted_by_wrong_authority_role() -> None:
    content = planning_fixture_response(
        "volume_plan.generate",
        {
            "planning_command": {
                "logical_key": "volume:1",
                "parent_version_id": "book-plan:v1",
                "input_versions": {},
            }
        },
    )
    reference = content["world_realization"][0]["invariant_refs"][0]
    reference.update(
        authority_role="character_cast",
        asset_type="character_cast",
        domain_type="WORLD_INVARIANT",
    )

    with pytest.raises(KernelError, match="WORLD_REALIZATION_REFERENCE_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.VOLUME,
            asset_version_id="volume:wrong-domain-authority",
            parent_version_id="book-plan:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_book_contract_rejects_impossible_obligation_window() -> None:
    content = planning_fixture_response(
        "book_plan.generate",
        {"planning_command": {"logical_key": "book:main", "input_versions": {}}},
    )
    content["knowledge_disclosure_obligations"]["obligation_windows"][0].update(
        {"setup_chapter": 3, "payoff_not_before": 2, "payoff_due_by": 1}
    )

    with pytest.raises(KernelError, match="NARRATIVE_OBLIGATION_WINDOW_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.BOOK,
            asset_version_id="book-plan:v1",
            parent_version_id="",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_volume_contract_rejects_gapped_narrative_segments() -> None:
    content = planning_fixture_response(
        "volume_plan.generate",
        {
            "planning_command": {
                "logical_key": "volume:1",
                "parent_version_id": "book-plan:v1",
                "input_versions": {},
            }
        },
    )
    content["narrative_segments"] = [
        {**content["narrative_segments"][0], "chapter_range": [1, 1]},
        {
            **content["narrative_segments"][0],
            "segment_id": "narrative-segment:2",
            "chapter_range": [3, 3],
        },
    ]

    with pytest.raises(KernelError, match="NARRATIVE_SEGMENT_COVERAGE_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.VOLUME,
            asset_version_id="volume:v1",
            parent_version_id="book-plan:v1",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_arc_contract_rejects_invalid_typed_relation() -> None:
    content = planning_fixture_response(
        "arc_plan.generate",
        {
            "planning_command": {
                "logical_key": "arc:main",
                "input_versions": {"volume_plan": "volume:v1"},
            }
        },
    )
    content["arc_relations"] = [
        {
            "relation_id": "relation:1",
            "relation_type": "CONTAINS",
            "source_arc_ref": "arc:main",
            "target_arc_ref": "arc:secondary",
            "trigger_or_condition": "the public choice",
        }
    ]

    with pytest.raises(KernelError, match="NARRATIVE_ARC_RELATION_INVALID"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.ARC,
            asset_version_id="arc:v1",
            parent_version_id="",
            execution_scope=PlanExecutionScope.PLANNED,
            content=content,
        )


def test_chapter_contract_preserves_explicit_empty_arc_contribution_policy() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2",
                "parent_version_id": "chapter-group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    content["required_arc_contributions"] = []
    content.pop("narrative_architecture_version")

    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.CHAPTER,
        asset_version_id="chapter:v2",
        parent_version_id="chapter-group:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )

    assert contract.content["required_arc_contributions"] == []


def test_planning_fixture_preserves_requested_chapter_number() -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:2:after:replan-1",
                "parent_version_id": "chapter-group:v2",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )

    assert content["chapter_number"] == 2
    assert content["title"].startswith("Chapter 2:")
    assert content["primary_function"] == "reversal"
    assert content["ending_hook"] == "ally defects"


def test_planning_fixture_applies_frozen_change_evidence() -> None:
    base = {
        "logical_key": "chapter-group:1",
        "parent_version_id": "volume:v1",
        "input_versions": {},
    }
    original = planning_fixture_response(
        "chapter_group_plan.generate", {"planning_command": base}
    )
    replacement = planning_fixture_response(
        "chapter_group_plan.generate",
        {
            "planning_command": {
                **base,
                "change_evidence_version_ids": ["recap:v1", "replan-request:v1"],
            }
        },
    )

    assert replacement["objective"] != original["objective"]
    assert "governed change evidence" in replacement["objective"]


def _command(generator: str) -> StoryPlanningGenerationCommand:
    return StoryPlanningGenerationCommand(
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
        actor_id="planner",
        generator_operation_name=generator,
        logical_key=f"{generator}:main",
        input_versions={
            role: f"asset:{role}:v1" for role in GENERATOR_INPUT_ROLES[generator]
        },
        idempotency_key=f"generate:{generator}",
        trace_id="trace-1",
        correlation_id="correlation-1",
    )


def _inputs(command: StoryPlanningGenerationCommand) -> tuple[FrozenPlanningInput, ...]:
    return tuple(
        FrozenPlanningInput(role, version, HASH, role)
        for role, version in command.input_versions.items()
    )


@pytest.mark.parametrize("generator", sorted(GENERATOR_INPUT_ROLES))
def test_five_planning_generators_require_exact_authority_input_roles(
    generator: str,
) -> None:
    command = _command(generator)
    assert (
        command.generator_operation_name == GENERATOR_CATALOG[generator].operation_name
    )
    assert {item.role for item in _inputs(command)} == set(
        GENERATOR_INPUT_ROLES[generator]
    )

    incomplete = dict(command.input_versions)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(ValueError, match="Authority role set"):
        StoryPlanningGenerationCommand(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            actor_id=command.actor_id,
            generator_operation_name=generator,
            logical_key=command.logical_key,
            input_versions=incomplete,
            idempotency_key="incomplete",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )


def test_planning_change_evidence_cannot_alias_generator_input() -> None:
    command = _command("book_plan.generate")

    with pytest.raises(ValueError, match="change evidence identity"):
        StoryPlanningGenerationCommand(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            actor_id=command.actor_id,
            generator_operation_name=command.generator_operation_name,
            logical_key=command.logical_key,
            input_versions=command.input_versions,
            idempotency_key=command.idempotency_key,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            change_evidence_version_ids=(next(iter(command.input_versions.values())),),
        )


def test_arc_generation_freezes_multi_volume_and_related_arc_scope() -> None:
    base = _command("arc_plan.generate")
    command = StoryPlanningGenerationCommand(
        project_id=base.project_id,
        workspace_id=base.workspace_id,
        book_id=base.book_id,
        actor_id=base.actor_id,
        generator_operation_name=base.generator_operation_name,
        logical_key=base.logical_key,
        input_versions=base.input_versions,
        arc_scope_volume_plan_version_ids=("volume:v2", "volume:v3"),
        related_arc_plan_version_ids=("arc:v2",),
        dependent_arc_plan_version_ids=("arc:v3",),
        idempotency_key=base.idempotency_key,
        trace_id=base.trace_id,
        correlation_id=base.correlation_id,
    )
    scope_inputs = (
        *_inputs(command),
        FrozenPlanningInput("arc_scope_volume:1", "volume:v2", HASH, "volume_plan"),
        FrozenPlanningInput("arc_scope_volume:2", "volume:v3", HASH, "volume_plan"),
        FrozenPlanningInput("related_arc:1", "arc:v2", HASH, "arc_plan"),
        FrozenPlanningInput("dependent_arc:1", "arc:v3", HASH, "arc_plan"),
    )
    contents = {item.role: {} for item in scope_inputs}
    contents["book_plan"] = _with_inherited_load_policy({})

    fixture = planning_fixture_response(
        "arc_plan.generate",
        {
            "planning_command": {
                "logical_key": command.logical_key,
                "input_versions": dict(command.input_versions),
                "arc_scope_volume_plan_version_ids": list(
                    command.arc_scope_volume_plan_version_ids
                ),
                "related_arc_plan_version_ids": list(
                    command.related_arc_plan_version_ids
                ),
                "dependent_arc_plan_version_ids": list(
                    command.dependent_arc_plan_version_ids
                ),
            }
        },
    )
    envelope = build_planning_constraint_envelope(
        project_id="project-1",
        book_id="book-1",
        generation_operation_id="operation:arc-proof",
        generator_operation_name=command.generator_operation_name,
        frozen_inputs=scope_inputs,
        input_contents=contents,
        candidate_payload=fixture,
    )

    assert fixture["cross_volume_scope"] == [
        command.input_versions["volume_plan"],
        "volume:v2",
        "volume:v3",
    ]
    assert {item["volume_plan_version_id"] for item in fixture["arc_segments"]} == set(
        fixture["cross_volume_scope"]
    )
    assert fixture["arc_relations"] == [
        {
            "relation_id": f"relation:incoming:{command.logical_key}:1",
            "relation_type": "ENABLES",
            "source_arc_ref": "arc:v2",
            "target_arc_ref": command.logical_key,
            "trigger_or_condition": "the related Arc enables the candidate Arc",
        },
        {
            "relation_id": f"relation:outgoing:{command.logical_key}:1",
            "relation_type": "ENABLES",
            "source_arc_ref": command.logical_key,
            "target_arc_ref": "arc:v3",
            "trigger_or_condition": "the candidate Arc enables the dependent Arc",
        },
    ]
    assert len(envelope["parent_versions"]) == len(scope_inputs)


def test_arc_generation_rejects_relation_outside_frozen_portfolio() -> None:
    base = _command("arc_plan.generate")
    command = StoryPlanningGenerationCommand(
        project_id=base.project_id,
        workspace_id=base.workspace_id,
        book_id=base.book_id,
        actor_id=base.actor_id,
        generator_operation_name=base.generator_operation_name,
        logical_key=base.logical_key,
        input_versions=base.input_versions,
        related_arc_plan_version_ids=("arc:v2",),
        idempotency_key=base.idempotency_key,
        trace_id=base.trace_id,
        correlation_id=base.correlation_id,
    )

    with pytest.raises(KernelError, match="PLANNING_ARC_RELATION_SCOPE_INVALID"):
        _validate_frozen_arc_references(
            command,
            {
                "arc_relations": [
                    {
                        "source_arc_ref": command.logical_key,
                        "target_arc_ref": "arc:not-frozen",
                    }
                ]
            },
        )


def test_scheduling_generation_freezes_related_arc_portfolio() -> None:
    base = _command("chapter_group_plan.generate")
    command = StoryPlanningGenerationCommand(
        project_id=base.project_id,
        workspace_id=base.workspace_id,
        book_id=base.book_id,
        actor_id=base.actor_id,
        generator_operation_name=base.generator_operation_name,
        logical_key=base.logical_key,
        input_versions=base.input_versions,
        related_arc_plan_version_ids=("arc:v2", "arc:v3"),
        idempotency_key=base.idempotency_key,
        trace_id=base.trace_id,
        correlation_id=base.correlation_id,
    )
    frozen = (
        *_inputs(command),
        FrozenPlanningInput("related_arc:1", "arc:v2", HASH, "arc_plan"),
        FrozenPlanningInput("related_arc:2", "arc:v3", HASH, "arc_plan"),
    )
    contents = {item.role: {} for item in frozen}
    contents["book_plan"] = _with_inherited_load_policy({})
    fixture = planning_fixture_response(
        command.generator_operation_name,
        {
            "planning_command": {
                "logical_key": command.logical_key,
                "input_versions": dict(command.input_versions),
                "related_arc_plan_version_ids": list(
                    command.related_arc_plan_version_ids
                ),
            }
        },
    )
    envelope = build_planning_constraint_envelope(
        project_id="project-1",
        book_id="book-1",
        generation_operation_id="operation:scheduling-proof",
        generator_operation_name=command.generator_operation_name,
        frozen_inputs=frozen,
        input_contents=contents,
        candidate_payload=fixture,
    )

    assert {
        item["arc_plan_version_id"]
        for item in fixture["chapter_function_matrix"][0]["arc_cadence"]
    } == {command.input_versions["arc_plans"], "arc:v2", "arc:v3"}
    assert len(envelope["parent_versions"]) == len(frozen)


class _ExecutionPort:
    production_execution_gateway_backed = True
    external_effect_backed = True

    def execute(self, command):
        return DomainExecutionCandidate(
            candidate_kind=CandidateKind.GENERATION,
            raw_output={"objective": "Advance the governed story plan"},
            evidence=DomainExecutionEvidence(
                execution_id="execution-1",
                operation_id="operation-1",
                attempt_id="attempt-1",
                fencing_token=7,
                capability=command.capability,
                backend_id="scripted-fixture",
                route_snapshot_id="route-1",
                input_manifest_ref="input-1",
                output_manifest_ref="output-1",
                validation_manifest_ref="validation-1",
                usage_receipt_ref="usage-1",
                cost_receipt_ref="cost-1",
                fixture_protocol_only=True,
                real_model_call=False,
                production_verified=False,
                external_receipt_ref="external-effect-receipt-1",
            ),
        )


class _Resolver:
    def __init__(self, *, commit_authority: str = "STORY_DESIGN_AUTHORITY") -> None:
        self.commit_authority = commit_authority

    def resolve(self, **kwargs):
        definition = kwargs["definition"]
        snapshot = SimpleNamespace(
            operation_id="operation-1",
            attempt_id="attempt-1",
            execution_fencing_token=7,
            snapshot_id=HASH,
            snapshot_hash=HASH,
            execution_snapshot=SimpleNamespace(
                execution_capability_id=definition.capability,
                prompt_bundle_ref="prompt-bundle:planning:v1",
            ),
        )
        work_order = SimpleNamespace(
            operation_id="operation-1",
            attempt_id="attempt-1",
            fencing_token=7,
            execution_capability=definition.capability,
            project_id="project-1",
            book_id="book-1",
            work_order_id="work-order-1",
            to_context=lambda: {"work_order_id": "work-order-1"},
        )
        binding = SimpleNamespace(
            operation_id="operation-1",
            attempt_id="attempt-1",
            fencing_token=7,
            execution_capability_id=definition.capability,
            capability_pack_attempt_snapshot_id=HASH,
            capability_pack_attempt_snapshot_hash=HASH,
            commit_authority=self.commit_authority,
            input_manifest_ref="input-1",
            binding_id="binding-1",
            binding_hash=HASH,
        )
        return PlanningExecutionBundle(snapshot, work_order, binding, _ExecutionPort())


def test_planning_binder_requires_pack_agent_and_pep_on_one_attempt() -> None:
    command = _command("book_plan.generate")
    candidate = CapabilityPackBackedPlanningExecutionBinder(_Resolver()).execute(
        operation_id="operation-1",
        attempt_id="attempt-1",
        fencing_token=7,
        worker_id="planning-worker",
        command=command,
        inputs=_inputs(command),
        definition=GENERATOR_CATALOG[command.generator_operation_name],
    )

    assert candidate.evidence.operation_id == "operation-1"
    assert candidate.evidence.capability_pack_attempt_snapshot_id == HASH
    assert candidate.evidence.fixture_protocol_only is True
    assert candidate.authority_content(project_id="project-1", book_id="book-1")[
        "candidate_payload"
    ]["objective"]


def test_planning_agent_cannot_claim_chapter_commit_authority() -> None:
    command = _command("chapter_plan.generate")
    with pytest.raises(KernelError, match="Planning Agent can only submit"):
        CapabilityPackBackedPlanningExecutionBinder(
            _Resolver(commit_authority="CHAPTER_AUTHORITY")
        ).execute(
            operation_id="operation-1",
            attempt_id="attempt-1",
            fencing_token=7,
            worker_id="planning-worker",
            command=command,
            inputs=_inputs(command),
            definition=GENERATOR_CATALOG[command.generator_operation_name],
        )


def test_planning_constraint_envelope_propagates_parent_invariants_and_scope() -> None:
    command = _command("chapter_plan.generate")
    inputs = _inputs(command)
    contents = {
        role: {} for role in GENERATOR_INPUT_ROLES[command.generator_operation_name]
    }
    contents["book_plan"] = {
        "invariants": ["the succession law cannot be waived"],
        "prohibited_outcomes": ["the dead regent returns alive"],
    }
    contents["book_plan"] = _with_inherited_load_policy(contents["book_plan"])
    contents["story_state"] = {
        "accepted_through_chapter": 11,
        "unresolved_obligation_ids": ["obligation:sealed-door"],
    }

    envelope = build_planning_constraint_envelope(
        project_id="project-1",
        book_id="book-1",
        generation_operation_id="operation:constraint-proof",
        generator_operation_name=command.generator_operation_name,
        frozen_inputs=inputs,
        input_contents=contents,
        candidate_payload={
            "objective": "Force the heir to choose publicly",
            "prohibited_outcomes": ["resolve the sealed door off-page"],
        },
    )

    assert envelope["planning_scope"] == "CHAPTER"
    assert envelope["permitted_change_scope"] == "CHAPTER"
    assert envelope["accepted_state_boundary"] == {
        "accepted_through_chapter": 11,
        "future_plan_only": True,
    }
    assert len(envelope["parent_versions"]) == len(
        GENERATOR_INPUT_ROLES["chapter_plan.generate"]
    )
    assert envelope["inherited_invariants"][0]["constraint"] == (
        "the succession law cannot be waived"
    )
    assert envelope["required_obligations"][0]["constraint"] == (
        "obligation:sealed-door"
    )
    assert envelope["change_governance"]["preserve_executed_history"] is True
    assert envelope["envelope_digest"].startswith("sha256:")
