from __future__ import annotations

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
from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    CapabilityPackBackedPlanningExecutionBinder,
    FrozenPlanningInput,
    PlanningExecutionBundle,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    STORY_PLANNING_GENERATION_VERSION,
    StoryPlanningGenerationCommand,
    story_planning_generation_definition,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_fixture_response,
    planning_provider_output_schema,
)
from novel_forge.modules.story_planning_runtime.application import (
    _AUTHORITY_INPUT_ASSET_TYPES,
)


HASH = "sha256:" + "a" * 64


def test_real_planning_definition_versions_the_bounded_xhigh_timeout() -> None:
    definition = story_planning_generation_definition(
        application_build_id="unit-test-build",
        commit_sha="a" * 40,
    )

    assert definition["definition_version"] == STORY_PLANNING_GENERATION_VERSION
    assert definition["timeout_policy"] == {
        "operation_timeout_seconds": STORY_PLANNING_OPERATION_TIMEOUT_SECONDS
    }


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
    if contract_type is not PlanContractType.BOOK:
        assert schema["properties"]["parent_version_id"]["const"] == "parent:v1"
    if contract_type in {PlanContractType.VOLUME, PlanContractType.CHAPTER_GROUP}:
        assert schema["properties"]["chapter_range"]["minItems"] == 2
        assert schema["properties"]["chapter_range"]["maxItems"] == 2
    if contract_type is PlanContractType.CHAPTER:
        assert schema["properties"]["required_arc_contributions"]["maxItems"] == 1
        assert schema["properties"]["title"]["maxLength"] == 120
        assert schema["properties"]["premise"]["maxLength"] == 320
        assert "reader-facing" in schema["properties"]["title"]["description"]


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
