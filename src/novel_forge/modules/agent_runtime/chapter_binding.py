"""Chapter node bridge into the PostgreSQL Agent Definition Authority.

The bridge attaches an Agent work order and immutable runtime evidence to the
Chapter node's existing Authority Attempt.  It does not execute a second Agent
Attempt and it never commits the Chapter domain asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Callable
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from novel_forge.modules.agent_collaboration.application import (
    AgentCollaborationApplication,
)
from novel_forge.modules.agent_collaboration.domain import (
    AgentCollaborationSession,
    AgentMessageType,
    AgentOutputEnvelope,
    AgentScopeContract,
    AgentWorkOrder,
    AssetReadScope,
    AuthorityScope,
    CollaborationDecision,
    CollaborationDecisionType,
    KnowledgeVisibility,
    KnowledgeVisibilityScope,
    NarrativeScope,
    NarrativeScopeType,
    Participant,
    ParticipantSnapshot,
    ProposalScope,
    ProposedAssetChange,
    SessionStatus,
    TemporalScope,
)
from novel_forge.modules.agent_collaboration.repository import CollaborationCommit
from novel_forge.modules.agent_runtime.contracts import AgentRuntimeBinding
from novel_forge.modules.agent_runtime.coordinator import (
    AgentTurnExecutionCoordinator,
    ExistingDomainAssetCommit,
)
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.chapter_authority.execution_gateway import (
    ChapterExecutionBinding,
)
from novel_forge.modules.chapter_authority.model_effects import (
    AGENT_MODEL_STAGES,
    ModelProviderResult,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.domain_execution import (
    DomainExecutionEvidence,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


AGENT_BOUND_CHAPTER_STAGES = AGENT_MODEL_STAGES


@dataclass(frozen=True, slots=True)
class FrozenChapterAgentWorkOrder:
    work_order: AgentWorkOrder
    chapter_number: int
    owner_authority: str


class PostgresChapterAgentBindingRecorder:
    """Freeze and accept Agent candidates on an existing Chapter Attempt."""

    production_authority = True

    def __init__(
        self,
        database_url: str,
        *,
        workflow_definition_ref: str = "chapter_authority_slice@2.2.0",
        bound_stages: frozenset[str] = AGENT_BOUND_CHAPTER_STAGES,
        required_stages: frozenset[str] = frozenset(),
        compatibility_allowed: bool = True,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not workflow_definition_ref:
            raise ValueError("Chapter Agent Binding recorder is incomplete")
        if not required_stages <= bound_stages:
            raise ValueError("required Chapter Agent stages must be bound stages")
        self.database_url = database_url
        self.workflow_definition_ref = workflow_definition_ref
        self.bound_stages = bound_stages
        self.required_stages = required_stages
        self.compatibility_allowed = compatibility_allowed
        self.legacy_writer = AuthorityAssetWriter(database_url)
        self.turn_coordinator = AgentTurnExecutionCoordinator(
            database_url, fault_injector=fault_injector
        )

    def freeze(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        execution_binding: ChapterExecutionBinding,
    ) -> FrozenChapterAgentWorkOrder | None:
        if stage not in self.bound_stages:
            if not self.compatibility_allowed:
                raise KernelError(
                    "CHAPTER_AGENT_STAGE_NOT_MIGRATED",
                    f"controlled Chapter stage has no Agent Runtime migration: {stage}",
                )
            self.record_compatibility_usage(request, stage=stage)
            return None
        work_order_id = _identity("chapter-agent-work-order", request.attempt_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            existing = uow.repositories.agent_collaboration.find_work_order_by_turn(
                _identity("chapter-agent-turn", request.attempt_id)
            )
            if existing is not None:
                if existing.work_order_id != work_order_id:
                    raise KernelError(
                        "CHAPTER_AGENT_WORK_ORDER_CONFLICT",
                        "Chapter Attempt already has different Agent work order",
                    )
                uow.commit()
                return FrozenChapterAgentWorkOrder(
                    work_order=existing,
                    chapter_number=_chapter_number(request, execution_binding),
                    owner_authority="CHAPTER_AUTHORITY",
                )

            try:
                node_binding = (
                    uow.repositories.agent_runtime.resolve_active_chapter_node_binding(
                        workflow_definition_ref=self.workflow_definition_ref,
                        workflow_node_id=stage,
                    )
                )
            except KernelError as exc:
                if (
                    exc.code == "CHAPTER_AGENT_BINDING_NOT_FOUND"
                    and stage not in self.required_stages
                ):
                    uow.commit()
                    self.record_compatibility_usage(request, stage=stage)
                    return None
                raise

            operation = _operation_snapshot(uow.cursor, request)
            _validate_operation_binding(operation, node_binding, stage)
            agent = uow.repositories.agent_runtime.lock_active_definition(
                str(node_binding["agent_id"])
            )
            _validate_definition_binding(agent, node_binding)
            capability = _bound_capability(
                agent,
                node_binding,
                production_required=not self.compatibility_allowed,
            )
            chapter_number = _chapter_number(request, execution_binding)
            book_id = execution_binding.request.book_id
            context = next(
                (
                    item
                    for item in request.inputs
                    if item.asset_version_id
                    == execution_binding.input_manifest.context_bundle_version
                ),
                None,
            )
            if context is None:
                raise KernelError(
                    "CHAPTER_AGENT_CONTEXT_NOT_FROZEN",
                    "Agent-bound Chapter node requires its Context Bundle in the frozen input set",
                )
            if context.asset_type != "context_bundle":
                raise KernelError(
                    "CHAPTER_AGENT_CONTEXT_NOT_FROZEN",
                    "Agent-bound Chapter node requires a Context Bundle AssetVersion",
                )
            contracts = _execution_contracts(
                uow.repositories.asset_documents,
                request.project_id,
                execution_binding,
            )
            # A retry is a new Authority Attempt and must retain its own frozen
            # collaboration evidence instead of mutating the prior attempt.
            session_id = _identity("chapter-agent-session", request.attempt_id)
            scope_snapshot_id = _identity("chapter-agent-scope", request.attempt_id)
            participant_snapshot_id = _identity(
                "chapter-agent-participants", request.attempt_id
            )
            collaboration = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            collaboration.create_collaboration_session(
                AgentCollaborationSession(
                    session_id=session_id,
                    project_id=request.project_id,
                    owner_authority=str(node_binding["commit_authority"]),
                    business_goal=f"Produce the {stage} candidate for chapter {chapter_number}.",
                    issue_type=f"CHAPTER_{stage.upper()}_CANDIDATE",
                    scope_snapshot_ref="",
                    participant_snapshot_ref="",
                    current_candidate_version_ref="",
                    status=SessionStatus.CREATED,
                    round_number=0,
                    turn_number=0,
                    execution_count=0,
                    spent_budget=Decimal("0"),
                    budget_ref=execution_binding.request.budget_policy_ref,
                    termination_policy_ref="termination:single-domain-candidate:v1",
                    created_operation_id=request.operation_id,
                    saga_id=str(operation["saga_id"]),
                    authority_decision_ref="",
                    last_turn_id="",
                )
            )
            input_versions = tuple(item.asset_version_id for item in request.inputs)
            scope = AgentScopeContract(
                scope_contract_id=f"scope:chapter-agent:{stage}",
                version=1,
                narrative=NarrativeScope(
                    kind=NarrativeScopeType.CHAPTER,
                    book_id=book_id,
                    volume_id=f"{book_id}:volume:active",
                    arc_id=f"{book_id}:arc:active",
                    chapter_group_id=f"{book_id}:chapter-group:active",
                    chapter_id=f"{book_id}:chapter:{chapter_number}",
                ),
                asset_read=AssetReadScope(
                    allowed_asset_types=tuple(
                        sorted({item.asset_type for item in request.inputs})
                    ),
                    asset_version_ids=input_versions,
                    forbidden_asset_types=("raw_source", "published_chapter"),
                ),
                proposal=ProposalScope(
                    allowed_asset_types=(f"{stage}_candidate",),
                    allowed_change_types=(f"{stage}.propose",),
                    forbidden_asset_types=(
                        "canon_snapshot",
                        "active_plan",
                        "published_chapter",
                    ),
                    forbidden_change_types=("authority.commit", "publish.activate"),
                ),
                authority=AuthorityScope(
                    authority_type=str(node_binding["commit_authority"]),
                    allowed_narrative_scopes=(NarrativeScopeType.CHAPTER,),
                    allowed_change_types=(f"{stage}.propose",),
                ),
                temporal=TemporalScope(
                    past_locked_through=max(0, chapter_number - 1),
                    active_range=(chapter_number, chapter_number),
                    forecast_horizon=chapter_number,
                    published_boundary=max(0, chapter_number - 1),
                ),
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
                    snapshot_id=scope_snapshot_id,
                    authority_id=str(node_binding["commit_authority"]),
                ),
            )
            collaboration.assign_participants(
                session_id,
                ParticipantSnapshot.freeze(
                    snapshot_id=participant_snapshot_id,
                    participants=(
                        Participant(
                            agent_id=str(agent["agent_id"]),
                            agent_definition_version=int(agent["definition_version"]),
                            role=str(agent["role"]),
                        ),
                    ),
                ),
            )
            work_order = AgentWorkOrder(
                work_order_id=work_order_id,
                collaboration_session_id=session_id,
                turn_id=_identity("chapter-agent-turn", request.attempt_id),
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                agent_id=str(agent["agent_id"]),
                agent_definition_version=int(agent["definition_version"]),
                capability=str(capability["capability_id"]),
                message_type=AgentMessageType.PROPOSAL,
                business_goal=f"Produce the {stage} candidate for chapter {chapter_number}.",
                current_issue="Return a Candidate; Domain Authority owns validation and commit.",
                scope_snapshot_ref=scope_snapshot_id,
                participant_snapshot_ref=participant_snapshot_id,
                input_asset_versions=input_versions,
                candidate_version_ref="",
                context_bundle_ref=context.asset_version_id,
                evidence_refs=(
                    execution_binding.route_snapshot.prompt_bundle_ref,
                    execution_binding.route_snapshot.skill_bundle_ref,
                ),
                must_preserve=("frozen input AssetVersions", "Domain Authority commit"),
                must_change=(f"{stage} candidate",),
                forbidden_changes=("canon.mutate", "plan.activate", "publish.activate"),
                acceptance_criteria=(
                    "PEP validation manifest present",
                    "candidate schema valid",
                    "Chapter Domain Handler accepts output",
                ),
                risk_level=str(capability["risk_class"]),
                budget_policy_ref=execution_binding.request.budget_policy_ref,
                timeout_policy_ref=execution_binding.request.timeout_policy_ref,
                approval_policy_ref=str(agent["approval_policy_ref"]),
                failure_policy="AUTHORITY_RETRY_OR_REPAIR",
                continuation_policy="DOMAIN_AUTHORITY_COMMIT_THEN_WORKFLOW",
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=book_id,
                route_snapshot_ref=execution_binding.route_snapshot.route_snapshot_id,
                input_manifest_ref=execution_binding.input_manifest.manifest_id,
                capability_version=int(capability["capability_version"]),
                execution_capability=str(capability["execution_capability_id"]),
            )
            runtime_binding = AgentRuntimeBinding(
                binding_id=_identity(
                    "chapter-agent-runtime-binding", request.attempt_id
                ),
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=book_id,
                workflow_definition_ref=self.workflow_definition_ref,
                workflow_node_id=stage,
                operation_definition_ref=(
                    f"{operation['definition_name']}@{operation['definition_version']}"
                ),
                operation_definition_hash=str(operation["definition_hash"]),
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                work_order_id=work_order.work_order_id,
                agent_id=work_order.agent_id,
                agent_definition_version=work_order.agent_definition_version,
                agent_definition_hash=str(agent["definition_hash"]),
                capability_id=work_order.capability,
                capability_version=work_order.capability_version,
                capability_hash=str(capability["capability_hash"]),
                execution_capability_id=work_order.execution_capability,
                chapter_node_binding_ref=(
                    f"{node_binding['binding_id']}@{node_binding['binding_version']}"
                ),
                capability_pack_ref=str(node_binding["capability_pack_ref"]),
                capability_pack_compilation_hash=str(
                    node_binding["capability_pack_compilation_hash"]
                ),
                context_bundle_asset_version_id=context.asset_version_id,
                context_bundle_hash=context.content_hash,
                prompt_bundle_ref=contracts["prompt_bundle_ref"],
                prompt_bundle_hash=contracts["prompt_bundle_hash"],
                skill_bundle_ref=contracts["skill_bundle_ref"],
                skill_bundle_hash=contracts["skill_bundle_hash"],
                tool_policy_ref=str(agent["tool_policy_ref"]),
                tool_policy_hash=str(agent["tool_policy_hash"]),
                tool_permission_snapshot_ref=contracts["tool_permission_snapshot_ref"],
                tool_permission_snapshot_hash=contracts[
                    "tool_permission_snapshot_hash"
                ],
                context_policy_ref=contracts["context_policy_ref"],
                context_policy_hash=contracts["context_policy_hash"],
                route_snapshot_ref=contracts["route_snapshot_ref"],
                route_snapshot_hash=contracts["route_snapshot_hash"],
                input_manifest_ref=contracts["input_manifest_ref"],
                input_manifest_hash=contracts["input_manifest_hash"],
                budget_policy_ref=execution_binding.request.budget_policy_ref,
                timeout_policy_ref=execution_binding.request.timeout_policy_ref,
                approval_policy_ref=str(agent["approval_policy_ref"]),
                validation_policy_ref=execution_binding.request.validation_policy_ref,
                commit_policy_ref=execution_binding.request.commit_policy_ref,
                commit_authority=str(node_binding["commit_authority"]),
                release_sha=str(node_binding["release_sha"]),
            )
            self.turn_coordinator.freeze_turn_in_uow(uow, work_order, runtime_binding)
            uow.commit()
        self.turn_coordinator.fault_injector("after_runtime_binding_freeze")
        return FrozenChapterAgentWorkOrder(
            work_order=work_order,
            chapter_number=chapter_number,
            owner_authority=str(node_binding["commit_authority"]),
        )

    def accept_candidate(
        self,
        frozen_work_order: FrozenChapterAgentWorkOrder,
        *,
        result: ModelProviderResult,
        execution_binding: ChapterExecutionBinding,
    ) -> None:
        evidence = _domain_evidence(result, execution_binding)
        work_order = frozen_work_order.work_order
        candidate_id = _identity("chapter-agent-candidate", work_order.attempt_id)
        output_id = _identity("chapter-agent-output", work_order.attempt_id)
        proposed_change = ProposedAssetChange(
            asset_type=f"{execution_binding.request.stage}_candidate",
            asset_version_id="",
            narrative_scope=NarrativeScope(
                kind=NarrativeScopeType.CHAPTER,
                book_id=work_order.book_id,
                volume_id=f"{work_order.book_id}:volume:active",
                arc_id=f"{work_order.book_id}:arc:active",
                chapter_group_id=f"{work_order.book_id}:chapter-group:active",
                chapter_id=(
                    f"{work_order.book_id}:chapter:{frozen_work_order.chapter_number}"
                ),
            ),
            change_type=f"{execution_binding.request.stage}.propose",
            knowledge_visibility=KnowledgeVisibility.AUTHOR_KNOWLEDGE,
            chapter_number=frozen_work_order.chapter_number,
            touches_published_content=False,
        )
        envelope = AgentOutputEnvelope(
            output_id=output_id,
            session_id=work_order.collaboration_session_id,
            turn_id=work_order.turn_id,
            agent_id=work_order.agent_id,
            message_type=AgentMessageType.PROPOSAL,
            structured_payload={
                "candidate_version_id": candidate_id,
                "candidate_type": f"{execution_binding.request.stage}_candidate",
                "content_ref": evidence.output_manifest_ref,
                "structured_diff": {
                    "op": "candidate.create",
                    "path": f"/{execution_binding.request.stage}",
                    "value_ref": evidence.output_manifest_ref,
                },
                "domain_candidate": result.output,
                "commit_status": "NOT_COMMITTED",
                "change_reason_refs": [evidence.validation_manifest_ref],
            },
            natural_language_explanation=(
                "PEP produced a Candidate for Chapter Domain Authority validation."
            ),
            source_asset_versions=work_order.input_asset_versions,
            evidence_refs=(
                evidence.output_manifest_ref,
                evidence.validation_manifest_ref,
            ),
            assumptions=(),
            confidence=0.5,
            affected_assets=(),
            proposed_changes=(proposed_change,),
            preserved_constraints=work_order.must_preserve,
            accessed_knowledge=(KnowledgeVisibility.AUTHOR_KNOWLEDGE,),
            unresolved_questions=(),
            risk_level=work_order.risk_level,
            requested_next_action="DOMAIN_AUTHORITY_VALIDATE_AND_COMMIT",
            execution_evidence_ref=evidence.validation_manifest_ref,
        )
        accepted = self.turn_coordinator.accept_envelope(work_order, envelope, evidence)
        if not accepted.attempt_completion_allowed:
            raise KernelError(
                "CHAPTER_AGENT_CANDIDATE_REJECTED",
                "Agent candidate failed collaboration scope validation",
            )

    def finalize_domain_commit(
        self,
        *,
        project_id: str,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        asset_version_id: str,
        content_hash: str,
    ) -> CollaborationCommit:
        """Attach the accepted Candidate to the already materialized Chapter asset."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT work_order.session_id, candidate.candidate_version_id,
                       binding.commit_policy_ref, binding.commit_authority,
                       output.execution_evidence_ref
                FROM authority_agent_runtime_binding AS binding
                JOIN authority_agent_work_order AS work_order
                  ON work_order.work_order_id=binding.work_order_id
                JOIN authority_agent_candidate_version AS candidate
                  ON candidate.originating_turn_id=work_order.turn_id
                LEFT JOIN authority_agent_output_envelope AS output
                  ON output.turn_id=work_order.turn_id
                WHERE binding.project_id=%s AND binding.operation_id=%s
                  AND binding.attempt_id=%s
                  AND EXISTS (
                      SELECT 1 FROM authority_lease_acquisition AS lease
                      WHERE lease.attempt_id=binding.attempt_id
                        AND lease.fencing_token=%s
                        AND lease.status='HELD'
                  )
                """,
                [project_id, operation_id, attempt_id, fencing_token],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CHAPTER_AGENT_CANDIDATE_MISSING",
                "Agent-bound Chapter asset cannot complete without its Candidate",
            )
        return self.turn_coordinator.record_existing_domain_commit(
            ExistingDomainAssetCommit(
                project_id=project_id,
                session_id=str(row[0]),
                candidate_version_id=str(row[1]),
                operation_id=operation_id,
                attempt_id=attempt_id,
                fencing_token=fencing_token,
                asset_version_id=asset_version_id,
                content_hash=content_hash,
                commit_policy_ref=str(row[2]),
                authority_type=str(row[3]),
                receipt_ref=(
                    f"authority-operation-output:{operation_id}:{asset_version_id}"
                ),
                decision_evidence=tuple(item for item in (str(row[4] or ""),) if item),
            )
        )

    def record_domain_rejection(
        self,
        *,
        project_id: str,
        operation_id: str,
        attempt_id: str,
        error_code: str,
    ) -> bool:
        """Record Domain validation failure without creating an AssetVersion."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT session.session_id, candidate.candidate_version_id,
                       binding.commit_authority, binding.commit_policy_ref,
                       session.authority_decision_id
                FROM authority_agent_runtime_binding AS binding
                JOIN authority_agent_work_order AS work_order
                  ON work_order.work_order_id=binding.work_order_id
                JOIN authority_agent_collaboration_session AS session
                  ON session.session_id=work_order.session_id
                JOIN authority_agent_candidate_version AS candidate
                  ON candidate.originating_turn_id=work_order.turn_id
                WHERE binding.project_id=%s AND binding.operation_id=%s
                  AND binding.attempt_id=%s
                """,
                [project_id, operation_id, attempt_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                uow.commit()
                return False
            if row[4]:
                uow.commit()
                return True
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            application.request_authority_decision(
                str(row[0]), domain_candidate_validated=True
            )
            application.apply_authority_decision(
                CollaborationDecision(
                    decision_id=_identity(
                        "chapter-agent-domain-rejection", str(row[0])
                    ),
                    decision=CollaborationDecisionType.REPAIR_REQUIRED,
                    authority_type=str(row[2]),
                    authority_version=1,
                    session_id=str(row[0]),
                    candidate_version_id=str(row[1]),
                    accepted_changes=(),
                    rejected_changes=("domain handler rejected candidate",),
                    deferred_changes=(),
                    accepted_with_objections=(),
                    unresolved_objections=(error_code,),
                    required_followup=("repair candidate and rerun Domain validation",),
                    affected_asset_versions=(),
                    commit_policy_ref=str(row[3]),
                    decision_evidence=(f"domain-error:{error_code}",),
                )
            )
            uow.commit()
            return True

    def record_compatibility_usage(
        self, request: ChapterHandlerRequest, *, stage: str
    ) -> None:
        self.legacy_writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=f"legacy-usage:{request.operation_id}:{stage}",
                asset_type="legacy_usage_event",
                schema_version="legacy-usage-event.v1",
                logical_ref=f"legacy_usage/chapter_agent_binding/{request.operation_id}/{stage}",
                category="audit",
                output_key=f"legacy_usage.chapter_agent_binding.{stage}",
                role="compatibility_evidence",
                content={
                    "classification": "COMPATIBILITY_ADAPTER",
                    "source": "chapter_handler_model_port",
                    "replacement": "postgresql_agent_definition_and_chapter_binding",
                    "stage": stage,
                    "operation_id": request.operation_id,
                    "attempt_id": request.attempt_id,
                    "silent_fallback": False,
                    "production_authority": False,
                },
                qualification_policy="legacy-usage-audit-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        )


def _operation_snapshot(cursor: Any, request: ChapterHandlerRequest) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT operation.definition_name, operation.definition_version,
               operation.definition_snapshot, saga.saga_id
        FROM authority_operation AS operation
        LEFT JOIN authority_saga AS saga
          ON saga.root_operation_id=operation.root_operation_id
         AND saga.project_id=operation.project_id
        WHERE operation.operation_id=%s AND operation.project_id=%s
        """,
        [request.operation_id, request.project_id],
    )
    row = cursor.fetchone()
    if row is None or not row[3]:
        raise KernelError(
            "CHAPTER_AGENT_OPERATION_NOT_FOUND",
            "Chapter Agent Binding requires a real Authority Saga operation",
        )
    definition = dict(row[2] or {})
    return {
        "definition_name": str(row[0]),
        "definition_version": str(row[1]),
        "definition_hash": str(definition.get("definition_hash") or ""),
        "definition_snapshot": definition,
        "saga_id": str(row[3]),
    }


def _validate_operation_binding(
    operation: dict[str, Any], binding: dict[str, Any], stage: str
) -> None:
    expected = (
        str(binding["operation_definition_name"]),
        str(binding["operation_definition_version"]),
        str(binding["operation_definition_hash"]),
    )
    actual = (
        str(operation["definition_name"]),
        str(operation["definition_version"]),
        str(operation["definition_hash"]),
    )
    if actual != expected:
        raise KernelError(
            "CHAPTER_AGENT_OPERATION_BINDING_DRIFT",
            f"Chapter {stage} operation differs from active Agent Binding",
        )


def _bound_capability(
    agent: dict[str, Any],
    binding: dict[str, Any],
    *,
    production_required: bool,
) -> dict[str, Any]:
    matches = [
        item
        for item in agent["capabilities"]
        if str(item["capability_id"]) == str(binding["capability_id"])
        and int(item["capability_version"]) == int(binding["capability_version"])
    ]
    if len(matches) != 1:
        raise KernelError(
            "CHAPTER_AGENT_CAPABILITY_NOT_BOUND",
            "Agent Definition does not contain the Chapter-bound Capability version",
        )
    capability = matches[0]
    expected = (
        str(binding["capability_hash"]),
        str(binding["execution_capability_id"]),
    )
    actual = (
        str(capability["capability_hash"]),
        str(capability["execution_capability_id"]),
    )
    if actual != expected:
        raise KernelError(
            "CHAPTER_AGENT_CAPABILITY_DRIFT",
            "Agent Capability differs from its frozen PEP mapping",
        )
    if (
        production_required
        and capability["qualification_status"] != "QUALIFIED_REAL_RUNTIME"
    ):
        raise KernelError(
            "CHAPTER_AGENT_CAPABILITY_NOT_PRODUCTION_QUALIFIED",
            "controlled Chapter execution requires REAL_RUNTIME qualification",
        )
    return capability


def _validate_definition_binding(
    agent: dict[str, Any], binding: dict[str, Any]
) -> None:
    expected = {
        "agent_id": binding["agent_id"],
        "definition_version": binding["agent_definition_version"],
        "definition_hash": binding["agent_definition_hash"],
        "capability_pack_ref": binding["capability_pack_ref"],
        "input_contract_ref": binding["input_contract_ref"],
        "output_contract_ref": binding["output_contract_ref"],
    }
    drift = [
        key for key, value in expected.items() if str(agent.get(key)) != str(value)
    ]
    if drift:
        raise KernelError(
            "CHAPTER_AGENT_DEFINITION_BINDING_DRIFT",
            "active Agent Definition differs from Chapter binding: " + ", ".join(drift),
        )


def _execution_contracts(
    assets: Any,
    project_id: str,
    binding: ChapterExecutionBinding,
) -> dict[str, str]:
    suffix = binding.route_snapshot.route_snapshot_id.rsplit("/", 1)[-1]
    refs = {
        "route_snapshot_ref": binding.route_snapshot.route_snapshot_id,
        "input_manifest_ref": binding.input_manifest.manifest_id,
        "prompt_bundle_ref": binding.route_snapshot.prompt_bundle_ref,
        "skill_bundle_ref": binding.route_snapshot.skill_bundle_ref,
        "tool_permission_snapshot_ref": f"production_execution/tool_permissions/{suffix}",
        "context_policy_ref": (
            "context-policy:" + binding.request.capability.replace(".", "-") + ":v1"
        ),
    }
    frozen: dict[str, str] = {}
    for name, logical_ref in refs.items():
        document = assets.require(project_id=project_id, logical_ref=logical_ref)
        frozen[name] = logical_ref
        frozen[name.removesuffix("_ref") + "_hash"] = document.content_hash
    return frozen


def _chapter_number(
    request: ChapterHandlerRequest, binding: ChapterExecutionBinding
) -> int:
    value = int(binding.request.target_scope.get("chapter_number") or 0)
    if value <= 0:
        raise KernelError(
            "CHAPTER_AGENT_SCOPE_INVALID",
            "Agent-bound Chapter execution requires a positive chapter number",
        )
    return value


def _domain_evidence(
    result: ModelProviderResult,
    binding: ChapterExecutionBinding,
) -> DomainExecutionEvidence:
    production = dict(result.execution_evidence or {})
    execution_result = dict(production.get("execution_result") or {})
    execution_handle = dict(production.get("execution_handle") or {})
    required = {
        "output_manifest_ref": execution_result.get("output_manifest_ref"),
        "validation_manifest_ref": execution_result.get("validation_report_ref"),
        "usage_receipt_ref": execution_result.get("usage_receipt_ref"),
        "cost_receipt_ref": execution_result.get("cost_receipt_ref"),
    }
    if any(not value for value in required.values()):
        raise KernelError(
            "CHAPTER_AGENT_PEP_EVIDENCE_INCOMPLETE",
            "successful Chapter Agent Candidate lacks required PEP manifests",
        )
    return DomainExecutionEvidence(
        execution_id=binding.request.execution_id,
        operation_id=binding.request.operation_id,
        attempt_id=binding.request.attempt_id,
        fencing_token=binding.request.fencing_token,
        capability=binding.request.capability,
        backend_id=str(execution_handle.get("backend_id") or ""),
        route_snapshot_id=binding.request.route_snapshot_id,
        input_manifest_ref=binding.request.input_manifest_ref,
        output_manifest_ref=str(required["output_manifest_ref"]),
        validation_manifest_ref=str(required["validation_manifest_ref"]),
        usage_receipt_ref=str(required["usage_receipt_ref"]),
        cost_receipt_ref=str(required["cost_receipt_ref"]),
        fixture_protocol_only=not result.real_model_call,
        real_model_call=result.real_model_call,
        production_verified=False,
        provider_id=result.provider_id,
        model_id=result.model_id,
        provider_request_id=str(execution_handle.get("provider_request_id") or ""),
        external_receipt_ref=str(execution_result.get("external_receipt_ref") or ""),
    )


def _identity(kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"novel-forge:{kind}:{value}"))


__all__ = [
    "AGENT_BOUND_CHAPTER_STAGES",
    "FrozenChapterAgentWorkOrder",
    "PostgresChapterAgentBindingRecorder",
]
