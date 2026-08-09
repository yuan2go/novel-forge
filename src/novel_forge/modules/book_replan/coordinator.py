"""Recap -> replacement Candidate -> PlanChange -> regeneration -> Book resume."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import uuid4

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
    PlanningGenerationStatus,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


SCOPE_GENERATOR = {
    "BOOK": "book_plan.generate",
    "VOLUME": "volume_plan.generate",
    "ARC": "arc_plan.generate",
    "CHAPTER_GROUP": "chapter_group_plan.generate",
    "CHAPTER": "chapter_plan.generate",
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

_CANON_OUTPUT_ROLE_TYPES = {
    "character_state_snapshot": "character_state_version",
    "foreshadow_snapshot": "foreshadowing_state_version",
    "reward_ledger_snapshot": "reward_ledger_version",
    "promise_ledger_snapshot": "promise_ledger_version",
}


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
    auto_approve_low_risk: bool = False

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


class BookReplanCoordinator:
    """Coordinates Authorities; it owns no Attempt, Lease, Fence, or Provider."""

    def __init__(
        self,
        database_url: str,
        *,
        book_authority: PostgresBookAuthority,
        planning: StoryPlanningGenerationApplication,
        plan_change: PostgresPlanChangeAuthority,
        input_resolver: BookProductionInputResolver,
        principal: Principal,
    ) -> None:
        if not database_url:
            raise ValueError("Book Replan requires PostgreSQL")
        self.database_url = database_url
        self.book = book_authority
        self.planning = planning
        self.plan_change = plan_change
        self.input_resolver = input_resolver
        self.principal = principal

    def start(self, command: CoordinateBookReplanCommand) -> dict[str, Any]:
        self.principal.require("book.authority.execute", command.project_id)
        existing = self._find_by_idempotency(
            command.project_id, command.idempotency_key
        )
        if existing is not None:
            return existing
        book = self.book.require(command.book_run_id)
        self._require_scope(book, command)
        recap_operation_id = self._require_recap_lineage(command)
        target = self._target_plan(command, int(book["accepted_through_chapter"]) + 1)
        if target["execution_scope"] == "EXECUTED":
            raise KernelError(
                "BOOK_REPLAN_EXECUTED_PLAN_FORBIDDEN",
                "ordinary Replan cannot modify an Executed plan",
            )
        generator = SCOPE_GENERATOR[command.affected_scope]
        inputs = self._replacement_inputs(
            command.project_id,
            target_asset_version_id=target["asset_version_id"],
            generator=generator,
        )
        generated = self.planning.generate(
            StoryPlanningGenerationCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=self.principal.principal_id,
                generator_operation_name=generator,
                logical_key=target["logical_key"],
                input_versions=inputs,
                parent_version_id=target["parent_version_id"],
                idempotency_key=f"{command.idempotency_key}:replacement-candidate",
                trace_id=command.trace_id,
                correlation_id=recap_operation_id,
                auto_approve_low_risk=False,
            ),
            principal=self.principal,
        )
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
                source_type=PlanChangeSource.LONGFORM_RECAP,
                source_evidence_version_id=command.replan_request_asset_version_id,
                target_asset_version_id=target["asset_version_id"],
                proposed_asset_version_id=generated.candidate_asset_version_id,
            ),
            principal=self.principal,
        )
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
                    created_by_operation_id
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,%s,%s,%s,
                    'APPROVAL_PENDING',%s,%s
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
        if command.auto_approve_low_risk and proposal["risk"] == "LOW":
            self.approve(
                replan_id,
                authority_type="PLAN_CHANGE_AUTHORITY",
                authority_version="plan-change-low-risk-policy-v1",
                evidence={"explicit_low_risk_auto_approval_policy": True},
            )
            return self.activate(replan_id)
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
                "plan_change_decision_operation_id": proposal["approval_operation_id"],
            },
            handler=record_approval,
        )
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

        self._run_checkpoint(
            project_id=replan["project_id"],
            workspace_id=str(book["workspace_id"]),
            book_id=replan["book_id"],
            idempotency_key=f"{replan['stable_idempotency_key']}:regenerating-record",
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
                       stable_idempotency_key, version
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

    def _require_recap_lineage(self, command: CoordinateBookReplanCommand) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT recap.operation_id
                FROM authority_operation_output_asset AS recap
                JOIN authority_operation_output_asset AS request
                  ON request.operation_id=recap.operation_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=recap.operation_id
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
        return str(row[0])

    def _target_plan(
        self, command: CoordinateBookReplanCommand, next_chapter: int
    ) -> dict[str, Any]:
        parameters: list[Any] = [
            command.project_id,
            command.book_id,
            command.affected_scope,
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
    ) -> dict[str, str]:
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
        result = {str(item["role"]): str(item["asset_version_id"]) for item in row[0]}
        if set(result) != set(GENERATOR_INPUT_ROLES[generator]):
            raise KernelError(
                "BOOK_REPLAN_INPUT_ROLE_MISMATCH",
                "target plan input roles differ from replacement Generator",
            )
        return result

    def _regenerate_future_plan(
        self, replan: dict[str, Any], proposal: dict[str, Any]
    ) -> str:
        if replan["affected_scope"] != "CHAPTER_GROUP":
            return ""
        book = self.book.require(replan["book_run_id"])
        chapter = int(book["accepted_through_chapter"]) + 1
        inputs = self._latest_generator_inputs(
            book,
            generator="chapter_plan.generate",
            overrides={
                "chapter_group_plan": proposal["proposed_asset_version_id"],
                "chapter_function_matrix_row": proposal["proposed_asset_version_id"],
            },
        )
        result = self.planning.generate(
            StoryPlanningGenerationCommand(
                project_id=replan["project_id"],
                workspace_id=str(book["workspace_id"]),
                book_id=replan["book_id"],
                actor_id=self.principal.principal_id,
                generator_operation_name="chapter_plan.generate",
                logical_key=f"chapter:{chapter}:after:{replan['replan_id']}",
                input_versions=inputs,
                parent_version_id=proposal["proposed_asset_version_id"],
                idempotency_key=f"{replan['stable_idempotency_key']}:regenerate:chapter:{chapter}",
                trace_id=f"{replan['replan_id']}:regenerate",
                correlation_id=proposal["activation_operation_id"],
                auto_approve_low_risk=True,
            ),
            principal=self.principal,
        )
        if result.status is not PlanningGenerationStatus.ACTIVE:
            raise KernelError(
                "BOOK_REPLAN_FUTURE_REGENERATION_BLOCKED",
                "future ChapterPlan did not reach Active state",
            )
        return result.candidate_asset_version_id

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
            "arc_plans": str(snapshot["active_arc_plan_versions"][0]),
            "character_state": snapshot["character_state_version"],
            "foreshadowing_state": snapshot["foreshadowing_state_version"],
            "reward_ledger": snapshot["reward_ledger_version"],
            "promise_ledger": snapshot["promise_ledger_version"],
            "quality_trend": snapshot["quality_trend_version"],
            **overrides,
        }
        aliases = {
            "previous_chapter_outcome": (
                "previous_chapter_outcome",
                "chapter_outcome",
            ),
            "story_state": ("story_state_snapshot", "story_state"),
            "canon_snapshot": ("canon_snapshot",),
            "reader_state": ("reader_state", "reader_state_transition"),
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

    def _resolve_new_snapshot(self, book: dict[str, Any], causation: str):
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
                actor_id=self.principal.principal_id,
                idempotency_key=f"{book['stable_idempotency_key']}:replan-input:{causation}",
                trace_id=f"{causation}:book-input",
                correlation_id=causation,
                role_asset_version_overrides=self._new_snapshot_role_overrides(book),
            ),
            principal=self.principal,
        )

    def _new_snapshot_role_overrides(
        self, book: dict[str, Any]
    ) -> tuple[tuple[str, str], ...]:
        previous = self._snapshot(book["input_snapshot_id"])
        overrides = {role: str(previous[role]) for role in _SNAPSHOT_ROLE_FIELDS}
        active_canon = str(book.get("active_canon_snapshot_version_id") or "")
        if not active_canon:
            return tuple(sorted(overrides.items()))
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id
                FROM authority_operation_output_asset
                WHERE asset_version_id=%s
                """,
                [active_canon],
            )
            anchor_rows = uow.cursor.fetchall()
            if len(anchor_rows) != 1:
                raise KernelError(
                    "BOOK_REPLAN_ACTIVE_CANON_OUTPUT_AMBIGUOUS",
                    "active Canon snapshot must identify one Authority commit",
                )
            uow.cursor.execute(
                """
                SELECT asset.asset_type, output.asset_version_id
                FROM authority_operation_output_asset AS output
                JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
                WHERE output.operation_id=%s
                  AND output.role='state_snapshot'
                  AND asset.asset_type=ANY(%s)
                """,
                [str(anchor_rows[0][0]), list(_CANON_OUTPUT_ROLE_TYPES)],
            )
            rows = uow.cursor.fetchall()
        resolved: dict[str, str] = {}
        for asset_type, version_id in rows:
            role = _CANON_OUTPUT_ROLE_TYPES[str(asset_type)]
            if role in resolved:
                raise KernelError(
                    "BOOK_REPLAN_CANON_ROLE_INPUT_AMBIGUOUS",
                    f"active Canon commit has multiple outputs for {role}",
                )
            resolved[role] = str(version_id)
        missing = set(_CANON_OUTPUT_ROLE_TYPES.values()) - set(resolved)
        if missing:
            raise KernelError(
                "BOOK_REPLAN_CANON_ROLE_INPUT_MISSING",
                "active Canon commit lacks required Book input roles: "
                + ", ".join(sorted(missing)),
            )
        overrides.update(resolved)
        return tuple(sorted(overrides.items()))

    def _snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.input_resolver.require(snapshot_id).to_dict()
        return snapshot

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
