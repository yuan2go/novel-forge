from __future__ import annotations

from copy import deepcopy
import hashlib
import tempfile
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_story_planning_generation_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.input_resolver import (
    BookProductionInputResolver,
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.book_authority.production import (
    BookProductionState,
    PostgresBookAuthority,
    StartBookProductionCommand,
)
from novel_forge.modules.book_authority.supervisor import (
    PostgresBookProductionSupervisor,
)
from novel_forge.modules.book_production import (
    PostgresBookNarrativeCheckpointAuthority,
    SupervisorAction,
)
from novel_forge.modules.book_replan import (
    BookReplanCoordinator,
    CoordinateBookReplanCommand,
)
from novel_forge.modules.chapter_group_authority import PostgresChapterGroupAuthority
from novel_forge.modules.hierarchical_planning.domain import (
    COMMON_FIELDS,
    TYPE_FIELDS,
    PlanContractType,
)
from novel_forge.modules.reader_calibration import (
    JudgeMode,
    ReaderJudgeQualificationStatus,
)
from novel_forge.modules.reader_judge_authority import (
    ReaderJudgeAuthorityApplication,
    ReaderJudgeDefinition,
    ReaderJudgeResolutionScope,
    ReaderJudgeRuntimeResolver,
)
from novel_forge.modules.plan_change_authority import PostgresPlanChangeAuthority
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    CapabilityPackBackedPlanningExecutionBinder,
    FrozenPlanningInput,
    PostgresPlanningExecutionBundleResolver,
    PreparedPlanningExecution,
    PlanningExecutionEvidence,
    PlanningGenerationCandidate,
    PlanningGenerationStatus,
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
    canonical_hash,
    story_planning_generation_definition,
)
from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionEvidence,
)
from novel_forge.modules.production_execution.capability_registry import (
    PLANNING_TIMEOUT_POLICY_VERSION,
    default_capability_registry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)


RELEASE_SHA = "e" * 40


def _activate_planning_pack(harness: CapabilityPackPostgresHarness) -> str:
    definition = story_planning_generation_definition(
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        uow.cursor.execute(
            """
            SELECT definition_hash
            FROM authority_operation_definition
            WHERE name='story_planning.generate' AND definition_version='1.1.0'
            """
        )
        definition_hash = str(uow.cursor.fetchone()[0])
        uow.commit()
    capabilities = [
        "planning.book.generate",
        "planning.volume.generate",
        "planning.arc.generate",
        "planning.chapter_group.generate",
        "planning.story_chapter.generate",
    ]
    template = next(
        node
        for node in harness._base_manifest["workflow_template"]["nodes"]
        if node.get("agent_definition_ref")
    )
    nodes = []
    for generator, capability in zip(
        (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        ),
        capabilities,
        strict=True,
    ):
        node = deepcopy(template)
        node.update(
            node_id=generator,
            operation_name="story_planning.generate",
            operation_definition_ref=STORY_PLANNING_OPERATION_DEFINITION_REF,
            operation_definition_hash=definition_hash,
            handler_key="novel_forge.story_planning.generate",
            stage=generator,
            capability_id=capability,
            agent_definition_ref=f"{generator.replace('.', '-')}-agent@1",
            input_asset_types=["planning_generation_input_snapshot"],
            output_asset_types=["planning_generation_candidate"],
            depends_on=[],
            commit_authority="STORY_DESIGN_AUTHORITY",
            retry_policy={
                "max_attempts": 3,
                "retryable_errors": [],
                "dead_letter_on_exhausted": True,
            },
            timeout_policy_ref=(
                f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}"
            ),
        )
        nodes.append(node)
    manifest = harness._base_manifest
    manifest["identity"].update(
        name="Story Planning Generator Pack",
        domain="story_planning",
        description="Five governed Planning Candidate generators.",
    )
    manifest["compatibility"]["required_capabilities"] = [
        *capabilities,
        "quality.originality.judge",
    ]
    manifest["workflow_template"].update(
        workflow_id="story_planning_generators",
        workflow_version=STORY_PLANNING_WORKFLOW_DEFINITION_REF.rpartition("@")[2],
        nodes=nodes,
    )
    manifest["workflow_template"]["completion"] = {
        "required_terminal_nodes": [item["node_id"] for item in nodes],
        "required_evidence": ["trace", "audit"],
        "required_output_asset_types": ["planning_generation_candidate"],
    }
    manifest["context_sources"]["allowed_asset_types"].append(
        "planning_generation_input_snapshot"
    )
    manifest["tool_permissions"]["tools"] = [
        {
            **manifest["tool_permissions"]["tools"][0],
            "allowed_operations": [item["node_id"] for item in nodes],
        }
    ]
    manifest["evaluation"]["required_gates"] = [
        {
            "gate_id": "planning_source_isolation",
            "judge_capability_id": "quality.originality.judge",
            "blocking": True,
            "threshold": 1,
            "required_evidence": ["planning_generation_candidate"],
        }
    ]
    manifest["evaluation"]["metrics"] = []
    timeout_refs = {
        f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}"
        for capability in capabilities
    }
    harness._base_catalog["artifacts"] = [
        artifact
        for artifact in harness._base_catalog["artifacts"]
        if artifact["ref"] not in timeout_refs
    ]
    for artifact in harness._base_catalog["artifacts"]:
        if artifact["ref"] == manifest["context_sources"]["policy_id"]:
            artifact["content"]["allowed_asset_types"] = list(
                manifest["context_sources"]["allowed_asset_types"]
            )
            artifact["content_hash"] = canonical_hash(artifact["content"])
        elif artifact["ref"] == manifest["tool_permissions"]["policy_id"]:
            artifact["content"]["explicit_tool_refs"] = ["model.provider.invoke"]
            artifact["content_hash"] = canonical_hash(artifact["content"])
    for capability in capabilities:
        contract = default_capability_registry().resolve(capability)
        for schema_ref in (contract.input_schema_ref, contract.output_schema_ref):
            harness._base_catalog["artifacts"].append(
                {
                    "kind": "SCHEMA",
                    "ref": schema_ref,
                    "version": "v1",
                    "content": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "additionalProperties": True,
                    },
                }
            )
        harness._base_catalog["artifacts"].append(
            {
                "kind": "TIMEOUT_POLICY",
                "ref": f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}",
                "version": PLANNING_TIMEOUT_POLICY_VERSION,
                "content": {
                    "policy_id": f"timeout:{capability.replace('.', '-')}:{PLANNING_TIMEOUT_POLICY_VERSION}",
                    "operation_timeout_seconds": STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
                    "timeout_action": "FAIL_ATTEMPT",
                    "authority_binding": STORY_PLANNING_OPERATION_DEFINITION_REF,
                },
            }
        )
    scope = harness.approval_scope()
    scope["allowed_workflow_definition_refs"] = [STORY_PLANNING_WORKFLOW_DEFINITION_REF]
    pack = harness.register_compile_approve("1.1.0", generation=1, approval_scope=scope)
    deployment = harness.deploy(pack)
    harness.activate(deployment)
    return deployment.deployment_id


class _ExternalEffectPepFixturePlanningBinder:
    """Deterministic Candidate transport for the PostgreSQL Authority fixture."""

    production_execution_gateway_backed = True

    def execute(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: Any,
    ) -> PlanningGenerationCandidate:
        payload = _planning_contract(command)
        if ":replacement-candidate" in command.idempotency_key:
            payload["objective"] = f"{payload['objective']} after recap deviation"
        if command.logical_key.endswith(":repair-probe") and command.repair_number == 0:
            payload = {"objective": "Deliberately incomplete first candidate"}
        digest = canonical_hash(
            {
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "generator": command.generator_operation_name,
                "repair": command.repair_number,
            }
        )
        return PlanningGenerationCandidate(
            generator_operation_name=command.generator_operation_name,
            planning_scope=command.planning_scope,
            logical_key=command.logical_key,
            candidate_payload=payload,
            frozen_inputs=inputs,
            evidence=PlanningExecutionEvidence(
                operation_id=operation_id,
                attempt_id=attempt_id,
                fencing_token=fencing_token,
                route_snapshot_id=f"route:{digest}",
                input_manifest_ref=f"input:{digest}",
                output_manifest_ref=f"output:{digest}",
                validation_manifest_ref=f"validation:{digest}",
                usage_receipt_ref=f"usage:{digest}",
                cost_receipt_ref=f"cost:{digest}",
                external_receipt_ref=f"external-effect:{digest}",
                capability_pack_attempt_snapshot_id=f"pack-snapshot:{digest}",
                capability_pack_attempt_snapshot_hash=digest,
                agent_work_order_ref=f"work-order:{digest}",
                agent_work_order_hash=digest,
                agent_runtime_binding_ref=f"runtime-binding:{digest}",
                agent_runtime_binding_hash=digest,
                commit_authority="STORY_DESIGN_AUTHORITY",
                fixture_protocol_only=True,
            ),
        )


class _PlanningExternalEffectPepPort:
    """Scripted PEP port backed by the real Command Kernel ExternalEffect runtime."""

    production_execution_gateway_backed = True
    external_effect_backed = True

    def __init__(
        self,
        *,
        context: EffectCommandContext,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        effect_id: str,
        command: StoryPlanningGenerationCommand,
        adapter: FakeDeterministicProvider,
        route_snapshot_ref: str,
        input_manifest_ref: str,
    ) -> None:
        self.context = context
        self.attempt_id = attempt_id
        self.fencing_token = fencing_token
        self.worker_id = worker_id
        self.effect_id = effect_id
        self.planning_command = command
        self.adapter = adapter
        self.route_snapshot_ref = route_snapshot_ref
        self.input_manifest_ref = input_manifest_ref

    def execute(self, command: Any) -> DomainExecutionCandidate:
        dispatched = dispatch_external_effect(
            DATABASE_URL,
            self.context,
            effect_id=self.effect_id,
            worker_id=self.worker_id,
            lease_seconds=30,
            adapter=self.adapter,
        )
        assert dispatched["outcome"] == "success"
        payload = _planning_contract(self.planning_command)
        if ":replacement-candidate" in self.planning_command.idempotency_key:
            payload["objective"] = f"{payload['objective']} after recap deviation"
        return DomainExecutionCandidate(
            candidate_kind=CandidateKind.GENERATION,
            raw_output=payload,
            evidence=DomainExecutionEvidence(
                execution_id=self.effect_id,
                operation_id=self.context.operation_id,
                attempt_id=self.attempt_id,
                fencing_token=self.fencing_token,
                capability=command.capability,
                backend_id="command-kernel-external-effect:scripted-fixture",
                route_snapshot_id=self.route_snapshot_ref,
                input_manifest_ref=self.input_manifest_ref,
                output_manifest_ref=f"output-manifest:{self.effect_id}",
                validation_manifest_ref=f"validation-manifest:{self.effect_id}",
                usage_receipt_ref=f"usage-receipt:{self.effect_id}",
                cost_receipt_ref=f"cost-receipt:{self.effect_id}",
                fixture_protocol_only=True,
                real_model_call=False,
                production_verified=False,
                provider_id=self.adapter.provider,
                model_id="scripted-planning-fixture",
                provider_request_id=str(dispatched.get("provider_request_id") or ""),
                external_receipt_ref=self.effect_id,
            ),
        )


class _PlanningExternalEffectPreparer:
    def prepare(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: Any,
        attempt_snapshot: Any,
    ) -> PreparedPlanningExecution:
        frozen = attempt_snapshot.execution_snapshot
        manifest = [
            {
                "role": item.role,
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
            }
            for item in inputs
        ]
        input_manifest_hash = canonical_hash(manifest)
        input_manifest_ref = (
            f"planning-input-manifest:{input_manifest_hash.removeprefix('sha256:')}"
        )
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=worker_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        adapter = FakeDeterministicProvider("success")
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider=adapter.provider,
                capability=definition.capability,
                stable_idempotency_key=(
                    f"{operation_id}:{attempt_id}:{definition.capability}:fixture"
                ),
                request_payload={
                    "generator_operation_name": command.generator_operation_name,
                    "logical_key": command.logical_key,
                    "input_manifest_ref": input_manifest_ref,
                },
                max_attempts=1,
                reversible=False,
                request_timeout_seconds=30,
                reconciliation_mode=adapter.reconciliation_mode,
                provider_capability_profile=dict(adapter.capability_profile),
            )["external_effect_id"]
        )
        port = _PlanningExternalEffectPepPort(
            context=context,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
            effect_id=effect_id,
            command=command,
            adapter=adapter,
            route_snapshot_ref=frozen.route_policy_ref,
            input_manifest_ref=input_manifest_ref,
        )
        return PreparedPlanningExecution(
            execution_port=port,
            context_bundle_asset_version_id=inputs[0].asset_version_id,
            context_bundle_hash=inputs[0].content_hash,
            route_snapshot_ref=frozen.route_policy_ref,
            route_snapshot_hash=frozen.route_policy_hash,
            input_manifest_ref=input_manifest_ref,
            input_manifest_hash=input_manifest_hash,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            prompt_bundle_hash=frozen.prompt_bundle_hash,
            skill_bundle_ref=frozen.skill_bundle_ref,
            skill_bundle_hash=frozen.skill_bundle_hash,
            tool_permission_snapshot_ref=frozen.tool_policy_ref,
            tool_permission_snapshot_hash=frozen.tool_policy_hash,
            context_policy_ref=frozen.context_policy_ref,
            context_policy_hash=frozen.context_policy_hash,
            validation_policy_ref=frozen.evaluation_policy_ref,
            commit_policy_ref="story-design-candidate-only:v1",
            timeout_policy_ref="story-planning-timeout:v1",
        )


def _principal(project_id: str) -> Principal:
    return Principal(
        principal_id=f"planning-operator:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(
            {
                "story_planning.authority.execute",
                "story_planning.authority.approve",
                "story_planning.authority.activate",
                "story_design.authority.execute",
                "book.authority.execute",
            }
        ),
        project_scope=frozenset({project_id}),
        authentication_source="postgres-functional-loop-fixture",
    )


def _planning_contract(command: StoryPlanningGenerationCommand) -> dict[str, Any]:
    contract_type = PlanContractType(command.planning_scope.value)
    payload: dict[str, Any] = {
        "contract_id": f"contract:{command.logical_key}",
        "logical_key": command.logical_key,
        "objective": f"Governed objective for {command.logical_key}",
        "entry_state_ref": "story-state:entry",
        "exit_state_spec": {"progress": "advanced"},
        "hard_constraints": [],
        "soft_constraints": [],
        "required_events": [],
        "forbidden_events": [],
        "required_payoffs": [],
        "forbidden_payoffs": [],
        "character_deltas": [],
        "world_deltas": [],
        "relationship_deltas": [],
        "arc_contributions": [],
        "canon_dependencies": [],
        "quality_targets": {"minimum": 80},
        "budget_policy_ref": "planning-budget:v1",
        "context_profile_ref": "planning-context:v1",
    }
    assert set(COMMON_FIELDS).issubset(payload)
    type_defaults: dict[PlanContractType, dict[str, Any]] = {
        PlanContractType.BOOK: {
            "reader_promise": "Escalation with earned payoff",
            "central_conflict_engine": "Goal versus irreversible cost",
            "protagonist_transformation": "Avoidance to accountable choice",
            "antagonist_escalation": ["pressure", "constraint", "collision"],
            "world_evolution": ["scarcity", "revelation"],
            "relationship_evolution": ["distrust", "alliance"],
            "theme_evolution": ["freedom", "responsibility"],
            "ending_contract": {"outcome": "costly agency"},
            "volume_skeleton": [{"volume": 1, "function": "commitment"}],
            "major_turns": ["irreversible choice"],
            "climax_distribution": [1],
            "long_promise_payoff": ["central promise settled"],
            "length_strategy": {"target_chapters": 3},
            "risk_register": [],
        },
        PlanContractType.VOLUME: {
            "volume_function": "force commitment",
            "stage_conflict": "safety versus truth",
            "stage_antagonist": "institutional resistance",
            "irreversible_change": "public commitment",
            "midpoint": "false victory",
            "climax": "costly revelation",
            "settlement": "new obligation",
            "next_volume_bridge": "wider threat",
            "chapter_range": [1, 3],
        },
        PlanContractType.ARC: {
            "arc_type": "character-conflict",
            "resistance": "denial",
            "escalation": "public consequences",
            "turn": "truth exposed",
            "choice": "accept responsibility",
            "cost": "loss of safety",
            "result": "earned agency",
            "consequence": "new opposition",
            "dependencies": [],
            "closure_conditions": ["choice demonstrated"],
            "cross_volume_scope": [command.parent_version_id],
        },
        PlanContractType.CHAPTER_GROUP: {
            "local_objective": "Turn private doubt into public commitment",
            "trigger": "evidence arrives",
            "resistance_escalation": ["denial", "countermove"],
            "turn": "ally defects",
            "local_climax": "public choice",
            "information_release": ["hidden cost"],
            "emotion_curve": ["doubt", "pressure", "resolve"],
            "antagonist_actions": ["isolate", "expose"],
            "chapter_function_matrix": [
                _chapter_function_row(1, "setup", "door closes"),
                _chapter_function_row(2, "reversal", "ally defects"),
                _chapter_function_row(3, "payoff", "cost arrives"),
            ],
            "chapter_range": [1, 3],
            "cost_range": ["social", "material"],
            "primary_arc_ids": ["arc:primary"],
            "secondary_arc_ids": [],
            "required_arc_contributions": ["arc:primary"],
            "arc_checkpoint_expectations": [
                {
                    "arc_plan_version_id": command.input_versions.get("arc_plans", ""),
                    "expectation": "choice advances",
                }
            ],
        },
        PlanContractType.CHAPTER: {
            **_chapter_function_row(1, "setup", "door closes"),
            "actual_arc_contributions": [],
            "title": "The Door Closes",
            "premise": "The protagonist makes a witnessed choice.",
        },
    }
    payload.update(type_defaults[contract_type])
    if contract_type is PlanContractType.CHAPTER:
        for contribution in payload["required_arc_contributions"]:
            contribution["arc_plan_version_id"] = command.input_versions["arc_plans"]
    if command.parent_version_id:
        payload["parent_version_id"] = command.parent_version_id
    assert set(TYPE_FIELDS[contract_type]).issubset(payload)
    return payload


def _chapter_function_row(chapter: int, function: str, hook: str) -> dict[str, Any]:
    return {
        "chapter_number": chapter,
        "primary_function": function,
        "secondary_functions": ["character pressure"],
        "required_state_delta": {"commitment": 1},
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc:primary", "kind": "advance"}
        ],
        "promise_action": "advance",
        "foreshadow_action": "plant",
        "reward_action": "partial payoff",
        "ending_hook": hook,
        "prohibited_outcomes": ["silent reset"],
    }


def _seed_inputs(project_id: str, book_id: str) -> dict[str, str]:
    roles = sorted(
        {role for values in GENERATOR_INPUT_ROLES.values() for role in values}
    )
    result: dict[str, str] = {}
    with transaction() as connection, connection.cursor() as cursor:
        for role in roles:
            asset_id = f"fixture:{project_id}:{role}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": role, "facts": [role]}
            if role == "production_profile":
                content["profile_id"] = "controlled-planning-fixture"
                content["target_chapter_count"] = 3
            elif role == "book_design":
                content["ending_contract"] = {"outcome": "costly agency"}
            digest = (
                "sha256:"
                + hashlib.sha256(str(sorted(content.items())).encode()).hexdigest()
            )
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, role],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [version_id, asset_id, Jsonb(content), digest, f"{role}.v1"],
            )
            result[role] = version_id
    return result


def _seed_recap_lineage(project_id: str, book_id: str) -> tuple[str, str]:
    definition_name = identifier("longform-recap-fixture-definition")
    operation_id = identifier("longform-recap-fixture-operation")
    outputs: list[tuple[str, str, str]] = []
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=project_id,
            status="SUCCEEDED",
        )
        for asset_type, output_key, content in (
            (
                "longform_recap",
                "longform.recap.report",
                {"book_id": book_id, "deviations": ["GROUP_OBJECTIVE_DRIFT"]},
            ),
            (
                "replan_request",
                "longform.recap.replan_request",
                {
                    "book_id": book_id,
                    "affected_scope": "CHAPTER_GROUP",
                    "future_only": True,
                },
            ),
        ):
            asset_id = identifier(f"{asset_type}-asset")
            version_id = f"{asset_id}:v1"
            digest = canonical_hash(content)
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    digest,
                    f"{asset_type}.v1",
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_operation_output_asset(
                    operation_id,asset_id,asset_version_id,output_key,role,content_hash
                ) VALUES (%s,%s,%s,%s,'PRIMARY',%s)
                """,
                [operation_id, asset_id, version_id, output_key, digest],
            )
            outputs.append((asset_type, output_key, version_id))
    return outputs[0][2], outputs[1][2]


def _seed_current_canon_role_outputs(
    *, project_id: str, book_id: str, book_run_id: str
) -> dict[str, str]:
    definition_name = identifier("current-canon-role-fixture-definition")
    operation_id = identifier("current-canon-role-fixture-operation")
    versions: dict[str, str] = {}
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=project_id,
            status="SUCCEEDED",
        )
        for asset_type in (
            "canon_snapshot",
            "character_state_snapshot",
            "foreshadow_snapshot",
            "reward_ledger_snapshot",
            "promise_ledger_snapshot",
        ):
            asset_id = identifier(f"current-{asset_type}-asset")
            version_id = f"{asset_id}:v1"
            content = {
                "book_id": book_id,
                "chapter_number": 1,
                "role": asset_type,
            }
            digest = canonical_hash(content)
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    digest,
                    f"{asset_type}.v1",
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_operation_output_asset(
                    operation_id,asset_id,asset_version_id,output_key,role,content_hash
                ) VALUES (%s,%s,%s,%s,'state_snapshot',%s)
                """,
                [
                    operation_id,
                    asset_id,
                    version_id,
                    f"chapter.canon.snapshot.{asset_type}",
                    digest,
                ],
            )
            versions[asset_type] = version_id
        cursor.execute(
            """
            UPDATE authority_book_production
            SET active_canon_snapshot_version_id=%s
            WHERE book_run_id=%s
            """,
            [versions["canon_snapshot"], book_run_id],
        )
        assert cursor.rowcount == 1
    return versions


def _seed_chapter_acceptance_for_checkpoint(
    *,
    project_id: str,
    book_run_id: str,
    chapter_plan_version: str,
    chapter_group_plan_version: str,
    production_profile_version: str,
    arc_plan_version: str,
) -> str:
    request_id = identifier("checkpoint-chapter-request")
    delegation_id = identifier("checkpoint-delegation")
    child_operation_id = identifier("checkpoint-child-operation")
    acceptance_operation_id = identifier("checkpoint-acceptance-operation")
    child_saga_id = identifier("checkpoint-child-saga")
    child_definition = identifier("checkpoint-child-definition")
    acceptance_definition = identifier("checkpoint-acceptance-definition")
    outcome_version = ""
    story_state_version = ""
    canon_version = ""
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s",
            [chapter_plan_version],
        )
        chapter_plan_hash = str(cursor.fetchone()[0])
        insert_definition(cursor, child_definition)
        insert_definition(cursor, acceptance_definition)
        insert_operation(
            cursor,
            operation_id=child_operation_id,
            definition_name=child_definition,
            project_id=project_id,
            status="SUCCEEDED",
        )
        insert_operation(
            cursor,
            operation_id=acceptance_operation_id,
            definition_name=acceptance_definition,
            project_id=project_id,
            status="SUCCEEDED",
        )
        cursor.execute(
            """
            INSERT INTO authority_saga(
                saga_id,root_operation_id,project_id,status,trace_id,correlation_id
            ) VALUES (%s,%s,%s,'SUCCEEDED',%s,%s)
            """,
            [
                child_saga_id,
                child_operation_id,
                project_id,
                f"trace:{child_operation_id}",
                f"correlation:{child_operation_id}",
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_book_chapter_request(
                chapter_request_id,book_run_id,project_id,chapter_number,
                chapter_plan_version,chapter_plan_content_hash,
                production_profile_version,stable_idempotency_key,command_payload,
                chapter_root_operation_id,chapter_saga_id,status_reference,
                parent_group_version_id
            ) VALUES (%s,%s,%s,1,%s,%s,%s,%s,'{}'::jsonb,%s,%s,'SUCCEEDED',%s)
            """,
            [
                request_id,
                book_run_id,
                project_id,
                chapter_plan_version,
                chapter_plan_hash,
                production_profile_version,
                f"{request_id}:submit",
                child_operation_id,
                child_saga_id,
                chapter_group_plan_version,
            ],
        )
        cursor.execute(
            """
            INSERT INTO authority_child_delegation(
                delegation_id,project_id,owner_authority,owner_id,child_authority,
                chapter_request_id,chapter_number,plan_version_id,
                child_root_operation_id,child_saga_id,stable_idempotency_key,status
            ) VALUES (%s,%s,'BOOK',%s,'CHAPTER',%s,1,%s,%s,%s,%s,'ACCEPTED')
            """,
            [
                delegation_id,
                project_id,
                book_run_id,
                request_id,
                chapter_plan_version,
                child_operation_id,
                child_saga_id,
                f"{request_id}:delegation",
            ],
        )
        for asset_type, content in (
            (
                "chapter_outcome",
                {
                    "actual_arc_contributions": [
                        {
                            "arc_plan_version_id": arc_plan_version,
                            "kind": "advance",
                            "evidence": "accepted chapter outcome",
                        }
                    ]
                },
            ),
            ("story_state_snapshot", {"chapter_number": 1}),
            ("canon_snapshot", {"chapter_number": 1}),
        ):
            asset_id = identifier(f"checkpoint-{asset_type}")
            version_id = f"{asset_id}:v1"
            digest = canonical_hash(content)
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    digest,
                    f"{asset_type}.v1",
                ],
            )
            if asset_type == "chapter_outcome":
                outcome_version = version_id
            elif asset_type == "story_state_snapshot":
                story_state_version = version_id
            else:
                canon_version = version_id
        cursor.execute(
            """
            INSERT INTO authority_book_chapter_acceptance(
                acceptance_id,project_id,book_run_id,chapter_request_id,
                delegation_id,acceptance_operation_id,chapter_number,
                chapter_outcome_asset_version_id,story_state_asset_version_id,
                canon_snapshot_asset_version_id,evidence,status
            ) VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,'COMMITTED')
            """,
            [
                identifier("checkpoint-acceptance"),
                project_id,
                book_run_id,
                request_id,
                delegation_id,
                acceptance_operation_id,
                outcome_version,
                story_state_version,
                canon_version,
                Jsonb({"fixture_protocol_only": True}),
            ],
        )
    return request_id


def _activate_plan_chain(
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    generic: dict[str, str],
    principal: Principal,
    application: StoryPlanningGenerationApplication,
    assert_replay: bool = False,
) -> dict[str, str]:
    activated: dict[str, str] = {}
    parent = ""
    sequence = (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    )
    for generator in sequence:
        inputs = {
            role: (
                activated["book_plan.generate"]
                if role == "book_plan"
                else activated["volume_plan.generate"]
                if role == "volume_plan"
                else activated["arc_plan.generate"]
                if role == "arc_plans"
                else activated["chapter_group_plan.generate"]
                if role == "chapter_group_plan"
                else generic[role]
            )
            for role in GENERATOR_INPUT_ROLES[generator]
        }
        logical = {
            "book_plan.generate": "book:main",
            "volume_plan.generate": "volume:1",
            "arc_plan.generate": "arc:primary",
            "chapter_group_plan.generate": "chapter-group:1-3",
            "chapter_plan.generate": "chapter:1",
        }[generator]
        command = StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name=generator,
            logical_key=logical,
            input_versions=inputs,
            parent_version_id=parent,
            idempotency_key=f"{project_id}:{generator}",
            trace_id=f"trace:{generator}",
            correlation_id=f"correlation:{project_id}",
        )
        generated = application.generate(command, principal=principal)
        assert generated.status is PlanningGenerationStatus.APPROVAL_PENDING
        candidate = application.require_candidate(
            generated.candidate_asset_version_id
        )
        assert candidate["generator_definition_version"] == (
            GENERATOR_CATALOG[generator].definition_version
        )
        application.approve_candidate(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{command.idempotency_key}:approve",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        active = application.activate_candidate(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{command.idempotency_key}:activate",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        assert (
            active["planning_binding"]["asset_version_id"]
            == generated.candidate_asset_version_id
        )
        activated[generator] = generated.candidate_asset_version_id
        if generator in {
            "book_plan.generate",
            "volume_plan.generate",
            "chapter_group_plan.generate",
        }:
            parent = generated.candidate_asset_version_id
        elif generator == "arc_plan.generate":
            parent = activated["volume_plan.generate"]
        if assert_replay:
            replay = application.generate(command, principal=principal)
            assert replay.status is PlanningGenerationStatus.ACTIVE
            assert replay.replayed is True
            assert (
                replay.candidate_asset_version_id
                == generated.candidate_asset_version_id
            )
    return activated


def test_five_planning_generators_repair_activate_and_replay_in_postgres() -> None:
    ensure_migrated()
    suffix = uuid4().hex
    project_id = f"planning-project-{suffix}"
    workspace_id = f"planning-workspace-{suffix}"
    book_id = f"planning-book-{suffix}"
    seed_authority_project_book(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id
    )
    generic = _seed_inputs(project_id, book_id)
    principal = _principal(project_id)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(),
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    activated = _activate_plan_chain(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        generic=generic,
        principal=principal,
        application=application,
        assert_replay=True,
    )

    repair_inputs = {
        role: generic[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
    }
    repaired = application.generate(
        StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key="book:repair-probe",
            input_versions=repair_inputs,
            idempotency_key=f"{project_id}:repair-probe",
            trace_id="trace:repair-probe",
            correlation_id=f"correlation:{project_id}",
        ),
        principal=principal,
    )
    assert repaired.status is PlanningGenerationStatus.APPROVAL_PENDING
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE repair_number=1)
            FROM authority_story_planning_generation
            WHERE project_id=%s AND logical_key='book:repair-probe'
            """,
            [project_id],
        )
        assert uow.cursor.fetchone() == (2, 1)
        uow.cursor.execute(
            """
            SELECT member_scope, membership_kind, COUNT(*)
            FROM authority_arc_membership
            WHERE project_id=%s AND arc_plan_version_id=%s
            GROUP BY member_scope, membership_kind
            """,
            [project_id, activated["arc_plan.generate"]],
        )
        assert set(uow.cursor.fetchall()) == {
            ("VOLUME", "VOLUME_SPAN", 1),
            ("CHAPTER_GROUP", "PRIMARY", 1),
            ("CHAPTER_GROUP", "REQUIRED_CONTRIBUTION", 1),
            ("CHAPTER_GROUP", "CHECKPOINT_EXPECTATION", 1),
            ("CHAPTER", "REQUIRED_CONTRIBUTION", 1),
        }
        uow.cursor.execute(
            """
            SELECT asset.asset_type,
                   version.content->>'source_planning_candidate_asset_version_id',
                   operation.definition_name, operation.status,
                   version.content->>'title', version.content->>'premise'
            FROM authority_operation_output_asset AS output
            JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=output.asset_version_id
            JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
            WHERE operation.project_id=%s
              AND output.output_key='story_planning.chapter_plan_projection'
            """,
            [project_id],
        )
        assert uow.cursor.fetchall() == [
            (
                "chapter_plan",
                activated["chapter_plan.generate"],
                "story_planning.chapter_plan.materialize",
                "SUCCEEDED",
                "The Door Closes",
                "The protagonist makes a witnessed choice.",
            )
        ]
        uow.cursor.execute(
            """
            SELECT generation_id
            FROM authority_story_planning_generation
            WHERE project_id=%s
            ORDER BY created_at
            LIMIT 1
            """,
            [project_id],
        )
        generation_id = str(uow.cursor.fetchone()[0])
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_story_planning_generation
                SET input_snapshot='[]'::jsonb
                WHERE generation_id=%s
                """,
                [generation_id],
            )


def test_production_composition_executes_five_planning_generators_via_pep() -> None:
    harness = CapabilityPackPostgresHarness("planning-production-composition")
    _activate_planning_pack(harness)
    generic = _seed_inputs(harness.project_id, harness.book_ids[0])
    principal = _principal(harness.project_id)
    with tempfile.TemporaryDirectory(prefix="planning-production-pep-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "development",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "planning-production-composition",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_MODEL": "scripted-planning-fixture",
            "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "xhigh",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        chapter = build_chapter_authority_application(settings, env=env)
        planning = build_story_planning_generation_application(
            settings,
            env=env,
            chapter_application=chapter,
        )
        activated = _activate_plan_chain(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=harness.book_ids[0],
            generic=generic,
            principal=principal,
            application=planning,
        )
        chapter.close()

    assert set(activated) == set(GENERATOR_INPUT_ROLES)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT snapshot.attempt_id),
                   COUNT(DISTINCT effect.external_effect_id)
            FROM authority_attempt_capability_pack_snapshot AS snapshot
            JOIN authority_operation AS operation
              ON operation.operation_id=snapshot.operation_id
            JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            WHERE operation.project_id=%s
              AND operation.definition_name='story_planning.generate'
              AND effect.provider='production_execution_gateway'
            """,
            [harness.project_id],
        )
        assert uow.cursor.fetchone() == (5, 5)
        uow.cursor.execute(
            """
            SELECT DISTINCT version.content->'contract'->>'model_id',
                            version.content->'contract'->>'reasoning_effort'
            FROM authority_asset AS asset
            JOIN authority_asset_version AS version
              ON version.asset_id=asset.asset_id
            WHERE asset.project_id=%s
              AND asset.asset_type='model_profile'
              AND version.content->'contract'->>'profile_id'
                    LIKE 'planning.%%.default'
            """,
            [harness.project_id],
        )
        assert uow.cursor.fetchall() == [("scripted-planning-fixture", "xhigh")]


def test_planning_retry_reuses_frozen_pack_after_measured_provider_result() -> None:
    harness = CapabilityPackPostgresHarness("planning-attempt-retry")
    baseline_deployment_id = _activate_planning_pack(harness)
    generic = _seed_inputs(harness.project_id, harness.book_ids[0])
    principal = _principal(harness.project_id)
    injected = {"done": False}

    def fail_once(checkpoint: str) -> None:
        if (
            checkpoint == "after_measured_usage_before_candidate_acceptance"
            and not injected["done"]
        ):
            injected["done"] = True
            raise KernelError(
                "MODEL_EFFECT_RETRYABLE_PLANNING_PROOF",
                "controlled proof failure after measured Provider usage",
            )

    with tempfile.TemporaryDirectory(prefix="planning-attempt-retry-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "development",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "planning-attempt-retry",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        chapter = build_chapter_authority_application(settings, env=env)
        planning = build_story_planning_generation_application(
            settings,
            env=env,
            chapter_application=chapter,
            post_provider_fault_injector=fail_once,
        )
        command = StoryPlanningGenerationCommand(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=harness.book_ids[0],
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key=f"{harness.book_ids[0]}:retry-proof",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key=f"{harness.project_id}:planning-retry-proof",
            trace_id=f"trace:{harness.project_id}:planning-retry-proof",
            correlation_id=f"correlation:{harness.project_id}",
        )
        with pytest.raises(KernelError, match="MODEL_EFFECT_RETRYABLE_PLANNING_PROOF"):
            planning.generate(command, principal=principal)

        replacement_scope = harness.approval_scope()
        replacement_scope["allowed_workflow_definition_refs"] = [
            STORY_PLANNING_WORKFLOW_DEFINITION_REF
        ]
        replacement_pack = harness.register_compile_approve(
            "1.2.0", generation=2, approval_scope=replacement_scope
        )
        replacement_deployment = harness.deploy(replacement_pack)
        harness.activate(replacement_deployment, expected_activation_version=1)

        result = planning.generate(command, principal=principal)
        chapter.close()

    assert result.status is PlanningGenerationStatus.APPROVAL_PENDING
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT attempt.attempt_number, attempt.status,
                   snapshot.snapshot_id, snapshot.snapshot_hash,
                   snapshot.pack_version, snapshot.deployment_id
            FROM authority_attempt AS attempt
            JOIN authority_attempt_capability_pack_snapshot AS snapshot
              ON snapshot.attempt_id=attempt.attempt_id
            WHERE attempt.operation_id=%s
            ORDER BY attempt.attempt_number
            """,
            [result.generation_operation_id],
        )
        attempts = uow.cursor.fetchall()
        uow.cursor.execute(
            """
            SELECT asset.asset_type, version.content->>'candidate_accepted'
            FROM authority_operation_output_asset AS binding
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE binding.operation_id=%s
              AND asset.asset_type IN ('model_call_log', 'cost_ledger')
              AND version.content ? 'candidate_accepted'
            ORDER BY asset.asset_type, version.created_at
            """,
            [result.generation_operation_id],
        )
        evidence = uow.cursor.fetchall()
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_operation_output_asset
            WHERE operation_id=%s AND role='primary'
              AND output_key='story_planning.candidate'
            """,
            [result.generation_operation_id],
        )
        candidate_count = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT status
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [result.generation_operation_id],
        )
        operation_status = str(uow.cursor.fetchone()[0])
    assert [(row[0], row[1]) for row in attempts] == [
        (1, "FAILED_RETRYABLE"),
        # Planning remains approval-gated after Provider success, so the
        # successful Attempt is deliberately held at RESULT_SUBMITTED while
        # the Operation waits for Planning Authority approval.
        (2, "RESULT_SUBMITTED"),
    ]
    assert operation_status == "WAITING_GATE"
    assert attempts[0][2] != attempts[1][2]
    assert attempts[0][3] == attempts[1][3]
    assert attempts[0][4] == attempts[1][4] == "1.1.0"
    assert attempts[0][5] == attempts[1][5] == baseline_deployment_id
    assert attempts[1][5] != replacement_deployment.deployment_id
    assert evidence == [
        ("cost_ledger", "false"),
        ("cost_ledger", "true"),
        ("model_call_log", "false"),
        ("model_call_log", "true"),
    ]
    assert candidate_count == 1


def test_book_input_resolver_freezes_active_authorities_and_planning_pack() -> None:
    harness = CapabilityPackPostgresHarness("book-input-resolver")
    deployment_id = _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    generic = _seed_inputs(project_id, book_id)
    principal = _principal(project_id)
    execution_resolver = PostgresPlanningExecutionBundleResolver(
        DATABASE_URL,
        execution_preparer=_PlanningExternalEffectPreparer(),
        workflow_definition_ref=STORY_PLANNING_WORKFLOW_DEFINITION_REF,
        pack_id=harness.pack_id,
        environment="development",
        runtime_profile="development",
        release_channel="VALIDATION",
        release_sha=RELEASE_SHA,
    )
    planning = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=CapabilityPackBackedPlanningExecutionBinder(
            execution_resolver
        ),
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    activated = _activate_plan_chain(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        generic=generic,
        principal=principal,
        application=planning,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT snapshot.attempt_id),
                   COUNT(DISTINCT work_order.turn_id),
                   COUNT(DISTINCT binding.attempt_id),
                   COUNT(DISTINCT effect.external_effect_id)
            FROM authority_story_planning_generation AS generation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=generation.operation_id
            JOIN authority_attempt_capability_pack_snapshot AS snapshot
              ON snapshot.attempt_id=attempt.attempt_id
            JOIN authority_agent_work_order AS work_order
              ON work_order.attempt_id=attempt.attempt_id
            JOIN authority_agent_runtime_binding AS binding
              ON binding.attempt_id=attempt.attempt_id
            JOIN authority_external_effect AS effect
              ON effect.operation_id=generation.operation_id
            WHERE generation.project_id=%s
            """,
            [project_id],
        )
        assert uow.cursor.fetchone() == (5, 5, 5, 5)
    book_record_id = f"fixture:{project_id}:book-record"
    book_record_version = f"{book_record_id}:v1"
    with transaction() as connection, connection.cursor() as cursor:
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:{asset_type}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": asset_type}
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    canonical_hash(content),
                    f"{asset_type}.v1",
                ],
            )
        book_record = {"book_id": book_id, "record": "authority"}
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'book_record')",
            [book_record_id, project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'book-record.v1')
            """,
            [
                book_record_version,
                book_record_id,
                Jsonb(book_record),
                canonical_hash(book_record),
            ],
        )
        cursor.execute(
            """
                UPDATE authority_book
                SET current_book_asset_version_id=%s,
                    current_book_design_asset_version_id=%s,
                    production_profile=%s,
                    status='DESIGN_ACTIVE', version=version+1
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            RETURNING version
            """,
            [
                book_record_version,
                generic["book_design"],
                Jsonb({"profile_id": "controlled-planning-fixture"}),
                project_id,
                workspace_id,
                book_id,
            ],
        )
        expected_book_version = int(cursor.fetchone()[0])
    resolver = BookProductionInputResolver(
        DATABASE_URL,
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    command = ResolveBookProductionInputCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        production_profile=generic["production_profile"],
        expected_book_version=expected_book_version,
        actor_id=principal.principal_id,
        idempotency_key=f"{project_id}:resolve-input",
        trace_id=f"trace:{project_id}:resolve-input",
        correlation_id=f"correlation:{project_id}",
    )
    snapshot = resolver.resolve(command, principal=principal)
    replay = resolver.resolve(command, principal=principal)
    assert snapshot.snapshot_id == replay.snapshot_id
    assert snapshot.book_plan_version == activated["book_plan.generate"]
    assert snapshot.current_volume_plan_version == activated["volume_plan.generate"]
    assert snapshot.active_arc_plan_versions == (activated["arc_plan.generate"],)
    assert (
        snapshot.current_chapter_group_plan_version
        == activated["chapter_group_plan.generate"]
    )
    assert deployment_id in snapshot.capability_pack_deployment_refs
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_book_production_input_snapshot SET release_sha=%s WHERE snapshot_id=%s",
                ["f" * 40, snapshot.snapshot_id],
            )

    book_authority = PostgresBookAuthority(
        DATABASE_URL,
        chapter_port=object(),
        followup_application=object(),
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
        legacy_fixture_input_allowed=False,
    )
    book = book_authority.start(
        StartBookProductionCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            trace_id=f"trace:{project_id}:book-start",
            correlation_id=f"correlation:{project_id}",
            stable_idempotency_key=f"{project_id}:book-start",
            book_design_version=snapshot.book_design_version,
            book_plan_version=snapshot.book_plan_version,
            production_profile_version=snapshot.production_profile_version,
            longform_context_versions={
                "volume_plan_version": snapshot.current_volume_plan_version,
                "arc_plan_version": snapshot.active_arc_plan_versions[0],
                "character_state_version": snapshot.character_state_version,
                "foreshadowing_state_version": (snapshot.foreshadowing_state_version),
                "quality_trend_version": snapshot.quality_trend_version,
                "reward_ledger_version": snapshot.reward_ledger_version,
                "promise_ledger_version": snapshot.promise_ledger_version,
                "reader_segment_version": snapshot.reader_segment_version,
                "reader_contract_version": snapshot.reader_contract_version,
                "platform_profile_version": snapshot.platform_profile_version,
            },
            target_chapter_count=3,
            input_snapshot_id=snapshot.snapshot_id,
            input_mode="RESOLVED_AUTHORITY_INPUT",
        ),
        principal=principal,
    )
    checkpoint_request_id = _seed_chapter_acceptance_for_checkpoint(
        project_id=project_id,
        book_run_id=book.book_run_id,
        chapter_plan_version=activated["chapter_plan.generate"],
        chapter_group_plan_version=activated["chapter_group_plan.generate"],
        production_profile_version=snapshot.production_profile_version,
        arc_plan_version=activated["arc_plan.generate"],
    )
    checkpoints = PostgresBookNarrativeCheckpointAuthority(
        DATABASE_URL,
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    checkpoint_result = checkpoints.record_after_acceptance(
        book_run_id=book.book_run_id,
        chapter_request_id=checkpoint_request_id,
        principal=principal,
    )
    checkpoint_replay = checkpoints.record_after_acceptance(
        book_run_id=book.book_run_id,
        chapter_request_id=checkpoint_request_id,
        principal=principal,
    )
    assert checkpoint_result["replayed"] is False
    assert checkpoint_replay["replayed"] is True
    assert checkpoint_result["operation_id"] == checkpoint_replay["operation_id"]
    assert {
        key: value for key, value in checkpoint_result.items() if key != "replayed"
    } == {key: value for key, value in checkpoint_replay.items() if key != "replayed"}
    assert checkpoint_result["contribution_count"] == 1
    assert checkpoint_result["ending_reachability"]["status"] in {
        "REACHABLE",
        "AT_RISK",
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT contribution.contribution_id),
                   COUNT(DISTINCT arc.checkpoint_id),
                   COUNT(DISTINCT volume.checkpoint_id),
                   COUNT(DISTINCT ending.report_id),
                   COUNT(DISTINCT checkpoint_operation.operation_id)
            FROM authority_arc_contribution AS contribution
            JOIN authority_book_arc_checkpoint AS arc
              ON arc.updated_by_operation_id=contribution.recorded_by_operation_id
            JOIN authority_book_volume_checkpoint AS volume
              ON volume.updated_by_operation_id=contribution.recorded_by_operation_id
            JOIN authority_ending_reachability_report AS ending
              ON ending.generated_by_operation_id=contribution.recorded_by_operation_id
            JOIN authority_operation AS checkpoint_operation
              ON checkpoint_operation.operation_id=contribution.recorded_by_operation_id
            WHERE contribution.chapter_request_id=%s
              AND checkpoint_operation.definition_name='book.narrative_checkpoint.record'
              AND checkpoint_operation.status='SUCCEEDED'
            """,
            [checkpoint_request_id],
        )
        assert uow.cursor.fetchone() == (1, 1, 1, 1, 1)
    current_canon_roles = _seed_current_canon_role_outputs(
        project_id=project_id,
        book_id=book_id,
        book_run_id=book.book_run_id,
    )
    recap_version, replan_request_version = _seed_recap_lineage(project_id, book_id)
    plan_change = PostgresPlanChangeAuthority(
        DATABASE_URL,
        story_design=planning.story_design,
        planning=planning.planning,
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    coordinator = BookReplanCoordinator(
        DATABASE_URL,
        book_authority=book_authority,
        planning=planning,
        plan_change=plan_change,
        input_resolver=resolver,
        principal=principal,
    )
    replan_command = CoordinateBookReplanCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        book_run_id=book.book_run_id,
        source_recap_asset_version_id=recap_version,
        replan_request_asset_version_id=replan_request_version,
        affected_scope="CHAPTER_GROUP",
        target_asset_version_id=activated["chapter_group_plan.generate"],
        idempotency_key=f"{project_id}:replan:chapter-group",
        trace_id=f"trace:{project_id}:replan",
        correlation_id=book.root_operation_id,
    )
    pending = coordinator.start(replan_command)
    replayed_pending = coordinator.start(replan_command)
    assert pending["status"] == "APPROVAL_PENDING"
    assert replayed_pending["replan_id"] == pending["replan_id"]
    coordinator.approve(
        pending["replan_id"],
        authority_type="PLAN_CHANGE_AUTHORITY",
        authority_version="fixture-explicit-approval-v1",
        evidence={
            "human_approved": True,
            "fixture_protocol_only": True,
            "production_verified": False,
        },
    )
    resumed = coordinator.activate(pending["replan_id"])
    replayed_resume = coordinator.activate(pending["replan_id"])
    assert resumed["status"] == "RESUMED"
    assert resumed["book_state"] == "READY"
    assert resumed["replacement_child_candidate"]
    assert replayed_resume["replan_id"] == resumed["replan_id"]
    assert resumed["input_snapshot_id"] != snapshot.snapshot_id
    resumed_snapshot = resolver.require(resumed["input_snapshot_id"])
    assert (
        resumed_snapshot.character_state_version
        == current_canon_roles["character_state_snapshot"]
    )
    assert (
        resumed_snapshot.foreshadowing_state_version
        == current_canon_roles["foreshadow_snapshot"]
    )
    assert (
        resumed_snapshot.reward_ledger_version
        == current_canon_roles["reward_ledger_snapshot"]
    )
    assert (
        resumed_snapshot.promise_ledger_version
        == current_canon_roles["promise_ledger_snapshot"]
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT freshness FROM story_plan_binding
            WHERE asset_version_id=%s
            """,
            [activated["chapter_group_plan.generate"]],
        )
        old_group_freshness = str(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COUNT(*) FROM authority_book_production_input_binding
            WHERE book_run_id=%s
            """,
            [book.book_run_id],
        )
        binding_count = int(uow.cursor.fetchone()[0])
    assert old_group_freshness == "STALE"
    assert binding_count == 2

    chapter_groups = PostgresChapterGroupAuthority(
        DATABASE_URL,
        book_authority=book_authority,
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
    )
    supervisor = PostgresBookProductionSupervisor(
        book_authority,
        planning=planning,
        chapter_groups=chapter_groups,
        principal=principal,
    )
    group_frozen = supervisor.tick(book.book_run_id)
    assert group_frozen.action is SupervisorAction.FREEZE_CHAPTER_GROUP_PLAN
    group_started = supervisor.tick(book.book_run_id)
    assert group_started.action is SupervisorAction.START_CHAPTER_GROUP
    paused = book_authority.pause(
        book.book_run_id, reason="restart recovery probe", principal=principal
    )
    assert paused["state"] == "PAUSED"
    restarted_supervisor = PostgresBookProductionSupervisor(
        book_authority,
        planning=planning,
        chapter_groups=chapter_groups,
        principal=principal,
    )
    paused_tick = restarted_supervisor.tick(book.book_run_id)
    assert paused_tick.action is SupervisorAction.NO_ACTION
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*) FROM authority_chapter_group_production
            WHERE book_run_id=%s
            """,
            [book.book_run_id],
        )
        group_run_count = int(uow.cursor.fetchone()[0])
    assert group_run_count == 1
    resumed_book = book_authority.resume(
        book.book_run_id, reason="restart recovery complete", principal=principal
    )
    assert resumed_book["state"] == "READY"
    state_operation_id = supervisor._set_state(
        book_authority.require(book.book_run_id),
        BookProductionState.CHAPTER_PLAN_REQUIRED,
    )
    assert state_operation_id
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT definition_name, status
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [state_operation_id],
        )
        assert uow.cursor.fetchone() == (
            "book.supervisor.checkpoint.advance",
            "SUCCEEDED",
        )


def test_reader_judge_shadow_activation_drift_and_suspension_in_postgres() -> None:
    harness = CapabilityPackPostgresHarness("reader-judge-functional-loop")
    reader_node_selected = False
    for node in harness._base_manifest["workflow_template"]["nodes"]:
        if node.get("agent_definition_ref") and not reader_node_selected:
            node["commit_authority"] = "READER_JUDGE_AUTHORITY"
            reader_node_selected = True
    pack = harness.register_compile_approve("1.0.0", generation=1)
    deployment = harness.deploy(pack)
    harness.activate(deployment)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT node_bindings FROM authority_capability_pack_binding_set WHERE binding_set_id=%s",
            [deployment.binding_set_id],
        )
        nodes = list(uow.cursor.fetchone()[0])
    node = next(
        item for item in nodes if item["commit_authority"] == "READER_JUDGE_AUTHORITY"
    )
    application = ReaderJudgeAuthorityApplication(
        DATABASE_URL,
        application_build_id="reader-judge-functional-loop",
        commit_sha=RELEASE_SHA,
    )
    principal = harness.principal("reader-judge-admin", "reader_judge.authority.manage")
    key = harness.project_id
    created = application.create_definition(
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        definition=ReaderJudgeDefinition(
            judge_id=f"reader-judge:{harness.project_id}",
            definition_version=1,
            model_profile_ref="scripted-fixture-model@1",
            model_version="scripted-fixture-v1",
            capability_pack_ref=deployment.deployment_id,
            prompt_ref=str(node["prompt_bundle_ref"]),
            skill_ref=str(node["skill_bundle_ref"]),
            reader_segment_scope="*",
            platform_scope="*",
            genre_scope="*",
            subgenre_scope="*",
            chapter_type_scope="*",
            evaluation_contract_ref="reader-outcome-evaluation:v1",
            calibration_policy_ref="reader-calibration:v1",
            decision_policy_ref="reader-decision:v1",
            mode=JudgeMode.SHADOW,
            status=ReaderJudgeQualificationStatus.UNQUALIFIED,
        ),
        idempotency_key=f"{key}:create",
        trace_id=f"trace:{key}",
        correlation_id=f"correlation:{key}",
        principal=principal,
    )
    qualification = application.decide_qualification(
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        judge_version_id=str(created["judge_version_id"]),
        qualification_status=ReaderJudgeQualificationStatus.SHADOW,
        evidence_level="FIXTURE",
        evidence={"sample_size": 0, "minimum_sample_size": 1},
        calibration_profile_id="",
        idempotency_key=f"{key}:qualification",
        trace_id=f"trace:{key}",
        correlation_id=f"correlation:{key}",
        principal=principal,
    )
    application.activate(
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        book_id=harness.book_ids[0],
        judge_version_id=str(created["judge_version_id"]),
        expected_activation_version=0,
        idempotency_key=f"{key}:activate",
        trace_id=f"trace:{key}",
        correlation_id=f"correlation:{key}",
        principal=principal,
    )
    resolver = ReaderJudgeRuntimeResolver(DATABASE_URL)
    scope = ReaderJudgeResolutionScope(
        harness.project_id,
        harness.book_ids[0],
        "web",
        "fantasy",
        "progression",
        "standard",
        "general",
        "scripted-fixture-v1",
    )
    active = resolver.resolve(scope)
    assert active.mode is JudgeMode.SHADOW
    assert active.calibration_status is ReaderJudgeQualificationStatus.SHADOW
    assert active.publish_blocking is False
    assert active.authority_commit_allowed is False

    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE authority_capability_pack_deployment
            SET deployment_status='DISABLED'
            WHERE deployment_id=%s
            """,
            [deployment.deployment_id],
        )
    pack_disabled = resolver.resolve(scope)
    assert pack_disabled.fallback_reason == "NO_ACTIVE_QUALIFIED_JUDGE"
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE authority_capability_pack_deployment
            SET deployment_status='ACTIVE'
            WHERE deployment_id=%s
            """,
            [deployment.deployment_id],
        )

    second = application.create_definition(
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        definition=ReaderJudgeDefinition(
            judge_id=f"reader-judge-secondary:{harness.project_id}",
            definition_version=1,
            model_profile_ref="scripted-fixture-model@1",
            model_version="scripted-fixture-v1",
            capability_pack_ref=deployment.deployment_id,
            prompt_ref=str(node["prompt_bundle_ref"]),
            skill_ref=str(node["skill_bundle_ref"]),
            reader_segment_scope="*",
            platform_scope="*",
            genre_scope="*",
            subgenre_scope="*",
            chapter_type_scope="*",
            evaluation_contract_ref="reader-outcome-evaluation:v1",
            calibration_policy_ref="reader-calibration:v1",
            decision_policy_ref="reader-decision:v1",
            mode=JudgeMode.SHADOW,
            status=ReaderJudgeQualificationStatus.UNQUALIFIED,
        ),
        idempotency_key=f"{key}:create-secondary",
        trace_id=f"trace:{key}:secondary",
        correlation_id=f"correlation:{key}",
        principal=principal,
    )
    definition_name = identifier("reader-judge-cross-version-activation")
    operation_id = identifier("reader-judge-cross-version-operation")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=harness.project_id,
            status="SUCCEEDED",
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_reader_judge_activation(
                    activation_id,judge_version_id,project_id,book_id,
                    activation_version,expected_previous_activation_version,
                    qualification_decision_id,activation_operation_id
                ) VALUES (%s,%s,%s,NULL,1,0,%s,%s)
                """,
                [
                    f"reader-judge-activation:{uuid4()}",
                    second["judge_version_id"],
                    harness.project_id,
                    qualification["decision_id"],
                    operation_id,
                ],
            )

    application.record_drift(
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        book_id=harness.book_ids[0],
        expected_activation_version=1,
        severity="HIGH",
        drift_type="fixture-distribution-shift",
        evidence={"fixture": True},
        idempotency_key=f"{key}:drift",
        trace_id=f"trace:{key}",
        correlation_id=f"correlation:{key}",
        principal=principal,
    )
    drifted = resolver.resolve(scope)
    assert drifted.mode is JudgeMode.SHADOW
    assert drifted.calibration_status is ReaderJudgeQualificationStatus.DRIFTED

    application.suspend(
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        book_id=harness.book_ids[0],
        expected_activation_version=1,
        reason="operator fixture suspension",
        idempotency_key=f"{key}:suspend",
        trace_id=f"trace:{key}",
        correlation_id=f"correlation:{key}",
        principal=principal,
    )
    fallback = resolver.resolve(scope)
    assert fallback.mode is JudgeMode.SHADOW
    assert fallback.calibration_status is ReaderJudgeQualificationStatus.UNQUALIFIED
    assert fallback.fallback_reason == "NO_ACTIVE_QUALIFIED_JUDGE"

    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_reader_judge_version SET mode='ADVISORY' WHERE judge_version_id=%s",
                [created["judge_version_id"]],
            )


def test_reader_judge_composite_scope_rejects_cross_project_sql_chain() -> None:
    ensure_migrated()
    first = f"judge-scope-a-{uuid4().hex}"
    second = f"judge-scope-b-{uuid4().hex}"
    seed_authority_project_book(project_id=first, book_id=f"book:{first}")
    seed_authority_project_book(project_id=second, book_id=f"book:{second}")
    definition_name = identifier("reader-judge-scope-fixture")
    operation_id = identifier("reader-judge-scope-operation")
    judge_id = f"judge:{first}"
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=first,
            status="SUCCEEDED",
        )
        cursor.execute(
            "INSERT INTO authority_reader_judge(judge_id,project_id,created_by_operation_id) VALUES (%s,%s,%s)",
            [judge_id, first, operation_id],
        )
    other_definition = identifier("reader-judge-scope-fixture")
    other_operation = identifier("reader-judge-scope-operation")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, other_definition)
        insert_operation(
            cursor,
            operation_id=other_operation,
            definition_name=other_definition,
            project_id=second,
            status="SUCCEEDED",
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_reader_judge_version(
                    judge_version_id,judge_id,project_id,definition_version,
                    model_profile_ref,model_version,capability_pack_ref,
                    prompt_ref,skill_ref,reader_segment_scope,platform_scope,
                    genre_scope,subgenre_scope,chapter_type_scope,
                    evaluation_contract_ref,calibration_policy_ref,
                    decision_policy_ref,mode,status,maximum_adjustment_chapters,
                    definition,definition_hash,created_by_operation_id
                ) VALUES (
                    %s,%s,%s,1,'model@1','model-v1','pack','prompt','skill',
                    '*','*','*','*','*','evaluation','calibration','decision',
                    'SHADOW','UNQUALIFIED',0,'{}'::jsonb,%s,%s
                )
                """,
                [
                    f"judge-version:{uuid4()}",
                    judge_id,
                    second,
                    "sha256:" + "a" * 64,
                    other_operation,
                ],
            )
