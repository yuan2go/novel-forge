from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
    build_story_planning_generation_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.input_resolver import (
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.book_followup_authority import LongformCheckpointType
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
)
from novel_forge.modules.book_production import SupervisorAction
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
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    FrozenPlanningInput,
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
                "book.authority.approve_replan",
                "book.followup:*",
                "chapter.authority.execute",
                "external_effect.execute",
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
        | {
            "style_policy",
            "quality_rubric",
            # Frozen Story Design inputs retained by the existing Book input
            # snapshot schema.  They are future-intent inputs, not accepted
            # Narrative State v2 projections.
            "character_state",
            "foreshadowing_state",
            "reward_ledger",
            "promise_ledger",
        }
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
            elif role == "platform_profile":
                content["safe_summary"] = "Versioned internal platform policy."
                content["structured_facts"] = [
                    {
                        "key": "platform_rules",
                        "value": {
                            "chapter_length": {"minimum": 10, "maximum": 10000},
                            "format": {"paragraph_max": 500},
                            "sensitive_content": [],
                            "ai_content": {"mode": "internal"},
                            "opening": ["visible conflict"],
                            "rhythm": ["payoff"],
                            "publish_metadata": {"title_required": True},
                        },
                    }
                ]
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


def _followup_output(
    *,
    project_id: str,
    chapter_request_id: str,
    followup_type: str,
    output_key: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT link.operation_id, operation.status, binding.asset_version_id,
                   binding.content_hash, version.content
            FROM authority_book_followup_operation AS link
            JOIN authority_operation AS operation
              ON operation.operation_id=link.operation_id
            JOIN authority_operation_output_asset AS binding
              ON binding.operation_id=link.operation_id AND binding.output_key=%s
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
            WHERE link.project_id=%s AND link.chapter_request_id=%s
              AND link.followup_type=%s
            """,
            [output_key, project_id, chapter_request_id, followup_type],
        )
        rows = uow.cursor.fetchall()
    assert len(rows) == 1
    assert str(rows[0][1]) == "SUCCEEDED"
    return {
        "operation_id": str(rows[0][0]),
        "asset_version_id": str(rows[0][2]),
        "content_hash": str(rows[0][3]),
        "content": dict(rows[0][4]),
    }


def _followup_output_exists(
    *, project_id: str, chapter_request_id: str, output_key: str
) -> bool:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM authority_book_followup_operation AS link
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id=link.operation_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=link.operation_id
                WHERE link.project_id=%s
                  AND link.chapter_request_id=%s
                  AND binding.output_key=%s
                  AND operation.status='SUCCEEDED'
            )
            """,
            [project_id, chapter_request_id, output_key],
        )
        return bool(uow.cursor.fetchone()[0])


def _run_controlled_recap_through_authority(
    authority: Any,
    *,
    project_id: str,
    chapter_request_id: str,
    principal: Principal,
) -> dict[str, Any]:
    """Produce controlled Replan evidence through the real follow-up Authority."""
    request = authority.require_chapter_request(chapter_request_id)
    book = authority.require(request["book_run_id"])
    reader = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_request_id,
        followup_type="READER_OUTCOME",
        output_key="reader_outcome.report",
    )
    frozen = dict(book["longform_context_versions"])
    authority_inputs = authority.resolve_asset_refs(
        project_id=project_id,
        asset_version_ids=(
            str(book["book_design_version"]),
            str(book["book_plan_version"]),
            str(frozen["volume_plan_version"]),
            str(frozen["arc_plan_version"]),
            str(frozen["quality_trend_version"]),
            str(book["last_chapter_outcome_version_id"]),
            str(book["active_story_state_version_id"]),
            str(book["active_canon_snapshot_version_id"]),
        ),
    )

    admission = authority.schedule_longform_recap(
        chapter_request_id,
        principal=principal,
        payload={
            "book_id": book["book_id"],
            "checkpoint_type": LongformCheckpointType.BOOK_AUTHORITY_REQUEST.value,
            "chapter_range": [1, int(request["chapter_number"])],
            "book_design_version": book["book_design_version"],
            "book_plan_version": book["book_plan_version"],
            "volume_plan_version": frozen["volume_plan_version"],
            "arc_plan_version": frozen["arc_plan_version"],
            "canon_snapshot_version": book["active_canon_snapshot_version_id"],
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": frozen["quality_trend_version"],
            "chapter_outcome_versions": [book["last_chapter_outcome_version_id"]],
            "story_state_version": book["active_story_state_version_id"],
            "observations": {
                "evidence_level": "CONTROLLED_FIXTURE",
                "fixture_only": True,
                "production_verified": False,
                "reader_state": dict(reader["content"].get("reader_state") or {}),
                "reader_qualification": {
                    "qualification_status": "SHADOW",
                    "sample_size": 0,
                    "confidence": 0,
                    "disagreement": True,
                    "position_bias": True,
                    "ood": True,
                    "drift_detected": False,
                    "recent_reports": [],
                    "last_adjustment_chapter": None,
                },
                "canon": {
                    "conflicts": [
                        {
                            "type": "FUTURE_PROMISE_PAYOFF_DEVIATION",
                            "target": "chapter:2",
                            "executed_content_affected": False,
                        }
                    ],
                    "evidence_level": "CONTROLLED_FIXTURE",
                },
                "quality_trend": {"direction": "STABLE"},
            },
        },
        input_assets=(
            {
                "asset_version_id": str(reader["asset_version_id"]),
                "content_hash": str(reader["content_hash"]),
            },
            *authority_inputs,
        ),
    )
    authority.followup.run_or_recover(
        BookFollowupAdmission(admission.operation_id, project_id, True)
    )
    return {
        "operation_id": admission.operation_id,
        "recap": _followup_output(
            project_id=project_id,
            chapter_request_id=chapter_request_id,
            followup_type="LONGFORM_RECAP",
            output_key="longform.recap.report",
        ),
        "replan_request": _followup_output(
            project_id=project_id,
            chapter_request_id=chapter_request_id,
            followup_type="LONGFORM_RECAP",
            output_key="longform.recap.replan_request",
        ),
    }


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
        candidate = application.require_candidate(generated.candidate_asset_version_id)
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
        execution = build_production_execution_composition(settings, env=env)
        planning = build_story_planning_generation_application(
            settings,
            execution=execution,
            env=env,
        )
        activated = _activate_plan_chain(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=harness.book_ids[0],
            generic=generic,
            principal=principal,
            application=planning,
        )
        execution.close()

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
        execution = build_production_execution_composition(settings, env=env)
        planning = build_story_planning_generation_application(
            settings,
            execution=execution,
            env=env,
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
        execution.close()

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


@pytest.mark.parametrize("runtime_path", ("NO_REPLAN", "EXPLICIT_REPLAN_APPROVAL"))
def test_book_input_resolver_freezes_active_authorities_and_planning_pack(
    runtime_path: str,
) -> None:
    harness = CapabilityPackPostgresHarness("book-input-resolver")
    deployment_id = _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    generic = _seed_inputs(project_id, book_id)
    from tests.integration.test_postgresql_only_chapter_slice import (
        PostgreSQLOnlyChapterSliceTests,
    )

    PostgreSQLOnlyChapterSliceTests.release_evidence(project_id)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE authority_asset_version
            SET lifecycle='SUPERSEDED'
            WHERE asset_version_id=%s
            """,
            [f"{project_id}:platform-profile-v1"],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset(asset_id,project_id,asset_type)
            VALUES (%s,%s,'approval_decision')
            """,
            [f"fixture:{project_id}:approval-decision", project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            )
            SELECT %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',
                   content,content_hash,'integration-fixture.v1'
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [
                f"fixture:{project_id}:approval-decision:v1",
                f"fixture:{project_id}:approval-decision",
                f"{project_id}:approval-v1",
            ],
        )
    principal = _principal(project_id)
    worker_principal = Principal(
        principal_id=f"book-worker:{project_id}",
        principal_type=PrincipalType.WORKER,
        permissions=frozenset(
            permission
            for permission in principal.permissions
            if permission != "book.authority.approve_replan"
        ),
        project_scope=principal.project_scope,
        authentication_source="postgres-functional-loop-worker",
    )
    object_store = tempfile.TemporaryDirectory()
    settings = IndustrialSettings(
        root=Path(__file__).resolve().parents[2],
        environment="development",
        storage_authority="postgresql",
        database_url=DATABASE_URL,
    )
    runtime_env = {
        "NOVEL_FORGE_ENVIRONMENT": "development",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "core-functional-loop-fixture",
        "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": object_store.name,
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": "core-functional-loop-worker",
        "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
    }
    production_execution = build_production_execution_composition(
        settings, env=runtime_env
    )
    chapter_application = build_chapter_authority_application(
        settings, execution=production_execution, env=runtime_env
    )
    worker_production_executions = []

    def build_worker_runtime():
        worker_execution = build_production_execution_composition(
            settings, env=runtime_env
        )
        worker_chapter = build_chapter_authority_application(
            settings, execution=worker_execution, env=runtime_env
        )
        worker_production_executions.append(worker_execution)
        return (
            build_book_production_composition(
                settings,
                principal=worker_principal,
                execution=worker_execution,
                env=runtime_env,
                chapter_application=worker_chapter,
            ),
            worker_chapter,
        )

    composition = build_book_production_composition(
        settings,
        principal=principal,
        execution=production_execution,
        env=runtime_env,
        chapter_application=chapter_application,
    )
    worker_composition, worker_chapter_application = build_worker_runtime()
    planning = composition.planning
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
    resolver = composition.input_resolver
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

    book_authority = composition.authority
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from novel_forge.api.models import product_model_map
    from novel_forge.api.routers.book_authority import create_router
    from novel_forge.api.routers.context import ProductRouterContext

    authority_api = FastAPI()
    authority_api.include_router(
        create_router(
            ProductRouterContext(
                app_settings=settings,
                models=product_model_map(),
                services=SimpleNamespace(book_production=composition),
            )
        )
    )

    def api_post(path: str, payload: dict[str, Any]):
        trusted = SimpleNamespace(resolve_api_principal=lambda **_values: principal)
        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=trusted,
            ),
            TestClient(authority_api) as client,
        ):
            return client.post(path, json=payload)

    def api_get(path: str):
        query_principal = Principal(
            principal_id=f"book-query:{project_id}",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.query"}),
            project_scope=frozenset({project_id}),
            authentication_source="postgres-functional-loop-query",
        )
        trusted = SimpleNamespace(
            resolve_api_principal=lambda **_values: query_principal
        )
        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=trusted,
            ),
            TestClient(authority_api) as client,
        ):
            return client.get(path)

    start_response = api_post(
        "/product/production/book-authority/commands",
        {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "idempotency_key": f"{project_id}:book-start",
            "input_snapshot_id": snapshot.snapshot_id,
            "input_mode": "RESOLVED_AUTHORITY_INPUT",
            "target_chapter_count": 3,
            "light_recap_cadence": 5,
            "formal_recap_cadence": 10,
            "actor_id": "untrusted-caller",
            "trace_id": f"trace:{project_id}:book-start",
            "correlation_id": f"correlation:{project_id}",
        },
    )
    assert start_response.status_code == 202, start_response.text
    book = SimpleNamespace(**start_response.json())

    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.runtime_job import RuntimeJobAuthority
    from novel_forge.workers.book_authority import (
        execute_book_coordination_claim,
        schedule_book_coordination_jobs,
    )

    runtime_jobs = RuntimeJobAuthority(DATABASE_URL)

    def worker_tick(runtime):
        schedule_book_coordination_jobs(
            runtime.query,
            runtime_jobs,
            limit=1,
            book_run_id=book.book_run_id,
        )
        claim = runtime_jobs.claim(
            runtime_group="book",
            worker_id="canonical-book-worker",
            lease_seconds=30,
            job_kinds=("BOOK_COORDINATION_TICK",),
            subject_kind="BOOK_RUN",
            subject_id=book.book_run_id,
        )
        assert claim is not None
        return execute_book_coordination_claim(runtime_jobs, runtime, claim)

    def run_chapter(chapter_runtime, root_operation_id: str) -> None:
        scheduler = chapter_runtime.scheduler(principal=worker_principal)
        for _ in range(len(ChapterNode) + 4):
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=root_operation_id,
            )
            if tick.saga_status == "SUCCEEDED":
                return
        raise AssertionError("Chapter worker did not complete the admitted Chapter")

    before_replan_actions: list[str] = []
    for _ in range(32):
        tick = worker_tick(worker_composition)
        action = str(tick["action"])
        before_replan_actions.append(action)
        if action == SupervisorAction.DISPATCH_CHAPTER.value:
            run_chapter(worker_chapter_application, str(tick["operation_id"]))
        if (
            int(book_authority.require(book.book_run_id)["accepted_through_chapter"])
            >= 1
        ):
            break
    else:
        raise AssertionError("Canonical Worker did not accept Chapter 1")
    assert SupervisorAction.DISPATCH_CHAPTER.value in before_replan_actions
    assert SupervisorAction.ACCEPT_CHAPTER.value in before_replan_actions

    checkpoint_action = ""
    for _ in range(8):
        checkpoint_tick = worker_tick(worker_composition)
        checkpoint_action = str(checkpoint_tick["action"])
        if checkpoint_action == SupervisorAction.UPDATE_CHECKPOINTS.value:
            break
    assert checkpoint_action == SupervisorAction.UPDATE_CHECKPOINTS.value
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT request.chapter_request_id
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
            WHERE acceptance.book_run_id=%s AND acceptance.chapter_number=1
            """,
            [book.book_run_id],
        )
        checkpoint_request_id = str(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_volume_checkpoint
            WHERE book_run_id=%s AND accepted_through_chapter=1
            """,
            [book.book_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 1

    if runtime_path == "NO_REPLAN":
        no_replan_actions: list[str] = []
        for _ in range(32):
            tick = worker_tick(worker_composition)
            action = str(tick["action"])
            no_replan_actions.append(action)
            if action == SupervisorAction.DISPATCH_CHAPTER.value:
                run_chapter(worker_chapter_application, str(tick["operation_id"]))
            if (
                int(
                    book_authority.require(book.book_run_id)["accepted_through_chapter"]
                )
                >= 2
            ):
                break
        else:
            raise AssertionError(
                "Canonical Worker did not produce the no-Replan Chapter 2"
            )
        assert SupervisorAction.START_REPLAN.value not in no_replan_actions
        assert SupervisorAction.DISPATCH_CHAPTER.value in no_replan_actions
        assert SupervisorAction.ACCEPT_CHAPTER.value in no_replan_actions
        assert (
            book_authority.require(book.book_run_id)["input_snapshot_id"]
            == snapshot.snapshot_id
        )
        production_execution.close()
        for worker_execution in worker_production_executions:
            worker_execution.close()
        object_store.cleanup()
        return

    for _ in range(8):
        if _followup_output_exists(
            project_id=project_id,
            chapter_request_id=checkpoint_request_id,
            output_key="reader_outcome.report",
        ):
            break
        worker_tick(worker_composition)
    else:
        raise AssertionError("Canonical Worker did not complete Reader Outcome")

    controlled_recap = _run_controlled_recap_through_authority(
        book_authority,
        project_id=project_id,
        chapter_request_id=checkpoint_request_id,
        principal=principal,
    )
    coordinator = composition.replan
    assert controlled_recap["recap"]["asset_version_id"]
    assert controlled_recap["replan_request"]["asset_version_id"]
    book_authority.complete_followup(
        controlled_recap["operation_id"], replan_required=True
    )
    assert book_authority.require(book.book_run_id)["state"] == (
        BookProductionState.REPLAN_REQUIRED.value
    )

    started_replan = worker_tick(worker_composition)
    assert started_replan["action"] == SupervisorAction.START_REPLAN.value
    pending = coordinator.latest_for_book(book.book_run_id)
    assert pending is not None
    assert pending["status"] == "APPROVAL_PENDING"
    assert book_authority.require(book.book_run_id)["state"] == (
        BookProductionState.REPLAN_APPROVAL_PENDING.value
    )
    assert (
        schedule_book_coordination_jobs(
            composition.query,
            runtime_jobs,
            limit=1,
            book_run_id=book.book_run_id,
        )
        == ()
    )
    pending_restart, _pending_restart_chapter = build_worker_runtime()
    pending_restart_tick = pending_restart.tick(book.book_run_id)
    assert pending_restart_tick.action is SupervisorAction.WAIT_REPLAN_APPROVAL
    waiting_response = api_post(
        f"/product/production/book-authority/runs/{book.book_run_id}/tick",
        {},
    )
    assert waiting_response.status_code == 200, waiting_response.text
    assert waiting_response.json()["action"] == (
        SupervisorAction.WAIT_REPLAN_APPROVAL.value
    )
    assert (
        coordinator.latest_for_book(book.book_run_id)["replan_id"]
        == (pending["replan_id"])
    )
    with pytest.raises(PermissionError):
        worker_composition.approve_replan(
            book_run_id=book.book_run_id,
            replan_id=str(pending["replan_id"]),
            authority_type="PLAN_CHANGE_AUTHORITY",
            authority_version="worker-forbidden-v1",
            evidence={},
        )

    approval_response = api_post(
        f"/product/production/book-authority/runs/{book.book_run_id}/"
        f"replans/{pending['replan_id']}/approve",
        {
            "authority_type": "PLAN_CHANGE_AUTHORITY",
            "authority_version": "fixture-explicit-approval-v1",
            "evidence": {
                "operator_approved": True,
                "fixture_protocol_only": True,
                "production_verified": False,
            },
            "actor_id": "untrusted-caller",
        },
    )
    assert approval_response.status_code == 200, approval_response.text
    assert approval_response.json()["status"] == "ACTIVE"
    approval_replay = api_post(
        f"/product/production/book-authority/runs/{book.book_run_id}/"
        f"replans/{pending['replan_id']}/approve",
        {
            "authority_type": "PLAN_CHANGE_AUTHORITY",
            "authority_version": "fixture-explicit-approval-v1",
            "evidence": {
                "operator_approved": True,
                "fixture_protocol_only": True,
                "production_verified": False,
            },
            "actor_id": "untrusted-caller",
        },
    )
    assert approval_replay.status_code == 200, approval_replay.text
    assert approval_replay.json()["replan_id"] == pending["replan_id"]

    restarted, _restarted_chapter = build_worker_runtime()
    activated_replan = worker_tick(restarted)
    assert activated_replan["action"] == SupervisorAction.ACTIVATE_REPLAN.value
    resumed = restarted.replan.require(pending["replan_id"])
    assert resumed["status"] == "RESUMED"
    assert resumed["input_snapshot_id"] != snapshot.snapshot_id
    resumed_snapshot = resolver.require(resumed["input_snapshot_id"])
    # A replan binds a new immutable future-intent snapshot, but accepted
    # Narrative State remains owned by Book acceptance pointers.  It must not
    # be copied into the legacy Story Design input roles.
    assert resumed_snapshot.character_state_version == snapshot.character_state_version
    assert (
        resumed_snapshot.foreshadowing_state_version
        == snapshot.foreshadowing_state_version
    )
    assert resumed_snapshot.reward_ledger_version == snapshot.reward_ledger_version
    assert resumed_snapshot.promise_ledger_version == snapshot.promise_ledger_version
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

    group_transition = worker_tick(restarted)
    if group_transition["action"] == SupervisorAction.FREEZE_CHAPTER_GROUP_PLAN.value:
        group_started = worker_tick(restarted)
    else:
        group_started = group_transition
    assert group_started["action"] == SupervisorAction.START_CHAPTER_GROUP.value
    paused = book_authority.pause(
        book.book_run_id, reason="restart recovery probe", principal=principal
    )
    assert paused["state"] == "PAUSED"
    restarted_after_pause, restarted_after_pause_chapter = build_worker_runtime()
    paused_tick = restarted_after_pause.tick(book.book_run_id)
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
    assert group_run_count == 2
    resumed_book = book_authority.resume(
        book.book_run_id, reason="restart recovery complete", principal=principal
    )
    assert resumed_book["state"] == "READY"

    after_replan_actions: list[str] = []
    for _ in range(32):
        tick = worker_tick(restarted_after_pause)
        action = str(tick["action"])
        after_replan_actions.append(action)
        if action == SupervisorAction.DISPATCH_CHAPTER.value:
            run_chapter(restarted_after_pause_chapter, str(tick["operation_id"]))
        if (
            int(book_authority.require(book.book_run_id)["accepted_through_chapter"])
            >= 2
        ):
            break
    else:
        raise AssertionError("Canonical Worker did not resume through Chapter 2")
    assert SupervisorAction.DISPATCH_CHAPTER.value in after_replan_actions
    assert SupervisorAction.ACCEPT_CHAPTER.value in after_replan_actions
    assert book_authority.require(book.book_run_id)["accepted_through_chapter"] == 2

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT request.chapter_request_id
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
            WHERE acceptance.book_run_id=%s AND acceptance.chapter_number=2
            """,
            [book.book_run_id],
        )
        chapter_two_request_id = str(uow.cursor.fetchone()[0])
    current_book = book_authority.require(book.book_run_id)
    frozen = dict(current_book["longform_context_versions"])
    reader = _followup_output(
        project_id=project_id,
        chapter_request_id=checkpoint_request_id,
        followup_type="READER_OUTCOME",
        output_key="reader_outcome.report",
    )
    authority_inputs = book_authority.resolve_asset_refs(
        project_id=project_id,
        asset_version_ids=(
            str(current_book["book_design_version"]),
            str(current_book["book_plan_version"]),
            str(frozen["volume_plan_version"]),
            str(frozen["arc_plan_version"]),
            str(frozen["quality_trend_version"]),
            str(current_book["last_chapter_outcome_version_id"]),
            str(current_book["active_story_state_version_id"]),
            str(current_book["active_canon_snapshot_version_id"]),
        ),
    )
    later_admission = book_authority.schedule_longform_recap(
        chapter_two_request_id,
        principal=principal,
        payload={
            "book_id": current_book["book_id"],
            "checkpoint_type": LongformCheckpointType.ARC_CHECKPOINT.value,
            "chapter_range": [1, 2],
            "book_design_version": current_book["book_design_version"],
            "book_plan_version": current_book["book_plan_version"],
            "volume_plan_version": frozen["volume_plan_version"],
            "arc_plan_version": frozen["arc_plan_version"],
            "canon_snapshot_version": current_book["active_canon_snapshot_version_id"],
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": frozen["quality_trend_version"],
            "chapter_outcome_versions": [
                current_book["last_chapter_outcome_version_id"]
            ],
            "story_state_version": current_book["active_story_state_version_id"],
            "observations": {
                "evidence_level": "CONTROLLED_FIXTURE",
                "fixture_only": True,
                "production_verified": False,
                "reader_state": dict(reader["content"].get("reader_state") or {}),
                "reader_qualification": {
                    "qualification_status": "SHADOW",
                    "sample_size": 0,
                    "confidence": 0,
                    "disagreement": True,
                    "position_bias": True,
                    "ood": True,
                    "recent_reports": [],
                },
                "canon": {"conflicts": []},
                "quality_trend": {"direction": "STABLE"},
            },
        },
        input_assets=(
            {
                "asset_version_id": str(reader["asset_version_id"]),
                "content_hash": str(reader["content_hash"]),
            },
            *authority_inputs,
        ),
    )
    book_authority.followup.run_or_recover(
        BookFollowupAdmission(later_admission.operation_id, project_id, True)
    )
    later_recap = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_two_request_id,
        followup_type="LONGFORM_RECAP",
        output_key="longform.recap.report",
    )
    later_deviation = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_two_request_id,
        followup_type="LONGFORM_RECAP",
        output_key="longform.recap.deviation_report",
    )
    reevaluation_payload = {
        "source_recap_asset_version_id": str(later_recap["asset_version_id"]),
        "deviation_report_asset_version_id": str(later_deviation["asset_version_id"]),
        "idempotency_key": f"{pending['replan_id']}:reevaluation:chapter:2",
        "trace_id": f"trace:{pending['replan_id']}:reevaluation",
        "correlation_id": str(later_admission.operation_id),
        "actor_id": "untrusted-caller",
    }
    reevaluation_response = api_post(
        f"/product/production/book-authority/runs/{book.book_run_id}/"
        f"replans/{pending['replan_id']}/reevaluate",
        reevaluation_payload,
    )
    replayed_response = api_post(
        f"/product/production/book-authority/runs/{book.book_run_id}/"
        f"replans/{pending['replan_id']}/reevaluate",
        reevaluation_payload,
    )
    assert reevaluation_response.status_code == 200, reevaluation_response.text
    assert replayed_response.status_code == 200, replayed_response.text
    reevaluated = reevaluation_response.json()
    replayed_reevaluation = replayed_response.json()
    assert reevaluated["resolution"] == "RESOLVED"
    assert replayed_reevaluation["replayed"] is True
    assert replayed_reevaluation["reevaluation_id"] == (reevaluated["reevaluation_id"])
    corrective_response = api_get(
        f"/product/production/book-authority/runs/{book.book_run_id}/"
        "corrective-actions?issue_type=CANON_CONFLICT"
    )
    assert corrective_response.status_code == 200, corrective_response.text
    corrective = corrective_response.json()
    assert len(corrective) == 1
    assert corrective[0]["status"] == "RESOLVED"
    assert (
        corrective[0]["evaluation_operation_id"]
        == (reevaluated["evaluation_operation_id"])
    )
    production_execution.close()
    for worker_execution in worker_production_executions:
        worker_execution.close()
    object_store.cleanup()


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
