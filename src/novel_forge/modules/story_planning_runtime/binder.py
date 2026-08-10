"""Capability-Pack/Agent/PEP binding for Story Planning candidates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.modules.agent_collaboration.application import (
    AgentCollaborationApplication,
)
from novel_forge.modules.agent_collaboration.domain import (
    AgentCollaborationSession,
    AgentMessageType,
    AgentScopeContract,
    AgentWorkOrder,
    AssetReadScope,
    AuthorityScope,
    KnowledgeVisibility,
    KnowledgeVisibilityScope,
    NarrativeScope,
    NarrativeScopeType,
    Participant,
    ParticipantSnapshot,
    ProposalScope,
    SessionStatus,
    TemporalScope,
)
from novel_forge.modules.agent_runtime.contracts import AgentRuntimeBinding
from novel_forge.modules.agent_runtime.coordinator import AgentTurnExecutionCoordinator
from novel_forge.modules.capability_pack_authority import CapabilityPackAttemptSnapshot
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
    chapter_node_binding_from_snapshot,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCommand,
    DomainExecutionPort,
    DomainModelOperation,
)
from novel_forge.modules.story_design_authority import GeneratorDefinition
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    FrozenPlanningInput,
    PlanningExecutionEvidence,
    PlanningGenerationCandidate,
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    StoryPlanningGenerationCommand,
    canonical_hash,
)


@dataclass(frozen=True, slots=True)
class PlanningExecutionBundle:
    attempt_snapshot: CapabilityPackAttemptSnapshot
    work_order: AgentWorkOrder
    runtime_binding: AgentRuntimeBinding
    execution_port: DomainExecutionPort


@dataclass(frozen=True, slots=True)
class PreparedPlanningExecution:
    """PEP contracts frozen for one existing Planning Authority Attempt."""

    execution_port: DomainExecutionPort
    context_bundle_asset_version_id: str
    context_bundle_hash: str
    route_snapshot_ref: str
    route_snapshot_hash: str
    input_manifest_ref: str
    input_manifest_hash: str
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_permission_snapshot_ref: str
    tool_permission_snapshot_hash: str
    context_policy_ref: str
    context_policy_hash: str
    validation_policy_ref: str
    commit_policy_ref: str
    timeout_policy_ref: str

    def __post_init__(self) -> None:
        references = (
            self.context_bundle_asset_version_id,
            self.route_snapshot_ref,
            self.input_manifest_ref,
            self.prompt_bundle_ref,
            self.skill_bundle_ref,
            self.tool_permission_snapshot_ref,
            self.context_policy_ref,
            self.validation_policy_ref,
            self.commit_policy_ref,
            self.timeout_policy_ref,
        )
        hashes = (
            self.context_bundle_hash,
            self.route_snapshot_hash,
            self.input_manifest_hash,
            self.prompt_bundle_hash,
            self.skill_bundle_hash,
            self.tool_permission_snapshot_hash,
            self.context_policy_hash,
        )
        if any(not str(value).strip() for value in references):
            raise ValueError("prepared Planning execution references are incomplete")
        if any(
            not str(value).startswith("sha256:") or len(str(value)) != 71
            for value in hashes
        ):
            raise ValueError("prepared Planning execution hashes must be SHA-256")
        if not getattr(
            self.execution_port, "production_execution_gateway_backed", False
        ) or not getattr(self.execution_port, "external_effect_backed", False):
            raise ValueError(
                "prepared Planning execution must use the ExternalEffect-backed PEP"
            )


class PlanningExecutionPreparer(Protocol):
    def prepare(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
        attempt_snapshot: CapabilityPackAttemptSnapshot,
    ) -> PreparedPlanningExecution: ...


class PlanningExecutionBundleResolver(Protocol):
    def resolve(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningExecutionBundle: ...


class PostgresPlanningExecutionBundleResolver:
    """Freeze Pack, Agent WorkOrder, runtime binding, and PEP on one Attempt.

    The injected preparer is the single transport-specific seam. It must return
    an ExternalEffect-backed Production Execution Plane port; this resolver owns
    no provider, Attempt, Lease, or business activation state.
    """

    def __init__(
        self,
        database_url: str,
        *,
        execution_preparer: PlanningExecutionPreparer,
        workflow_definition_ref: str,
        pack_id: str,
        environment: str,
        runtime_profile: str,
        release_channel: str,
        release_sha: str,
    ) -> None:
        values = (
            database_url,
            workflow_definition_ref,
            pack_id,
            environment,
            runtime_profile,
            release_channel,
            release_sha,
        )
        if any(not value.strip() for value in values) or len(release_sha) != 40:
            raise ValueError("Planning execution resolver configuration is incomplete")
        self.database_url = database_url
        self.execution_preparer = execution_preparer
        self.workflow_definition_ref = workflow_definition_ref
        self.pack_id = pack_id
        self.environment = environment
        self.runtime_profile = runtime_profile
        self.release_channel = release_channel
        self.release_sha = release_sha
        self.pack_resolver = CapabilityPackRuntimeResolver(database_url)
        self.turn_coordinator = AgentTurnExecutionCoordinator(database_url)

    def resolve(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningExecutionBundle:
        attempt_snapshot = self.pack_resolver.freeze_attempt_snapshot(
            CapabilityPackResolutionRequest(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                workflow_definition_ref=self.workflow_definition_ref,
                workflow_node_id=command.generator_operation_name,
                environment=self.environment,
                runtime_profile=self.runtime_profile,
                release_channel=self.release_channel,
                release_sha=self.release_sha,
                operation_definition_ref=STORY_PLANNING_OPERATION_DEFINITION_REF,
                pack_id=self.pack_id,
            ),
            operation_id=operation_id,
            attempt_id=attempt_id,
            execution_fencing_token=fencing_token,
            worker_id=worker_id,
        )
        node = chapter_node_binding_from_snapshot(attempt_snapshot.execution_snapshot)
        node.update(
            {
                "budget_policy_ref": (
                    attempt_snapshot.execution_snapshot.budget_policy_ref
                ),
                "approval_policy_ref": (
                    attempt_snapshot.execution_snapshot.approval_policy_ref
                ),
            }
        )
        if str(node["execution_capability_id"]) != definition.capability or str(
            node["commit_authority"]
        ) not in {
            "STORY_DESIGN_AUTHORITY",
            "HIERARCHICAL_PLANNING_AUTHORITY",
            "PLAN_CHANGE_AUTHORITY",
        }:
            raise KernelError(
                "PLANNING_CAPABILITY_PACK_NODE_INVALID",
                "Capability Pack node cannot submit this Planning Candidate",
            )
        prepared = self.execution_preparer.prepare(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
            command=command,
            inputs=inputs,
            definition=definition,
            attempt_snapshot=attempt_snapshot,
        )
        frozen = attempt_snapshot.execution_snapshot
        CapabilityPackRuntimeResolver.validate_runtime_admission(
            frozen,
            {
                "operation_definition_ref": frozen.operation_definition_ref,
                "operation_definition_hash": frozen.operation_definition_hash,
                "agent_definition_ref": frozen.agent_definition_ref,
                "agent_definition_hash": frozen.agent_definition_hash,
                "capability_ref": frozen.capability_ref,
                "capability_hash": frozen.capability_hash,
                "execution_capability_id": frozen.execution_capability_id,
                "execution_capability_hash": frozen.execution_capability_hash,
                "prompt_bundle_ref": prepared.prompt_bundle_ref,
                "prompt_bundle_hash": prepared.prompt_bundle_hash,
                "skill_bundle_ref": prepared.skill_bundle_ref,
                "skill_bundle_hash": prepared.skill_bundle_hash,
                "tool_policy_ref": frozen.tool_policy_ref,
                "tool_policy_hash": frozen.tool_policy_hash,
                "context_policy_ref": prepared.context_policy_ref,
                "context_policy_hash": prepared.context_policy_hash,
                "evaluation_policy_ref": prepared.validation_policy_ref,
                "evaluation_policy_hash": frozen.evaluation_policy_hash,
                "release_sha": self.release_sha,
            },
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = self._operation(uow, operation_id, command.project_id)
            if (
                operation["definition_name"],
                operation["definition_version"],
                operation["definition_hash"],
            ) != (
                str(node["operation_definition_name"]),
                str(node["operation_definition_version"]),
                str(node["operation_definition_hash"]),
            ):
                raise KernelError(
                    "PLANNING_OPERATION_BINDING_DRIFT",
                    "Planning Operation differs from the frozen Pack node",
                )
            agent = uow.repositories.agent_runtime.lock_definition_version(
                str(node["agent_id"]), int(node["agent_definition_version"])
            )
            capability = self._capability(agent, node)
            if (
                RuntimeEnvironment.parse(self.runtime_profile).controlled
                and capability.get("qualification_status") != "QUALIFIED_REAL_RUNTIME"
            ):
                raise KernelError(
                    "PLANNING_AGENT_CAPABILITY_NOT_RUNTIME_QUALIFIED",
                    "controlled Planning execution requires REAL_RUNTIME qualification",
                )
            work_order = self._work_order(
                uow,
                operation=operation,
                attempt_id=attempt_id,
                fencing_token=fencing_token,
                command=command,
                inputs=inputs,
                definition=definition,
                prepared=prepared,
                node=node,
                agent=agent,
                capability=capability,
            )
            runtime_binding = self._runtime_binding(
                operation=operation,
                work_order=work_order,
                prepared=prepared,
                node=node,
                agent=agent,
                capability=capability,
                snapshot=attempt_snapshot,
            )
            self.turn_coordinator.freeze_turn_in_uow(uow, work_order, runtime_binding)
            uow.commit()
        return PlanningExecutionBundle(
            attempt_snapshot,
            work_order,
            runtime_binding,
            prepared.execution_port,
        )

    @staticmethod
    def _operation(
        uow: AuthorityUnitOfWork, operation_id: str, project_id: str
    ) -> dict[str, str]:
        uow.cursor.execute(
            """
            SELECT operation.definition_name, operation.definition_version,
                   operation.definition_snapshot, saga.saga_id
            FROM authority_operation AS operation
            JOIN authority_saga AS saga
              ON saga.root_operation_id=operation.root_operation_id
             AND saga.project_id=operation.project_id
            WHERE operation.operation_id=%s AND operation.project_id=%s
            """,
            [operation_id, project_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_AGENT_OPERATION_INVALID",
                "Planning Agent binding requires an admitted Saga Operation",
            )
        snapshot = dict(row[2] or {})
        return {
            "operation_id": operation_id,
            "definition_name": str(row[0]),
            "definition_version": str(row[1]),
            "definition_hash": str(snapshot.get("definition_hash") or ""),
            "saga_id": str(row[3]),
        }

    @staticmethod
    def _capability(
        agent: dict[str, object], node: dict[str, object]
    ) -> dict[str, object]:
        expected_definition = (
            str(node["agent_id"]),
            int(node["agent_definition_version"]),
            str(node["agent_definition_hash"]),
        )
        actual_definition = (
            str(agent["agent_id"]),
            int(agent["definition_version"]),
            str(agent["definition_hash"]),
        )
        if actual_definition != expected_definition:
            raise KernelError(
                "PLANNING_AGENT_DEFINITION_DRIFT",
                "Agent Definition differs from the frozen Pack node",
            )
        definition_drift = [
            key
            for key, expected in {
                "capability_pack_ref": node["capability_pack_ref"],
                "input_contract_ref": node["input_contract_ref"],
                "output_contract_ref": node["output_contract_ref"],
            }.items()
            if str(agent.get(key)) != str(expected)
        ]
        if definition_drift:
            raise KernelError(
                "PLANNING_AGENT_DEFINITION_DRIFT",
                "Agent Definition differs from Pack contracts: "
                + ", ".join(definition_drift),
            )
        matches = [
            dict(item)
            for item in list(agent["capabilities"])  # type: ignore[arg-type]
            if str(item["capability_id"]) == str(node["capability_id"])
            and int(item["capability_version"]) == int(node["capability_version"])
        ]
        if len(matches) != 1:
            raise KernelError(
                "PLANNING_AGENT_CAPABILITY_NOT_BOUND",
                "Agent Definition lacks the exact Planning capability",
            )
        capability = matches[0]
        if str(capability["capability_hash"]) != str(node["capability_hash"]) or str(
            capability["execution_capability_id"]
        ) != str(node["execution_capability_id"]):
            raise KernelError(
                "PLANNING_AGENT_CAPABILITY_DRIFT",
                "Agent capability differs from the frozen Pack node",
            )
        return capability

    def _work_order(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation: dict[str, str],
        attempt_id: str,
        fencing_token: int,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
        prepared: PreparedPlanningExecution,
        node: dict[str, object],
        agent: dict[str, object],
        capability: dict[str, object],
    ) -> AgentWorkOrder:
        turn_id = _identity("planning-agent-turn", attempt_id)
        existing = uow.repositories.agent_collaboration.find_work_order_by_turn(turn_id)
        if existing is not None:
            if existing.operation_id != operation["operation_id"]:
                raise KernelError(
                    "PLANNING_AGENT_WORK_ORDER_CONFLICT",
                    "Planning Attempt already has another Agent WorkOrder",
                )
            return existing
        session_id = _identity("planning-agent-session", attempt_id)
        scope_id = _identity("planning-agent-scope", attempt_id)
        participants_id = _identity("planning-agent-participants", attempt_id)
        collaboration = AgentCollaborationApplication(
            uow.repositories.agent_collaboration
        )
        collaboration.create_collaboration_session(
            AgentCollaborationSession(
                session_id=session_id,
                project_id=command.project_id,
                owner_authority=str(node["commit_authority"]),
                business_goal=(
                    f"Generate {command.planning_scope.value} plan candidate "
                    f"{command.logical_key}."
                ),
                issue_type=f"{command.planning_scope.value}_PLAN_CANDIDATE",
                scope_snapshot_ref="",
                participant_snapshot_ref="",
                current_candidate_version_ref="",
                status=SessionStatus.CREATED,
                round_number=0,
                turn_number=0,
                execution_count=0,
                spent_budget=Decimal("0"),
                budget_ref=str(node["budget_policy_ref"]),
                termination_policy_ref="termination:single-planning-candidate:v1",
                created_operation_id=operation["operation_id"],
                saga_id=operation["saga_id"],
                authority_decision_ref="",
                last_turn_id="",
                attempt_id=attempt_id,
            )
        )
        narrative_scope = self._narrative_scope(command)
        scope = AgentScopeContract(
            scope_contract_id=f"scope:planning:{command.planning_scope.value.lower()}",
            version=1,
            narrative=narrative_scope,
            asset_read=AssetReadScope(
                allowed_asset_types=tuple(sorted({item.asset_type for item in inputs})),
                asset_version_ids=tuple(item.asset_version_id for item in inputs),
                forbidden_asset_types=("raw_source", "published_chapter"),
            ),
            proposal=ProposalScope(
                allowed_asset_types=(definition.output_candidate_type,),
                allowed_change_types=(f"{command.generator_operation_name}.propose",),
                forbidden_asset_types=("active_plan", "published_chapter"),
                forbidden_change_types=("authority.commit", "plan.activate"),
            ),
            authority=AuthorityScope(
                authority_type=str(node["commit_authority"]),
                allowed_narrative_scopes=(narrative_scope.kind,),
                allowed_change_types=(f"{command.generator_operation_name}.propose",),
            ),
            temporal=TemporalScope(0, (1, 1), 1, 0),
            knowledge=KnowledgeVisibilityScope(
                allowed=(
                    KnowledgeVisibility.AUTHOR_KNOWLEDGE,
                    KnowledgeVisibility.PUBLIC_CANON,
                    KnowledgeVisibility.HIDDEN_PLANNING,
                )
            ),
        )
        collaboration.freeze_scope(
            session_id,
            scope.freeze(
                snapshot_id=scope_id, authority_id=str(node["commit_authority"])
            ),
        )
        collaboration.assign_participants(
            session_id,
            ParticipantSnapshot.freeze(
                snapshot_id=participants_id,
                participants=(
                    Participant(
                        agent_id=str(agent["agent_id"]),
                        agent_definition_version=int(agent["definition_version"]),
                        role=str(agent["role"]),
                    ),
                ),
            ),
        )
        return AgentWorkOrder(
            work_order_id=_identity("planning-agent-work-order", attempt_id),
            collaboration_session_id=session_id,
            turn_id=turn_id,
            operation_id=operation["operation_id"],
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            agent_id=str(agent["agent_id"]),
            agent_definition_version=int(agent["definition_version"]),
            capability=str(capability["capability_id"]),
            message_type=AgentMessageType.PROPOSAL,
            business_goal=f"Generate {command.logical_key} as a Candidate.",
            current_issue=(
                f"scope={command.planning_scope.value}; logical_id={command.logical_key}; "
                f"parent_version={command.parent_version_id or 'ROOT'}"
            ),
            scope_snapshot_ref=scope_id,
            participant_snapshot_ref=participants_id,
            input_asset_versions=tuple(item.asset_version_id for item in inputs),
            candidate_version_ref="",
            context_bundle_ref=prepared.context_bundle_asset_version_id,
            evidence_refs=(prepared.prompt_bundle_ref, prepared.skill_bundle_ref),
            must_preserve=("frozen input AssetVersions", "Domain Authority commit"),
            must_change=(definition.output_candidate_type,),
            forbidden_changes=("plan.activate", "published_chapter.modify"),
            acceptance_criteria=(
                "PEP validation manifest present",
                "Candidate schema valid",
                "Story Design Authority owns activation",
            ),
            risk_level=definition.risk_class,
            budget_policy_ref=str(node["budget_policy_ref"]),
            timeout_policy_ref=prepared.timeout_policy_ref,
            approval_policy_ref=str(node["approval_policy_ref"]),
            failure_policy="AUTHORITY_BOUNDED_REPAIR",
            continuation_policy="STORY_DESIGN_VALIDATE_THEN_PLAN_AUTHORITY",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            route_snapshot_ref=prepared.route_snapshot_ref,
            input_manifest_ref=prepared.input_manifest_ref,
            capability_version=int(capability["capability_version"]),
            execution_capability=str(capability["execution_capability_id"]),
        )

    @staticmethod
    def _narrative_scope(
        command: StoryPlanningGenerationCommand,
    ) -> NarrativeScope:
        kind = NarrativeScopeType(command.planning_scope.value)
        common: dict[str, str | NarrativeScopeType] = {
            "kind": kind,
            "book_id": command.book_id,
        }
        if kind is NarrativeScopeType.VOLUME:
            common["volume_id"] = command.logical_key
        elif kind is NarrativeScopeType.ARC:
            common["arc_id"] = command.logical_key
        elif kind is NarrativeScopeType.CHAPTER_GROUP:
            common.update(
                volume_id=str(command.input_versions["volume_plan"]),
                chapter_group_id=command.logical_key,
            )
        elif kind is NarrativeScopeType.CHAPTER:
            common.update(
                volume_id=str(command.input_versions["volume_plan"]),
                arc_id=str(command.input_versions["arc_plans"]),
                chapter_group_id=str(command.input_versions["chapter_group_plan"]),
                chapter_id=command.logical_key,
            )
        return NarrativeScope(**common)  # type: ignore[arg-type]

    @staticmethod
    def _runtime_binding(
        *,
        operation: dict[str, str],
        work_order: AgentWorkOrder,
        prepared: PreparedPlanningExecution,
        node: dict[str, object],
        agent: dict[str, object],
        capability: dict[str, object],
        snapshot: CapabilityPackAttemptSnapshot,
    ) -> AgentRuntimeBinding:
        frozen = snapshot.execution_snapshot
        return AgentRuntimeBinding(
            binding_id=_identity(
                "planning-agent-runtime-binding", work_order.attempt_id
            ),
            project_id=work_order.project_id,
            workspace_id=work_order.workspace_id,
            book_id=work_order.book_id,
            workflow_definition_ref=frozen.workflow_definition_ref,
            workflow_node_id=frozen.workflow_node_id,
            operation_definition_ref=frozen.operation_definition_ref,
            operation_definition_hash=frozen.operation_definition_hash,
            operation_id=work_order.operation_id,
            attempt_id=work_order.attempt_id,
            fencing_token=work_order.fencing_token,
            work_order_id=work_order.work_order_id,
            agent_id=work_order.agent_id,
            agent_definition_version=work_order.agent_definition_version,
            agent_definition_hash=str(agent["definition_hash"]),
            capability_id=work_order.capability,
            capability_version=work_order.capability_version,
            capability_hash=str(capability["capability_hash"]),
            execution_capability_id=work_order.execution_capability,
            chapter_node_binding_ref=str(node["chapter_node_binding_ref"]),
            capability_pack_ref=str(node["capability_pack_ref"]),
            capability_pack_compilation_hash=str(
                node["capability_pack_compilation_hash"]
            ),
            context_bundle_asset_version_id=prepared.context_bundle_asset_version_id,
            context_bundle_hash=prepared.context_bundle_hash,
            prompt_bundle_ref=prepared.prompt_bundle_ref,
            prompt_bundle_hash=prepared.prompt_bundle_hash,
            skill_bundle_ref=prepared.skill_bundle_ref,
            skill_bundle_hash=prepared.skill_bundle_hash,
            tool_policy_ref=frozen.tool_policy_ref,
            tool_policy_hash=frozen.tool_policy_hash,
            tool_permission_snapshot_ref=prepared.tool_permission_snapshot_ref,
            tool_permission_snapshot_hash=prepared.tool_permission_snapshot_hash,
            context_policy_ref=prepared.context_policy_ref,
            context_policy_hash=prepared.context_policy_hash,
            route_snapshot_ref=prepared.route_snapshot_ref,
            route_snapshot_hash=prepared.route_snapshot_hash,
            input_manifest_ref=prepared.input_manifest_ref,
            input_manifest_hash=prepared.input_manifest_hash,
            budget_policy_ref=frozen.budget_policy_ref,
            timeout_policy_ref=prepared.timeout_policy_ref,
            approval_policy_ref=frozen.approval_policy_ref,
            validation_policy_ref=prepared.validation_policy_ref,
            commit_policy_ref=prepared.commit_policy_ref,
            commit_authority=frozen.commit_authority,
            release_sha=frozen.release_sha,
            capability_pack_deployment_id=frozen.deployment_id,
            capability_pack_activation_version=frozen.activation_version,
            capability_pack_binding_set_id=frozen.binding_set_id,
            capability_pack_binding_set_hash=frozen.binding_set_hash,
            capability_pack_scope_type=frozen.selected_scope_type.value,
            capability_pack_assignment_ref=frozen.assignment_ref,
            capability_pack_attempt_snapshot_id=snapshot.snapshot_id,
            capability_pack_attempt_snapshot_hash=snapshot.snapshot_hash,
        )


class PlanningExecutionBinder(Protocol):
    def execute(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningGenerationCandidate: ...


class CapabilityPackBackedPlanningExecutionBinder:
    """Validate one frozen Pack/Agent binding and submit only through PEP."""

    production_execution_gateway_backed = True

    def __init__(self, resolver: PlanningExecutionBundleResolver) -> None:
        self.resolver = resolver

    def execute(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningGenerationCandidate:
        bundle = self.resolver.resolve(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
            command=command,
            inputs=inputs,
            definition=definition,
        )
        self._validate_bundle(
            bundle,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            command=command,
            definition=definition,
        )
        execution = bundle.execution_port.execute(
            DomainExecutionCommand(
                capability=definition.capability,
                operation=DomainModelOperation.GENERATE,
                candidate_kind=CandidateKind.GENERATION,
                # The actual prompt is the frozen Pack prompt bundle.  The
                # Domain port receives only its immutable reference here.
                prompt=bundle.attempt_snapshot.execution_snapshot.prompt_bundle_ref,
                context={
                    "input_manifest_ref": bundle.runtime_binding.input_manifest_ref,
                    "work_order_id": bundle.work_order.work_order_id,
                    "logical_key": command.logical_key,
                    "planning_scope": command.planning_scope.value,
                },
            )
        )
        evidence = execution.evidence
        return PlanningGenerationCandidate(
            generator_operation_name=command.generator_operation_name,
            planning_scope=command.planning_scope,
            logical_key=command.logical_key,
            candidate_payload=dict(execution.raw_output),
            frozen_inputs=inputs,
            evidence=PlanningExecutionEvidence(
                operation_id=evidence.operation_id,
                attempt_id=evidence.attempt_id,
                fencing_token=evidence.fencing_token,
                route_snapshot_id=evidence.route_snapshot_id,
                input_manifest_ref=evidence.input_manifest_ref,
                output_manifest_ref=evidence.output_manifest_ref,
                validation_manifest_ref=evidence.validation_manifest_ref,
                usage_receipt_ref=evidence.usage_receipt_ref,
                cost_receipt_ref=evidence.cost_receipt_ref,
                external_receipt_ref=evidence.external_receipt_ref,
                capability_pack_attempt_snapshot_id=(
                    bundle.attempt_snapshot.snapshot_id
                ),
                capability_pack_attempt_snapshot_hash=(
                    bundle.attempt_snapshot.snapshot_hash
                ),
                agent_work_order_ref=bundle.work_order.work_order_id,
                agent_work_order_hash=canonical_hash(bundle.work_order.to_context()),
                agent_runtime_binding_ref=bundle.runtime_binding.binding_id,
                agent_runtime_binding_hash=bundle.runtime_binding.binding_hash,
                commit_authority=bundle.runtime_binding.commit_authority,
                fixture_protocol_only=evidence.fixture_protocol_only,
                real_provider_proven=(
                    evidence.real_model_call and not evidence.fixture_protocol_only
                ),
                production_verified=evidence.production_verified,
            ),
        )

    @staticmethod
    def _validate_bundle(
        bundle: PlanningExecutionBundle,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        command: StoryPlanningGenerationCommand,
        definition: GeneratorDefinition,
    ) -> None:
        snapshot = bundle.attempt_snapshot
        binding = bundle.runtime_binding
        work_order = bundle.work_order
        if not getattr(
            bundle.execution_port, "production_execution_gateway_backed", False
        ) or not getattr(bundle.execution_port, "external_effect_backed", False):
            raise KernelError(
                "PLANNING_EXECUTION_PLANE_INVALID",
                "Planning execution requires the ExternalEffect-backed PEP port",
            )
        identity = (operation_id, attempt_id, fencing_token)
        if (
            (
                snapshot.operation_id,
                snapshot.attempt_id,
                snapshot.execution_fencing_token,
            )
            != identity
            or (binding.operation_id, binding.attempt_id, binding.fencing_token)
            != identity
            or (
                work_order.operation_id,
                work_order.attempt_id,
                work_order.fencing_token,
            )
            != identity
        ):
            raise KernelError(
                "PLANNING_EXECUTION_ATTEMPT_DRIFT",
                "Pack Snapshot, Agent binding, and WorkOrder must use one Attempt fence",
            )
        execution_snapshot = snapshot.execution_snapshot
        if (
            execution_snapshot.execution_capability_id != definition.capability
            or binding.execution_capability_id != definition.capability
            or work_order.execution_capability != definition.capability
        ):
            raise KernelError(
                "PLANNING_EXECUTION_CAPABILITY_DRIFT",
                "Planning execution differs from GeneratorDefinition capability",
            )
        if (
            binding.capability_pack_attempt_snapshot_id != snapshot.snapshot_id
            or binding.capability_pack_attempt_snapshot_hash != snapshot.snapshot_hash
        ):
            raise KernelError(
                "PLANNING_CAPABILITY_PACK_SNAPSHOT_DRIFT",
                "Agent binding must consume the frozen Attempt Pack Snapshot",
            )
        if binding.commit_authority not in {
            "STORY_DESIGN_AUTHORITY",
            "HIERARCHICAL_PLANNING_AUTHORITY",
            "PLAN_CHANGE_AUTHORITY",
        }:
            raise KernelError(
                "PLANNING_COMMIT_AUTHORITY_INVALID",
                "Planning Agent can only submit a Candidate to a planning Authority",
            )
        if (
            work_order.project_id != command.project_id
            or work_order.book_id != command.book_id
        ):
            raise KernelError(
                "PLANNING_WORK_ORDER_SCOPE_DRIFT",
                "Planning Agent WorkOrder belongs to another Project or Book",
            )


def _identity(kind: str, source: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"novel-forge:{kind}:{source}"))


__all__ = [
    "CapabilityPackBackedPlanningExecutionBinder",
    "PlanningExecutionPreparer",
    "PlanningExecutionBinder",
    "PlanningExecutionBundle",
    "PlanningExecutionBundleResolver",
    "PostgresPlanningExecutionBundleResolver",
    "PreparedPlanningExecution",
]
