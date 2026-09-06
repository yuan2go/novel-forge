from __future__ import annotations

from dataclasses import dataclass, replace
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
    PostgresNarrativeRealizationApplication,
)
from novel_forge.modules.production_preparation import (
    ProductionPreparationRequest,
    ProductionPreparationService,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PlanningGenerationStatus,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from .governed_scheduler import PostgresBookAuthorityScheduler
from .production import (
    BookProductionState,
    BookProductionStateClass,
    PostgresBookAuthority,
    SubmitBookChapterCommand,
    book_production_state_semantics,
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


def _bounded_chapter_group_range(
    *,
    start_chapter: int,
    target_chapter_count: int,
    preferred_size: int,
    maximum_chapters: int = 8,
) -> tuple[int, int]:
    if start_chapter <= 0 or target_chapter_count < start_chapter:
        raise KernelError(
            "BOOK_SUPERVISOR_CHAPTER_GROUP_HORIZON_INVALID",
            "ChapterGroup horizon must begin inside the bounded Book",
        )
    remaining = target_chapter_count - start_chapter + 1
    if preferred_size <= 0 or maximum_chapters <= 0:
        raise ValueError("ChapterGroup execution window limits must be positive")
    size = min(preferred_size, maximum_chapters, remaining)
    return start_chapter, start_chapter + size - 1


class PostgresBookProductionSupervisor:
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
        realizations: PostgresNarrativeRealizationApplication,
        narrative_search: PostgresNarrativeSearchApplication | None = None,
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
        self.realizations = realizations
        self.narrative_search = narrative_search or PostgresNarrativeSearchApplication(
            authority.database_url, planning=planning
        )
        self.scheduler = PostgresBookAuthorityScheduler(
            authority, query=query, principal=principal
        )
        self.checkpoints = PostgresBookNarrativeCheckpointAuthority(
            authority.database_url,
            application_build_id=authority.application_build_id,
            commit_sha=authority.commit_sha,
        )

    def tick(self, book_run_id: str) -> BookProductionSupervisorTick:
        try:
            return self._tick(book_run_id)
        except KernelError as exc:
            if exc.code != "BOOK_CONTROL_APPROVAL_REQUIRED":
                raise
            book = self.authority.require(book_run_id)
            return self._result(book_run_id, str(book["state"]), SupervisorAction.WAIT_CONTROL_DECISION)

    def _tick(self, book_run_id: str) -> BookProductionSupervisorTick:
        book = self.authority.require(book_run_id)
        before = str(book["state"])
        semantics = book_production_state_semantics(before)
        group_run = self._active_group_run(book)
        if (
            group_run is not None
            and group_run.get("active_chapter_request_id")
            and int(group_run["accepted_through_chapter"]) < int(book["accepted_through_chapter"])
        ):
            self.chapter_groups.reconcile_and_accept(str(group_run["group_run_id"]), principal=self.principal)
            return self._result(book_run_id, before, SupervisorAction.ACCEPT_CHAPTER)
        if book["input_mode"] != "RESOLVED_AUTHORITY_INPUT":
            raise KernelError(
                "BOOK_SUPERVISOR_RESOLVED_INPUT_REQUIRED",
                "autonomous supervision cannot run in Legacy fixture input mode",
            )
        if semantics.state_class is BookProductionStateClass.TERMINAL:
            return self._result(book_run_id, before, SupervisorAction.NO_ACTION)
        if before == BookProductionState.PLAN_APPROVAL_PENDING.value:
            return self._result(
                book_run_id,
                before,
                SupervisorAction.WAIT_PLAN_APPROVAL,
            )
        if before == BookProductionState.CHECKPOINT_PENDING.value:
            checkpoint = self._checkpoint_if_needed(book)
            if checkpoint is not None:
                return self._result(
                    book_run_id,
                    before,
                    SupervisorAction.UPDATE_CHECKPOINTS,
                    evidence_ref=checkpoint["volume_checkpoint"]["checkpoint_id"],
                )
            return self._result(book_run_id, before, SupervisorAction.NO_ACTION)
        if (
            semantics.state_class is BookProductionStateClass.DURABLE_WAIT
            and before != BookProductionState.REPLAN_APPROVAL_PENDING.value
        ):
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
            BookProductionState.CHAPTER_ACCEPTANCE_PENDING.value,
            BookProductionState.CHAPTER_FAILED_RETRYABLE.value,
            BookProductionState.CHAPTER_FAILED_TERMINAL.value,
            BookProductionState.CANON_PENDING.value,
            BookProductionState.CANON_COMMITTED.value,
            BookProductionState.READER_OUTCOME_PENDING.value,
            BookProductionState.FOLLOWUP_PENDING.value,
        }:
            group_run = self._active_group_run(book)
            if (
                group_run is not None
                and group_run["state"] == ChapterGroupState.CLOSURE_PENDING.value
                and before
                in {
                    BookProductionState.CANON_COMMITTED.value,
                    BookProductionState.READER_OUTCOME_PENDING.value,
                    BookProductionState.FOLLOWUP_PENDING.value,
                }
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
            if (
                group_run is not None
                and group_run["active_chapter_request_id"] is not None
                and before
                in {
                    BookProductionState.CHAPTER_SUBMITTED.value,
                    BookProductionState.CHAPTER_RUNNING.value,
                    BookProductionState.CHAPTER_WAITING_RETRY.value,
                    BookProductionState.CHAPTER_COMPLETED.value,
                    BookProductionState.CHAPTER_ACCEPTANCE_PENDING.value,
                    BookProductionState.CHAPTER_FAILED_RETRYABLE.value,
                    BookProductionState.CANON_PENDING.value,
                    BookProductionState.CANON_COMMITTED.value,
                    BookProductionState.READER_OUTCOME_PENDING.value,
                    BookProductionState.FOLLOWUP_PENDING.value,
                }
            ):
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
            if (
                group_run is not None
                and before == BookProductionState.CHAPTER_FAILED_TERMINAL.value
            ):
                request = self.authority.require_chapter_request(
                    str(book["active_chapter_request_id"])
                )
                reason = str(request.get("failure_classification") or "")
                self.chapter_groups.cancel(
                    str(group_run["group_run_id"]),
                    reason=reason or "Chapter Authority reached a terminal failure",
                    principal=self.principal,
                )
                return self._result(
                    book_run_id,
                    before,
                    SupervisorAction.ABORT_TERMINAL_CHAPTER,
                )
            tick = self.scheduler.tick(book_run_id)
            action = self._scheduler_action(tick.action)
            return self._result(book_run_id, before, action, tick.operation_id)
        if (
            before == BookProductionState.READY.value
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
            self.authority.complete_book_checkpoint(
                str(book["book_run_id"]),
                chapter_number=int(book["accepted_through_chapter"]),
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
        if group[
            "execution_scope"
        ] == PlanExecutionScope.PLANNED.value and self._plan_working_set_is_stale(
            book=book,
            plan=group,
            generator="chapter_group_plan.generate",
            chapter_number=next_chapter,
        ):
            result = self._replace_planned_working_set(
                book=book,
                plan=group,
                generator="chapter_group_plan.generate",
                chapter_number=next_chapter,
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
        try:
            realization = self.realizations.require_current_for_chapter(
                project_id=str(book["project_id"]),
                book_id=str(book["book_id"]),
                chapter_group_plan_version_id=str(group["asset_version_id"]),
                chapter_number=next_chapter,
            )
        except KernelError as exc:
            if exc.code != "NARRATIVE_REALIZATION_REQUIRED":
                raise
            working_set = self._generation_arc_working_set(
                book=book,
                generator="chapter_group_plan.generate",
                chapter_number=next_chapter,
            )
            frozen = self.realizations.qualify_and_freeze_for_group(
                book_run_id=str(book["book_run_id"]),
                chapter_group_plan_version_id=str(group["asset_version_id"]),
                arc_working_set=working_set,
                principal=self.principal,
                idempotency_key=(
                    f"{book['stable_idempotency_key']}:narrative-realization:"
                    f"{group['asset_version_id']}:{working_set['working_set_digest']}"
                ),
                trace_id=f"{book['root_operation_id']}:narrative-realization",
                correlation_id=str(book["root_operation_id"]),
            )
            return self._result(
                book_run_id,
                before,
                SupervisorAction.QUALIFY_NARRATIVE_REALIZATION,
                str(frozen["operation_id"]),
                str(frozen["realization_id"]),
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
        if self._plan_working_set_is_stale(
            book=book,
            plan=chapter_plan,
            generator="chapter_plan.generate",
            chapter_number=next_chapter,
        ):
            result = self._replace_planned_working_set(
                book=book,
                plan=chapter_plan,
                generator="chapter_plan.generate",
                chapter_number=next_chapter,
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
        chapter_admission = self.query.require_chapter_production_admission(
            book_run_id=str(book["book_run_id"]),
            snapshot_id=str(book["input_snapshot_id"]),
            chapter_group_plan_version_id=str(group["asset_version_id"]),
            chapter_plan_version_id=str(chapter_plan["asset_version_id"]),
            chapter_number=next_chapter,
            accepted_through_chapter=int(book["accepted_through_chapter"]),
            active_story_state_version_id=str(
                book.get("active_story_state_version_id") or ""
            ),
            active_canon_snapshot_version_id=str(
                book.get("active_canon_snapshot_version_id") or ""
            ),
        )
        explicit_overrides: dict[str, str | list[str]] = {
            "chapter_plan": str(execution_plan["asset_version_id"])
        }
        snapshot = self.query.require_input_snapshot(str(book["input_snapshot_id"]))
        explicit_overrides.update(self._chapter_foundation_overrides(snapshot))
        execution_envelope = (execution_plan.get("content") or {}).get(
            "constraint_envelope"
        )
        execution_working_set = (
            execution_envelope.get("arc_working_set")
            if isinstance(execution_envelope, dict)
            else None
        )
        selected_arc_versions = [
            str(item.get("arc_plan_version_id") or "")
            for item in (execution_working_set or {}).get("selected_contributions", ())
            if isinstance(item, dict) and str(item.get("arc_plan_version_id") or "")
        ]
        if not selected_arc_versions:
            raise KernelError(
                "BOOK_SUPERVISOR_ARC_WORKING_SET_MISSING",
                "Chapter preparation requires the selected ArcPlan versions",
            )
        # INVARIANT: The Working Set chooses a bounded subset, while Planning Authority
        # remains the owner of the immutable ArcPlan contracts.  Freeze those
        # exact selected versions into the existing production manifest so
        # Mission/Context and accepted evidence share one completion identity.
        explicit_overrides["arc_plan"] = selected_arc_versions
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
            initial_story_state = str(snapshot.get("initial_story_state_version") or "")
            initial_canon = str(snapshot.get("initial_canon_snapshot_version") or "")
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
            **self._context_version_refs(book, group, chapter_plan),
            **dict(prepared.context_version_refs),
            "longform_design_qualification_hash": chapter_admission[
                "longform_design_qualification_hash"
            ],
            "chapter_production_admission_hash": chapter_admission["admission_hash"],
        }
        preparation_report = self._stage_budgeted_preparation_report(prepared)
        preparation_report["chapter_production_admission"] = chapter_admission
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
                narrative_realization_id=str(realization["realization_id"]),
                narrative_realization_slice_id=str(realization["slice_id"]),
                narrative_realization_contract_digest=str(
                    realization["contract_digest"]
                ),
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
            capability_required_asset_types=("character_cast", "reader_promise"),
            context_token_budget=self.context_token_budget,
        )

    @staticmethod
    def _chapter_foundation_overrides(
        snapshot: dict[str, Any],
    ) -> dict[str, str]:
        foundation = snapshot.get("foundation_set")
        bindings = foundation.get("bindings") if isinstance(foundation, dict) else None
        if not isinstance(bindings, list):
            raise KernelError(
                "BOOK_SUPERVISOR_FOUNDATION_CONTEXT_MISSING",
                "Chapter preparation requires the frozen qualified Foundation Set",
            )
        expected = {
            "CHARACTER_CAST": "character_cast",
            "READER_PROMISE": "reader_promise",
        }
        by_role: dict[str, dict[str, Any]] = {}
        for raw in bindings:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "")
            if role in expected:
                if role in by_role:
                    raise KernelError(
                        "BOOK_SUPERVISOR_FOUNDATION_CONTEXT_MISSING",
                        f"duplicate {role} Foundation binding",
                    )
                by_role[role] = raw
        if set(by_role) != set(expected):
            raise KernelError(
                "BOOK_SUPERVISOR_FOUNDATION_CONTEXT_MISSING",
                "Chapter preparation requires exact CHARACTER_CAST and READER_PROMISE bindings",
            )
        result: dict[str, str] = {}
        for role, asset_type in expected.items():
            binding = by_role[role]
            version = str(binding.get("asset_version_id") or "")
            content_hash = str(binding.get("content_hash") or "")
            digest = content_hash.removeprefix("sha256:")
            if (
                not version
                or not content_hash.startswith("sha256:")
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise KernelError(
                    "BOOK_SUPERVISOR_FOUNDATION_CONTEXT_MISSING",
                    f"{role} Foundation binding lacks exact version/hash lineage",
                )
            result[asset_type] = version
        return result

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
        self,
        book: dict[str, Any],
        generator: str,
        chapter_number: int,
        *,
        replacement_plan: dict[str, Any] | None = None,
    ) -> Any:
        cursor_projection = self.query.require_cursor_plan_projection(
            snapshot_id=str(book["input_snapshot_id"]),
            chapter_cursor=chapter_number,
        )
        arc_working_set = self._generation_arc_working_set(
            book=book,
            generator=generator,
            chapter_number=chapter_number,
        )
        arc_versions = tuple(
            str(item["arc_plan_version_id"])
            for item in arc_working_set["selected_contributions"]
        )
        inputs = self._resolve_generation_inputs(
            book,
            generator,
            primary_arc_version=arc_versions[0],
            volume_plan_version=str(cursor_projection["volume_plan_version"]),
        )
        parent = (
            str(cursor_projection["volume_plan_version"])
            if generator == "chapter_group_plan.generate"
            else str(
                self._active_plan(book, "CHAPTER_GROUP", chapter_number)[
                    "asset_version_id"
                ]
            )
        )
        causal_versions = self.query.causal_action_versions(book_run_id=str(book["book_run_id"]), chapter_number=chapter_number)
        if causal_versions:
            from .control_application import PostgresBookControlApplication
            controls = PostgresBookControlApplication(self.authority.database_url, application_build_id=self.authority.application_build_id, commit_sha=self.authority.commit_sha)
            for version in causal_versions:
                controls.require_causal_approval(project_id=str(book["project_id"]), book_run_id=str(book["book_run_id"]), chapter_number=chapter_number, actor_id=self.principal.principal_id, subject_version_id=version)
        generation = StoryPlanningGenerationCommand(
            world_preparation_request={
                "book_run_id": str(book["book_run_id"]),
                "input_snapshot_id": str(book["input_snapshot_id"]),
                "accepted_through_chapter": int(book["accepted_through_chapter"]),
                "story_state_version_id": str(book.get("active_story_state_version_id") or ""),
                "canon_version_id": str(book.get("active_canon_snapshot_version_id") or ""),
                "planning_input_refs": [{"role": role, "asset_version_id": version} for role, version in inputs.items() if role in {"book_plan", "volume_plan", "arc_plans", "chapter_group_plan"}] + [{"role": "arc_plans", "asset_version_id": version} for version in arc_versions[1:]],
            } if generator == "chapter_plan.generate" else None,
            project_id=str(book["project_id"]),
            workspace_id=str(book["workspace_id"]),
            book_id=str(book["book_id"]),
            actor_id=self.principal.principal_id,
            generator_operation_name=generator,
            logical_key=(
                str(replacement_plan["content"]["logical_key"])
                if replacement_plan is not None
                else f"chapter-group:containing:{chapter_number}"
                if generator == "chapter_group_plan.generate"
                else f"chapter:{chapter_number}"
            ),
            input_versions=inputs,
            parent_version_id=parent,
            related_arc_plan_version_ids=(
                tuple(arc_versions[1:])
                if generator in {"chapter_group_plan.generate", "chapter_plan.generate"}
                else ()
            ),
            governance_action_version_ids=tuple(dict.fromkeys((
                *self._governance_action_versions(project_id=str(book["project_id"]), input_version_ids=tuple(inputs.values())),
                *causal_versions,
            ))),
            idempotency_key=(
                f"{book['stable_idempotency_key']}:{generator}:{chapter_number}:"
                f"snapshot:{book['input_snapshot_id']}:"
                f"working-set:{arc_working_set['working_set_digest']}"
            ),
            trace_id=f"{book['root_operation_id']}:{generator}:{chapter_number}",
            correlation_id=str(book["root_operation_id"]),
            auto_approve_low_risk=(
                generator != "chapter_group_plan.generate" and replacement_plan is None
            ),
            arc_working_set=arc_working_set,
            narrative_realization=(
                self.realizations.require_current_for_chapter(
                    project_id=str(book["project_id"]),
                    book_id=str(book["book_id"]),
                    chapter_group_plan_version_id=parent,
                    chapter_number=chapter_number,
                )
                if generator == "chapter_plan.generate"
                else None
            ),
        )
        if generator == "chapter_group_plan.generate":
            accepted_through = int(book["accepted_through_chapter"])
            volume_range = tuple(
                int(item) for item in cursor_projection["volume_chapter_range"]
            )
            if len(volume_range) != 2 or not (
                volume_range[0] <= chapter_number <= volume_range[1]
            ):
                raise KernelError(
                    "BOOK_SUPERVISOR_CHAPTER_GROUP_HORIZON_INVALID",
                    "ChapterGroup cursor must belong to the projected Volume",
                )
            execution_policy = self.chapter_groups.execution_policies.freeze_for_book(
                project_id=str(book["project_id"]),
                book_run_id=str(book["book_run_id"]),
                actor_id=self.principal.principal_id,
            )
            group_start, group_end = _bounded_chapter_group_range(
                start_chapter=chapter_number,
                target_chapter_count=min(
                    int(book["target_chapter_count"]), volume_range[1]
                ),
                preferred_size=execution_policy["policy"]["preferred_chapters"],
                maximum_chapters=execution_policy["policy"]["maximum_chapters"],
            )
            parent_state = str(book.get("active_story_state_version_id") or "")
            if accepted_through == 0:
                parent_state = str(
                    self.query.require_input_snapshot(
                        str(book["input_snapshot_id"])
                    ).get("initial_story_state_version")
                    or ""
                )
            search = self.narrative_search.explore(
                NarrativeSearchRequest(
                    generation=generation,
                    planning_horizon={
                        "level": "CHAPTER_GROUP",
                        "starts_at_chapter": group_start,
                        "ends_at_chapter": group_end,
                        "chapter_range": [group_start, group_end],
                        "near_future": True,
                    },
                    desired_transformation={
                        "chapter_range": [group_start, group_end],
                        "arc_working_set_digest": arc_working_set["working_set_digest"],
                        "selected_arc_contributions": list(
                            arc_working_set["selected_contributions"]
                        ),
                    },
                    hard_constraints=(
                        "accepted reality is immutable",
                        "candidate scheduling and realization must exactly cover the frozen ChapterGroup range",
                        "only selected working-set arcs may receive contributions",
                        "preserve POV knowledge and forbidden-change boundaries",
                    ),
                    accepted_through_chapter=accepted_through,
                    book_run_id=str(book["book_run_id"]),
                    parent_state_asset_version_id=parent_state,
                    expected_active_asset_version_id=(
                        str(replacement_plan["asset_version_id"])
                        if replacement_plan is not None
                        else ""
                    ),
                    replacement_decision_evidence=(
                        self._working_set_replacement_evidence(
                            book=book,
                            plan=replacement_plan,
                            arc_working_set=arc_working_set,
                        )
                        if replacement_plan is not None
                        else {}
                    ),
                ),
                principal=self.principal,
                activate_selected=True,
            )
            return search.selected_generation
        frozen = self.planning.find_frozen_generation_command(project_id=generation.project_id, idempotency_key=generation.idempotency_key)
        result = self.planning.generate(frozen or generation, principal=self.principal)
        if replacement_plan is None:
            return result
        if result.status is not PlanningGenerationStatus.APPROVAL_PENDING:
            raise KernelError(
                "BOOK_SUPERVISOR_PLAN_REPLACEMENT_INVALID",
                "replacement candidate did not stop at the approval boundary",
            )
        self.planning.approve_candidate(
            result.candidate_asset_version_id,
            principal=self.principal,
            idempotency_key=f"{generation.idempotency_key}:approve-replacement",
            trace_id=generation.trace_id,
            correlation_id=generation.correlation_id,
        )
        activation = self.planning.activate_candidate(
            result.candidate_asset_version_id,
            principal=self.principal,
            idempotency_key=f"{generation.idempotency_key}:activate-replacement",
            trace_id=generation.trace_id,
            correlation_id=generation.correlation_id,
            expected_active_asset_version_id=str(replacement_plan["asset_version_id"]),
            decision_evidence=self._working_set_replacement_evidence(
                book=book,
                plan=replacement_plan,
                arc_working_set=arc_working_set,
            ),
        )
        return replace(
            result,
            status=PlanningGenerationStatus.ACTIVE,
            story_design_state=dict(activation["story_design"]),
            planning_binding=dict(activation["planning_binding"]),
        )

    def _plan_working_set_is_stale(
        self,
        *,
        book: dict[str, Any],
        plan: dict[str, Any],
        generator: str,
        chapter_number: int,
    ) -> bool:
        expected = self._generation_arc_working_set(
            book=book,
            generator=generator,
            chapter_number=chapter_number,
        )
        envelope = plan["content"].get("constraint_envelope")
        declared = (
            envelope.get("arc_working_set") if isinstance(envelope, dict) else None
        )
        return declared != expected

    def _replace_planned_working_set(
        self,
        *,
        book: dict[str, Any],
        plan: dict[str, Any],
        generator: str,
        chapter_number: int,
    ) -> Any:
        if plan["execution_scope"] != PlanExecutionScope.PLANNED.value:
            raise KernelError(
                "BOOK_SUPERVISOR_FROZEN_PLAN_WORKING_SET_STALE",
                "a Frozen near-future plan requires explicit PlanChange before replacement",
            )
        return self._generate_plan(
            book,
            generator,
            chapter_number,
            replacement_plan=plan,
        )

    @staticmethod
    def _working_set_replacement_evidence(
        *,
        book: dict[str, Any],
        plan: dict[str, Any] | None,
        arc_working_set: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "authority": "BOOK_PRODUCTION_SUPERVISOR",
            "reason": "accepted-reality Arc Working Set changed before freeze",
            "book_run_id": str(book["book_run_id"]),
            "accepted_through_chapter": int(book["accepted_through_chapter"]),
            "replaced_asset_version_id": str(
                (plan or {}).get("asset_version_id") or ""
            ),
            "working_set_digest": str(arc_working_set["working_set_digest"]),
        }

    def _governance_action_versions(
        self, *, project_id: str, input_version_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        return self.query.governance_action_versions(
            project_id=project_id,
            input_version_ids=input_version_ids,
        )

    def _resolve_generation_inputs(
        self,
        book: dict[str, Any],
        generator: str,
        *,
        primary_arc_version: str,
        volume_plan_version: str,
    ) -> dict[str, str]:
        snapshot = self.query.require_input_snapshot(str(book["input_snapshot_id"]))
        fixed = {
            "book_plan": snapshot["book_plan_version"],
            "volume_plan": volume_plan_version,
            "arc_plans": primary_arc_version,
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
            # INVARIANT: Planning Authority accepts the frozen ChapterGroupPlan itself as
            # the source for this role and validates/extracts the unique row
            # for the requested Chapter.  Reuse that exact Active version so a
            # stale standalone matrix asset can never outrank the current plan.
            fixed["chapter_function_matrix_row"] = group["asset_version_id"]
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

    def _generation_arc_working_set(
        self,
        *,
        book: dict[str, Any],
        generator: str,
        chapter_number: int,
    ) -> dict[str, Any]:
        schedule_row: dict[str, Any] | None = None
        if generator == "chapter_plan.generate":
            group = self._active_plan(book, "CHAPTER_GROUP", chapter_number)
            if group is None:
                raise KernelError(
                    "BOOK_SUPERVISOR_CHAPTER_GROUP_MISSING",
                    "Chapter generation requires current Narrative Scheduling",
                )
            rows = [
                item
                for item in group["content"].get("chapter_function_matrix") or ()
                if isinstance(item, dict)
                and int(item.get("chapter_number") or 0) == chapter_number
            ]
            if len(rows) != 1:
                raise KernelError(
                    "BOOK_SUPERVISOR_SCHEDULE_ROW_INVALID",
                    "Narrative Scheduling must contain one Chapter function row",
                )
            schedule_row = rows[0]
        return self.query.require_arc_working_set(
            book_run_id=str(book["book_run_id"]),
            snapshot_id=str(book["input_snapshot_id"]),
            chapter_number=chapter_number,
            schedule_row=schedule_row,
        )

    @staticmethod
    def _scheduler_action(action: str) -> SupervisorAction:
        return {
            "RECONCILE_CHAPTER": SupervisorAction.RECONCILE_CHAPTER,
            "ACCEPT_CHAPTER": SupervisorAction.ACCEPT_CHAPTER,
            "RECOVER_LEGACY_ACCEPTANCE": SupervisorAction.ACCEPT_CHAPTER,
            "ABORT_TERMINAL_CHAPTER": SupervisorAction.ABORT_TERMINAL_CHAPTER,
            "NORMALIZE_LEGACY_NON_BLOCKING_STATE": (
                SupervisorAction.NORMALIZE_LEGACY_STATE
            ),
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
                target_asset_version_id=str(
                    source.get("target_asset_version_id") or ""
                ),
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

    def _context_version_refs(
        self,
        book: dict[str, Any],
        group: dict[str, Any],
        chapter_plan: dict[str, Any],
    ) -> dict[str, Any]:
        projection = self.query.require_cursor_plan_projection(
            snapshot_id=str(book["input_snapshot_id"]),
            chapter_cursor=int(book["accepted_through_chapter"]) + 1,
        )
        envelope = (chapter_plan.get("content") or {}).get("constraint_envelope")
        working_set = dict(
            envelope.get("arc_working_set") if isinstance(envelope, dict) else {}
        )
        if not working_set:
            raise KernelError(
                "BOOK_SUPERVISOR_ARC_WORKING_SET_MISSING",
                "Chapter dispatch requires its frozen Arc Working Set",
            )
        return {
            **dict(book["longform_context_versions"]),
            "volume_plan_version": projection["volume_plan_version"],
            "arc_plan_versions": list(projection["arc_plan_versions"]),
            "selected_arc_plan_versions": [
                str(item["arc_plan_version_id"])
                for item in working_set["selected_contributions"]
            ],
            "arc_working_set": working_set,
            "arc_working_set_digest": working_set["working_set_digest"],
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
