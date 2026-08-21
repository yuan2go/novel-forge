"""Operation-backed PlanChange proposal, approval, impact and activation."""

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

from .domain import (
    PlanChangeSource,
    classify_plan_change_risk,
    require_approvable_scope,
    semantic_plan_diff,
)


VERSION = "1.0.4"
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
            (name, VERSION): AuthorityHandlerRegistration(
                definition_name=name,
                definition_version=VERSION,
                handler_key=f"{HANDLER_PREFIX}.{name}",
                handler_contract_version="plan-change-handler-v1",
                output_asset_type=asset_type,
                output_key=output_key,
                role="primary",
                completion_topic=f"{name}.completed",
                handler=handler,
            )
            for name, (asset_type, output_key) in DEFINITIONS.items()
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

    def propose(
        self, command: PlanChangeProposalCommand, *, principal: Principal
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", command.project_id)
        target = self._target_binding(
            command.project_id,
            command.book_id,
            command.target_asset_version_id,
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
        operation_id = self._execute(
            definition="plan_change.propose",
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=principal.principal_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            idempotency_key=command.stable_idempotency_key,
            payload={
                "book_id": command.book_id,
                "source_type": command.source_type.value,
                "target_asset_version_id": command.target_asset_version_id,
                "proposed_asset_version_id": (command.proposed_asset_version_id),
                "semantic_diff": diff,
                "risk": risk.value,
                "authority_decision_required": True,
            },
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
            uow.repositories.plan_change.record_impacts(
                proposal_id=proposal_id,
                project_id=proposal["project_id"],
                source_asset_version_id=proposal["target_asset_version_id"],
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
            uow.repositories.plan_change.revalidate(
                project_id=project_id,
                asset_version_id=asset_version_id,
                evidence_version_id=evidence_version_id,
                operation_id=operation_id,
            )
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
            "freshness": "CURRENT",
            "operation_id": operation_id,
        }

    def require(self, proposal_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.plan_change.require(proposal_id)

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
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition,
                "definition_version": VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:plan-change",
                "idempotency_key": idempotency_key,
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
        if (
            state["approval"] not in {"PENDING", "APPROVED"}
            or state["qualification"] != "QUALIFIED"
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
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": name,
        "definition_version": VERSION,
        "family": "plan_change_authority",
        "enabled": True,
        "definition_status": "integration_proven",
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
        # The formal decision is an Authority asset consumed by activate; the
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
