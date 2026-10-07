from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError

from .production import BookProductionState, PostgresBookAuthority
from .queries import PostgresBookProductionQuery


@dataclass(frozen=True, slots=True)
class BookAuthorityTick:
    book_run_id: str
    previous_state: str
    state: str
    action: str
    operation_id: str = ""


class PostgresBookAuthorityScheduler:

    _CHAPTER_RECONCILIATION_STATES = frozenset(
        {
            BookProductionState.CHAPTER_SUBMITTED.value,
            BookProductionState.CHAPTER_RUNNING.value,
            BookProductionState.CHAPTER_WAITING_RETRY.value,
            BookProductionState.CHAPTER_FAILED_RETRYABLE.value,
        }
    )
    _CHAPTER_ACCEPTANCE_STATES = frozenset(
        {
            BookProductionState.CHAPTER_COMPLETED.value,
            BookProductionState.CHAPTER_ACCEPTANCE_PENDING.value,
            BookProductionState.CANON_PENDING.value,
        }
    )
    _LEGACY_NON_BLOCKING_STATES = frozenset(
        {
            BookProductionState.CANON_COMMITTED.value,
            BookProductionState.READER_OUTCOME_PENDING.value,
            BookProductionState.FOLLOWUP_PENDING.value,
        }
    )

    def __init__(
        self,
        authority: PostgresBookAuthority,
        *,
        query: PostgresBookProductionQuery,
        principal: Principal,
    ) -> None:
        self.authority = authority
        self.query = query
        self.principal = principal

    def tick(self, book_run_id: str) -> BookAuthorityTick:
        book = self.authority.require(book_run_id)
        before = str(book["state"])
        if before in self._CHAPTER_RECONCILIATION_STATES:
            request = self._active_request(book)
            if request["status_reference"] == "SUBMITTING" and not request.get("chapter_root_operation_id"):
                if request.get("parent_group_version_id"):
                    return self._result(book_run_id, before, "WAIT_GROUP_DISPATCH_RECOVERY")
                recovered = self.authority.recover_chapter_submission(request["chapter_request_id"], principal=self.principal)
                return self._result(book_run_id, before, "DISPATCH_CHAPTER", str(recovered["chapter_root_operation_id"]))
            self.authority.reconcile_chapter(request["chapter_request_id"])
            return self._result(book_run_id, before, "RECONCILE_CHAPTER")
        if before in self._CHAPTER_ACCEPTANCE_STATES:
            request = self._active_request(book)
            try:
                accepted = self.authority.accept_chapter(
                    request["chapter_request_id"], principal=self.principal
                )
            except KernelError as exc:
                if exc.code != "BOOK_CONTROL_APPROVAL_REQUIRED":
                    raise
                return self._result(book_run_id, before, "WAIT_CONTROL_DECISION")
            return self._result(
                book_run_id,
                before,
                "ACCEPT_CHAPTER",
                str(accepted["acceptance_operation_id"]),
            )
        if before == BookProductionState.CHAPTER_FAILED_TERMINAL.value:
            request = self._active_request(book)
            reason = str(request.get("failure_classification") or "")
            self.authority.cancel(
                book_run_id,
                reason=reason or "Chapter Authority reached a terminal failure",
                terminal_failure=True,
                principal=self.principal,
            )
            return self._result(book_run_id, before, "ABORT_TERMINAL_CHAPTER")
        if before in self._LEGACY_NON_BLOCKING_STATES:
            active_request_id = str(book.get("active_chapter_request_id") or "")
            if active_request_id:
                request = self.authority.reconcile_chapter(active_request_id)
                if str(request["status_reference"]) == "SUCCEEDED":
                    accepted = self.authority.accept_chapter(
                        active_request_id,
                        principal=self.principal,
                    )
                    return self._result(
                        book_run_id,
                        before,
                        "RECOVER_LEGACY_ACCEPTANCE",
                        str(accepted["acceptance_operation_id"]),
                    )
                return self._result(
                    book_run_id,
                    before,
                    "RECONCILE_CHAPTER",
                )
            accepted_request_id = self.query.latest_accepted_chapter_request_id(
                book_run_id=book_run_id,
                project_id=str(book["project_id"]),
            )
            accepted_request = (
                self.authority.require_chapter_request(accepted_request_id)
                if accepted_request_id
                else None
            )
            if (
                accepted_request is None
                or int(book["accepted_through_chapter"]) <= 0
                or int(accepted_request["chapter_number"])
                != int(book["accepted_through_chapter"])
            ):
                raise KernelError(
                    "BOOK_LEGACY_STATE_RECOVERY_EVIDENCE_MISSING",
                    "legacy sidecar state has neither an active Chapter nor a "
                    "committed acceptance at the Book cursor",
                )
            if int(book["accepted_through_chapter"]) >= int(
                book["target_chapter_count"]
            ):
                self.authority.complete_book_checkpoint(
                    book_run_id,
                    chapter_number=int(book["accepted_through_chapter"]),
                )
                return self._result(
                    book_run_id,
                    before,
                    "NORMALIZE_LEGACY_NON_BLOCKING_STATE",
                )
            self.authority.advance_supervisor_checkpoint(
                book_run_id,
                expected_version=int(book["version"]),
                expected_state=before,
                target_state=BookProductionState.READY,
                principal=self.principal,
            )
            return self._result(
                book_run_id, before, "NORMALIZE_LEGACY_NON_BLOCKING_STATE"
            )
        return BookAuthorityTick(book_run_id, before, before, "NOOP")

    def _active_request(self, book: dict[str, Any]) -> dict[str, Any]:
        request_id = str(book["active_chapter_request_id"] or "")
        if not request_id:
            raise KernelError(
                "BOOK_ACTIVE_CHAPTER_MISSING",
                "Book checkpoint has no active Chapter request",
            )
        request = self.authority.require_chapter_request(request_id)
        if request.get("book_run_id") != book["book_run_id"] or request.get("project_id") != book["project_id"]:
            raise KernelError("BOOK_ACTIVE_CHAPTER_SCOPE_MISMATCH", "active Chapter reservation belongs to another Book run")
        return request

    def _result(
        self, book_run_id: str, before: str, action: str, operation_id: str = ""
    ) -> BookAuthorityTick:
        return BookAuthorityTick(
            book_run_id,
            before,
            str(self.authority.require(book_run_id)["state"]),
            action,
            operation_id,
        )


__all__ = ["BookAuthorityTick", "PostgresBookAuthorityScheduler"]
