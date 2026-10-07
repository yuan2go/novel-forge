from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
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
    admit_command,
)
from novel_forge.modules.content_authority.scheduler import (
    ContentAuthorityScheduler,
)
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
    PostgresHierarchicalPlanningAuthority,
)
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    PlanningScope,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.narrative_realization_repositories import (
    NarrativeRealizationRepository,
)

from .domain import (
    PlanChangeSource,
    classify_plan_change_risk,
    require_approvable_scope,
    semantic_plan_diff,
)
from .semantic_impact import (
    load_semantic_impact_discovery,
    resolve_semantic_dispositions,
)


VERSION = "1.0.4"
COORDINATED_VERSION = "1.0.6"
DEFINITIONS = {
    "plan_change.propose": (
        "plan_change_proposal",
        "plan_change.proposal",
    ),
    "plan_change.approve": (
        "plan_change_decision",
        "plan_change.decision",
    ),
    "plan_change.activate": (
        "plan_change_activation_receipt",
        "plan_change.activation",
    ),
    "plan_change.revalidate": (
        "plan_revalidation_receipt",
        "plan_change.revalidation",
    ),
}
HANDLER_PREFIX = "novel_forge.plan_change_authority"


@dataclass(frozen=True, slots=True)
class PlanChangeProposalCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    stable_idempotency_key: str
    source_type: PlanChangeSource
    source_evidence_version_id: str
    target_asset_version_id: str
    proposed_asset_version_id: str


class _Handler:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "PLAN_CHANGE_INPUT_INVALID",
                "PlanChange payload must be an object",
            )
        asset_type, output_key = DEFINITIONS[request.definition_name]
        content = {
            "type": {
                "plan_change.propose": "PlanChangeProposal",
                "plan_change.approve": "PlanChangeDecision",
                "plan_change.activate": "PlanChangeActivationReceipt",
                "plan_change.revalidate": "PlanRevalidationReceipt",
            }[request.definition_name],
            "contract_version": request.definition_name.replace(".", "-") + "-v1",
            **payload,
            "source_asset_versions": [item.asset_version_id for item in request.inputs],
            "direct_plan_mutation_allowed": False,
        }
        return AuthorityHandlerOutput(
            asset_type=asset_type,
            output_key=output_key,
            role="primary",
            content=content,
            qualification_policy="plan-change-authority-v1",
            reference_asset_version_ids=tuple(
                item.asset_version_id for item in request.inputs
            ),
            evidence={"deterministic": True, "model_calls": 0},
        )


class _Registry:
    def __init__(self) -> None:
        handler = _Handler()
        self.items = {
            (name, version): AuthorityHandlerRegistration(
                definition_name=name,
                definition_version=version,
                handler_key=f"{HANDLER_PREFIX}.{name}",
                handler_contract_version="plan-change-handler-v1",
                output_asset_type=asset_type,
                output_key=output_key,
                role="primary",
                completion_topic=f"{name}.completed",
                handler=handler,
            )
            for name, (asset_type, output_key) in DEFINITIONS.items()
            for version in (VERSION, COORDINATED_VERSION)
        }

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(item.handler_key for item in self.items.values())

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        return self.items[(definition_name, definition_version)]


class PostgresPlanChangeAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        story_design: PostgresStoryDesignAssetAuthority,
        planning: PostgresHierarchicalPlanningAuthority,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "plan-change-authority-worker",
        failure_injector: Callable[[str], None] | None = None,
        coordinated_contract: bool = False,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "PlanChange Authority requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.story_design = story_design
        self.planning = planning
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.failure_injector = failure_injector
        self.registry = _Registry()
        self.coordinated_contract = coordinated_contract

    def propose(
        self, command: PlanChangeProposalCommand, *, principal: Principal
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", command.project_id)
        frozen = self._frozen_proposal(command)
        if frozen is not None:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    "SELECT proposal_id FROM authority_plan_change_proposal WHERE proposal_operation_id=%s",
                    [frozen["operation_id"]],
                )
                existing = uow.cursor.fetchone()
            if existing is not None:
                return self.require(str(existing[0]))
        if command.source_type is PlanChangeSource.HUMAN_FEEDBACK:
            from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

            source = AuthorityAssetQuery(self.database_url).require(
                project_id=command.project_id,
                asset_version_id=command.source_evidence_version_id,
            )
            if (
                source.asset_type != "replan_request"
                or source.content.get("contract_version")
                != "operator-planning-change-request.v1"
                or source.content.get("authority_boundary")
                != "FUTURE_PLAN_PROPOSAL_ONLY"
                or source.content.get("book_id") != command.book_id
                or source.content.get("target_plan_version_id")
                != command.target_asset_version_id
            ):
                raise KernelError(
                    "PLAN_CHANGE_FEEDBACK_SCOPE_INVALID",
                    "operator change evidence must bind this Book and target plan",
                )
        target = self._target_binding(
            command.project_id,
            command.book_id,
            command.target_asset_version_id,
            require_active=frozen is None,
        )
        proposed = self._proposed_design(
            command.project_id, command.proposed_asset_version_id
        )
        if (
            proposed["logical_key"] != target["logical_key"]
            or proposed["planning_scope"] != target["contract_type"]
        ):
            raise KernelError(
                "PLAN_CHANGE_CANDIDATE_SCOPE_MISMATCH",
                "proposed plan must target the same logical key and scope",
            )
        require_approvable_scope(str(target["execution_scope"]))
        changes = semantic_plan_diff(dict(target["content"]), dict(proposed["content"]))
        if not changes:
            raise KernelError(
                "PLAN_CHANGE_EMPTY",
                "PlanChangeProposal must contain semantic changes",
            )
        risk = classify_plan_change_risk(
            changes,
            target_execution_scope=str(target["execution_scope"]),
        )
        diff = [asdict(change) for change in changes]
        if frozen is None:
            with AuthorityUnitOfWork(self.database_url) as uow:
                discovery = load_semantic_impact_discovery(
                    uow.cursor,
                    project_id=command.project_id,
                    book_id=command.book_id,
                    target_asset_version_id=command.target_asset_version_id,
                    proposed_asset_version_id=command.proposed_asset_version_id,
                    changes=diff,
                )
            payload = {
                "book_id": command.book_id,
                "source_type": command.source_type.value,
                "target_asset_version_id": command.target_asset_version_id,
                "proposed_asset_version_id": command.proposed_asset_version_id,
                "semantic_diff": diff,
                "risk": risk.value,
                "authority_decision_required": True,
                "semantic_impact_discovery": discovery,
            }
        else:
            payload = frozen["payload"]
        operation_id = self._execute(
            definition="plan_change.propose",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=principal.principal_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            idempotency_key=command.stable_idempotency_key,
            payload=payload,
            input_assets=self._resolve(
                command.project_id,
                (
                    command.source_evidence_version_id,
                    command.target_asset_version_id,
                    command.proposed_asset_version_id,
                ),
            ),
            principal=principal,
        )
        proposal_id = f"plan-change:{operation_id}"
        self._probe("after_proposal_execution_before_projection")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.plan_change.create_proposal(
                {
                    "proposal_id": proposal_id,
                    "project_id": command.project_id,
                    "book_id": command.book_id,
                    "source_type": command.source_type.value,
                    "source_evidence_version_id": (command.source_evidence_version_id),
                    "target_asset_version_id": (command.target_asset_version_id),
                    "proposed_asset_version_id": (command.proposed_asset_version_id),
                    "target_contract_type": target["contract_type"],
                    "target_logical_key": target["logical_key"],
                    "target_execution_scope": target["execution_scope"],
                    "semantic_diff": diff,
                    "risk": risk.value,
                    "proposal_operation_id": operation_id,
                    "stable_idempotency_key": (command.stable_idempotency_key),
                }
            )
            uow.commit()
        return self.require(proposal_id)

    def decide(
        self,
        proposal_id: str,
        *,
        approved: bool,
        authority_type: str,
        authority_version: str,
        evidence: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:
        proposal = self.require(proposal_id)
        principal.require("book.authority.execute", proposal["project_id"])
        workspace_id = self._workspace_id(proposal["project_id"], proposal["book_id"])
        decision = "APPROVED" if approved else "REJECTED"
        dispositions = resolve_semantic_dispositions(
            proposal["semantic_impact_discovery"],
            evidence.get("semantic_impact_dispositions", []),
        )
        evidence = {**evidence, "semantic_impact_dispositions": dispositions}
        if proposal["approval_operation_id"]:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    "SELECT decision,authority_type,authority_version,evidence FROM authority_plan_change_decision WHERE proposal_id=%s",
                    [proposal_id],
                )
                recorded = uow.cursor.fetchone()
            if recorded is None or tuple(recorded) != (
                decision,
                authority_type,
                authority_version,
                evidence,
            ):
                raise KernelError(
                    "PLAN_CHANGE_DECISION_CONFLICT",
                    "a recorded decision cannot be rewritten by a retry",
                )
            return proposal
        if approved:
            from novel_forge.modules.mkaos_authority.craft_scope import validate_scope_transition_decision
            validate_scope_transition_decision(self.database_url, proposal=proposal, evidence=evidence)
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.repositories.plan_change.require_current_inferred_impacts(
                    project_id=proposal["project_id"],
                    book_id=proposal["book_id"],
                    discovery=proposal["semantic_impact_discovery"],
                    dispositions=dispositions,
                )
        proposal_output = self._operation_output(
            proposal["proposal_operation_id"], "plan_change.proposal"
        )
        operation_id = self._execute(
            definition="plan_change.approve",
            project_id=proposal["project_id"],
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            trace_id=f"{proposal_id}:decision",
            correlation_id=proposal["proposal_operation_id"],
            idempotency_key=f"{proposal['stable_idempotency_key']}:decision",
            payload={
                "proposal_id": proposal_id,
                "decision": decision,
                "authority_type": authority_type,
                "authority_version": authority_version,
                "evidence": evidence,
            },
            input_assets=(proposal_output,),
            principal=principal,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            if evidence.get("contract_version") == "book-authorized-future-correction.v2":
                if not self.coordinated_contract:
                    raise KernelError("BOOK_AUTO_REPLAN_CONTRACT_INVALID", "Auto approval requires the explicit current owner")
                from novel_forge.modules.book_replan.auto_authorization import require_auto_replan_proof
                require_auto_replan_proof(uow.cursor,project_id=proposal["project_id"],proposal_id=proposal_id,actor_id=principal.principal_id,evidence=evidence)
            uow.repositories.plan_change.decide(
                proposal_id=proposal_id,
                project_id=proposal["project_id"],
                decision=decision,
                operation_id=operation_id,
                authority_type=authority_type,
                authority_version=authority_version,
                evidence=evidence,
                decided_by=principal.principal_id,
            )
            uow.commit()
        return self.require(proposal_id)

    def activate(self, proposal_id: str, *, principal: Principal) -> dict[str, Any]:
        proposal = self.require(proposal_id)
        principal.require("book.authority.execute", proposal["project_id"])
        workspace_id = self._workspace_id(proposal["project_id"], proposal["book_id"])
        if proposal["status"] not in {
            "APPROVED",
            "ACTIVATION_PENDING",
            "ACTIVE",
        }:
            raise KernelError(
                "PLAN_CHANGE_NOT_APPROVED",
                "only approved PlanChangeProposal can activate",
            )
        if proposal["status"] == "ACTIVE":
            return proposal
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.plan_change.require_current_inferred_impacts(
                project_id=proposal["project_id"],
                book_id=proposal["book_id"],
                discovery=proposal["semantic_impact_discovery"],
                dispositions=proposal["semantic_impact_dispositions"],
            )
        proposed_state = self.story_design.require(
            project_id=proposal["project_id"],
            asset_version_id=proposal["proposed_asset_version_id"],
        )
        decision_output = self._operation_output(
            proposal["approval_operation_id"], "plan_change.decision"
        )
        operation_id = self._execute(
            definition="plan_change.activate",
            project_id=proposal["project_id"],
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            trace_id=f"{proposal_id}:activate",
            correlation_id=proposal["proposal_operation_id"],
            idempotency_key=(f"{proposal['stable_idempotency_key']}:activate"),
            payload={
                "proposal_id": proposal_id,
                "target_asset_version_id": proposal["target_asset_version_id"],
                "proposed_asset_version_id": proposal["proposed_asset_version_id"],
                "recoverable_activation": True,
            },
            input_assets=(
                decision_output,
                *self._resolve(
                    proposal["project_id"],
                    (proposal["proposed_asset_version_id"],),
                ),
            ),
            principal=principal,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.plan_change.mark_activation_pending(
                proposal_id, operation_id
            )
            uow.commit()
        if proposed_state["approval"] == "PENDING":
            proposed_state = self.story_design.transition(
                StoryDesignTransitionCommand(
                    project_id=proposal["project_id"],
                    workspace_id=workspace_id,
                    actor_id=principal.principal_id,
                    trace_id=f"{proposal_id}:story-design-approve",
                    correlation_id=operation_id,
                    idempotency_key=(
                        f"{proposal['stable_idempotency_key']}:story-design-approve"
                    ),
                    asset_version_id=proposal["proposed_asset_version_id"],
                    content_hash=self._asset_hash(
                        proposal["proposed_asset_version_id"]
                    ),
                    logical_key=proposal["target_logical_key"],
                    generator_operation_name=proposed_state["generator_operation_name"],
                    transition=DesignTransition.APPROVE,
                    planning_scope=PlanningScope(proposal["target_contract_type"]),
                    expected_version=int(proposed_state["version"]),
                    evidence={
                        "plan_change_proposal_id": proposal_id,
                        "decision_operation_id": proposal["approval_operation_id"],
                        "authority_type": "PLAN_CHANGE_AUTHORITY",
                    },
                ),
                principal=principal,
            )
        if proposed_state["lifecycle"] != "ACTIVE":
            self.story_design.transition(
                StoryDesignTransitionCommand(
                    project_id=proposal["project_id"],
                    workspace_id=workspace_id,
                    actor_id=principal.principal_id,
                    trace_id=f"{proposal_id}:story-design-activate",
                    correlation_id=operation_id,
                    idempotency_key=(
                        f"{proposal['stable_idempotency_key']}:story-design-activate"
                    ),
                    asset_version_id=proposal["proposed_asset_version_id"],
                    content_hash=self._asset_hash(
                        proposal["proposed_asset_version_id"]
                    ),
                    logical_key=proposal["target_logical_key"],
                    generator_operation_name=proposed_state["generator_operation_name"],
                    transition=DesignTransition.ACTIVATE,
                    planning_scope=PlanningScope(proposal["target_contract_type"]),
                    expected_version=int(proposed_state["version"]),
                    evidence={
                        "plan_change_proposal_id": proposal_id,
                        "decision_operation_id": proposal["approval_operation_id"],
                        "replacement_approved": True,
                    },
                ),
                principal=principal,
            )
        else:
            self._require_story_design_active(proposal)
        if getattr(self,"coordinated_contract",False):
            from novel_forge.modules.story_design_authority.creative_validation import validation_state,project_approved_validation_eligibility
            if validation_state(proposed_state):
                with AuthorityUnitOfWork(self.database_url) as uow:
                    project_approved_validation_eligibility(uow.cursor,project_id=proposal["project_id"],book_id=proposal["book_id"],asset_version_id=proposal["proposed_asset_version_id"])
                    uow.commit()
        self._probe("after_plan_activation_before_binding")
        target = self._target_binding(
            proposal["project_id"],
            proposal["book_id"],
            proposal["target_asset_version_id"],
            require_active=False,
        )
        self.planning.bind_active_contract(
            project_id=proposal["project_id"],
            book_id=proposal["book_id"],
            asset_version_id=proposal["proposed_asset_version_id"],
            contract_type=PlanContractType(proposal["target_contract_type"]),
            parent_version_id=str(target["parent_version_id"] or ""),
            execution_scope=PlanExecutionScope(proposal["target_execution_scope"]),
            replacement_approved=True,
            expected_active_asset_version_id=proposal["target_asset_version_id"],
            decision_evidence={
                "plan_change_proposal_id": proposal_id,
                "approval_operation_id": proposal["approval_operation_id"],
            },
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            idempotency_key=(f"{proposal['stable_idempotency_key']}:planning-binding"),
            trace_id=f"{proposal_id}:planning-binding",
            correlation_id=proposal["proposal_operation_id"],
            causation_operation_id=operation_id,
            principal=principal,
        )
        self._probe("after_plan_activation_before_outbox")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.plan_change.require_current_inferred_impacts(
                project_id=proposal["project_id"],
                book_id=proposal["book_id"],
                discovery=proposal["semantic_impact_discovery"],
                dispositions=proposal["semantic_impact_dispositions"],
            )
            uow.repositories.plan_change.record_impacts(
                proposal_id=proposal_id,
                project_id=proposal["project_id"],
                source_asset_version_id=proposal["target_asset_version_id"],
                operation_id=operation_id,
            )
            inferred_impacts = uow.repositories.plan_change.record_inferred_impacts(
                proposal_id=proposal_id,
                project_id=proposal["project_id"],
                book_id=proposal["book_id"],
                source_asset_version_id=proposal["target_asset_version_id"],
                operation_id=operation_id,
                discovery=proposal["semantic_impact_discovery"],
                dispositions=proposal["semantic_impact_dispositions"],
            )
            invalidated_realization_ids = NarrativeRealizationRepository(
                uow.cursor
            ).stale_for_noncurrent_plan_inputs(
                project_id=proposal["project_id"],
                book_id=proposal["book_id"],
                operation_id=operation_id,
            )
            uow.repositories.plan_change.mark_active(proposal_id)
            event_id = str(uuid4())
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": event_id,
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "plan_change_proposal",
                    "aggregate_id": proposal_id,
                    "operation_id": operation_id,
                    "project_id": proposal["project_id"],
                    "event_type": "plan_change.activated",
                    "correlation_id": proposal["proposal_operation_id"],
                    "causation_id": proposal["approval_operation_id"],
                    "payload": {
                        "proposal_id": proposal_id,
                        "new_plan_version_id": proposal["proposed_asset_version_id"],
                        "inferred_impact_asset_version_ids": inferred_impacts,
                        "invalidated_narrative_realization_ids": list(
                            invalidated_realization_ids
                        ),
                    },
                }
            )
            uow.commit()
        return self.require(proposal_id)

    def revalidate(
        self,
        *,
        project_id: str,
        asset_version_id: str,
        evidence_version_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        workspace_id = self._workspace_for_asset(project_id, asset_version_id)
        operation_id = self._execute(
            definition="plan_change.revalidate",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            trace_id=f"{asset_version_id}:revalidate",
            correlation_id=asset_version_id,
            idempotency_key=(
                f"plan-revalidate:{project_id}:{asset_version_id}:{evidence_version_id}"
            ),
            payload={
                "asset_version_id": asset_version_id,
                "evidence_version_id": evidence_version_id,
            },
            input_assets=self._resolve(
                project_id, (asset_version_id, evidence_version_id)
            ),
            principal=principal,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            applied = uow.repositories.plan_change.revalidate(
                project_id=project_id,
                asset_version_id=asset_version_id,
                evidence_version_id=evidence_version_id,
                operation_id=operation_id,
            )
            uow.cursor.execute(
                "SELECT freshness FROM story_plan_binding WHERE project_id=%s AND asset_version_id=%s",
                [project_id, asset_version_id],
            )
            freshness = str(uow.cursor.fetchone()[0])
            if not applied:
                return {
                    "asset_version_id": asset_version_id,
                    "freshness": freshness,
                    "operation_id": operation_id,
                }
            event_id = str(uuid4())
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": event_id,
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "story_plan_binding",
                    "aggregate_id": asset_version_id,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "event_type": "plan_change.revalidated",
                    "correlation_id": asset_version_id,
                    "causation_id": evidence_version_id,
                    "payload": {
                        "asset_version_id": asset_version_id,
                        "evidence_version_id": evidence_version_id,
                    },
                }
            )
            uow.commit()
        return {
            "asset_version_id": asset_version_id,
            "freshness": freshness,
            "operation_id": operation_id,
        }

    def require(self, proposal_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            proposal = uow.repositories.plan_change.require(proposal_id)
            uow.cursor.execute(
                """SELECT version.content FROM authority_operation_output_asset output
                   JOIN authority_asset_version version USING(asset_version_id)
                   WHERE output.operation_id=%s AND output.output_key='plan_change.proposal'""",
                [proposal["proposal_operation_id"]],
            )
            content = uow.cursor.fetchone()
            proposal["semantic_impact_discovery"] = (content[0] if content else {}).get(
                "semantic_impact_discovery", {}
            )
            uow.cursor.execute(
                "SELECT evidence FROM authority_plan_change_decision WHERE proposal_id=%s",
                [proposal_id],
            )
            decision = uow.cursor.fetchone()
            proposal["semantic_impact_dispositions"] = (
                decision[0] if decision else {}
            ).get("semantic_impact_dispositions", [])
            return proposal

    def _frozen_proposal(
        self, command: PlanChangeProposalCommand
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT operation_id,project_id,workspace_id,command_payload
                   FROM authority_operation WHERE idempotency_scope='project:plan-change'
                     AND idempotency_key=%s""",
                [command.stable_idempotency_key],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        payload = row[3].get("payload", {})
        if (
            row[1] != command.project_id
            or row[2] != command.workspace_id
            or row[3].get("input_asset_version_ids")
            != [
                command.source_evidence_version_id,
                command.target_asset_version_id,
                command.proposed_asset_version_id,
            ]
            or payload.get("book_id") != command.book_id
            or payload.get("source_type") != command.source_type.value
        ):
            raise KernelError(
                "IDEMPOTENCY_CONFLICT",
                "Plan Change retry must retain its original scope and source versions",
            )
        return {"operation_id": row[0], "payload": payload}

    def _execute(
        self,
        *,
        definition: str,
        project_id: str,
        workspace_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
        principal: Principal,
    ) -> str:
        self._register_definitions()
        current = getattr(self, "coordinated_contract", False)
        if current:
            from novel_forge.modules.book_authority.reader_pack import require_current_reader_template
            with AuthorityUnitOfWork(self.database_url) as uow:
                book_id = str(payload.get("book_id") or "")
                if not book_id:
                    uow.cursor.execute("SELECT book_id FROM authority_plan_change_proposal WHERE proposal_id=%s AND project_id=%s", [payload.get("proposal_id"),project_id])
                    row = uow.cursor.fetchone()
                    book_id = str(row[0]) if row else ""
                require_current_reader_template(uow.cursor,project_id=project_id,book_id=book_id)
        predecessor = self._proposal_contract_predecessor(definition=definition, project_id=project_id,workspace_id=workspace_id,
            actor_id=actor_id,idempotency_key=idempotency_key,payload=payload,input_assets=input_assets) if current else ""
        definition_version = COORDINATED_VERSION if current else VERSION
        if current and not predecessor:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute("""SELECT definition_version FROM authority_operation
                    WHERE project_id=%s AND definition_name=%s AND idempotency_scope='project:plan-change'
                      AND idempotency_key=%s""", [project_id,definition,idempotency_key])
                frozen = uow.cursor.fetchone()
            if frozen:
                if frozen[0] not in {VERSION, COORDINATED_VERSION}:
                    raise KernelError("IDEMPOTENCY_CONFLICT", "Unsupported frozen PlanChange identity")
                definition_version = str(frozen[0])
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition,
                "definition_version": definition_version,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:plan-change",
                "idempotency_key": idempotency_key + ":contract-successor:" + COORDINATED_VERSION if predecessor else idempotency_key,
                **({"parent_operation_id":predecessor,"causation_operation_id":predecessor} if predecessor else {}),
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": payload,
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="PlanChange inputs frozen",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id="",
                ),
            )
            start_saga(
                self.database_url,
                GraphCommandContext(project_id, actor_id, trace_id, correlation_id),
                root_operation_id=operation_id,
            )
        ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=operation_id,
            project_id=project_id,
        )
        return operation_id

    def _proposal_contract_predecessor(
        self,
        *,
        definition,
        project_id,
        workspace_id,
        actor_id,
        idempotency_key,
        payload,
        input_assets,
    ):
        if definition != "plan_change.propose":
            return ""
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT operation_id,definition_version,status,project_id,workspace_id,actor_id,
                command_payload,input_asset_snapshot FROM authority_operation
                WHERE idempotency_scope='project:plan-change' AND idempotency_key=%s AND project_id=%s FOR UPDATE""",
                [idempotency_key,project_id],
            )
            row = uow.cursor.fetchone()
            if (
                not row
                or row[1] != VERSION
                or row[2] not in {"FAILED_FINAL", "DEAD_LETTER"}
            ):
                return ""
            uow.cursor.execute(
                "SELECT result,error FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1",
                [row[0]],
            )
            attempt = uow.cursor.fetchone()
            failure = (
                (attempt[0] or {}).get("error_code")
                or (attempt[1] or {}).get("error_code")
                if attempt
                else ""
            )
            uow.cursor.execute(
                """SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)
                OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt owned USING(attempt_id) WHERE owned.operation_id=%s AND lease.released_at IS NULL AND lease.expires_at>NOW())
                OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s AND state IN ('ABORTED','CANCELLED'))
                OR EXISTS(SELECT 1 FROM authority_story_formation_run formation JOIN authority_story_creation_cancellation cancel USING(formation_run_id)
                  WHERE formation.project_id=%s AND formation.book_id=%s)""",
                [
                    row[0],
                    row[0],
                    row[0],
                    row[0],
                    project_id,
                    payload["book_id"],
                    project_id,
                    payload["book_id"],
                ],
            )
            unsafe = uow.cursor.fetchone()[0]
            if (
                failure != "AUTHORITY_INPUT_NOT_ELIGIBLE"
                or unsafe
                or row[3:6] != (project_id, workspace_id, actor_id)
                or row[6].get("payload") != payload
                or row[7]
                != [{"project_id": project_id, **item} for item in input_assets]
            ):
                raise KernelError(
                    "PLAN_CHANGE_CONTRACT_SUCCESSOR_UNSAFE",
                    "Only the exact zero-effect pending-input contract failure may continue",
                )
            candidate = require_validation_plan_change_input(
                uow.cursor, project_id=project_id, payload=payload
            )
            if not candidate:
                raise KernelError(
                    "PLAN_CHANGE_CONTRACT_SUCCESSOR_UNSAFE",
                    "Source candidate requires its original creative-validation admission",
                )
            from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
            require_known_cli_lineage(uow.cursor,project_id=project_id,operation_id=str(row[0]))
            return str(row[0])

    def _target_binding(
        self,
        project_id: str,
        book_id: str,
        asset_version_id: str,
        *,
        require_active: bool = True,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            active_join = (
                "JOIN active_story_plan_version AS active "
                "ON active.binding_id=binding.binding_id"
                if require_active
                else ""
            )
            uow.cursor.execute(
                f"""
                SELECT binding.contract_type, binding.logical_key,
                       binding.execution_scope, binding.parent_version_id,
                       binding.freshness, version.content
                FROM story_plan_binding AS binding
                {active_join}
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.asset_version_id=%s
                """,
                [project_id, book_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLAN_CHANGE_TARGET_NOT_ACTIVE",
                "PlanChange target is not an active typed plan",
            )
        fields = (
            "contract_type",
            "logical_key",
            "execution_scope",
            "parent_version_id",
            "freshness",
            "content",
        )
        return dict(zip(fields, row, strict=True))

    def _proposed_design(
        self, project_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        state = self.story_design.require(
            project_id=project_id, asset_version_id=asset_version_id
        )
        from novel_forge.modules.story_design_authority.creative_validation import candidate_validation

        with AuthorityUnitOfWork(self.database_url) as uow:
            validation = candidate_validation(uow.cursor, project_id=project_id, asset_version_id=asset_version_id)
        admitted = state["qualification"] == "QUALIFIED" or (
            validation is not None
            and state["qualification"] == "STRUCTURALLY_VALID"
            and state["execution_evidence"].get("creative_validation") == validation
        )
        if (
            state["approval"] not in {"PENDING", "APPROVED"}
            or not admitted
            or state["lifecycle"] != "MATERIALIZED"
        ):
            raise KernelError(
                "PLAN_CHANGE_CANDIDATE_NOT_QUALIFIED",
                "proposed plan must be qualified, approval-pending or approved, and inactive",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        return {**state, "content": dict(row[0])}

    def _workspace_id(self, project_id: str, book_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT workspace_id FROM authority_book
                WHERE project_id=%s AND book_id=%s
                """,
                [project_id, book_id],
            )
            rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "PLAN_CHANGE_BOOK_SCOPE_INVALID",
                "PlanChange could not resolve one authoritative Book workspace",
            )
        return str(rows[0][0])

    def _workspace_for_asset(self, project_id: str, asset_version_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT DISTINCT book_id FROM story_plan_binding
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [project_id, asset_version_id],
            )
            rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "PLAN_CHANGE_ASSET_SCOPE_INVALID",
                "Plan revalidation requires one authoritative Book binding",
            )
        return self._workspace_id(project_id, str(rows[0][0]))

    def _resolve(
        self, project_id: str, version_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            results = []
            for version_id in version_ids:
                uow.cursor.execute(
                    """
                    SELECT version.content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset
                      ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s
                      AND asset.project_id=%s
                    """,
                    [version_id, project_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    raise KernelError(
                        "PLAN_CHANGE_INPUT_NOT_FOUND",
                        f"missing Project-scoped AssetVersion {version_id}",
                    )
                results.append(
                    {
                        "asset_version_id": version_id,
                        "content_hash": str(row[0]),
                    }
                )
        return tuple(results)

    def _asset_hash(self, asset_version_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content_hash FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLAN_CHANGE_INPUT_NOT_FOUND",
                "proposed AssetVersion does not exist",
            )
        return str(row[0])

    def _require_story_design_active(self, proposal: dict[str, Any]) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset_version_id
                FROM authority_story_design_active_version
                WHERE project_id=%s AND logical_key=%s
                """,
                [
                    proposal["project_id"],
                    proposal["target_logical_key"],
                ],
            )
            row = uow.cursor.fetchone()
        if row is None or str(row[0]) != proposal["proposed_asset_version_id"]:
            raise KernelError(
                "PLAN_CHANGE_ACTIVATION_RECOVERY_CONFLICT",
                "active Story Design version differs from the proposal",
            )

    def _operation_output(self, operation_id: str, output_key: str) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, version.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s AND binding.output_key=%s
                """,
                [operation_id, output_key],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLAN_CHANGE_OUTPUT_MISSING",
                f"missing output {output_key}",
            )
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name, (asset_type, output_key) in DEFINITIONS.items():
                uow.repositories.definitions.register(
                    _definition(
                        name,
                        asset_type,
                        output_key,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
                if self.coordinated_contract:
                    uow.repositories.definitions.register(_definition(name,asset_type,output_key,
                        application_build_id=self.application_build_id,commit_sha=self.commit_sha,definition_version=COORDINATED_VERSION))
            uow.commit()

    def _probe(self, point: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(point)


def _definition(
    name: str,
    asset_type: str,
    output_key: str,
    *,
    application_build_id: str,
    commit_sha: str,
    definition_version: str = VERSION,
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": name,
        "definition_version": definition_version,
        "family": "plan_change_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending" if definition_version == COORDINATED_VERSION else "integration_proven",
        "command_schema_version": f"{name}.command.v1",
        "result_schema_version": f"{name}.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "asset_type": asset_type,
            "output_key": output_key,
        },
        "handler_key": f"{HANDLER_PREFIX}.{name}",
        "handler_contract_version": "plan-change-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["book.authority.execute"],
        # INVARIANT: The formal decision is an Authority asset consumed by activate; the
        # generic admission approval field would duplicate that authority.
        "approval_policy": {"required": False},
        "idempotency_scope": "project:plan-change",
        "concurrency_key_template": "project:{project_id}:plan-change",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only proposal and recoverable activation",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "direct_active_plan_mutation": False,
            "impact_analysis_required": True,
            "plan_change_candidate_asset_input_allowed": (
                name in {"plan_change.propose", "plan_change.activate"}
            ),
            **({"plan_change_validation_candidate_asset_input_allowed":name in {"plan_change.propose","plan_change.activate"}} if definition_version == COORDINATED_VERSION else {}),
            "semantic_revalidation_target_input_allowed": (
                name == "plan_change.revalidate"
            ),
        },
        "completion_contract": {
            "version": "plan-change-completion-v1",
            "required_asset_selectors": [
                {
                    "selector": asset_type,
                    "output_key": output_key,
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [f"{name}.completed"],
        },
    }


__all__ = ["PlanChangeProposalCommand", "PostgresPlanChangeAuthority"]


def require_validation_plan_change_input(cursor, *, project_id, payload):
    from novel_forge.modules.story_design_authority.creative_validation import (
        candidate_validation,
    )

    identity = str(payload.get("proposed_asset_version_id") or "")
    book_id = payload.get("book_id")
    if not book_id and payload.get("proposal_id"):
        cursor.execute(
            "SELECT book_id,proposed_asset_version_id FROM authority_plan_change_proposal WHERE proposal_id=%s AND project_id=%s AND status IN ('APPROVED','ACTIVATION_PENDING','ACTIVE')",
            [payload["proposal_id"], project_id],
        )
        proposal = cursor.fetchone()
        if not proposal or proposal[1] != identity:
            raise KernelError(
                "PLAN_CHANGE_VALIDATION_INPUT_INVALID",
                "Activation requires the exact approved same-Book proposal",
            )
        book_id = proposal[0]
    validation = candidate_validation(
        cursor, project_id=project_id, asset_version_id=identity
    )
    if validation is None:
        return ""
    cursor.execute(
        """SELECT state.qualification,state.approval,state.lifecycle,state.freshness,
        state.execution_evidence,version.content->>'book_id' FROM authority_story_design_version_state state
        JOIN authority_asset_version version USING(asset_version_id)
        WHERE state.project_id=%s AND state.asset_version_id=%s""",
        [project_id, identity],
    )
    row = cursor.fetchone()
    if (
        not row
        or row[0] != "STRUCTURALLY_VALID"
        or row[1] not in {"PENDING", "APPROVED"}
        or row[2] not in {"MATERIALIZED", "ACTIVE"}
        or row[3] != "CURRENT"
        or row[4].get("creative_validation") != validation
        or validation["book_id"] != book_id
        or row[5] != validation["book_id"]
    ):
        raise KernelError(
            "PLAN_CHANGE_VALIDATION_INPUT_INVALID",
            "Exact current same-Book structural admission required for pending proposal input",
        )
    from novel_forge.modules.book_authority.reader_pack import require_current_reader_template
    from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage
    require_current_reader_template(cursor,project_id=project_id,book_id=book_id)
    require_known_cli_lineage(cursor,project_id=project_id,operation_id=validation["generation_operation_id"])
    cursor.execute("SELECT definition_name,definition_version,status,command_payload #>> '{payload,book_id}',command_payload #>> '{payload,execution_contract_version}' FROM authority_operation WHERE operation_id=%s AND project_id=%s",[validation["generation_operation_id"],project_id])
    owner=cursor.fetchone()
    if (not owner or owner[:2] != ("story_planning.generate","1.21.0")
        or owner[2] not in {"WAITING_GATE","SUCCEEDED"} or owner[3:] != (book_id,"1.21.0")):
        raise KernelError("PLAN_CHANGE_VALIDATION_INPUT_INVALID","Pending input requires its exact native current same-Book Planning owner")
    cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED') OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt owned USING(attempt_id) WHERE owned.operation_id=%s AND lease.released_at IS NULL AND lease.expires_at>NOW())",[validation["generation_operation_id"],validation["generation_operation_id"]])
    if cursor.fetchone()[0]:
        raise KernelError("PLAN_CHANGE_VALIDATION_INPUT_INVALID","Original candidate accounting and leases must settle")
    return identity
