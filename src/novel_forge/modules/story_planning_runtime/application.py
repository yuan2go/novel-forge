"""Command-Kernel-backed runtime for five hierarchical Planning generators."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    admit_command,
    execute_transaction_command,
)
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
    PostgresHierarchicalPlanningAuthority,
    validate_planning_contract,
)
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    GENERATOR_CATALOG,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
)
from novel_forge.modules.story_design_authority.validators import (
    validate_story_design_candidate,
)
from novel_forge.modules.story_design_authority.qualification import (
    required_qualification_profiles,
    scripted_qualification,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_DEFINITION as STORY_PLANNING_EVALUATION_DEFINITION,
    NARRATIVE_EVALUATION_HANDLER as STORY_PLANNING_EVALUATION_HANDLER,
    NARRATIVE_EVALUATION_VERSION as STORY_PLANNING_EVALUATION_VERSION,
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
    NarrativeSemanticEvaluationExecutionPort,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .binder import PlanningExecutionBinder
from .domain import (
    FrozenPlanningInput,
    PlanningGenerationResult,
    PlanningGenerationStatus,
    STORY_PLANNING_MAX_ATTEMPTS,
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    StoryPlanningGenerationCommand,
    StoryPlanningEvaluationCommand,
    build_planning_constraint_envelope,
    canonical_hash,
)


STORY_PLANNING_GENERATION_DEFINITION = "story_planning.generate"
STORY_PLANNING_GENERATION_VERSION = STORY_PLANNING_OPERATION_DEFINITION_REF.rpartition(
    "@"
)[2]
STORY_PLANNING_GENERATION_HANDLER = "novel_forge.story_planning.generate"
CHAPTER_PLAN_PROJECTION_DEFINITION = "story_planning.chapter_plan.materialize"
CHAPTER_PLAN_PROJECTION_HANDLER = "novel_forge.story_planning.chapter_plan.materialize"


_PLAN_INPUT_CONTRACTS = {
    "book_plan": PlanContractType.BOOK,
    "volume_plan": PlanContractType.VOLUME,
    "arc_plans": PlanContractType.ARC,
    "chapter_group_plan": PlanContractType.CHAPTER_GROUP,
}

_AUTHORITY_INPUT_ASSET_TYPES = {
    "story_state": frozenset({"story_state", "story_state_snapshot"}),
    "reader_state": frozenset({"reader_state", "reader_state_transition"}),
    "character_state": frozenset({"character_state", "character_state_snapshot"}),
    "foreshadowing_state": frozenset({"foreshadowing_state", "foreshadow_snapshot"}),
    "reward_ledger": frozenset({"reward_ledger", "reward_ledger_snapshot"}),
    "promise_ledger": frozenset({"promise_ledger", "promise_ledger_snapshot"}),
    "previous_volume_outcome": frozenset({"previous_volume_outcome", "volume_outcome"}),
    "previous_chapter_group_outcome": frozenset(
        {"previous_chapter_group_outcome", "chapter_group_outcome"}
    ),
    "previous_chapter_outcome": frozenset(
        {"previous_chapter_outcome", "chapter_outcome"}
    ),
    "ending_reachability": frozenset(
        {"ending_reachability", "ending_reachability_report"}
    ),
}


class _PlanningGenerationHandler:
    def __init__(self, binder: PlanningExecutionBinder) -> None:
        self.binder = binder

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "PLANNING_GENERATION_INPUT_INVALID",
                "Planning Generation payload must be an object",
            )
        command = _command_from_payload(payload)
        if (
            command.project_id != request.project_id
            or command.workspace_id != request.workspace_id
        ):
            raise KernelError(
                "PLANNING_GENERATION_SCOPE_MISMATCH",
                "Planning Generation command differs from admitted scope",
            )
        definition = GENERATOR_CATALOG.get(command.generator_operation_name)
        if definition is None:
            raise KernelError(
                "GENERATOR_DEFINITION_NOT_FOUND",
                "Planning GeneratorDefinition is not registered",
            )
        by_id = {item.asset_version_id: item for item in request.inputs}
        inputs: list[FrozenPlanningInput] = []
        authority_roles = _authority_role_versions(command)
        for role, asset_version_id in authority_roles.items():
            item = by_id.get(asset_version_id)
            if item is None:
                raise KernelError(
                    "PLANNING_GENERATION_FROZEN_INPUT_MISSING",
                    f"admitted input is missing Authority role {role}",
                )
            inputs.append(
                FrozenPlanningInput(
                    role=role,
                    asset_version_id=item.asset_version_id,
                    content_hash=item.content_hash,
                    asset_type=item.asset_type,
                )
            )
        for asset_version_id in command.change_evidence_version_ids:
            item = by_id.get(asset_version_id)
            if item is None:
                raise KernelError(
                    "PLANNING_GENERATION_CHANGE_EVIDENCE_MISSING",
                    "admitted Planning input is missing frozen change evidence",
                )
        candidate = self.binder.execute(
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            worker_id=request.worker_id,
            command=command,
            inputs=tuple(inputs),
            definition=definition,
        )
        evidence = candidate.evidence.to_dict()
        if (
            evidence["operation_id"] != request.operation_id
            or evidence["attempt_id"] != request.attempt_id
            or int(evidence["fencing_token"]) != request.fencing_token
        ):
            raise KernelError(
                "PLANNING_EXECUTION_EVIDENCE_DRIFT",
                "PEP candidate evidence differs from the current Authority Attempt",
            )
        return AuthorityHandlerOutput(
            # One generic worker Operation has one frozen output contract.
            # The concrete candidate kind remains frozen in the Generator
            # Definition and candidate content; it cannot change the admitted
            # OperationDefinition output selector mid-Attempt.
            asset_type="planning_generation_candidate",
            output_key="story_planning.candidate",
            role="primary",
            content=candidate.authority_content(
                project_id=command.project_id,
                book_id=command.book_id,
                constraint_envelope=build_planning_constraint_envelope(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    generation_operation_id=request.operation_id,
                    generator_operation_name=command.generator_operation_name,
                    frozen_inputs=tuple(inputs),
                    input_contents={
                        role: by_id[asset_version_id].content
                        for role, asset_version_id in authority_roles.items()
                    },
                    candidate_payload=candidate.candidate_payload,
                    arc_working_set=command.arc_working_set,
                ),
            ),
            qualification_policy="story-planning-candidate-only-v1",
            reference_asset_version_ids=(
                *(item.asset_version_id for item in inputs),
                *command.change_evidence_version_ids,
            ),
            evidence=evidence,
            # Generation only creates an immutable candidate.  Semantic
            # Evaluation and activation own the two later transitions.
            lifecycle="CANDIDATE",
            eligibility="INELIGIBLE",
            governance="CLEAR",
        )


class StoryPlanningGenerationHandlerRegistry:
    def __init__(self, binder: PlanningExecutionBinder) -> None:
        generation = AuthorityHandlerRegistration(
            definition_name=STORY_PLANNING_GENERATION_DEFINITION,
            definition_version=STORY_PLANNING_GENERATION_VERSION,
            handler_key=STORY_PLANNING_GENERATION_HANDLER,
            handler_contract_version="story-planning-generation-handler-v1",
            output_asset_type="planning_generation_candidate",
            output_key="story_planning.candidate",
            role="primary",
            completion_topic="story_planning.candidate.materialized",
            handler=_PlanningGenerationHandler(binder),
        )
        self.items = {
            STORY_PLANNING_GENERATION_DEFINITION: generation,
        }

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(item.handler_key for item in self.items.values())

    @property
    def definition_names(self) -> frozenset[str]:
        return frozenset(self.items)

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        item = self.items.get(definition_name)
        if item is None or item.definition_version != definition_version:
            raise KeyError((definition_name, definition_version))
        return item


class StoryPlanningGenerationApplication:
    def __init__(
        self,
        database_url: str,
        *,
        execution_binder: PlanningExecutionBinder,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "story-planning-generation-worker",
        semantic_evaluation_execution_port: NarrativeSemanticEvaluationExecutionPort
        | None = None,
        allow_scripted_evaluation_fixture: bool = False,
        narrative_evaluator_principal: Principal | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Planning Generation requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.allow_scripted_evaluation_fixture = allow_scripted_evaluation_fixture
        self.narrative_evaluator_principal = narrative_evaluator_principal
        self.registry = StoryPlanningGenerationHandlerRegistry(execution_binder)
        self.semantic_evaluation = NarrativeSemanticEvaluationApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id=f"{worker_id}:semantic-evaluation",
            execution_port=semantic_evaluation_execution_port,
            allow_scripted_fixture=allow_scripted_evaluation_fixture,
        )
        self.story_design = PostgresStoryDesignAssetAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id=f"{worker_id}:story-design",
        )
        self.planning = PostgresHierarchicalPlanningAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )

    def generate(
        self,
        command: StoryPlanningGenerationCommand,
        *,
        principal: Principal,
    ) -> PlanningGenerationResult:
        principal.require("story_planning.authority.execute", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Planning Generation actor must be the trusted Principal"
            )
        definition = GENERATOR_CATALOG[command.generator_operation_name]
        self._register_definitions()
        frozen_inputs = self._resolve_inputs(command)
        frozen_change_evidence = self._resolve_change_evidence(command)
        input_assets = [
            {
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
            }
            for item in frozen_inputs
        ]
        input_assets.extend(
            {
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
            }
            for item in frozen_change_evidence
        )
        if command.repair_of_candidate_id:
            repair_asset = self._require_asset(
                project_id=command.project_id,
                asset_version_id=command.repair_of_candidate_id,
            )
            input_assets.append(
                {
                    "asset_version_id": repair_asset["asset_version_id"],
                    "content_hash": repair_asset["content_hash"],
                }
            )
        payload = _command_payload(command)
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": STORY_PLANNING_GENERATION_DEFINITION,
                "definition_version": STORY_PLANNING_GENERATION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "logical_key": command.logical_key,
                "actor_id": command.actor_id,
                "idempotency_scope": "book:story-planning-generation",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": (
                    command.parent_agent_session_operation_id
                    or command.repair_of_candidate_id
                ),
                "causation_operation_id": (
                    command.parent_agent_session_operation_id or None
                ),
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": payload,
                },
                "input_assets": input_assets,
            },
            context=AdmissionContext(
                actor_id=command.actor_id,
                permissions=frozenset({"story_planning.authority.execute"}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        self._record_generation(
            operation_id=operation_id,
            command=command,
            inputs=(*frozen_inputs, *frozen_change_evidence),
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=command.actor_id,
                    reason="Planning Generation inputs and Pack route are frozen",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=(
                        command.parent_agent_session_operation_id
                        or command.repair_of_candidate_id
                    ),
                ),
            )
            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    command.actor_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        generation = self.require_generation(operation_id)
        existing_candidate_id = str(generation.get("candidate_asset_version_id") or "")
        if existing_candidate_id:
            existing_candidate = self.require_candidate(existing_candidate_id)
            advanced = self._advance_candidate(
                operation_id=operation_id,
                candidate_asset_version_id=existing_candidate_id,
                candidate_content_hash=str(existing_candidate["content_hash"]),
                command=command,
                principal=principal,
                replayed=True,
                definition=definition,
            )
            return self._evaluate_pending_if_required(
                advanced=advanced,
                generation_command=command,
                principal=principal,
            )
        scheduled = ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(operation_id=operation_id, project_id=command.project_id)
        candidate_id = scheduled.output.asset_version_id
        self._record_candidate(
            operation_id=operation_id,
            candidate_asset_version_id=candidate_id,
            candidate_content_hash=scheduled.output.content_hash,
            command=command,
            attempt_id=scheduled.attempt_id,
        )
        advanced = self._advance_candidate(
            operation_id=operation_id,
            candidate_asset_version_id=candidate_id,
            candidate_content_hash=scheduled.output.content_hash,
            command=command,
            principal=principal,
            replayed=bool(admitted["replayed"]),
            definition=definition,
        )
        return self._evaluate_pending_if_required(
            advanced=advanced,
            generation_command=command,
            principal=principal,
        )

    def evaluate_candidate(
        self,
        command: StoryPlanningEvaluationCommand,
        *,
        principal: Principal,
        transition_principal: Principal | None = None,
    ) -> PlanningGenerationResult:
        principal.require("narrative_design.evaluate", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError(
                "Planning Evaluation actor must be the trusted Principal"
            )
        transition_principal = transition_principal or principal
        transition_principal.require(
            "story_planning.authority.execute", command.project_id
        )
        generation = self.require_candidate(command.candidate_asset_version_id)
        if (
            generation["project_id"] != command.project_id
            or generation["workspace_id"] != command.workspace_id
            or generation["book_id"] != command.book_id
            or generation["generation_operation_id"] != command.generation_operation_id
            or generation["generator_operation_name"]
            != command.generator_operation_name
            or generation["content_hash"] != command.candidate_content_hash
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_LINEAGE_INVALID",
                "Planning Evaluation differs from the frozen candidate lineage",
            )
        state = self.story_design.require(
            project_id=command.project_id,
            asset_version_id=command.candidate_asset_version_id,
        )
        if state["qualification"] != "STRUCTURALLY_VALID":
            raise KernelError(
                "NARRATIVE_EVALUATION_CANDIDATE_NOT_READY",
                "Narrative Evaluation requires a structurally valid immutable candidate",
            )
        evaluated = self.semantic_evaluation.execute(
            NarrativeSemanticEvaluationCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=command.actor_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                generator_operation_name=command.generator_operation_name,
                candidate_content_hash=command.candidate_content_hash,
                evaluator_execution_class=command.evaluator_execution_class,
                evaluation=(
                    None if command.evaluation is None else dict(command.evaluation)
                ),
                evidence_asset_version_ids=command.evidence_asset_version_ids,
                idempotency_key=command.idempotency_key,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            ),
            principal=principal,
            caller_permission="story_planning.authority.execute",
        )
        generation_command = self._generation_command(command.generation_operation_id)
        if evaluated.qualification.status != "PASS":
            return self._repair_or_reject(
                operation_id=command.generation_operation_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                candidate_content_hash=command.candidate_content_hash,
                command=generation_command,
                principal=transition_principal,
                definition=GENERATOR_CATALOG[command.generator_operation_name],
                error=KernelError(
                    "NARRATIVE_SEMANTIC_QUALIFICATION_FAILED",
                    "independent Narrative Evaluation did not pass",
                ),
            )
        return self._advance_candidate(
            operation_id=command.generation_operation_id,
            candidate_asset_version_id=command.candidate_asset_version_id,
            candidate_content_hash=command.candidate_content_hash,
            command=generation_command,
            principal=transition_principal,
            replayed=evaluated.replayed,
            definition=GENERATOR_CATALOG[command.generator_operation_name],
        )

    def _evaluate_pending_if_required(
        self,
        *,
        advanced: PlanningGenerationResult,
        generation_command: StoryPlanningGenerationCommand,
        principal: Principal,
    ) -> PlanningGenerationResult:
        if advanced.status is not PlanningGenerationStatus.EVALUATION_PENDING:
            return advanced
        candidate = self._require_asset(
            project_id=generation_command.project_id,
            asset_version_id=advanced.candidate_asset_version_id,
        )
        execution = dict(candidate["content"].get("execution_evidence") or {})
        fixture = bool(execution.get("fixture_protocol_only"))
        evaluator_principal = (
            principal if fixture else self.narrative_evaluator_principal
        )
        if evaluator_principal is None:
            raise KernelError(
                "NARRATIVE_EVALUATION_PRINCIPAL_REQUIRED",
                "production Planning evaluation has no independent trusted Principal",
            )
        return self.evaluate_candidate(
            StoryPlanningEvaluationCommand(
                project_id=generation_command.project_id,
                workspace_id=generation_command.workspace_id,
                book_id=generation_command.book_id,
                actor_id=evaluator_principal.principal_id,
                candidate_asset_version_id=advanced.candidate_asset_version_id,
                generation_operation_id=advanced.generation_operation_id,
                generator_operation_name=generation_command.generator_operation_name,
                candidate_content_hash=str(candidate["content_hash"]),
                evaluator_execution_class=(
                    "SCRIPTED_FIXTURE" if fixture else "MODEL_PROVIDER"
                ),
                evaluation=(
                    scripted_qualification(generation_command.generator_operation_name)
                    if fixture
                    else None
                ),
                idempotency_key=(
                    f"{generation_command.idempotency_key}:semantic-evaluation"
                ),
                trace_id=generation_command.trace_id,
                correlation_id=generation_command.correlation_id,
            ),
            principal=evaluator_principal,
            transition_principal=principal,
        )

    def approve_candidate(
        self,
        candidate_asset_version_id: str,
        *,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        generation = self.require_candidate(candidate_asset_version_id)
        principal.require("story_planning.authority.approve", generation["project_id"])
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        if state["approval"] == "APPROVED":
            return state
        if state["approval"] != "PENDING":
            raise KernelError(
                "PLANNING_CANDIDATE_NOT_APPROVABLE",
                "Planning candidate is not waiting for approval",
            )
        approved = self.story_design.transition(
            StoryDesignTransitionCommand(
                project_id=generation["project_id"],
                workspace_id=generation["workspace_id"],
                actor_id=principal.principal_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                asset_version_id=candidate_asset_version_id,
                content_hash=generation["content_hash"],
                logical_key=generation["logical_key"],
                generator_operation_name=generation["generator_operation_name"],
                transition=DesignTransition.APPROVE,
                planning_scope=generation["planning_scope"],
                expected_version=int(state["version"]),
                evidence={
                    "approval_policy_key": generation["approval_policy_key"],
                    "approved_by": principal.principal_id,
                },
            ),
            principal=principal,
        )
        self._update_generation_status(
            generation["generation_operation_id"], "APPROVED"
        )
        return approved

    def activate_candidate(
        self,
        candidate_asset_version_id: str,
        *,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        expected_active_asset_version_id: str = "",
        replacement_approved: bool = False,
        decision_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        generation = self.require_candidate(candidate_asset_version_id)
        principal.require("story_planning.authority.activate", generation["project_id"])
        generation_record = self.require_generation(
            generation["generation_operation_id"]
        )
        if str(generation_record["status"]) != "ACTIVE":
            self._require_generation_inputs_current(
                operation_id=generation["generation_operation_id"],
                project_id=generation["project_id"],
                book_id=generation["book_id"],
            )
        self._require_narrative_qualification_summary(
            operation_id=generation["generation_operation_id"],
            candidate_asset_version_id=candidate_asset_version_id,
            project_id=generation["project_id"],
            book_id=generation["book_id"],
            generator_operation_name=generation["generator_operation_name"],
        )
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        if state["lifecycle"] != "ACTIVE":
            if state["approval"] != "APPROVED":
                raise KernelError(
                    "PLANNING_CANDIDATE_APPROVAL_REQUIRED",
                    "Planning candidate activation requires an approval decision",
                )
            state = self.story_design.transition(
                StoryDesignTransitionCommand(
                    project_id=generation["project_id"],
                    workspace_id=generation["workspace_id"],
                    actor_id=principal.principal_id,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}:story-design",
                    asset_version_id=candidate_asset_version_id,
                    content_hash=generation["content_hash"],
                    logical_key=generation["logical_key"],
                    generator_operation_name=generation["generator_operation_name"],
                    transition=DesignTransition.ACTIVATE,
                    planning_scope=generation["planning_scope"],
                    expected_version=int(state["version"]),
                    evidence={
                        "activation_policy_key": generation["activation_policy_key"]
                    },
                ),
                principal=principal,
            )
        binding = self.planning.bind_active_contract(
            project_id=generation["project_id"],
            workspace_id=generation["workspace_id"],
            book_id=generation["book_id"],
            actor_id=principal.principal_id,
            asset_version_id=candidate_asset_version_id,
            contract_type=PlanContractType(generation["planning_scope"].value),
            parent_version_id=generation["parent_version_id"],
            execution_scope=PlanExecutionScope.PLANNED,
            expected_active_asset_version_id=expected_active_asset_version_id,
            replacement_approved=replacement_approved,
            decision_evidence=dict(decision_evidence or {}),
            idempotency_key=f"{idempotency_key}:planning-binding",
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_operation_id=generation["generation_operation_id"],
            principal=principal,
        )
        chapter_plan_projection = None
        if generation["planning_scope"].value == PlanContractType.CHAPTER.value:
            chapter_plan_projection = self._materialize_chapter_plan_projection(
                generation=generation,
                candidate_asset_version_id=candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{idempotency_key}:chapter-plan-projection",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        self._update_generation_status(generation["generation_operation_id"], "ACTIVE")
        return {
            "story_design": state,
            "planning_binding": binding,
            "chapter_plan_projection": chapter_plan_projection,
        }

    def _require_generation_inputs_current(
        self, *, operation_id: str, project_id: str, book_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT input_snapshot
                FROM authority_story_planning_generation
                WHERE operation_id=%s AND project_id=%s AND book_id=%s
                """,
                [operation_id, project_id, book_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_SNAPSHOT_MISSING",
                    "Planning activation requires its immutable generation inputs",
                )
            for item in row[0]:
                frozen = dict(item)
                asset_version_id = str(frozen.get("asset_version_id") or "")
                uow.cursor.execute(
                    """
                    SELECT asset.asset_type, version.content_hash,
                           version.lifecycle, version.eligibility,
                           version.governance, binding.freshness,
                           active.binding_id
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    LEFT JOIN story_plan_binding AS binding
                      ON binding.project_id=asset.project_id
                     AND binding.book_id=%s
                     AND binding.asset_version_id=version.asset_version_id
                    LEFT JOIN active_story_plan_version AS active
                      ON active.binding_id=binding.binding_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s
                    """,
                    [book_id, asset_version_id, project_id],
                )
                current = uow.cursor.fetchone()
                if (
                    current is None
                    or str(current[0]) != str(frozen.get("asset_type") or "")
                    or str(current[1]) != str(frozen.get("content_hash") or "")
                    or str(current[2]) != "ACTIVE"
                    or str(current[3]) != "ELIGIBLE"
                    or str(current[4]) != "CLEAR"
                    or (
                        current[5] is not None
                        and (str(current[5]) != "CURRENT" or current[6] is None)
                    )
                ):
                    raise KernelError(
                        "PLANNING_GENERATION_INPUT_STALE",
                        "Planning candidate input identity or currentness changed before activation",
                    )

    def _materialize_chapter_plan_projection(
        self,
        *,
        generation: dict[str, Any],
        candidate_asset_version_id: str,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Materialize the activated candidate as Chapter Runtime input.

        The generic candidate and typed Planning binding remain authoritative.
        This deterministic projection only gives the existing Chapter Runtime
        its strict physical ``chapter_plan`` input contract with explicit
        candidate and activation lineage.
        """

        definition = chapter_plan_projection_definition(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            candidate = self._require_asset(
                project_id=generation["project_id"],
                asset_version_id=candidate_asset_version_id,
            )
            uow.commit()

        def materialize(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            content = {
                **_chapter_runtime_projection(dict(candidate["content"])),
                "source_planning_candidate_asset_version_id": (
                    candidate_asset_version_id
                ),
                "source_planning_generation_operation_id": generation[
                    "generation_operation_id"
                ],
                "planning_activation": "ACTIVE",
                "physical_contract_type": "chapter_plan",
            }
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=generation["project_id"],
                    asset_id=f"chapter-plan:{candidate_asset_version_id}",
                    asset_type="chapter_plan",
                    schema_version="activated-chapter-plan.v1",
                    logical_ref=(
                        "story_planning/chapter_plans/"
                        f"{candidate_asset_version_id}.json"
                    ),
                    category="planning",
                    output_key="story_planning.chapter_plan_projection",
                    role="primary",
                    content=content,
                    qualification_policy="activated-planning-chapter-contract-v1",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    reference_asset_ids=(str(candidate["asset_id"]),),
                )
            )
            checkpoint("after_business_projection_update")
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "chapter_plan",
                    "aggregate_id": document.asset_version_id,
                    "operation_id": operation_id,
                    "project_id": generation["project_id"],
                    "event_type": "story_planning.chapter_plan.materialized",
                    "correlation_id": correlation_id,
                    "causation_id": generation["generation_operation_id"],
                    "payload": {
                        "operation_id": operation_id,
                        "asset_version_id": document.asset_version_id,
                        "source_planning_candidate_asset_version_id": (
                            candidate_asset_version_id
                        ),
                    },
                }
            )
            checkpoint("after_outbox_insert")
            return {
                "asset_version_id": document.asset_version_id,
                "content_hash": document.content_hash,
                "source_planning_candidate_asset_version_id": (
                    candidate_asset_version_id
                ),
            }

        return dict(
            execute_transaction_command(
                self.database_url,
                {
                    "definition_name": CHAPTER_PLAN_PROJECTION_DEFINITION,
                    "definition_version": "1.0.0",
                    "project_id": generation["project_id"],
                    "workspace_id": generation["workspace_id"],
                    "book_id": generation["book_id"],
                    "actor_id": principal.principal_id,
                    "idempotency_scope": "book:activated-chapter-plan",
                    "idempotency_key": idempotency_key,
                    "trace_id": trace_id,
                    "span_id": str(uuid4()),
                    "correlation_id": correlation_id,
                    "causation_id": generation["generation_operation_id"],
                    "causation_operation_id": generation["generation_operation_id"],
                    "input": {
                        "project_id": generation["project_id"],
                        "candidate_asset_version_id": candidate_asset_version_id,
                    },
                    "input_assets": [
                        {
                            "asset_version_id": candidate_asset_version_id,
                            "content_hash": candidate["content_hash"],
                        }
                    ],
                },
                context=AdmissionContext(
                    actor_id=principal.principal_id,
                    permissions=frozenset({"story_planning.authority.activate"}),
                    available_handlers=frozenset({CHAPTER_PLAN_PROJECTION_HANDLER}),
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                ),
                handler=materialize,
            )
        )

    def materialize_activated_chapter_plan_projection(
        self,
        candidate_asset_version_id: str,
        *,
        principal: Principal,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Use the same typed projection after PlanChange-owned activation."""

        generation = self.require_candidate(candidate_asset_version_id)
        if generation["planning_scope"].value != PlanContractType.CHAPTER.value:
            raise KernelError(
                "PLANNING_CHAPTER_PROJECTION_SCOPE_INVALID",
                "typed ChapterPlan projection requires a Chapter candidate",
            )
        state = self.story_design.require(
            project_id=generation["project_id"],
            asset_version_id=candidate_asset_version_id,
        )
        if state["lifecycle"] != "ACTIVE":
            raise KernelError(
                "PLANNING_CHAPTER_PROJECTION_ACTIVATION_REQUIRED",
                "typed ChapterPlan projection requires an Active candidate",
            )
        projection = self._materialize_chapter_plan_projection(
            generation=generation,
            candidate_asset_version_id=candidate_asset_version_id,
            principal=principal,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        self._update_generation_status(generation["generation_operation_id"], "ACTIVE")
        return projection

    def require_generation(self, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT generation_id, operation_id, project_id, workspace_id,
                       book_id, generator_operation_name, planning_scope,
                       logical_key, input_snapshot, input_snapshot_hash,
                       status, candidate_asset_version_id,
                       repair_of_candidate_id, repair_number, version
                FROM authority_story_planning_generation
                WHERE operation_id=%s
                """,
                [operation_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_GENERATION_NOT_FOUND", "Planning Generation does not exist"
            )
        fields = (
            "generation_id",
            "operation_id",
            "project_id",
            "workspace_id",
            "book_id",
            "generator_operation_name",
            "planning_scope",
            "logical_key",
            "input_snapshot",
            "input_snapshot_hash",
            "status",
            "candidate_asset_version_id",
            "repair_of_candidate_id",
            "repair_number",
            "version",
        )
        return dict(zip(fields, row, strict=True))

    def _generation_command(self, operation_id: str) -> StoryPlanningGenerationCommand:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT command_payload->'payload'
                FROM authority_operation
                WHERE operation_id=%s
                  AND definition_name=%s
                """,
                [operation_id, STORY_PLANNING_GENERATION_DEFINITION],
            )
            row = uow.cursor.fetchone()
        if row is None or not isinstance(row[0], dict):
            raise KernelError(
                "PLANNING_GENERATION_COMMAND_MISSING",
                "frozen Planning Generation command is unavailable",
            )
        return _command_from_payload(dict(row[0]))

    def require_candidate(self, candidate_asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT generation.operation_id, generation.project_id,
                       generation.workspace_id, generation.book_id,
                       generation.generator_operation_name,
                       generation.planning_scope, generation.logical_key,
                       generation.parent_version_id,
                       design_state.generator_definition_version,
                       candidate.content_hash,
                       definition.definition->>'approval_policy_key',
                       definition.definition->>'activation_policy_key'
                FROM authority_story_planning_candidate AS candidate
                JOIN authority_story_planning_generation AS generation
                  ON generation.generation_id=candidate.generation_id
                JOIN authority_story_design_version_state AS design_state
                  ON design_state.project_id=generation.project_id
                 AND design_state.asset_version_id=
                     candidate.candidate_asset_version_id
                 AND design_state.logical_key=generation.logical_key
                 AND design_state.generator_operation_name=
                     generation.generator_operation_name
                JOIN authority_story_design_generator_definition AS definition
                  ON definition.operation_name=
                     design_state.generator_operation_name
                 AND definition.definition_version=
                     design_state.generator_definition_version
                WHERE candidate.candidate_asset_version_id=%s
                """,
                [candidate_asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_CANDIDATE_NOT_FOUND", "Planning candidate does not exist"
            )
        fields = (
            "generation_operation_id",
            "project_id",
            "workspace_id",
            "book_id",
            "generator_operation_name",
            "planning_scope",
            "logical_key",
            "parent_version_id",
            "generator_definition_version",
            "content_hash",
            "approval_policy_key",
            "activation_policy_key",
        )
        result = dict(zip(fields, row, strict=True))
        from novel_forge.modules.story_design_authority import PlanningScope

        result["planning_scope"] = PlanningScope(str(result["planning_scope"]))
        result["parent_version_id"] = str(result["parent_version_id"] or "")
        return result

    def _advance_candidate(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        command: StoryPlanningGenerationCommand,
        principal: Principal,
        replayed: bool,
        definition: Any,
    ) -> PlanningGenerationResult:
        try:
            state = self.story_design.require(
                project_id=command.project_id,
                asset_version_id=candidate_asset_version_id,
            )
        except KernelError as exc:
            if exc.code != "STORY_DESIGN_CANDIDATE_NOT_FOUND":
                raise
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.ENROLL,
                expected_version=0,
                evidence=self._candidate_evidence(candidate_asset_version_id),
            )
        if state["lifecycle"] == "ACTIVE":
            try:
                binding = self.planning.require_binding(
                    project_id=command.project_id,
                    asset_version_id=candidate_asset_version_id,
                )
            except KernelError as exc:
                if (
                    exc.code != "PLANNING_BINDING_NOT_FOUND"
                    or definition.risk_class == "HIGH"
                    or not command.auto_approve_low_risk
                ):
                    raise
                recovered = self.activate_candidate(
                    candidate_asset_version_id,
                    principal=principal,
                    idempotency_key=f"{command.idempotency_key}:auto-activate",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
                binding = recovered["planning_binding"]
            self._update_generation_status(operation_id, "ACTIVE")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.ACTIVE,
                state,
                binding,
                replayed,
            )
        if state["approval"] == "APPROVED":
            self._update_generation_status(operation_id, "APPROVED")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.APPROVED,
                state,
                replayed=replayed,
            )
        if state["lifecycle"] == "REJECTED":
            self._update_generation_status(operation_id, "REJECTED")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.REJECTED,
                state,
                replayed=replayed,
            )
        if state["lifecycle"] == "CANDIDATE":
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.MATERIALIZE,
                expected_version=int(state["version"]),
                evidence={"generation_operation_id": operation_id},
            )
        if state["lifecycle"] == "MATERIALIZED" and state["qualification"] == "PENDING":
            content = self._require_asset(
                project_id=command.project_id,
                asset_version_id=candidate_asset_version_id,
            )["content"]
            try:
                validation = validate_story_design_candidate(
                    content=content,
                    project_id=command.project_id,
                    generator_operation_name=command.generator_operation_name,
                    planning_scope=command.planning_scope,
                    logical_key=command.logical_key,
                )
                contract = validate_planning_contract(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    contract_type=PlanContractType(command.planning_scope.value),
                    asset_version_id=candidate_asset_version_id,
                    parent_version_id=command.parent_version_id,
                    execution_scope=PlanExecutionScope.PLANNED,
                    content=content,
                )
                if command.generator_operation_name == "arc_plan.generate":
                    expected_volume_scope = {
                        command.input_versions["volume_plan"],
                        *command.arc_scope_volume_plan_version_ids,
                    }
                    declared_volume_scope = {
                        str(item) for item in content.get("cross_volume_scope") or ()
                    }
                    if declared_volume_scope != expected_volume_scope:
                        raise KernelError(
                            "NARRATIVE_ARC_AUTHORITY_SCOPE_MISMATCH",
                            "Arc cross_volume_scope must exactly match frozen Active VolumePlan versions",
                        )
                _validate_frozen_arc_references(command, content)
                if contract.logical_key != command.logical_key:
                    raise KernelError(
                        "PLANNING_LOGICAL_KEY_MISMATCH",
                        "Planning Candidate content differs from the admitted logical key",
                    )
            except KernelError as exc:
                return self._repair_or_reject(
                    operation_id=operation_id,
                    candidate_asset_version_id=candidate_asset_version_id,
                    candidate_content_hash=candidate_content_hash,
                    command=command,
                    principal=principal,
                    definition=definition,
                    error=exc,
                )
            evidence = {
                **validation.to_evidence(),
                "planning_contract": {
                    "contract_type": contract.contract_type.value,
                    "logical_key": contract.logical_key,
                    "parent_version_id": contract.parent_version_id,
                    "execution_scope": contract.execution_scope.value,
                },
            }
            self._record_validation(
                operation_id=operation_id,
                candidate_asset_version_id=candidate_asset_version_id,
                validation_kind="COMBINED",
                status="PASS",
                report=evidence,
            )
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.STRUCTURAL_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": True, "validation_report": evidence},
            )
        if state["qualification"] == "STRUCTURALLY_VALID":
            try:
                qualification = self._require_narrative_qualification_summary(
                    operation_id=operation_id,
                    candidate_asset_version_id=candidate_asset_version_id,
                    project_id=command.project_id,
                    book_id=command.book_id,
                    generator_operation_name=command.generator_operation_name,
                )
            except KernelError as exc:
                if exc.code != "NARRATIVE_QUALIFICATION_RECEIPT_INCOMPLETE":
                    raise
                self._update_generation_status(operation_id, "EVALUATION_PENDING")
                return PlanningGenerationResult(
                    operation_id,
                    candidate_asset_version_id,
                    PlanningGenerationStatus.EVALUATION_PENDING,
                    state,
                    replayed=replayed,
                )
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.SEMANTIC_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": True, **qualification},
            )
        if state["qualification"] == "SEMANTICALLY_VALID":
            qualification = self._require_narrative_qualification_summary(
                operation_id=operation_id,
                candidate_asset_version_id=candidate_asset_version_id,
                project_id=command.project_id,
                book_id=command.book_id,
                generator_operation_name=command.generator_operation_name,
            )
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.QUALIFY,
                expected_version=int(state["version"]),
                evidence={"passed": True, **qualification},
            )
        if state["qualification"] == "QUALIFIED":
            self._set_candidate_eligibility(
                project_id=command.project_id,
                candidate_asset_version_id=candidate_asset_version_id,
                eligibility="ELIGIBLE",
            )
        if (
            state["qualification"] == "QUALIFIED"
            and state["approval"] == "NOT_REQUESTED"
        ):
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.SUBMIT_APPROVAL,
                expected_version=int(state["version"]),
                evidence={"approval_policy_key": definition.approval_policy_key},
            )
        self._update_generation_status(operation_id, "APPROVAL_PENDING")
        if definition.risk_class != "HIGH" and command.auto_approve_low_risk:
            state = self.approve_candidate(
                candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{command.idempotency_key}:auto-approve",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            activated = self.activate_candidate(
                candidate_asset_version_id,
                principal=principal,
                idempotency_key=f"{command.idempotency_key}:auto-activate",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.ACTIVE,
                state,
                activated["planning_binding"],
                replayed,
            )
        return PlanningGenerationResult(
            operation_id,
            candidate_asset_version_id,
            PlanningGenerationStatus.APPROVAL_PENDING,
            state,
            replayed=replayed,
        )

    def _repair_or_reject(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        command: StoryPlanningGenerationCommand,
        principal: Principal,
        definition: Any,
        error: KernelError,
    ) -> PlanningGenerationResult:
        semantic = error.code in {
            "STORY_DESIGN_SEMANTIC_INVALID",
            "NARRATIVE_SEMANTIC_EVALUATION_REQUIRED",
            "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
            "NARRATIVE_SEMANTIC_PROFILE_DRIFT",
            "NARRATIVE_SEMANTIC_QUALIFICATION_FAILED",
        }
        validation_kind = "SEMANTIC" if semantic else "STRUCTURAL"
        report = {
            "status": "FAIL",
            "validation_kind": validation_kind,
            "error_code": error.code,
            "message": error.message,
            "candidate_asset_version_id": candidate_asset_version_id,
        }
        report_hash = self._record_validation(
            operation_id=operation_id,
            candidate_asset_version_id=candidate_asset_version_id,
            validation_kind=validation_kind,
            status="FAIL",
            report=report,
        )
        state = self.story_design.require(
            project_id=command.project_id,
            asset_version_id=candidate_asset_version_id,
        )
        if semantic:
            state = self._transition(
                command,
                principal,
                candidate_asset_version_id,
                candidate_content_hash,
                DesignTransition.STRUCTURAL_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": True, "validation_report_hash": report_hash},
            )
            transition = DesignTransition.SEMANTIC_VALIDATE
            maximum = definition.maximum_semantic_repairs
        else:
            transition = DesignTransition.STRUCTURAL_VALIDATE
            maximum = definition.maximum_structural_regenerations
        state = self._transition(
            command,
            principal,
            candidate_asset_version_id,
            candidate_content_hash,
            transition,
            expected_version=int(state["version"]),
            evidence={"passed": False, "validation_report_hash": report_hash},
        )
        if command.repair_number >= maximum:
            self._update_generation_status(operation_id, "REJECTED")
            return PlanningGenerationResult(
                operation_id,
                candidate_asset_version_id,
                PlanningGenerationStatus.REJECTED,
                state,
            )
        self._update_generation_status(operation_id, "REPAIR_REQUIRED")
        repaired = StoryPlanningGenerationCommand(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            actor_id=command.actor_id,
            generator_operation_name=command.generator_operation_name,
            logical_key=command.logical_key,
            input_versions=dict(command.input_versions),
            idempotency_key=(
                f"{command.idempotency_key}:repair:{command.repair_number + 1}"
            ),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            parent_version_id=command.parent_version_id,
            arc_scope_volume_plan_version_ids=(
                command.arc_scope_volume_plan_version_ids
            ),
            related_arc_plan_version_ids=command.related_arc_plan_version_ids,
            dependent_arc_plan_version_ids=command.dependent_arc_plan_version_ids,
            change_evidence_version_ids=command.change_evidence_version_ids,
            governance_action_version_ids=command.governance_action_version_ids,
            repair_of_candidate_id=candidate_asset_version_id,
            repair_reason=f"{error.code}:{report_hash}",
            repair_number=command.repair_number + 1,
            auto_approve_low_risk=command.auto_approve_low_risk,
            arc_working_set=command.arc_working_set,
        )
        return self.generate(repaired, principal=principal)

    def _transition(
        self,
        command: StoryPlanningGenerationCommand,
        principal: Principal,
        candidate_asset_version_id: str,
        content_hash: str,
        transition: DesignTransition,
        *,
        expected_version: int,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return self.story_design.transition(
            StoryDesignTransitionCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                actor_id=command.actor_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                idempotency_key=(
                    f"{command.idempotency_key}:story-design:{transition.value}:"
                    f"{candidate_asset_version_id}:v{expected_version}"
                ),
                asset_version_id=candidate_asset_version_id,
                content_hash=content_hash,
                logical_key=command.logical_key,
                generator_operation_name=command.generator_operation_name,
                transition=transition,
                planning_scope=command.planning_scope,
                expected_version=expected_version,
                evidence=evidence,
            ),
            principal=principal,
        )

    def _candidate_evidence(self, candidate_asset_version_id: str) -> dict[str, Any]:
        content = self._require_asset_by_id(candidate_asset_version_id)["content"]
        evidence = dict(content.get("execution_evidence") or {})
        if not evidence:
            raise KernelError(
                "PLANNING_CANDIDATE_EXECUTION_EVIDENCE_MISSING",
                "materialized Planning Candidate lacks PEP evidence",
            )
        return evidence

    def _resolve_inputs(
        self, command: StoryPlanningGenerationCommand
    ) -> tuple[FrozenPlanningInput, ...]:
        authority_roles = _authority_role_versions(command)
        plan_input_ids = [
            asset_version_id
            for role, asset_version_id in authority_roles.items()
            if role in _PLAN_INPUT_CONTRACTS
            or role.startswith("arc_scope_volume:")
            or role.startswith("related_arc:")
            or role.startswith("dependent_arc:")
            or role == "chapter_function_matrix_row"
        ]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, workspace_id
                FROM authority_book
                WHERE book_id=%s
                """,
                [command.book_id],
            )
            book = uow.cursor.fetchone()
            if book != (command.project_id, command.workspace_id):
                raise KernelError(
                    "PLANNING_GENERATION_BOOK_SCOPE_INVALID",
                    "Planning Generation Book belongs to another Project or Workspace",
                )
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_type,
                       version.content_hash, version.content,
                       NOT EXISTS (
                           SELECT 1
                           FROM authority_asset_supersession AS supersession
                           WHERE supersession.previous_asset_version_id=
                                 version.asset_version_id
                       ) AS is_current_version
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [command.project_id, list(authority_roles.values())],
            )
            rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.contract_type,
                       binding.parent_version_id
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.project_id=binding.project_id
                 AND active.book_id=binding.book_id
                 AND active.binding_id=binding.binding_id
                 AND active.asset_version_id=binding.asset_version_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.asset_version_id=ANY(%s::text[])
                  AND binding.freshness='CURRENT'
                """,
                [command.project_id, command.book_id, plan_input_ids],
            )
            plan_rows = uow.cursor.fetchall()
        by_id = {
            str(row[0]): {
                "asset_type": str(row[1]),
                "content_hash": str(row[2]),
                "content": dict(row[3]),
                "is_current_version": bool(row[4]),
            }
            for row in rows
        }
        plan_by_id = {
            str(row[0]): {
                "contract_type": PlanContractType(str(row[1])),
                "parent_version_id": str(row[2] or ""),
            }
            for row in plan_rows
        }
        missing = sorted(set(authority_roles.values()) - set(by_id))
        if missing:
            raise KernelError(
                "PLANNING_GENERATION_INPUT_AUTHORITY_INVALID",
                "Planning inputs are missing, ineligible, or outside Project scope: "
                + ", ".join(missing),
            )
        result: list[FrozenPlanningInput] = []
        for role, asset_version_id in authority_roles.items():
            item = by_id[asset_version_id]
            expected_contract = (
                PlanContractType.VOLUME
                if role.startswith("arc_scope_volume:")
                else PlanContractType.ARC
                if role.startswith(("related_arc:", "dependent_arc:"))
                else _PLAN_INPUT_CONTRACTS.get(role)
            )
            if expected_contract is not None:
                plan = plan_by_id.get(asset_version_id)
                if plan is None or plan["contract_type"] is not expected_contract:
                    raise KernelError(
                        "PLANNING_GENERATION_INPUT_ROLE_INVALID",
                        f"Authority input {role} is not the current Active "
                        f"{expected_contract.value} Plan for this Book",
                    )
            elif role == "chapter_function_matrix_row" and (
                item["asset_type"] not in {role, "chapter_function_matrix"}
                and (
                    asset_version_id not in plan_by_id
                    or plan_by_id[asset_version_id]["contract_type"]
                    is not PlanContractType.CHAPTER_GROUP
                    or not isinstance(
                        item["content"].get("chapter_function_matrix"), list
                    )
                )
            ):
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_ROLE_INVALID",
                    "chapter_function_matrix_row must be a typed Authority asset "
                    "or the current Active ChapterGroupPlan containing the matrix",
                )
            elif role.startswith("narrative_governance_action:"):
                if (
                    item["asset_type"]
                    not in {"governance_decision", "narrative_governance_action"}
                    or not item["is_current_version"]
                ):
                    raise KernelError(
                        "PLANNING_GENERATION_GOVERNANCE_ACTION_INVALID",
                        "Narrative governance action must be current typed Authority evidence",
                    )
            elif role != "chapter_function_matrix_row":
                allowed_asset_types = _AUTHORITY_INPUT_ASSET_TYPES.get(
                    role, frozenset({role})
                )
                if item["asset_type"] not in allowed_asset_types:
                    raise KernelError(
                        "PLANNING_GENERATION_INPUT_ROLE_INVALID",
                        f"Authority input {role} has asset type {item['asset_type']}",
                    )
            declared_book = str(item["content"].get("book_id") or "")
            if declared_book and declared_book != command.book_id:
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_BOOK_INVALID",
                    f"Authority input {role} belongs to another Book",
                )
            result.append(
                FrozenPlanningInput(
                    role=role,
                    asset_version_id=asset_version_id,
                    content_hash=item["content_hash"],
                    asset_type=item["asset_type"],
                )
            )
        expected_parent_role = {
            "volume_plan.generate": "book_plan",
            "chapter_group_plan.generate": "volume_plan",
            "chapter_plan.generate": "chapter_group_plan",
        }.get(command.generator_operation_name)
        if expected_parent_role is None:
            if command.parent_version_id:
                raise KernelError(
                    "PLANNING_GENERATION_PARENT_INVALID",
                    f"{command.planning_scope.value} generation cannot declare a "
                    "containment parent Plan",
                )
        elif command.parent_version_id != command.input_versions[expected_parent_role]:
            raise KernelError(
                "PLANNING_GENERATION_PARENT_INVALID",
                f"{command.planning_scope.value} parent must equal the frozen "
                f"{expected_parent_role} Authority version",
            )
        plan_relationships = (
            ("volume_plan", "book_plan"),
            ("chapter_group_plan", "volume_plan"),
        )
        for child_role, parent_role in plan_relationships:
            child_id = command.input_versions.get(child_role)
            parent_id = command.input_versions.get(parent_role)
            if not child_id or not parent_id:
                continue
            if plan_by_id[child_id]["parent_version_id"] != parent_id:
                raise KernelError(
                    "PLANNING_GENERATION_INPUT_HIERARCHY_INVALID",
                    f"Authority input {child_role} is not a child of the frozen "
                    f"{parent_role} version",
                )
        governed_by_id = {
            item.asset_version_id: item
            for item in result
            if item.role.startswith("narrative_governance_action:")
        }
        for item in by_id.values():
            content = item["content"]
            envelope = content.get("constraint_envelope")
            policy = (
                envelope.get("narrative_load_policy")
                if isinstance(envelope, dict)
                else content.get("narrative_load_policy")
            )
            if not isinstance(policy, dict):
                continue
            for override in policy.get("governed_overrides") or ():
                if not isinstance(override, dict):
                    continue
                action_id = str(
                    override.get("governance_action_asset_version_id") or ""
                )
                action_hash = str(override.get("governance_action_content_hash") or "")
                frozen = governed_by_id.get(action_id)
                if frozen is None or frozen.content_hash != action_hash:
                    raise KernelError(
                        "PLANNING_GENERATION_GOVERNANCE_ACTION_UNBOUND",
                        "Narrative Load override is not bound to exact governance Authority evidence",
                    )
        return tuple(result)

    def _resolve_change_evidence(
        self, command: StoryPlanningGenerationCommand
    ) -> tuple[FrozenPlanningInput, ...]:
        if not command.change_evidence_version_ids:
            return ()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_type,
                       version.content_hash, version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [command.project_id, list(command.change_evidence_version_ids)],
            )
            rows = uow.cursor.fetchall()
        by_id = {str(row[0]): row for row in rows}
        if set(by_id) != set(command.change_evidence_version_ids):
            raise KernelError(
                "PLANNING_GENERATION_CHANGE_EVIDENCE_INVALID",
                "Planning change evidence is missing or outside Authority scope",
            )
        result: list[FrozenPlanningInput] = []
        for ordinal, asset_version_id in enumerate(
            command.change_evidence_version_ids, start=1
        ):
            row = by_id[asset_version_id]
            asset_type = str(row[1])
            content = dict(row[3])
            if asset_type not in {"longform_recap", "replan_request"}:
                raise KernelError(
                    "PLANNING_GENERATION_CHANGE_EVIDENCE_TYPE_INVALID",
                    "Planning change evidence must be a Recap or ReplanRequest",
                )
            declared_book = str(content.get("book_id") or "")
            if declared_book and declared_book != command.book_id:
                raise KernelError(
                    "PLANNING_GENERATION_CHANGE_EVIDENCE_BOOK_INVALID",
                    "Planning change evidence belongs to another Book",
                )
            result.append(
                FrozenPlanningInput(
                    role=f"change_evidence:{ordinal}",
                    asset_version_id=asset_version_id,
                    content_hash=str(row[2]),
                    asset_type=asset_type,
                )
            )
        return tuple(result)

    def _record_generation(
        self,
        *,
        operation_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
    ) -> None:
        snapshot = [asdict(item) for item in inputs]
        snapshot_hash = canonical_hash(snapshot)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_planning_generation(
                    generation_id, operation_id, project_id, workspace_id,
                    book_id, generator_operation_name, planning_scope,
                    logical_key, parent_version_id, input_snapshot,
                    input_snapshot_hash, status, repair_of_candidate_id,
                    repair_reason, repair_number
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''),
                    %s, %s, 'ADMITTED', NULLIF(%s, ''), NULLIF(%s, ''), %s
                )
                ON CONFLICT (operation_id) DO NOTHING
                """,
                [
                    f"planning-generation:{operation_id}",
                    operation_id,
                    command.project_id,
                    command.workspace_id,
                    command.book_id,
                    command.generator_operation_name,
                    command.planning_scope.value,
                    command.logical_key,
                    command.parent_version_id,
                    Jsonb(snapshot),
                    snapshot_hash,
                    command.repair_of_candidate_id,
                    command.repair_reason,
                    command.repair_number,
                ],
            )
            uow.commit()

    def _record_candidate(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        candidate_content_hash: str,
        command: StoryPlanningGenerationCommand,
        attempt_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_planning_candidate(
                    candidate_id, generation_id, project_id, book_id,
                    candidate_asset_version_id, content_hash,
                    attempt_id, repair_of_candidate_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, '')
                ) ON CONFLICT (generation_id) DO NOTHING
                """,
                [
                    f"planning-candidate:{candidate_asset_version_id}",
                    f"planning-generation:{operation_id}",
                    command.project_id,
                    command.book_id,
                    candidate_asset_version_id,
                    candidate_content_hash,
                    attempt_id,
                    command.repair_of_candidate_id,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_story_planning_generation
                SET candidate_asset_version_id=%s,
                    status='CANDIDATE_MATERIALIZED', version=version+1,
                    updated_at=NOW()
                WHERE operation_id=%s
                  AND (candidate_asset_version_id IS NULL
                       OR candidate_asset_version_id=%s)
                """,
                [candidate_asset_version_id, operation_id, candidate_asset_version_id],
            )
            uow.commit()

    def _record_validation(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        validation_kind: str,
        status: str,
        report: dict[str, Any],
    ) -> str:
        report_hash = canonical_hash(report)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_story_planning_validation_report(
                    validation_report_id, project_id,
                    candidate_asset_version_id, generation_operation_id,
                    validation_kind, status, report, report_hash
                )
                SELECT %s, generation.project_id, %s, %s, %s, %s, %s, %s
                FROM authority_story_planning_generation AS generation
                WHERE generation.operation_id=%s
                ON CONFLICT (candidate_asset_version_id, validation_kind, report_hash)
                DO NOTHING
                """,
                [
                    report_hash,
                    candidate_asset_version_id,
                    operation_id,
                    validation_kind,
                    status,
                    Jsonb(report),
                    report_hash,
                    operation_id,
                ],
            )
            uow.commit()
        return report_hash

    def _require_narrative_qualification_summary(
        self,
        *,
        operation_id: str,
        candidate_asset_version_id: str,
        project_id: str,
        book_id: str,
        generator_operation_name: str,
    ) -> dict[str, Any]:
        profiles = required_qualification_profiles(generator_operation_name)
        expected = {profile.layer.value: profile for profile in profiles}
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT design_layer, profile_id, profile_version, profile_hash,
                       evaluation_hash, qualification_hash,
                       evaluator_execution_class, evaluation_operation_id,
                       evaluation_attempt_id, evaluation_asset_version_id,
                       evaluation_evidence_hash
                FROM authority_narrative_design_qualification
                WHERE project_id=%s AND book_id=%s
                  AND asset_version_id=%s AND generation_operation_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                  AND (
                        evaluator_execution_class='MODEL_PROVIDER'
                        OR (%s AND evaluator_execution_class='SCRIPTED_FIXTURE')
                      )
                  AND (
                        evaluator_execution_class<>'MODEL_PROVIDER'
                        OR (
                            provider_model_call_asset_version_id IS NOT NULL
                            AND provider_model_call_content_hash IS NOT NULL
                            AND provider_evidence_hash IS NOT NULL
                            AND provider_result_hash IS NOT NULL
                            AND provider_route_snapshot_id IS NOT NULL
                        )
                      )
                ORDER BY design_layer
                """,
                [
                    project_id,
                    book_id,
                    candidate_asset_version_id,
                    operation_id,
                    self.allow_scripted_evaluation_fixture,
                ],
            )
            rows = uow.cursor.fetchall()
        by_layer = {str(row[0]): row for row in rows}
        if set(by_layer) != set(expected) or len(rows) != len(expected):
            raise KernelError(
                "NARRATIVE_QUALIFICATION_RECEIPT_INCOMPLETE",
                "Narrative Semantic Evaluation receipts are missing or ambiguous",
            )
        hashes: set[str] = set()
        receipts: list[dict[str, Any]] = []
        for layer in sorted(expected):
            row = by_layer[layer]
            profile = expected[layer]
            if tuple(str(item) for item in row[1:4]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "NARRATIVE_QUALIFICATION_RECEIPT_STALE",
                    "stored Narrative Qualification profile differs from current policy",
                )
            hashes.add(str(row[5]))
            receipts.append(
                {
                    "design_layer": layer,
                    "profile_hash": str(row[3]),
                    "evaluation_hash": str(row[4]),
                    "evaluator_execution_class": str(row[6]),
                    "evaluation_operation_id": str(row[7]),
                    "evaluation_attempt_id": str(row[8]),
                    "evaluation_asset_version_id": str(row[9]),
                    "evaluation_evidence_hash": str(row[10]),
                }
            )
        if len(hashes) != 1:
            raise KernelError(
                "NARRATIVE_QUALIFICATION_RECEIPT_INCONSISTENT",
                "layer receipts do not share one qualification identity",
            )
        return {
            "narrative_qualification_hash": hashes.pop(),
            "narrative_qualification_receipts": receipts,
        }

    def _update_generation_status(self, operation_id: str, status: str) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_story_planning_generation
                SET status=%s, version=version+1, updated_at=NOW()
                WHERE operation_id=%s AND status<>%s
                """,
                [status, operation_id, status],
            )
            uow.commit()

    def _set_candidate_eligibility(
        self,
        *,
        project_id: str,
        candidate_asset_version_id: str,
        eligibility: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_asset_version AS version
                SET eligibility=%s
                FROM authority_asset AS asset
                WHERE version.asset_version_id=%s
                  AND version.asset_id=asset.asset_id
                  AND asset.project_id=%s
                  AND version.lifecycle='CANDIDATE'
                  AND version.eligibility IN ('INELIGIBLE', %s)
                """,
                [
                    eligibility,
                    candidate_asset_version_id,
                    project_id,
                    eligibility,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "PLANNING_CANDIDATE_ELIGIBILITY_CONFLICT",
                    "Planning candidate eligibility changed outside qualification",
                )
            uow.cursor.execute(
                """
                SELECT evaluation_operation_id, qualification_hash
                FROM authority_narrative_design_qualification
                WHERE project_id=%s AND asset_version_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [project_id, candidate_asset_version_id],
            )
            receipt = uow.cursor.fetchone()
            if receipt is None:
                raise KernelError(
                    "PLANNING_CANDIDATE_QUALIFICATION_MISSING",
                    "Planning eligibility requires independent Narrative Qualification",
                )
            qualification_id = canonical_hash(
                {
                    "asset_version_id": candidate_asset_version_id,
                    "evaluation_operation_id": str(receipt[0]),
                    "decision": eligibility,
                }
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id,
                    policy_version, decision, evidence
                ) VALUES (
                    %s, %s, 'independent-narrative-evaluation-v1', %s, %s
                )
                ON CONFLICT (qualification_id) DO NOTHING
                """,
                [
                    qualification_id,
                    candidate_asset_version_id,
                    eligibility,
                    Jsonb(
                        {
                            "schema_version": "planning-semantic-evaluation.v1",
                            "evaluation_operation_id": str(receipt[0]),
                            "qualification_hash": str(receipt[1]),
                            "trust_boundary": "INDEPENDENT",
                        }
                    ),
                ],
            )
            uow.commit()

    def _require_asset(
        self, *, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        result = self._require_asset_by_id(asset_version_id)
        if result["project_id"] != project_id:
            raise KernelError(
                "PLANNING_ASSET_SCOPE_INVALID",
                "Planning asset belongs to another Project",
            )
        return result

    def _require_asset_by_id(self, asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.asset_id, asset.project_id,
                       asset.asset_type, version.content_hash, version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_ASSET_NOT_FOUND", "Planning asset does not exist"
            )
        return dict(
            zip(
                (
                    "asset_version_id",
                    "asset_id",
                    "project_id",
                    "asset_type",
                    "content_hash",
                    "content",
                ),
                row,
                strict=True,
            )
        )

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                story_planning_generation_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            for definition in GENERATOR_CATALOG.values():
                uow.repositories.story_design.register_generator(asdict(definition))
            uow.commit()


def chapter_plan_projection_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    command = {
        "type": "object",
        "required": ["project_id", "candidate_asset_version_id"],
        "properties": {
            "project_id": {"type": "string", "minLength": 1},
            "candidate_asset_version_id": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    result = {
        "type": "object",
        "required": [
            "asset_version_id",
            "content_hash",
            "source_planning_candidate_asset_version_id",
        ],
        "properties": {
            "asset_version_id": {"type": "string", "minLength": 1},
            "content_hash": {"type": "string", "minLength": 1},
            "source_planning_candidate_asset_version_id": {
                "type": "string",
                "minLength": 1,
            },
        },
        "additionalProperties": False,
    }
    return {
        "name": CHAPTER_PLAN_PROJECTION_DEFINITION,
        "definition_version": "1.0.0",
        "family": "story_planning",
        "command_schema_version": "story-planning-chapter-plan-projection.command.v1",
        "result_schema_version": "story-planning-chapter-plan-projection.result.v1",
        "enabled": True,
        "command_schema": command,
        "result_schema": result,
        "input_contract": command,
        "output_contract": {
            **result,
            "asset_type": "chapter_plan",
            "output_key": "story_planning.chapter_plan_projection",
            "role": "primary",
        },
        "handler_key": CHAPTER_PLAN_PROJECTION_HANDLER,
        "handler_contract_version": "story-planning-chapter-plan-projection-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["story_planning.authority.activate"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "candidate_activation_required": True,
            "lineage_required": True,
        },
        "idempotency_scope": "book:activated-chapter-plan",
        "concurrency_key_template": "book:{book_id}:chapter-plan-projection",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable_atomic"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only typed planning projection",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["chapter_authority"],
        "migration_owner": "story-planning-runtime",
        "completion_contract": {
            "version": "story-planning-chapter-plan-projection-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": "chapter_plan",
                    "output_key": "story_planning.chapter_plan_projection",
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_qualifications": [{"decision": "ELIGIBLE"}],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["story_planning.chapter_plan.materialized"],
        },
    }


def _chapter_runtime_projection(candidate: dict[str, Any]) -> dict[str, Any]:
    """Project one generated execution contract without inventing narrative state."""

    primary = str(candidate.get("primary_function") or "progression")
    objective = str(candidate.get("objective") or candidate.get("premise") or "")
    hook = str(candidate.get("ending_hook") or "the choice creates a new obligation")
    required_events = list(candidate.get("required_events") or ())
    required_payoffs = list(candidate.get("required_payoffs") or ())
    hard_constraints = list(candidate.get("hard_constraints") or ())
    return {
        **candidate,
        "chapter": int(
            candidate.get("chapter_number") or candidate.get("chapter") or 0
        ),
        "title": str(
            candidate.get("title")
            or (f"Chapter {int(candidate.get('chapter_number') or 0)}: {primary}")
        ),
        "premise": str(candidate.get("premise") or objective),
        "chapter_function": primary,
        "chapter_objective": objective,
        "scene_sequence": list(candidate.get("scene_plan") or required_events),
        "chapter_hook": hook,
        "conflict_chain": hard_constraints
        or ["the objective meets escalating resistance"],
        "emotional_curve": ["pressure", "choice", "consequence"],
        "suspense_curve": ["question", "complication", "earned hook"],
        "reader_promise_actions": required_payoffs
        or [str(candidate.get("promise_action") or "advance the central promise")],
        "protagonist_charm_mechanism": (
            "the protagonist accepts a visible cost to preserve agency"
        ),
        "information_reveals": required_events
        or ["the choice exposes a consequence hidden at entry"],
        "antagonist_pressure": "resistance intensifies before the chapter turn",
        "next_chapter_bridge": hook,
        "reward_setup": required_payoffs or ["the promised consequence is prepared"],
        "reward_payoff": required_payoffs or ["the chapter pays a local consequence"],
        "conflict_escalation": ["resistance", "choice", "irreversible cost"],
        "chapter_intent": candidate.get("chapter_intent"),
        "arc_schedule": list(candidate.get("arc_schedule") or ()),
        "setups": list(candidate.get("setups") or ()),
        "payoffs": list(candidate.get("payoffs") or ()),
        "character_participation": list(candidate.get("character_participation") or ()),
        "knowledge_boundaries": list(candidate.get("knowledge_boundaries") or ()),
        "disclosures": list(candidate.get("disclosures") or ()),
        "required_state_transitions": list(
            candidate.get("required_state_transitions") or ()
        ),
        "reader_experience": dict(candidate.get("reader_experience") or {}),
        "scene_plan": list(candidate.get("scene_plan") or ()),
        "expected_exit_state": dict(candidate.get("expected_exit_state") or {}),
        "narrative_segment_ref": dict(candidate.get("narrative_segment_ref") or {}),
        "narrative_architecture_version": str(
            candidate.get("narrative_architecture_version") or ""
        ),
    }


def story_planning_generation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string"},
            "input_asset_version_ids": {"type": "array", "minItems": 1},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    return {
        "name": STORY_PLANNING_GENERATION_DEFINITION,
        "definition_version": STORY_PLANNING_GENERATION_VERSION,
        "family": "story_planning_runtime",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "story-planning-generation-command-v1",
        "result_schema_version": "story-planning-generation-result-v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {
            "asset_type": "planning_generation_candidate",
            "output_key": "story_planning.candidate",
        },
        "handler_key": STORY_PLANNING_GENERATION_HANDLER,
        "handler_contract_version": "story-planning-generation-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["story_planning.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "candidate_only": True,
            "story_design_activation_separate": True,
            "semantic_evaluation_operation_separate": True,
            "repair_candidate_asset_input_allowed": True,
            "capability_pack_attempt_snapshot_required": True,
            "agent_runtime_binding_required": True,
            "production_execution_gateway_required": True,
            "high_risk_auto_approval": False,
        },
        "idempotency_scope": "book:story-planning-generation",
        "concurrency_key_template": "book:{book_id}:planning:{logical_key}",
        "retry_policy": {
            "max_attempts": STORY_PLANNING_MAX_ATTEMPTS,
            "dead_letter_on_exhausted": True,
        },
        "timeout_policy": {
            "operation_timeout_seconds": STORY_PLANNING_OPERATION_TIMEOUT_SECONDS
        },
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only candidates and validation evidence",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": ["model.planning"],
        "projection_consumers": [
            "story_design_authority",
            "hierarchical_planning_authority",
        ],
        "migration_owner": "story-planning-runtime",
        "completion_contract": {
            "version": "story-planning-generation-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": "planning_generation_candidate",
                    "output_key": "story_planning.candidate",
                    "role": "primary",
                    "lifecycle": "CANDIDATE",
                    "eligibility": "INELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit", "cost_when_provider_used"],
            "required_outbox_events": ["story_planning.candidate.materialized"],
        },
    }


def _command_payload(command: StoryPlanningGenerationCommand) -> dict[str, Any]:
    return {
        "project_id": command.project_id,
        "workspace_id": command.workspace_id,
        "book_id": command.book_id,
        "actor_id": command.actor_id,
        "generator_operation_name": command.generator_operation_name,
        "logical_key": command.logical_key,
        "input_versions": dict(command.input_versions),
        "idempotency_key": command.idempotency_key,
        "trace_id": command.trace_id,
        "correlation_id": command.correlation_id,
        "parent_version_id": command.parent_version_id,
        "arc_scope_volume_plan_version_ids": list(
            command.arc_scope_volume_plan_version_ids
        ),
        "related_arc_plan_version_ids": list(command.related_arc_plan_version_ids),
        "dependent_arc_plan_version_ids": list(command.dependent_arc_plan_version_ids),
        "change_evidence_version_ids": list(command.change_evidence_version_ids),
        "governance_action_version_ids": list(command.governance_action_version_ids),
        "repair_of_candidate_id": command.repair_of_candidate_id,
        "repair_reason": command.repair_reason,
        "repair_number": command.repair_number,
        "auto_approve_low_risk": command.auto_approve_low_risk,
        "parent_agent_session_operation_id": (
            command.parent_agent_session_operation_id
        ),
        "arc_working_set": dict(command.arc_working_set or {}),
    }


def _command_from_payload(payload: dict[str, Any]) -> StoryPlanningGenerationCommand:
    return StoryPlanningGenerationCommand(
        project_id=str(payload.get("project_id") or ""),
        workspace_id=str(payload.get("workspace_id") or ""),
        book_id=str(payload.get("book_id") or ""),
        actor_id=str(payload.get("actor_id") or ""),
        generator_operation_name=str(payload.get("generator_operation_name") or ""),
        logical_key=str(payload.get("logical_key") or ""),
        input_versions=dict(payload.get("input_versions") or {}),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        trace_id=str(payload.get("trace_id") or ""),
        correlation_id=str(payload.get("correlation_id") or ""),
        parent_version_id=str(payload.get("parent_version_id") or ""),
        arc_scope_volume_plan_version_ids=tuple(
            str(item) for item in payload.get("arc_scope_volume_plan_version_ids") or ()
        ),
        related_arc_plan_version_ids=tuple(
            str(item) for item in payload.get("related_arc_plan_version_ids") or ()
        ),
        dependent_arc_plan_version_ids=tuple(
            str(item) for item in payload.get("dependent_arc_plan_version_ids") or ()
        ),
        change_evidence_version_ids=tuple(
            str(item) for item in payload.get("change_evidence_version_ids") or ()
        ),
        governance_action_version_ids=tuple(
            str(item) for item in payload.get("governance_action_version_ids") or ()
        ),
        repair_of_candidate_id=str(payload.get("repair_of_candidate_id") or ""),
        repair_reason=str(payload.get("repair_reason") or ""),
        repair_number=int(payload.get("repair_number") or 0),
        auto_approve_low_risk=bool(payload.get("auto_approve_low_risk", False)),
        parent_agent_session_operation_id=str(
            payload.get("parent_agent_session_operation_id") or ""
        ),
        arc_working_set=dict(payload.get("arc_working_set") or {}) or None,
    )


def _authority_role_versions(
    command: StoryPlanningGenerationCommand,
) -> dict[str, str]:
    return {
        **dict(command.input_versions),
        **{
            f"arc_scope_volume:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.arc_scope_volume_plan_version_ids, start=1
            )
        },
        **{
            f"related_arc:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.related_arc_plan_version_ids, start=1
            )
        },
        **{
            f"dependent_arc:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.dependent_arc_plan_version_ids, start=1
            )
        },
        **{
            f"narrative_governance_action:{index}": asset_version_id
            for index, asset_version_id in enumerate(
                command.governance_action_version_ids, start=1
            )
        },
    }


def _validate_frozen_arc_references(
    command: StoryPlanningGenerationCommand, content: dict[str, Any]
) -> None:
    if command.generator_operation_name == "arc_plan.generate":
        frozen = {
            command.logical_key,
            *command.related_arc_plan_version_ids,
            *command.dependent_arc_plan_version_ids,
        }
        for relation in content.get("arc_relations") or ():
            if not isinstance(relation, dict):
                continue
            source = str(relation.get("source_arc_ref") or "")
            target = str(relation.get("target_arc_ref") or "")
            if (
                source not in frozen
                or target not in frozen
                or command.logical_key not in {source, target}
            ):
                raise KernelError(
                    "PLANNING_ARC_RELATION_SCOPE_INVALID",
                    "Arc Graph relations must connect the candidate Arc to its frozen Arc portfolio",
                )
        return
    if command.generator_operation_name not in {
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }:
        return
    frozen = {
        str(command.input_versions["arc_plans"]),
        *command.related_arc_plan_version_ids,
    }
    if command.arc_working_set:
        selected = {
            str(item.get("arc_plan_version_id") or "")
            for item in command.arc_working_set.get("selected_contributions") or ()
            if isinstance(item, dict)
        }
        if selected != frozen:
            raise KernelError(
                "PLANNING_ARC_WORKING_SET_DRIFT",
                "Planning output Arc portfolio differs from the frozen Working Set",
            )
    references: list[str] = []
    if command.generator_operation_name == "chapter_group_plan.generate":
        portfolio = [
            *(str(item) for item in content.get("primary_arc_ids") or ()),
            *(str(item) for item in content.get("secondary_arc_ids") or ()),
        ]
        if len(portfolio) != len(set(portfolio)) or set(portfolio) != frozen:
            raise KernelError(
                "PLANNING_ARC_PORTFOLIO_MISMATCH",
                "Narrative Scheduling must classify every frozen Working Set Arc exactly once",
            )
        references.extend(
            str(item) for item in content.get("required_arc_contributions") or ()
        )
        references.extend(
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_checkpoint_expectations") or ()
            if isinstance(item, dict)
        )
        for row in content.get("chapter_function_matrix") or ():
            if not isinstance(row, dict):
                continue
            references.extend(
                str(item.get("arc_plan_version_id") or "")
                for item in row.get("arc_cadence") or ()
                if isinstance(item, dict)
            )
            references.extend(
                str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
                for item in row.get("required_arc_contributions") or ()
                if isinstance(item, dict)
            )
    else:
        schedule_arcs = {
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_schedule") or ()
            if isinstance(item, dict)
        }
        contribution_arcs = {
            str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
            for item in content.get("required_arc_contributions") or ()
            if isinstance(item, dict)
        }
        scene_arcs = {
            str(item)
            for scene in content.get("scene_plan") or ()
            if isinstance(scene, dict)
            for item in scene.get("arc_progress") or ()
            if str(item)
        }
        if command.arc_working_set and (
            schedule_arcs != frozen
            or contribution_arcs != frozen
            or scene_arcs != frozen
        ):
            raise KernelError(
                "PLANNING_ARC_COMPOSITION_INCOMPLETE",
                "Chapter composition must cover every frozen Working Set Arc in schedule, contributions, and Scenes",
            )
        if command.arc_working_set:
            expected_roles = {
                str(item.get("arc_plan_version_id") or ""): str(item.get("role") or "")
                for item in command.arc_working_set.get("selected_contributions") or ()
                if isinstance(item, dict)
            }
            actual_roles = {
                str(item.get("arc_plan_version_id") or ""): str(item.get("role") or "")
                for item in content.get("arc_schedule") or ()
                if isinstance(item, dict)
            }
            if actual_roles != expected_roles:
                raise KernelError(
                    "PLANNING_ARC_CONTRIBUTION_ROLE_DRIFT",
                    "Chapter Arc roles must match the governed Working Set",
                )
        references.extend(
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_schedule") or ()
            if isinstance(item, dict)
        )
        references.extend(
            str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
            for item in content.get("required_arc_contributions") or ()
            if isinstance(item, dict)
        )
        for scene in content.get("scene_plan") or ():
            if isinstance(scene, dict):
                references.extend(str(item) for item in scene.get("arc_progress") or ())
    if not references or any(not item or item not in frozen for item in references):
        raise KernelError(
            "PLANNING_ARC_REFERENCE_INVALID",
            "Scheduling or Chapter design references an Arc outside its frozen portfolio",
        )


__all__ = [
    "CHAPTER_PLAN_PROJECTION_DEFINITION",
    "STORY_PLANNING_EVALUATION_DEFINITION",
    "STORY_PLANNING_EVALUATION_HANDLER",
    "STORY_PLANNING_EVALUATION_VERSION",
    "STORY_PLANNING_GENERATION_DEFINITION",
    "STORY_PLANNING_GENERATION_HANDLER",
    "STORY_PLANNING_GENERATION_VERSION",
    "StoryPlanningGenerationApplication",
    "StoryPlanningGenerationHandlerRegistry",
    "chapter_plan_projection_definition",
    "story_planning_generation_definition",
]
