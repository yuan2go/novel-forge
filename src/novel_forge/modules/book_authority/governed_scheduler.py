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
            accepted = self.authority.accept_chapter(
                request["chapter_request_id"], principal=self.principal
            )
            admission = self._schedule_reader(accepted, request)
            return self._result(
                book_run_id,
                before,
                "ACCEPT_CHAPTER_AND_SUBMIT_READER_SHADOW",
                admission.operation_id,
            )
        if before in {
            BookProductionState.READY.value,
            BookProductionState.COMPLETED.value,
            # Compatibility with runs admitted before sidecars became
            # non-blocking Book children.
            BookProductionState.READER_OUTCOME_PENDING.value,
            BookProductionState.CHECKPOINT_PENDING.value,
        }:
            sidecar = self._tick_accepted_sidecars(book, before)
            if sidecar is not None:
                return sidecar
        return BookAuthorityTick(book_run_id, before, before, "NOOP")

    def _tick_accepted_sidecars(
        self, book: dict[str, Any], before: str
    ) -> BookAuthorityTick | None:
        request = self._latest_accepted_request(book)
        if request is None:
            return None
        reader_operation = self._followup_operation(
            request["chapter_request_id"], "READER_OUTCOME"
        )
        if not reader_operation:
            admission = self._schedule_reader(book, request)
            return self._result(
                book["book_run_id"],
                before,
                "SUBMIT_READER_SHADOW",
                admission.operation_id,
            )
        operation_id = reader_operation
        if self._operation_status(operation_id, book["project_id"]) != "SUCCEEDED":
            self.authority.followup.run_or_recover(
                BookFollowupAdmission(operation_id, book["project_id"], True)
            )
            return self._result(
                book["book_run_id"],
                before,
                "COMPLETE_READER_SHADOW",
                operation_id,
            )
        reader = self._output(operation_id, book["project_id"], "reader_outcome.report")
        trigger = should_trigger_longform_recap(
            chapter_number=int(request["chapter_number"]),
            light_cadence=int(book["light_recap_cadence"]),
            formal_cadence=int(book["formal_recap_cadence"]),
            chapter_group_complete=self._chapter_group_complete(request),
        )
        if not trigger["should_trigger"]:
            return None
        recap_operation = self._followup_operation(
            request["chapter_request_id"], "LONGFORM_RECAP"
        )
        if not recap_operation:
            admission = self._schedule_recap(book, request, reader, trigger)
            return self._result(
                book["book_run_id"],
                before,
                "SUBMIT_LONGFORM_RECAP_SIDECAR",
                admission.operation_id,
            )
        if self._operation_status(recap_operation, book["project_id"]) != "SUCCEEDED":
            self.authority.followup.run_or_recover(
                BookFollowupAdmission(recap_operation, book["project_id"], True)
            )
            return self._result(
                book["book_run_id"],
                before,
                "COMPLETE_LONGFORM_RECAP_SIDECAR",
                recap_operation,
            )
        return None

    def _chapter_group_complete(self, request: dict[str, Any]) -> bool:
        group_version = str(request.get("parent_group_version_id") or "")
        if not group_version:
            return False
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content->'chapter_range'
                FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [group_version],
            )
            row = uow.cursor.fetchone()
        if row is None or not isinstance(row[0], list) or len(row[0]) != 2:
            raise KernelError(
                "BOOK_CHAPTER_GROUP_PLAN_INVALID",
                "Chapter request references an invalid ChapterGroup Plan",
            )
        return int(request["chapter_number"]) == int(row[0][1])

    def _latest_accepted_request(self, book: dict[str, Any]) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT request.chapter_request_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                WHERE acceptance.book_run_id=%s
                  AND acceptance.project_id=%s
                ORDER BY acceptance.chapter_number DESC
                LIMIT 1
                """,
                [book["book_run_id"], book["project_id"]],
            )
            row = uow.cursor.fetchone()
        return (
            self.authority.require_chapter_request(str(row[0]))
            if row is not None
            else None
        )

    def _followup_operation(self, chapter_request_id: str, followup_type: str) -> str:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id
                FROM authority_book_followup_operation
                WHERE chapter_request_id=%s AND followup_type=%s
                """,
                [chapter_request_id, followup_type],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def _operation_status(self, operation_id: str, project_id: str) -> str:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        return str(state["status"])

    def _schedule_reader(
        self, book: dict[str, Any], request: dict[str, Any]
    ) -> BookFollowupAdmission:
        evidence = self.authority.chapter_port.require_acceptance_evidence(
            project_id=book["project_id"],
            root_operation_id=request["chapter_root_operation_id"],
        )
        draft = self._evidence_output(evidence, "draft_version")
        canon = self._evidence_output(evidence, "canon_snapshot")
        quality = self._evidence_output(evidence, "quality_score_report")
        manifest = self._evidence_output(evidence, "production_input_manifest")
        frozen_versions = dict(book["longform_context_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=book["project_id"],
            asset_version_ids=(
                str(request["chapter_plan_version"]),
                str(book["book_design_version"]),
                str(book["book_plan_version"]),
                str(frozen_versions["volume_plan_version"]),
                str(frozen_versions["arc_plan_version"]),
                str(frozen_versions["reader_segment_version"]),
                str(frozen_versions["reader_contract_version"]),
                str(frozen_versions["platform_profile_version"]),
                str(book["last_chapter_outcome_version_id"]),
                str(book["active_story_state_version_id"]),
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
                "book_plan_version": book["book_plan_version"],
                "parent_plan_versions": {
                    "volume_plan_version": frozen_versions["volume_plan_version"],
                    "arc_plan_version": frozen_versions["arc_plan_version"],
                },
                "reader_segment_version": frozen_versions["reader_segment_version"],
                "reader_contract_version": frozen_versions["reader_contract_version"],
                "platform_profile_version": frozen_versions["platform_profile_version"],
                "canon_snapshot_version": canon["asset_version_id"],
                "chapter_outcome_version": book["last_chapter_outcome_version_id"],
                "story_state_version": book["active_story_state_version_id"],
                "quality_evidence_version": quality["asset_version_id"],
                "input_manifest_ref": manifest["asset_version_id"],
                "previous_reader_state_version": self._previous_reader_state(
                    book, int(request["chapter_number"])
                ),
                "evaluation_profile_version": "reader-evaluation:v1",
                "model_strategy_version": book["production_profile_version"],
            },
            input_assets=(
                self._asset_ref(draft),
                self._asset_ref(canon),
                self._asset_ref(quality),
                self._asset_ref(manifest),
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
        evidence = self.authority.chapter_port.require_acceptance_evidence(
            project_id=book["project_id"],
            root_operation_id=request["chapter_root_operation_id"],
        )
        canon = self._evidence_output(evidence, "canon_snapshot")
        character = self._evidence_output(evidence, "character_state_snapshot")
        foreshadow = self._evidence_output(evidence, "foreshadow_snapshot")
        reward = self._evidence_output(evidence, "reward_ledger_snapshot")
        promise = self._evidence_output(evidence, "promise_ledger_snapshot")
        chapter = int(request["chapter_number"])
        frozen_versions = dict(book["longform_context_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=book["project_id"],
            asset_version_ids=(
                str(book["book_design_version"]),
                str(book["book_plan_version"]),
                str(frozen_versions["volume_plan_version"]),
                str(frozen_versions["arc_plan_version"]),
                str(frozen_versions["quality_trend_version"]),
                str(book["last_chapter_outcome_version_id"]),
                str(book["active_story_state_version_id"]),
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
                "character_state_version": character["asset_version_id"],
                "foreshadowing_state_version": foreshadow["asset_version_id"],
                "reader_state_version": reader["asset_version_id"],
                "quality_trend_version": frozen_versions["quality_trend_version"],
                "reward_ledger_version": reward["asset_version_id"],
                "promise_ledger_version": promise["asset_version_id"],
                "chapter_outcome_versions": [book["last_chapter_outcome_version_id"]],
                "story_state_version": book["active_story_state_version_id"],
                "observations": {
                    "reader_state": dict(reader["content"].get("reader_state") or {}),
                    "reader_qualification": {
                        "qualification_status": str(
                            reader["content"].get("judge_qualification_status")
                            or "SHADOW"
                        ),
                        "sample_size": int(reader["content"].get("sample_size") or 0),
                        "confidence": float(reader["content"].get("confidence") or 0),
                        "disagreement": True,
                        "position_bias": True,
                        "ood": True,
                        "drift_detected": False,
                        "recent_reports": [],
                        "last_adjustment_chapter": None,
                    },
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
                self._asset_ref(character),
                self._asset_ref(foreshadow),
                self._asset_ref(reward),
                self._asset_ref(promise),
                *authority_inputs,
            ),
        )

    def _previous_reader_state(self, book: dict[str, Any], chapter_number: int) -> str:
        if chapter_number <= 1:
            return "NONE"
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_followup_operation AS link
                  ON link.chapter_request_id=acceptance.chapter_request_id
                 AND link.followup_type='READER_OUTCOME'
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id=link.operation_id
                 AND binding.output_key='reader_outcome.state_transition'
                WHERE acceptance.book_run_id=%s
                  AND acceptance.chapter_number=%s
                """,
                [book["book_run_id"], chapter_number - 1],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else "NONE"

    @staticmethod
    def _evidence_output(evidence: dict[str, Any], asset_type: str) -> dict[str, Any]:
        matches = [
            item for item in evidence["outputs"] if item["asset_type"] == asset_type
        ]
        if len(matches) != 1:
            raise KernelError(
                "BOOK_CHAPTER_OUTPUT_MISSING",
                f"Chapter Authority produced {len(matches)} {asset_type} outputs",
            )
        return matches[0]

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

    @staticmethod
    def _asset_ref(item: dict[str, Any]) -> dict[str, str]:
        return {
            "asset_version_id": str(item["asset_version_id"]),
            "content_hash": str(item["content_hash"]),
        }


__all__ = ["BookAuthorityTick", "PostgresBookAuthorityScheduler"]
