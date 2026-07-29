"""Persistent Book Authority coordinator over the Chapter Authority command port.

Only book checkpoints and Chapter operation references are stored here. Chapter
attempts, leases, fences, effects, outputs, and terminal state remain owned by
Chapter Authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Protocol
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
    BookFollowupAuthorityApplication,
    BookFollowupCommand,
)
from novel_forge.modules.book_followup_authority.contracts import (
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
)
from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSagaAdmission,
    SingleChapterRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    register_saga_step,
    start_saga,
    transition_saga_gate,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


BOOK_COORDINATE_DEFINITION = "book.production.coordinate"
BOOK_COORDINATE_DEFINITION_VERSION = "1.0.0"
BOOK_COORDINATE_HANDLER = "novel_forge.book_authority.coordinator"
LONGFORM_CONTEXT_VERSION_KEYS = frozenset(
    {
        "volume_plan_version",
        "arc_plan_version",
        "character_state_version",
        "foreshadowing_state_version",
        "quality_trend_version",
        "reward_ledger_version",
        "promise_ledger_version",
    }
)


class BookProductionState(StrEnum):
    READY = "READY"
    CHAPTER_SUBMITTED = "CHAPTER_SUBMITTED"
    CHAPTER_RUNNING = "CHAPTER_RUNNING"
    CHAPTER_WAITING_RETRY = "CHAPTER_WAITING_RETRY"
    CHAPTER_COMPLETED = "CHAPTER_COMPLETED"
    CHAPTER_FAILED_RETRYABLE = "CHAPTER_FAILED_RETRYABLE"
    CHAPTER_FAILED_TERMINAL = "CHAPTER_FAILED_TERMINAL"
    CANON_PENDING = "CANON_PENDING"
    CANON_COMMITTED = "CANON_COMMITTED"
    READER_OUTCOME_PENDING = "READER_OUTCOME_PENDING"
    CHECKPOINT_PENDING = "CHECKPOINT_PENDING"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class StartBookProductionCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    stable_idempotency_key: str
    book_design_version: str
    book_plan_version: str
    production_profile_version: str
    longform_context_versions: dict[str, str]
    target_chapter_count: int
    light_recap_cadence: int = 5
    formal_recap_cadence: int = 10


@dataclass(frozen=True, slots=True)
class SubmitBookChapterCommand:
    book_run_id: str
    chapter_number: int
    title: str
    premise: str
    chapter_plan_asset_version_id: str
    chapter_plan_content_hash: str
    context_candidates: tuple[dict[str, Any], ...]
    context_version_refs: dict[str, Any] | None = None
    context_token_budget: int = 6000
    preparation_report: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BookProductionAdmission:
    book_run_id: str
    root_operation_id: str
    saga_id: str
    replayed: bool


class ChapterAuthorityCommandPort(Protocol):
    def submit(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission: ...

    def require_run(
        self, *, project_id: str, root_operation_id: str
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class ChapterAuthorityCommandAdapter:
    application: ChapterAuthorityApplication

    def submit(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission:
        return self.application.admit(request, principal=principal)

    def require_run(
        self, *, project_id: str, root_operation_id: str
    ) -> dict[str, Any]:
        return self.application.query.require_run(
            project_id=project_id, root_operation_id=root_operation_id
        )


def stable_chapter_submission_key(
    *,
    book_id: str,
    book_plan_version: str,
    chapter_number: int,
    chapter_plan_version: str,
    production_profile_version: str,
) -> str:
    if (
        not book_id
        or not book_plan_version
        or chapter_number <= 0
        or not chapter_plan_version
        or not production_profile_version
    ):
        raise ValueError("complete versioned chapter submission identity is required")
    payload = {
        "book_id": book_id,
        "book_plan_version": book_plan_version,
        "chapter_number": chapter_number,
        "chapter_plan_version": chapter_plan_version,
        "production_profile_version": production_profile_version,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"book-chapter:{digest}"


class PostgresBookAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        chapter_port: ChapterAuthorityCommandPort,
        followup_application: BookFollowupAuthorityApplication,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("PostgreSQL, build id, and full commit SHA are required")
        self.database_url = database_url
        self.chapter_port = chapter_port
        self.followup = followup_application
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def start(
        self, command: StartBookProductionCommand, *, principal: Principal
    ) -> BookProductionAdmission:
        principal.require("book.authority.execute", command.project_id)
        _validate_start(command)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                book_coordinate_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        root_input_version_ids = (
            command.book_design_version,
            command.book_plan_version,
            *(
                command.longform_context_versions[key]
                for key in sorted(LONGFORM_CONTEXT_VERSION_KEYS)
            ),
        )
        root_input_assets = self.resolve_asset_refs(
            project_id=command.project_id,
            asset_version_ids=root_input_version_ids,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": BOOK_COORDINATE_DEFINITION,
                "definition_version": BOOK_COORDINATE_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:book-coordinate",
                "idempotency_key": command.stable_idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": list(root_input_version_ids),
                    "payload": asdict(command),
                },
                "input_assets": list(root_input_assets),
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({BOOK_COORDINATE_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        root_operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                root_operation_id, command.project_id
            )
        if state["status"] == "ADMITTED":
            for expected, target in (("ADMITTED", "READY"), ("READY", "EXECUTING")):
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
                        reason="start persistent Book Authority coordination",
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                        causation_id="",
                    ),
                )
        saga_id = str(
            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    principal.principal_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=root_operation_id,
            )["saga_id"]
        )
        book_run_id = f"book-run:{root_operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.book_authority.create_run(
                {
                    "book_run_id": book_run_id,
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "book_id": command.book_id,
                    "book_design_version": command.book_design_version,
                    "book_plan_version": command.book_plan_version,
                    "production_profile_version": command.production_profile_version,
                    "longform_context_versions": command.longform_context_versions,
                    "root_operation_id": root_operation_id,
                    "saga_id": saga_id,
                    "stable_idempotency_key": command.stable_idempotency_key,
                    "target_chapter_count": command.target_chapter_count,
                    "light_recap_cadence": command.light_recap_cadence,
                    "formal_recap_cadence": command.formal_recap_cadence,
                }
            )
            uow.cursor.execute(
                """
                SELECT book_run_id, root_operation_id, saga_id
                FROM authority_book_production
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [command.project_id, command.stable_idempotency_key],
            )
            row = uow.cursor.fetchone()
            uow.commit()
        if row is None or row[1] != root_operation_id:
            raise KernelError(
                "BOOK_AUTHORITY_IDEMPOTENCY_CONFLICT",
                "Book command replay resolved to a different root Operation",
            )
        return BookProductionAdmission(
            book_run_id=str(row[0]),
            root_operation_id=str(row[1]),
            saga_id=str(row[2]),
            replayed=bool(admitted["replayed"]),
        )

    def submit_chapter(
        self, command: SubmitBookChapterCommand, *, principal: Principal
    ) -> dict[str, Any]:
        book = self.require(command.book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        stable_key = stable_chapter_submission_key(
            book_id=book["book_id"],
            book_plan_version=book["book_plan_version"],
            chapter_number=command.chapter_number,
            chapter_plan_version=command.chapter_plan_asset_version_id,
            production_profile_version=book["production_profile_version"],
        )
        if command.chapter_number > int(book["target_chapter_count"]):
            raise KernelError(
                "BOOK_CHAPTER_OUT_OF_RANGE", "chapter exceeds Book target count"
            )
        request_id = f"chapter-request:{stable_key.removeprefix('book-chapter:')}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT chapter_request_id, chapter_root_operation_id
                FROM authority_book_chapter_request
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [book["project_id"], stable_key],
            )
            existing = uow.cursor.fetchone()
            if existing is None:
                uow.repositories.book_authority.create_chapter_request(
                    {
                        "chapter_request_id": request_id,
                        "book_run_id": command.book_run_id,
                        "project_id": book["project_id"],
                        "chapter_number": command.chapter_number,
                        "chapter_plan_version": command.chapter_plan_asset_version_id,
                        "chapter_plan_content_hash": command.chapter_plan_content_hash,
                        "production_profile_version": book[
                            "production_profile_version"
                        ],
                        "stable_idempotency_key": stable_key,
                        "command_payload": asdict(command),
                    }
                )
                if not uow.repositories.book_authority.reserve_chapter(
                    book_run_id=command.book_run_id,
                    chapter_request_id=request_id,
                    chapter_number=command.chapter_number,
                ):
                    raise KernelError(
                        "BOOK_CHAPTER_SUBMISSION_NOT_READY",
                        "Book is not READY for the next sequential Chapter",
                    )
                existing = (request_id, None)
            uow.commit()
        if existing is None:
            raise KernelError("BOOK_CHAPTER_REQUEST_MISSING", "chapter request was not persisted")
        request_id = str(existing[0])
        if existing[1]:
            return self.require_chapter_request(request_id)
        admission = self.chapter_port.submit(
            SingleChapterRequest(
                project_id=book["project_id"],
                workspace_id=book["workspace_id"],
                actor_id=principal.principal_id,
                chapter=command.chapter_number,
                title=command.title,
                premise=command.premise,
                trace_id=f"{book['root_operation_id']}:chapter:{command.chapter_number}",
                correlation_id=book["root_operation_id"],
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
                chapter_plan_asset_version_id=command.chapter_plan_asset_version_id,
                chapter_plan_content_hash=command.chapter_plan_content_hash,
                context_candidates=command.context_candidates,
                context_version_refs=command.context_version_refs,
                context_token_budget=command.context_token_budget,
                preparation_report=command.preparation_report,
                idempotency_key=stable_key,
            ),
            principal=principal,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.book_authority.link_chapter(
                chapter_request_id=request_id,
                book_run_id=command.book_run_id,
                root_operation_id=admission.root_operation_id,
                saga_id=admission.saga_id,
            )
            uow.commit()
        return self.require_chapter_request(request_id)

    def pause(
        self, book_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        book = self.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        if book["state"] in {
            BookProductionState.COMPLETED.value,
            BookProductionState.ABORTED.value,
        }:
            raise KernelError(
                "BOOK_GATE_TERMINAL", "terminal Book production cannot be paused"
            )
        context = self._book_graph_context(book, principal.principal_id)
        transition_saga_gate(
            self.database_url,
            context,
            str(book["saga_id"]),
            target_status="WAITING_GATE",
            reason=reason or "operator pause",
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.book_authority.set_gate_state(
                book_run_id=book_run_id,
                state=BookProductionState.PAUSED.value,
                reason=reason or "operator pause",
            )
            uow.commit()
        return self.require(book_run_id)

    def resume(
        self, book_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        book = self.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        if book["state"] != BookProductionState.PAUSED.value:
            raise KernelError(
                "BOOK_GATE_NOT_PAUSED", "only a paused Book production can resume"
            )
        context = self._book_graph_context(book, principal.principal_id)
        transition_saga_gate(
            self.database_url,
            context,
            str(book["saga_id"]),
            target_status="RUNNING",
            reason=reason or "operator resume",
        )
        next_state = BookProductionState.READY
        active_request_id = str(book["active_chapter_request_id"] or "")
        if active_request_id:
            request = self.require_chapter_request(active_request_id)
            next_state = {
                "SUBMITTING": BookProductionState.CHAPTER_SUBMITTED,
                "ADMITTED": BookProductionState.CHAPTER_SUBMITTED,
                "RUNNING": BookProductionState.CHAPTER_RUNNING,
                "WAITING_RETRY": BookProductionState.CHAPTER_WAITING_RETRY,
                "SUCCEEDED": BookProductionState.CHAPTER_COMPLETED,
                "FAILED_RETRYABLE": BookProductionState.CHAPTER_FAILED_RETRYABLE,
                "FAILED_TERMINAL": BookProductionState.CHAPTER_FAILED_TERMINAL,
            }.get(str(request["status_reference"]), BookProductionState.READY)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.book_authority.set_gate_state(
                book_run_id=book_run_id,
                state=next_state.value,
            )
            uow.commit()
        return self.require(book_run_id)

    def recover_chapter_submission(
        self, chapter_request_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        request = self.require_chapter_request(chapter_request_id)
        if request["chapter_root_operation_id"]:
            return request
        payload = dict(request["command_payload"])
        return self.submit_chapter(
            SubmitBookChapterCommand(
                book_run_id=str(payload["book_run_id"]),
                chapter_number=int(payload["chapter_number"]),
                title=str(payload["title"]),
                premise=str(payload["premise"]),
                chapter_plan_asset_version_id=str(
                    payload["chapter_plan_asset_version_id"]
                ),
                chapter_plan_content_hash=str(payload["chapter_plan_content_hash"]),
                context_candidates=tuple(payload["context_candidates"]),
                context_version_refs=payload.get("context_version_refs"),
                context_token_budget=int(payload.get("context_token_budget") or 6000),
                preparation_report=payload.get("preparation_report"),
            ),
            principal=principal,
        )

    def reconcile_chapter(self, chapter_request_id: str) -> dict[str, Any]:
        request = self.require_chapter_request(chapter_request_id)
        root = request["chapter_root_operation_id"]
        if not root:
            return request
        run = self.chapter_port.require_run(
            project_id=request["project_id"], root_operation_id=root
        )
        operation_status = str(run["status"])
        saga_status = str(run.get("saga", {}).get("status") or "")
        if operation_status == "SUCCEEDED" or saga_status == "SUCCEEDED":
            request_status, book_state = "SUCCEEDED", BookProductionState.CHAPTER_COMPLETED
        elif operation_status == "FAILED_RETRYABLE":
            request_status, book_state = "FAILED_RETRYABLE", BookProductionState.CHAPTER_FAILED_RETRYABLE
        elif operation_status in {"FAILED_FINAL", "DEAD_LETTER"}:
            request_status, book_state = "FAILED_TERMINAL", BookProductionState.CHAPTER_FAILED_TERMINAL
        elif operation_status == "CANCELLED":
            request_status, book_state = "CANCELLED", BookProductionState.PAUSED
        else:
            request_status, book_state = "RUNNING", BookProductionState.CHAPTER_RUNNING
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.book_authority.record_chapter_status(
                chapter_request_id=chapter_request_id,
                book_run_id=request["book_run_id"],
                request_status=request_status,
                book_state=book_state.value,
            )
            uow.commit()
        return self.require_chapter_request(chapter_request_id)

    def schedule_reader_outcome(
        self,
        chapter_request_id: str,
        *,
        principal: Principal,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
    ) -> BookFollowupAdmission:
        return self._schedule_followup(
            chapter_request_id,
            principal=principal,
            definition_name=READER_OUTCOME_DEFINITION,
            followup_type="READER_OUTCOME",
            state=BookProductionState.READER_OUTCOME_PENDING,
            payload=payload,
            input_assets=input_assets,
        )

    def schedule_longform_recap(
        self,
        chapter_request_id: str,
        *,
        principal: Principal,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
    ) -> BookFollowupAdmission:
        return self._schedule_followup(
            chapter_request_id,
            principal=principal,
            definition_name=LONGFORM_RECAP_DEFINITION,
            followup_type="LONGFORM_RECAP",
            state=BookProductionState.CHECKPOINT_PENDING,
            payload=payload,
            input_assets=input_assets,
        )

    def complete_followup(
        self, operation_id: str, *, replan_required: bool = False
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT link.book_run_id, link.followup_type, operation.status,
                       request.chapter_number, book.target_chapter_count,
                       book.saga_id, book.project_id, root.actor_id,
                       root.trace_id, root.correlation_id
                FROM authority_book_followup_operation AS link
                JOIN authority_operation AS operation
                  ON operation.operation_id=link.operation_id
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=link.chapter_request_id
                JOIN authority_book_production AS book
                  ON book.book_run_id=link.book_run_id
                JOIN authority_operation AS root
                  ON root.operation_id=book.root_operation_id
                WHERE link.operation_id=%s
                """,
                [operation_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError("BOOK_FOLLOWUP_NOT_FOUND", "follow-up link does not exist")
            if row[2] != "SUCCEEDED":
                raise KernelError("BOOK_FOLLOWUP_NOT_COMPLETE", f"follow-up Operation is {row[2]}")
            if replan_required:
                state = BookProductionState.REPLAN_REQUIRED
            elif row[1] == "READER_OUTCOME":
                state = BookProductionState.CHAPTER_COMPLETED
            elif int(row[3]) >= int(row[4]):
                state = BookProductionState.COMPLETED
            else:
                state = BookProductionState.READY
            uow.repositories.book_authority.advance(
                book_run_id=str(row[0]),
                chapter_number=int(row[3]),
                state=state.value,
            )
            uow.commit()
        if state is BookProductionState.COMPLETED:
            coordinate_saga(
                self.database_url,
                GraphCommandContext(
                    str(row[6]), str(row[7]), str(row[8]), str(row[9])
                ),
                str(row[5]),
            )
        return self.require(str(row[0]))

    def complete_book_checkpoint(
        self, book_run_id: str, *, chapter_number: int
    ) -> dict[str, Any]:
        """Persist a non-Recap checkpoint and close the root Saga when terminal."""
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.target_chapter_count, book.saga_id, book.project_id,
                       root.actor_id, root.trace_id, root.correlation_id
                FROM authority_book_production AS book
                JOIN authority_operation AS root
                  ON root.operation_id=book.root_operation_id
                WHERE book.book_run_id=%s
                """,
                [book_run_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "BOOK_RUN_NOT_FOUND", "Book Authority run does not exist"
                )
            state = (
                BookProductionState.COMPLETED
                if chapter_number >= int(row[0])
                else BookProductionState.READY
            )
            uow.repositories.book_authority.advance(
                book_run_id=book_run_id,
                chapter_number=chapter_number,
                state=state.value,
            )
            uow.commit()
        if state is BookProductionState.COMPLETED:
            coordinate_saga(
                self.database_url,
                GraphCommandContext(
                    str(row[2]), str(row[3]), str(row[4]), str(row[5])
                ),
                str(row[1]),
            )
        return self.require(book_run_id)

    def require(self, book_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book_run_id, project_id, workspace_id, book_id,
                       book_design_version, book_plan_version,
                       production_profile_version, longform_context_versions,
                       root_operation_id, saga_id,
                       stable_idempotency_key, state, current_chapter,
                       target_chapter_count, light_recap_cadence,
                       formal_recap_cadence, active_chapter_request_id,
                       last_reader_outcome_operation_id, last_recap_operation_id,
                       version, paused_reason, failure_classification
                FROM authority_book_production WHERE book_run_id=%s
                """,
                [book_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_RUN_NOT_FOUND", "Book Authority run does not exist")
        fields = (
            "book_run_id", "project_id", "workspace_id", "book_id",
            "book_design_version", "book_plan_version",
            "production_profile_version", "longform_context_versions",
            "root_operation_id", "saga_id",
            "stable_idempotency_key", "state", "current_chapter",
            "target_chapter_count", "light_recap_cadence",
            "formal_recap_cadence", "active_chapter_request_id",
            "last_reader_outcome_operation_id", "last_recap_operation_id",
            "version", "paused_reason", "failure_classification",
        )
        return dict(zip(fields, row, strict=True))

    def require_chapter_request(self, chapter_request_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT chapter_request_id, book_run_id, project_id,
                       chapter_number, chapter_plan_version,
                       chapter_plan_content_hash, production_profile_version,
                       stable_idempotency_key, command_payload,
                       chapter_root_operation_id, chapter_saga_id,
                       status_reference, failure_classification
                FROM authority_book_chapter_request
                WHERE chapter_request_id=%s
                """,
                [chapter_request_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_CHAPTER_REQUEST_NOT_FOUND", "chapter request does not exist")
        fields = (
            "chapter_request_id", "book_run_id", "project_id",
            "chapter_number", "chapter_plan_version",
            "chapter_plan_content_hash", "production_profile_version",
            "stable_idempotency_key", "command_payload",
            "chapter_root_operation_id", "chapter_saga_id",
            "status_reference", "failure_classification",
        )
        return dict(zip(fields, row, strict=True))

    def resolve_asset_refs(
        self, *, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        """Resolve immutable Authority inputs without exposing a mutation port."""
        if len(asset_version_ids) != len(set(asset_version_ids)):
            raise KernelError(
                "BOOK_INPUT_VERSION_DUPLICATE",
                "Book Authority input AssetVersions must be distinct",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id = ANY(%s)
                """,
                [project_id, list(asset_version_ids)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        missing = [item for item in asset_version_ids if item not in found]
        if missing:
            raise KernelError(
                "BOOK_AUTHORITY_INPUT_ASSET_MISSING",
                "missing immutable Book input AssetVersions: "
                + ", ".join(missing),
            )
        return tuple(
            {"asset_version_id": item, "content_hash": found[item]}
            for item in asset_version_ids
        )

    def _schedule_followup(
        self,
        chapter_request_id: str,
        *,
        principal: Principal,
        definition_name: str,
        followup_type: str,
        state: BookProductionState,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
    ) -> BookFollowupAdmission:
        request = self.require_chapter_request(chapter_request_id)
        if followup_type == "READER_OUTCOME" and request["status_reference"] != "SUCCEEDED":
            raise KernelError(
                "BOOK_READER_OUTCOME_NOT_READY",
                "Reader Outcome requires a completed Chapter operation",
            )
        stable_key = (
            f"{request['stable_idempotency_key']}:{followup_type.lower()}:"
            f"{payload.get('checkpoint_type') or 'v1'}"
        )
        book = self.require(request["book_run_id"])
        admission = self.followup.admit(
            BookFollowupCommand(
                definition_name=definition_name,
                project_id=request["project_id"],
                workspace_id=book["workspace_id"],
                actor_id=principal.principal_id,
                trace_id=f"{request['chapter_root_operation_id']}:{followup_type.lower()}",
                correlation_id=request["chapter_root_operation_id"],
                idempotency_key=stable_key,
                payload=payload,
                input_assets=input_assets,
                root_operation_id=book["root_operation_id"],
                parent_operation_id=book["root_operation_id"],
                causation_operation_id=request["chapter_root_operation_id"],
            ),
            principal=principal,
        )
        graph = GraphCommandContext(
            request["project_id"],
            principal.principal_id,
            f"{request['chapter_root_operation_id']}:{followup_type.lower()}",
            request["chapter_root_operation_id"],
        )
        ordinal = int(request["chapter_number"]) * 2 - (
            1 if followup_type == "READER_OUTCOME" else 0
        )
        register_saga_step(
            self.database_url,
            graph,
            str(book["saga_id"]),
            admission.operation_id,
            f"chapter:{request['chapter_number']}:{followup_type.lower()}",
            ordinal,
            "",
        )
        if (
            followup_type == "LONGFORM_RECAP"
            and book["last_reader_outcome_operation_id"]
        ):
            add_operation_dependency(
                self.database_url,
                graph,
                admission.operation_id,
                str(book["last_reader_outcome_operation_id"]),
                "ON_SUCCESS",
        )
        followup_id = "book-followup:" + hashlib.sha256(stable_key.encode()).hexdigest()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.book_authority.link_followup(
                followup_id=followup_id,
                book_run_id=request["book_run_id"],
                chapter_request_id=chapter_request_id,
                project_id=request["project_id"],
                followup_type=followup_type,
                operation_id=admission.operation_id,
                stable_idempotency_key=stable_key,
                book_state=state.value,
            )
            uow.commit()
        return admission

    def _book_graph_context(
        self, book: dict[str, Any], actor_id: str
    ) -> GraphCommandContext:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT trace_id, correlation_id
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                """,
                [book["root_operation_id"], book["project_id"]],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_ROOT_OPERATION_MISSING", "Book root Operation is missing"
            )
        return GraphCommandContext(
            str(book["project_id"]), actor_id, str(row[0]), str(row[1])
        )


def book_coordinate_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": BOOK_COORDINATE_DEFINITION,
        "definition_version": BOOK_COORDINATE_DEFINITION_VERSION,
        "family": "book_authority",
        "command_schema_version": "book.production.coordinate.command.v1",
        "result_schema_version": "book.production.coordinate.result.v1",
        "enabled": True,
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "type": "book_authority_checkpoint",
            "authority_state_table": "authority_book_production",
        },
        "handler_key": BOOK_COORDINATE_HANDLER,
        "handler_contract_version": "book-authority-coordinator-v1",
        "definition_status": "integration_proven",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "saga",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:book-coordinate",
        "concurrency_key_template": "project:{project_id}:book",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 86400},
        "cancellation_policy": {"mode": "cancel_children"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only child authority references",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["book_authority_checkpoint"],
        "migration_owner": "book-authority",
        "policy": {
            "chapter_authority_state_ownership": "reference_only",
            "persistent_checkpoint_required": True,
        },
        "completion_contract": {
            "version": "book.production.coordinate.completion.v1",
            "required_evidence": ["trace", "audit", "book_checkpoint"],
        },
    }


def _validate_start(command: StartBookProductionCommand) -> None:
    required = (
        command.project_id,
        command.workspace_id,
        command.book_id,
        command.actor_id,
        command.trace_id,
        command.correlation_id,
        command.stable_idempotency_key,
        command.book_design_version,
        command.book_plan_version,
        command.production_profile_version,
    )
    versions = command.longform_context_versions
    if (
        any(not item for item in required)
        or command.target_chapter_count <= 0
        or command.light_recap_cadence <= 0
        or command.formal_recap_cadence <= 0
        or set(versions) != LONGFORM_CONTEXT_VERSION_KEYS
        or any(
            not value or value.endswith(":current")
            for value in versions.values()
        )
    ):
        raise ValueError(
            "Book Authority start command requires complete immutable context versions"
        )


__all__ = [
    "BOOK_COORDINATE_DEFINITION",
    "LONGFORM_CONTEXT_VERSION_KEYS",
    "BookProductionAdmission",
    "BookProductionState",
    "ChapterAuthorityCommandAdapter",
    "ChapterAuthorityCommandPort",
    "PostgresBookAuthority",
    "StartBookProductionCommand",
    "SubmitBookChapterCommand",
    "stable_chapter_submission_key",
    "book_coordinate_definition",
]
