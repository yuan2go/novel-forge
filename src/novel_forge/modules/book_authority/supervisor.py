"""Deterministic Book Production Supervisor over existing Domain Authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_production import (
    PostgresBookNarrativeCheckpointAuthority,
    SupervisorAction,
)
from novel_forge.modules.chapter_group_authority import (
    ChapterGroupState,
    PostgresChapterGroupAuthority,
    StartChapterGroupCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
)
from novel_forge.modules.production_preparation import (
    ProductionPreparationRequest,
    ProductionPreparationService,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationStatus,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from .governed_scheduler import PostgresBookAuthorityScheduler
from .production import (
    BookProductionState,
    PostgresBookAuthority,
    SubmitBookChapterCommand,
)
from .queries import PostgresBookProductionQuery


@dataclass(frozen=True, slots=True)
class BookProductionSupervisorTick:
    book_run_id: str
    previous_state: str
    state: str
    action: SupervisorAction
    operation_id: str = ""
    evidence_ref: str = ""


class PostgresBookProductionSupervisor:
    """Chooses one business action per Tick; it owns no child Attempt or Provider."""

    def __init__(
        self,
        authority: PostgresBookAuthority,
        *,
        planning: StoryPlanningGenerationApplication,
        chapter_groups: PostgresChapterGroupAuthority,
        query: PostgresBookProductionQuery,
        principal: Principal,
        replan: Any,
        production_preparation: ProductionPreparationService,
        context_token_budget: int = 16_000,
        quality_context_token_budget: int | None = None,
    ) -> None:
        if context_token_budget <= 0:
            raise ValueError("context_token_budget must be positive")
        if (
            quality_context_token_budget is not None
            and quality_context_token_budget <= 0
        ):
            raise ValueError("quality_context_token_budget must be positive")
        self.authority = authority
        self.planning = planning
        self.chapter_groups = chapter_groups
        self.query = query
        self.principal = principal
        self.replan = replan
        self.context_token_budget = context_token_budget
        self.quality_context_token_budget = (
            quality_context_token_budget or context_token_budget
        )
        self.production_preparation = production_preparation
        self.scheduler = PostgresBookAuthorityScheduler(
            authority, query=query, principal=principal
        )
        self.checkpoints = PostgresBookNarrativeCheckpointAuthority(
            authority.database_url,
            application_build_id=authority.application_build_id,
            commit_sha=authority.commit_sha,
        )

    def tick(self, book_run_id: str) -> BookProductionSupervisorTick:
        book = self.authority.require(book_run_id)
        before = str(book["state"])
        if book["input_mode"] != "RESOLVED_AUTHORITY_INPUT":
            raise KernelError(
                "BOOK_SUPERVISOR_RESOLVED_INPUT_REQUIRED",
                "autonomous supervision cannot run in Legacy fixture input mode",
            )
        if before in {
            BookProductionState.PAUSED.value,
            BookProductionState.ABORTED.value,
        }:
            return self._result(book_run_id, before, SupervisorAction.NO_ACTION)
        if before == BookProductionState.REPLAN_APPROVAL_PENDING.value:
            replan = self._latest_replan(book_run_id)
            return self._result(
                book_run_id,
                before,
                SupervisorAction.WAIT_REPLAN_APPROVAL,
                evidence_ref=str(replan["replan_id"]),
            )
        if before == BookProductionState.READY.value:
            replan = self.replan.latest_for_book(book_run_id)
            if replan is not None and replan["status"] == "REGENERATING":
                activated = self.replan.activate(str(replan["replan_id"]))
                return self._result(
                    book_run_id,
                    before,
                    SupervisorAction.ACTIVATE_REPLAN,
                    evidence_ref=str(activated["replan_id"]),
                )
        if before == BookProductionState.REPLAN_GENERATING.value:
            replan = self._latest_replan(book_run_id)
            if replan["affected_scope"] == "CHAPTER_GROUP":
                active_group = self._active_group_run(book)
                if active_group is not None:
                    self.chapter_groups.supersede_for_approved_replan(
                        str(active_group["group_run_id"]),
                        replan_id=str(replan["replan_id"]),
                        target_group_plan_version_id=str(
                            replan["target_asset_version_id"]
                        ),
                        principal=self.principal,
                    )
            activated = self.replan.activate(str(replan["replan_id"]))
            return self._result(
                book_run_id,
                before,
                SupervisorAction.ACTIVATE_REPLAN,
                evidence_ref=str(activated["replan_id"]),
            )
        if before in {
            BookProductionState.CHAPTER_SUBMITTED.value,
            BookProductionState.CHAPTER_RUNNING.value,
            BookProductionState.CHAPTER_WAITING_RETRY.value,
            BookProductionState.CHAPTER_COMPLETED.value,
            BookProductionState.READER_OUTCOME_PENDING.value,
            BookProductionState.FOLLOWUP_PENDING.value,
            BookProductionState.CHECKPOINT_PENDING.value,
        }:
            group_run = self._active_group_run(book)
            if group_run is not None and before in {
                BookProductionState.CHAPTER_SUBMITTED.value,
                BookProductionState.CHAPTER_RUNNING.value,
                BookProductionState.CHAPTER_WAITING_RETRY.value,
                BookProductionState.CHAPTER_COMPLETED.value,
            }:
                reconciled = self.chapter_groups.reconcile_and_accept(
                    str(group_run["group_run_id"]), principal=self.principal
                )
                action = (
                    SupervisorAction.ACCEPT_CHAPTER
                    if int(reconciled["accepted_through_chapter"])
                    > int(group_run["accepted_through_chapter"])
                    else SupervisorAction.RECONCILE_CHAPTER
                )
                return self._result(book_run_id, before, action)
            tick = self.scheduler.tick(book_run_id)
            action = self._scheduler_action(tick.action)
            return self._result(book_run_id, before, action, tick.operation_id)
        if (
            before
            in {
                BookProductionState.READY.value,
                BookProductionState.COMPLETED.value,
            }
            and int(book["accepted_through_chapter"]) > 0
        ):
            checkpoint = self._checkpoint_if_needed(book)
            if checkpoint is not None:
                return self._result(
                    book_run_id,
                    before,
                    SupervisorAction.UPDATE_CHECKPOINTS,
                    evidence_ref=checkpoint["volume_checkpoint"]["checkpoint_id"],
                )
            sidecar = self.scheduler.tick(book_run_id)
            action = self._scheduler_action(sidecar.action)
            if action is not SupervisorAction.NO_ACTION:
                return self._result(book_run_id, before, action, sidecar.operation_id)
            replan_report_id = self.query.checkpoint_replan_report_id(
                book_run_id=str(book["book_run_id"]),
                accepted_through_chapter=int(book["accepted_through_chapter"]),
            )
            if replan_report_id:
                # A checkpoint finding becomes executable only after the
                # governed Recap has emitted its Replan Request.
                self.query.require_replan_source(book_run_id=str(book["book_run_id"]))
                self.authority.advance_supervisor_checkpoint(
                    str(book["book_run_id"]),
                    expected_version=int(book["version"]),
                    expected_state=str(book["state"]),
                    target_state=BookProductionState.REPLAN_REQUIRED,
                    principal=self.principal,
                )
                return self._result(
                    book_run_id,
                    before,
                    SupervisorAction.UPDATE_CHECKPOINTS,
                    evidence_ref=replan_report_id,
                )
        if before == BookProductionState.REPLAN_REQUIRED.value:
            return self._start_replan(book)
        next_chapter = int(book["accepted_through_chapter"]) + 1
        group_run = self._active_group_run(book)
        if (
            group_run is not None
            and group_run["state"] == ChapterGroupState.CLOSURE_PENDING.value
        ):
            closed = self.chapter_groups.close(
                str(group_run["group_run_id"]), principal=self.principal
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.CLOSE_CHAPTER_GROUP,
                str(closed.get("root_operation_id") or ""),
                str(closed["group_run_id"]),
            )
        if before == BookProductionState.COMPLETED.value:
            return self._result(book_run_id, before, SupervisorAction.NO_ACTION)
        if next_chapter > int(book["target_chapter_count"]):
            self.authority.advance_supervisor_checkpoint(
                str(book["book_run_id"]),
                expected_version=int(book["version"]),
                expected_state=str(book["state"]),
                target_state=BookProductionState.COMPLETED,
                principal=self.principal,
            )
            return self._result(book_run_id, before, SupervisorAction.COMPLETE)
        group = self._active_plan(book, "CHAPTER_GROUP", next_chapter)
        if group is None:
            result = self._generate_plan(
                book, "chapter_group_plan.generate", next_chapter
            )
            target = (
                BookProductionState.CHAPTER_PLAN_REQUIRED
                if result.status is PlanningGenerationStatus.ACTIVE
                else BookProductionState.PLAN_APPROVAL_PENDING
            )
            self.authority.advance_supervisor_checkpoint(
                str(book["book_run_id"]),
                expected_version=int(book["version"]),
                expected_state=str(book["state"]),
                target_state=target,
                principal=self.principal,
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.GENERATE_CHAPTER_GROUP,
                result.generation_operation_id,
                result.candidate_asset_version_id,
            )
        if group["execution_scope"] == PlanExecutionScope.PLANNED.value:
            operation_id = self._freeze_plan(
                book, group, PlanContractType.CHAPTER_GROUP
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.FREEZE_CHAPTER_GROUP_PLAN,
                operation_id,
                str(group["asset_version_id"]),
            )
        if group["execution_scope"] != PlanExecutionScope.FROZEN.value:
            raise KernelError(
                "BOOK_SUPERVISOR_GROUP_PLAN_NOT_EXECUTABLE",
                "ChapterGroupPlan must be Frozen before group production starts",
            )
        group_run = self._active_group_run(book, str(group["asset_version_id"]))
        if group_run is None:
            started = self.chapter_groups.start(
                StartChapterGroupCommand(
                    project_id=str(book["project_id"]),
                    workspace_id=str(book["workspace_id"]),
                    actor_id=self.principal.principal_id,
                    trace_id=f"{book['root_operation_id']}:chapter-group:start",
                    correlation_id=str(book["root_operation_id"]),
                    stable_idempotency_key=(
                        f"{book['stable_idempotency_key']}:chapter-group:"
                        f"{group['asset_version_id']}"
                    ),
                    book_run_id=book_run_id,
                    group_plan_version_id=str(group["asset_version_id"]),
                    group_plan_content_hash=str(group["content_hash"]),
                ),
                principal=self.principal,
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.START_CHAPTER_GROUP,
                str(started["root_operation_id"]),
                str(started["group_run_id"]),
            )
        chapter_plan = self._active_plan(book, "CHAPTER", next_chapter)
        if chapter_plan is None:
            result = self._generate_plan(book, "chapter_plan.generate", next_chapter)
            target = (
                BookProductionState.READY
                if result.status is PlanningGenerationStatus.ACTIVE
                else BookProductionState.PLAN_APPROVAL_PENDING
            )
            self.authority.advance_supervisor_checkpoint(
                str(book["book_run_id"]),
                expected_version=int(book["version"]),
                expected_state=str(book["state"]),
                target_state=target,
                principal=self.principal,
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.GENERATE_CHAPTER_PLAN,
                result.generation_operation_id,
                result.candidate_asset_version_id,
            )
        if chapter_plan["execution_scope"] == PlanExecutionScope.PLANNED.value:
            operation_id = self._freeze_plan(
                book, chapter_plan, PlanContractType.CHAPTER
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.FREEZE_CHAPTER_PLAN,
                operation_id,
                str(chapter_plan["asset_version_id"]),
            )
        if chapter_plan["execution_scope"] != PlanExecutionScope.FROZEN.value:
            raise KernelError(
                "BOOK_SUPERVISOR_CHAPTER_PLAN_NOT_EXECUTABLE",
                "ChapterPlan must be Frozen before Chapter dispatch",
            )
        execution_plan = self.query.require_chapter_execution_plan(
            str(chapter_plan["asset_version_id"])
        )
        explicit_overrides: dict[str, str | list[str]] = {
            "chapter_plan": str(execution_plan["asset_version_id"])
        }
        if next_chapter > 1:
            previous_story_state = str(book.get("active_story_state_version_id") or "")
            previous_canon = str(book.get("active_canon_snapshot_version_id") or "")
            if not previous_story_state or not previous_canon:
                raise KernelError(
                    "BOOK_SUPERVISOR_PREVIOUS_ACCEPTANCE_STATE_MISSING",
                    "continuing Chapter preparation requires accepted Story State and Canon",
                )
            explicit_overrides.update(
                {
                    "story_state_snapshot": previous_story_state,
                    "canon_snapshot": previous_canon,
                }
            )
        else:
            snapshot = self.query.require_input_snapshot(str(book["input_snapshot_id"]))
            initial_story_state = str(
                snapshot.get("initial_story_state_version") or ""
            )
            initial_canon = str(
                snapshot.get("initial_canon_snapshot_version") or ""
            )
            if bool(initial_story_state) != bool(initial_canon):
                raise KernelError(
                    "BOOK_INITIAL_NARRATIVE_STATE_INCOMPLETE",
                    "initial Story State and Canon must be prepared together",
                )
            if initial_story_state:
                explicit_overrides.update(
                    {
                        "story_state_snapshot": initial_story_state,
                        "canon_snapshot": initial_canon,
                    }
                )
        preparation = self.production_preparation.prepare(
            self._chapter_preparation_request(
                book=book,
                next_chapter=next_chapter,
                explicit_overrides=explicit_overrides,
            )
        )
        prepared = preparation.command
        if prepared is None:
            raise KernelError(
                "BOOK_SUPERVISOR_CHAPTER_PREPARATION_BLOCKED",
                str(
                    {
                        "missing": preparation.report.missing_required_asset_types,
                        "blocked": preparation.report.blocked_assets,
                        "repair_actions": preparation.report.repair_actions,
                    }
                ),
            )
        context_version_refs = {
            **self._context_version_refs(book, group),
            **dict(prepared.context_version_refs),
        }
        preparation_report = self._stage_budgeted_preparation_report(prepared)
        dispatched_group = self.chapter_groups.dispatch(
            str(group_run["group_run_id"]),
            SubmitBookChapterCommand(
                book_run_id=book_run_id,
                chapter_number=next_chapter,
                title=prepared.title,
                premise=prepared.premise,
                chapter_plan_asset_version_id=str(chapter_plan["asset_version_id"]),
                chapter_plan_content_hash=str(chapter_plan["content_hash"]),
                context_candidates=prepared.context_candidates,
                execution_chapter_plan_asset_version_id=str(
                    execution_plan["asset_version_id"]
                ),
                execution_chapter_plan_content_hash=str(execution_plan["content_hash"]),
                parent_group_version_id=str(group["asset_version_id"]),
                context_version_refs=context_version_refs,
                context_token_budget=prepared.context_token_budget,
                preparation_report=preparation_report,
            ),
            principal=self.principal,
        )
        dispatched = self.authority.require_chapter_request(
            str(dispatched_group["active_chapter_request_id"])
        )
        return self._result(
            book_run_id,
            before,
            SupervisorAction.DISPATCH_CHAPTER,
            str(dispatched.get("chapter_root_operation_id") or ""),
            str(dispatched["chapter_request_id"]),
        )

    def _chapter_preparation_request(
        self,
        *,
        book: dict[str, Any],
        next_chapter: int,
        explicit_overrides: dict[str, str | list[str]],
    ) -> ProductionPreparationRequest:
        return ProductionPreparationRequest(
            project_id=str(book["project_id"]),
            workspace_id=str(book["workspace_id"]),
            book_id=str(book["book_id"]),
            chapter=next_chapter,
            idempotency_key=(
                f"{book['stable_idempotency_key']}:chapter:{next_chapter}"
            ),
            explicit_asset_version_overrides=explicit_overrides,
            context_token_budget=self.context_token_budget,
        )

    def _stage_budgeted_preparation_report(self, prepared: Any) -> dict[str, Any]:
        report = dict(prepared.preparation_report)
        stage_budgets = dict(report.get("stage_context_token_budgets") or {})
        report["stage_context_token_budgets"] = {
            **stage_budgets,
            "draft": int(prepared.context_token_budget),
            "quality": self.quality_context_token_budget,
        }
        return report

    def _generate_plan(
        self, book: dict[str, Any], generator: str, chapter_number: int
    ) -> Any:
        inputs = self._resolve_generation_inputs(book, generator)
        parent = (
            self.query.require_input_snapshot(str(book["input_snapshot_id"]))[
                "current_volume_plan_version"
            ]
            if generator == "chapter_group_plan.generate"
            else str(
                self._active_plan(book, "CHAPTER_GROUP", chapter_number)[
                    "asset_version_id"
                ]
            )
        )
        return self.planning.generate(
            StoryPlanningGenerationCommand(
                project_id=str(book["project_id"]),
                workspace_id=str(book["workspace_id"]),
                book_id=str(book["book_id"]),
                actor_id=self.principal.principal_id,
                generator_operation_name=generator,
                logical_key=(
                    f"chapter-group:containing:{chapter_number}"
                    if generator == "chapter_group_plan.generate"
                    else f"chapter:{chapter_number}"
                ),
                input_versions=inputs,
                parent_version_id=parent,
                idempotency_key=(
                    f"{book['stable_idempotency_key']}:{generator}:{chapter_number}:"
                    f"snapshot:{book['input_snapshot_id']}"
                ),
                trace_id=f"{book['root_operation_id']}:{generator}:{chapter_number}",
                correlation_id=str(book["root_operation_id"]),
                auto_approve_low_risk=True,
            ),
            principal=self.principal,
        )

    def _resolve_generation_inputs(
        self, book: dict[str, Any], generator: str
    ) -> dict[str, str]:
        snapshot = self.query.require_input_snapshot(str(book["input_snapshot_id"]))
        fixed = {
            "book_plan": snapshot["book_plan_version"],
            "volume_plan": snapshot["current_volume_plan_version"],
            "arc_plans": self._primary_arc_version(snapshot),
            "character_state": snapshot["character_state_version"],
            "foreshadowing_state": snapshot["foreshadowing_state_version"],
            "quality_trend": snapshot["quality_trend_version"],
            "reward_ledger": snapshot["reward_ledger_version"],
            "promise_ledger": snapshot["promise_ledger_version"],
        }
        group = self._active_plan(
            book, "CHAPTER_GROUP", int(book["accepted_through_chapter"]) + 1
        )
        if group:
            fixed["chapter_group_plan"] = group["asset_version_id"]
        result: dict[str, str] = {}
        for role in GENERATOR_INPUT_ROLES[generator]:
            value = fixed.get(role) or self._latest_role_asset(book, role)
            if not value:
                raise KernelError(
                    "BOOK_SUPERVISOR_PLANNING_INPUT_MISSING",
                    f"Authority could not resolve Planning role {role}",
                )
            result[role] = str(value)
        return result

    def _latest_role_asset(self, book: dict[str, Any], role: str) -> str:
        aliases = {
            "story_state": ("story_state_snapshot", "story_state"),
            "canon_snapshot": ("canon_snapshot",),
            "previous_chapter_group_outcome": (
                "previous_chapter_group_outcome",
                "chapter_group_outcome",
            ),
            "reader_state": ("reader_state", "reader_state_transition"),
            "chapter_function_matrix_row": (
                "chapter_function_matrix_row",
                "chapter_function_matrix",
            ),
            "previous_chapter_outcome": (
                "previous_chapter_outcome",
                "chapter_outcome",
            ),
        }.get(role, (role,))
        return self.query.latest_eligible_role_asset(
            project_id=str(book["project_id"]),
            book_id=str(book["book_id"]),
            asset_types=aliases,
        )

    def _active_plan(
        self, book: dict[str, Any], contract_type: str, chapter_number: int
    ) -> dict[str, Any] | None:
        return self.query.active_plan_covering_chapter(
            project_id=str(book["project_id"]),
            book_id=str(book["book_id"]),
            contract_type=contract_type,
            chapter_number=chapter_number,
        )

    def _freeze_plan(
        self,
        book: dict[str, Any],
        plan: dict[str, Any],
        contract_type: PlanContractType,
    ) -> str:
        frozen = self.planning.planning.bind_active_contract(
            project_id=str(book["project_id"]),
            book_id=str(book["book_id"]),
            asset_version_id=str(plan["asset_version_id"]),
            contract_type=contract_type,
            parent_version_id=str(plan["parent_version_id"]),
            execution_scope=PlanExecutionScope.FROZEN,
            expected_active_asset_version_id=str(plan["asset_version_id"]),
            decision_evidence={
                "authority": "BOOK_PRODUCTION_SUPERVISOR",
                "reason": "next executable plan checkpoint",
                "book_input_snapshot_id": str(book["input_snapshot_id"]),
            },
            workspace_id=str(book["workspace_id"]),
            actor_id=self.principal.principal_id,
            idempotency_key=(
                f"{book['stable_idempotency_key']}:freeze:{contract_type.value}:"
                f"{plan['asset_version_id']}"
            ),
            trace_id=f"{book['root_operation_id']}:freeze:{contract_type.value}",
            correlation_id=str(book["root_operation_id"]),
            causation_operation_id=str(book["root_operation_id"]),
            principal=self.principal,
        )
        return str(frozen["operation_id"])

    def _active_group_run(
        self, book: dict[str, Any], group_plan_version: str = ""
    ) -> dict[str, Any] | None:
        group_run_id = self.query.active_chapter_group_run_id(
            project_id=str(book["project_id"]),
            book_run_id=str(book["book_run_id"]),
            group_plan_version_id=group_plan_version,
        )
        return self.chapter_groups.require(group_run_id) if group_run_id else None

    @staticmethod
    def _primary_arc_version(snapshot: dict[str, Any]) -> str:
        versions = tuple(str(item) for item in snapshot["active_arc_plan_versions"])
        if not versions:
            raise KernelError(
                "BOOK_SUPERVISOR_ACTIVE_ARC_MISSING",
                "resolved Book input has no Active Arc plan",
            )
        return versions[0]

    @staticmethod
    def _scheduler_action(action: str) -> SupervisorAction:
        return {
            "RECONCILE_CHAPTER": SupervisorAction.RECONCILE_CHAPTER,
            "ACCEPT_CHAPTER_AND_SUBMIT_READER_SHADOW": SupervisorAction.ACCEPT_CHAPTER,
            "SUBMIT_READER_SHADOW": SupervisorAction.SCHEDULE_READER_OUTCOME,
            "COMPLETE_READER_SHADOW": SupervisorAction.SCHEDULE_READER_OUTCOME,
            "SUBMIT_LONGFORM_RECAP_SIDECAR": SupervisorAction.SCHEDULE_LONGFORM_RECAP,
            "COMPLETE_LONGFORM_RECAP_SIDECAR": SupervisorAction.SCHEDULE_LONGFORM_RECAP,
        }.get(action, SupervisorAction.NO_ACTION)

    def _checkpoint_if_needed(self, book: dict[str, Any]) -> dict[str, Any] | None:
        chapter = int(book["accepted_through_chapter"])
        if chapter <= 0:
            return None
        chapter_request_id = self.query.checkpointable_chapter_request_id(
            book_run_id=str(book["book_run_id"]),
            accepted_through_chapter=chapter,
        )
        if not chapter_request_id:
            return None
        return self.checkpoints.record_after_acceptance(
            book_run_id=str(book["book_run_id"]),
            chapter_request_id=chapter_request_id,
            principal=self.principal,
        )

    def _start_replan(self, book: dict[str, Any]) -> BookProductionSupervisorTick:
        from novel_forge.modules.book_replan import CoordinateBookReplanCommand

        source = self.query.require_replan_source(book_run_id=str(book["book_run_id"]))
        accepted_chapter = int(book["accepted_through_chapter"])
        result = self.replan.start(
            CoordinateBookReplanCommand(
                project_id=str(book["project_id"]),
                workspace_id=str(book["workspace_id"]),
                book_id=str(book["book_id"]),
                book_run_id=str(book["book_run_id"]),
                source_recap_asset_version_id=str(source["recap_asset_version_id"]),
                replan_request_asset_version_id=str(
                    source["replan_request_asset_version_id"]
                ),
                affected_scope=str(source["affected_scope"]),
                idempotency_key=(
                    f"{book['stable_idempotency_key']}:replan:{accepted_chapter}:"
                    f"{source['recap_operation_id']}"
                ),
                trace_id=f"{book['root_operation_id']}:replan:{accepted_chapter}",
                correlation_id=str(source["recap_operation_id"]),
            )
        )
        return self._result(
            str(book["book_run_id"]),
            BookProductionState.REPLAN_REQUIRED.value,
            SupervisorAction.START_REPLAN,
            str(result["generation_operation_id"]),
            str(result["replan_id"]),
        )

    def _latest_replan(self, book_run_id: str) -> dict[str, Any]:
        result = self.replan.latest_for_book(book_run_id)
        if result is None:
            raise KernelError(
                "BOOK_REPLAN_NOT_FOUND",
                "Book state references no durable Replan record",
            )
        return dict(result)

    @staticmethod
    def _context_version_refs(
        book: dict[str, Any], group: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            **dict(book["longform_context_versions"]),
            "book_design_version": book["book_design_version"],
            "book_plan_version": book["book_plan_version"],
            "chapter_group_plan_version": group["asset_version_id"],
            "book_production_input_snapshot_id": book["input_snapshot_id"],
        }

    def _result(
        self,
        book_run_id: str,
        previous_state: str,
        action: SupervisorAction,
        operation_id: str = "",
        evidence_ref: str = "",
    ) -> BookProductionSupervisorTick:
        return BookProductionSupervisorTick(
            book_run_id,
            previous_state,
            str(self.authority.require(book_run_id)["state"]),
            action,
            operation_id,
            evidence_ref,
        )


__all__ = ["BookProductionSupervisorTick", "PostgresBookProductionSupervisor"]
