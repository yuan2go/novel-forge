from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
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
    PostgresPlanningExecutionPreparer,
    _planning_repair_routing_lineage,
    _recent_activated_repetition_keys,
    _realization_reference_contract,
    planning_fixture_response as _planning_fixture_response,
    planning_provider_output_schema,
)
from novel_forge.modules.story_planning_runtime.application import (
    _AUTHORITY_INPUT_ASSET_TYPES,
    _validate_frozen_arc_references,
    _validate_narrative_search_horizon,
    StoryPlanningGenerationApplication,
)
from novel_forge.modules.story_planning_runtime import (
    application as planning_application,
    execution as planning_execution,
)


HASH = "sha256:" + "a" * 64


def _routing_lineage_runtime(rows):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, _query, parameters):
            self.operation_id = parameters[0]

        def fetchone(self):
            return rows.get(self.operation_id)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    return SimpleNamespace(connection=lambda: Connection())


def _routing_lineage_row(predecessor, repair_number, **payload):
    command = {
        "project_id": "project-1",
        "book_id": "book-1",
        "generator_operation_name": "world.design.generate",
        "logical_key": "world:1",
        "repair_of_operation_id": predecessor,
        "repair_number": repair_number,
        **payload,
    }
    return (
        "project-1",
        "book-1",
        "story_planning.generate",
        command,
        predecessor or None,
    )


def test_planning_repair_routing_lineage_is_rooted_in_durable_operations(monkeypatch):
    rows = {
        "repair-2": _routing_lineage_row("repair-1", 2),
        "repair-1": _routing_lineage_row("root", 1),
        "root": _routing_lineage_row("", 0),
    }
    monkeypatch.setattr(
        "novel_forge.modules.story_planning_runtime.execution.get_database_runtime",
        lambda _database_url: _routing_lineage_runtime(rows),
    )
    assert _planning_repair_routing_lineage(
        "postgresql://unused",
        project_id="project-1",
        book_id="book-1",
        generator_operation_name="world.design.generate",
        operation_id="repair-2",
        repair_of_operation_id="repair-1",
    ) == ("root", "repair-1", "repair-2")


@pytest.mark.parametrize("legacy_causation", [False, True])
def test_candidate_repair_routing_lineage_uses_immutable_generation_source(monkeypatch, legacy_causation):
    content = {
        "project_id": "project-1", "book_id": "book-1", "logical_key": "world:1",
        "generator_operation_name": "world.design.generate",
        "execution_evidence": {"operation_id": "root"},
    }
    digest = canonical_hash(content)
    successor = _routing_lineage_row("", 1, repair_of_candidate_id="candidate:root")
    rows = {
        "repair": (*successor[:4], None if legacy_causation else "root"),
        "root": _routing_lineage_row("", 0),
        "candidate:root": ("root", digest, digest, content),
    }
    monkeypatch.setattr(planning_execution, "get_database_runtime", lambda _: _routing_lineage_runtime(rows))
    assert _planning_repair_routing_lineage(
        "unused", project_id="project-1", book_id="book-1",
        generator_operation_name="world.design.generate", operation_id="repair",
        repair_of_operation_id="", repair_of_candidate_id="candidate:root",
    ) == ("root", "repair")


@pytest.mark.parametrize("defect", ["content_hash", "source_operation", "book_scope"])
def test_candidate_repair_routing_lineage_rejects_unbound_candidate(monkeypatch, defect):
    content = {
        "project_id": "project-1", "book_id": "foreign" if defect == "book_scope" else "book-1",
        "logical_key": "world:1", "generator_operation_name": "world.design.generate",
        "execution_evidence": {"operation_id": "other" if defect == "source_operation" else "root"},
    }
    digest = canonical_hash(content)
    rows = {
        "repair": _routing_lineage_row("", 1, repair_of_candidate_id="candidate:root"),
        "candidate:root": ("root", HASH if defect == "content_hash" else digest, digest, content),
        "root": _routing_lineage_row("", 0),
    }
    monkeypatch.setattr(planning_execution, "get_database_runtime", lambda _: _routing_lineage_runtime(rows))
    with pytest.raises(KernelError, match="PLANNING_ROUTING_LINEAGE_INVALID"):
        _planning_repair_routing_lineage(
            "unused", project_id="project-1", book_id="book-1",
            generator_operation_name="world.design.generate", operation_id="repair",
            repair_of_operation_id="", repair_of_candidate_id="candidate:root",
        )


@pytest.mark.parametrize(
    "replacement",
    [
        {"book_id": "book-other"},
        {"generator_operation_name": "character.cast.generate"},
        {"logical_key": "world:other"},
    ],
)
def test_planning_repair_routing_lineage_rejects_scope_drift(monkeypatch, replacement):
    rows = {
        "repair": _routing_lineage_row("root", 1),
        "root": _routing_lineage_row("", 0, **replacement),
    }
    monkeypatch.setattr(
        "novel_forge.modules.story_planning_runtime.execution.get_database_runtime",
        lambda _database_url: _routing_lineage_runtime(rows),
    )
    with pytest.raises(KernelError, match="PLANNING_ROUTING_LINEAGE_INVALID"):
        _planning_repair_routing_lineage(
            "postgresql://unused",
            project_id="project-1",
            book_id="book-1",
            generator_operation_name="world.design.generate",
            operation_id="repair",
            repair_of_operation_id="root",
        )


def test_planning_repair_routing_lineage_rejects_cycle(monkeypatch):
    rows = {
        "repair": _routing_lineage_row("root", 2),
        "root": _routing_lineage_row("repair", 1),
    }
    monkeypatch.setattr(
        "novel_forge.modules.story_planning_runtime.execution.get_database_runtime",
        lambda _database_url: _routing_lineage_runtime(rows),
    )
    with pytest.raises(KernelError, match="PLANNING_ROUTING_LINEAGE_CYCLE"):
        _planning_repair_routing_lineage(
            "postgresql://unused",
            project_id="project-1",
            book_id="book-1",
            generator_operation_name="world.design.generate",
            operation_id="repair",
            repair_of_operation_id="root",
        )


def test_planning_repair_routing_lineage_has_a_bounded_depth(monkeypatch):
    rows = {
        f"repair-{number}": _routing_lineage_row(
            f"repair-{number - 1}" if number else "", number
        )
        for number in range(9)
    }
    monkeypatch.setattr(
        "novel_forge.modules.story_planning_runtime.execution.get_database_runtime",
        lambda _database_url: _routing_lineage_runtime(rows),
    )
    with pytest.raises(KernelError, match="PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED"):
        _planning_repair_routing_lineage(
            "postgresql://unused",
            project_id="project-1",
            book_id="book-1",
            generator_operation_name="world.design.generate",
            operation_id="repair-8",
            repair_of_operation_id="repair-7",
        )


@pytest.mark.parametrize("removed", ["chapter_contract_schema_version", "narrative_architecture_version"])
def test_current_chapter_activation_cannot_use_import_compatibility_to_downgrade(removed: str) -> None:
    content = planning_fixture_response(
        "chapter_plan.generate",
        {"planning_command": {"logical_key": "chapter:1", "parent_version_id": "chapter-group:v1"}},
    )
    content.pop(removed)
    with pytest.raises(KernelError, match="CHAPTER_CONTRACT_VERSION_REQUIRED"):
        validate_planning_contract(
            project_id="project-1", book_id="book-1",
            contract_type=PlanContractType.CHAPTER, asset_version_id="chapter:new",
            parent_version_id="chapter-group:v1", execution_scope=PlanExecutionScope.PLANNED,
            content=content, allow_pre_hierarchy_compatibility=True,
            require_current_chapter_contract=True,
        )


def _realization_slice(
    *, chapter_number: int = 1, parent_version_id: str = "chapter-group:v1"
) -> dict[str, object]:
    event_id = f"realization:event:{chapter_number}"
    arc_id = "arc:v1"
    event = {
        "event_id": event_id,
        "slice_id": f"realization:slice:{chapter_number}",
        "chapter_number": chapter_number,
        "causes": [],
        "actor_ref": "character:protagonist",
        "motivation": "protect the last viable promise",
        "preconditions": ["the accepted boundary leaves one costly choice"],
        "knowledge_boundary": {
            "actor_knows": ["fact:pressure"],
            "reader_may_learn": ["fact:cost"],
            "forbidden_disclosures": ["fact:future"],
        },
        "action": "make the witnessed choice",
        "decision": "accept the immediate cost",
        "resistance": "the antagonist closes the safe alternative",
        "consequence": "the alliance becomes publicly conditional",
        "state_deltas": [
            {
                "state_kind": "relationship_state",
                "entity_id": "relationship:alliance",
                "from_state": "private",
                "to_state": "publicly conditional",
            }
        ],
        "disclosures": ["fact:cost"],
        "obligation_actions": ["promise:alliance:ADVANCE"],
        "arc_contributions": [arc_id],
        "irreversible_change": "the choice is witnessed",
        "next_event_ids": [],
        "required": True,
    }
    return {
        "realization_id": "narrative-realization:test",
        "contract_digest": HASH,
        "chapter_group_plan_version_id": parent_version_id,
        "chapter_group_content_hash": HASH,
        "slice_id": f"realization:slice:{chapter_number}",
        "chapter_number": chapter_number,
        "event_ids": [event_id],
        "events": [event],
        "foundation_set_digest": HASH,
        "accepted_through_chapter": chapter_number - 1,
        "arc_working_set_digest": HASH,
        "proof_asset_version_id": "realization-proof:v1",
        "proof_hash": HASH,
    }


def _chapter_schedule_row(*, chapter_number: int = 1) -> dict[str, object]:
    return {
        "chapter_number": chapter_number,
        "primary_function": "force a witnessed choice",
        "secondary_functions": ["escalate institutional pressure", "advance trust"],
        "required_state_delta": {
            "summary": "the protagonist loses anonymity after choosing publicly"
        },
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc:v1", "contribution": "advance"}
        ],
        "promise_action": "advance the promise of accountable agency",
        "foreshadow_action": "plant the institution's visible response",
        "reward_action": "deliver one costly discovery",
        "ending_hook": "the antagonist answers the public choice",
        "prohibited_outcomes": ["silent reset", "off-page resolution"],
        "narrative_density": "HIGH",
        "reader_experience": {
            "target_emotion": "costly resolve",
            "reward_mode": "DISCOVERY",
        },
        "arc_cadence": [{"arc_plan_version_id": "arc:v1", "action": "ADVANCE"}],
        "obligation_actions": [
            {
                "obligation_id": "promise:choice",
                "action": "ADVANCE",
                "due_chapter": chapter_number + 2,
            }
        ],
    }


def test_repetition_debt_ignores_unselected_search_branches() -> None:
    assert _recent_activated_repetition_keys(
        (
            {
                "repetition_key": "unselected-branch",
                "plan_binding_id": "",
                "plan_freshness": "",
            },
            {
                "repetition_key": "stale-plan",
                "plan_binding_id": "binding:stale",
                "plan_freshness": "STALE",
            },
            {
                "repetition_key": "selected-plan",
                "plan_binding_id": "binding:current",
                "plan_freshness": "CURRENT",
            },
        )
    ) == ("selected-plan",)


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

    inputs = deepcopy(inputs)
    planning_command = dict(inputs.get("planning_command") or {})
    if stage == "chapter_plan.generate" and not planning_command.get(
        "narrative_realization"
    ):
        logical_key = str(planning_command.get("logical_key") or "chapter:1")
        suffix = logical_key.rsplit(":", 1)[-1]
        chapter_number = int(suffix) if suffix.isdigit() else 1
        planning_command["narrative_realization"] = _realization_slice(
            chapter_number=chapter_number,
            parent_version_id=str(
                planning_command.get("parent_version_id") or "chapter-group:v1"
            ),
        )
        inputs["planning_command"] = planning_command
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
        narrative_realization=(
            _realization_slice(parent_version_id="parent:v1")
            if contract_type is PlanContractType.CHAPTER
            else None
        ),
        chapter_schedule_row=(
            _chapter_schedule_row()
            if contract_type is PlanContractType.CHAPTER
            else None
        ),
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
    character = schema["properties"]["character_realization"]["items"]["properties"]
    assert world["invariant_refs"]["items"]["properties"]["domain_type"] == {
        "type": "string",
        "const": "WORLD_INVARIANT",
    }
    assert (
        "world_invariant"
        not in world["invariant_refs"]["items"]["properties"]["authority_role"]["enum"]
    )
    assert (
        "book_design"
        not in character["state_ref"]["properties"]["authority_role"]["enum"]
    )
    if contract_type not in {PlanContractType.BOOK, PlanContractType.ARC}:
        assert schema["properties"]["parent_version_id"]["const"] == "parent:v1"
    if contract_type is PlanContractType.ARC:
        assert "parent_version_id" not in schema["properties"]
        assert schema["properties"]["thread_id"]["minLength"] == 1
        assert schema["properties"]["arc_segments"]["minItems"] == 1
        assert schema["properties"]["arc_relations"]["maxItems"] == 0
    if contract_type in {PlanContractType.VOLUME, PlanContractType.CHAPTER_GROUP}:
        assert schema["properties"]["chapter_range"]["minItems"] == 2
        assert schema["properties"]["chapter_range"]["maxItems"] == 2
    if contract_type is PlanContractType.CHAPTER:
        realization_schema = schema["properties"]["narrative_realization_slice"]
        assert realization_schema["type"] == "object"
        assert realization_schema["additionalProperties"] is False
        assert (
            realization_schema["properties"]["events"]["items"]["properties"][
                "chapter_number"
            ]["const"]
            == 1
        )
        assert realization_schema["properties"]["event_ids"]["minItems"] == 1
        assert realization_schema["properties"]["event_ids"]["maxItems"] == 1

        def assert_no_non_scalar_const(value: object) -> None:
            if isinstance(value, dict):
                if "const" in value:
                    assert not isinstance(value["const"], (dict, list))
                for child in value.values():
                    assert_no_non_scalar_const(child)
            elif isinstance(value, list):
                for child in value:
                    assert_no_non_scalar_const(child)

        assert_no_non_scalar_const(realization_schema)
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


def test_realization_reference_contract_exposes_exact_frozen_authority_choices() -> (
    None
):
    contract = _realization_reference_contract(
        project_id="project-1",
        book_id="book-1",
        frozen_by_operation_id="operation:planning",
        inputs=(
            FrozenPlanningInput("world_bible", "world:v1", HASH, "world_bible"),
            FrozenPlanningInput("character_cast", "cast:v1", HASH, "character_cast"),
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
    group = planning_provider_output_schema(
        PlanContractType.CHAPTER_GROUP,
        parent_version_id="volume:v1",
        arc_plan_version_id="arc:v1",
    )
    chapter = planning_provider_output_schema(
        PlanContractType.CHAPTER,
        parent_version_id="group:v1",
        arc_plan_version_id="arc:v1",
        narrative_realization=_realization_slice(parent_version_id="group:v1"),
        chapter_schedule_row=_chapter_schedule_row(),
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
        "primary_arc_ids",
        "secondary_arc_ids",
        "required_arc_contributions",
        "arc_checkpoint_expectations",
    ):
        assert field in group["required"]
    assert group["properties"]["primary_arc_ids"]["items"]["const"] == "arc:v1"
    assert group["properties"]["secondary_arc_ids"]["maxItems"] == 1
    assert (
        group["properties"]["required_arc_contributions"]["items"]["const"] == "arc:v1"
    )
    assert (
        group["properties"]["arc_checkpoint_expectations"]["items"]["properties"][
            "arc_plan_version_id"
        ]["const"]
        == "arc:v1"
    )
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


def test_chapter_provider_schema_freezes_active_schedule_row() -> None:
    schedule = _chapter_schedule_row()
    schema = planning_provider_output_schema(
        PlanContractType.CHAPTER,
        parent_version_id="group:v1",
        arc_plan_version_id="arc:v1",
        narrative_realization=_realization_slice(parent_version_id="group:v1"),
        chapter_schedule_row=schedule,
    )
    properties = schema["properties"]

    assert properties["primary_function"]["const"] == schedule["primary_function"]
    assert properties["secondary_functions"]["minItems"] == 2
    assert properties["secondary_functions"]["maxItems"] == 2
    assert (
        properties["secondary_functions"]["items"]["enum"]
        == (schedule["secondary_functions"])
    )
    assert (
        properties["required_state_delta"]["properties"]["summary"]["const"]
        == schedule["required_state_delta"]["summary"]
    )
    assert properties["promise_action"]["const"] == schedule["promise_action"]
    assert properties["narrative_density"]["const"] == "HIGH"
    reader = properties["reader_experience"]["properties"]
    assert reader["target_emotion"]["const"] == "costly resolve"
    assert reader["reward_mode"]["const"] == "DISCOVERY"
    assert "const" not in reader["entry_question"]
    assert "const" not in reader["exit_question"]


def test_chapter_schedule_binding_rejects_reworded_scheduling() -> None:
    schedule = _chapter_schedule_row()
    content = planning_fixture_response(
        "chapter_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter:1",
                "parent_version_id": "group:v1",
                "input_versions": {"arc_plans": "arc:v1"},
            }
        },
    )
    for field in (
        "primary_function",
        "secondary_functions",
        "required_state_delta",
        "promise_action",
        "foreshadow_action",
        "reward_action",
        "ending_hook",
        "prohibited_outcomes",
        "narrative_density",
    ):
        content[field] = deepcopy(schedule[field])
    content["reader_experience"].update(schedule["reader_experience"])

    planning_application._validate_chapter_schedule_binding(content, schedule)
    content["promise_action"] = "a plausible paraphrase that changes the schedule"

    with pytest.raises(KernelError, match="CHAPTER_SCHEDULE_BINDING_DRIFT"):
        planning_application._validate_chapter_schedule_binding(content, schedule)


def test_chapter_group_search_schema_freezes_exact_horizon() -> None:
    schema = planning_provider_output_schema(
        PlanContractType.CHAPTER_GROUP,
        parent_version_id="volume:v1",
        arc_plan_version_id="arc:v1",
        narrative_search=True,
        narrative_search_horizon={
            "level": "CHAPTER_GROUP",
            "starts_at_chapter": 5,
            "ends_at_chapter": 8,
            "chapter_range": [5, 8],
        },
    )

    chapter_range = schema["properties"]["chapter_range"]
    assert "const" not in chapter_range
    assert chapter_range["minItems"] == chapter_range["maxItems"] == 2
    assert chapter_range["items"]["enum"] == [5, 8]

    def assert_no_non_scalar_const(value: object) -> None:
        if isinstance(value, dict):
            if "const" in value:
                assert not isinstance(value["const"], (dict, list))
            for child in value.values():
                assert_no_non_scalar_const(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_non_scalar_const(child)

    assert_no_non_scalar_const(schema)
    matrix = schema["properties"]["chapter_function_matrix"]
    assert matrix["minItems"] == matrix["maxItems"] == 4
    assert matrix["items"]["properties"]["chapter_number"]["enum"] == [
        5,
        6,
        7,
        8,
    ]
    events = schema["properties"]["narrative_event_chain"]
    assert events["minItems"] == 4
    assert events["items"]["properties"]["chapter_number"]["enum"] == [
        5,
        6,
        7,
        8,
    ]


def test_chapter_realization_schema_merges_repeated_object_scalar_vocabulary() -> None:
    realization = _realization_slice()
    realization["events"][0]["state_deltas"].append(
        {
            "state_kind": "character_state",
            "entity_id": "character:protagonist",
            "from_state": "hesitant",
            "to_state": "committed",
        }
    )

    schema = planning_provider_output_schema(
        PlanContractType.CHAPTER,
        parent_version_id="group:v1",
        arc_plan_version_id="arc:v1",
        narrative_realization=realization,
        chapter_schedule_row=_chapter_schedule_row(),
    )

    state_delta = schema["properties"]["narrative_realization_slice"]["properties"][
        "events"
    ]["items"]["properties"]["state_deltas"]
    assert state_delta["minItems"] == state_delta["maxItems"] == 2
    assert state_delta["items"]["properties"]["state_kind"]["enum"] == [
        "relationship_state",
        "character_state",
    ]


def test_arc_provider_allows_relations_only_with_distinct_frozen_arc_refs() -> None:
    schema = planning_provider_output_schema(
        PlanContractType.ARC,
        logical_key="arc:primary",
        related_arc_plan_version_ids=("arc:related:v1",),
    )
    relations = schema["properties"]["arc_relations"]

    assert "maxItems" not in relations
    refs = relations["items"]["properties"]
    assert refs["source_arc_ref"]["enum"] == ["arc:primary", "arc:related:v1"]
    assert refs["target_arc_ref"]["enum"] == ["arc:primary", "arc:related:v1"]


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


def test_narrative_load_counts_world_concepts_not_revealed_facts() -> None:
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
    content["scene_plan"] = [
        {
            **content["scene_plan"][0],
            "information_gain": [f"fact:reveal:{index}" for index in range(12)],
        }
    ]

    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.CHAPTER,
        asset_version_id="chapter:fact-rich",
        parent_version_id="chapter-group:v1",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )
    assert contract.logical_key == "chapter:2"

    content["world_deltas"] = [
        {"subject": f"world-concept:{index}", "change": "introduced"}
        for index in range(5)
    ]
    with pytest.raises(KernelError, match="NARRATIVE_LOAD_BUDGET_EXCEEDED"):
        validate_planning_contract(
            project_id="project-1",
            book_id="book-1",
            contract_type=PlanContractType.CHAPTER,
            asset_version_id="chapter:world-load-exceeded",
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
        narrative_realization=_realization_slice(parent_version_id="group:v1"),
        chapter_schedule_row=_chapter_schedule_row(),
    )

    assert schema["properties"]["arc_schedule"]["maxItems"] == 3
    assert schema["properties"]["arc_schedule"]["items"]["properties"][
        "arc_plan_version_id"
    ]["enum"] == ["arc:v1", "arc:v2", "arc:v3"]
    assert schema["properties"]["required_arc_contributions"]["maxItems"] == 3
    assert schema["properties"]["scene_plan"]["items"]["properties"]["arc_progress"][
        "items"
    ]["enum"] == ["arc:v1", "arc:v2", "arc:v3"]


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


def test_scene_contract_advances_declared_character_knowledge_between_scenes() -> None:
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
    gained_fact = "fact:hidden-cost"
    content["knowledge_boundaries"].append(
        {
            "layer": "CHARACTER_KNOWLEDGE",
            "subject_id": "protagonist",
            "fact_id": gained_fact,
            "status": "KNOWN",
            "available_from_chapter": content["chapter_number"],
        }
    )
    first_scene = content["scene_plan"][0]
    second_scene = deepcopy(first_scene)
    second_scene.update(
        {
            "scene_id": "chapter:2:scene:2",
            "entry_state": first_scene["exit_state"],
            "exit_state": "the witnessed cost is now actionable",
            "narrative_time_relation": "ADVANCES",
            "story_time": {
                **first_scene["story_time"],
                "start_ordinal": first_scene["story_time"]["end_ordinal"] + 1,
                "end_ordinal": first_scene["story_time"]["end_ordinal"] + 2,
            },
            "accessible_knowledge": [gained_fact],
            "information_gain": [],
        }
    )
    content["scene_plan"].append(second_scene)

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


def test_book_contract_accepts_window_for_declared_story_truth() -> None:
    content = planning_fixture_response(
        "book_plan.generate",
        {"planning_command": {"logical_key": "book:main", "input_versions": {}}},
    )
    obligations = content["knowledge_disclosure_obligations"]
    obligations["story_truth_ids"] = ["truth:revision-traces"]
    obligations["obligation_windows"].append(
        {
            "obligation_id": "truth:revision-traces",
            "setup_chapter": 1,
            "payoff_not_before": 1,
            "payoff_due_by": 2,
        }
    )

    contract = validate_planning_contract(
        project_id="project-1",
        book_id="book-1",
        contract_type=PlanContractType.BOOK,
        asset_version_id="book-plan:truth-window",
        parent_version_id="",
        execution_scope=PlanExecutionScope.PLANNED,
        content=content,
    )

    assert contract.content["knowledge_disclosure_obligations"]["story_truth_ids"] == [
        "truth:revision-traces"
    ]


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


def test_future_chapter_group_search_begins_after_accepted_boundary() -> None:
    replacement = planning_fixture_response(
        "chapter_group_plan.generate",
        {
            "planning_command": {
                "logical_key": "chapter-group:1-3",
                "parent_version_id": "volume:v1",
                "input_versions": {"arc_plans": "arc:v1"},
                "narrative_search_accepted_through_chapter": 1,
            }
        },
    )

    assert replacement["chapter_range"] == [2, 4]
    assert {
        int(item["chapter_number"]) for item in replacement["narrative_event_chain"]
    } == {2, 3, 4}


def test_chapter_group_search_command_freezes_complete_request_and_exact_range() -> (
    None
):
    base = _command("chapter_group_plan.generate")
    horizon = {
        "level": "CHAPTER_GROUP",
        "starts_at_chapter": 1,
        "ends_at_chapter": 4,
        "chapter_range": [1, 4],
    }
    command = StoryPlanningGenerationCommand(
        project_id=base.project_id,
        workspace_id=base.workspace_id,
        book_id=base.book_id,
        actor_id=base.actor_id,
        generator_operation_name=base.generator_operation_name,
        logical_key=base.logical_key,
        input_versions=base.input_versions,
        idempotency_key=base.idempotency_key,
        trace_id=base.trace_id,
        correlation_id=base.correlation_id,
        narrative_search_id="search:v1",
        narrative_search_branch_key="future-1",
        narrative_search_strategy_directive="advance costly agency",
        narrative_search_planning_horizon=horizon,
        narrative_search_desired_transformation={"goal": "advance the Arc"},
        narrative_search_hard_constraints=("accepted reality is immutable",),
    )
    horizon["chapter_range"] = [1, 3]

    assert command.narrative_search_chapter_range == (1, 4)
    assert command.narrative_search_snapshot["planning_horizon"]["chapter_range"] == [
        1,
        4,
    ]
    content = planning_fixture_response(
        "chapter_group_plan.generate",
        {
            "planning_command": {
                "logical_key": command.logical_key,
                "parent_version_id": "volume:v1",
                "input_versions": {"arc_plans": "arc:v1"},
                "narrative_search_planning_horizon": dict(
                    command.narrative_search_planning_horizon or {}
                ),
            }
        },
    )
    _validate_narrative_search_horizon(command, content)

    for invalid_range in ([1, 3], [4, 1], [1, 1]):
        content["chapter_range"] = invalid_range
        with pytest.raises(
            KernelError, match="NARRATIVE_SEARCH_CHAPTER_GROUP_RANGE_MISMATCH"
        ):
            _validate_narrative_search_horizon(command, content)


def test_chapter_group_search_command_rejects_identity_without_frozen_request() -> None:
    base = _command("chapter_group_plan.generate")

    with pytest.raises(ValueError, match="complete frozen request"):
        StoryPlanningGenerationCommand(
            project_id=base.project_id,
            workspace_id=base.workspace_id,
            book_id=base.book_id,
            actor_id=base.actor_id,
            generator_operation_name=base.generator_operation_name,
            logical_key=base.logical_key,
            input_versions=base.input_versions,
            idempotency_key=base.idempotency_key,
            trace_id=base.trace_id,
            correlation_id=base.correlation_id,
            narrative_search_id="search:v1",
            narrative_search_branch_key="future-1",
            narrative_search_strategy_directive="advance costly agency",
        )


def test_volume_search_freezes_and_enforces_exact_book_portfolio_range() -> None:
    base = _command("volume_plan.generate")
    command = StoryPlanningGenerationCommand(
        project_id=base.project_id,
        workspace_id=base.workspace_id,
        book_id=base.book_id,
        actor_id=base.actor_id,
        generator_operation_name=base.generator_operation_name,
        logical_key="volume:2",
        input_versions=base.input_versions,
        parent_version_id=base.parent_version_id,
        idempotency_key=base.idempotency_key,
        trace_id=base.trace_id,
        correlation_id=base.correlation_id,
        narrative_search_id="search:volume:2",
        narrative_search_branch_key="future-1",
        narrative_search_strategy_directive="realize the frozen second volume",
        narrative_search_planning_horizon={
            "level": "VOLUME",
            "ordinal": 2,
            "chapter_range": [4, 6],
            "starts_at_chapter": 4,
            "ends_at_chapter": 6,
        },
        narrative_search_desired_transformation={"required_chapter_range": [4, 6]},
        narrative_search_hard_constraints=(
            "the Book portfolio allocation is immutable",
        ),
    )

    assert command.narrative_search_chapter_range == (4, 6)
    _validate_narrative_search_horizon(command, {"chapter_range": [4, 6]})

    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_VOLUME_RANGE_MISMATCH"):
        _validate_narrative_search_horizon(command, {"chapter_range": [4, 7]})


def test_book_search_rejects_oversized_or_drifted_opening_topology_before_activation() -> (
    None
):
    base = _command("book_plan.generate")
    topology_budget = {
        "contract_version": "book-opening-topology-budget.v2",
        "policy_contract_version": "book-opening-provider-budget.v2",
        "policy_hash": "sha256:" + "b" * 64,
        "arc_count": 2,
        "calls_per_search": 6,
        "reserved_search_count": 1,
        "provider_call_capacity": 48,
        "reserved_provider_calls": 6,
        "max_volume_count": 4,
    }
    command = StoryPlanningGenerationCommand(
        project_id=base.project_id,
        workspace_id=base.workspace_id,
        book_id=base.book_id,
        actor_id=base.actor_id,
        generator_operation_name=base.generator_operation_name,
        logical_key="book:main",
        input_versions=base.input_versions,
        idempotency_key=base.idempotency_key,
        trace_id=base.trace_id,
        correlation_id=base.correlation_id,
        narrative_search_id="search:book",
        narrative_search_branch_key="future-1",
        narrative_search_strategy_directive="establish sustainable architecture",
        narrative_search_planning_horizon={
            "level": "BOOK",
            "target_chapters": 12,
            "opening_topology_budget": topology_budget,
        },
        narrative_search_desired_transformation={
            "required_target_chapters": 12,
        },
        narrative_search_hard_constraints=("the Opening topology budget is immutable",),
    )
    candidate = planning_fixture_response(
        "book_plan.generate",
        {
            "planning_command": {
                "logical_key": "book:main",
                "narrative_search_planning_horizon": {
                    "level": "BOOK",
                    "target_chapters": 12,
                },
            }
        },
    )
    candidate["volume_skeleton"] = [
        {"volume": ordinal, "goal": f"volume {ordinal}"} for ordinal in range(1, 5)
    ]
    _validate_narrative_search_horizon(command, candidate)

    oversized = deepcopy(candidate)
    oversized["volume_skeleton"].append({"volume": 5, "goal": "poisoned outer"})
    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_BOOK_TOPOLOGY_EXCEEDED"):
        _validate_narrative_search_horizon(command, oversized)
    repaired = replace(
        command,
        idempotency_key=f"{command.idempotency_key}:repair:1",
        repair_of_candidate_id="candidate:oversized",
        repair_reason="NARRATIVE_SEARCH_BOOK_TOPOLOGY_EXCEEDED:report",
        repair_number=1,
    )
    assert repaired.narrative_search_planning_horizon == (
        command.narrative_search_planning_horizon
    )
    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_BOOK_TOPOLOGY_EXCEEDED"):
        _validate_narrative_search_horizon(repaired, oversized)

    drifted = replace(
        base,
        logical_key="book:main",
        narrative_search_id="search:book:drift",
        narrative_search_branch_key="future-1",
        narrative_search_strategy_directive="drifted topology",
        narrative_search_planning_horizon={
            "level": "BOOK",
            "target_chapters": 12,
            "opening_topology_budget": {
                **topology_budget,
                "max_volume_count": 5,
            },
        },
        narrative_search_desired_transformation={"required_target_chapters": 12},
        narrative_search_hard_constraints=("immutable topology",),
    )
    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_BOOK_TOPOLOGY_DRIFT"):
        _validate_narrative_search_horizon(drifted, candidate)


def test_planning_fixture_obeys_frozen_book_target_and_volume_range() -> None:
    book = planning_fixture_response(
        "book_plan.generate",
        {
            "planning_command": {
                "logical_key": "book:main",
                "narrative_search_planning_horizon": {
                    "level": "BOOK",
                    "target_chapters": 8,
                },
            }
        },
    )
    volume = planning_fixture_response(
        "volume_plan.generate",
        {
            "planning_command": {
                "logical_key": "volume:3",
                "narrative_search_planning_horizon": {
                    "level": "VOLUME",
                    "chapter_range": [7, 8],
                },
            }
        },
    )

    assert book["length_strategy"] == {"target_chapters": 8}
    assert len(book["volume_skeleton"]) == 3
    assert volume["chapter_range"] == [7, 8]
    assert volume["narrative_segments"][0]["chapter_range"] == [7, 8]


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
        narrative_realization=(
            _realization_slice(parent_version_id="asset:chapter_group_plan:v1")
            if generator == "chapter_plan.generate"
            else None
        ),
    )


def test_world_runtime_contract_preserves_historical_frozen_commands():
    from novel_forge.modules.story_planning_runtime.application import (
        _command_payload,
        _command_from_payload,
    )

    command = _command("chapter_plan.generate")
    current = _command_payload(command)
    assert current["execution_contract_version"] == STORY_PLANNING_GENERATION_VERSION
    previous = {**current, "execution_contract_version": "1.13.0"}
    assert _command_payload(_command_from_payload(previous)) == previous
    published = {**current, "execution_contract_version": "1.12.0"}
    assert _command_payload(_command_from_payload(published)) == published
    assert _command_from_payload(current) == command
    historical = {
        key: value
        for key, value in current.items()
        if key != "execution_contract_version"
    }
    replay = _command_from_payload(historical)
    assert replay.execution_contract_version == "1.11.0"
    assert not replay.world_preparation_request
    assert _command_payload(replay) == historical


def _inputs(command: StoryPlanningGenerationCommand) -> tuple[FrozenPlanningInput, ...]:
    return tuple(
        FrozenPlanningInput(role, version, HASH, role)
        for role, version in command.input_versions.items()
    )


def test_planning_context_uses_canonical_policy_and_selection_seam() -> None:
    command = _command("book_plan.generate")
    selected_inputs = [
        {
            "role": "story_foundation",
            "asset_version_id": "foundation-v1",
            "asset_type": "story_foundation",
            "content_hash": HASH,
            "content": {
                "premise": "A governed premise",
                "soft_suggestions": ["x" * 80_000],
            },
        }
    ]
    content = {
        "schema_version": "novelos.planning_context_bundle.v1",
        "book_id": command.book_id,
        "planning_scope": command.planning_scope.value,
        "logical_key": command.logical_key,
        "input_versions": selected_inputs,
        "arc_working_set": {},
        "narrative_search": {},
        "realization_reference_contract": {},
        "narrative_qualification_profiles": [],
        "token_budget": 16_000,
    }
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(
        command=command,
        selected_inputs=selected_inputs,
        content=content,
    )

    assert manifest["contract_version"] == "planning-context-manifest-v1"
    assert manifest["provider_context_view"]["contract_version"] == (
        "provider-context-view-v2"
    )
    assert len(manifest["policy_compilation"]["input_policies"]) == 3
    assert manifest["token_accounting"]["accepted_tokens"] > 0
    assert manifest["token_accounting"]["accepted_tokens"] < 16_000
    assert manifest["token_accounting"]["precision"] == "ESTIMATE_ONLY"
    compiled = manifest["provider_context_view"]["compiled_view"]
    assert compiled["segments"][0]["content"]["premise"] == "A governed premise"
    assert manifest["projection_audit"]["loss_records"][0]["reason"] == "OPTIONAL_CONTEXT_BUDGET"
    assert compiled["selection_explanation"]["loss_receipt"]["loss_record_count"] == 1
    assert manifest["provider_context_view"]["source_input_hash"].startswith("sha256:")
    assert all(
        item["reason"] != "ACCEPTED_BOUNDARY_MISSING"
        for item in manifest["candidate_decisions"]
    )
    assert manifest["selected_inputs"][0]["logical_context_kind"].startswith(
        "planning_"
    )
    authority_input = next(
        item
        for item in manifest["selected_inputs"]
        if item["asset_version_id"] == "foundation-v1"
    )
    assert authority_input["physical_asset_type"] == "story_foundation"
    assert authority_input["provenance"][
        "authority_asset_version_id"
    ] == "foundation-v1"
    assert {item["decision"] for item in manifest["candidate_decisions"]} == {
        "SELECTED"
    }


def test_planning_context_rejects_duplicate_authority_representation() -> None:
    command = _command("book_plan.generate")
    selected_inputs = [
        {
            "role": "story_foundation",
            "asset_version_id": asset_version_id,
            "asset_type": "story_foundation",
            "content_hash": HASH,
            "content": {"premise": "same Authority source"},
        }
        for asset_version_id in ("shared-v1", "shared-v2")
    ]
    content = {
        "schema_version": "novelos.planning_context_bundle.v1",
        "book_id": command.book_id,
        "planning_scope": command.planning_scope.value,
        "logical_key": command.logical_key,
        "input_versions": selected_inputs,
        "arc_working_set": {},
        "narrative_search": {},
        "realization_reference_contract": {},
        "narrative_qualification_profiles": [],
        "token_budget": 16_000,
    }

    with pytest.raises(KernelError, match="dropped or deduplicated input"):
        PostgresPlanningExecutionPreparer._planning_context_manifest(
            command=command,
            selected_inputs=selected_inputs,
            content=content,
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
            narrative_realization=command.narrative_realization,
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


def test_chapter_plan_rejects_caller_shaped_realization_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _realization_slice(parent_version_id="asset:chapter_group_plan:v1")

    class FakeUow:
        cursor = object()

        def __init__(self, _database_url: str) -> None:
            pass

        def __enter__(self) -> "FakeUow":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class FakeRepository:
        def __init__(self, _cursor: object) -> None:
            pass

        def require_current_for_chapter(self, **_values: object) -> dict[str, object]:
            return current

    monkeypatch.setattr(planning_application, "AuthorityUnitOfWork", FakeUow)
    monkeypatch.setattr(
        planning_application, "NarrativeRealizationRepository", FakeRepository
    )
    application = object.__new__(StoryPlanningGenerationApplication)
    application.database_url = "postgresql://unused"
    command = _command("chapter_plan.generate")

    assert application._require_frozen_realization_slice(command) == current

    forged = dict(current)
    forged["events"] = [{**current["events"][0], "action": "forged action"}]
    forged_command = StoryPlanningGenerationCommand(
        project_id=command.project_id,
        workspace_id=command.workspace_id,
        book_id=command.book_id,
        actor_id=command.actor_id,
        generator_operation_name=command.generator_operation_name,
        logical_key=command.logical_key,
        input_versions=command.input_versions,
        idempotency_key="generate:forged-realization",
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
        narrative_realization=forged,
    )
    with pytest.raises(KernelError, match="NARRATIVE_REALIZATION_SLICE_DRIFT"):
        application._require_frozen_realization_slice(forged_command)


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
        binding = SimpleNamespace(
            operation_id="operation-1",
            attempt_id="attempt-1",
            fencing_token=7,
            project_id="project-1",
            book_id="book-1",
            execution_capability_id=definition.capability,
            capability_pack_attempt_snapshot_id=HASH,
            capability_pack_attempt_snapshot_hash=HASH,
            commit_authority=self.commit_authority,
            input_manifest_ref="input-1",
            binding_id="binding-1",
            binding_hash=HASH,
        )
        return PlanningExecutionBundle(snapshot, binding, _ExecutionPort())


def test_planning_binder_requires_pack_capability_and_pep_on_one_attempt() -> None:
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


def test_planning_capability_cannot_claim_chapter_commit_authority() -> None:
    command = _command("chapter_plan.generate")
    with pytest.raises(KernelError, match="Planning Capability can only submit"):
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


def test_planning_role_aliases_share_one_exact_kernel_admission_reference():
    from novel_forge.modules.story_planning_runtime.application import _canonical_admission_assets
    source = {"asset_version_id": "group-plan:v1", "content_hash": "sha256:group"}
    refs = [source, {"asset_version_id": "state:v2", "content_hash": "sha256:state"}, dict(source)]
    assert _canonical_admission_assets(refs) == refs[:2]
    assert len(refs) == 3
    with pytest.raises(KernelError, match="must agree on its exact content identity"):
        _canonical_admission_assets([source, {**source, "content_hash": "sha256:other"}])


@pytest.mark.parametrize('snapshot_fence, binding_fence, allowed', [(4, 7, True), (8, 7, False), (4, 6, False)])
def test_planning_takeover_preserves_snapshot_provenance_but_requires_current_binding(snapshot_fence, binding_fence, allowed):
    class Resolver(_Resolver):
        def resolve(self, **kwargs):
            bundle = super().resolve(**kwargs)
            bundle.attempt_snapshot.execution_fencing_token = snapshot_fence
            bundle.capability_binding.fencing_token = binding_fence
            return bundle
    command = _command('book_plan.generate')
    def execute():
        return CapabilityPackBackedPlanningExecutionBinder(Resolver()).execute(operation_id='operation-1', attempt_id='attempt-1', fencing_token=7, worker_id='planning-worker', command=command, inputs=_inputs(command), definition=GENERATOR_CATALOG[command.generator_operation_name])
    if allowed:
        assert execute().evidence.fencing_token == 7
    else:
        with pytest.raises(KernelError, match='PLANNING_EXECUTION_ATTEMPT_DRIFT'):
            execute()


def test_raw_result_contract_requires_all_repaired_fields_and_keeps_original():
    import json
    from tests.integration.synthesis_production_support import SynthesisTransport
    from novel_forge.modules.story_planning_runtime.result_recovery import validate_raw_result

    raw = SynthesisTransport().planning("world.design.generate", {})
    world = json.loads(raw["world_foundation_json"])
    world["compiled_scope"] = ["BOOK", "VOLUME", "ARC"]
    world["genre_profile"] = {"label": "guofeng"}
    raw["world_foundation_json"] = json.dumps(world)
    original = deepcopy(raw)
    with pytest.raises(KernelError) as failed:
        validate_raw_result("world.design.generate", raw, compiled_scope="BOOK")
    assert {item["field_path"] for item in failed.value.diagnostics} == {"$.compiled_scope", "$.genre_profile"}
    world["compiled_scope"] = "BOOK"
    incomplete = {**raw, "world_foundation_json": json.dumps(world)}
    with pytest.raises(KernelError, match="genre_profile"):
        validate_raw_result("world.design.generate", incomplete, compiled_scope="BOOK")
    assert raw == original


@pytest.mark.parametrize("raw", [None, [], 42, "invalid", {"objective": []}])
def test_raw_result_boundary_rejects_types_without_coercion(raw):
    from novel_forge.modules.story_planning_runtime.result_recovery import validate_raw_result
    with pytest.raises(KernelError, match="expected"):
        validate_raw_result("world.design.generate", raw, compiled_scope="BOOK")


def test_result_repair_command_keeps_historical_identity_and_bounded_new_causation(monkeypatch):
    from novel_forge.modules.story_planning_runtime import result_recovery
    from novel_forge.modules.story_planning_runtime.application import _command_from_payload, _command_payload

    original = replace(_command("world.design.generate"), execution_contract_version="1.14.0")
    historical = _command_payload(original)
    assert "repair_of_operation_id" not in historical
    diagnostic = {"error_code": "WORLD_FOUNDATION_SCHEMA_INVALID", "fields": [{"field_path": "$.compiled_scope"}]}
    source = {"asset_version_id": "result:failed", "diagnostic": diagnostic}
    monkeypatch.setattr(result_recovery, "require_result_repair_source", lambda *args, **kwargs: source)
    application = object.__new__(StoryPlanningGenerationApplication)
    application.database_url = "isolated-test"
    calls = []
    application.generate = lambda command, **kwargs: calls.append(command) or command
    recovered = application._repair_unmaterialized_result(original, operation_id="failed:operation", principal=object())
    assert recovered.repair_of_operation_id == "failed:operation"
    assert recovered.repair_of_candidate_id == ""
    assert recovered.repair_number == 1
    assert recovered.execution_contract_version == STORY_PLANNING_GENERATION_VERSION
    assert _command_payload(original) == historical
    assert _command_from_payload(_command_payload(recovered)) == recovered
    with pytest.raises(KernelError, match="PLANNING_RESULT_REPAIR_BOUND_EXCEEDED"):
        application._repair_unmaterialized_result(recovered, operation_id="failed:again", principal=object())
    assert len(calls) == 1


def test_result_repair_cannot_mix_candidate_and_raw_result_causation():
    with pytest.raises(ValueError, match="without a source Candidate"):
        replace(_command("world.design.generate"), repair_of_operation_id="failed:operation", repair_of_candidate_id="candidate:other", repair_result_asset_version_id="result:failed", repair_result_diagnostic={"error_code": "bad"}, repair_reason="bad:hash", repair_number=1)


def _planning_profile_binding(preparer, *, schema_ref, generator="creative.candidates.generate", project_id="project-1", book_id="book-1", operation_id="profile-operation", attempt_id="profile-attempt", release_sha="a" * 40):
    from novel_forge.modules.production_execution import ExecutionRuntimeClass, FallbackPolicy, default_capability_registry
    from novel_forge.modules.story_planning_runtime.execution import PlanningExecutionRoute
    from tests.unit.test_production_execution_gateway import contracts

    _, profile, policy, _, _, _ = contracts(backend_id="codex-profile-test", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    route = PlanningExecutionRoute(model_profile=profile, route_policy=policy, fallback_policy=FallbackPolicy.fail_closed(policy.fallback_policy_ref, 1), backend_version="1", runtime_host_id="host:test", auth_profile_ref="auth:test", release_sha=release_sha)
    command = replace(_command(generator), project_id=project_id, book_id=book_id)
    definition = GENERATOR_CATALOG[generator]
    return preparer._execution_binding(
        operation_id=operation_id, attempt_id=attempt_id, fencing_token=1,
        command=command, definition=definition,
        capability=default_capability_registry().resolve(definition.capability),
        planning_route=route,
        context_document=SimpleNamespace(asset_version_id="context:test", content_hash=HASH),
        input_documents=(), effect_id="effect:test", stable_key="effect-key:test", reservation_id="reservation:test",
        output_schema_ref=schema_ref, frozen=SimpleNamespace(prompt_bundle_ref="prompt:test", skill_bundle_ref="skill:test"),
        stage_name=generator, stage_identity="planning",
    )


@pytest.mark.parametrize("generator", ["creative.candidates.generate", "world.design.generate", "character.cast.generate", "book_plan.generate"])
def test_planning_model_profile_distinguishes_contracts_and_reuses_exact_legacy(generator):
    from novel_forge.modules.production_execution import ModelProfile, RoutePolicy
    preparer = object.__new__(PostgresPlanningExecutionPreparer)
    documents = {}
    preparer._operation_graph = lambda operation_id, project_id: {"root_operation_id": operation_id, "saga_id": "saga:test", "definition_name": "story_planning.generate"}
    def require(**arguments):
        key = (arguments["project_id"], arguments["logical_ref"])
        if key not in documents:
            raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "missing")
        return documents[key]
    def ensure(**arguments):
        key = (arguments["project_id"], arguments["logical_ref"])
        contract = arguments["contract"]
        if key in documents:
            assert documents[key].content["contract"] == contract
        else:
            documents[key] = SimpleNamespace(asset_type=arguments["asset_type"], content={"contract": deepcopy(contract)}, content_hash=canonical_hash(contract))
        return documents[key]
    preparer.query = SimpleNamespace(require=require)
    preparer._ensure_contract = ensure
    first, _ = _planning_profile_binding(preparer, schema_ref="schema:author-guided:v1", generator=generator)
    original = deepcopy({key: value.content for key, value in documents.items()})
    second, _ = _planning_profile_binding(preparer, schema_ref="schema:plain:v1", generator=generator, book_id="book-2", operation_id="profile-operation-2", attempt_id="attempt-2")
    assert ".sha256." in first.route_snapshot.model_profile_id
    assert ".sha256." in second.route_snapshot.model_profile_id
    assert first.route_snapshot.model_profile_id != second.route_snapshot.model_profile_id
    assert first.route_snapshot.policy_id != second.route_snapshot.policy_id
    assert first.route_snapshot.fallback_policy_ref != second.route_snapshot.fallback_policy_ref
    for key, content in original.items():
        assert documents[key].content == content
    for binding in (first, second):
        route = binding.route_snapshot
        profile = documents[("project-1", f"production_execution/model_profiles/{route.model_profile_id}/v1")].content["contract"]
        policy = documents[("project-1", f"production_execution/route_policies/{route.policy_id}/v1")].content["contract"]
        assert route.model_profile_hash == ModelProfile.from_dict(profile).contract_hash
        assert route.route_policy_hash == RoutePolicy.from_dict(policy).contract_hash
        assert profile["output_policy_ref"] == route.output_schema_ref
        assert policy["allowed_model_profile_ids"] == [route.model_profile_id]
        assert policy["fallback_policy_ref"] == route.fallback_policy_ref
    replay, _ = _planning_profile_binding(preparer, schema_ref="schema:plain:v1", generator=generator, book_id="book-2", operation_id="profile-operation-2", attempt_id="attempt-2")
    assert replay == second
    reused, _ = _planning_profile_binding(preparer, schema_ref="schema:author-guided:v1", generator=generator, operation_id="profile-operation-3", attempt_id="attempt-3")
    assert reused.route_snapshot.model_profile_id == first.route_snapshot.model_profile_id


@pytest.mark.parametrize("invalid", [[], None, 42, {"profile_id": "wrong"}])
def test_model_profile_does_not_coerce_or_rewrite_invalid_retained_contract(invalid):
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    from tests.unit.test_production_execution_gateway import contracts
    _, profile, _, _, _, _ = contracts(backend_id="codex-profile-test", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    preparer = object.__new__(PostgresPlanningExecutionPreparer)
    document = SimpleNamespace(asset_type="model_profile", content={"contract": invalid})
    preparer.query = SimpleNamespace(require=lambda **kwargs: document)
    before = deepcopy(document.content)
    with pytest.raises(KernelError, match="EXECUTION_CONTRACT_FROZEN_CONFLICT"):
        preparer._select_model_profile("project-1", profile)
    assert document.content == before
