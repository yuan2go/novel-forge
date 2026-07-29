"""One-step persistent Book scheduler using only Authority command/query ports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
)
from novel_forge.modules.book_followup_authority.domain import (
    should_trigger_longform_recap,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .production import BookProductionState, PostgresBookAuthority


@dataclass(frozen=True, slots=True)
class BookAuthorityTick:
    book_run_id: str
    previous_state: str
    state: str
    action: str
    operation_id: str = ""


class PostgresBookAuthorityScheduler:
    """Advance one durable checkpoint; no Chapter execution state is copied."""

    def __init__(
        self, authority: PostgresBookAuthority, *, principal: Principal
    ) -> None:
        self.authority = authority
        self.principal = principal

    def tick(self, book_run_id: str) -> BookAuthorityTick:
        book = self.authority.require(book_run_id)
        before = str(book["state"])
        if before in {
            BookProductionState.CHAPTER_SUBMITTED.value,
            BookProductionState.CHAPTER_RUNNING.value,
            BookProductionState.CHAPTER_WAITING_RETRY.value,
        }:
            request = self._active_request(book)
            self.authority.reconcile_chapter(request["chapter_request_id"])
            return self._result(book_run_id, before, "RECONCILE_CHAPTER")
        if before == BookProductionState.CHAPTER_COMPLETED.value:
            request = self._active_request(book)
            if not book["last_reader_outcome_operation_id"]:
                admission = self._schedule_reader(book, request)
                return self._result(
                    book_run_id,
                    before,
                    "SUBMIT_READER_OUTCOME",
                    admission.operation_id,
                )
            return self._finish_reader_or_checkpoint(book, request, before)
        if before == BookProductionState.READER_OUTCOME_PENDING.value:
            request = self._active_request(book)
            return self._finish_reader_or_checkpoint(book, request, before)
        if before == BookProductionState.CHECKPOINT_PENDING.value:
            operation_id = str(book["last_recap_operation_id"] or "")
            if not operation_id:
                raise KernelError(
                    "BOOK_RECAP_REFERENCE_MISSING",
                    "checkpoint state has no Long-form Recap operation",
                )
            self.authority.followup.run_or_recover(
                BookFollowupAdmission(operation_id, book["project_id"], True)
            )
            replan = self._has_output(
                operation_id, book["project_id"], "longform.recap.replan_request"
            )
            self.authority.complete_followup(
                operation_id, replan_required=replan
            )
            return self._result(
                book_run_id, before, "COMPLETE_LONGFORM_RECAP", operation_id
            )
        return BookAuthorityTick(book_run_id, before, before, "NOOP")

    def _finish_reader_or_checkpoint(
        self,
        book: dict[str, Any],
        request: dict[str, Any],
        before: str,
    ) -> BookAuthorityTick:
        operation_id = str(book["last_reader_outcome_operation_id"] or "")
        if not operation_id:
            admission = self._schedule_reader(book, request)
            return self._result(
                book["book_run_id"],
                before,
                "SUBMIT_READER_OUTCOME",
                admission.operation_id,
            )
        self.authority.followup.run_or_recover(
            BookFollowupAdmission(operation_id, book["project_id"], True)
        )
        reader = self._output(
            operation_id, book["project_id"], "reader_outcome.report"
        )
        gate = str(reader["content"].get("gate") or "")
        replan = gate in {
            "REVISION_REQUIRED",
            "HUMAN_REVIEW_REQUIRED",
            "BLOCKED",
        }
        self.authority.complete_followup(operation_id, replan_required=replan)
        if replan:
            return self._result(
                book["book_run_id"], before, "READER_OUTCOME_REPLAN", operation_id
            )
        trigger = should_trigger_longform_recap(
            chapter_number=int(request["chapter_number"]),
            light_cadence=int(book["light_recap_cadence"]),
            formal_cadence=int(book["formal_recap_cadence"]),
        )
        if trigger["should_trigger"]:
            admission = self._schedule_recap(book, request, reader, trigger)
            return self._result(
                book["book_run_id"],
                before,
                "SUBMIT_LONGFORM_RECAP",
                admission.operation_id,
            )
        self.authority.complete_book_checkpoint(
            book["book_run_id"], chapter_number=int(request["chapter_number"])
        )
        return self._result(
            book["book_run_id"], before, "COMPLETE_BOOK_CHECKPOINT", operation_id
        )

    def _schedule_reader(
        self, book: dict[str, Any], request: dict[str, Any]
    ) -> BookFollowupAdmission:
        run = self.authority.chapter_port.require_run(
            project_id=book["project_id"],
            root_operation_id=request["chapter_root_operation_id"],
        )
        draft = self._primary(run, "draft_version")
        canon = self._primary(run, "canon_patch")
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=book["project_id"],
            asset_version_ids=(
                str(request["chapter_plan_version"]),
                str(book["book_design_version"]),
            ),
        )
        return self.authority.schedule_reader_outcome(
            request["chapter_request_id"],
            principal=self.principal,
            payload={
                "book_id": book["book_id"],
                "chapter_id": f"chapter:{request['chapter_number']}",
                "chapter_number": int(request["chapter_number"]),
                "final_draft_asset_version": draft["asset_version_id"],
                "chapter_plan_asset_version": request["chapter_plan_version"],
                "book_design_version": book["book_design_version"],
                "reader_contract_version": "reader-contract:v1",
                "canon_snapshot_version": canon["asset_version_id"],
                "previous_reader_state_version": "reader-state:none",
                "evaluation_profile_version": "reader-evaluation:v1",
                "model_strategy_version": book["production_profile_version"],
            },
            input_assets=(
                self._asset_ref(draft),
                self._asset_ref(canon),
                *authority_inputs,
            ),
        )

    def _schedule_recap(
        self,
        book: dict[str, Any],
        request: dict[str, Any],
        reader: dict[str, Any],
        trigger: dict[str, Any],
    ) -> BookFollowupAdmission:
        run = self.authority.chapter_port.require_run(
            project_id=book["project_id"],
            root_operation_id=request["chapter_root_operation_id"],
        )
        canon = self._primary(run, "canon_patch")
        chapter = int(request["chapter_number"])
        frozen_versions = dict(book["longform_context_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=book["project_id"],
            asset_version_ids=(
                str(book["book_design_version"]),
                str(book["book_plan_version"]),
                *(
                    str(frozen_versions[key])
                    for key in sorted(frozen_versions)
                ),
            ),
        )
        return self.authority.schedule_longform_recap(
            request["chapter_request_id"],
            principal=self.principal,
            payload={
                "book_id": book["book_id"],
                "checkpoint_type": trigger["checkpoint_type"],
                "chapter_range": [
                    max(1, chapter - int(book["formal_recap_cadence"]) + 1),
                    chapter,
                ],
                "book_design_version": book["book_design_version"],
                "book_plan_version": book["book_plan_version"],
                "volume_plan_version": frozen_versions["volume_plan_version"],
                "arc_plan_version": frozen_versions["arc_plan_version"],
                "canon_snapshot_version": canon["asset_version_id"],
                "character_state_version": frozen_versions[
                    "character_state_version"
                ],
                "foreshadowing_state_version": frozen_versions[
                    "foreshadowing_state_version"
                ],
                "reader_state_version": reader["asset_version_id"],
                "quality_trend_version": frozen_versions[
                    "quality_trend_version"
                ],
                "reward_ledger_version": frozen_versions[
                    "reward_ledger_version"
                ],
                "promise_ledger_version": frozen_versions[
                    "promise_ledger_version"
                ],
                "observations": {
                    "reader_state": dict(
                        reader["content"].get("reader_state") or {}
                    ),
                    "canon": {"conflicts": []},
                    "quality_trend": {"direction": "STABLE"},
                },
            },
            input_assets=(
                {
                    "asset_version_id": reader["asset_version_id"],
                    "content_hash": reader["content_hash"],
                },
                self._asset_ref(canon),
                *authority_inputs,
            ),
        )

    def _active_request(self, book: dict[str, Any]) -> dict[str, Any]:
        request_id = str(book["active_chapter_request_id"] or "")
        if not request_id:
            raise KernelError(
                "BOOK_ACTIVE_CHAPTER_MISSING",
                "Book checkpoint has no active Chapter request",
            )
        return self.authority.require_chapter_request(request_id)

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

    def _output(
        self, operation_id: str, project_id: str, output_key: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.content_hash, version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=binding.operation_id
                WHERE binding.operation_id=%s AND operation.project_id=%s
                  AND binding.output_key=%s
                """,
                [operation_id, project_id, output_key],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_FOLLOWUP_OUTPUT_MISSING", f"missing output {output_key}"
            )
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
            "content": dict(row[2]),
        }

    def _has_output(
        self, operation_id: str, project_id: str, output_key: str
    ) -> bool:
        try:
            self._output(operation_id, project_id, output_key)
        except KernelError as exc:
            if exc.code == "BOOK_FOLLOWUP_OUTPUT_MISSING":
                return False
            raise
        return True

    @staticmethod
    def _primary(run: dict[str, Any], asset_type: str) -> dict[str, Any]:
        try:
            return next(
                item
                for item in run["primary_outputs"]
                if item["asset_type"] == asset_type
            )
        except StopIteration as exc:
            raise KernelError(
                "BOOK_CHAPTER_OUTPUT_MISSING",
                f"Chapter Authority produced no {asset_type}",
            ) from exc

    @staticmethod
    def _asset_ref(item: dict[str, Any]) -> dict[str, str]:
        return {
            "asset_version_id": str(item["asset_version_id"]),
            "content_hash": str(item["content_hash"]),
        }


__all__ = ["BookAuthorityTick", "PostgresBookAuthorityScheduler"]
