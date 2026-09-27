from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority import (
    BookProductionInputResolver,
    BookProductionState,
    PostgresBookAuthority,
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.plan_change_authority import (
    PlanChangeProposalCommand,
    PlanChangeSource,
    PostgresPlanChangeAuthority,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PlanningGenerationStatus,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


SCOPE_GENERATOR = {
    "BOOK": "book_plan.generate",
    "VOLUME": "volume_plan.generate",
    "NARRATIVE_SEGMENT": "volume_plan.generate",
    "ARC": "arc_plan.generate",
    "ARC_SEGMENT": "arc_plan.generate",
    "CHAPTER_GROUP": "chapter_group_plan.generate",
    "CHAPTER": "chapter_plan.generate",
}

SCOPE_CONTRACT = {
    "BOOK": "BOOK",
    "VOLUME": "VOLUME",
    "NARRATIVE_SEGMENT": "VOLUME",
    "ARC": "ARC",
    "ARC_SEGMENT": "ARC",
    "CHAPTER_GROUP": "CHAPTER_GROUP",
    "CHAPTER": "CHAPTER",
}

_SNAPSHOT_ROLE_FIELDS = (
    "production_profile_version",
    "reader_segment_version",
    "reader_contract_version",
    "platform_profile_version",
    "character_state_version",
    "foreshadowing_state_version",
    "quality_trend_version",
    "reward_ledger_version",
    "promise_ledger_version",
)


@dataclass(frozen=True, slots=True)
class CoordinateBookReplanCommand:
    project_id: str
    workspace_id: str
    book_id: str
    book_run_id: str
    source_recap_asset_version_id: str
    replan_request_asset_version_id: str
    affected_scope: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    target_asset_version_id: str = ""

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.book_run_id,
            self.source_recap_asset_version_id,
            self.replan_request_asset_version_id,
            self.affected_scope,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if (
            any(not item.strip() for item in required)
            or self.affected_scope not in SCOPE_GENERATOR
        ):
            raise ValueError("Book Replan command is incomplete")


@dataclass(frozen=True, slots=True)
class ReevaluateBookReplanCommand:
    project_id: str
    workspace_id: str
    replan_id: str
    source_recap_asset_version_id: str
    deviation_report_asset_version_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.project_id,
                self.workspace_id,
                self.replan_id,
                self.source_recap_asset_version_id,
                self.deviation_report_asset_version_id,
                self.idempotency_key,
                self.trace_id,
                self.correlation_id,
            )
        ):
            raise ValueError("Book Replan reevaluation command is incomplete")


class BookReplanCoordinator:

    def __init__(
        self,
        database_url: str,
        *,
        book_authority: PostgresBookAuthority,
        planning: StoryPlanningGenerationApplication,
        plan_change: PostgresPlanChangeAuthority,
        input_resolver: BookProductionInputResolver,
        principal: Principal,
        fault_injector: Any | None = None,
        narrative_search: PostgresNarrativeSearchApplication | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("Book Replan requires PostgreSQL")
        self.database_url = database_url
        self.book = book_authority
        self.planning = planning
        self.plan_change = plan_change
        self.input_resolver = input_resolver
        self.principal = principal
        self.fault_injector = fault_injector or (lambda _checkpoint: None)
        self.narrative_search = narrative_search or PostgresNarrativeSearchApplication(
            database_url, planning=planning
        )

    def start(self, command: CoordinateBookReplanCommand) -> dict[str, Any]:
        self.principal.require("book.authority.execute", command.project_id)
        existing = self._find_by_idempotency(
            command.project_id, command.idempotency_key
        )
        if existing is not None:
            return existing
        book = self.book.require(command.book_run_id)
        self._require_scope(book, command)
        recap_lineage = self._require_recap_lineage(command)
        recap_operation_id = str(recap_lineage["operation_id"])
        replan_request = dict(recap_lineage["replan_request"])
        declared_scope = str(replan_request.get("affected_scope") or "")
        if declared_scope and declared_scope != command.affected_scope:
            raise KernelError(
                "BOOK_REPLAN_SCOPE_ESCALATION_FORBIDDEN",
                "Replan command cannot exceed or change the evidence-approved scope",
            )
        target = self._target_plan(command, int(book["accepted_through_chapter"]) + 1)
        self._require_segment_target(
            affected_scope=command.affected_scope,
            target_content=target["content"],
            impact_scope=dict(replan_request.get("impact_scope") or {}),
        )
        if target["execution_scope"] == "EXECUTED":
            raise KernelError(
                "BOOK_REPLAN_EXECUTED_PLAN_FORBIDDEN",
                "ordinary Replan cannot modify an Executed plan",
            )
        generator = SCOPE_GENERATOR[command.affected_scope]
        (
            inputs,
            frozen_related_arc_plan_version_ids,
            governance_action_version_ids,
        ) = self._replacement_inputs(
            command.project_id,
            target_asset_version_id=target["asset_version_id"],
            generator=generator,
        )
        arc_scope_volume_plan_version_ids: tuple[str, ...] = ()
        related_arc_plan_version_ids: tuple[str, ...] = ()
        dependent_arc_plan_version_ids: tuple[str, ...] = ()
        if generator == "arc_plan.generate":
            original_scope = tuple(
                str(item) for item in target["content"].get("cross_volume_scope") or ()
            )
            primary_volume = str(inputs.get("volume_plan") or "")
            if not original_scope or original_scope[0] != primary_volume:
                raise KernelError(
                    "BOOK_REPLAN_ARC_SCOPE_STALE",
                    "Arc replacement must preserve its ordered primary Volume scope",
                )
            arc_scope_volume_plan_version_ids = original_scope[1:]
            related_arc_plan_version_ids = self._related_arc_versions(
                project_id=command.project_id,
                book_id=command.book_id,
                dependent_arc_plan_version_id=str(target["asset_version_id"]),
            )
            dependent_arc_plan_version_ids = self._dependent_arc_versions(
                project_id=command.project_id,
                book_id=command.book_id,
                source_arc_plan_version_id=str(target["asset_version_id"]),
            )
        elif generator in {
            "chapter_group_plan.generate",
            "chapter_plan.generate",
        }:
            related_arc_plan_version_ids = frozen_related_arc_plan_version_ids
        generation = StoryPlanningGenerationCommand(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            actor_id=self.principal.principal_id,
            generator_operation_name=generator,
            logical_key=target["logical_key"],
            input_versions=inputs,
            parent_version_id=target["parent_version_id"],
            arc_scope_volume_plan_version_ids=(arc_scope_volume_plan_version_ids),
            related_arc_plan_version_ids=related_arc_plan_version_ids,
            dependent_arc_plan_version_ids=dependent_arc_plan_version_ids,
            change_evidence_version_ids=(
                command.source_recap_asset_version_id,
                command.replan_request_asset_version_id,
            ),
            governance_action_version_ids=governance_action_version_ids,
            idempotency_key=f"{command.idempotency_key}:replacement-candidate",
            trace_id=command.trace_id,
            correlation_id=recap_operation_id,
            auto_approve_low_risk=False,
        )
        if generator == "chapter_plan.generate":
            generated = self.planning.generate(generation, principal=self.principal)
        else:
            planning_horizon: dict[str, Any] = {
                "level": SCOPE_CONTRACT[command.affected_scope],
                "future_only": True,
                "affected_scope": command.affected_scope,
            }
            desired_transformation: dict[str, Any] = {
                "replan_request_asset_version_id": (
                    command.replan_request_asset_version_id
                ),
                "target_asset_version_id": target["asset_version_id"],
                "impact_scope": dict(replan_request.get("impact_scope") or {}),
            }
            if generator == "chapter_group_plan.generate":
                chapter_range = target["content"].get("chapter_range")
                if not isinstance(chapter_range, list) or len(chapter_range) != 2:
                    raise KernelError(
                        "BOOK_REPLAN_CHAPTER_GROUP_HORIZON_INVALID",
                        "ChapterGroup replacement requires the exact target range",
                    )
                start, end = map(int, chapter_range)
                planning_horizon.update(
                    starts_at_chapter=start,
                    ends_at_chapter=end,
                    chapter_range=[start, end],
                )
                desired_transformation["chapter_range"] = [start, end]
            generated = self.narrative_search.explore(
                NarrativeSearchRequest(
                    generation=generation,
                    planning_horizon=planning_horizon,
                    desired_transformation=desired_transformation,
                    hard_constraints=tuple(
                        str(item)
                        for item in replan_request.get("preserved_invariants") or ()
                    )
                    or (
                        "accepted chapters and accepted narrative state are immutable",
                    ),
                    accepted_through_chapter=int(book["accepted_through_chapter"]),
                    book_run_id=command.book_run_id,
                    parent_state_asset_version_id=str(
                        book.get("active_story_state_version_id") or ""
                    ),
                ),
                principal=self.principal,
                activate_selected=False,
            ).selected_generation
        if generated.status is not PlanningGenerationStatus.APPROVAL_PENDING:
            raise KernelError(
                "BOOK_REPLAN_CANDIDATE_NOT_PENDING",
                "replacement Candidate must stop at Authority approval",
            )
        proposal = self.plan_change.propose(
            PlanChangeProposalCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=self.principal.principal_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                stable_idempotency_key=f"{command.idempotency_key}:plan-change",
                source_type=(
                    PlanChangeSource.ARC_CLOSURE_RISK
                    if replan_request.get("type") == "ArcRevisionCandidate"
                    else PlanChangeSource.LONGFORM_RECAP
                ),
                source_evidence_version_id=command.replan_request_asset_version_id,
                target_asset_version_id=target["asset_version_id"],
                proposed_asset_version_id=generated.candidate_asset_version_id,
            ),
            principal=self.principal,
        )
        self.fault_injector("after_plan_change_proposal_before_replan_checkpoint")
        replan_id = (
            "book-replan:"
            + hashlib.sha256(
                f"{command.project_id}:{command.idempotency_key}".encode()
            ).hexdigest()
        )

        def record_start(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_book_replan(
                    replan_id, project_id, book_id, book_run_id,
                    source_recap_asset_version_id,
                    replan_request_asset_version_id, affected_scope,
                    future_only, target_asset_version_id,
                    replacement_candidate_asset_version_id,
                    generation_operation_id, plan_change_proposal_id,
                    input_snapshot_id, status, stable_idempotency_key,
                    created_by_operation_id, impact_scope,
                    preserved_invariants, decision_evidence
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,%s,%s,%s,
                    'APPROVAL_PENDING',%s,%s,%s,%s,%s
                ) ON CONFLICT(project_id, stable_idempotency_key) DO NOTHING
                """,
                [
                    replan_id,
                    command.project_id,
                    command.book_id,
                    command.book_run_id,
                    command.source_recap_asset_version_id,
                    command.replan_request_asset_version_id,
                    command.affected_scope,
                    target["asset_version_id"],
                    generated.candidate_asset_version_id,
                    generated.generation_operation_id,
                    proposal["proposal_id"],
                    book["input_snapshot_id"],
                    command.idempotency_key,
                    operation_id,
                    Jsonb(dict(replan_request.get("impact_scope") or {})),
                    Jsonb(list(replan_request.get("preserved_invariants") or [])),
                    Jsonb(list(replan_request.get("decision_evidence") or [])),
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_production
                SET state='REPLAN_APPROVAL_PENDING', version=version+1,
                    updated_at=NOW()
                WHERE book_run_id=%s
                  AND state IN ('REPLAN_REQUIRED','READY','PLANNING_REQUIRED')
                """,
                [command.book_run_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_REPLAN_STATE_CONFLICT",
                    "Book state changed before Replan admission",
                )
            if replan_request.get("type") == "ArcRevisionCandidate":
                uow.cursor.execute(
                    """
                    UPDATE authority_arc_checkpoint_followup
                    SET status='WAITING_APPROVAL', plan_change_id=%s,
                        version=version+1, updated_at=NOW()
                    WHERE operation_id=%s AND status='PROPOSED'
                    """,
                    [proposal["proposal_id"], recap_operation_id],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "ARC_REVISION_FOLLOWUP_STATE_CONFLICT",
                        "ArcRevision follow-up was not ready for PlanChange",
                    )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=command.project_id,
                replan_id=replan_id,
                event_type="book.replan.approval_pending",
                correlation_id=command.correlation_id,
                payload={
                    "plan_change_proposal_id": proposal["proposal_id"],
                    "replacement_candidate_asset_version_id": (
                        generated.candidate_asset_version_id
                    ),
                },
            )
            checkpoint("after_outbox_insert")
            return {"replan_id": replan_id, "status": "APPROVAL_PENDING"}

        self._run_checkpoint(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            idempotency_key=f"{command.idempotency_key}:record",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_operation_id=generated.generation_operation_id,
            payload={
                "transition": "APPROVAL_PENDING",
                "replan_id": replan_id,
                "book_run_id": command.book_run_id,
                "generation_operation_id": generated.generation_operation_id,
                "plan_change_proposal_id": proposal["proposal_id"],
            },
            handler=record_start,
        )
        result = self.require(replan_id)
        return result

    def _find_by_idempotency(
        self, project_id: str, stable_idempotency_key: str
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT replan_id FROM authority_book_replan
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [project_id, stable_idempotency_key],
            )
            row = uow.cursor.fetchone()
        return self.require(str(row[0])) if row is not None else None

    def latest_for_book(self, book_run_id: str) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT replan_id
                FROM authority_book_replan
                WHERE book_run_id=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [book_run_id],
            )
            row = uow.cursor.fetchone()
        return self.require(str(row[0])) if row is not None else None

    def _run_checkpoint(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        causation_operation_id: str,
        payload: dict[str, Any],
        handler: Any,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                _replan_checkpoint_definition(
                    application_build_id=self.book.application_build_id,
                    commit_sha=self.book.commit_sha,
                )
            )
            uow.commit()
        return dict(
            execute_transaction_command(
                self.database_url,
                {
                    "definition_name": "book.replan.checkpoint.record",
                    "definition_version": "1.0.0",
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "book_id": book_id,
                    "actor_id": self.principal.principal_id,
                    "idempotency_scope": "book:replan-checkpoint",
                    "idempotency_key": idempotency_key,
                    "trace_id": trace_id,
                    "span_id": str(uuid4()),
                    "correlation_id": correlation_id,
                    "causation_id": causation_operation_id,
                    "causation_operation_id": causation_operation_id,
                    "input": {"project_id": project_id, "book_id": book_id, **payload},
                    "input_assets": [],
                },
                context=AdmissionContext(
                    actor_id=self.principal.principal_id,
                    permissions=frozenset({"book.authority.execute"}),
                    available_handlers=frozenset(
                        {"novel_forge.book.replan.checkpoint.record"}
                    ),
                    application_build_id=self.book.application_build_id,
                    commit_sha=self.book.commit_sha,
                ),
                handler=handler,
            )
        )

    @staticmethod
    def _event(
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        project_id: str,
        replan_id: str,
        event_type: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_replan",
                "aggregate_id": replan_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": event_type,
                "correlation_id": correlation_id,
                "causation_id": correlation_id,
                "payload": {"operation_id": operation_id, **payload},
            }
        )

    def approve(
        self,
        replan_id: str,
        *,
        authority_type: str,
        authority_version: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        replan = self.require(replan_id)
        self.principal.require(
            "book.authority.approve_replan", str(replan["project_id"])
        )
        if replan["status"] in {"ACTIVE", "REGENERATING", "RESUMED"}:
            return {
                **replan,
                "plan_change": self.plan_change.require(
                    replan["plan_change_proposal_id"]
                ),
            }
        if replan["status"] != "APPROVAL_PENDING":
            raise KernelError(
                "BOOK_REPLAN_APPROVAL_STATE_INVALID",
                "Book Replan is not waiting for Authority approval",
            )
        proposal = self.plan_change.decide(
            replan["plan_change_proposal_id"],
            approved=True,
            authority_type=authority_type,
            authority_version=authority_version,
            evidence={**evidence, "book_replan_id": replan_id, "future_only": True},
            principal=self.principal,
        )
        book = self.book.require(replan["book_run_id"])

        def record_approval(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                UPDATE authority_book_replan
                SET status='ACTIVE', version=version+1, updated_at=NOW()
                WHERE replan_id=%s AND status='APPROVAL_PENDING'
                """,
                [replan_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_REPLAN_STATE_CONFLICT",
                    "Replan status changed before approval checkpoint",
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_production
                SET state='REPLAN_GENERATING', version=version+1, updated_at=NOW()
                WHERE book_run_id=%s AND state='REPLAN_APPROVAL_PENDING'
                """,
                [replan["book_run_id"]],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_REPLAN_STATE_CONFLICT",
                    "Book status changed before approval checkpoint",
                )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=replan["project_id"],
                replan_id=replan_id,
                event_type="book.replan.approved",
                correlation_id=str(proposal["approval_operation_id"]),
                payload={
                    "plan_change_proposal_id": replan["plan_change_proposal_id"],
                    "decision_operation_id": proposal["approval_operation_id"],
                },
            )
            checkpoint("after_outbox_insert")
            return {"replan_id": replan_id, "status": "ACTIVE"}

        try:
            self._run_checkpoint(
                project_id=replan["project_id"],
                workspace_id=str(book["workspace_id"]),
                book_id=replan["book_id"],
                idempotency_key=f"{replan['stable_idempotency_key']}:approval-record",
                trace_id=f"{replan_id}:approval",
                correlation_id=str(proposal["approval_operation_id"]),
                causation_operation_id=str(proposal["approval_operation_id"]),
                payload={
                    "transition": "ACTIVE",
                    "replan_id": replan_id,
                    "plan_change_decision_operation_id": proposal[
                        "approval_operation_id"
                    ],
                },
                handler=record_approval,
            )
        except KernelError as exc:
            replay = self.require(replan_id)
            if exc.code != "BOOK_REPLAN_STATE_CONFLICT" or replay["status"] not in {
                "ACTIVE",
                "REGENERATING",
                "RESUMED",
            }:
                raise
        return {**self.require(replan_id), "plan_change": proposal}

    def activate(self, replan_id: str) -> dict[str, Any]:
        replan = self.require(replan_id)
        if replan["status"] not in {"ACTIVE", "REGENERATING", "RESUMED"}:
            raise KernelError(
                "BOOK_REPLAN_APPROVAL_REQUIRED",
                "Book Replan requires a PlanChange approval decision",
            )
        if replan["status"] == "RESUMED":
            return replan
        proposal = self.plan_change.activate(
            replan["plan_change_proposal_id"], principal=self.principal
        )
        book = self.book.require(replan["book_run_id"])

        def record_regenerating(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                UPDATE authority_book_replan
                SET status='REGENERATING', version=version+1, updated_at=NOW()
                WHERE replan_id=%s AND status='ACTIVE'
                """,
                [replan_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_REPLAN_STATE_CONFLICT",
                    "Replan status changed before regeneration checkpoint",
                )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=replan["project_id"],
                replan_id=replan_id,
                event_type="book.replan.regenerating",
                correlation_id=str(proposal["activation_operation_id"]),
                payload={
                    "plan_change_activation_operation_id": proposal[
                        "activation_operation_id"
                    ]
                },
            )
            checkpoint("after_outbox_insert")
            return {"replan_id": replan_id, "status": "REGENERATING"}

        if replan["status"] == "ACTIVE":
            self._run_checkpoint(
                project_id=replan["project_id"],
                workspace_id=str(book["workspace_id"]),
                book_id=replan["book_id"],
                idempotency_key=(
                    f"{replan['stable_idempotency_key']}:regenerating-record"
                ),
                trace_id=f"{replan_id}:regenerating",
                correlation_id=str(proposal["activation_operation_id"]),
                causation_operation_id=str(proposal["activation_operation_id"]),
                payload={"transition": "REGENERATING", "replan_id": replan_id},
                handler=record_regenerating,
            )
        chapter_plan_projection: dict[str, Any] | None = None
        if replan["affected_scope"] == "CHAPTER":
            chapter_plan_projection = (
                self.planning.materialize_activated_chapter_plan_projection(
                    replan["replacement_candidate_asset_version_id"],
                    principal=self.principal,
                    idempotency_key=(
                        f"{replan['stable_idempotency_key']}:chapter-plan-projection"
                    ),
                    trace_id=f"{replan_id}:chapter-plan-projection",
                    correlation_id=str(proposal["activation_operation_id"]),
                )
            )
        replacement_child = self._regenerate_future_plan(replan, proposal)
        book = self.book.require(replan["book_run_id"])
        snapshot = self._resolve_new_snapshot(book, proposal["activation_operation_id"])
        resumed = self.book.bind_replanned_input_snapshot(
            replan["book_run_id"],
            snapshot_id=snapshot.snapshot_id,
            causation_operation_id=proposal["activation_operation_id"],
            target_state=BookProductionState.READY,
            expected_version=int(book["version"]),
            principal=self.principal,
        )

        def record_resumed(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                UPDATE authority_book_replan
                SET status='RESUMED', input_snapshot_id=%s,
                    version=version+1, updated_at=NOW()
                WHERE replan_id=%s AND status='REGENERATING'
                """,
                [snapshot.snapshot_id, replan_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_REPLAN_STATE_CONFLICT",
                    "Replan status changed before resume checkpoint",
                )
            uow.cursor.execute(
                """
                UPDATE authority_arc_checkpoint_followup
                SET status='COMPLETED', version=version+1, updated_at=NOW()
                WHERE plan_change_id=%s AND status='WAITING_APPROVAL'
                """,
                [replan["plan_change_proposal_id"]],
            )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=replan["project_id"],
                replan_id=replan_id,
                event_type="book.replan.resumed",
                correlation_id=str(proposal["activation_operation_id"]),
                payload={
                    "input_snapshot_id": snapshot.snapshot_id,
                    "replacement_child_candidate": replacement_child,
                    "chapter_plan_projection": chapter_plan_projection,
                },
            )
            checkpoint("after_outbox_insert")
            return {"replan_id": replan_id, "status": "RESUMED"}

        self._run_checkpoint(
            project_id=replan["project_id"],
            workspace_id=str(book["workspace_id"]),
            book_id=replan["book_id"],
            idempotency_key=f"{replan['stable_idempotency_key']}:resume-record",
            trace_id=f"{replan_id}:resume",
            correlation_id=str(proposal["activation_operation_id"]),
            causation_operation_id=str(proposal["activation_operation_id"]),
            payload={
                "transition": "RESUMED",
                "replan_id": replan_id,
                "input_snapshot_id": snapshot.snapshot_id,
            },
            handler=record_resumed,
        )
        return {
            **self.require(replan_id),
            "book_state": resumed["state"],
            "replacement_child_candidate": replacement_child,
            "chapter_plan_projection": chapter_plan_projection,
        }

    def reevaluate(self, command: ReevaluateBookReplanCommand) -> dict[str, Any]:
        self.principal.require("book.authority.execute", command.project_id)
        replan = self.require(command.replan_id)
        if replan["project_id"] != command.project_id or replan["status"] != "RESUMED":
            raise KernelError(
                "BOOK_REPLAN_REEVALUATION_NOT_READY",
                "only a resumed Replan in the same Project can be reevaluated",
            )
        book = self.book.require(replan["book_run_id"])
        if str(book["workspace_id"]) != command.workspace_id:
            raise KernelError(
                "BOOK_REPLAN_SCOPE_MISMATCH",
                "Replan reevaluation belongs to another Workspace",
            )
        evidence = self._require_reevaluation_lineage(command, replan)
        remaining = sorted(
            set(evidence["original_issue_types"])
            & set(evidence["observed_issue_types"])
        )
        gate_result = "FAILED" if remaining else "PASSED"
        resolution = "ESCALATED" if remaining else "RESOLVED"
        reevaluation_id = (
            "book-replan-reevaluation:"
            + hashlib.sha256(
                f"{command.project_id}:{command.replan_id}:{command.idempotency_key}".encode()
            ).hexdigest()
        )

        def record_reevaluation(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                INSERT INTO authority_book_replan_reevaluation(
                  reevaluation_id, replan_id, project_id,
                  source_recap_asset_version_id,
                  deviation_report_asset_version_id,
                  evaluation_operation_id, gate_result, resolution,
                  remaining_issue_types, evidence_refs,
                  stable_idempotency_key
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(project_id,replan_id,stable_idempotency_key)
                DO NOTHING
                """,
                [
                    reevaluation_id,
                    command.replan_id,
                    command.project_id,
                    command.source_recap_asset_version_id,
                    command.deviation_report_asset_version_id,
                    operation_id,
                    gate_result,
                    resolution,
                    Jsonb(remaining),
                    Jsonb(
                        [
                            replan["replan_request_asset_version_id"],
                            replan["replacement_candidate_asset_version_id"],
                            command.source_recap_asset_version_id,
                            command.deviation_report_asset_version_id,
                        ]
                    ),
                    command.idempotency_key,
                ],
            )
            self._event(
                uow,
                operation_id=operation_id,
                project_id=command.project_id,
                replan_id=command.replan_id,
                event_type="book.replan.reevaluated",
                correlation_id=command.correlation_id,
                payload={
                    "gate_result": gate_result,
                    "resolution": resolution,
                    "remaining_issue_types": remaining,
                    "source_recap_asset_version_id": (
                        command.source_recap_asset_version_id
                    ),
                },
            )
            checkpoint("after_outbox_insert")
            return {
                "reevaluation_id": reevaluation_id,
                "replan_id": command.replan_id,
                "evaluation_operation_id": operation_id,
                "gate_result": gate_result,
                "resolution": resolution,
                "remaining_issue_types": remaining,
            }

        return self._run_checkpoint(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=replan["book_id"],
            idempotency_key=f"{command.idempotency_key}:record",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_operation_id=evidence["evaluation_source_operation_id"],
            payload={
                "transition": "REEVALUATED",
                "replan_id": command.replan_id,
                "source_recap_asset_version_id": (
                    command.source_recap_asset_version_id
                ),
                "deviation_report_asset_version_id": (
                    command.deviation_report_asset_version_id
                ),
            },
            handler=record_reevaluation,
        )

    def require(self, replan_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT replan_id, project_id, book_id, book_run_id,
                       source_recap_asset_version_id,
                       replan_request_asset_version_id, affected_scope,
                       future_only, target_asset_version_id,
                       replacement_candidate_asset_version_id,
                       generation_operation_id, plan_change_proposal_id,
                       COALESCE(input_snapshot_id,''), status,
                       stable_idempotency_key, version, impact_scope,
                       preserved_invariants, decision_evidence
                FROM authority_book_replan WHERE replan_id=%s
                """,
                [replan_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_REPLAN_NOT_FOUND", "Book Replan does not exist")
        keys = (
            "replan_id",
            "project_id",
            "book_id",
            "book_run_id",
            "source_recap_asset_version_id",
            "replan_request_asset_version_id",
            "affected_scope",
            "future_only",
            "target_asset_version_id",
            "replacement_candidate_asset_version_id",
            "generation_operation_id",
            "plan_change_proposal_id",
            "input_snapshot_id",
            "status",
            "stable_idempotency_key",
            "version",
            "impact_scope",
            "preserved_invariants",
            "decision_evidence",
        )
        return dict(zip(keys, row, strict=True))

    def _require_scope(
        self, book: dict[str, Any], command: CoordinateBookReplanCommand
    ) -> None:
        if (
            book["project_id"] != command.project_id
            or book["workspace_id"] != command.workspace_id
            or book["book_id"] != command.book_id
        ):
            raise KernelError(
                "BOOK_REPLAN_SCOPE_MISMATCH",
                "Book Replan belongs to another Authority scope",
            )
        if book["input_mode"] != "RESOLVED_AUTHORITY_INPUT":
            raise KernelError(
                "BOOK_REPLAN_RESOLVED_INPUT_REQUIRED",
                "Book Replan requires an Authority-resolved input snapshot",
            )

    def _require_recap_lineage(
        self, command: CoordinateBookReplanCommand
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT recap.operation_id, request_version.content
                FROM authority_operation_output_asset AS recap
                JOIN authority_operation_output_asset AS request
                  ON request.operation_id=recap.operation_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=recap.operation_id
                JOIN authority_asset_version AS request_version
                  ON request_version.asset_version_id=request.asset_version_id
                WHERE recap.asset_version_id=%s
                  AND recap.output_key='longform.recap.report'
                  AND request.asset_version_id=%s
                  AND request.output_key='longform.recap.replan_request'
                  AND operation.project_id=%s AND operation.status='SUCCEEDED'
                """,
                [
                    command.source_recap_asset_version_id,
                    command.replan_request_asset_version_id,
                    command.project_id,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_REPLAN_SOURCE_INVALID",
                "ReplanRequest must be emitted by the same successful Longform Recap",
            )
        content = dict(row[1])
        if content.get("contract_version") not in {
            "book-replan-request-v1",
            "book-replan-request-v2",
            "arc-revision-candidate-v1",
        }:
            raise KernelError(
                "BOOK_REPLAN_SOURCE_INVALID",
                "ReplanRequest contract is not supported",
            )
        return {"operation_id": str(row[0]), "replan_request": content}

    def _require_reevaluation_lineage(
        self,
        command: ReevaluateBookReplanCommand,
        replan: dict[str, Any],
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT evaluation.operation_id,
                       source_version.content,
                       evaluation_version.content,
                       request_version.content->'reason_refs',
                       deviation_version.content->'deviations'
                FROM authority_operation_output_asset AS recap
                JOIN authority_operation_output_asset AS deviation
                  ON deviation.operation_id=recap.operation_id
                JOIN authority_operation AS evaluation
                  ON evaluation.operation_id=recap.operation_id
                 AND evaluation.status='SUCCEEDED'
                JOIN authority_asset_version AS deviation_version
                  ON deviation_version.asset_version_id=deviation.asset_version_id
                JOIN authority_asset_version AS evaluation_version
                  ON evaluation_version.asset_version_id=recap.asset_version_id
                JOIN authority_operation_output_asset AS source_recap
                  ON source_recap.asset_version_id=%s
                 AND source_recap.output_key='longform.recap.report'
                JOIN authority_operation AS source
                  ON source.operation_id=source_recap.operation_id
                 AND source.status='SUCCEEDED'
                JOIN authority_asset_version AS source_version
                  ON source_version.asset_version_id=source_recap.asset_version_id
                JOIN authority_asset_version AS request_version
                  ON request_version.asset_version_id=%s
                WHERE recap.asset_version_id=%s
                  AND recap.output_key='longform.recap.report'
                  AND deviation.asset_version_id=%s
                  AND deviation.output_key='longform.recap.deviation_report'
                  AND evaluation.project_id=%s
                """,
                [
                    replan["source_recap_asset_version_id"],
                    replan["replan_request_asset_version_id"],
                    command.source_recap_asset_version_id,
                    command.deviation_report_asset_version_id,
                    command.project_id,
                ],
            )
            row = uow.cursor.fetchone()
        source_content = dict(row[1]) if row is not None else {}
        evaluation_content = dict(row[2]) if row is not None else {}
        source_range = list(source_content.get("chapter_range") or [])
        evaluation_range = list(evaluation_content.get("chapter_range") or [])
        try:
            is_later_position = (
                len(source_range) == 2
                and len(evaluation_range) == 2
                and int(evaluation_range[1]) > int(source_range[1])
            )
        except (TypeError, ValueError):
            is_later_position = False
        if (
            row is None
            or source_content.get("book_id") != replan["book_id"]
            or evaluation_content.get("book_id") != replan["book_id"]
            or not is_later_position
        ):
            raise KernelError(
                "BOOK_REPLAN_REEVALUATION_SOURCE_INVALID",
                "reevaluation requires a later narrative-position Longform Recap and its deviation report",
            )
        return {
            "evaluation_source_operation_id": str(row[0]),
            "original_issue_types": [str(item) for item in (row[3] or [])],
            "observed_issue_types": [
                str(item.get("type") or "") for item in (row[4] or [])
            ],
        }

    def _target_plan(
        self, command: CoordinateBookReplanCommand, next_chapter: int
    ) -> dict[str, Any]:
        parameters: list[Any] = [
            command.project_id,
            command.book_id,
            SCOPE_CONTRACT[command.affected_scope],
        ]
        explicit = ""
        if command.target_asset_version_id:
            explicit = "AND binding.asset_version_id=%s"
            parameters.append(command.target_asset_version_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT binding.asset_version_id, binding.logical_key,
                       COALESCE(binding.parent_version_id,''),
                       binding.execution_scope, version.content
                FROM active_story_plan_version AS active
                JOIN story_plan_binding AS binding ON binding.binding_id=active.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE active.project_id=%s AND active.book_id=%s
                  AND binding.contract_type=%s AND binding.freshness='CURRENT'
                  {explicit}
                ORDER BY active.activated_at DESC
                """,
                parameters,
            )
            rows = uow.cursor.fetchall()
        matches = []
        for row in rows:
            content = dict(row[4])
            if (
                command.affected_scope == "CHAPTER"
                and int(content.get("chapter_number") or 0) < next_chapter
            ):
                continue
            if command.affected_scope == "CHAPTER_GROUP":
                start, end = map(int, content.get("chapter_range") or (0, 0))
                if not start <= next_chapter <= end:
                    continue
            matches.append(row)
        if len(matches) != 1:
            raise KernelError(
                "BOOK_REPLAN_TARGET_AMBIGUOUS",
                "Authority could not resolve one future plan target",
            )
        row = matches[0]
        return {
            "asset_version_id": str(row[0]),
            "logical_key": str(row[1]),
            "parent_version_id": str(row[2]),
            "execution_scope": str(row[3]),
            "content": dict(row[4]),
        }

    def _replacement_inputs(
        self,
        project_id: str,
        *,
        target_asset_version_id: str,
        generator: str,
    ) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT input_snapshot
                FROM authority_story_planning_generation
                WHERE project_id=%s AND candidate_asset_version_id=%s
                """,
                [project_id, target_asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_REPLAN_TARGET_GENERATION_MISSING",
                "target plan lacks a frozen Planning Generation input snapshot",
            )
        expected_roles = set(GENERATOR_INPUT_ROLES[generator])
        result = {
            str(item["role"]): str(item["asset_version_id"])
            for item in row[0]
            if str(item["role"]) in expected_roles
        }
        if set(result) != expected_roles:
            raise KernelError(
                "BOOK_REPLAN_INPUT_ROLE_MISMATCH",
                "target plan input roles differ from replacement Generator",
            )
        related_arcs = tuple(
            str(item["asset_version_id"])
            for item in row[0]
            if str(item["role"]).startswith("related_arc:")
        )
        governance_actions = tuple(
            str(item["asset_version_id"])
            for item in row[0]
            if str(item["role"]).startswith("narrative_governance_action:")
        )
        return result, related_arcs, governance_actions

    def _regenerate_future_plan(
        self, replan: dict[str, Any], proposal: dict[str, Any]
    ) -> str:
        if replan["affected_scope"] == "CHAPTER":
            return ""
        book = self.book.require(replan["book_run_id"])
        snapshot = self._snapshot(book["input_snapshot_id"])
        approved_scope = replan["affected_scope"]
        replacement_id = str(proposal["proposed_asset_version_id"])
        book_plan_id = str(snapshot["book_plan_version"])
        current_volume_before = str(snapshot["current_volume_plan_version"])
        volume_plan_id = current_volume_before
        volume_plan_ids = [
            str(item) for item in snapshot["volume_portfolio_plan_versions"]
        ]
        arc_plan_ids = [str(item) for item in snapshot["arc_portfolio_plan_versions"]]
        group_plan_id = str(snapshot["current_chapter_group_plan_version"])
        volume_replacements = {item: item for item in volume_plan_ids}
        if approved_scope == "BOOK":
            book_plan_id = replacement_id
            for existing_volume_id in volume_plan_ids:
                volume_target = self._plan_by_asset(
                    replan["project_id"], replan["book_id"], existing_volume_id
                )
                volume_replacements[existing_volume_id] = (
                    self._generate_approved_replacement(
                        replan=replan,
                        proposal=proposal,
                        book=book,
                        generator="volume_plan.generate",
                        logical_key=volume_target["logical_key"],
                        parent_version_id=book_plan_id,
                        overrides={"book_plan": book_plan_id},
                        expected_active_asset_version_id=volume_target[
                            "asset_version_id"
                        ],
                    )
                )
            volume_plan_id = volume_replacements[current_volume_before]
        elif approved_scope in {"VOLUME", "NARRATIVE_SEGMENT"}:
            volume_plan_id = replacement_id
            volume_replacements[current_volume_before] = replacement_id

        if approved_scope in {"BOOK", "VOLUME", "NARRATIVE_SEGMENT"}:
            initially_impacted = {
                arc_plan_id
                for arc_plan_id in arc_plan_ids
                if approved_scope == "BOOK"
                or current_volume_before
                in {
                    str(item)
                    for item in self._plan_by_asset(
                        replan["project_id"], replan["book_id"], arc_plan_id
                    )["content"].get("cross_volume_scope")
                    or ()
                }
            }
            ordered_impacted = self._arc_regeneration_order(
                project_id=replan["project_id"],
                book_id=replan["book_id"],
                portfolio_arc_plan_version_ids=tuple(arc_plan_ids),
                initially_impacted_arc_plan_version_ids=initially_impacted,
            )
            arc_replacements: dict[str, str] = {}
            for arc_plan_id in ordered_impacted:
                arc_target = self._plan_by_asset(
                    replan["project_id"], replan["book_id"], arc_plan_id
                )
                old_scope = [
                    str(item)
                    for item in arc_target["content"].get("cross_volume_scope") or ()
                ]
                scoped_volumes = [
                    volume_replacements.get(item, item) for item in old_scope
                ]
                related_versions = tuple(
                    arc_replacements.get(item, item)
                    for item in self._related_arc_versions(
                        project_id=replan["project_id"],
                        book_id=replan["book_id"],
                        dependent_arc_plan_version_id=arc_plan_id,
                    )
                )
                dependent_versions = tuple(
                    arc_replacements.get(item, item)
                    for item in self._dependent_arc_versions(
                        project_id=replan["project_id"],
                        book_id=replan["book_id"],
                        source_arc_plan_version_id=arc_plan_id,
                    )
                )
                primary_volume_id = scoped_volumes[0]
                arc_replacements[arc_plan_id] = self._generate_approved_replacement(
                    replan=replan,
                    proposal=proposal,
                    book=book,
                    generator="arc_plan.generate",
                    logical_key=arc_target["logical_key"],
                    parent_version_id="",
                    overrides={
                        "book_plan": book_plan_id,
                        "volume_plan": primary_volume_id,
                    },
                    expected_active_asset_version_id=arc_target["asset_version_id"],
                    arc_scope_volume_plan_version_ids=tuple(
                        item for item in scoped_volumes if item != primary_volume_id
                    ),
                    related_arc_plan_version_ids=related_versions,
                    dependent_arc_plan_version_ids=dependent_versions,
                )
            arc_plan_ids = [arc_replacements.get(item, item) for item in arc_plan_ids]
        elif approved_scope in {"ARC", "ARC_SEGMENT"}:
            target_arc_id = str(replan["target_asset_version_id"])
            arc_plan_ids = self._replace_portfolio_version(
                arc_plan_ids,
                target_version_id=target_arc_id,
                replacement_version_id=replacement_id,
            )
            arc_replacements = {target_arc_id: replacement_id}
            for related_arc_id in self._transitive_arc_relation_dependents(
                project_id=replan["project_id"],
                book_id=replan["book_id"],
                source_arc_plan_version_id=target_arc_id,
                portfolio_arc_plan_version_ids=tuple(arc_plan_ids),
            ):
                arc_target = self._plan_by_asset(
                    replan["project_id"], replan["book_id"], related_arc_id
                )
                old_scope = tuple(
                    str(item)
                    for item in arc_target["content"].get("cross_volume_scope") or ()
                )
                related_versions = tuple(
                    arc_replacements.get(item, item)
                    for item in self._related_arc_versions(
                        project_id=replan["project_id"],
                        book_id=replan["book_id"],
                        dependent_arc_plan_version_id=related_arc_id,
                    )
                )
                dependent_versions = tuple(
                    arc_replacements.get(item, item)
                    for item in self._dependent_arc_versions(
                        project_id=replan["project_id"],
                        book_id=replan["book_id"],
                        source_arc_plan_version_id=related_arc_id,
                    )
                )
                regenerated = self._generate_approved_replacement(
                    replan=replan,
                    proposal=proposal,
                    book=book,
                    generator="arc_plan.generate",
                    logical_key=arc_target["logical_key"],
                    parent_version_id="",
                    overrides={
                        "book_plan": book_plan_id,
                        "volume_plan": old_scope[0],
                    },
                    expected_active_asset_version_id=related_arc_id,
                    arc_scope_volume_plan_version_ids=old_scope[1:],
                    related_arc_plan_version_ids=related_versions,
                    dependent_arc_plan_version_ids=dependent_versions,
                )
                arc_replacements[related_arc_id] = regenerated
                arc_plan_ids = self._replace_portfolio_version(
                    arc_plan_ids,
                    target_version_id=related_arc_id,
                    replacement_version_id=regenerated,
                )

        if not arc_plan_ids:
            raise KernelError(
                "BOOK_REPLAN_ARC_CLOSURE_MISSING",
                "future Replan regeneration requires at least one active ArcPlan",
            )
        current_relevant_arc_ids = self._project_arc_portfolio_for_volume(
            project_id=replan["project_id"],
            book_id=replan["book_id"],
            arc_plan_ids=arc_plan_ids,
            volume_plan_id=volume_plan_id,
        )

        if approved_scope in {
            "BOOK",
            "VOLUME",
            "NARRATIVE_SEGMENT",
            "ARC",
            "ARC_SEGMENT",
        }:
            group_target = self._plan_by_asset(
                replan["project_id"], replan["book_id"], group_plan_id
            )
            group_plan_id = self._generate_approved_replacement(
                replan=replan,
                proposal=proposal,
                book=book,
                generator="chapter_group_plan.generate",
                logical_key=group_target["logical_key"],
                parent_version_id=volume_plan_id,
                overrides={
                    "book_plan": book_plan_id,
                    "volume_plan": volume_plan_id,
                    "arc_plans": current_relevant_arc_ids[0],
                },
                expected_active_asset_version_id=group_target["asset_version_id"],
                related_arc_plan_version_ids=tuple(current_relevant_arc_ids[1:]),
            )
        elif approved_scope == "CHAPTER_GROUP":
            group_plan_id = replacement_id

        # INVARIANT: replanning replaces future Intent only; a ChapterPlan cannot
        # regenerate before the replacement group freezes a qualified realization
        # against the latest accepted boundary.
        return group_plan_id

    def _transitive_arc_relation_dependents(
        self,
        *,
        project_id: str,
        book_id: str,
        source_arc_plan_version_id: str,
        portfolio_arc_plan_version_ids: tuple[str, ...],
    ) -> tuple[str, ...]:

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                WITH RECURSIVE affected(asset_version_id, depth, path) AS (
                    SELECT edge.dependent_asset_version_id, 1,
                           ARRAY[edge.source_asset_version_id,
                                 edge.dependent_asset_version_id]
                    FROM asset_dependency_edge AS edge
                    WHERE edge.project_id=%s AND edge.book_id=%s
                      AND edge.source_asset_version_id=%s
                      AND edge.dependency_type='ARC_RELATION'
                    UNION ALL
                    SELECT edge.dependent_asset_version_id,
                           affected.depth+1,
                           affected.path || edge.dependent_asset_version_id
                    FROM affected
                    JOIN asset_dependency_edge AS edge
                      ON edge.project_id=%s AND edge.book_id=%s
                     AND edge.source_asset_version_id=affected.asset_version_id
                     AND edge.dependency_type='ARC_RELATION'
                    WHERE NOT edge.dependent_asset_version_id=ANY(affected.path)
                )
                SELECT asset_version_id, MIN(depth)
                FROM affected
                WHERE asset_version_id=ANY(%s)
                  AND asset_version_id<>%s
                GROUP BY asset_version_id
                ORDER BY MIN(depth), asset_version_id
                """,
                [
                    project_id,
                    book_id,
                    source_arc_plan_version_id,
                    project_id,
                    book_id,
                    list(portfolio_arc_plan_version_ids),
                    source_arc_plan_version_id,
                ],
            )
            return tuple(str(row[0]) for row in uow.cursor.fetchall())

    def _arc_regeneration_order(
        self,
        *,
        project_id: str,
        book_id: str,
        portfolio_arc_plan_version_ids: tuple[str, ...],
        initially_impacted_arc_plan_version_ids: set[str],
    ) -> tuple[str, ...]:
        portfolio = tuple(dict.fromkeys(portfolio_arc_plan_version_ids))
        if not initially_impacted_arc_plan_version_ids.issubset(portfolio):
            raise KernelError(
                "BOOK_REPLAN_ARC_PORTFOLIO_STALE",
                "Arc regeneration target is outside the frozen global portfolio",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source_asset_version_id, dependent_asset_version_id
                FROM asset_dependency_edge
                WHERE project_id=%s AND book_id=%s
                  AND dependency_type='ARC_RELATION'
                  AND source_asset_version_id=ANY(%s)
                  AND dependent_asset_version_id=ANY(%s)
                """,
                [project_id, book_id, list(portfolio), list(portfolio)],
            )
            edges = tuple((str(row[0]), str(row[1])) for row in uow.cursor.fetchall())
        impacted = set(initially_impacted_arc_plan_version_ids)
        while True:
            expanded = impacted | {
                dependent for source, dependent in edges if source in impacted
            }
            if expanded == impacted:
                break
            impacted = expanded
        incoming = {
            item: {source for source, dependent in edges if dependent == item}
            for item in impacted
        }
        pending = set(impacted)
        ordered: list[str] = []
        while pending:
            ready = [
                item
                for item in portfolio
                if item in pending and not (incoming[item] & pending)
            ]
            if not ready:
                raise KernelError(
                    "BOOK_REPLAN_ARC_RELATION_CYCLE",
                    "Arc relation closure cannot be regenerated deterministically",
                )
            ordered.extend(ready)
            pending.difference_update(ready)
        return tuple(ordered)

    def _related_arc_versions(
        self,
        *,
        project_id: str,
        book_id: str,
        dependent_arc_plan_version_id: str,
    ) -> tuple[str, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source_asset_version_id
                FROM asset_dependency_edge
                WHERE project_id=%s AND book_id=%s
                  AND dependent_asset_version_id=%s
                  AND dependency_type='ARC_RELATION'
                ORDER BY source_asset_version_id
                """,
                [project_id, book_id, dependent_arc_plan_version_id],
            )
            return tuple(str(row[0]) for row in uow.cursor.fetchall())

    def _dependent_arc_versions(
        self,
        *,
        project_id: str,
        book_id: str,
        source_arc_plan_version_id: str,
    ) -> tuple[str, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT dependent_asset_version_id
                FROM asset_dependency_edge
                WHERE project_id=%s AND book_id=%s
                  AND source_asset_version_id=%s
                  AND dependency_type='ARC_RELATION'
                ORDER BY dependent_asset_version_id
                """,
                [project_id, book_id, source_arc_plan_version_id],
            )
            return tuple(str(row[0]) for row in uow.cursor.fetchall())

    def _generate_approved_replacement(
        self,
        *,
        replan: dict[str, Any],
        proposal: dict[str, Any],
        book: dict[str, Any],
        generator: str,
        logical_key: str,
        parent_version_id: str,
        overrides: dict[str, str],
        expected_active_asset_version_id: str,
        arc_scope_volume_plan_version_ids: tuple[str, ...] = (),
        related_arc_plan_version_ids: tuple[str, ...] = (),
        dependent_arc_plan_version_ids: tuple[str, ...] = (),
    ) -> str:
        inputs = self._latest_generator_inputs(
            book,
            generator=generator,
            overrides=overrides,
        )
        governance_action_version_ids = (
            self._frozen_governance_action_versions(
                project_id=replan["project_id"],
                candidate_asset_version_id=expected_active_asset_version_id,
            )
            if expected_active_asset_version_id
            else ()
        )
        suffix = generator.removesuffix(".generate").replace("_", "-")
        result = self.planning.generate(
            StoryPlanningGenerationCommand(
                project_id=replan["project_id"],
                workspace_id=str(book["workspace_id"]),
                book_id=replan["book_id"],
                actor_id=self.principal.principal_id,
                generator_operation_name=generator,
                logical_key=logical_key,
                input_versions=inputs,
                parent_version_id=parent_version_id,
                arc_scope_volume_plan_version_ids=(arc_scope_volume_plan_version_ids),
                related_arc_plan_version_ids=related_arc_plan_version_ids,
                dependent_arc_plan_version_ids=dependent_arc_plan_version_ids,
                change_evidence_version_ids=(
                    replan["source_recap_asset_version_id"],
                    replan["replan_request_asset_version_id"],
                ),
                governance_action_version_ids=governance_action_version_ids,
                idempotency_key=(
                    f"{replan['stable_idempotency_key']}:regenerate:{suffix}:"
                    f"{logical_key}"
                ),
                trace_id=f"{replan['replan_id']}:regenerate:{suffix}",
                correlation_id=proposal["activation_operation_id"],
                auto_approve_low_risk=False,
            ),
            principal=self.principal,
        )
        if result.status is PlanningGenerationStatus.ACTIVE:
            return result.candidate_asset_version_id
        if result.status is not PlanningGenerationStatus.APPROVAL_PENDING:
            raise KernelError(
                "BOOK_REPLAN_FUTURE_REGENERATION_BLOCKED",
                f"future {generator} did not reach its approval gate",
            )
        self.planning.approve_candidate(
            result.candidate_asset_version_id,
            principal=self.principal,
            idempotency_key=(
                f"{replan['stable_idempotency_key']}:regenerate:{suffix}:approve:"
                f"{result.candidate_asset_version_id}"
            ),
            trace_id=f"{replan['replan_id']}:regenerate:{suffix}:approve",
            correlation_id=proposal["activation_operation_id"],
        )
        self.planning.activate_candidate(
            result.candidate_asset_version_id,
            principal=self.principal,
            idempotency_key=(
                f"{replan['stable_idempotency_key']}:regenerate:{suffix}:activate:"
                f"{result.candidate_asset_version_id}"
            ),
            trace_id=f"{replan['replan_id']}:regenerate:{suffix}:activate",
            correlation_id=proposal["activation_operation_id"],
            expected_active_asset_version_id=expected_active_asset_version_id,
            replacement_approved=bool(expected_active_asset_version_id),
            decision_evidence=(
                {
                    "replan_id": replan["replan_id"],
                    "plan_change_proposal_id": proposal["proposal_id"],
                    "activation_operation_id": proposal["activation_operation_id"],
                    "approved_scope": replan["affected_scope"],
                    "downstream_requalification": True,
                }
                if expected_active_asset_version_id
                else {}
            ),
        )
        return result.candidate_asset_version_id

    def _frozen_governance_action_versions(
        self, *, project_id: str, candidate_asset_version_id: str
    ) -> tuple[str, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT input_snapshot
                FROM authority_story_planning_generation
                WHERE project_id=%s AND candidate_asset_version_id=%s
                """,
                [project_id, candidate_asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_REPLAN_TARGET_GENERATION_MISSING",
                "replacement target lacks immutable generation lineage",
            )
        return tuple(
            str(item["asset_version_id"])
            for item in row[0]
            if str(item["role"]).startswith("narrative_governance_action:")
        )

    def _plan_by_asset(
        self, project_id: str, book_id: str, asset_version_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.logical_key,
                       COALESCE(binding.parent_version_id,''),
                       binding.contract_type, binding.execution_scope,
                       binding.freshness, version.content
                FROM story_plan_binding AS binding
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
                "BOOK_REPLAN_DEPENDENT_PLAN_MISSING",
                "Replan dependency closure references an unknown Planning binding",
            )
        return {
            "asset_version_id": str(row[0]),
            "logical_key": str(row[1]),
            "parent_version_id": str(row[2]),
            "contract_type": str(row[3]),
            "execution_scope": str(row[4]),
            "freshness": str(row[5]),
            "content": dict(row[6]),
        }

    @staticmethod
    def _replace_portfolio_version(
        version_ids: list[str],
        *,
        target_version_id: str,
        replacement_version_id: str,
    ) -> list[str]:
        if version_ids.count(target_version_id) != 1:
            raise KernelError(
                "BOOK_REPLAN_ARC_PORTFOLIO_TARGET_INVALID",
                "Arc Replan target must identify one active Arc in the frozen portfolio",
            )
        return [
            replacement_version_id if item == target_version_id else item
            for item in version_ids
        ]

    @staticmethod
    def _scheduled_arc_versions(
        *,
        group_content: dict[str, Any],
        chapter: int,
        active_arc_plan_ids: list[str],
    ) -> list[str]:
        rows = [
            item
            for item in group_content.get("chapter_function_matrix") or ()
            if isinstance(item, dict)
            and int(item.get("chapter_number") or 0) == chapter
        ]
        if len(rows) != 1:
            raise KernelError(
                "BOOK_REPLAN_SCHEDULE_ROW_INVALID",
                "Replan Scheduling must contain one row for the next Chapter",
            )
        scheduled = [
            str(item.get("arc_plan_version_id") or "")
            for item in rows[0].get("arc_cadence") or ()
            if isinstance(item, dict) and str(item.get("action") or "") != "DORMANT"
        ]
        if (
            not scheduled
            or len(scheduled) > 3
            or len(set(scheduled)) != len(scheduled)
            or not set(scheduled).issubset(active_arc_plan_ids)
        ):
            raise KernelError(
                "BOOK_REPLAN_SCHEDULE_ARC_INVALID",
                "Replanned Chapter Arc context must be a bounded active subset",
            )
        return scheduled

    def _project_arc_portfolio_for_volume(
        self,
        *,
        project_id: str,
        book_id: str,
        arc_plan_ids: list[str],
        volume_plan_id: str,
    ) -> list[str]:
        relevant = [
            arc_plan_id
            for arc_plan_id in arc_plan_ids
            if volume_plan_id
            in {
                str(item)
                for item in self._plan_by_asset(project_id, book_id, arc_plan_id)[
                    "content"
                ].get("cross_volume_scope")
                or ()
            }
        ]
        if not relevant:
            raise KernelError(
                "BOOK_REPLAN_CURRENT_ARC_MISSING",
                "replanned current Volume has no relevant Arc in the global portfolio",
            )
        return relevant

    def _active_plan_for_position(
        self,
        *,
        project_id: str,
        book_id: str,
        contract_type: str,
        chapter: int,
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.logical_key,
                       COALESCE(binding.parent_version_id,''), version.content
                FROM active_story_plan_version AS active
                JOIN story_plan_binding AS binding
                  ON binding.binding_id=active.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE active.project_id=%s AND active.book_id=%s
                  AND binding.contract_type=%s AND binding.freshness='CURRENT'
                ORDER BY active.activated_at DESC
                """,
                [project_id, book_id, contract_type],
            )
            rows = uow.cursor.fetchall()
        matches = [
            row
            for row in rows
            if int(dict(row[3]).get("chapter_number") or 0) == chapter
        ]
        if len(matches) > 1:
            raise KernelError(
                "BOOK_REPLAN_DEPENDENT_PLAN_AMBIGUOUS",
                "more than one current ChapterPlan covers the Replan position",
            )
        if not matches:
            return None
        row = matches[0]
        return {
            "asset_version_id": str(row[0]),
            "logical_key": str(row[1]),
            "parent_version_id": str(row[2]),
            "content": dict(row[3]),
        }

    @staticmethod
    def _require_segment_target(
        *,
        affected_scope: str,
        target_content: dict[str, Any],
        impact_scope: dict[str, Any],
    ) -> None:
        field_and_collection = {
            "NARRATIVE_SEGMENT": ("narrative_segment_id", "narrative_segments"),
            "ARC_SEGMENT": ("arc_segment_id", "arc_segments"),
        }
        if affected_scope not in field_and_collection:
            return
        field, collection = field_and_collection[affected_scope]
        target_id = str(impact_scope.get(field) or "")
        identities = {
            str(item.get("segment_id") or "")
            for item in target_content.get(collection) or ()
            if isinstance(item, dict)
        }
        if not target_id or target_id not in identities:
            raise KernelError(
                "BOOK_REPLAN_SEGMENT_SCOPE_INVALID",
                f"{affected_scope} requires one segment identity inside the target plan",
            )

    def _latest_generator_inputs(
        self,
        book: dict[str, Any],
        *,
        generator: str,
        overrides: dict[str, str],
    ) -> dict[str, str]:
        snapshot = self._snapshot(book["input_snapshot_id"])
        fixed = {
            "book_plan": snapshot["book_plan_version"],
            "volume_plan": snapshot["current_volume_plan_version"],
            "arc_plans": str(snapshot["current_relevant_arc_plan_versions"][0]),
            "character_state": snapshot["character_state_version"],
            "foreshadowing_state": snapshot["foreshadowing_state_version"],
            "reward_ledger": snapshot["reward_ledger_version"],
            "promise_ledger": snapshot["promise_ledger_version"],
            "quality_trend": snapshot["quality_trend_version"],
            "story_state": book.get("active_story_state_version_id") or snapshot.get("initial_story_state_version"),
            "canon_snapshot": book.get("active_canon_snapshot_version_id") or snapshot.get("initial_canon_snapshot_version"),
            "previous_chapter_outcome": book.get("last_chapter_outcome_version_id"),
            **overrides,
        }
        from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
        observed_reader = PostgresBookProductionQuery(self.database_url).previous_reader_state(
            book_run_id=str(book["book_run_id"]), chapter_number=int(book["accepted_through_chapter"]) + 1)
        if observed_reader != "NONE":
            fixed["reader_state"] = observed_reader
        aliases = {
            "previous_chapter_outcome": (
                "previous_chapter_outcome",
                "chapter_outcome",
            ),
            "story_state": ("story_state_snapshot", "story_state"),
            "canon_snapshot": ("canon_snapshot",),
            "reader_state": ("reader_state",),
        }
        result: dict[str, str] = {}
        for role in GENERATOR_INPUT_ROLES[generator]:
            version = fixed.get(role) or self._latest_active_asset(
                book["project_id"], book["book_id"], aliases.get(role, (role,))
            )
            if not version:
                raise KernelError(
                    "BOOK_REPLAN_REGENERATION_INPUT_MISSING",
                    f"missing future Planning input {role}",
                )
            result[role] = version
        return result

    def resume_operator_plan_change(self, *, book_run_id: str, proposal_id: str, principal: Principal) -> dict[str, Any]:
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

        book = self.book.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        proposal = self.plan_change.require(proposal_id)
        if (proposal["project_id"], proposal["book_id"], proposal["status"], proposal["source_type"]) != (book["project_id"], book["book_id"], "ACTIVE", "HUMAN_FEEDBACK"):
            raise KernelError("BOOK_OPERATOR_PLAN_CHANGE_INVALID", "resume requires an active operator PlanChange for this Book")
        query = AuthorityAssetQuery(self.database_url)
        source = query.require(project_id=book["project_id"], asset_version_id=proposal["source_evidence_version_id"])
        replacement = query.require(project_id=book["project_id"], asset_version_id=proposal["proposed_asset_version_id"])
        boundary = source.content.get("accepted_through_chapter")
        chapter_range = replacement.content.get("chapter_range")
        if (
            source.content.get("contract_version") != "operator-planning-change-request.v1"
            or source.content.get("book_id") != book["book_id"]
            or source.content.get("target_plan_version_id") != proposal["target_asset_version_id"]
            or not isinstance(boundary, int) or isinstance(boundary, bool)
            or proposal["target_contract_type"] != "CHAPTER_GROUP"
            or not isinstance(chapter_range, list) or len(chapter_range) != 2
            or not all(isinstance(value, int) and not isinstance(value, bool) for value in chapter_range)
            or chapter_range[0] <= boundary or chapter_range[1] < chapter_range[0]
        ):
            raise KernelError("BOOK_OPERATOR_PLAN_CHANGE_SCOPE_INVALID", "bounded operator resume requires a wholly future ChapterGroup and its original accepted boundary")
        causation = proposal["activation_operation_id"]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.snapshot_id, operation.status,
                       (operation.command_payload #>> '{input,expected_version}')::bigint
                FROM authority_book_production_input_binding binding
                JOIN authority_operation operation ON operation.operation_id=binding.bound_by_operation_id
                WHERE binding.book_run_id=%s AND operation.causation_operation_id=%s
                ORDER BY binding.binding_version DESC LIMIT 1
                """, [book_run_id, causation],
            )
            applied = uow.cursor.fetchone()
        if applied is not None and applied[1] != "SUCCEEDED":
            raise KernelError("BOOK_OPERATOR_PLAN_CHANGE_RECONCILE_REQUIRED", "input binding exists without a confirmed successful owning Operation")
        receipt = {"proposal_id": proposal_id, "book_run_id": book_run_id,
                   "source_evidence_version_id": source.asset_version_id,
                   "proposed_asset_version_id": replacement.asset_version_id,
                   "accepted_through_chapter": boundary}
        if applied is not None:
            if (
                int(book["accepted_through_chapter"]) == boundary and book["state"] == "PAUSED"
                and book.get("input_snapshot_id") == applied[0]
                and applied[2] is not None and int(book["version"]) == int(applied[2]) + 1
            ):
                book = self.book.resume(book_run_id, reason=f"PlanChange {proposal_id} applied", principal=principal, expected_version=int(book["version"]))
            return {**receipt, "snapshot_id": str(applied[0]), "state": book["state"], "replayed": True}
        if book["state"] != "PAUSED" or int(book["accepted_through_chapter"]) != boundary:
            raise KernelError("BOOK_OPERATOR_PLAN_CHANGE_CHECKPOINT_REQUIRED", "pause exactly at the change request's accepted boundary before rebinding")
        if book.get("active_chapter_request_id"):
            request = self.book.require_chapter_request(str(book["active_chapter_request_id"]))
            if int(request["chapter_number"]) > boundary:
                raise KernelError("BOOK_OPERATOR_PLAN_CHANGE_INFLIGHT", "finish or recover the dispatched Chapter before changing its inputs")
        snapshot = self._resolve_new_snapshot(book, causation, principal=principal)
        bound = self.book.bind_replanned_input_snapshot(
            book_run_id, snapshot_id=snapshot.snapshot_id, causation_operation_id=causation,
            target_state=BookProductionState.PAUSED, expected_version=int(book["version"]), principal=principal,
        )
        resumed = self.book.resume(book_run_id, reason=f"PlanChange {proposal_id} applied", principal=principal, expected_version=int(bound["version"]))
        return {**receipt, "snapshot_id": snapshot.snapshot_id, "state": resumed["state"], "replayed": False}

    def _resolve_new_snapshot(self, book: dict[str, Any], causation: str, *, principal: Principal | None = None):
        principal = principal or self.principal
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version FROM authority_book
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                """,
                [book["project_id"], book["workspace_id"], book["book_id"]],
            )
            row = uow.cursor.fetchone()
        return self.input_resolver.resolve(
            ResolveBookProductionInputCommand(
                project_id=book["project_id"],
                workspace_id=book["workspace_id"],
                book_id=book["book_id"],
                production_profile=str(book["production_profile_version"]),
                expected_book_version=int(row[0]),
                narrative_chapter_cursor=max(
                    1, int(book.get("accepted_through_chapter") or 0) + 1
                ),
                actor_id=principal.principal_id,
                idempotency_key=f"{book['stable_idempotency_key']}:replan-input:{causation}",
                trace_id=f"{causation}:book-input",
                correlation_id=causation,
                role_asset_version_overrides=self._new_snapshot_role_overrides(book),
            ),
            principal=principal,
        )

    def _new_snapshot_role_overrides(
        self, book: dict[str, Any]
    ) -> tuple[tuple[str, str], ...]:
        previous = self._snapshot(book["input_snapshot_id"])
        overrides = {role: str(previous[role]) for role in _SNAPSHOT_ROLE_FIELDS}
        return tuple(sorted(overrides.items()))

    def _snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return asdict(self.input_resolver.require(snapshot_id))

    def _latest_active_asset(
        self, project_id: str, book_id: str, asset_types: tuple[str, ...]
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id=asset.asset_id
                WHERE asset.project_id=%s AND asset.asset_type=ANY(%s)
                  AND version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                  AND COALESCE(version.content->>'book_id',%s)=%s
                ORDER BY version.created_at DESC, version.version_number DESC
                LIMIT 1
                """,
                [project_id, list(asset_types), book_id, book_id],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row else ""


def _replan_checkpoint_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": "book.replan.checkpoint.record",
        "definition_version": "1.0.0",
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "book.replan.checkpoint.command.v1",
        "result_schema_version": "book.replan.checkpoint.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "BookReplanCheckpointFact"},
        "handler_key": "novel_forge.book.replan.checkpoint.record",
        "handler_contract_version": "book-replan-checkpoint-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "plan_change_authority_required": True,
            "future_only": True,
        },
        "idempotency_scope": "book:replan-checkpoint",
        "concurrency_key_template": "book:{book_id}:replan-checkpoint",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only PlanChange-backed checkpoint",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "completion_contract": {
            "version": "book-replan-checkpoint-completion-v1",
            "required_evidence": ["trace", "audit", "plan_change_decision"],
        },
    }


__all__ = ["BookReplanCoordinator", "CoordinateBookReplanCommand"]
