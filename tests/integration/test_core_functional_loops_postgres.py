from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
import json
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
from novel_forge.modules.book_authority import OpenBookProductionRequest
from novel_forge.modules.book_authority.input_resolver import (
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.book_design_authority import (
    EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignSemanticEvaluationCommand,
)
from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.workers.book_authority import execute_book_opening_claim
from novel_forge.modules.book_followup_authority import LongformCheckpointType
from novel_forge.modules.book_followup_authority.coordinator import (
    PostgresBookFollowupCoordinator,
)
from novel_forge.modules.book_followup_authority.query import (
    BookFollowupProjectionQuery,
)
from novel_forge.modules.book_replan import (
    CoordinateBookReplanCommand,
)
from novel_forge.modules.book_production import SupervisorAction
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
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
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
    canonical_hash,
    story_planning_generation_definition,
)
from novel_forge.modules.story_planning_runtime.execution import (
    planning_fixture_response,
)
from novel_forge.modules.production_execution import ModelProfile
from novel_forge.modules.story_design_authority import (
    GENERATOR_CATALOG,
    NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
    narrative_semantic_evaluation_definition,
    scripted_qualification,
    validate_narrative_qualification,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    build_narrative_evaluation_pack_profile,
    build_story_planning_pack_profile,
)
from novel_forge.modules.provider_control import (
    OpenAIProviderAdapterV2,
    ProviderAdapterRegistry,
)
from novel_forge.modules.production_execution.contracts import ExecutionOutcome
from novel_forge.modules.production_execution.gateway import ProductionExecutionGateway
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import LATEST_MIGRATION_ID, run_migrations
from novel_forge.workers.book_followup_authority import (
    execute_book_followup_admission_claim,
    schedule_book_followup_admission_jobs,
)
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
from tests.integration.hierarchy_closure_postgres_support import (
    seed_ready_story_foundation,
)
from tests.integration.migration_window_postgres_support import (
    PRE_WORKFLOW_MIGRATION_ID,
    WORKFLOW_MIGRATION_ID,
    assert_database_at_migration,
    disposable_database_at_migration,
)
import tests.integration.authority_postgres_support as authority_postgres_support
import tests.integration.capability_pack_postgres_support as capability_pack_support


RELEASE_SHA = "e" * 40


@pytest.fixture()
def pre_workflow_migration_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_database_url = DATABASE_URL
    with disposable_database_at_migration(
        base_database_url,
        prefix="nf_core_functional_0103",
        target_migration_id=PRE_WORKFLOW_MIGRATION_ID,
    ) as database_url:
        monkeypatch.setattr(
            authority_postgres_support,
            "DATABASE_URL",
            database_url,
        )
        monkeypatch.setattr(
            capability_pack_support,
            "DATABASE_URL",
            database_url,
        )
        monkeypatch.setattr(
            capability_pack_support,
            "ensure_migrated",
            lambda: assert_database_at_migration(
                database_url,
                target_migration_id=PRE_WORKFLOW_MIGRATION_ID,
            ),
        )
        monkeypatch.setitem(globals(), "DATABASE_URL", database_url)
        yield database_url


class _MeasuredPlanningAndEvaluationTransport:
    def __init__(self) -> None:
        self.stages: list[str] = []
        self.idempotency_keys: set[str] = set()

    def execute(self, request):  # type: ignore[no-untyped-def]
        self.stages.append(request.stage)
        self.idempotency_keys.add(request.stable_idempotency_key)
        input_text = str(request.request_payload["input_text"])
        contract_offset = input_text.find("provider-task-view-v1")
        task_line_start = input_text.rfind("\n", 0, contract_offset) + 1
        task_offset = input_text.find("{", task_line_start, contract_offset)
        if request.stage != "narrative_semantic_evaluation":
            assert contract_offset >= 0 and task_offset >= 0
        result = (
            scripted_qualification("book_plan.generate")
            if request.stage == "narrative_semantic_evaluation"
            else planning_fixture_response(
                request.stage,
                json.JSONDecoder().raw_decode(input_text[task_offset:])[0],
            )
        )
        return {
            "outcome": "success",
            "request_sent": True,
            "provider_request_id": (
                f"provider-request:{request.stable_idempotency_key}"
            ),
            "completion_mode": "synchronous",
            "evidence": {
                "result": result,
                "usage": {"input_tokens": 200, "output_tokens": 80},
                "cost": {"amount": "0.01", "currency": "USD"},
                "request_hash": request.request_hash,
            },
        }

    def query(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("synchronous proof must not query")

    def cancel(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("completed proof must not cancel")

    def verify_callback(self, body, headers, *, secret):  # type: ignore[no-untyped-def]
        raise AssertionError("synchronous proof has no callback")


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
            WHERE name=%s AND definition_version=%s
            """,
            (definition["name"], definition["definition_version"]),
        )
        definition_hash = str(uow.cursor.fetchone()[0])
        uow.commit()
    profile = build_story_planning_pack_profile(
        Path(__file__).resolve().parents[2],
        operation_definition_hash=definition_hash,
        pack_id=harness.pack_id,
    )
    harness._base_manifest = profile.manifest
    harness._base_catalog = profile.artifact_catalog
    scope = harness.approval_scope(environments=("test",), runtime_profiles=("test",))
    scope["allowed_workflow_definition_refs"] = [profile.workflow_ref]
    pack = harness.register_compile_approve(
        "1.1.0",
        generation=1,
        approval_scope=scope,
        target_runtime_profile="test",
        proof_skill_ref=profile.agent_skill_ref,
    )
    harness.register_agents(pack.compiled)
    deployment = harness.deploy(pack, environment="test", runtime_profile="test")
    harness.activate(deployment, environment="test")
    return deployment.deployment_id


def _activate_narrative_evaluation_pack(
    *, project_id: str, workspace_id: str, book_id: str
) -> str:
    harness = CapabilityPackPostgresHarness(
        "planning-semantic-provider-proof",
        application_build_id=NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
        release_sha=RELEASE_SHA,
    )
    harness.project_id = project_id
    harness.workspace_id = workspace_id
    harness.book_ids = (book_id,)
    harness.compiler = harness.principal("compiler", *harness.compiler.permissions)
    harness.approver = harness.principal("approver", *harness.approver.permissions)
    harness.agent_admin = harness.principal(
        "agent-admin", *harness.agent_admin.permissions
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        registered = uow.repositories.definitions.register(
            narrative_semantic_evaluation_definition(
                application_build_id=NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
                commit_sha=RELEASE_SHA,
            )
        )
        uow.commit()
    profile = build_narrative_evaluation_pack_profile(
        Path(__file__).resolve().parents[2],
        operation_definition_hash=str(registered["definition_hash"]),
        pack_id=harness.pack_id,
    )
    harness._base_manifest = profile.manifest
    harness._base_catalog = profile.artifact_catalog
    harness.workflow_definition_ref = profile.workflow_ref
    approval_scope = harness.approval_scope(
        environments=("test",),
        runtime_profiles=("test",),
        project_ids=(project_id,),
        workspace_ids=(workspace_id,),
        book_ids=(book_id,),
    )
    pack = harness.register_compile_approve(
        "1.0.0",
        generation=1,
        approval_scope=approval_scope,
        proof_skill_ref=profile.agent_skill_ref,
        release_sha=RELEASE_SHA,
        target_runtime_profile="test",
    )
    deployment = harness.deploy(
        pack,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        environment="test",
        runtime_profile="test",
    )
    harness.activate(deployment, environment="test")
    return harness.pack_id


class _ExternalEffectPepFixturePlanningBinder:
    """Deterministic Candidate transport for the PostgreSQL Authority fixture."""

    production_execution_gateway_backed = True

    def __init__(self, *, target_chapter_count: int = 3) -> None:
        self.target_chapter_count = target_chapter_count

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
        payload = _planning_contract(
            command,
            operation_id=operation_id,
            inputs=inputs,
            target_chapter_count=self.target_chapter_count,
        )
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
                capability_execution_ref=f"capability-execution:{digest}",
                capability_execution_hash=digest,
                capability_runtime_binding_ref=f"runtime-binding:{digest}",
                capability_runtime_binding_hash=digest,
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
                "narrative_design.evaluate",
                "book.authority.execute",
                "book.authority.approve_replan",
                "book_design.authority.execute",
                "book_design.authority.query",
                "book.followup:*",
                "chapter.authority.execute",
                "external_effect.execute",
            }
        ),
        project_scope=frozenset({project_id}),
        authentication_source="postgres-functional-loop-fixture",
    )


def _planning_contract(
    command: StoryPlanningGenerationCommand,
    *,
    operation_id: str,
    inputs: tuple[FrozenPlanningInput, ...],
    target_chapter_count: int = 3,
) -> dict[str, Any]:
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
            "volume_skeleton": [
                {"volume": ordinal, "function": "commitment"}
                for ordinal in range(1, (target_chapter_count + 2) // 3 + 1)
            ],
            "major_turns": ["irreversible choice"],
            "climax_distribution": [1],
            "long_promise_payoff": ["central promise settled"],
            "length_strategy": {"target_chapters": target_chapter_count},
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
    if contract_type is PlanContractType.VOLUME and command.logical_key == "volume:2":
        payload["chapter_range"] = [4, 6]
    if contract_type is PlanContractType.CHAPTER:
        for contribution in payload["required_arc_contributions"]:
            contribution["arc_plan_version_id"] = command.input_versions["arc_plans"]
    if command.parent_version_id:
        payload["parent_version_id"] = command.parent_version_id
    payload.update(
        planning_fixture_response(
            command.generator_operation_name,
            {
                "planning_command": {
                    "project_id": command.project_id,
                    "book_id": command.book_id,
                    "generation_operation_id": operation_id,
                    "logical_key": command.logical_key,
                    "parent_version_id": command.parent_version_id,
                    "input_versions": dict(command.input_versions),
                    "arc_scope_volume_plan_version_ids": list(
                        command.arc_scope_volume_plan_version_ids
                    ),
                    "related_arc_plan_version_ids": list(
                        command.related_arc_plan_version_ids
                    ),
                    "narrative_search_id": command.narrative_search_id,
                    "narrative_search_branch_key": (
                        command.narrative_search_branch_key
                    ),
                    "narrative_search_accepted_through_chapter": (
                        command.narrative_search_accepted_through_chapter
                    ),
                    "narrative_search_strategy_directive": (
                        command.narrative_search_strategy_directive
                    ),
                    "narrative_search_planning_horizon": dict(
                        command.narrative_search_planning_horizon or {}
                    ),
                    "narrative_search_desired_transformation": dict(
                        command.narrative_search_desired_transformation or {}
                    ),
                    "narrative_search_hard_constraints": list(
                        command.narrative_search_hard_constraints
                    ),
                },
                "frozen_inputs": [
                    {
                        "role": item.role,
                        "asset_version_id": item.asset_version_id,
                        "content_hash": item.content_hash,
                        "asset_type": item.asset_type,
                    }
                    for item in inputs
                ],
            },
        )
    )
    assert set(TYPE_FIELDS[contract_type]).issubset(payload)
    return payload


def _chapter_function_row(chapter: int, function: str, hook: str) -> dict[str, Any]:
    return {
        "chapter_number": chapter,
        "primary_function": function,
        "secondary_functions": ["character pressure"],
        "required_state_delta": {"summary": "commitment advances"},
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc:primary", "kind": "advance"}
        ],
        "promise_action": "advance",
        "foreshadow_action": "plant",
        "reward_action": "partial payoff",
        "ending_hook": hook,
        "prohibited_outcomes": ["silent reset"],
        "narrative_density": (
            "HIGH" if function in {"reversal", "payoff"} else "MEDIUM"
        ),
        "reader_experience": {
            "target_emotion": (
                "costly relief" if function == "payoff" else "rising pressure"
            ),
            "reward_mode": "PAYOFF" if function == "payoff" else "DISCOVERY",
        },
        "arc_cadence": [
            {
                "arc_plan_version_id": "arc:primary",
                "action": "PAYOFF" if function == "payoff" else "ADVANCE",
            }
        ],
        "obligation_actions": [
            {
                "obligation_id": "promise:choice",
                "action": "PAYOFF" if function == "payoff" else "ADVANCE",
                "due_chapter": chapter if function == "payoff" else chapter + 2,
            }
        ],
    }


def _seed_inputs(
    project_id: str,
    book_id: str,
    *,
    target_chapter_count: int = 3,
    governance_action: tuple[str, str] | None = None,
    world_foundation: dict[str, Any] | None = None,
    world_production_policy: dict[str, Any] | None = None,
    initial_current_state: dict[str, Any] | None = None,
) -> dict[str, str]:
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
    canonical_foundation_roles = {
        "creative_foundation",
        "theme_contract",
        "ending_intent",
        "reader_promise",
        "world_bible",
        "character_cast",
        "book_design",
    }
    roles = [role for role in roles if role not in canonical_foundation_roles]
    result: dict[str, str] = {}
    with transaction() as connection, connection.cursor() as cursor:
        for role in roles:
            asset_id = f"fixture:{project_id}:{role}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": role, "facts": [role]}
            if role == "production_profile":
                content["profile_id"] = "controlled-planning-fixture"
                if world_production_policy is not None:
                    content["world_production_policy"] = dict(world_production_policy)
                content["target_chapter_count"] = target_chapter_count
                if governance_action is not None:
                    content["narrative_load_policy"] = {
                        "policy_id": "governed-load-policy",
                        "policy_version": 1,
                        "governed_overrides": [
                            {
                                "override_id": "override:active-arcs",
                                "project_id": project_id,
                                "book_id": book_id,
                                "scope_type": "BOOK",
                                "scope_key": book_id,
                                "limits": {"max_active_arcs": 5},
                                "governance_action_asset_version_id": (
                                    governance_action[0]
                                ),
                                "governance_action_content_hash": (
                                    governance_action[1]
                                ),
                            }
                        ],
                    }
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
            digest = canonical_hash(content)
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
        campaign_identity = canonical_hash(
            {"fixture": "core-functional-loop", "project_id": project_id}
        )
        story_state: dict[str, Any] = {
            "type": "StoryStateSnapshot",
            "contract_version": "story-state-snapshot-v2",
            "layer": "CURRENT_STATE",
            "project_id": project_id,
            "book_id": book_id,
            "scope": {"project_id": project_id, "book_id": book_id},
            "accepted_through_chapter": 0,
            "chapter": 0,
            "chapter_number": 0,
            "state_version": 0,
            "current_state": deepcopy(initial_current_state or {}),
            "reducer_applications": [],
            "accepted_state_only": True,
            "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
            "campaign_contract_identity": campaign_identity,
            "evidence_level": "CONTROLLED_INTEGRATION_FIXTURE",
        }
        story_state["state_hash"] = canonical_hash(story_state)
        canon: dict[str, Any] = {
            "type": "CanonSnapshot",
            "contract_version": "canon-snapshot-v2",
            "layer": "TRUTH",
            "project_id": project_id,
            "book_id": book_id,
            "scope": {"project_id": project_id, "book_id": book_id},
            "accepted_through_chapter": 0,
            "chapter": 0,
            "chapter_number": 0,
            "current_facts": [],
            "story_state_hash": story_state["state_hash"],
            "accepted_state_only": True,
            "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
            "campaign_contract_identity": campaign_identity,
            "evidence_level": "CONTROLLED_INTEGRATION_FIXTURE",
        }
        canon["canon_hash"] = canonical_hash(canon)
        for result_key, asset_type, content in (
            ("initial_story_state", "story_state_snapshot", story_state),
            ("initial_canon_snapshot", "canon_snapshot", canon),
        ):
            asset_id = f"fixture:{project_id}:{result_key}"
            version_id = f"{asset_id}:v1"
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
                    f"{asset_type}.v2",
                ],
            )
            result[result_key] = version_id
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s",
            [project_id, book_id],
        )
        workspace_id = str(cursor.fetchone()[0])
    formation_principal = Principal(
        principal_id=f"hierarchy-formation:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(
            {
                "story_design.authority.execute",
                "book.authority.execute",
                "book_design.authority.execute",
                "book_design.authority.query",
            }
        ),
        project_scope=frozenset({project_id}),
        authentication_source="controlled-core-loop-fixture",
    )
    hierarchy = seed_ready_story_foundation(
        DATABASE_URL,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        principal=formation_principal,
        target_chapters=target_chapter_count,
        release_sha=RELEASE_SHA,
        world_foundation=world_foundation,
    )
    result.update(hierarchy["asset_versions"])
    result["foundation_set_digest"] = hierarchy["foundation_set_digest"]
    result["story_formation_run"] = hierarchy["formation_run_id"]
    result["book_version"] = str(hierarchy["book_version"])
    return result


def _evolution_foundation_fixture() -> dict[str, object]:
    return {
        "schema_version": EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
        "title": "The Glass Harbor",
        "genre": "speculative mystery",
        "premise": "A cartographer proves the city edits its maps.",
        "theme": "collective truth",
        "core_conflict": "Witnesses challenge a self-editing archive.",
        "reader_promise": "Every discovery forces a costly public choice.",
        "ending": "The archive becomes publicly accountable.",
        "protagonist": {
            "name": "Mara",
            "external_goal": "Restore the missing district.",
            "internal_need": "Trust collaborators.",
            "flaw": "Treats uncertainty as failure.",
            "arc": "Solitary certainty becomes accountable collaboration.",
        },
        "world_rules": ["Witnessed places resist erasure."],
        "target_chapters": 90,
        "core_characters": [
            {
                "character_id": "mara",
                "role": "protagonist",
                "long_term_goal": "Restore the district.",
                "causal_arc": "Isolation becomes collaboration.",
                "conflict_function": "Certainty delays collective action.",
            }
        ],
        "opposition_forces": [
            {
                "force_id": "archive",
                "goal": "Control memory.",
                "leverage": "Rewrite maps.",
                "escalation_pattern": "Denial becomes erasure.",
                "limit": "Witnesses delay erasure.",
            }
        ],
        "narrative_dna": {
            "core_question": "Who owns truth?",
            "recurring_choice": "Certainty or disclosure.",
            "cost_logic": "Every fact exposes a witness.",
            "distinctive_mechanism": "Maps change physical access.",
            "emotional_contract": "Discovery brings hope and public cost.",
        },
        "creative_foundation": {
            "target_reader": "mystery readers who value consequential choices",
            "why_worth_writing": "public truth has a personal cost",
            "subgenre": "institutional speculative mystery",
            "core_desire": "recover erased belonging",
            "core_fear": "certainty will isolate Mara",
            "narrative_engine": "each anomaly forces disclosure or concealment",
            "differentiation": "geography changes through accountable choices",
            "emotional_contract": "wonder converts into shared responsibility",
            "serialization_potential": "districts reveal distinct bargains",
            "thematic_question": "Can public truth remain humane?",
            "ending_direction": "collective custody replaces solitary control",
        },
        "world_system": [
            {
                "rule_id": "witness-delay",
                "rule": "Witnessed places resist erasure.",
                "cost": "The witness becomes publicly exposed.",
                "exception": "A witness may recant.",
                "consequence": "Access remains open for seven days.",
                "conflict_potential": "The archive pressures witnesses.",
                "narrative_function": "Turn knowledge into costly agency.",
            }
        ],
        "character_system": [
            {
                "character_id": "mara",
                "name": "Mara",
                "role": "protagonist",
                "desire": "restore the district",
                "need": "share uncertain evidence",
                "fear": "causing another erasure",
                "wound": "a failed solitary proof",
                "false_belief": "only certainty protects people",
                "values": "truth and care",
                "moral_boundary": "never fabricate a witness",
                "agency": "chooses what to disclose",
                "capability": "reads archival topology",
                "weakness": "withholds uncertainty",
                "voice": "precise until emotionally cornered",
                "secret": "her first map caused harm",
                "relationship_function": "must learn accountable trust",
                "arc_direction": "certainty becomes collective responsibility",
            }
        ],
    }


def _seed_fixture_book_design_qualification(
    project_id: str, book_id: str, book_design_version_id: str
) -> None:
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operation.operation_id, attempt.attempt_id,
                   output.asset_version_id
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
             AND attempt.status='SUCCEEDED'
            JOIN authority_operation_output_asset AS output
              ON output.operation_id=operation.operation_id
            WHERE operation.project_id=%s AND operation.status='SUCCEEDED'
            ORDER BY operation.updated_at DESC
            LIMIT 1
            """,
            [project_id],
        )
        evaluation_operation_id, evaluation_attempt_id, evaluation_asset_id = (
            str(item) for item in cursor.fetchone()
        )
        cursor.execute(
            """
            SELECT operation_id
            FROM authority_operation
            WHERE project_id=%s AND status='SUCCEEDED'
              AND operation_id<>%s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            [project_id, evaluation_operation_id],
        )
        generation_operation_id = str(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT content_hash FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [book_design_version_id],
        )
        book_design_content_hash = str(cursor.fetchone()[0])
        qualification = validate_narrative_qualification(
            generator_operation_name="book_design.propose",
            value=scripted_qualification("book_design.propose"),
        )
        for receipt in qualification.receipts:
            qualification_id = canonical_hash(
                {
                    "asset_version_id": book_design_version_id,
                    "design_layer": receipt.layer.value,
                    "profile_hash": receipt.profile_hash,
                    "evaluation_hash": receipt.evaluation_hash,
                }
            )
            cursor.execute(
                """
                INSERT INTO authority_narrative_design_qualification(
                    qualification_id, project_id, book_id,
                    asset_version_id, source_operation_id,
                    candidate_content_hash, design_layer, profile_id,
                    profile_version, profile_hash, capability_id, skill_ref,
                    evaluator_execution_class, qualification_status,
                    evaluation, evaluation_hash, qualification_hash,
                    generation_operation_id, evaluation_operation_id,
                    evaluation_attempt_id, evaluation_asset_version_id,
                    evaluation_evidence_hash, trust_boundary
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, 'SCRIPTED_FIXTURE', 'PASS', %s, %s, %s,
                    %s, %s, %s, %s, %s, 'INDEPENDENT'
                )
                """,
                [
                    qualification_id,
                    project_id,
                    book_id,
                    book_design_version_id,
                    evaluation_operation_id,
                    book_design_content_hash,
                    receipt.layer.value,
                    receipt.profile_id,
                    receipt.profile_version,
                    receipt.profile_hash,
                    receipt.capability_id,
                    receipt.skill_ref,
                    Jsonb(receipt.evidence),
                    receipt.evaluation_hash,
                    qualification.qualification_hash,
                    generation_operation_id,
                    evaluation_operation_id,
                    evaluation_attempt_id,
                    evaluation_asset_id,
                    canonical_hash(
                        {
                            "fixture_protocol_only": True,
                            "evaluation_operation_id": evaluation_operation_id,
                            "candidate_asset_version_id": book_design_version_id,
                        }
                    ),
                ],
            )


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
    snapshot = PostgresBookProductionQuery(
        DATABASE_URL
    ).require_accepted_followup_snapshot(chapter_request_id=chapter_request_id)
    reader = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_request_id,
        followup_type="READER_OUTCOME",
        output_key="reader_outcome.report",
    )
    authority_inputs = authority.resolve_asset_refs(
        project_id=project_id,
        asset_version_ids=(
            str(snapshot["book_design_version"]),
            str(snapshot["book_plan_version"]),
            str(snapshot["volume_plan_version"]),
            *(str(item) for item in snapshot["arc_plan_versions"]),
            str(snapshot["quality_trend_version"]),
            str(snapshot["accepted_chapter_outcome_version"]),
            str(snapshot["accepted_story_state_version"]),
            str(snapshot["accepted_canon_snapshot_version"]),
        ),
    )

    admission = authority.schedule_longform_recap(
        chapter_request_id,
        principal=principal,
        payload={
            "book_id": snapshot["book_id"],
            "checkpoint_type": LongformCheckpointType.BOOK_AUTHORITY_REQUEST.value,
            "chapter_range": [1, int(request["chapter_number"])],
            "observed_through_chapter": int(snapshot["observed_through_chapter"]),
            "acceptance_operation_id": snapshot["acceptance_operation_id"],
            "book_production_input_snapshot_id": snapshot[
                "book_production_input_snapshot_id"
            ],
            "book_design_version": snapshot["book_design_version"],
            "book_plan_version": snapshot["book_plan_version"],
            "volume_plan_version": snapshot["volume_plan_version"],
            "arc_plan_versions": list(snapshot["arc_plan_versions"]),
            "canon_snapshot_version": snapshot["accepted_canon_snapshot_version"],
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": snapshot["quality_trend_version"],
            "chapter_outcome_versions": [snapshot["accepted_chapter_outcome_version"]],
            "story_state_version": snapshot["accepted_story_state_version"],
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
    ContentAuthorityScheduler(
        DATABASE_URL,
        registry=authority.followup.registry,
        worker_id="canonical-book-followup-worker",
    ).run_or_recover(operation_id=admission.operation_id, project_id=project_id)
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
    multi_volume_arc: bool = False,
) -> dict[str, str]:
    activated: dict[str, str] = {}
    parent = ""
    sequence = (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
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
            "book_plan.generate": (
                "book:main:portfolio-2" if multi_volume_arc else "book:main"
            ),
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
            parent_version_id="" if generator == "arc_plan.generate" else parent,
            arc_scope_volume_plan_version_ids=(
                (activated["volume_plan.generate:secondary"],)
                if generator == "arc_plan.generate" and multi_volume_arc
                else ()
            ),
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
        if generator == "volume_plan.generate" and multi_volume_arc:
            secondary_command = StoryPlanningGenerationCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                generator_operation_name=generator,
                logical_key="volume:2",
                input_versions={
                    role: (
                        activated["book_plan.generate"]
                        if role == "book_plan"
                        else generic[role]
                    )
                    for role in GENERATOR_INPUT_ROLES[generator]
                },
                parent_version_id=activated["book_plan.generate"],
                idempotency_key=f"{project_id}:{generator}:secondary",
                trace_id=f"trace:{generator}:secondary",
                correlation_id=f"correlation:{project_id}",
            )
            secondary = application.generate(secondary_command, principal=principal)
            assert secondary.status is PlanningGenerationStatus.APPROVAL_PENDING
            application.approve_candidate(
                secondary.candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{secondary_command.idempotency_key}:approve",
                trace_id=secondary_command.trace_id,
                correlation_id=secondary_command.correlation_id,
            )
            application.activate_candidate(
                secondary.candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{secondary_command.idempotency_key}:activate",
                trace_id=secondary_command.trace_id,
                correlation_id=secondary_command.correlation_id,
            )
            activated["volume_plan.generate:secondary"] = (
                secondary.candidate_asset_version_id
            )
        if generator == "arc_plan.generate" and multi_volume_arc:
            future_command = StoryPlanningGenerationCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                generator_operation_name=generator,
                logical_key="arc:future",
                input_versions={
                    role: (
                        activated["book_plan.generate"]
                        if role == "book_plan"
                        else activated["volume_plan.generate:secondary"]
                        if role == "volume_plan"
                        else generic[role]
                    )
                    for role in GENERATOR_INPUT_ROLES[generator]
                },
                related_arc_plan_version_ids=(activated["arc_plan.generate"],),
                idempotency_key=f"{project_id}:{generator}:future",
                trace_id=f"trace:{generator}:future",
                correlation_id=f"correlation:{project_id}",
            )
            future = application.generate(future_command, principal=principal)
            assert future.status is PlanningGenerationStatus.APPROVAL_PENDING
            application.approve_candidate(
                future.candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{future_command.idempotency_key}:approve",
                trace_id=future_command.trace_id,
                correlation_id=future_command.correlation_id,
            )
            application.activate_candidate(
                future.candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{future_command.idempotency_key}:activate",
                trace_id=future_command.trace_id,
                correlation_id=future_command.correlation_id,
            )
            activated["arc_plan.generate:future"] = future.candidate_asset_version_id
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


@pytest.mark.parametrize(
    "autonomous_world",
    [
        False,
        True,
        pytest.param("causal_preparation", id="causal-preparation"),
        pytest.param("intra_chapter", id="intra-chapter"),
        *[
            pytest.param(value, id=value)
            for value in (
                "multi_preparation",
                "historical_disclosure",
                "process_recovery",
                "smoke_command",
                "on_camera_preparation",
                "on_camera_missing",
                "on_camera_observer_drift",
                "preparation_expiry",
                "reader_partial",
                "character_disclosure",
                "reader_misdirect",
                "mixed_disclosure",
                "withhold_disclosure",
                "intra_chapter_missing",
                "intra_chapter_cycle",
                "manual_director",
                "acceptance_recovery",
                "provider_recovery",
                "concurrent_workers",
                "perturbed_foundation",
                "creative_grounding",
                "creative_retained_original",
                "creative_process_memo",
                "creative_process_support",
                "creative_process_artifact",
                "creative_reject_plan",
                "creative_reject_dialogue",
                "creative_reject_deleted",
                "creative_reject_memo",
                "operator_plan_change",
                "long_novel_pilot",
            )
        ],
    ],
)
def test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres(
    request: pytest.FixtureRequest, autonomous_world: bool | str
) -> None:
    test_case = request.node
    harness = CapabilityPackPostgresHarness("narrative-evolution-opening")
    chapter_pack_id = ""
    if autonomous_world:
        from copy import copy

        chapter_pack = copy(harness)
        chapter_pack.pack_id = f"world-chapter-{uuid4().hex}"
        chapter_pack._base_manifest = deepcopy(harness._base_manifest)
        chapter_pack._base_catalog = deepcopy(harness._base_catalog)
        approved = chapter_pack.register_compile_approve(
            "1.0.0",
            generation=1,
            approval_scope=chapter_pack.approval_scope(
                environments=("test",), runtime_profiles=("test",)
            ),
            target_runtime_profile="test",
        )
        chapter_pack.register_agents(approved.compiled)
        deployed = chapter_pack.deploy(
            approved, environment="test", runtime_profile="test"
        )
        chapter_pack.activate(deployed, environment="test")
        chapter_pack_id = chapter_pack.pack_id
    _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    principal = _principal(project_id)
    evaluator = Principal(
        principal_id=f"foundation-evaluator:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"narrative_design.evaluate"}),
        project_scope=frozenset({project_id}),
        authentication_source="postgres-foundation-evaluator-fixture",
    )
    design = BookDesignAuthorityApplication(
        DATABASE_URL,
        application_build_id="narrative-evolution-opening",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )

    def design_command(
        definition_name: str,
        *,
        payload: dict[str, object],
        target_asset_version_id: str = "",
    ) -> dict[str, Any]:
        return design.execute(
            BookDesignAuthorityCommand(
                definition_name=definition_name,
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                service_identity="narrative-evolution-opening-fixture",
                idempotency_key=f"{project_id}:{definition_name}",
                trace_id=f"trace:{project_id}:foundation",
                correlation_id=f"correlation:{project_id}",
                payload=payload,
                expected_book_version=1,
                target_asset_version_id=target_asset_version_id,
            ),
            principal=principal,
        )

    candidate = design_command(
        "book_design.propose", payload=_evolution_foundation_fixture()
    )
    qualification = design.evaluate_semantics(
        BookDesignSemanticEvaluationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=evaluator.principal_id,
            candidate_asset_version_id=str(candidate["asset_version_id"]),
            generation_operation_id=str(candidate["operation_id"]),
            generator_operation_name="book_design.propose",
            candidate_content_hash=str(candidate["content_hash"]),
            evaluator_execution_class="SCRIPTED_FIXTURE",
            evaluation=scripted_qualification("book_design.propose"),
            idempotency_key=f"{project_id}:book-design-evaluate",
            trace_id=f"trace:{project_id}:foundation-evaluate",
            correlation_id=f"correlation:{project_id}",
        ),
        principal=evaluator,
    )
    assert qualification["status"] == "VALIDATED"
    design_command(
        "book_design.decide",
        payload={"decision": "APPROVE", "reason": "qualified opening foundation"},
        target_asset_version_id=str(candidate["asset_version_id"]),
    )
    activated = design_command(
        "book_design.activate",
        payload={"reason": "selected opening foundation"},
        target_asset_version_id=str(candidate["asset_version_id"]),
    )
    assert set(activated["foundation_asset_versions"]) == {
        "creative_foundation",
        "world_bible",
        "character_cast",
        "character_arc_portfolio",
        "theme_contract",
        "ending_intent",
        "reader_promise",
    }

    from tests.integration.narrative_reality_vertical_support import (
        compiled_world_fixture,
    )

    approved_world = compiled_world_fixture()
    if autonomous_world == "perturbed_foundation":
        approved_world["entities"] = [
            {"entity_id": "faction:harbor", "kind": "FACTION"}
        ]
        approved_world["rules"][0]["rule_id"] = "harbor-pressure"
        approved_world["rules"][0]["predicate"].update(
            entity_key="world_state_id=harbor-pressure", value="RISING"
        )
    generic = _seed_inputs(
        project_id,
        book_id,
        target_chapter_count=180 if autonomous_world == "long_novel_pilot" else 6 if autonomous_world == "operator_plan_change" else 3,
        world_foundation=approved_world,
        world_production_policy={"planning_window_chapters": 2}
        if autonomous_world == "preparation_expiry"
        else None,
    )
    from tests.integration.test_postgresql_only_chapter_slice import (
        PostgreSQLOnlyChapterSliceTests,
    )

    PostgreSQLOnlyChapterSliceTests.release_evidence(project_id)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE authority_asset_version SET lifecycle='SUPERSEDED' WHERE asset_version_id=%s",
            [f"{project_id}:platform-profile-v1"],
        )
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'approval_decision')",
            [f"fixture:{project_id}:native-approval", project_id],
        )
        cursor.execute(
            "INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) SELECT %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',content,content_hash,'integration-fixture.v1' FROM authority_asset_version WHERE asset_version_id=%s",
            [
                f"fixture:{project_id}:native-approval:v1",
                f"fixture:{project_id}:native-approval",
                f"{project_id}:approval-v1",
            ],
        )
    with transaction() as connection, connection.cursor() as cursor:
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:opening:{asset_type}"
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
    opening_roles = {
        role
        for generator in (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
        )
        for role in GENERATOR_INPUT_ROLES[generator]
        if role not in {"book_plan", "volume_plan"}
    }
    planning_inputs = {
        role: (
            generic["initial_story_state"]
            if role == "story_state"
            else generic["initial_canon_snapshot"]
            if role == "canon_snapshot"
            else generic[role]
        )
        for role in opening_roles
    }

    with tempfile.TemporaryDirectory(prefix="narrative-evolution-opening-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "narrative-evolution-opening",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_MODEL": "scripted-planning-fixture",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
            "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": chapter_pack_id
            or "chapter_generation_pack",
        }
        from tests.integration.narrative_reality_vertical_support import (
            NativeRealityTransportFixture,
            execute_native_reality_vertical,
        )

        if autonomous_world:
            from tests.integration.world_causal_production_support import (
                AutonomousWorldTransport,
            )

            native_transport = AutonomousWorldTransport(
                scenario=autonomous_world
                if isinstance(autonomous_world, str)
                else "delayed_disclosure"
            )
        else:
            native_transport = NativeRealityTransportFixture()
        if autonomous_world in {"creative_grounding", "creative_retained_original"}:
            from tests.integration.creative_grounding_support import CreativeGroundingTransport
            native_transport = CreativeGroundingTransport(retain_original=autonomous_world == "creative_retained_original")
        if str(autonomous_world).startswith("creative_reject_"):
            from tests.integration.creative_grounding_support import CreativeGroundingTransport
            native_transport = CreativeGroundingTransport(negative=str(autonomous_world).removeprefix("creative_reject_"))
        if autonomous_world in {"operator_plan_change", "long_novel_pilot"}:
            from tests.integration.operator_plan_change_support import OperatorPlanChangeTransport
            native_transport = OperatorPlanChangeTransport(long_novel=autonomous_world == "long_novel_pilot")
        execution = build_production_execution_composition(
            settings,
            env=env,
            chapter_fixture_factory=native_transport,
            planning_fixture_factory=native_transport.planning,
        )
        chapter_application = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        composition = build_book_production_composition(
            settings,
            principal=principal,
            execution=execution,
            env=env,
            chapter_application=chapter_application,
            planning_post_provider_fault_injector=native_transport.post_provider_checkpoint
            if autonomous_world
            else None,
        )
        request = OpenBookProductionRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            expected_book_version=int(generic["book_version"]),
            production_profile=generic["production_profile"],
            planning_input_versions=planning_inputs,
            arc_logical_keys=("arc:central", "arc:relationship"),
            idempotency_key=f"{project_id}:open-book",
            trace_id=f"trace:{project_id}:open-book",
            correlation_id=f"correlation:{project_id}",
            initial_story_state_version=generic["initial_story_state"],
            initial_canon_snapshot_version=generic["initial_canon_snapshot"],
        )
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
        opening_trusted = SimpleNamespace(
            resolve_api_principal=lambda **_values: principal
        )
        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=opening_trusted,
            ),
            TestClient(authority_api) as opening_client,
        ):
            opening_response = opening_client.post(
                f"/product/production/book-authority/books/{book_id}/opening-runs",
                json={
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "expected_book_version": int(generic["book_version"]),
                    "production_profile": generic["production_profile"],
                    "planning_input_versions": planning_inputs,
                    "arc_logical_keys": ["arc:central", "arc:relationship"],
                    "initial_story_state_version": generic["initial_story_state"],
                    "initial_canon_snapshot_version": generic["initial_canon_snapshot"],
                    "idempotency_key": f"{project_id}:open-book",
                    "actor_id": principal.principal_id,
                    "trace_id": f"trace:{project_id}:open-book",
                    "correlation_id": f"correlation:{project_id}",
                },
            )
        assert opening_response.status_code == 202
        admission = SimpleNamespace(**opening_response.json())
        assert composition.opening is not None
        runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
        opening_claim = composition.opening.claim_next_execution(
            worker_id="opening-integration-worker",
            lease_seconds=30,
            project_id=project_id,
        )
        assert opening_claim is not None

        class RejectSeparateRuntimeCompletion:
            def __init__(self, delegate: RuntimeJobAuthority) -> None:
                self.delegate = delegate

            def __getattr__(self, name: str) -> object:
                return getattr(self.delegate, name)

            def complete(self, _claim: object, _result: object) -> None:
                raise AssertionError(
                    "Book Opening and RuntimeJob completion must share one UoW"
                )

        opened = execute_book_opening_claim(
            RejectSeparateRuntimeCompletion(runtime_jobs),  # type: ignore[arg-type]
            composition.opening,
            principal,
            opening_claim,
            lease_seconds=30,
        )
        assert (
            composition.opening.require(admission.opening_run_id)["lifecycle"]
            == "COMPLETE"
        )
        replay_claim = composition.opening.claim_next_execution(
            worker_id="opening-integration-recovery-worker",
            lease_seconds=30,
            project_id=project_id,
        )
        assert replay_claim is None
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT job.status,attempt.status,lease.status,
                       execution.lifecycle
                FROM authority_runtime_job AS job
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.lease_id=attempt.lease_id
                JOIN authority_book_opening_execution AS execution
                  ON execution.runtime_job_id=job.runtime_job_id
                WHERE job.runtime_job_id=%s
                """,
                [opening_claim.runtime_job_id],
            )
            assert uow.cursor.fetchone() == (
                "SUCCEEDED",
                "SUCCEEDED",
                "RELEASED",
                "SUCCEEDED",
            )
        replay = composition.open_book(request)
        opening_run = composition.opening.require(admission.opening_run_id)
        snapshot = composition.input_resolver.require(opened["input_snapshot_id"])
        opening_query_principal = Principal(
            principal_id=f"opening-query:{project_id}",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.query"}),
            project_scope=frozenset({project_id}),
            authentication_source="postgres-opening-query-fixture",
        )
        opening_query_trusted = SimpleNamespace(
            resolve_api_principal=lambda **_values: opening_query_principal
        )
        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=opening_query_trusted,
            ),
            TestClient(authority_api) as opening_client,
        ):
            opening_detail = opening_client.get(
                "/product/production/book-authority/opening-runs/"
                f"{admission.opening_run_id}"
            )
        assert opening_detail.status_code == 200
        assert opening_detail.json()["lifecycle"] == "COMPLETE"

        assert replay.replayed is True
        assert replay.opening_run_id == admission.opening_run_id
        assert replay.runtime_job_id == admission.runtime_job_id
        assert opening_run["lifecycle"] == "COMPLETE"
        opening_search_count = 6 if autonomous_world == "long_novel_pilot" else 5 if autonomous_world == "operator_plan_change" else 4
        assert len(opened["search_ids"]) == opening_search_count
        assert opened["book_design_version"] == generic["book_design"]
        assert snapshot.book_plan_version == opened["book_plan_version"]
        assert snapshot.current_volume_plan_version == opened["volume_plan_version"]
        assert set(snapshot.arc_portfolio_plan_versions) == set(
            opened["arc_plan_versions"]
        )
        assert snapshot.initial_story_state_version == (generic["initial_story_state"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(*) FILTER (WHERE status='ACTIVATED')
                FROM authority_story_narrative_search
                WHERE project_id=%s AND book_id=%s
                """,
                [project_id, book_id],
            )
            assert uow.cursor.fetchone() == (opening_search_count, opening_search_count)
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(*) FILTER (WHERE candidate.status='SELECTED')
                FROM authority_story_narrative_search_candidate AS candidate
                JOIN authority_story_narrative_search AS search
                  ON search.search_id=candidate.search_id
                WHERE search.project_id=%s AND search.book_id=%s
                """,
                [project_id, book_id],
            )
            assert uow.cursor.fetchone() == (opening_search_count * 3, opening_search_count)
            uow.cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(checkpoint.checkpoint_id),
                       COUNT(DISTINCT checkpoint.opening_execution_id),
                       BOOL_AND(
                           checkpoint.evidence_version=1
                           AND checkpoint.evidence_hash=candidate.branch_evidence_hash
                           AND checkpoint.semantic_work_key=(
                               'narrative-search-branch:' || candidate.search_id || ':' ||
                               candidate.branch_key
                           )
                           AND node.node_kind IN (
                               'BOOK_PLAN','VOLUME_PORTFOLIO','INITIAL_ARC_SCOPE'
                           )
                       )
                FROM authority_story_narrative_search_candidate AS candidate
                JOIN authority_story_narrative_search AS search
                  ON search.search_id=candidate.search_id
                LEFT JOIN authority_book_opening_semantic_checkpoint AS checkpoint
                  ON checkpoint.opening_run_id=%s
                 AND checkpoint.evidence_type='NARRATIVE_SEARCH_BRANCH'
                 AND checkpoint.evidence_id=candidate.membership_id
                LEFT JOIN authority_book_opening_workflow_node AS node
                  ON node.opening_run_id=checkpoint.opening_run_id
                 AND node.workflow_node_id=checkpoint.workflow_node_id
                WHERE search.project_id=%s AND search.book_id=%s
                """,
                [
                    admission.opening_run_id,
                    project_id,
                    book_id,
                ],
            )
            assert uow.cursor.fetchone() == (opening_search_count * 3, opening_search_count * 3, 3, True)
            uow.cursor.execute(
                """
                SELECT budget_contract_state,budget_scope_id,budget_scope_revision
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                """,
                [admission.opening_run_id],
            )
            budget_binding = uow.cursor.fetchone()
            assert budget_binding is not None
            assert budget_binding[0] == "BOUND"
            assert str(budget_binding[1]).startswith("budget-scope:")
            assert budget_binding[2] == 1

        if autonomous_world in {"operator_plan_change", "long_novel_pilot"}:
            from tests.integration.operator_plan_change_support import execute_operator_plan_change_vertical
            native_evidence = execute_operator_plan_change_vertical(
                composition=composition, chapter=chapter_application, snapshot=snapshot,
                settings=settings, authority_api=authority_api,
                book_target=180 if autonomous_world == "long_novel_pilot" else 6,
                pilot_cursor=6 if autonomous_world == "long_novel_pilot" else 0,
            )
            test_case.user_properties.append(("operator_plan_change_vertical", json.dumps(native_evidence, sort_keys=True)))
            execution.close()
            return

        if autonomous_world:
            from tests.integration.world_causal_production_support import (
                execute_autonomous_world_vertical,
                capture_world_execution_evidence,
            )

            try:
                native_evidence = execute_autonomous_world_vertical(
                    composition=composition,
                    chapter_application=chapter_application,
                    snapshot=snapshot,
                    generic=generic,
                    transport=native_transport,
                    runtime_config={"root": root, "env": env},
                )
            except KernelError as error:
                if not str(autonomous_world).startswith("creative_reject_"):
                    raise
                from tests.integration.creative_grounding_support import verify_rejected_creative
                native_evidence = verify_rejected_creative(composition=composition, chapter_application=chapter_application,
                    project_id=project_id, error=error, transport=native_transport)
            else:
                assert not str(autonomous_world).startswith("creative_reject_"), "unsupported facts must not be accepted"
            native_evidence["authority_evidence"] = capture_world_execution_evidence(
                composition=composition,
                project_id=project_id,
                book_run_id=native_evidence["book_run_id"],
            )
            if autonomous_world is True:
                from novel_forge.modules.story_planning_runtime.world_sampling import (
                    WorldProviderSampleCommand, prepare_world_sample, require_world_sample_source,
                )
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("""SELECT operation.operation_id,generation.book_id FROM authority_operation operation
                        JOIN authority_story_planning_generation generation USING(operation_id)
                        WHERE operation.project_id=%s AND operation.status='SUCCEEDED'
                          AND operation.command_payload#>>'{payload,generator_operation_name}'='chapter_plan.generate'
                        ORDER BY operation.created_at LIMIT 1""", [project_id])
                    world_origin, world_book = uow.cursor.fetchone()
                    uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [project_id])
                    effects_before = uow.cursor.fetchone()[0]
                operator = harness.principal("world-sample-fixture", "story_planning.authority.execute")
                prepared = prepare_world_sample(composition.planning, WorldProviderSampleCommand(
                    project_id, world_book, operator.principal_id, world_origin, "world_candidates.generate",
                    "fixture-unapproved-grant", "fixture-world-preflight"), principal=operator)
                assert prepared["provider_calls"] == 0 and prepared["production_eligible"] is False
                for world_stage in ("world_candidates.generate", "world_candidates.evaluate"):
                    frozen_world = require_world_sample_source(DATABASE_URL, project_id=project_id,
                        book_id=world_book, source_operation_id=world_origin, stage=world_stage)
                    assert frozen_world.context.content["world_preparation"] == frozen_world.stage.task
                    assert frozen_world.context.content["narrative_intelligence"]["selection_digest"] == frozen_world.stage.task["narrative_intelligence"]["selection_digest"]
                with pytest.raises(KernelError, match="WORLD_SAMPLE_SOURCE_INVALID"):
                    require_world_sample_source(DATABASE_URL, project_id=project_id, book_id="wrong-book",
                        source_operation_id=world_origin, stage="world_candidates.generate")
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [project_id])
                    assert uow.cursor.fetchone()[0] == effects_before
                from tests.integration.world_provider_sampling_support import exercise_world_generator_sample
                exercise_world_generator_sample(composition.planning, harness, book_id=world_book, source_operation_id=world_origin)
        else:
            native_evidence = execute_native_reality_vertical(
                composition=composition,
                chapter_application=chapter_application,
                snapshot=snapshot,
                generic=generic,
                transport=native_transport,
            )
        assert (
            native_evidence["proof_ceiling"]
            == "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY"
        )
        if autonomous_world in {"creative_grounding", "creative_retained_original"}:
            from tests.integration.creative_grounding_support import verify_creative_workspace
            native_evidence["creative_workspace"] = verify_creative_workspace(
                composition=composition, chapter_application=chapter_application,
                book_run_id=native_evidence["book_run_id"], transport=native_transport,
            )
        test_case.user_properties.append(
            ("narrative_reality_vertical", json.dumps(native_evidence, sort_keys=True))
        )
        execution.close()


def test_five_planning_generators_repair_activate_and_replay_in_postgres() -> None:
    ensure_migrated()
    suffix = uuid4().hex
    project_id = f"planning-project-{suffix}"
    workspace_id = f"planning-workspace-{suffix}"
    book_id = f"planning-book-{suffix}"
    seed_authority_project_book(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id
    )
    generic = _seed_inputs(project_id, book_id, target_chapter_count=6)
    principal = _principal(project_id)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(
            target_chapter_count=6
        ),
        application_build_id="core-functional-loop-fixture",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    activated = _activate_plan_chain(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        generic=generic,
        principal=principal,
        application=application,
        assert_replay=True,
        multi_volume_arc=True,
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
            ("VOLUME", "VOLUME_SPAN", 2),
            ("CHAPTER_GROUP", "PRIMARY", 1),
            ("CHAPTER_GROUP", "REQUIRED_CONTRIBUTION", 1),
            ("CHAPTER_GROUP", "CHECKPOINT_EXPECTATION", 1),
        }
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM story_plan_binding
            WHERE project_id=%s AND book_id=%s AND contract_type='CHAPTER'
            """,
            [project_id, book_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 0
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

    with pytest.raises(ValueError, match="Frozen Narrative Realization"):
        StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="chapter_plan.generate",
            logical_key="chapter:1:illegal-direct",
            input_versions={
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
                for role in GENERATOR_INPUT_ROLES["chapter_plan.generate"]
            },
            parent_version_id=activated["chapter_group_plan.generate"],
            idempotency_key=f"{project_id}:illegal-direct-chapter",
            trace_id=f"trace:{project_id}:illegal-direct-chapter",
            correlation_id=f"correlation:{project_id}",
        )
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


def test_narrative_search_persists_comparison_and_guards_activation() -> None:
    ensure_migrated()
    suffix = uuid4().hex
    project_id = f"narrative-search-project-{suffix}"
    workspace_id = f"narrative-search-workspace-{suffix}"
    book_id = f"narrative-search-book-{suffix}"
    seed_authority_project_book(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id
    )
    generic = _seed_inputs(project_id, book_id, target_chapter_count=6)
    principal = _principal(project_id)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(
            target_chapter_count=6
        ),
        application_build_id="narrative-search-postgres-fixture",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    search = PostgresNarrativeSearchApplication(DATABASE_URL, planning=application)
    command = StoryPlanningGenerationCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        actor_id=principal.principal_id,
        generator_operation_name="book_plan.generate",
        logical_key="book:searched-main",
        input_versions={
            role: generic[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        idempotency_key=f"{project_id}:book-search",
        trace_id=f"trace:{project_id}:book-search",
        correlation_id=f"correlation:{project_id}",
    )
    request = NarrativeSearchRequest(
        generation=command,
        planning_horizon={"level": "BOOK", "reach": "DISTANT"},
        desired_transformation={"ending_direction": "costly accountable agency"},
        hard_constraints=("preserve reader promise",),
        accepted_through_chapter=0,
    )

    result = search.explore(request, principal=principal, activate_selected=True)
    replay = search.explore(request, principal=principal, activate_selected=True)

    assert result.status.value == "ACTIVATED"
    assert len(result.candidate_asset_version_ids) == 3
    assert replay.search_id == result.search_id
    assert replay.candidate_asset_version_ids == result.candidate_asset_version_ids
    assert replay.replayed is True
    rejected = result.comparison.rejected_candidate_asset_version_ids[0]
    application.approve_candidate(
        rejected,
        principal=principal,
        idempotency_key=f"{command.idempotency_key}:approve-rejected-probe",
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )
    with pytest.raises(KernelError, match="NARRATIVE_SEARCH_SELECTION_REQUIRED"):
        application.activate_candidate(
            rejected,
            principal=principal,
            idempotency_key=f"{command.idempotency_key}:activate-rejected-probe",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT search.status, COUNT(candidate.membership_id),
                   COUNT(*) FILTER (WHERE candidate.status='SELECTED'),
                   COUNT(*) FILTER (WHERE candidate.status='REJECTED'),
                   COUNT(decision.decision_id)
            FROM authority_story_narrative_search AS search
            JOIN authority_story_narrative_search_candidate AS candidate
              ON candidate.search_id=search.search_id
            JOIN authority_story_narrative_search_decision AS decision
              ON decision.search_id=search.search_id
            WHERE search.search_id=%s
            GROUP BY search.status
            """,
            [result.search_id],
        )
        assert uow.cursor.fetchone() == ("ACTIVATED", 3, 1, 2, 3)


def test_planning_generation_freezes_typed_governance_action_in_canonical_input() -> (
    None
):
    ensure_migrated()
    suffix = uuid4().hex
    project_id = f"planning-governance-{suffix}"
    workspace_id = f"planning-governance-workspace-{suffix}"
    book_id = f"planning-governance-book-{suffix}"
    seed_authority_project_book(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id
    )
    action_id = f"governance-action:{suffix}:v1"
    action_content = {
        "project_id": project_id,
        "book_id": book_id,
        "action": "APPROVE_NARRATIVE_LOAD_OVERRIDE",
        "status": "APPROVED",
    }
    action_hash = canonical_hash(action_content)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'narrative_governance_action')",
            [f"governance-action:{suffix}", project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,
                      'narrative-governance-action.v1')
            """,
            [
                action_id,
                f"governance-action:{suffix}",
                Jsonb(action_content),
                action_hash,
            ],
        )
    generic = _seed_inputs(
        project_id,
        book_id,
        governance_action=(action_id, action_hash),
    )
    principal = _principal(project_id)
    application = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(),
        application_build_id="governed-planning-input-proof",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    inputs = {
        role: generic[role] for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
    }
    with pytest.raises(KernelError, match="GOVERNANCE_ACTION_UNBOUND"):
        application.generate(
            StoryPlanningGenerationCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                generator_operation_name="book_plan.generate",
                logical_key="book:governance-missing",
                input_versions=inputs,
                idempotency_key=f"{project_id}:governance-missing",
                trace_id="trace:governance-missing",
                correlation_id=f"correlation:{project_id}",
            ),
            principal=principal,
        )
    generated = application.generate(
        StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key="book:governance-bound",
            input_versions=inputs,
            governance_action_version_ids=(action_id,),
            idempotency_key=f"{project_id}:governance-bound",
            trace_id="trace:governance-bound",
            correlation_id=f"correlation:{project_id}",
        ),
        principal=principal,
    )
    assert generated.status is PlanningGenerationStatus.APPROVAL_PENDING
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [generated.candidate_asset_version_id],
        )
        frozen = dict(uow.cursor.fetchone()[0])["frozen_inputs"]
    assert any(
        item["role"] == "narrative_governance_action:1"
        and item["asset_version_id"] == action_id
        and item["content_hash"] == action_hash
        for item in frozen
    )


def test_production_composition_executes_upstream_planning_via_pep() -> None:
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
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
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

    assert set(activated) == {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
    }
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
        assert uow.cursor.fetchone() == (4, 4)
        uow.cursor.execute(
            """
            SELECT DISTINCT version.content->'contract'
            FROM authority_asset AS asset
            JOIN authority_asset_version AS version
              ON version.asset_id=asset.asset_id
            WHERE asset.project_id=%s
              AND asset.asset_type='model_profile'
              AND version.content->'contract'->>'profile_id'
                    LIKE 'planning.%%.default.sha256.%%'
            """,
            [harness.project_id],
        )
        profiles = [ModelProfile.from_dict(row[0]) for row in uow.cursor.fetchall()]
        assert len(profiles) == 4
        assert {(item.model_id, item.reasoning_effort) for item in profiles} == {
            ("scripted-planning-fixture", "xhigh")
        }
        for item in profiles:
            base_id, digest = item.profile_id.split(".sha256.")
            assert digest == replace(item, profile_id=base_id).contract_hash


def test_real_provider_planning_candidate_is_independently_evaluated_and_activated() -> (
    None
):
    harness = CapabilityPackPostgresHarness("planning-real-provider-evaluation")
    _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    evaluator_pack_id = _activate_narrative_evaluation_pack(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
    )
    generic = _seed_inputs(project_id, book_id)
    principal = _principal(project_id)
    transport = _MeasuredPlanningAndEvaluationTransport()
    registry = ProviderAdapterRegistry()
    registry.register(
        OpenAIProviderAdapterV2(
            transport,
            supports_query=False,
            supports_cancel=False,
            supports_callback=False,
            supports_cost_receipt=True,
            provider_idempotency_supported=True,
        )
    )
    with tempfile.TemporaryDirectory(prefix="planning-real-provider-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "planning-real-provider-evaluation",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "openai",
            "NOVEL_FORGE_PLANNING_PROVIDER": "openai",
            "NOVEL_FORGE_PLANNING_MODEL": "gpt-planning-proof",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "openai",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "gpt-evaluator-proof",
            "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": "xhigh",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
            "NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID": (evaluator_pack_id),
            "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": project_id,
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID": (
                "independent-planning-semantic-evaluator"
            ),
            "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
            "NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT": "131072",
            "NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD": (
                "OPENAI_UTF8_BYTES_UPPER_BOUND_V1"
            ),
            "NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF": (
                "test-proof:openai-byte-upper-bound:v1"
            ),
        }
        execution = build_production_execution_composition(
            settings, env=env, provider_registry=registry
        )
        application = build_story_planning_generation_application(
            settings, execution=execution, env=env
        )
        command = StoryPlanningGenerationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key="book:real-provider-proof",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key=f"{project_id}:book-plan:real-provider-proof",
            trace_id=f"trace:{project_id}:real-provider-proof",
            correlation_id=f"correlation:{project_id}",
        )
        generated = application.generate(command, principal=principal)
        assert generated.status is PlanningGenerationStatus.APPROVAL_PENDING
        assert transport.stages == [
            "book_plan.generate",
            "narrative_semantic_evaluation",
        ]
        application.approve_candidate(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{command.idempotency_key}:approve",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        activated = application.activate_candidate(
            generated.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{command.idempotency_key}:activate",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        replay = application.generate(command, principal=principal)

    assert activated["planning_binding"]["asset_version_id"] == (
        generated.candidate_asset_version_id
    )
    assert replay.status is PlanningGenerationStatus.ACTIVE
    assert len(transport.stages) == 2
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT evaluation_operation_id),
                   COUNT(DISTINCT evaluation_attempt_id),
                   COUNT(DISTINCT provider_model_call_asset_version_id),
                   BOOL_AND(evaluator_execution_class='MODEL_PROVIDER'),
                   BOOL_AND(trust_boundary='INDEPENDENT')
            FROM authority_narrative_design_qualification
            WHERE project_id=%s AND asset_version_id=%s
            """,
            [project_id, generated.candidate_asset_version_id],
        )
        proof = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT generation.actor_id, evaluation.actor_id,
                   version.lifecycle, version.eligibility
            FROM authority_narrative_design_qualification AS qualification
            JOIN authority_operation AS generation
              ON generation.operation_id=qualification.generation_operation_id
            JOIN authority_operation AS evaluation
              ON evaluation.operation_id=qualification.evaluation_operation_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=qualification.asset_version_id
            WHERE qualification.project_id=%s
              AND qualification.asset_version_id=%s
            LIMIT 1
            """,
            [project_id, generated.candidate_asset_version_id],
        )
        identities = uow.cursor.fetchone()
    assert proof == (1, 1, 1, True, True)
    assert identities[0] != identities[1]
    assert identities[2:] == ("ACTIVE", "ELIGIBLE")


@pytest.mark.parametrize(
    "failure_checkpoint",
    [
        "after_provider_receipt_before_budget_settlement",
        "after_measured_usage_before_candidate_acceptance",
    ],
    ids=[
        "receipt-to-settlement-frozen-profile-drift",
        "settlement-to-candidate",
    ],
)
def test_planning_retry_reuses_frozen_pack_after_provider_result(
    failure_checkpoint: str,
) -> None:
    harness = CapabilityPackPostgresHarness("planning-attempt-retry")
    baseline_deployment_id = _activate_planning_pack(harness)
    generic = _seed_inputs(harness.project_id, harness.book_ids[0])
    principal = _principal(harness.project_id)
    injected = {"done": False}

    def fail_once(checkpoint: str) -> None:
        if checkpoint == failure_checkpoint and not injected["done"]:
            injected["done"] = True
            raise KernelError(
                "MODEL_EFFECT_RETRYABLE_PLANNING_PROOF",
                "controlled proof failure after durable Provider success",
            )

    with tempfile.TemporaryDirectory(prefix="planning-attempt-retry-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
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

        replacement_scope = harness.approval_scope(
            environments=("test",), runtime_profiles=("test",)
        )
        replacement_scope["allowed_workflow_definition_refs"] = [
            STORY_PLANNING_WORKFLOW_DEFINITION_REF
        ]
        replacement_pack = harness.register_compile_approve(
            "1.2.0",
            generation=2,
            approval_scope=replacement_scope,
            target_runtime_profile="test",
            proof_skill_ref="long-outline",
        )
        replacement_deployment = harness.deploy(
            replacement_pack, environment="test", runtime_profile="test"
        )
        harness.activate(
            replacement_deployment,
            expected_activation_version=1,
            environment="test",
        )

        if failure_checkpoint == "after_provider_receipt_before_budget_settlement":
            # The durable Effect was sent under receipt-capable=true.  A later
            # process may expose a changed adapter profile; replay must account
            # the receipt using the Effect's first-send frozen profile.
            execution.gateway.capability_profile = replace(
                execution.gateway.capability_profile,
                supports_usage_receipt=False,
                supports_cost_receipt=False,
            )

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
            SELECT asset.asset_type, version.content->>'candidate_accepted',
                   version.content->>'provider_invoked_this_attempt',
                   version.content->>'recovered_external_effect_success'
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
            SELECT COUNT(*), COUNT(DISTINCT binding.asset_version_id),
                   COUNT(DISTINCT version.content_hash)
            FROM authority_operation_output_asset AS binding
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
            WHERE binding.operation_id=%s
              AND binding.output_key='planning.context_bundle'
            """,
            [result.generation_operation_id],
        )
        planning_context_identity = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT status
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [result.generation_operation_id],
        )
        operation_status = str(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT dispatch.dispatch_id),
                   array_agg(DISTINCT dispatch.generation ORDER BY dispatch.generation)
            FROM authority_external_effect AS effect
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            WHERE effect.operation_id=%s
              AND effect.effect_type='model.invoke'
            """,
            [result.generation_operation_id],
        )
        effect_count, dispatch_count, dispatch_generations = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT reservation.status,reservation.actual_tokens,
                   effect.provider_capability_profile->>'supports_usage_receipt'
            FROM authority_budget_reservation AS reservation
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id=reservation.external_effect_id
            WHERE reservation.operation_id=%s
            ORDER BY reservation.created_at DESC
            LIMIT 1
            """,
            [result.generation_operation_id],
        )
        reservation_proof = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT validation.status, validation.candidate_asset_version_id
            FROM authority_story_planning_validation_report AS validation
            WHERE validation.generation_operation_id=%s
            """,
            [result.generation_operation_id],
        )
        validation_rows = uow.cursor.fetchall()
    assert [(row[0], row[1]) for row in attempts] == [
        (1, "FAILED_RETRYABLE"),
        # The worker Attempt is terminal after its immutable Candidate is
        # materialized; Planning Authority approval gates the Candidate, not
        # the already-completed Provider Attempt.
        (2, "SUCCEEDED"),
    ]
    assert operation_status == "SUCCEEDED"
    assert attempts[0][2] != attempts[1][2]
    assert attempts[0][3] == attempts[1][3]
    assert attempts[0][4] == attempts[1][4] == "1.1.0"
    assert attempts[0][5] == attempts[1][5] == baseline_deployment_id
    assert attempts[1][5] != replacement_deployment.deployment_id
    if failure_checkpoint == "after_measured_usage_before_candidate_acceptance":
        assert evidence == [
            ("cost_ledger", "false", "true", "false"),
            ("model_call_log", "false", "true", "false"),
            ("model_call_log", "false", "false", "true"),
        ]
    else:
        assert evidence == [
            ("model_call_log", "false", "false", "true"),
        ]
    assert (effect_count, dispatch_count, dispatch_generations) == (1, 1, [1])
    assert reservation_proof == ("SETTLED", 0, "true")
    assert candidate_count == 1
    assert validation_rows
    assert {row[0] for row in validation_rows} == {"PASS"}
    assert {row[1] for row in validation_rows} == {result.candidate_asset_version_id}
    assert planning_context_identity == (1, 1, 1)


def test_planning_provider_timeout_retries_same_effect_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CapabilityPackPostgresHarness("planning-provider-timeout-retry")
    _activate_planning_pack(harness)
    generic = _seed_inputs(harness.project_id, harness.book_ids[0])
    principal = _principal(harness.project_id)
    original_reconcile = ProductionExecutionGateway.reconcile
    reconciliations = 0

    def timeout_once(self, handle):
        nonlocal reconciliations
        result = original_reconcile(self, handle)
        reconciliations += 1
        if reconciliations == 1:
            return replace(result, outcome=ExecutionOutcome.TIMED_OUT)
        return result

    monkeypatch.setattr(ProductionExecutionGateway, "reconcile", timeout_once)
    with tempfile.TemporaryDirectory(prefix="planning-provider-timeout-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "planning-provider-timeout-retry",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(settings, env=env)
        planning = build_story_planning_generation_application(
            settings, execution=execution, env=env
        )
        command = StoryPlanningGenerationCommand(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=harness.book_ids[0],
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key=f"{harness.book_ids[0]}:timeout-retry",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key=f"{harness.project_id}:timeout-retry",
            trace_id=f"trace:{harness.project_id}:timeout-retry",
            correlation_id=f"correlation:{harness.project_id}",
        )
        with pytest.raises(KernelError) as first:
            planning.generate(command, principal=principal)
        assert first.value.code == "MODEL_EFFECT_RETRYABLE_PLANNING"

        result = planning.generate(command, principal=principal)
        execution.close()

    assert result.status is PlanningGenerationStatus.APPROVAL_PENDING
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT effect.status, COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT dispatch.dispatch_id),
                   array_agg(dispatch.generation ORDER BY dispatch.generation),
                   effect.request_payload, effect.request_timeout_seconds
            FROM authority_external_effect AS effect
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            WHERE effect.operation_id=%s
            GROUP BY effect.status, effect.request_payload,
                     effect.request_timeout_seconds
            """,
            [result.generation_operation_id],
        )
        (
            effect_status,
            effect_count,
            dispatch_count,
            generations,
            effect_request,
            request_timeout_seconds,
        ) = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT COUNT(*) FROM authority_operation_output_asset
            WHERE operation_id=%s AND output_key='story_planning.candidate'
            """,
            [result.generation_operation_id],
        )
        candidate_count = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_asset
            WHERE project_id=%s
              AND asset_type='capability_materialization_manifest'
            """,
            [harness.project_id],
        )
        materialization_count = int(uow.cursor.fetchone()[0])
    assert reconciliations == 2
    assert (effect_status, effect_count, dispatch_count, generations) == (
        "SUCCEEDED",
        1,
        2,
        [1, 2],
    )
    capability_runtime = effect_request["_production_execution"]["capability_runtime"]
    assert capability_runtime["snapshot_hash"]
    assert capability_runtime["materialization_asset_version_id"]
    assert capability_runtime["materialization_content_hash"]
    assert capability_runtime["materialization_hash"]
    assert request_timeout_seconds == STORY_PLANNING_OPERATION_TIMEOUT_SECONDS
    assert materialization_count == 1
    assert candidate_count == 1


def test_non_book_planning_context_binds_book_authority_language_contract() -> None:
    harness = CapabilityPackPostgresHarness("planning-volume-language-contract")
    _activate_planning_pack(harness)
    book_id = harness.book_ids[0]
    generic = _seed_inputs(harness.project_id, book_id)
    principal = _principal(harness.project_id)
    language_contract = {
        "required_language": "zh-CN",
        "reader_facing_prose": "REQUIRED",
        "proof_gate": "PRIMARILY_REQUIRED_LANGUAGE",
    }
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE authority_book
            SET production_profile=%s
            WHERE project_id=%s AND book_id=%s
            """,
            [
                Jsonb({"language_contract": language_contract}),
                harness.project_id,
                book_id,
            ],
        )
    with tempfile.TemporaryDirectory(prefix="planning-volume-language-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "planning-volume-language-contract",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(settings, env=env)
        planning = build_story_planning_generation_application(
            settings, execution=execution, env=env
        )
        book_command = StoryPlanningGenerationCommand(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key="book:main",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key=f"{harness.project_id}:book-language-parent",
            trace_id=f"trace:{harness.project_id}:book-language-parent",
            correlation_id=f"correlation:{harness.project_id}",
        )
        book_plan = planning.generate(book_command, principal=principal)
        planning.approve_candidate(
            book_plan.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{harness.project_id}:book-language-parent:approve",
            trace_id=f"trace:{harness.project_id}:book-language-parent:approve",
            correlation_id=f"correlation:{harness.project_id}",
        )
        planning.activate_candidate(
            book_plan.candidate_asset_version_id,
            principal=principal,
            idempotency_key=f"{harness.project_id}:book-language-parent:activate",
            trace_id=f"trace:{harness.project_id}:book-language-parent:activate",
            correlation_id=f"correlation:{harness.project_id}",
        )
        command = StoryPlanningGenerationCommand(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            generator_operation_name="volume_plan.generate",
            logical_key="volume:1",
            input_versions={
                role: (
                    book_plan.candidate_asset_version_id
                    if role == "book_plan"
                    else generic[role]
                )
                for role in GENERATOR_INPUT_ROLES["volume_plan.generate"]
            },
            parent_version_id=book_plan.candidate_asset_version_id,
            idempotency_key=f"{harness.project_id}:volume-language",
            trace_id=f"trace:{harness.project_id}:volume-language",
            correlation_id=f"correlation:{harness.project_id}",
        )
        result = planning.generate(command, principal=principal)
        execution.close()

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT version.content
            FROM authority_operation_output_asset AS output
            JOIN authority_asset_version AS version
              ON version.asset_version_id=output.asset_version_id
            WHERE output.operation_id=%s
              AND output.output_key='planning.context_bundle'
            """,
            [result.generation_operation_id],
        )
        context = uow.cursor.fetchone()[0]

    assert result.status is PlanningGenerationStatus.APPROVAL_PENDING
    assert context["language_contract"] == language_contract


def test_planning_repeated_provider_timeout_exhausts_one_bounded_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CapabilityPackPostgresHarness("planning-provider-timeout-exhausted")
    _activate_planning_pack(harness)
    generic = _seed_inputs(harness.project_id, harness.book_ids[0])
    principal = _principal(harness.project_id)
    original_reconcile = ProductionExecutionGateway.reconcile

    def always_timeout(self, handle):
        return replace(
            original_reconcile(self, handle), outcome=ExecutionOutcome.TIMED_OUT
        )

    monkeypatch.setattr(ProductionExecutionGateway, "reconcile", always_timeout)
    with tempfile.TemporaryDirectory(prefix="planning-provider-exhausted-") as root:
        settings = IndustrialSettings(
            root=root,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "planning-provider-timeout-exhausted",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(settings, env=env)
        planning = build_story_planning_generation_application(
            settings, execution=execution, env=env
        )
        command = StoryPlanningGenerationCommand(
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            book_id=harness.book_ids[0],
            actor_id=principal.principal_id,
            generator_operation_name="book_plan.generate",
            logical_key=f"{harness.book_ids[0]}:timeout-exhausted",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            idempotency_key=f"{harness.project_id}:timeout-exhausted",
            trace_id=f"trace:{harness.project_id}:timeout-exhausted",
            correlation_id=f"correlation:{harness.project_id}",
        )
        errors: list[str] = []
        for _attempt in range(3):
            with pytest.raises(KernelError) as raised:
                planning.generate(command, principal=principal)
            errors.append(raised.value.code)
        execution.close()

    assert errors == [
        "MODEL_EFFECT_RETRYABLE_PLANNING",
        "MODEL_EFFECT_RETRYABLE_PLANNING",
        "MODEL_EFFECT_FINAL_PLANNING",
    ]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.status, effect.status,
                   COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT dispatch.dispatch_id),
                   array_agg(dispatch.generation ORDER BY dispatch.generation)
            FROM authority_operation AS operation
            JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            WHERE operation.project_id=%s
              AND operation.definition_name='story_planning.generate'
            GROUP BY operation.status, effect.status
            """,
            [harness.project_id],
        )
        status, effect_status, effect_count, dispatch_count, generations = (
            uow.cursor.fetchone()
        )
    assert (status, effect_status, effect_count, dispatch_count, generations) == (
        "FAILED_FINAL",
        "DEAD_LETTER",
        1,
        3,
        [1, 2, 3],
    )


def test_current_book_plan_portfolio_binds_six_production_effect_receipts() -> None:
    from tests.integration.narrative_reality_vertical_support import (
        NativeRealityTransportFixture,
        compiled_world_fixture,
    )

    harness = CapabilityPackPostgresHarness("book-plan-portfolio-production")
    _activate_planning_pack(harness)
    project_id = harness.project_id
    book_id = harness.book_ids[0]
    approved_world = compiled_world_fixture()
    for rule in approved_world["rules"]:
        rule.update(enforcement="SOFT_CAUSAL", predicate=None)
    generic = _seed_inputs(
        project_id, book_id, target_chapter_count=6, world_foundation=approved_world
    )
    principal = _principal(project_id)
    with tempfile.TemporaryDirectory(prefix="book-plan-portfolio-production-") as root:
        settings = IndustrialSettings(
            root=Path(__file__).resolve().parents[2],
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "core-functional-loop-fixture",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(
            settings, env=env,
            planning_fixture_factory=NativeRealityTransportFixture().planning,
        )
        try:
            chapter_application = build_chapter_authority_application(
                settings, execution=execution, env=env
            )
            composition = build_book_production_composition(
                settings, principal=principal, execution=execution,
                env=env, chapter_application=chapter_application,
            )
            activated = _activate_plan_chain(
                project_id=project_id,
                workspace_id=harness.workspace_id,
                book_id=book_id,
                generic=generic,
                principal=principal,
                application=composition.planning,
                multi_volume_arc=True,
            )
            assert len(activated) == 6
        finally:
            execution.close()
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT snapshot.attempt_id),
                   COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT generation.operation_id) FILTER (
                     WHERE version.content->'execution_evidence'->>'capability_pack_attempt_snapshot_id'
                           = snapshot.snapshot_id
                       AND COALESCE(version.content->'execution_evidence'->>'capability_execution_ref', '') <> ''
                   ),
                   COUNT(DISTINCT generation.operation_id) FILTER (
                     WHERE version.content->'execution_evidence'->>'external_receipt_ref'
                           = effect.external_effect_id
                   )
            FROM authority_story_planning_generation AS generation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=generation.operation_id
            JOIN authority_attempt_capability_pack_snapshot AS snapshot
              ON snapshot.attempt_id=attempt.attempt_id
            JOIN authority_external_effect AS effect
              ON effect.operation_id=generation.operation_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=generation.candidate_asset_version_id
            WHERE generation.project_id=%s
            """,
            [project_id],
        )
        assert uow.cursor.fetchone() == (6, 6, 6, 6)
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*)
                 FROM authority_agent_work_order AS work_order
                 JOIN authority_story_planning_generation AS generation
                   ON generation.operation_id=work_order.operation_id
                WHERE generation.project_id=%s),
              (SELECT COUNT(*)
                 FROM authority_agent_runtime_binding AS binding
                 JOIN authority_story_planning_generation AS generation
                   ON generation.operation_id=binding.operation_id
                WHERE generation.project_id=%s)
            """,
            [project_id, project_id],
        )
        assert uow.cursor.fetchone() == (0, 0)


@pytest.mark.parametrize(
    "runtime_path",
    (
        "READER_FAILURE_ISOLATION",
        "RECAP_FAILURE_ISOLATION",
        "EXPLICIT_REPLAN_APPROVAL",
    ),
)
def test_book_input_resolver_freezes_active_authorities_and_planning_pack(
    request: pytest.FixtureRequest,
    runtime_path: str,
    monkeypatch: pytest.MonkeyPatch,
    pre_workflow_migration_database: str,
) -> None:
    harness = CapabilityPackPostgresHarness("book-input-resolver")
    deployment_id = _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    from tests.integration.narrative_reality_vertical_support import compiled_world_fixture, NativeRealityTransportFixture
    approved_world = compiled_world_fixture()
    for rule in approved_world["rules"]:
        rule.update(enforcement="SOFT_CAUSAL", predicate=None)
    generic = _seed_inputs(
        project_id,
        book_id,
        target_chapter_count=6,
        world_foundation=approved_world,
        world_production_policy={"context_token_budget": 16000},
    )
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
        "NOVEL_FORGE_ENVIRONMENT": "test",
        "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "core-functional-loop-fixture",
        "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": object_store.name,
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": "core-functional-loop-worker",
        "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
    }
    causal_observation = {}
    causal_fixture_calls = []
    causal_obligation = {}
    causal_payoff = {}

    def causal_chapter_fixture(stage, inputs):
        from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
        result = default_chapter_fixture_response(stage, inputs)
        source = inputs.get({"draft": "plan", "revision": "draft", "canon_extraction": "revision"}.get(stage, "")) or {}
        causal_fixture_calls.append((stage, list(inputs), source.get("chapter"), bool(causal_observation)))
        if causal_observation and int(source.get("chapter") or 0) == 2:
            prose = "The council orders an inquiry."
            if stage in {"draft", "revision"}:
                result["text"] += " " + prose
                if result.get("scene_artifacts"):
                    result["scene_artifacts"][-1]["text"] += " " + prose
            if stage == "canon_extraction":
                start = source["text"].index(prose)
                result["world_state_changes"] = [{
                    "world_state_id": "council-alert", "status": "ALERT",
                    "summary": prose, "confidence": 1.0, "evidence_start": start, "evidence_end": start + len(prose),
                    "world_transition": {"payload_json": json.dumps(causal_observation)},
                }]
                result["obligation_changes"] = [{**causal_obligation, "status": "OPEN", "from_status": None, "payoff_evidence": None, "summary": prose, "confidence": 1.0, "evidence_start": start, "evidence_end": start + len(prose)}]
        if causal_payoff and int(source.get("chapter") or 0) == 3:
            prose = "The accepted inquiry permits a public hearing."
            if stage in {"draft", "revision"}:
                result["text"] += " " + prose
                if result.get("scene_artifacts"):
                    result["scene_artifacts"][-1]["text"] += " " + prose
            if stage == "canon_extraction":
                start = source["text"].index(prose)
                result["obligation_changes"] = [{**causal_obligation, "status": "FULFILLED", "from_status": "OPEN", "payoff_evidence": causal_payoff, "summary": prose, "confidence": 1.0, "evidence_start": start, "evidence_end": start + len(prose)}]
        from tests.integration.narrative_reality_vertical_support import scripted_claim_evidence
        return scripted_claim_evidence(stage, inputs, result)

    production_execution = build_production_execution_composition(
        settings, env=runtime_env, chapter_fixture_factory=causal_chapter_fixture, planning_fixture_factory=NativeRealityTransportFixture().planning
    )
    chapter_application = build_chapter_authority_application(
        settings, execution=production_execution, env=runtime_env
    )
    worker_production_executions = []

    def build_worker_runtime():
        worker_execution = build_production_execution_composition(
            settings, env=runtime_env, chapter_fixture_factory=causal_chapter_fixture, planning_fixture_factory=NativeRealityTransportFixture().planning
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
    migration_fixture_planning = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(
            target_chapter_count=6
        ),
        application_build_id="core-functional-loop-migration-fixture",
        commit_sha=RELEASE_SHA,
        allow_scripted_evaluation_fixture=True,
    )
    activated = _activate_plan_chain(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        generic=generic,
        principal=principal,
        application=migration_fixture_planning,
        multi_volume_arc=True,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT asset_version_id,
                   content->'execution_evidence'->'fixture_protocol_only'
            FROM authority_asset_version WHERE asset_version_id=ANY(%s)
            """,
            [list(activated.values())],
        )
        assert dict(uow.cursor.fetchall()) == {
            version_id: True for version_id in activated.values()
        }
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
        role_asset_version_overrides=(
            ("initial_story_state_version", generic["initial_story_state"]),
            ("initial_canon_snapshot_version", generic["initial_canon_snapshot"]),
        ),
    )
    snapshot = resolver.resolve(command, principal=principal)
    replay = resolver.resolve(command, principal=principal)
    assert snapshot.snapshot_id == replay.snapshot_id
    assert snapshot.book_plan_version == activated["book_plan.generate"]
    assert snapshot.narrative_chapter_cursor == 1
    assert snapshot.current_volume_plan_version == activated["volume_plan.generate"]
    assert snapshot.volume_portfolio_plan_versions == (
        activated["volume_plan.generate"],
        activated["volume_plan.generate:secondary"],
    )
    assert snapshot.arc_portfolio_plan_versions == (
        activated["arc_plan.generate"],
        activated["arc_plan.generate:future"],
    )
    assert snapshot.active_arc_plan_versions == (activated["arc_plan.generate"],)
    next_volume_projection = composition.query.require_cursor_plan_projection(
        snapshot_id=snapshot.snapshot_id,
        chapter_cursor=4,
    )
    assert next_volume_projection == {
        "chapter_cursor": 4,
        "volume_plan_version": activated["volume_plan.generate:secondary"],
        "volume_chapter_range": (4, 6),
        "arc_plan_versions": (
            activated["arc_plan.generate"],
            activated["arc_plan.generate:future"],
        ),
    }
    assert composition.replan._arc_regeneration_order(
        project_id=project_id,
        book_id=book_id,
        portfolio_arc_plan_version_ids=snapshot.arc_portfolio_plan_versions,
        initially_impacted_arc_plan_version_ids={activated["arc_plan.generate"]},
    ) == (
        activated["arc_plan.generate"],
        activated["arc_plan.generate:future"],
    )
    assert composition.replan._related_arc_versions(
        project_id=project_id,
        book_id=book_id,
        dependent_arc_plan_version_id=activated["arc_plan.generate:future"],
    ) == (activated["arc_plan.generate"],)
    assert (
        snapshot.current_chapter_group_plan_version
        == activated["chapter_group_plan.generate"]
    )
    assert snapshot.design_admission_status == "LONGFORM_DESIGN_QUALIFIED"
    assert snapshot.design_qualification["admission"] == ("LONGFORM_DESIGN_QUALIFIED")
    assert snapshot.design_qualification_hash == canonical_hash(
        snapshot.design_qualification
    )
    assert deployment_id in snapshot.capability_pack_deployment_refs
    with pytest.raises(psycopg.errors.CheckViolation):
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_book_production_input_snapshot SET release_sha=%s WHERE snapshot_id=%s",
                ["f" * 40, snapshot.snapshot_id],
            )

    assert_database_at_migration(
        pre_workflow_migration_database,
        target_migration_id=PRE_WORKFLOW_MIGRATION_ID,
    )
    migration_status = run_migrations(pre_workflow_migration_database)
    assert migration_status["ok"] is True
    assert migration_status["current"] == LATEST_MIGRATION_ID
    assert WORKFLOW_MIGRATION_ID in {
        item["migration_id"] for item in migration_status["applied"]
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT project_id,workspace_id,book_id,snapshot_hash,
                   source_migration_id
            FROM authority_book_opening_legacy_snapshot_entitlement
            WHERE snapshot_id=%s
            """,
            [snapshot.snapshot_id],
        )
        assert uow.cursor.fetchone() == (
            project_id,
            workspace_id,
            book_id,
            snapshot.snapshot_hash,
            WORKFLOW_MIGRATION_ID,
        )

    if runtime_path == "RECAP_FAILURE_ISOLATION":
        from novel_forge.modules.chapter_group_authority.policy import (
            ChapterGroupExecutionPolicy,
            PostgresChapterGroupExecutionPolicyAuthority,
        )

        policy_authority = PostgresChapterGroupExecutionPolicyAuthority(
            DATABASE_URL,
            application_build_id="core-functional-loop-fixture",
            commit_sha=RELEASE_SHA,
        )
        policy_command = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "principal": principal,
            "policy": ChapterGroupExecutionPolicy("recap-isolation-v1", 1, 1),
            "idempotency_key": f"{project_id}:recap-isolation-policy",
            "trace_id": f"trace:{project_id}:recap-isolation-policy",
            "correlation_id": f"correlation:{project_id}",
        }
        configured = policy_authority.configure(**policy_command)
        replayed = policy_authority.configure(**policy_command)
        assert configured["operation_id"] == replayed["operation_id"]
        assert replayed["replayed"] is True

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
            "target_chapter_count": 6,
            "light_recap_cadence": (
                1 if runtime_path == "RECAP_FAILURE_ISOLATION" else 5
            ),
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
    editorial_decisions = []
    control_mode = {"READER_FAILURE_ISOLATION": "REVIEW_REALITY_COMMIT", "RECAP_FAILURE_ISOLATION": "REVIEW_PLAN", "EXPLICIT_REPLAN_APPROVAL": "MANUAL_DIRECTOR"}[runtime_path]

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
        if claim is None:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT report FROM authority_story_planning_validation_report WHERE project_id=%s AND status='FAIL'", [project_id])
                failures = [row[0] for row in uow.cursor.fetchall()]
            raise AssertionError({"state": runtime.authority.require(book.book_run_id)["state"], "planning_failures": failures})
        result = execute_book_coordination_claim(runtime_jobs, runtime, claim)
        if result["action"] == "WAIT_CONTROL_DECISION":
            readiness = api_get(f"/product/production/book-authority/runs/{book.book_run_id}/control-readiness")
            assert readiness.status_code == 200, readiness.text
            gate = next(item for item in readiness.json()["gates"] if item["status"] == "WAITING_OPERATOR")
            from novel_forge.modules.book_authority.control_policy import ControlPolicy
            assert ControlPolicy(mode=control_mode).requires(gate["boundary"])
            assert runtime.query.narrative_reality(book_run_id=book.book_run_id)["chapter_number"] == readiness.json()["accepted_through_chapter"]
            arguments = dict(project_id=project_id, book_run_id=book.book_run_id, chapter_number=readiness.json()["chapter_number"], boundary=gate["boundary"], subject_version_id=gate["subject_version_id"], decision="APPROVE", reason="Fixture operator decision verifies the approval protocol only", idempotency_key=f"{project_id}:editorial:{readiness.json()['chapter_number']}:{gate['boundary']}:{gate['subject_version_id']}", trace_id=f"trace:{project_id}:editorial", correlation_id=f"correlation:{project_id}")
            with pytest.raises(PermissionError):
                runtime.controls.decide(principal=worker_principal, **arguments)
            if not editorial_decisions:
                with pytest.raises(ProcessLoss):
                    runtime.controls.decide(principal=principal, fault_injector=lose_at("after_editorial_decision"), **arguments)
            response = api_post(f"/product/production/book-authority/runs/{book.book_run_id}/control-decisions", {"actor_id": principal.principal_id, **{key: value for key, value in arguments.items() if key != "book_run_id"}})
            assert response.status_code == 200, response.text
            replay = runtime.controls.decide(principal=principal, **arguments)
            assert replay["replayed"] is True
            assert {key: value for key, value in replay.items() if key != "replayed"} == {key: value for key, value in response.json().items() if key != "replayed"}
            editorial_decisions.append(response.json())
        if result["action"] == "ACCEPT_CHAPTER" and causal_observation and book_authority.require(book.book_run_id)["accepted_through_chapter"] == 2:
            reality = runtime.query.narrative_reality(book_run_id=book.book_run_id)
            world = next(item for item in reality["current_state"]["world_state"] if item["entity_key"] == "world_state_id=council-alert")
            causal_payoff.update(asset_version_id=world["provenance"]["accepted_draft_asset_version_id"], event_id=world["source_event_id"])
        return result

    followup_runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
    followup_coordinator = PostgresBookFollowupCoordinator(
        book_authority,
        query=composition.query,
        principal=principal,
    )
    followup_scheduler = ContentAuthorityScheduler(
        DATABASE_URL,
        registry=book_authority.followup.registry,
        worker_id="canonical-book-followup-worker",
    )

    def followup_admission_tick() -> dict[str, object] | None:
        schedule_book_followup_admission_jobs(
            followup_coordinator,
            followup_runtime_jobs,
            limit=4,
        )
        claim = followup_runtime_jobs.claim(
            runtime_group="book_followup",
            worker_id="canonical-book-followup-worker",
            lease_seconds=30,
            job_kinds=("BOOK_FOLLOWUP_ADMISSION",),
            project_id=project_id,
        )
        if claim is None:
            return None
        return execute_book_followup_admission_claim(
            followup_coordinator,
            followup_runtime_jobs,
            claim,
            lease_seconds=30,
        )

    def followup_worker_tick() -> tuple[str, ...]:
        actions: list[str] = []
        result = followup_admission_tick()
        if result is not None:
            actions.append(str(result["action"]))
        for operation_id, operation_project_id in followup_scheduler.pending_operations(
            limit=4
        ):
            if operation_project_id != project_id:
                continue
            followup_scheduler.run_or_recover(
                operation_id=operation_id,
                project_id=operation_project_id,
            )
            actions.append("EXECUTE_FOLLOWUP_OPERATION")
        return tuple(actions)

    def run_chapter(chapter_runtime, root_operation_id: str) -> None:
        scheduler = chapter_runtime.scheduler(principal=worker_principal)
        # One Chapter execution may include the single bounded Quality correction
        # generation in addition to the primary node graph.
        for _ in range(len(ChapterNode) * 2 + 4):
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

    reality_response = api_get(f"/product/production/book-authority/runs/{book.book_run_id}/reality")
    assert reality_response.status_code == 200, reality_response.text
    reality_one = reality_response.json()
    assert reality_one["chapter_number"] == 1
    assert reality_one["parent_revision_id"] == ""
    from novel_forge.modules.book_authority.control_policy import ControlPolicy
    composition.controls.configure(project_id=project_id, workspace_id=workspace_id, policy=ControlPolicy(policy_version="fixture-editorial-mode-v1", mode=control_mode), principal=principal, idempotency_key=f"{project_id}:control-policy", trace_id=f"trace:{project_id}:control-policy", correlation_id=f"correlation:{project_id}")
    from novel_forge.modules.narrative_state import NarrativeStateRebuildService
    from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
    rebuilt = NarrativeStateRebuildService(DATABASE_URL).rebuild(project_id=project_id, book_id=book_id)
    assert rebuilt.projection["current_state"] == reality_one["current_state"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert NarrativeRealityRepository(uow.cursor).verify_replay(book_run_id=book.book_run_id)["revision_id"] == reality_one["revision_id"]
        uow.cursor.execute("SELECT s.asset_version_id FROM authority_story_design_version_state s JOIN authority_story_design_active_version a ON a.asset_version_id=s.asset_version_id AND a.project_id=s.project_id WHERE s.project_id=%s AND s.generator_operation_name='creative.candidates.generate'", [project_id])
        intent_version_id = str(uow.cursor.fetchone()[0])
    from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS
    source_entry = reality_one["current_state"]["canon_fact"][0]
    source_key = source_entry["entity_key"]
    next_world_time = max(reality_one["world_clock"].values(), default=0) + 1
    causal_payload = {
        "project_id": project_id, "actor_id": principal.principal_id,
        "reality_revision_id": reality_one["revision_id"], "intent_version_id": intent_version_id,
        "chapter_number": 2, "idempotency_key": f"{project_id}:causal-direction",
        "trace_id": f"trace:{project_id}:causal", "correlation_id": f"correlation:{project_id}",
        "candidates": [{
            "transition": {"transition_id": "undercurrent-response", "actor_id": "faction:council", "camera": "OFF_CAMERA", "story_time": {"timeline_id": "main", "start_ordinal": next_world_time, "end_ordinal": next_world_time, "precision": "EXACT"},
                "action": "respond to the accepted chapter event", "state_kind": "world_state", "entity_key": "world_state_id=council-alert",
                "changes": {"status": "ALERT"}, "cause_refs": [source_entry["source_event_id"]],
                "requirements": [{"requirement_id": "prior-event", "state_kind": "canon_fact", "entity_key": source_key, "field": "object", "operator": "EXISTS"}]},
            "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 0.7), "affected_entities": ["faction:council"],
            "world_consequences": ["council prepares an inquiry"], "rationale": "Accepted evidence gives the inquiry a cause",
        }],
    }
    awaiting = json.loads(json.dumps(causal_payload["candidates"][0]))
    awaiting["transition"]["transition_id"] = "hearing-after-inquiry"
    awaiting["transition"]["entity_key"] = "world_state_id=public-hearing"
    awaiting["transition"]["requirements"] = [{"requirement_id": "inquiry-required", "state_kind": "world_state", "entity_key": "world_state_id=council-alert", "field": "status", "operator": "EQUALS", "value": "ALERT"}]
    awaiting["rationale"] = "A hearing needs the inquiry established first"
    causal_payload["candidates"].append(awaiting)
    from novel_forge.modules.hierarchical_planning.causal_application import PostgresCausalPlanningApplication

    class ProcessLoss(BaseException):
        pass

    def lose_at(expected):
        def fail(checkpoint):
            if checkpoint == expected:
                raise ProcessLoss(checkpoint)
        return fail

    for field, bad_ref, code in (
        ("arc_refs", "arc:outside-book", "CAUSAL_PLAN_ARC_SCOPE_INVALID"),
        ("obligation_refs", "obligation:unaccepted", "CAUSAL_PLAN_OBLIGATION_SCOPE_INVALID"),
    ):
        invalid = deepcopy(causal_payload)
        invalid["idempotency_key"] += ":invalid:" + field
        invalid["candidates"][0][field] = [bad_ref]
        denied = api_post(f"/product/production/book-authority/runs/{book.book_run_id}/causal-plans", invalid)
        assert denied.status_code == 409, denied.text
        assert code in denied.text
    causal_arguments = {key: value for key, value in causal_payload.items() if key != "actor_id"}
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT COUNT(*) FROM authority_asset WHERE project_id=%s AND asset_type='narrative_governance_action'", [project_id])
        prior_governance_actions = uow.cursor.fetchone()[0]
    for checkpoint in ("after_causal_validation", "after_causal_proposal_event", "before_operation_completion"):
        application = PostgresCausalPlanningApplication(DATABASE_URL, application_build_id="core-functional-loop-fixture", commit_sha=RELEASE_SHA, fault_injector=lose_at(checkpoint))
        with pytest.raises(ProcessLoss):
            application.propose(principal=principal, book_run_id=book.book_run_id, **causal_arguments)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT COUNT(*) FROM authority_operation WHERE project_id=%s AND definition_name='planning.causal.propose'", [project_id])
            assert uow.cursor.fetchone()[0] == 0
            uow.cursor.execute("SELECT COUNT(*) FROM authority_asset WHERE project_id=%s AND asset_type='narrative_governance_action'", [project_id])
            assert uow.cursor.fetchone()[0] == prior_governance_actions
    application = PostgresCausalPlanningApplication(DATABASE_URL, application_build_id="core-functional-loop-fixture", commit_sha=RELEASE_SHA, fault_injector=lose_at("after_operation_completion_before_response"))
    with pytest.raises(ProcessLoss):
        application.propose(principal=principal, book_run_id=book.book_run_id, **causal_arguments)
    causal_response = api_post(f"/product/production/book-authority/runs/{book.book_run_id}/causal-plans", causal_payload)
    assert causal_response.status_code == 200, causal_response.text
    causal_plan = causal_response.json()
    assert causal_plan["selected_candidate_id"]
    assert causal_plan["replayed"] is True
    causal_replay = api_post(f"/product/production/book-authority/runs/{book.book_run_id}/causal-plans", causal_payload)
    assert causal_replay.status_code == 200, causal_replay.text
    assert causal_replay.json()["operation_id"] == causal_plan["operation_id"]
    assert causal_replay.json()["replayed"] is True
    causal_observation.update(causal_payload["candidates"][0]["transition"])
    pending_debt = next(debt for debt in causal_plan["causal_debts"] if debt["requirement_id"] == "inquiry-required")
    assert pending_debt["status"] == "PREPARATION_REQUIRED"
    causal_obligation.update(obligation_id=pending_debt["debt_id"], obligation_type="CAUSAL_DEBT", priority="HIGH", target_window={"status": "SCHEDULED", "from_chapter": 3, "to_chapter": 4}, linked_arc_ids=[], causal_requirement={"payload_json": json.dumps(awaiting["transition"]["requirements"][0])}, causal_plan_asset_version_id=causal_plan["governance_action_version_id"])
    assert api_get(f"/product/production/book-authority/runs/{book.book_run_id}/reality").json() == reality_one

    def assert_accepted_causal_reality():
        two = composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=2)
        assert two["parent_revision_id"] == reality_one["revision_id"]
        worlds = [item for item in two["current_state"]["world_state"] if item["entity_key"] == "world_state_id=council-alert"]
        assert worlds, causal_fixture_calls
        world = worlds[0]
        assert world["state"]["status"] == "ALERT"
        obligation = next(item for item in two["current_state"]["narrative_obligation"] if item["state"]["obligation_id"] == causal_obligation["obligation_id"])
        assert obligation["state"]["status"] == "OPEN"
        three = composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=3)
        repaid = next(item for item in three["current_state"]["narrative_obligation"] if item["state"]["obligation_id"] == causal_obligation["obligation_id"])
        assert repaid["state"]["status"] == "FULFILLED"
        assert len(editorial_decisions) >= (1 if control_mode == "MANUAL_DIRECTOR" else 2)
        assert repaid["state"]["payoff_evidence"] == causal_payoff
        replay = api_post(f"/product/production/book-authority/runs/{book.book_run_id}/causal-plans", causal_payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["governance_action_version_id"] == causal_plan["governance_action_version_id"]
        why = composition.query.reality_view(book_run_id=book.book_run_id, view="why", chapter_number=3, event_id=world["source_event_id"])
        assert world["source_event_id"] in {event["event_id"] for event in why["nodes"]}
        assert source_entry["source_event_id"] in {event["event_id"] for event in why["nodes"]}
        assert len(three["events"]) < sum(len(composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=number)["events"]) for number in (1, 2, 3))
        with pytest.raises(psycopg.errors.CheckViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("UPDATE authority_reality_event_index SET event_id='tampered' WHERE revision_id=%s", [two["revision_id"]])
        assert json.loads(world["state"]["world_transition"]["payload_json"])["camera"] == "OFF_CAMERA"
        projected = NarrativeStateRebuildService(DATABASE_URL).rebuild(project_id=project_id, book_id=book_id, through_chapter=2)
        assert projected.projection["current_state"] == two["current_state"]
        assert composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=1) == reality_one
        with pytest.raises(psycopg.errors.CheckViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("UPDATE authority_narrative_reality_revision SET source_digest=%s WHERE revision_id=%s", ["tampered", two["revision_id"]])
        with pytest.raises(psycopg.errors.CheckViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("DELETE FROM authority_narrative_reality_revision WHERE revision_id=%s", [two["revision_id"]])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            assert NarrativeRealityRepository(uow.cursor).project_acceptance(two["acceptance_id"]) == two["revision_id"]
            assert NarrativeRealityRepository(uow.cursor).verify_replay(book_run_id=book.book_run_id)["accepted_count"] >= 2
            uow.commit()

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
            SELECT request.chapter_request_id, request.command_payload
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
            WHERE acceptance.book_run_id=%s AND acceptance.chapter_number=1
            """,
            [book.book_run_id],
        )
        checkpoint_request = uow.cursor.fetchone()
        checkpoint_request_id = str(checkpoint_request[0])
        checkpoint_payload = dict(checkpoint_request[1])
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_volume_checkpoint
            WHERE book_run_id=%s AND accepted_through_chapter=1
            """,
            [book.book_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 1
        uow.cursor.execute(
            """
            SELECT content->'narrative_event_chain'
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [str(checkpoint_payload["parent_group_version_id"])],
        )
        frozen_realization_events = tuple(
            dict(item) for item in (uow.cursor.fetchone()[0] or ())
        )
        assert frozen_realization_events
        uow.cursor.execute(
            """
            SELECT realization.realization_id, realization.lifecycle,
                   COUNT(event.event_id),
                   COUNT(consumption.planned_event_id) FILTER (
                     WHERE consumption.coverage_status='ACCEPTED'
                   ), binding.execution_scope
            FROM authority_narrative_realization AS realization
            JOIN authority_narrative_realization_event AS event
              ON event.realization_id=realization.realization_id
            LEFT JOIN authority_narrative_realization_consumption AS consumption
              ON consumption.realization_id=event.realization_id
             AND consumption.planned_event_id=event.event_id
            JOIN story_plan_binding AS binding
              ON binding.asset_version_id=%s
             AND binding.contract_type='CHAPTER'
            WHERE realization.project_id=%s AND realization.book_id=%s
              AND realization.chapter_group_plan_version_id=%s
            GROUP BY realization.realization_id, realization.lifecycle,
                     binding.execution_scope
            """,
            [
                str(checkpoint_payload["chapter_plan_asset_version_id"]),
                project_id,
                book_id,
                str(checkpoint_payload["parent_group_version_id"]),
            ],
        )
        checkpoint_realization = uow.cursor.fetchone()
        assert checkpoint_realization is not None
        original_realization_id = str(checkpoint_realization[0])
        if runtime_path == "RECAP_FAILURE_ISOLATION":
            assert len(frozen_realization_events) == 1
            expected_realization_lifecycle = "EXECUTED"
        else:
            assert len(frozen_realization_events) > 1
            expected_realization_lifecycle = "FROZEN"
        assert tuple(checkpoint_realization[1:]) == (
            expected_realization_lifecycle,
            len(frozen_realization_events),
            1,
            "EXECUTED",
        )
    chapter_admission = dict(
        checkpoint_payload["preparation_report"]["chapter_production_admission"]
    )
    assert chapter_admission["admission"] == "CHAPTER_PRODUCTION_ADMITTED"
    assert chapter_admission["longform_design_qualification_hash"] == (
        snapshot.design_qualification_hash
    )
    assert (
        checkpoint_payload["context_version_refs"]["chapter_production_admission_hash"]
        == chapter_admission["admission_hash"]
    )

    if runtime_path in {
        "READER_FAILURE_ISOLATION",
        "RECAP_FAILURE_ISOLATION",
    }:
        chapter_one_progress = PostgresBookProductionQuery(DATABASE_URL).progress(
            book_run_id=book.book_run_id
        )
        assert chapter_one_progress.accepted_through_chapter == 1
        assert chapter_one_progress.last_narrative_progress_at is not None
        assert chapter_one_progress.state_class == "ACTIONABLE"
        assert chapter_one_progress.blocking_class == "NONE"
        assert chapter_one_progress.next_expected_transition == (
            "PLAN_OR_DISPATCH_NEXT_CHAPTER"
        )
        assert chapter_one_progress.next_chapter_number == 2
        assert chapter_one_progress.next_chapter_request_id == ""
        assert chapter_one_progress.next_chapter_dispatch_state == "NOT_CREATED"
        assert chapter_one_progress.pending_sidecar_backlog["blocking"] is False
        assert (
            chapter_one_progress.pending_sidecar_backlog["reader_admission_pending"]
            == 1
        )
        assert chapter_one_progress.pending_sidecar_backlog["total"] >= 1

        reader_admission = followup_admission_tick()
        assert reader_admission is not None
        assert reader_admission["action"] == "ADMIT_READER_OUTCOME"
        isolated_followup_type = "reader_outcome"
        isolated_followup_operation_id = str(reader_admission["operation_id"])
        if runtime_path == "RECAP_FAILURE_ISOLATION":
            followup_scheduler.run_or_recover(
                operation_id=isolated_followup_operation_id,
                project_id=project_id,
            )
            recap_admission = followup_admission_tick()
            assert recap_admission is not None
            assert recap_admission["action"] == "ADMIT_LONGFORM_RECAP"
            isolated_followup_type = "longform_recap"
            isolated_followup_operation_id = str(recap_admission["operation_id"])

        no_replan_actions: list[str] = []
        chapter_two_dispatched = False
        isolated_followup_failed = False
        for _ in range(96):
            tick = worker_tick(worker_composition)
            action = str(tick["action"])
            no_replan_actions.append(action)
            if action == SupervisorAction.DISPATCH_CHAPTER.value:
                dispatched_request = book_authority.require_chapter_request(
                    str(tick["evidence_ref"])
                )
                if int(dispatched_request["chapter_number"]) == 2:
                    chapter_two_dispatched = True
                    dispatched_progress = PostgresBookProductionQuery(
                        DATABASE_URL
                    ).progress(book_run_id=book.book_run_id)
                    assert dispatched_progress.accepted_through_chapter == 1
                    assert dispatched_progress.active_chapter_number == 2
                    assert dispatched_progress.active_chapter_request_id
                    assert dispatched_progress.active_operation_id == str(
                        tick["operation_id"]
                    )
                    assert (
                        dispatched_progress.pending_sidecar_backlog["blocking"] is False
                    )
                    assert dispatched_progress.pending_sidecar_backlog["total"] >= 1
                    assert (
                        dispatched_progress.pending_sidecar_backlog[
                            "operation_status_counts"
                        ][f"{isolated_followup_type}:ready"]
                        == 1
                    )
                run_chapter(worker_chapter_application, str(tick["operation_id"]))
                if chapter_two_dispatched and not isolated_followup_failed:
                    from novel_forge.modules.content_authority import (
                        scheduler as content_scheduler_runtime,
                    )

                    original_handler = content_scheduler_runtime.execute_content_handler

                    def fail_sidecar(*_args, **_kwargs):
                        raise KernelError(
                            "SIDECAR_INPUT_INVALID",
                            "injected terminal advisory sidecar failure",
                        )

                    monkeypatch.setattr(
                        content_scheduler_runtime,
                        "execute_content_handler",
                        fail_sidecar,
                    )
                    with pytest.raises(
                        KernelError, match="injected terminal advisory sidecar failure"
                    ):
                        followup_scheduler.run_or_recover(
                            operation_id=isolated_followup_operation_id,
                            project_id=project_id,
                        )
                    monkeypatch.setattr(
                        content_scheduler_runtime,
                        "execute_content_handler",
                        original_handler,
                    )
                    isolated_followup_failed = True
            if (
                int(
                    book_authority.require(book.book_run_id)["accepted_through_chapter"]
                )
                >= 4
            ):
                break
        else:
            raise AssertionError(
                "Canonical Worker did not cross into Volume 2 without Replan"
            )
        assert SupervisorAction.START_REPLAN.value not in no_replan_actions
        assert SupervisorAction.DISPATCH_CHAPTER.value in no_replan_actions
        assert SupervisorAction.ACCEPT_CHAPTER.value in no_replan_actions
        assert chapter_two_dispatched is True
        assert isolated_followup_failed is True
        assert (
            book_authority.require(book.book_run_id)["input_snapshot_id"]
            == snapshot.snapshot_id
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.created_at, request.created_at,
                       root.created_at, MIN(dispatch.created_at)
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_chapter_request AS request
                  ON request.book_run_id=acceptance.book_run_id
                 AND request.chapter_number=2
                JOIN authority_operation AS root
                  ON root.operation_id=request.chapter_root_operation_id
                JOIN authority_operation AS child
                  ON child.root_operation_id=root.operation_id
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=child.operation_id
                 AND effect.effect_type='model.invoke'
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                WHERE acceptance.book_run_id=%s
                  AND acceptance.chapter_number=1
                  AND acceptance.status='COMMITTED'
                GROUP BY acceptance.created_at, request.created_at,
                         root.created_at
                """,
                [book.book_run_id],
            )
            liveness_timestamps = uow.cursor.fetchone()
        assert liveness_timestamps is not None
        chapter_one_acceptance_at = liveness_timestamps[0]
        chapter_two_request_at = liveness_timestamps[1]
        chapter_two_dispatch_at = liveness_timestamps[2]
        chapter_two_first_provider_call_at = liveness_timestamps[3]
        assert chapter_two_request_at >= chapter_one_acceptance_at
        assert chapter_two_first_provider_call_at >= chapter_two_dispatch_at
        assert chapter_two_first_provider_call_at >= chapter_two_request_at
        failed_sidecar_progress = PostgresBookProductionQuery(DATABASE_URL).progress(
            book_run_id=book.book_run_id
        )
        assert failed_sidecar_progress.pending_sidecar_backlog["blocking"] is False
        assert (
            failed_sidecar_progress.pending_sidecar_backlog["operation_status_counts"][
                f"{isolated_followup_type}:failed_final"
            ]
            == 1
        )
        for _ in range(12):
            checkpoint_tick = worker_tick(worker_composition)
            if (
                checkpoint_tick["action"] == SupervisorAction.UPDATE_CHECKPOINTS.value
                and int(
                    book_authority.require(book.book_run_id)["accepted_through_chapter"]
                )
                == 4
            ):
                break
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT volume_plan_version
                FROM authority_book_volume_checkpoint
                WHERE book_run_id=%s AND accepted_through_chapter=4
                """,
                [book.book_run_id],
            )
            assert uow.cursor.fetchone() == (
                activated["volume_plan.generate:secondary"],
            )
            uow.cursor.execute(
                """
                SELECT DISTINCT arc_plan_version_id
                FROM authority_arc_checkpoint_v2
                WHERE project_id=%s AND book_id=%s
                  AND accepted_through_chapter=4
                ORDER BY arc_plan_version_id
                """,
                [project_id, book_id],
            )
            assert tuple(str(row[0]) for row in uow.cursor.fetchall()) == tuple(
                sorted(
                    (
                        activated["arc_plan.generate"],
                        activated["arc_plan.generate:future"],
                    )
                )
            )
            uow.cursor.execute(
                """
                SELECT realization.lifecycle, COUNT(event.event_id),
                       COUNT(consumption.planned_event_id) FILTER (
                         WHERE consumption.coverage_status='ACCEPTED'
                       )
                FROM authority_narrative_realization AS realization
                JOIN authority_narrative_realization_event AS event
                  ON event.realization_id=realization.realization_id
                LEFT JOIN authority_narrative_realization_consumption AS consumption
                  ON consumption.realization_id=event.realization_id
                 AND consumption.planned_event_id=event.event_id
                WHERE realization.realization_id=%s
                GROUP BY realization.lifecycle
                """,
                [original_realization_id],
            )
            accepted_event_count = sum(
                int(item["chapter_number"]) <= 4 for item in frozen_realization_events
            )
            expected_realization_lifecycle = (
                "EXECUTED"
                if accepted_event_count == len(frozen_realization_events)
                else "FROZEN"
            )
            assert uow.cursor.fetchone() == (
                expected_realization_lifecycle,
                len(frozen_realization_events),
                accepted_event_count,
            )
        production_execution.close()
        for worker_execution in worker_production_executions:
            worker_execution.close()
        assert_accepted_causal_reality()
        object_store.cleanup()
        return

    replan_target_group_version = ""
    replan_target_realization_id = ""
    for _ in range(128):
        future_tick = worker_tick(worker_composition)
        future_action = str(future_tick["action"])
        if future_action == SupervisorAction.DISPATCH_CHAPTER.value:
            run_chapter(
                worker_chapter_application,
                str(future_tick["operation_id"]),
            )
        accepted_through = int(
            book_authority.require(book.book_run_id)["accepted_through_chapter"]
        )
        if (
            accepted_through == 3
            and future_action == SupervisorAction.QUALIFY_NARRATIVE_REALIZATION.value
        ):
            future_group = composition.query.active_plan_covering_chapter(
                project_id=project_id,
                book_id=book_id,
                contract_type="CHAPTER_GROUP",
                chapter_number=4,
            )
            assert future_group is not None
            assert future_group["content"]["chapter_range"] == [4, 6]
            replan_target_group_version = str(future_group["asset_version_id"])
            replan_target_realization_id = str(future_tick["evidence_ref"])
        if (
            accepted_through == 3
            and replan_target_realization_id
            and future_action == SupervisorAction.GENERATE_CHAPTER_PLAN.value
        ):
            break
    else:
        raise AssertionError(
            "Canonical Worker did not freeze the future-only ChapterGroup 4-6"
        )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT request.chapter_request_id
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
            WHERE acceptance.book_run_id=%s AND acceptance.chapter_number=3
            """,
            [book.book_run_id],
        )
        checkpoint_request_id = str(uow.cursor.fetchone()[0])

    for _ in range(8):
        if _followup_output_exists(
            project_id=project_id,
            chapter_request_id=checkpoint_request_id,
            output_key="reader_outcome.report",
        ):
            break
        followup_worker_tick()
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
    assert book_authority.require(book.book_run_id)["state"] == (
        BookProductionState.READY.value
    )
    before_replan_reality = composition.query.narrative_reality(
        book_run_id=book.book_run_id, chapter_number=3
    )

    def preserved_replan_inputs():
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.chapter_number, acceptance.acceptance_id,
                       acceptance.chapter_outcome_asset_version_id,
                       acceptance.story_state_asset_version_id,
                       acceptance.canon_snapshot_asset_version_id,
                       request.chapter_request_id, request.command_payload,
                       operation.operation_id, operation.input_asset_snapshot
                FROM authority_book_chapter_acceptance acceptance
                JOIN authority_book_chapter_request request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                JOIN authority_operation operation
                  ON operation.operation_id=request.chapter_root_operation_id
                WHERE acceptance.book_run_id=%s AND acceptance.chapter_number<=3
                ORDER BY acceptance.chapter_number
                """,
                [book.book_run_id],
            )
            history = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT binding_id, asset_version_id, parent_version_id,
                       execution_scope, freshness, version
                FROM story_plan_binding
                WHERE project_id=%s AND book_id=%s
                  AND (contract_type IN ('BOOK','VOLUME','ARC')
                       OR execution_scope='EXECUTED')
                ORDER BY binding_id
                """,
                [project_id, book_id],
            )
            plans = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT effect.external_effect_id, effect.status,
                       dispatch.dispatch_id, receipt.external_receipt_id
                FROM authority_external_effect effect
                JOIN authority_operation operation USING(operation_id)
                LEFT JOIN authority_external_effect_dispatch dispatch
                  USING(external_effect_id)
                LEFT JOIN authority_external_receipt receipt USING(dispatch_id)
                WHERE operation.root_operation_id=ANY(%s)
                   OR operation.operation_id=ANY(%s)
                ORDER BY effect.external_effect_id, dispatch.dispatch_id,
                         receipt.external_receipt_id
                """,
                [[row[7] for row in history], [row[7] for row in history]],
            )
            return history, plans, uow.cursor.fetchall()

    preserved_history, preserved_plans, preserved_effects = preserved_replan_inputs()
    assert len(preserved_history) == 3
    assert preserved_effects and all(row[1] == "SUCCEEDED" for row in preserved_effects)
    assert all(row[6]["context_version_refs"]["book_production_input_snapshot_id"] == snapshot.snapshot_id for row in preserved_history)
    pending = coordinator.start(
        CoordinateBookReplanCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            book_run_id=book.book_run_id,
            source_recap_asset_version_id=str(
                controlled_recap["recap"]["asset_version_id"]
            ),
            replan_request_asset_version_id=str(
                controlled_recap["replan_request"]["asset_version_id"]
            ),
            affected_scope="CHAPTER_GROUP",
            idempotency_key=f"{project_id}:explicit-replan:chapter-group",
            trace_id=f"trace:{project_id}:explicit-replan",
            correlation_id=str(controlled_recap["operation_id"]),
        )
    )
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
    assert resumed_snapshot.design_admission_status == ("LONGFORM_DESIGN_QUALIFIED")
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
            [replan_target_group_version],
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
    assert preserved_replan_inputs() == (preserved_history, preserved_plans, preserved_effects)
    assert composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=3) == before_replan_reality
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT lifecycle
            FROM authority_narrative_realization
            WHERE realization_id=%s
            """,
            [replan_target_realization_id],
        )
        assert uow.cursor.fetchone() == ("STALE",)

    post_replan_planning_actions: list[str] = []
    for _ in range(8):
        group_transition = worker_tick(restarted)
        action = str(group_transition["action"])
        post_replan_planning_actions.append(action)
        if action == SupervisorAction.START_CHAPTER_GROUP.value:
            break
    else:
        raise AssertionError(
            "replacement ChapterGroup did not pass realization and ChapterPlan gates"
        )
    assert SupervisorAction.QUALIFY_NARRATIVE_REALIZATION.value in (
        post_replan_planning_actions
    )
    assert SupervisorAction.DISPATCH_CHAPTER.value not in post_replan_planning_actions
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
    assert group_run_count == 3
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
            >= 4
        ):
            break
    else:
        raise AssertionError("Canonical Worker did not resume through Chapter 4")
    assert SupervisorAction.GENERATE_CHAPTER_PLAN.value in after_replan_actions
    assert SupervisorAction.FREEZE_CHAPTER_PLAN.value in after_replan_actions
    assert SupervisorAction.DISPATCH_CHAPTER.value in after_replan_actions
    assert SupervisorAction.ACCEPT_CHAPTER.value in after_replan_actions
    assert book_authority.require(book.book_run_id)["accepted_through_chapter"] == 4

    run_chapter(restarted_after_pause_chapter, str(preserved_history[0][7]))
    final_history, final_plans, final_effects = preserved_replan_inputs()
    assert final_history == preserved_history
    assert final_effects == preserved_effects
    assert all(row in final_plans for row in preserved_plans)
    assert composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=3) == before_replan_reality

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT request.chapter_request_id
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
            WHERE acceptance.book_run_id=%s AND acceptance.chapter_number=4
            """,
            [book.book_run_id],
        )
        chapter_four_request_id = str(uow.cursor.fetchone()[0])
    for _ in range(8):
        if _followup_output_exists(
            project_id=project_id,
            chapter_request_id=chapter_four_request_id,
            output_key="reader_outcome.report",
        ):
            break
        followup_worker_tick()
    else:
        raise AssertionError("Book Followup worker did not complete Chapter 4 Reader")
    chapter_four_snapshot = composition.query.require_accepted_followup_snapshot(
        chapter_request_id=chapter_four_request_id
    )
    fourth_request = book_authority.require_chapter_request(chapter_four_request_id)
    fourth_payload = fourth_request["command_payload"]
    fourth_refs = fourth_payload["context_version_refs"]
    assert fourth_refs["book_production_input_snapshot_id"] == resumed_snapshot.snapshot_id
    assert fourth_refs["chapter_group_plan_version"] == resumed_snapshot.current_chapter_group_plan_version
    assert fourth_refs["chapter_group_plan_version"] != replan_target_group_version
    assert chapter_four_snapshot["book_production_input_snapshot_id"] == resumed_snapshot.snapshot_id
    predecessor_inputs = {row["asset_type"]: row for row in fourth_payload["context_candidates"] if row["asset_type"] in {"story_state_snapshot", "canon_snapshot"}}
    assert set(predecessor_inputs) == {"story_state_snapshot", "canon_snapshot"}
    assert predecessor_inputs["story_state_snapshot"]["asset_version_id"] == preserved_history[-1][3]
    assert predecessor_inputs["canon_snapshot"]["asset_version_id"] == preserved_history[-1][4]
    assert all(row["accepted_boundary"]["accepted_through_chapter"] == 3 for row in predecessor_inputs.values())
    fourth_reality = composition.query.narrative_reality(book_run_id=book.book_run_id, chapter_number=4)
    assert fourth_reality["parent_revision_id"] == before_replan_reality["revision_id"]
    reader = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_four_request_id,
        followup_type="READER_OUTCOME",
        output_key="reader_outcome.report",
    )
    previous_reader_state = composition.query.previous_reader_state(
        book_run_id=book.book_run_id,
        chapter_number=4,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT input_asset_snapshot
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [reader["operation_id"]],
        )
        chapter_four_reader_inputs = list(uow.cursor.fetchone()[0])
    assert previous_reader_state != "NONE"
    assert previous_reader_state in {
        str(item["asset_version_id"]) for item in chapter_four_reader_inputs
    }
    reader_longitudinal = BookFollowupProjectionQuery(
        DATABASE_URL
    ).reader_recap_evidence(
        project_id=project_id,
        book_run_id=book.book_run_id,
        through_chapter=4,
        current_report_asset_version_id=str(reader["asset_version_id"]),
    )
    assert len(reader_longitudinal["recent_reports"]) == 4
    assert reader_longitudinal["evidence_class"] == "READER_PROXY_ADVISORY"
    assert reader_longitudinal["qualification"]["disagreement"] is True
    assert reader_longitudinal["qualification"]["position_bias"] is True
    assert reader_longitudinal["qualification"]["ood"] is True
    authority_inputs = book_authority.resolve_asset_refs(
        project_id=project_id,
        asset_version_ids=(
            str(chapter_four_snapshot["book_design_version"]),
            str(chapter_four_snapshot["book_plan_version"]),
            str(chapter_four_snapshot["volume_plan_version"]),
            *(str(item) for item in chapter_four_snapshot["arc_plan_versions"]),
            str(chapter_four_snapshot["quality_trend_version"]),
            str(chapter_four_snapshot["accepted_chapter_outcome_version"]),
            str(chapter_four_snapshot["accepted_story_state_version"]),
            str(chapter_four_snapshot["accepted_canon_snapshot_version"]),
        ),
    )
    later_admission = book_authority.schedule_longform_recap(
        chapter_four_request_id,
        principal=principal,
        payload={
            "book_id": chapter_four_snapshot["book_id"],
            "checkpoint_type": LongformCheckpointType.ARC_CHECKPOINT.value,
            "chapter_range": [1, 4],
            "observed_through_chapter": int(
                chapter_four_snapshot["observed_through_chapter"]
            ),
            "acceptance_operation_id": chapter_four_snapshot["acceptance_operation_id"],
            "book_production_input_snapshot_id": chapter_four_snapshot[
                "book_production_input_snapshot_id"
            ],
            "book_design_version": chapter_four_snapshot["book_design_version"],
            "book_plan_version": chapter_four_snapshot["book_plan_version"],
            "volume_plan_version": chapter_four_snapshot["volume_plan_version"],
            "arc_plan_versions": list(chapter_four_snapshot["arc_plan_versions"]),
            "canon_snapshot_version": chapter_four_snapshot[
                "accepted_canon_snapshot_version"
            ],
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": chapter_four_snapshot["quality_trend_version"],
            "chapter_outcome_versions": [
                chapter_four_snapshot["accepted_chapter_outcome_version"]
            ],
            "story_state_version": chapter_four_snapshot[
                "accepted_story_state_version"
            ],
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
    followup_scheduler.run_or_recover(
        operation_id=later_admission.operation_id,
        project_id=project_id,
    )
    later_recap = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_four_request_id,
        followup_type="LONGFORM_RECAP",
        output_key="longform.recap.report",
    )
    later_deviation = _followup_output(
        project_id=project_id,
        chapter_request_id=chapter_four_request_id,
        followup_type="LONGFORM_RECAP",
        output_key="longform.recap.deviation_report",
    )
    reevaluation_payload = {
        "source_recap_asset_version_id": str(later_recap["asset_version_id"]),
        "deviation_report_asset_version_id": str(later_deviation["asset_version_id"]),
        "idempotency_key": f"{pending['replan_id']}:reevaluation:chapter:4",
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
    active_change = coordinator.plan_change.require(pending["plan_change_proposal_id"])
    request.node.user_properties.append(("book_replan_native", json.dumps({
        "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
        "project_id": project_id, "book_run_id": book.book_run_id,
        "accepted_before": 3, "accepted_after": 4,
        "accepted_reality_before": before_replan_reality["revision_id"],
        "accepted_reality_after": fourth_reality["revision_id"],
        "recap_version": controlled_recap["recap"]["asset_version_id"],
        "replan_id": pending["replan_id"], "replan_status": resumed["status"],
        "plan_change_proposal_id": active_change["proposal_id"],
        "activation_operation_id": active_change["activation_operation_id"],
        "prior_snapshot_id": snapshot.snapshot_id,
        "new_snapshot_id": resumed_snapshot.snapshot_id,
        "replaced_group_version": replan_target_group_version,
        "new_group_version": fourth_refs["chapter_group_plan_version"],
        "preserved_history_digest": canonical_hash(preserved_history),
        "preserved_plan_binding_ids": [row[0] for row in preserved_plans],
        "preserved_effect_count": len(preserved_effects),
        "next_request_id": chapter_four_request_id,
        "next_context_state_versions": {key: value["asset_version_id"] for key, value in predecessor_inputs.items()},
        "next_context_accepted_through": 3,
        "reevaluation_id": reevaluated["reevaluation_id"],
        "reevaluation_resolution": reevaluated["resolution"],
    }, sort_keys=True)))
    production_execution.close()
    for worker_execution in worker_production_executions:
        worker_execution.close()
    assert_accepted_causal_reality()
    object_store.cleanup()


def test_reader_judge_shadow_activation_drift_and_suspension_in_postgres() -> None:
    harness = CapabilityPackPostgresHarness("reader-judge-functional-loop")
    reader_node = next(
        node
        for node in harness._base_manifest["workflow_template"]["nodes"]
        if node["node_id"] == "review"
    )
    reader_node["agent_definition_ref"] = "reader-judge-agent@1"
    reader_node["commit_authority"] = "READER_JUDGE_AUTHORITY"
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


def test_planning_profile_contracts_coexist_in_one_project_without_rewriting_legacy():
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery, AuthorityAssetWriter
    from tests.integration.authority_postgres_support import insert_definition, insert_operation
    from tests.unit.test_story_planning_runtime import _planning_profile_binding

    harness = CapabilityPackPostgresHarness("planning-profile-identity", book_count=2)
    operation_ids = [str(uuid4()) for _ in range(3)]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        name = f"profile-contract-fixture:{uuid4()}"
        insert_definition(uow.cursor, name)
        for operation_id in operation_ids:
            insert_operation(uow.cursor, operation_id=operation_id, definition_name=name, project_id=harness.project_id, workspace_id=harness.workspace_id, status="EXECUTING")
        uow.commit()
    preparer = object.__new__(PostgresPlanningExecutionPreparer)
    preparer.query = AuthorityAssetQuery(DATABASE_URL)
    preparer.writer = AuthorityAssetWriter(DATABASE_URL)
    preparer._operation_graph = lambda operation_id, project_id: {"root_operation_id": operation_id, "saga_id": "profile-contract-fixture", "definition_name": name}
    select_profile = preparer._select_model_profile
    preparer._select_model_profile = lambda project_id, profile: profile
    first, _ = _planning_profile_binding(preparer, project_id=harness.project_id, book_id=harness.book_ids[0], operation_id=operation_ids[0], schema_ref="schema:foundation-provider-output:creative_foundation:v1:author-input-v1")
    preparer._select_model_profile = select_profile
    assert first.route_snapshot.model_profile_id.endswith(".default")
    original_ref = f"production_execution/model_profiles/{first.route_snapshot.model_profile_id}/v1"
    original = preparer.query.require(project_id=harness.project_id, logical_ref=original_ref)
    second, _ = _planning_profile_binding(preparer, project_id=harness.project_id, book_id=harness.book_ids[1], operation_id=operation_ids[1], schema_ref="schema:foundation-provider-output:creative_foundation:v1")
    retried, _ = _planning_profile_binding(preparer, project_id=harness.project_id, book_id=harness.book_ids[1], operation_id=operation_ids[1], attempt_id="retry-attempt", schema_ref="schema:foundation-provider-output:creative_foundation:v1")
    legacy, _ = _planning_profile_binding(preparer, project_id=harness.project_id, book_id=harness.book_ids[0], operation_id=operation_ids[2], schema_ref="schema:foundation-provider-output:creative_foundation:v1:author-input-v1")
    assert first.route_snapshot.model_profile_id == legacy.route_snapshot.model_profile_id
    assert second.route_snapshot.model_profile_id == retried.route_snapshot.model_profile_id
    assert second.route_snapshot.model_profile_id != first.route_snapshot.model_profile_id
    assert second.route_snapshot.policy_id == retried.route_snapshot.policy_id
    assert second.route_snapshot.fallback_policy_ref == retried.route_snapshot.fallback_policy_ref
    assert second.request.book_id == harness.book_ids[1]
    assert preparer.query.require(project_id=harness.project_id, logical_ref=original_ref) == original
    for kind in ("model_profile", "route_policy", "fallback_policy"):
        records = preparer.query.list_versions(project_id=harness.project_id, asset_type=kind)
        assert len(records) == 2
        assert all(record.version_number == 1 for record in records)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [harness.project_id])
        assert uow.cursor.fetchone()[0] == 0
