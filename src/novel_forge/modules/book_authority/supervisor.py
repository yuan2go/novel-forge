"""Deterministic Book Production Supervisor over existing Domain Authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

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
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
)
from novel_forge.modules.production_preparation import (
    PostgresProductionAssetResolver,
    ProductionPreparationRequest,
    ProductionPreparationService,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationStatus,
    StoryPlanningGenerationApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .governed_scheduler import PostgresBookAuthorityScheduler
from .production import (
    BookProductionState,
    PostgresBookAuthority,
    SubmitBookChapterCommand,
)


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
        principal: Principal,
        production_preparation: ProductionPreparationService | None = None,
    ) -> None:
        self.authority = authority
        self.planning = planning
        self.chapter_groups = chapter_groups
        self.principal = principal
        self.production_preparation = production_preparation or ProductionPreparationService(
            PostgresProductionAssetResolver(authority.database_url)
        )
        self.scheduler = PostgresBookAuthorityScheduler(authority, principal=principal)
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
        if before in {
            BookProductionState.READY.value,
            BookProductionState.COMPLETED.value,
        } and int(book["accepted_through_chapter"]) > 0:
            sidecar = self.scheduler.tick(book_run_id)
            action = self._scheduler_action(sidecar.action)
            if action is not SupervisorAction.NO_ACTION:
                return self._result(book_run_id, before, action, sidecar.operation_id)
        checkpoint = self._checkpoint_if_needed(book)
        if checkpoint is not None:
            if checkpoint["ending_reachability"]["replan_required"]:
                self._set_state(book, BookProductionState.REPLAN_REQUIRED)
            return self._result(
                book_run_id,
                before,
                SupervisorAction.UPDATE_CHECKPOINTS,
                evidence_ref=checkpoint["volume_checkpoint"]["checkpoint_id"],
            )
        if before == BookProductionState.REPLAN_REQUIRED.value:
            return self._result(book_run_id, before, SupervisorAction.START_REPLAN)
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
            self._set_state(book, BookProductionState.COMPLETED)
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
            self._set_state(book, target)
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
            self._set_state(book, target)
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
        execution_plan = self._chapter_execution_plan(chapter_plan)
        explicit_overrides = {
            "chapter_plan": str(execution_plan["asset_version_id"])
        }
        if next_chapter > 1:
            previous_story_state = str(
                book.get("active_story_state_version_id") or ""
            )
            previous_canon = str(
                book.get("active_canon_snapshot_version_id") or ""
            )
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
        preparation = self.production_preparation.prepare(
            ProductionPreparationRequest(
                project_id=str(book["project_id"]),
                workspace_id=str(book["workspace_id"]),
                chapter=next_chapter,
                idempotency_key=(
                    f"{book['stable_idempotency_key']}:chapter:{next_chapter}"
                ),
                explicit_asset_version_overrides=explicit_overrides,
                context_token_budget=16_000,
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
                execution_chapter_plan_content_hash=str(
                    execution_plan["content_hash"]
                ),
                parent_group_version_id=str(group["asset_version_id"]),
                context_version_refs=context_version_refs,
                context_token_budget=prepared.context_token_budget,
                preparation_report=prepared.preparation_report,
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

    def _generate_plan(
        self, book: dict[str, Any], generator: str, chapter_number: int
    ) -> Any:
        inputs = self._resolve_generation_inputs(book, generator)
        parent = (
            self._snapshot(book)["current_volume_plan_version"]
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
        snapshot = self._snapshot(book)
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
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id=asset.asset_id
                WHERE asset.project_id=%s AND asset.asset_type=ANY(%s)
                  AND version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                  AND COALESCE(version.content->>'book_id', %s)=%s
                ORDER BY version.created_at DESC, version.version_number DESC
                LIMIT 1
                """,
                [book["project_id"], list(aliases), book["book_id"], book["book_id"]],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def _active_plan(
        self, book: dict[str, Any], contract_type: str, chapter_number: int
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, version.content_hash,
                       version.content, binding.parent_version_id,
                       binding.execution_scope
                FROM active_story_plan_version AS active
                JOIN story_plan_binding AS binding ON binding.binding_id=active.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE active.project_id=%s AND active.book_id=%s
                  AND binding.contract_type=%s AND binding.freshness='CURRENT'
                ORDER BY active.activated_at DESC
                """,
                [book["project_id"], book["book_id"], contract_type],
            )
            rows = uow.cursor.fetchall()
        matches = []
        for row in rows:
            content = dict(row[2])
            if contract_type == "CHAPTER":
                applies = (
                    int(content.get("chapter_number") or content.get("chapter") or 0)
                    == chapter_number
                )
            else:
                chapter_range = content.get("chapter_range") or [
                    chapter_number,
                    chapter_number,
                ]
                applies = (
                    int(chapter_range[0]) <= chapter_number <= int(chapter_range[1])
                )
            if applies:
                matches.append(row)
        if len(matches) > 1:
            raise KernelError(
                "BOOK_SUPERVISOR_ACTIVE_PLAN_AMBIGUOUS",
                f"multiple Active {contract_type} plans cover chapter {chapter_number}",
            )
        if not matches:
            return None
        row = matches[0]
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
            "content": dict(row[2]),
            "parent_version_id": str(row[3] or ""),
            "execution_scope": str(row[4]),
        }

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
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT group_run_id
                FROM authority_chapter_group_production
                WHERE project_id=%s AND book_run_id=%s
                  AND (%s='' OR group_plan_version_id=%s)
                  AND state NOT IN ('COMPLETED','ABORTED','FAILED')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [
                    book["project_id"],
                    book["book_run_id"],
                    group_plan_version,
                    group_plan_version,
                ],
            )
            row = uow.cursor.fetchone()
        return self.chapter_groups.require(str(row[0])) if row is not None else None

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
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT request.chapter_request_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                WHERE acceptance.book_run_id=%s AND acceptance.chapter_number=%s
                  AND NOT EXISTS (
                    SELECT 1 FROM authority_book_volume_checkpoint AS checkpoint
                    WHERE checkpoint.book_run_id=acceptance.book_run_id
                      AND checkpoint.accepted_through_chapter=acceptance.chapter_number
                  )
                """,
                [book["book_run_id"], chapter],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return self.checkpoints.record_after_acceptance(
            book_run_id=str(book["book_run_id"]),
            chapter_request_id=str(row[0]),
            principal=self.principal,
        )

    def _snapshot(self, book: dict[str, Any]) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book_plan_version, current_volume_plan_version,
                       active_arc_plan_versions, character_state_version,
                       foreshadowing_state_version, quality_trend_version,
                       reward_ledger_version, promise_ledger_version
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s
                """,
                [book["input_snapshot_id"]],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_INPUT_SNAPSHOT_MISSING", "Book input snapshot vanished"
            )
        keys = (
            "book_plan_version",
            "current_volume_plan_version",
            "active_arc_plan_versions",
            "character_state_version",
            "foreshadowing_state_version",
            "quality_trend_version",
            "reward_ledger_version",
            "promise_ledger_version",
        )
        return dict(zip(keys, row, strict=True))

    def _chapter_execution_plan(
        self, planning_binding: dict[str, Any]
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash,
                       version.content
                FROM authority_operation_output_asset AS output
                JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=output.operation_id
                WHERE operation.project_id=%s
                  AND operation.status='SUCCEEDED'
                  AND asset.asset_type='chapter_plan'
                  AND output.output_key='story_planning.chapter_plan_projection'
                  AND version.content->>'source_planning_candidate_asset_version_id'=%s
                ORDER BY version.created_at DESC
                LIMIT 2
                """,
                [
                    self._project_for_plan(
                        str(planning_binding["asset_version_id"])
                    ),
                    str(planning_binding["asset_version_id"]),
                ],
            )
            rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "BOOK_SUPERVISOR_CHAPTER_PLAN_PROJECTION_INVALID",
                "Active Chapter plan requires one typed Planning projection",
            )
        return {
            "asset_version_id": str(rows[0][0]),
            "content_hash": str(rows[0][1]),
            "content": dict(rows[0][2]),
        }

    def _project_for_plan(self, asset_version_id: str) -> str:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_SUPERVISOR_CHAPTER_PLAN_MISSING",
                "Active Chapter plan AssetVersion does not exist",
            )
        return str(row[0])

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

    def _set_state(self, book: dict[str, Any], state: BookProductionState) -> str:
        definition_name = "book.supervisor.checkpoint.advance"
        handler_key = "novel_forge.book.supervisor.checkpoint.advance"
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.repositories.definitions.register(
                _supervisor_checkpoint_definition(
                    application_build_id=self.authority.application_build_id,
                    commit_sha=self.authority.commit_sha,
                )
            )
            uow.commit()

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                UPDATE authority_book_production
                SET state=%s, version=version+1, updated_at=NOW()
                WHERE book_run_id=%s AND version=%s
                """,
                [state.value, book["book_run_id"], book["version"]],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_SUPERVISOR_CHECKPOINT_CONFLICT",
                    "Book checkpoint changed during Supervisor Tick",
                )
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "book_production_supervisor",
                    "aggregate_id": str(book["book_run_id"]),
                    "operation_id": operation_id,
                    "project_id": str(book["project_id"]),
                    "event_type": "book.supervisor.checkpoint.advanced",
                    "correlation_id": str(book["root_operation_id"]),
                    "causation_id": str(book["root_operation_id"]),
                    "payload": {
                        "operation_id": operation_id,
                        "book_run_id": str(book["book_run_id"]),
                        "previous_state": str(book["state"]),
                        "state": state.value,
                        "expected_version": int(book["version"]),
                    },
                }
            )
            checkpoint("after_outbox_insert")
            return {"state": state.value}

        result = execute_transaction_command(
            self.authority.database_url,
            {
                "definition_name": definition_name,
                "definition_version": "1.0.0",
                "project_id": str(book["project_id"]),
                "workspace_id": str(book["workspace_id"]),
                "book_id": str(book["book_id"]),
                "actor_id": self.principal.principal_id,
                "idempotency_scope": "book:production-supervisor",
                "idempotency_key": (
                    f"{book['stable_idempotency_key']}:supervisor-state:"
                    f"{book['version']}:{state.value}"
                ),
                "trace_id": f"{book['root_operation_id']}:supervisor:{state.value}",
                "span_id": str(uuid4()),
                "correlation_id": str(book["root_operation_id"]),
                "causation_id": str(book["root_operation_id"]),
                "causation_operation_id": str(book["root_operation_id"]),
                "input": {
                    "book_run_id": str(book["book_run_id"]),
                    "expected_version": int(book["version"]),
                    "previous_state": str(book["state"]),
                    "state": state.value,
                },
                "input_assets": [],
            },
            context=AdmissionContext(
                actor_id=self.principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({handler_key}),
                application_build_id=self.authority.application_build_id,
                commit_sha=self.authority.commit_sha,
            ),
            handler=handler,
        )
        return str(result["operation_id"])

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



def _supervisor_checkpoint_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": "book.supervisor.checkpoint.advance",
        "definition_version": "1.0.0",
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "book.supervisor.checkpoint.command.v1",
        "result_schema_version": "book.supervisor.checkpoint.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "BookProductionBusinessCheckpoint"},
        "handler_key": "novel_forge.book.supervisor.checkpoint.advance",
        "handler_contract_version": "book-supervisor-checkpoint-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "attempt_runtime_owner": "COMMAND_KERNEL",
            "business_state_only": True,
        },
        "idempotency_scope": "book:production-supervisor",
        "concurrency_key_template": "book:{book_id}:production-supervisor",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {"supported": False, "reason": "CAS checkpoint"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "completion_contract": {
            "version": "book-supervisor-checkpoint-completion-v1",
            "required_evidence": ["trace", "audit", "book_checkpoint"],
        },
    }


__all__ = ["BookProductionSupervisorTick", "PostgresBookProductionSupervisor"]
