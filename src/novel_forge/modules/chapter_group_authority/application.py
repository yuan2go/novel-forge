from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority.production import (
    PostgresBookAuthority,
    SubmitBookChapterCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    coordinate_saga,
    register_saga_step,
    start_saga,
    transition_saga_gate,
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
from novel_forge.modules.hierarchical_planning import validate_chapter_function_matrix
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    ChapterGroupRange,
    ChapterGroupState,
    require_next_chapter,
    state_after_acceptance,
)


DEFINITION_VERSION = "1.0.0"
ROOT_DEFINITION = "chapter_group.production.run"
STEP_DEFINITIONS = (
    "chapter_group.prepare",
    "chapter_group.plan.resolve",
    "chapter_group.function_matrix.validate",
    "chapter_group.chapter.dispatch",
    "chapter_group.chapter.reconcile",
    "chapter_group.chapter.accept",
    "chapter_group.recap.run",
    "chapter_group.plan_vs_actual.evaluate",
    "chapter_group.plan_adjustment.propose",
    "chapter_group.production.close",
    "chapter_group.production.pause",
    "chapter_group.production.resume",
    "chapter_group.production.supersede",
    "chapter_group.production.cancel",
)
ALL_DEFINITIONS = (ROOT_DEFINITION, *STEP_DEFINITIONS)
HANDLER_PREFIX = "novel_forge.chapter_group_authority"


@dataclass(frozen=True, slots=True)
class StartChapterGroupCommand:
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    stable_idempotency_key: str
    book_run_id: str
    group_plan_version_id: str
    group_plan_content_hash: str


class _StepHandler:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "CHAPTER_GROUP_STEP_INPUT_INVALID",
                "ChapterGroup step payload must be an object",
            )
        sources = tuple(item.asset_version_id for item in request.inputs)
        if request.definition_name == "chapter_group.plan_vs_actual.evaluate":
            asset_type = "plan_vs_actual_report"
            output_key = "chapter_group.plan_vs_actual"
            content = {
                "type": "PlanVsActualReport",
                "contract_version": "chapter-group-plan-vs-actual-v1",
                "group_run_id": str(payload["group_run_id"]),
                "chapter_range": list(payload["chapter_range"]),
                "accepted_chapters": list(payload["accepted_chapters"]),
                "objective_status": str(payload.get("objective_status") or "OBSERVED"),
                "mutation_allowed": False,
            }
        elif request.definition_name == "chapter_group.plan_adjustment.propose":
            asset_type = "group_plan_adjustment_proposal"
            output_key = "chapter_group.adjustment_proposal"
            content = {
                "type": "GroupPlanAdjustmentProposal",
                "contract_version": "group-plan-adjustment-proposal-v1",
                "group_run_id": str(payload["group_run_id"]),
                "source_recap_operation_id": str(payload["source_recap_operation_id"]),
                "source_proposal_version_id": str(
                    payload["source_proposal_version_id"]
                ),
                "target_scope": "FUTURE_ONLY",
                "authority_decision_required": True,
                "active_plan_mutation_allowed": False,
            }
        else:
            asset_type = "chapter_group_step_receipt"
            output_key = "chapter_group.step." + request.definition_name.removeprefix(
                "chapter_group."
            )
            content = {
                "type": "ChapterGroupStepReceipt",
                "contract_version": "chapter-group-step-receipt-v1",
                "group_run_id": str(payload["group_run_id"]),
                "step": request.definition_name,
                "deterministic": True,
                "model_calls": 0,
                "payload": payload,
            }
        return AuthorityHandlerOutput(
            asset_type=asset_type,
            output_key=output_key,
            role="primary",
            content=content,
            qualification_policy="chapter-group-step-v1",
            reference_asset_version_ids=sources,
            evidence={
                "deterministic": True,
                "model_calls": 0,
                "authority_state_mutation": False,
            },
        )


class _Registry:
    def __init__(self) -> None:
        self._registrations: dict[tuple[str, str], AuthorityHandlerRegistration] = {}
        handler = _StepHandler()
        for definition_name in STEP_DEFINITIONS:
            asset_type, output_key = _output_contract(definition_name)
            self._registrations[(definition_name, DEFINITION_VERSION)] = (
                AuthorityHandlerRegistration(
                    definition_name=definition_name,
                    definition_version=DEFINITION_VERSION,
                    handler_key=f"{HANDLER_PREFIX}.{definition_name}",
                    handler_contract_version="chapter-group-step-handler-v1",
                    output_asset_type=asset_type,
                    output_key=output_key,
                    role="primary",
                    completion_topic=f"{definition_name}.completed",
                    handler=handler,
                )
            )

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(
            item.handler_key for item in self._registrations.values()
        ) | frozenset({f"{HANDLER_PREFIX}.{ROOT_DEFINITION}"})

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        return self._registrations[(definition_name, definition_version)]


class PostgresChapterGroupAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        book_authority: PostgresBookAuthority,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "chapter-group-authority-worker",
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "ChapterGroup Authority requires PostgreSQL and build identity"
            )
        self.database_url = database_url
        self.book = book_authority
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.registry = _Registry()

    def start(
        self, command: StartChapterGroupCommand, *, principal: Principal
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", command.project_id)
        book = self.book.require(command.book_run_id)
        if (
            book["project_id"] != command.project_id
            or book["workspace_id"] != command.workspace_id
        ):
            raise KernelError(
                "CHAPTER_GROUP_BOOK_SCOPE_MISMATCH",
                "Book run belongs to another Project or Workspace",
            )
        plan = self._group_plan(command.project_id, command.group_plan_version_id)
        if plan["content_hash"] != command.group_plan_content_hash:
            raise KernelError(
                "CHAPTER_GROUP_PLAN_HASH_MISMATCH",
                "frozen ChapterGroup Plan hash does not match",
            )
        content = dict(plan["content"])
        chapter_range = ChapterGroupRange(*map(int, content["chapter_range"]))
        validate_chapter_function_matrix(
            list(content["chapter_function_matrix"]),
            group_objective=str(content["local_objective"]),
        )
        accepted_through = int(book["accepted_through_chapter"])
        if not chapter_range.start - 1 <= accepted_through < chapter_range.end:
            raise KernelError(
                "CHAPTER_GROUP_BOOK_CURSOR_MISMATCH",
                "Book cursor must be before completion of the ChapterGroup",
            )
        if accepted_through >= chapter_range.start:
            self._require_replacement_group_snapshot(
                book=book,
                group_plan_version_id=command.group_plan_version_id,
            )
        self._register_definitions()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": ROOT_DEFINITION,
                "definition_version": DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:chapter-group-production",
                "idempotency_key": command.stable_idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": str(book["root_operation_id"]),
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": [command.group_plan_version_id],
                    "payload": asdict(command),
                },
                "input_assets": [
                    {
                        "asset_version_id": command.group_plan_version_id,
                        "content_hash": command.group_plan_content_hash,
                    }
                ],
            },
            context=self._admission_context(principal),
        )
        root_operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = uow.repositories.attempt_runtime.operation_state(
                root_operation_id, command.project_id
            )
        if operation["status"] == "ADMITTED":
            for expected, target in (
                ("ADMITTED", "READY"),
                ("READY", "EXECUTING"),
            ):
                with AuthorityUnitOfWork(self.database_url) as uow:
                    current = uow.repositories.attempt_runtime.operation_state(
                        root_operation_id, command.project_id
                    )
                transition_operation(
                    self.database_url,
                    OperationTransitionCommand(
                        operation_id=root_operation_id,
                        project_id=command.project_id,
                        expected_version=int(current["version"]),
                        expected_status=expected,
                        target_status=target,
                        actor_id=principal.principal_id,
                        reason="start governed ChapterGroup production",
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                        causation_id=str(book["root_operation_id"]),
                    ),
                )
        saga_id = str(
            start_saga(
                self.database_url,
                self._context(command.project_id, principal, command),
                root_operation_id=root_operation_id,
            )["saga_id"]
        )
        group_run_id = f"chapter-group-run:{root_operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.create(
                {
                    "group_run_id": group_run_id,
                    "project_id": command.project_id,
                    "book_id": str(book["book_id"]),
                    "book_run_id": command.book_run_id,
                    "group_plan_version_id": command.group_plan_version_id,
                    "volume_plan_version_id": str(plan["parent_version_id"]),
                    "root_operation_id": root_operation_id,
                    "saga_id": saga_id,
                    "stable_idempotency_key": command.stable_idempotency_key,
                    "chapter_start": chapter_range.start,
                    "chapter_end": chapter_range.end,
                    "accepted_through_chapter": accepted_through,
                }
            )
            uow.commit()
        group = self.require(group_run_id)
        inputs = (
            {
                "asset_version_id": command.group_plan_version_id,
                "content_hash": command.group_plan_content_hash,
            },
        )
        for ordinal, definition in enumerate(
            (
                "chapter_group.prepare",
                "chapter_group.plan.resolve",
                "chapter_group.function_matrix.validate",
            ),
            start=1,
        ):
            self._run_step(
                group,
                definition=definition,
                suffix="initial",
                ordinal=ordinal,
                payload={
                    "chapter_range": [
                        chapter_range.start,
                        chapter_range.end,
                    ],
                    "function_matrix": content["chapter_function_matrix"],
                },
                input_assets=inputs,
                principal=principal,
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            current = uow.repositories.chapter_group.require(group_run_id)
            if current["state"] == ChapterGroupState.PREPARING.value:
                uow.repositories.chapter_group.set_state(
                    group_run_id,
                    expected=(ChapterGroupState.PREPARING.value,),
                    target=ChapterGroupState.READY.value,
                )
            uow.commit()
        return self.require(group_run_id)

    def _require_replacement_group_snapshot(
        self,
        *,
        book: dict[str, Any],
        group_plan_version_id: str,
    ) -> None:
        if book["input_mode"] != "RESOLVED_AUTHORITY_INPUT":
            raise KernelError(
                "CHAPTER_GROUP_REPLACEMENT_RESOLVED_INPUT_REQUIRED",
                "an overlapping replacement ChapterGroup requires resolved input",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT current_chapter_group_plan_version
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s
                """,
                [book["input_snapshot_id"]],
            )
            row = uow.cursor.fetchone()
        if row is None or str(row[0] or "") != group_plan_version_id:
            raise KernelError(
                "CHAPTER_GROUP_REPLACEMENT_SNAPSHOT_MISMATCH",
                "replacement ChapterGroup must be bound by the current Book snapshot",
            )

    def dispatch(
        self,
        group_run_id: str,
        command: SubmitBookChapterCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        group = self.require(group_run_id)
        principal.require("book.authority.execute", group["project_id"])
        chapter_range = ChapterGroupRange(
            int(group["chapter_start"]), int(group["chapter_end"])
        )
        require_next_chapter(
            state=ChapterGroupState(str(group["state"])),
            accepted_through=int(group["accepted_through_chapter"]),
            active_chapter=(
                int(group["active_chapter_number"])
                if group["active_chapter_number"] is not None
                else None
            ),
            chapter_number=command.chapter_number,
            chapter_range=chapter_range,
        )
        if command.book_run_id != group["book_run_id"]:
            raise KernelError(
                "CHAPTER_GROUP_BOOK_RUN_MISMATCH",
                "Chapter command targets another Book run",
            )
        self._chapter_plan(
            group["project_id"],
            command.chapter_plan_asset_version_id,
            group["group_plan_version_id"],
            command.chapter_number,
        )
        inputs = (
            {
                "asset_version_id": command.chapter_plan_asset_version_id,
                "content_hash": command.chapter_plan_content_hash,
            },
        )
        self._run_step(
            group,
            definition="chapter_group.chapter.dispatch",
            suffix=f"chapter:{command.chapter_number}",
            ordinal=100 + command.chapter_number * 10,
            payload={"chapter_number": command.chapter_number},
            input_assets=inputs,
            principal=principal,
        )
        request = self.book.submit_chapter(
            SubmitBookChapterCommand(
                **{
                    **asdict(command),
                    "parent_group_version_id": str(group["group_plan_version_id"]),
                }
            ),
            principal=principal,
        )
        if not request["delegation_id"]:
            raise KernelError(
                "CHAPTER_GROUP_DELEGATION_MISSING",
                "Book Authority did not persist the child delegation",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.link_chapter(
                group_run_id=group_run_id,
                project_id=group["project_id"],
                chapter_number=command.chapter_number,
                chapter_plan_version_id=command.chapter_plan_asset_version_id,
                chapter_request_id=str(request["chapter_request_id"]),
                child_root_operation_id=str(request["chapter_root_operation_id"]),
                child_delegation_id=str(request["delegation_id"]),
            )
            uow.commit()
        return self.require(group_run_id)

    def reconcile_and_accept(
        self, group_run_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        group = self.require(group_run_id)
        principal.require("book.authority.execute", group["project_id"])
        request_id = str(group["active_chapter_request_id"] or "")
        if not request_id:
            return group
        request = self.book.reconcile_chapter(request_id)
        chapter = int(request["chapter_number"])
        plan_input = self.book.resolve_asset_refs(
            project_id=group["project_id"],
            asset_version_ids=(str(request["chapter_plan_version"]),),
        )
        self._run_step(
            group,
            definition="chapter_group.chapter.reconcile",
            suffix=f"chapter:{chapter}",
            ordinal=101 + chapter * 10,
            payload={
                "chapter_number": chapter,
                "child_status": request["status_reference"],
            },
            input_assets=plan_input,
            principal=principal,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.record_child_status(
                group_run_id=group_run_id,
                chapter_number=chapter,
                status=str(request["status_reference"]),
            )
            uow.commit()
        if request["status_reference"] != "SUCCEEDED":
            return self.require(group_run_id)
        accepted = self.book.accept_chapter(request_id, principal=principal)
        acceptance_operation_id = str(accepted["acceptance_operation_id"])
        outcome_version = str(accepted["last_chapter_outcome_version_id"])
        accept_inputs = self.book.resolve_asset_refs(
            project_id=group["project_id"],
            asset_version_ids=(outcome_version,),
        )
        self._run_step(
            group,
            definition="chapter_group.chapter.accept",
            suffix=f"chapter:{chapter}",
            ordinal=102 + chapter * 10,
            payload={
                "chapter_number": chapter,
                "acceptance_operation_id": acceptance_operation_id,
                "chapter_outcome_version_id": outcome_version,
            },
            input_assets=accept_inputs,
            principal=principal,
        )
        target = state_after_acceptance(
            chapter_number=chapter,
            chapter_range=ChapterGroupRange(
                int(group["chapter_start"]), int(group["chapter_end"])
            ),
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.accept_chapter(
                group_run_id=group_run_id,
                chapter_number=chapter,
                acceptance_operation_id=acceptance_operation_id,
                chapter_outcome_version_id=outcome_version,
                target_state=target.value,
            )
            uow.commit()
        return self.require(group_run_id)

    def close(self, group_run_id: str, *, principal: Principal) -> dict[str, Any]:
        group = self.require(group_run_id)
        principal.require("book.authority.execute", group["project_id"])
        if group["state"] != ChapterGroupState.CLOSURE_PENDING.value:
            raise KernelError(
                "CHAPTER_GROUP_CLOSURE_NOT_READY",
                "all Chapters must be accepted before closure",
            )
        closure = self._production_closure_inputs(group)
        common_inputs = self.book.resolve_asset_refs(
            project_id=group["project_id"],
            asset_version_ids=closure["asset_version_ids"],
        )
        close_operation = self._run_step(
            group,
            definition="chapter_group.production.close",
            suffix="close",
            ordinal=9001,
            payload={
                "chapter_range": [
                    group["chapter_start"],
                    group["chapter_end"],
                ],
                "accepted_chapters": closure["accepted_chapters"],
                "accepted_outcome_versions": closure["accepted_outcome_versions"],
                "story_state_versions": closure["story_state_versions"],
                "canon_snapshot_versions": closure["canon_snapshot_versions"],
                "production_correctness_committed": True,
                "retrospective_completion_required": False,
            },
            input_assets=common_inputs,
            principal=principal,
        )
        book = self.book.require(group["book_run_id"])
        self._commit_close(
            group,
            close_operation_id=close_operation,
            book=book,
        )
        coordinate_saga(
            self.database_url,
            self._group_context(group, principal),
            str(group["saga_id"]),
        )
        return self.require(group_run_id)

    def pause(
        self, group_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        group = self.require(group_run_id)
        self._control_step(group, "pause", reason, principal)
        self.book.pause(group["book_run_id"], reason=reason, principal=principal)
        transition_saga_gate(
            self.database_url,
            self._group_context(group, principal),
            str(group["saga_id"]),
            target_status="WAITING_GATE",
            reason=reason or "operator paused ChapterGroup",
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.set_state(
                group_run_id,
                expected=(
                    ChapterGroupState.READY.value,
                    ChapterGroupState.CHAPTER_RUNNING.value,
                ),
                target=ChapterGroupState.PAUSED.value,
            )
            uow.commit()
        return self.require(group_run_id)

    def resume(
        self, group_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        group = self.require(group_run_id)
        transition_saga_gate(
            self.database_url,
            self._group_context(group, principal),
            str(group["saga_id"]),
            target_status="RUNNING",
            reason=reason or "operator resumed ChapterGroup",
        )
        self._control_step(group, "resume", reason, principal)
        book = self.book.resume(
            group["book_run_id"], reason=reason, principal=principal
        )
        target = (
            ChapterGroupState.CHAPTER_RUNNING.value
            if book["active_chapter_request_id"]
            else ChapterGroupState.READY.value
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.set_state(
                group_run_id,
                expected=(ChapterGroupState.PAUSED.value,),
                target=target,
            )
            uow.commit()
        return self.require(group_run_id)

    def cancel(
        self, group_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        group = self.require(group_run_id)
        if group["state"] in {
            ChapterGroupState.COMPLETED.value,
            ChapterGroupState.ABORTED.value,
        }:
            return group
        self._control_step(group, "cancel", reason, principal)
        self.book.cancel(group["book_run_id"], reason=reason, principal=principal)
        self._request_root_cancellation(group, reason=reason, principal=principal)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.set_state(
                group_run_id,
                expected=(
                    ChapterGroupState.PREPARING.value,
                    ChapterGroupState.READY.value,
                    ChapterGroupState.CHAPTER_RUNNING.value,
                    ChapterGroupState.CLOSURE_PENDING.value,
                    ChapterGroupState.PAUSED.value,
                    ChapterGroupState.FAILED.value,
                ),
                target=ChapterGroupState.ABORTED.value,
                failure_reason=reason,
            )
            uow.commit()
        return self.require(group_run_id)

    def supersede_for_approved_replan(
        self,
        group_run_id: str,
        *,
        replan_id: str,
        target_group_plan_version_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        group = self.require(group_run_id)
        if group["state"] in {
            ChapterGroupState.COMPLETED.value,
            ChapterGroupState.ABORTED.value,
            ChapterGroupState.FAILED.value,
        }:
            return group
        principal.require("book.authority.execute", str(group["project_id"]))
        if str(group["group_plan_version_id"]) != target_group_plan_version_id:
            raise KernelError(
                "CHAPTER_GROUP_REPLAN_TARGET_MISMATCH",
                "approved Replan target does not match the active ChapterGroup",
            )
        if group["active_chapter_request_id"] is not None:
            raise KernelError(
                "CHAPTER_GROUP_REPLAN_ACTIVE_CHILD",
                "approved Replan cannot supersede a ChapterGroup with an active child",
            )
        reason = f"superseded by approved Book Replan {replan_id}"
        self._control_step(group, "supersede", reason, principal)
        self._request_root_cancellation(group, reason=reason, principal=principal)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.set_state(
                group_run_id,
                expected=(
                    ChapterGroupState.PREPARING.value,
                    ChapterGroupState.READY.value,
                    ChapterGroupState.CLOSURE_PENDING.value,
                    ChapterGroupState.PAUSED.value,
                ),
                target=ChapterGroupState.ABORTED.value,
                failure_reason=reason,
            )
            uow.commit()
        return self.require(group_run_id)

    def require(self, group_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.chapter_group.require(group_run_id)

    def _run_step(
        self,
        group: dict[str, Any],
        *,
        definition: str,
        suffix: str,
        ordinal: int,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
        principal: Principal,
    ) -> str:
        if definition not in STEP_DEFINITIONS:
            raise ValueError(f"unsupported ChapterGroup step: {definition}")
        command_payload = {
            "group_run_id": group["group_run_id"],
            **payload,
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition,
                "definition_version": DEFINITION_VERSION,
                "project_id": group["project_id"],
                "workspace_id": self.book.require(group["book_run_id"])["workspace_id"],
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:chapter-group-step",
                "idempotency_key": (
                    f"{group['stable_idempotency_key']}:{definition}:{suffix}"
                ),
                "trace_id": f"{group['root_operation_id']}:{definition}",
                "span_id": str(uuid4()),
                "correlation_id": str(group["root_operation_id"]),
                "causation_id": str(group["root_operation_id"]),
                "input": {
                    "project_id": group["project_id"],
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": command_payload,
                },
                "input_assets": list(input_assets),
                "root_operation_id": group["root_operation_id"],
                "parent_operation_id": group["root_operation_id"],
                "causation_operation_id": group["root_operation_id"],
            },
            context=self._admission_context(principal),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, group["project_id"]
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=group["project_id"],
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="ChapterGroup step inputs frozen",
                    trace_id=f"{group['root_operation_id']}:{definition}",
                    correlation_id=str(group["root_operation_id"]),
                    causation_id=str(group["root_operation_id"]),
                ),
            )
            register_saga_step(
                self.database_url,
                self._group_context(group, principal),
                str(group["saga_id"]),
                operation_id,
                f"{definition}:{suffix}",
                ordinal,
                "",
            )
        ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=operation_id,
            project_id=group["project_id"],
        )
        return operation_id

    def _commit_close(
        self,
        group: dict[str, Any],
        *,
        close_operation_id: str,
        book: dict[str, Any],
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.close(
                group_run_id=group["group_run_id"],
            )
            uow.cursor.execute(
                """
                UPDATE planning_horizon
                SET status='SUPERSEDED', updated_at=NOW()
                WHERE project_id=%s AND book_id=%s AND status='CURRENT'
                """,
                [group["project_id"], group["book_id"]],
            )
            uow.cursor.execute(
                """
                SELECT COALESCE(MAX(window_version), 0) + 1
                FROM planning_horizon
                WHERE project_id=%s AND book_id=%s
                """,
                [group["project_id"], group["book_id"]],
            )
            window_version = int(uow.cursor.fetchone()[0])
            end = int(group["chapter_end"])
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.contract_type='CHAPTER'
                ORDER BY binding.created_at DESC LIMIT 1
                """,
                [group["project_id"], group["book_id"]],
            )
            chapter = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT jsonb_agg(source_asset_version_id)
                FROM asset_dependency_edge
                WHERE project_id=%s AND book_id=%s
                  AND dependent_asset_version_id=%s
                  AND dependency_type='ARC_CONTRIBUTION'
                """,
                [
                    group["project_id"],
                    group["book_id"],
                    str(chapter[0]) if chapter else group["group_plan_version_id"],
                ],
            )
            arcs = uow.cursor.fetchone()[0] or []
            horizon_id = (
                "planning-horizon:"
                + hashlib.sha256(
                    (
                        f"{group['project_id']}:{group['book_id']}:{window_version}"
                    ).encode()
                ).hexdigest()
            )
            uow.cursor.execute(
                """
                INSERT INTO planning_horizon(
                    planning_horizon_id, project_id, book_id,
                    executed_through_chapter, frozen_through_chapter,
                    planned_through_chapter, speculative_through_chapter,
                    active_book_plan_version_id,
                    active_volume_plan_version_id,
                    active_group_plan_version_id,
                    active_chapter_plan_version_id, active_arc_ids,
                    window_version, based_on_canon_version,
                    based_on_story_state_version, policy_version, status,
                    updated_by_operation_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, 'rolling-horizon-v1', 'CURRENT', %s
                )
                """,
                [
                    horizon_id,
                    group["project_id"],
                    group["book_id"],
                    end,
                    end,
                    end + 7,
                    end + 20,
                    book["book_plan_version"],
                    group["volume_plan_version_id"],
                    group["group_plan_version_id"],
                    str(chapter[0]) if chapter else None,
                    Jsonb(list(arcs)),
                    window_version,
                    book["active_canon_snapshot_version_id"],
                    book["active_story_state_version_id"],
                    close_operation_id,
                ],
            )
            event_id = str(uuid4())
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": event_id,
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "chapter_group_production",
                    "aggregate_id": group["group_run_id"],
                    "operation_id": close_operation_id,
                    "project_id": group["project_id"],
                    "event_type": "chapter_group.production.closed",
                    "correlation_id": str(group["root_operation_id"]),
                    "causation_id": close_operation_id,
                    "payload": {
                        "group_run_id": group["group_run_id"],
                        "production_correctness_committed": True,
                        "retrospective_completion_required": False,
                        "planning_horizon_id": horizon_id,
                    },
                }
            )
            uow.commit()

    def _production_closure_inputs(
        self, group: dict[str, Any]
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT child.chapter_number, child.status,
                       acceptance.chapter_outcome_asset_version_id,
                       acceptance.story_state_asset_version_id,
                       acceptance.canon_snapshot_asset_version_id,
                       acceptance.status
                FROM authority_chapter_group_chapter AS child
                LEFT JOIN authority_book_chapter_acceptance AS acceptance
                  ON acceptance.chapter_request_id=child.chapter_request_id
                WHERE child.group_run_id=%s
                ORDER BY child.chapter_number
                """,
                [group["group_run_id"]],
            )
            rows = tuple(uow.cursor.fetchall())
        expected = tuple(
            range(int(group["chapter_start"]), int(group["chapter_end"]) + 1)
        )
        accepted = tuple(int(row[0]) for row in rows)
        if (
            accepted != expected
            or any(str(row[1]) != "ACCEPTED" for row in rows)
            or any(str(row[5]) != "COMMITTED" for row in rows)
            or any(not row[index] for row in rows for index in (2, 3, 4))
        ):
            raise KernelError(
                "CHAPTER_GROUP_PRODUCTION_CORRECTNESS_NOT_COMMITTED",
                "closure requires every Chapter AcceptedOutcome, Story State, and Canon commit",
            )
        outcomes = tuple(str(row[2]) for row in rows)
        states = tuple(str(row[3]) for row in rows)
        canons = tuple(str(row[4]) for row in rows)
        return {
            "accepted_chapters": list(accepted),
            "accepted_outcome_versions": list(outcomes),
            "story_state_versions": list(states),
            "canon_snapshot_versions": list(canons),
            "asset_version_ids": tuple(
                dict.fromkeys(
                    (
                        str(group["group_plan_version_id"]),
                        *outcomes,
                        *states,
                        *canons,
                    )
                )
            ),
        }

    def _group_plan(self, project_id: str, asset_version_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.parent_version_id, binding.execution_scope,
                       binding.freshness, version.content,
                       version.content_hash
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.project_id=%s
                  AND binding.asset_version_id=%s
                  AND binding.contract_type='CHAPTER_GROUP'
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None or str(row[1]) != "FROZEN" or str(row[2]) != "CURRENT":
            raise KernelError(
                "CHAPTER_GROUP_FROZEN_PLAN_REQUIRED",
                "ChapterGroup execution requires a current Frozen plan",
            )
        return {
            "parent_version_id": str(row[0]),
            "content": dict(row[3]),
            "content_hash": str(row[4]),
        }

    def _chapter_plan(
        self,
        project_id: str,
        asset_version_id: str,
        parent_version_id: str,
        chapter_number: int,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.execution_scope, binding.freshness,
                       binding.parent_version_id, version.content
                FROM story_plan_binding AS binding
                JOIN active_story_plan_version AS active
                  ON active.binding_id=binding.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.project_id=%s
                  AND binding.asset_version_id=%s
                  AND binding.contract_type='CHAPTER'
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or str(row[0]) != "FROZEN"
            or str(row[1]) != "CURRENT"
            or str(row[2]) != parent_version_id
            or int((row[3] or {}).get("chapter_number") or 0) != chapter_number
        ):
            raise KernelError(
                "CHAPTER_GROUP_CHAPTER_PLAN_INVALID",
                "dispatch requires a current Frozen ChapterPlan bound to the group",
            )
        return {"content": dict(row[3])}

    def _control_step(
        self,
        group: dict[str, Any],
        action: str,
        reason: str,
        principal: Principal,
    ) -> None:
        inputs = self.book.resolve_asset_refs(
            project_id=group["project_id"],
            asset_version_ids=(group["group_plan_version_id"],),
        )
        self._run_step(
            group,
            definition=f"chapter_group.production.{action}",
            suffix=f"version:{group['version']}",
            ordinal=10000 + int(group["version"]),
            payload={"reason": reason},
            input_assets=inputs,
            principal=principal,
        )

    def _request_root_cancellation(
        self,
        group: dict[str, Any],
        *,
        reason: str,
        principal: Principal,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            root = uow.repositories.attempt_runtime.operation_state(
                str(group["root_operation_id"]), group["project_id"]
            )
        if root["status"] in {
            "CANCELLED",
            "CANCELLATION_REQUESTED",
            "SUCCEEDED",
            "FAILED_FINAL",
            "DEAD_LETTER",
        }:
            return
        request_cancellation(
            self.database_url,
            CancelCommand(
                operation_id=str(group["root_operation_id"]),
                project_id=group["project_id"],
                actor_id=principal.principal_id,
                reason=reason or "ChapterGroup production cancelled",
                expected_version=int(root["version"]),
                idempotency_key=f"{group['stable_idempotency_key']}:cancel-root",
                trace_id=f"{group['root_operation_id']}:cancel",
                correlation_id=str(group["root_operation_id"]),
            ),
        )

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name in ALL_DEFINITIONS:
                uow.repositories.definitions.register(
                    _definition(
                        name,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()

    def _admission_context(self, principal: Principal) -> AdmissionContext:
        return AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"book.authority.execute"}),
            available_handlers=self.registry.available_handler_keys,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    @staticmethod
    def _context(
        project_id: str,
        principal: Principal,
        command: StartChapterGroupCommand,
    ) -> GraphCommandContext:
        return GraphCommandContext(
            project_id,
            principal.principal_id,
            command.trace_id,
            command.correlation_id,
        )

    @staticmethod
    def _group_context(
        group: dict[str, Any], principal: Principal
    ) -> GraphCommandContext:
        return GraphCommandContext(
            group["project_id"],
            principal.principal_id,
            f"{group['root_operation_id']}:trace",
            str(group["root_operation_id"]),
        )


def _output_contract(definition_name: str) -> tuple[str, str]:
    if definition_name == "chapter_group.plan_vs_actual.evaluate":
        return "plan_vs_actual_report", "chapter_group.plan_vs_actual"
    if definition_name == "chapter_group.plan_adjustment.propose":
        return (
            "group_plan_adjustment_proposal",
            "chapter_group.adjustment_proposal",
        )
    return (
        "chapter_group_step_receipt",
        "chapter_group.step." + definition_name.removeprefix("chapter_group."),
    )


def _definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    is_root = name == ROOT_DEFINITION
    asset_type, output_key = (
        ("chapter_group_checkpoint", "chapter_group.checkpoint")
        if is_root
        else _output_contract(name)
    )
    return {
        "name": name,
        "definition_version": DEFINITION_VERSION,
        "family": "chapter_group_authority",
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
        "handler_contract_version": "chapter-group-step-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "saga" if is_root else "worker",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": (
            "project:chapter-group-production"
            if is_root
            else "project:chapter-group-step"
        ),
        "concurrency_key_template": "project:{project_id}:chapter-group",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 86400 if is_root else 120},
        "cancellation_policy": {
            "mode": "cancel_children" if is_root else "cancel_active_attempt"
        },
        "compensation_policy": {
            "supported": False,
            "reason": "append-only references and idempotent child commands",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "chapter_execution_owner": "chapter_authority",
            "book_cursor_owner": "book_authority",
            "group_checkpoint_only": True,
        },
        "completion_contract": (
            {
                "version": "chapter-group-root-completion-v1",
                "required_evidence": ["trace", "audit", "group_checkpoint"],
            }
            if is_root
            else {
                "version": "chapter-group-step-completion-v1",
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
            }
        ),
    }


__all__ = ["PostgresChapterGroupAuthority", "StartChapterGroupCommand"]
