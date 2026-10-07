from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
)
from novel_forge.modules.authority_security import Principal

if TYPE_CHECKING:
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
from .policy import PostgresChapterGroupExecutionPolicyAuthority


DEFINITION_VERSION = "1.0.0"
REPLAN_RETIREMENT_VERSION = "1.1.0"
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
    def __init__(self, database_url: str = "") -> None:
        self.database_url = database_url

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "CHAPTER_GROUP_STEP_INPUT_INVALID",
                "ChapterGroup step payload must be an object",
            )
        if request.definition_name=="chapter_group.production.supersede" and request.definition_version==REPLAN_RETIREMENT_VERSION:
            from .replan_retirement import require_replan_retirement
            with AuthorityUnitOfWork(self.database_url) as uow:
                require_replan_retirement(uow.cursor,project_id=request.project_id,payload=payload,current_operation_id=request.operation_id)
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
    def __init__(self, database_url: str = "") -> None:
        self._registrations: dict[tuple[str, str], AuthorityHandlerRegistration] = {}
        handler = _StepHandler(database_url)
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

        registration=self._registrations[("chapter_group.production.supersede",DEFINITION_VERSION)]
        from dataclasses import replace
        self._registrations[("chapter_group.production.supersede",REPLAN_RETIREMENT_VERSION)] = replace(registration,definition_version=REPLAN_RETIREMENT_VERSION)

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
        self.registry = _Registry(database_url)
        self.execution_policies = PostgresChapterGroupExecutionPolicyAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )

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
        execution_policy = self.execution_policies.freeze_for_book(
            project_id=command.project_id,
            book_run_id=command.book_run_id,
            actor_id=principal.principal_id,
        )
        if chapter_range.count > execution_policy["policy"]["maximum_chapters"]:
            raise KernelError(
                "CHAPTER_GROUP_EXECUTION_POLICY_LIMIT",
                "ChapterGroup exceeds the frozen Book execution window policy",
            )
        from novel_forge.modules.story_design_authority.qualification import uses_work_requirements

        validate_chapter_function_matrix(
            list(content["chapter_function_matrix"]),
            group_objective=str(content["local_objective"]),
            work_requirements=uses_work_requirements(content),
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
                    "payload": {
                        **asdict(command),
                        "execution_policy_snapshot": execution_policy,
                    },
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
                    "execution_policy_snapshot": Jsonb(execution_policy),
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
        from novel_forge.modules.book_authority.production import (
            SubmitBookChapterCommand,
        )

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

    def recover_dispatch(self, group_run_id: str, *, principal: Principal) -> dict[str, Any]:
        group = self.require(group_run_id)
        principal.require("book.authority.execute", group["project_id"])
        with AuthorityUnitOfWork(self.database_url) as guard:
            guard.cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))",
                ["chapter-group-dispatch-recovery:" + group["book_run_id"]])
            if not guard.cursor.fetchone()[0]:
                raise KernelError("CHAPTER_GROUP_DISPATCH_RECOVERY_CONFLICT", "another recovery owns this Book dispatch")
            group = self.require(group_run_id)
            book = self.book.require(group["book_run_id"])
            request_id = str(book.get("active_chapter_request_id") or "")
            if not request_id:
                raise KernelError("CHAPTER_GROUP_DISPATCH_RECOVERY_STALE", "Book no longer has the reserved Chapter request")
            request = self.book.require_chapter_request(request_id)
            self._require_recoverable_dispatch(group, book, request)
            if group.get("active_chapter_request_id"):
                self._require_dispatch_link(guard.cursor, group, request)
                return group
            chapter = int(request["chapter_number"])
            payload = request["command_payload"]
            self._chapter_plan(group["project_id"], request["chapter_plan_version"], group["group_plan_version_id"], chapter)
            if not self._existing_dispatch_step(guard.cursor, group, request):
                self._run_step(group, definition="chapter_group.chapter.dispatch", suffix=f"chapter:{chapter}",
                    ordinal=100 + chapter * 10, payload={"chapter_number": chapter},
                    input_assets=({"asset_version_id": request["chapter_plan_version"],
                        "content_hash": payload["chapter_plan_content_hash"]},), principal=principal)
            recovered = self.book.recover_chapter_submission(request_id, principal=principal)
            if not recovered.get("chapter_root_operation_id") or not recovered.get("delegation_id"):
                raise KernelError("CHAPTER_GROUP_DELEGATION_MISSING", "recovered Chapter requires its native root and delegation")
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute("SELECT to_jsonb(book) FROM authority_book_production book WHERE book_run_id=%s FOR UPDATE",
                    [group["book_run_id"]])
                current_book = uow.cursor.fetchone()[0]
                uow.cursor.execute("SELECT group_run_id FROM authority_chapter_group_production WHERE group_run_id=%s FOR UPDATE",
                    [group_run_id])
                current_group = uow.repositories.chapter_group.require(group_run_id)
                self._require_recoverable_dispatch(current_group, current_book, recovered)
                if current_group.get("active_chapter_request_id"):
                    self._require_dispatch_link(uow.cursor, current_group, recovered)
                else:
                    uow.repositories.chapter_group.link_chapter(group_run_id=group_run_id,
                        project_id=group["project_id"], chapter_number=chapter,
                        chapter_plan_version_id=request["chapter_plan_version"], chapter_request_id=request_id,
                        child_root_operation_id=recovered["chapter_root_operation_id"], child_delegation_id=recovered["delegation_id"])
                    self._require_dispatch_link(uow.cursor, current_group, recovered)
                uow.commit()
        return self.require(group_run_id)

    @staticmethod
    def _existing_dispatch_step(cursor: Any, group: dict[str, Any], request: dict[str, Any]) -> bool:
        chapter = int(request["chapter_number"])
        definition = "chapter_group.chapter.dispatch"
        cursor.execute("""SELECT to_jsonb(operation),to_jsonb(step) FROM authority_operation operation
            LEFT JOIN authority_saga_step step ON step.operation_id=operation.operation_id
            WHERE operation.project_id=%s AND operation.idempotency_scope='project:chapter-group-step'
              AND operation.idempotency_key=%s""",
            [group["project_id"], f"{group['stable_idempotency_key']}:{definition}:chapter:{chapter}"])
        row = cursor.fetchone()
        if row is None:
            return False
        operation, step = row
        if operation["status"] != "SUCCEEDED" or not step:
            raise KernelError("CHAPTER_GROUP_DISPATCH_REQUIRES_RECOVERY", "The existing dispatch step must finish native recovery before linkage")
        expected = {"project_id": group["project_id"], "input_asset_version_ids": [request["chapter_plan_version"]],
            "payload": {"group_run_id": group["group_run_id"], "chapter_number": chapter}}
        refs = operation.get("input_asset_snapshot") or []
        if (operation["definition_name"] != definition or operation["command_payload"] != expected
            or any(operation.get(key) != group["root_operation_id"] for key in ("root_operation_id", "parent_operation_id", "causation_operation_id"))
            or operation.get("saga_id") != group["saga_id"] or step["saga_id"] != group["saga_id"]
            or step["step_key"] != f"{definition}:chapter:{chapter}" or step["ordinal"] != 100 + chapter * 10
            or [(item.get("asset_version_id"), item.get("content_hash")) for item in refs]
                != [(request["chapter_plan_version"], request["command_payload"]["chapter_plan_content_hash"])]
            or any(item.get("project_id", group["project_id"]) != group["project_id"] for item in refs)):
            raise KernelError("CHAPTER_GROUP_DISPATCH_RECOVERY_CONFLICT", "Existing dispatch step differs from its frozen group and Chapter inputs")
        return True

    @staticmethod
    def _require_recoverable_dispatch(group: dict[str, Any], book: dict[str, Any], request: dict[str, Any]) -> None:
        payload = request.get("command_payload") or {}
        if (group["book_run_id"] != book["book_run_id"] or request["book_run_id"] != book["book_run_id"]
            or group["project_id"] != book["project_id"] or request["project_id"] != book["project_id"]
            or request["chapter_request_id"] != book.get("active_chapter_request_id")
            or request.get("parent_group_version_id") != group["group_plan_version_id"]
            or payload.get("parent_group_version_id") != group["group_plan_version_id"]
            or payload.get("book_run_id") != group["book_run_id"]
            or int(request["chapter_number"]) != int(group["accepted_through_chapter"]) + 1
            or int(request["chapter_number"]) != int(book["accepted_through_chapter"]) + 1
            or not int(group["chapter_start"]) <= int(request["chapter_number"]) <= int(group["chapter_end"])
            or book["state"] in {"PAUSED", "ABORTED", "COMPLETED"}):
            raise KernelError("CHAPTER_GROUP_DISPATCH_RECOVERY_STALE", "reserved Chapter differs from the exact active Book and group boundary")
        active = group.get("active_chapter_request_id")
        if (active and (active != request["chapter_request_id"] or group["state"] != ChapterGroupState.CHAPTER_RUNNING.value)
            or not active and group["state"] != ChapterGroupState.READY.value):
            raise KernelError("CHAPTER_GROUP_DISPATCH_RECOVERY_CONFLICT", "ChapterGroup cannot recover this reserved dispatch")

    @staticmethod
    def _require_dispatch_link(cursor: Any, group: dict[str, Any], request: dict[str, Any]) -> None:
        cursor.execute("""SELECT project_id,chapter_plan_version_id,chapter_request_id,child_root_operation_id,child_delegation_id
            FROM authority_chapter_group_chapter WHERE group_run_id=%s AND chapter_number=%s""",
            [group["group_run_id"], request["chapter_number"]])
        if cursor.fetchone() != (group["project_id"], request["chapter_plan_version"], request["chapter_request_id"],
                                request["chapter_root_operation_id"], request["delegation_id"]):
            raise KernelError("CHAPTER_GROUP_DISPATCH_RECOVERY_CONFLICT", "existing group dispatch has a different immutable child binding")

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
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.chapter_group.record_child_status(
                group_run_id=group_run_id,
                chapter_number=chapter,
                status=str(request["status_reference"]),
            )
            uow.commit()
        if request["status_reference"] != "SUCCEEDED":
            return self.require(group_run_id)
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
        self.book.resume(
            group["book_run_id"], reason=reason, principal=principal
        )
        target = (
            ChapterGroupState.CHAPTER_RUNNING.value
            if group["active_chapter_request_id"]
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
        payload={"reason":reason,"group_run_id":group_run_id,"replan_id":replan_id,
            "retired_group_plan_version_id":target_group_plan_version_id,"expected_group_version":int(group["version"])}
        from .replan_retirement import require_replan_retirement
        with AuthorityUnitOfWork(self.database_url) as uow:
            impact=require_replan_retirement(uow.cursor,project_id=group["project_id"],payload=payload)
        payload.update(plan_change_impact_id=impact[0],plan_change_proposal_id=impact[1],approval_operation_id=impact[2],activation_operation_id=impact[3])
        retirement_operation_id = self._run_step(group,definition="chapter_group.production.supersede",definition_version=REPLAN_RETIREMENT_VERSION,
            suffix=f"version:{group['version']}:approved-impact:{impact[0]}",ordinal=10000+int(group["version"]),
            payload=payload,input_assets=(),principal=principal)
        self._request_root_cancellation(group, reason=reason, principal=principal)
        with AuthorityUnitOfWork(self.database_url) as uow:
            final_impact = require_replan_retirement(uow.cursor,project_id=group["project_id"],payload=payload,
                retirement_operation_id=retirement_operation_id)
            if final_impact != impact:
                raise KernelError("CHAPTER_GROUP_REPLAN_IMPACT_DRIFT","Approved retirement evidence changed before final mutation")
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
        definition_version: str = DEFINITION_VERSION,
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
                "definition_version": definition_version,
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
            from novel_forge.storage.book_edition_repositories import BookEditionRepository
            uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [group["book_id"]])
            editions = BookEditionRepository(uow.cursor)
            head = editions.head(group["book_id"])
            advances_selected_scope = True
            if head["version"]:
                proofs = [event["content"] for event in editions.events(head["selected_revision_id"]) if event["event_kind"] == "VALIDATED"]
                selected_run = (proofs[-1].get("validation_book_run_id") or proofs[-1].get("source_book_run_id")) if proofs else ""
                advances_selected_scope = selected_run == group["book_run_id"]
            uow.repositories.chapter_group.close(
                group_run_id=group["group_run_id"],
            )
            horizon_id = None
            if advances_selected_scope:
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
                        "planning_horizon_advanced": advances_selected_scope,
                    },
                }
            )
            uow.commit()

    def _production_closure_inputs(self, group: dict[str, Any]) -> dict[str, Any]:
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
            uow.repositories.definitions.register(_definition("chapter_group.production.supersede",
                application_build_id=self.application_build_id,commit_sha=self.commit_sha,definition_version=REPLAN_RETIREMENT_VERSION))
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
    name: str, *, application_build_id: str, commit_sha: str, definition_version: str = DEFINITION_VERSION
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
        "definition_version": definition_version,
        "family": "chapter_group_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending" if definition_version==REPLAN_RETIREMENT_VERSION else "integration_proven",
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
