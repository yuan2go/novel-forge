from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority.production import (
    PostgresBookAuthority,
    select_chapter_acceptance_outputs,
)
from novel_forge.modules.book_authority.queries import (
    BookFollowupAdmissionCandidate,
    PostgresBookProductionQuery,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
)
from novel_forge.modules.book_followup_authority.domain import (
    should_trigger_longform_recap,
)
from novel_forge.modules.book_followup_authority.query import (
    BookFollowupProjectionQuery,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


_ARC_FOLLOWUP_OPERATION_STATUS = {
    "ADMITTED": "RUNNING",
    "READY": "RUNNING",
    "EXECUTING": "RUNNING",
    "WAITING_CHILDREN": "RUNNING",
    "WAITING_GATE": "RUNNING",
    "FAILED_RETRYABLE": "FAILED_RETRYABLE",
    "WAITING_EXTERNAL_RESULT": "RECONCILIATION_REQUIRED",
    "RECONCILIATION_REQUIRED": "RECONCILIATION_REQUIRED",
    "CANCELLATION_REQUESTED": "RECONCILIATION_REQUIRED",
    "WAITING_APPROVAL": "WAITING_APPROVAL",
    "FAILED_FINAL": "FAILED_FINAL",
    "DEAD_LETTER": "DEAD_LETTER",
    "CANCELLED": "CANCELLED",
}
_ARC_FOLLOWUP_TERMINALS = frozenset(
    {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED", "MANUAL_INTERVENTION"}
)


@dataclass(frozen=True, slots=True)
class BookFollowupCoordinationResult:
    book_run_id: str
    chapter_request_id: str
    chapter_number: int
    action: str
    operation_id: str


class PostgresBookFollowupCoordinator:

    def __init__(
        self,
        authority: PostgresBookAuthority,
        *,
        query: PostgresBookProductionQuery,
        principal: Principal,
        followup_query: BookFollowupProjectionQuery | None = None,
    ) -> None:
        self.authority = authority
        self.query = query
        self.principal = principal
        self.followup_query = followup_query or BookFollowupProjectionQuery(
            authority.database_url
        )

    def admission_candidates(
        self, *, limit: int
    ) -> tuple[BookFollowupAdmissionCandidate, ...]:
        project_ids = (
            ()
            if "*" in self.principal.project_scope
            else tuple(sorted(self.principal.project_scope))
        )
        return self.query.followup_admission_candidates(
            limit=limit,
            project_ids=project_ids,
        )

    def admit(
        self, candidate: BookFollowupAdmissionCandidate
    ) -> BookFollowupCoordinationResult:
        snapshot = self.query.require_accepted_followup_snapshot(
            chapter_request_id=candidate.chapter_request_id
        )
        if (
            snapshot["book_run_id"] != candidate.book_run_id
            or snapshot["project_id"] != candidate.project_id
            or int(snapshot["chapter_number"]) != candidate.chapter_number
        ):
            raise KernelError(
                "BOOK_FOLLOWUP_CANDIDATE_DRIFT",
                "follow-up candidate differs from its accepted snapshot",
            )
        if not candidate.reader_operation_id:
            admission = self._schedule_reader(snapshot)
            return self._result(candidate, "ADMIT_READER_OUTCOME", admission)
        if candidate.reader_status != "SUCCEEDED":
            raise KernelError(
                "BOOK_FOLLOWUP_READER_NOT_READY",
                "Longform Recap admission requires a successful Reader Outcome",
            )
        if candidate.recap_operation_id:
            return BookFollowupCoordinationResult(
                candidate.book_run_id,
                candidate.chapter_request_id,
                candidate.chapter_number,
                "NO_ACTION",
                candidate.recap_operation_id,
            )
        reader = self.query.require_followup_output(
            operation_id=candidate.reader_operation_id,
            project_id=candidate.project_id,
            output_key="reader_outcome.report",
        )
        reader_evidence = self.followup_query.reader_recap_evidence(
            project_id=candidate.project_id,
            book_run_id=candidate.book_run_id,
            through_chapter=candidate.chapter_number,
            current_report_asset_version_id=str(reader["asset_version_id"]),
        )
        quality_trend = self.followup_query.asset(
            project_id=candidate.project_id,
            asset_version_id=str(snapshot["quality_trend_version"]),
        )
        canon = self.followup_query.asset(
            project_id=candidate.project_id,
            asset_version_id=str(snapshot["accepted_canon_snapshot_version"]),
        )
        ending_reachability = self.query.ending_reachability(
            book_run_id=candidate.book_run_id,
            chapter_number=candidate.chapter_number,
        )
        arc_checkpoint = self.query.arc_checkpoint_followup(
            book_run_id=candidate.book_run_id,
            chapter_number=candidate.chapter_number,
        )
        realization = self.query.accepted_realization_deviations(
            chapter_request_id=candidate.chapter_request_id
        )
        trigger = should_trigger_longform_recap(
            chapter_number=candidate.chapter_number,
            light_cadence=int(snapshot["light_recap_cadence"]),
            formal_cadence=int(snapshot["formal_recap_cadence"]),
            chapter_group_complete=self._chapter_group_complete(snapshot),
            authority_requested=bool(ending_reachability.get("replan_required") or realization["deviations"]),
            arc_checkpoint=arc_checkpoint is not None,
            reader_outcome_declining=bool(reader_evidence["trend"]["declining"]),
            canon_risk=bool(canon["content"].get("conflicts")),
            quality_trend_declining=(
                str(quality_trend["content"].get("direction") or "").upper()
                == "DECLINING"
            ),
        )
        if not trigger["should_trigger"]:
            raise KernelError(
                "BOOK_FOLLOWUP_RECAP_NOT_DUE",
                "candidate does not carry a governed Longform Recap trigger",
            )
        admission = self._schedule_recap(
            snapshot=snapshot,
            reader=reader,
            trigger=trigger,
            ending_reachability=ending_reachability,
            arc_checkpoint=arc_checkpoint,
            reader_evidence=reader_evidence,
            quality_trend=quality_trend,
            canon=canon,
            realization=realization,
        )
        if arc_checkpoint is not None:
            self._bind_arc_checkpoint_followup(
                followup_id=str(arc_checkpoint["followup_id"]),
                operation_id=admission.operation_id,
            )
        return self._result(candidate, "ADMIT_LONGFORM_RECAP", admission)

    def _schedule_reader(self, snapshot: dict[str, Any]) -> BookFollowupAdmission:
        evidence = self.authority.chapter_port.require_acceptance_evidence(
            project_id=str(snapshot["project_id"]),
            root_operation_id=str(snapshot["chapter_root_operation_id"]),
        )
        draft = self._evidence_output(evidence, "best_draft_candidate")
        quality = self._evidence_output(evidence, "quality_score_report")
        manifest = self._evidence_output(evidence, "production_input_manifest")
        canon = self.authority.resolve_asset_refs(
            project_id=str(snapshot["project_id"]),
            asset_version_ids=(str(snapshot["accepted_canon_snapshot_version"]),),
        )[0]
        arc_plan_versions = tuple(str(item) for item in snapshot["arc_plan_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=str(snapshot["project_id"]),
            asset_version_ids=(
                str(snapshot["chapter_plan_version"]),
                str(snapshot["book_design_version"]),
                str(snapshot["book_plan_version"]),
                str(snapshot["volume_plan_version"]),
                *arc_plan_versions,
                str(snapshot["reader_segment_version"]),
                str(snapshot["reader_contract_version"]),
                str(snapshot["platform_profile_version"]),
                str(snapshot["accepted_chapter_outcome_version"]),
                str(snapshot["accepted_story_state_version"]),
            ),
        )
        previous_reader_state = self.query.previous_reader_state(
            book_run_id=str(snapshot["book_run_id"]),
            chapter_number=int(snapshot["chapter_number"]),
        )
        previous_state_inputs = (
            ()
            if previous_reader_state == "NONE"
            else self.authority.resolve_asset_refs(
                project_id=str(snapshot["project_id"]),
                asset_version_ids=(previous_reader_state,),
            )
        )
        return self.authority.schedule_reader_outcome(
            str(snapshot["chapter_request_id"]),
            principal=self.principal,
            payload={
                "book_id": snapshot["book_id"],
                "chapter_id": f"chapter:{snapshot['chapter_number']}",
                "chapter_number": int(snapshot["chapter_number"]),
                "observed_through_chapter": int(snapshot["observed_through_chapter"]),
                "acceptance_operation_id": snapshot["acceptance_operation_id"],
                "book_production_input_snapshot_id": snapshot[
                    "book_production_input_snapshot_id"
                ],
                "final_draft_asset_version": draft["asset_version_id"],
                "chapter_plan_asset_version": snapshot["chapter_plan_version"],
                "book_design_version": snapshot["book_design_version"],
                "book_plan_version": snapshot["book_plan_version"],
                "parent_plan_versions": {
                    "volume_plan_version": snapshot["volume_plan_version"],
                    "arc_plan_versions": list(arc_plan_versions),
                },
                "reader_segment_version": snapshot["reader_segment_version"],
                "reader_contract_version": snapshot["reader_contract_version"],
                "platform_profile_version": snapshot["platform_profile_version"],
                "canon_snapshot_version": snapshot["accepted_canon_snapshot_version"],
                "chapter_outcome_version": snapshot["accepted_chapter_outcome_version"],
                "story_state_version": snapshot["accepted_story_state_version"],
                "quality_evidence_version": quality["asset_version_id"],
                "input_manifest_ref": manifest["asset_version_id"],
                "previous_reader_state_version": previous_reader_state,
                "evaluation_profile_version": "reader-evaluation:v1",
                "model_strategy_version": snapshot["production_profile_version"],
                "context_token_budget": int(snapshot["context_token_budget"]),
            },
            input_assets=(
                self._asset_ref(draft),
                self._asset_ref(canon),
                self._asset_ref(quality),
                self._asset_ref(manifest),
                *authority_inputs,
                *previous_state_inputs,
            ),
        )

    def _schedule_recap(
        self,
        *,
        snapshot: dict[str, Any],
        reader: dict[str, Any],
        trigger: dict[str, Any],
        ending_reachability: dict[str, Any],
        arc_checkpoint: dict[str, Any] | None,
        reader_evidence: dict[str, Any],
        quality_trend: dict[str, Any],
        canon: dict[str, Any],
        realization: dict[str, Any],
    ) -> BookFollowupAdmission:
        chapter = int(snapshot["chapter_number"])
        arc_plan_versions = tuple(str(item) for item in snapshot["arc_plan_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=str(snapshot["project_id"]),
            asset_version_ids=(
                str(snapshot["book_design_version"]),
                str(snapshot["book_plan_version"]),
                str(snapshot["volume_plan_version"]),
                *arc_plan_versions,
                str(snapshot["quality_trend_version"]),
                str(snapshot["accepted_chapter_outcome_version"]),
                str(snapshot["accepted_story_state_version"]),
                str(snapshot["accepted_canon_snapshot_version"]),
            ),
        )
        input_assets = self._unique_asset_refs(
            (
                {
                    "asset_version_id": reader["asset_version_id"],
                    "content_hash": reader["content_hash"],
                },
                *tuple(reader_evidence["source_assets"]),
                *authority_inputs,
            )
        )
        return self.authority.schedule_longform_recap(
            str(snapshot["chapter_request_id"]),
            principal=self.principal,
            payload={
                "book_id": snapshot["book_id"],
                "checkpoint_type": trigger["checkpoint_type"],
                "chapter_range": [
                    max(
                        1,
                        chapter - int(snapshot["formal_recap_cadence"]) + 1,
                    ),
                    chapter,
                ],
                "observed_through_chapter": int(snapshot["observed_through_chapter"]),
                "acceptance_operation_id": snapshot["acceptance_operation_id"],
                "book_production_input_snapshot_id": snapshot[
                    "book_production_input_snapshot_id"
                ],
                "book_design_version": snapshot["book_design_version"],
                "book_plan_version": snapshot["book_plan_version"],
                "volume_plan_version": snapshot["volume_plan_version"],
                "arc_plan_versions": list(arc_plan_versions),
                "canon_snapshot_version": snapshot["accepted_canon_snapshot_version"],
                "story_state_version": snapshot["accepted_story_state_version"],
                "reader_state_version": reader_evidence[
                    "current_state_asset_version_id"
                ],
                "quality_trend_version": snapshot["quality_trend_version"],
                "chapter_outcome_versions": list(
                    reader_evidence["chapter_outcome_versions"]
                ),
                "observations": {
                    "reader_evidence_class": "READER_PROXY_ADVISORY",
                    "reader_state": dict(reader_evidence["current_reader_state"]),
                    "reader_qualification": dict(reader_evidence["qualification"]),
                    "reader_longitudinal": {
                        "contract_version": reader_evidence["contract_version"],
                        "observed_through_chapter": reader_evidence[
                            "observed_through_chapter"
                        ],
                        "recent_reports": list(reader_evidence["recent_reports"]),
                        "trend": dict(reader_evidence["trend"]),
                    },
                    "canon": dict(canon["content"]),
                    "quality_trend": dict(quality_trend["content"]),
                    "ending_reachability": ending_reachability,
                    "accepted_arc_checkpoint": dict(arc_checkpoint or {}),
                    "accepted_realization_deviations": realization,
                },
            },
            input_assets=input_assets,
        )

    def _bind_arc_checkpoint_followup(
        self, *, followup_id: str, operation_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_arc_checkpoint_followup
                SET operation_id=%s, status='RUNNING', version=version+1,
                    updated_at=NOW()
                WHERE followup_id=%s
                  AND status IN ('READY','RUNNING','FAILED_RETRYABLE')
                  AND (operation_id IS NULL OR operation_id=%s)
                """,
                [operation_id, followup_id, operation_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "ARC_CHECKPOINT_FOLLOWUP_BINDING_CONFLICT",
                    "Arc checkpoint follow-up raced with another operation",
                )
            uow.commit()

    def reconcile_arc_checkpoint_followup(self, operation_id: str) -> None:

        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT followup.followup_id, followup.book_run_id,
                       followup.decision, operation.status,
                       EXISTS(
                           SELECT 1 FROM authority_operation_output_asset AS output
                           WHERE output.operation_id=operation.operation_id
                             AND output.output_key='longform.recap.replan_request'
                       ), followup.status, followup.projection_set_id,
                       followup.last_error, operation.version,
                       COALESCE(attempt.attempt_id, ''),
                       COALESCE(attempt.attempt_number, 0),
                       COALESCE(attempt.status, ''),
                       COALESCE(attempt.error, '{}'::jsonb),
                       book.state,
                       COALESCE(book.active_longform_projection_set_id, '')
                FROM authority_arc_checkpoint_followup AS followup
                JOIN authority_operation AS operation
                  ON operation.operation_id=followup.operation_id
                JOIN authority_book_production AS book
                  ON book.book_run_id=followup.book_run_id
                LEFT JOIN LATERAL (
                    SELECT candidate.attempt_id, candidate.attempt_number,
                           candidate.status, candidate.error
                    FROM authority_attempt AS candidate
                    WHERE candidate.operation_id=operation.operation_id
                    ORDER BY candidate.attempt_number DESC
                    LIMIT 1
                ) AS attempt ON TRUE
                WHERE followup.operation_id=%s
                FOR UPDATE OF followup, book
                """,
                [operation_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                return
            operation_status = str(row[3])
            has_revision = bool(row[4])
            if operation_status == "SUCCEEDED":
                next_status = "PROPOSED" if has_revision else "MANUAL_INTERVENTION"
            else:
                next_status = _ARC_FOLLOWUP_OPERATION_STATUS.get(operation_status)
            if next_status is None:
                return

            evidence = {
                "operation_id": operation_id,
                "operation_status": operation_status,
                "operation_version": int(row[8]),
                "attempt_id": str(row[9]),
                "attempt_number": int(row[10]),
                "attempt_status": str(row[11]),
                "attempt_error": dict(row[12] or {}),
                "accepted_truth_preserved": True,
                "future_production_only": True,
                "recovery_action": self._arc_followup_recovery_action(next_status),
            }
            if next_status == "MANUAL_INTERVENTION":
                evidence["error_code"] = "ARC_REVISION_OUTPUT_MISSING"
            stored_error = dict(row[7] or {})
            if str(row[5]) == next_status and stored_error == evidence:
                return
            uow.cursor.execute(
                """
                UPDATE authority_arc_checkpoint_followup
                SET status=%s, last_error=%s, version=version+1,
                    updated_at=NOW()
                WHERE followup_id=%s AND operation_id=%s
                """,
                [
                    next_status,
                    Jsonb({} if next_status == "PROPOSED" else evidence),
                    str(row[0]),
                    operation_id,
                ],
            )
            if next_status == "PROPOSED":
                if str(row[13]) in {"CHECKPOINT_PENDING", "READY"} and str(
                    row[14]
                ) == str(row[6]):
                    uow.cursor.execute(
                        """
                        UPDATE authority_book_production
                        SET state='REPLAN_REQUIRED', version=version+1,
                            updated_at=NOW()
                        WHERE book_run_id=%s AND state=%s
                          AND active_longform_projection_set_id=%s
                        """,
                        [str(row[1]), str(row[13]), str(row[6])],
                    )
                elif str(row[13]) not in {
                    "REPLAN_REQUIRED",
                    "REPLAN_GENERATING",
                    "REPLAN_APPROVAL_PENDING",
                } and str(row[14]) == str(row[6]):
                    raise KernelError(
                        "ARC_CHECKPOINT_BOOK_STATE_CONFLICT",
                        "Book left checkpoint-pending before ArcRevision admission",
                    )
            elif next_status in _ARC_FOLLOWUP_TERMINALS:
                reason = (
                    "Arc checkpoint follow-up requires governed recovery: "
                    f"{next_status} ({operation_id})"
                )
                if str(row[14]) == str(row[6]) and str(row[13]) not in {
                    "COMPLETED",
                    "ABORTED",
                    "PAUSED",
                }:
                    uow.cursor.execute(
                        """
                        UPDATE authority_book_production
                        SET state='PAUSED', paused_reason=%s, failure_reason=%s,
                            version=version+1, updated_at=NOW()
                        WHERE book_run_id=%s AND state=%s
                          AND active_longform_projection_set_id=%s
                        """,
                        [reason, next_status, str(row[1]), str(row[13]), str(row[6])],
                    )
                    if uow.cursor.rowcount != 1:
                        raise KernelError(
                            "ARC_CHECKPOINT_BOOK_STATE_CONFLICT",
                            "Book changed before terminal Arc follow-up was governed",
                        )
            uow.commit()

    def reconcile_completed_arc_checkpoint_followups(self, *, limit: int) -> int:
        if limit <= 0:
            raise ValueError("Arc checkpoint reconciliation limit must be positive")
        with AuthorityUnitOfWork(self.authority.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT followup.operation_id
                FROM authority_arc_checkpoint_followup AS followup
                JOIN authority_operation AS operation
                  ON operation.operation_id=followup.operation_id
                WHERE followup.status IN (
                    'RUNNING','FAILED_RETRYABLE','RECONCILIATION_REQUIRED'
                )
                  AND operation.status IN (
                    'ADMITTED','READY','EXECUTING','WAITING_CHILDREN',
                    'WAITING_EXTERNAL_RESULT','WAITING_GATE','WAITING_APPROVAL',
                    'FAILED_RETRYABLE','FAILED_FINAL','CANCELLATION_REQUESTED',
                    'RECONCILIATION_REQUIRED','SUCCEEDED','CANCELLED','DEAD_LETTER'
                  )
                ORDER BY followup.updated_at, followup.followup_id
                LIMIT %s
                """,
                [limit],
            )
            operation_ids = [str(row[0]) for row in uow.cursor.fetchall()]
        for operation_id in operation_ids:
            self.reconcile_arc_checkpoint_followup(operation_id)
        return len(operation_ids)

    @staticmethod
    def _arc_followup_recovery_action(status: str) -> str:
        return {
            "RUNNING": "WAIT_FOR_OPERATION_TERMINAL_OR_CHECKPOINT",
            "FAILED_RETRYABLE": "RETRY_SAME_OPERATION_WITH_STABLE_IDEMPOTENCY",
            "RECONCILIATION_REQUIRED": "RECONCILE_ORIGINAL_EXTERNAL_EFFECT",
            "WAITING_APPROVAL": "OPERATOR_APPROVAL_REQUIRED",
            "FAILED_FINAL": "OPERATOR_REVIEW_OR_EXPLICIT_RERUN",
            "DEAD_LETTER": "DEAD_LETTER_REDRIVE_OR_ABORT",
            "CANCELLED": "EXPLICIT_CHECKPOINT_REREQUEST_OR_ABORT",
            "MANUAL_INTERVENTION": "REPAIR_MISSING_ARC_REVISION_EVIDENCE",
        }.get(status, "NONE")

    def _chapter_group_complete(self, snapshot: dict[str, Any]) -> bool:
        group_version = str(snapshot.get("chapter_group_plan_version") or "")
        if not group_version:
            return False
        _start, end = self.query.require_chapter_group_range(group_version)
        return int(snapshot["chapter_number"]) == end

    @staticmethod
    def _evidence_output(evidence: dict[str, Any], asset_type: str) -> dict[str, Any]:
        accepted = select_chapter_acceptance_outputs(evidence)
        if asset_type in accepted:
            return accepted[asset_type]
        matches = [
            item for item in evidence["outputs"] if item["asset_type"] == asset_type
        ]
        if len(matches) != 1:
            raise KernelError(
                "BOOK_CHAPTER_OUTPUT_MISSING",
                f"Chapter Authority produced {len(matches)} {asset_type} outputs",
            )
        return matches[0]

    @staticmethod
    def _asset_ref(item: dict[str, Any]) -> dict[str, str]:
        return {
            "asset_version_id": str(item["asset_version_id"]),
            "content_hash": str(item["content_hash"]),
        }

    @staticmethod
    def _unique_asset_refs(
        items: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, str], ...]:
        result: list[dict[str, str]] = []
        hashes: dict[str, str] = {}
        for item in items:
            version_id = str(item["asset_version_id"])
            content_hash = str(item["content_hash"])
            prior = hashes.get(version_id)
            if prior is not None:
                if prior != content_hash:
                    raise KernelError(
                        "BOOK_FOLLOWUP_INPUT_HASH_CONFLICT",
                        "one frozen AssetVersion resolved to different hashes",
                    )
                continue
            hashes[version_id] = content_hash
            result.append(
                {
                    "asset_version_id": version_id,
                    "content_hash": content_hash,
                }
            )
        return tuple(result)

    @staticmethod
    def _result(
        candidate: BookFollowupAdmissionCandidate,
        action: str,
        admission: BookFollowupAdmission,
    ) -> BookFollowupCoordinationResult:
        return BookFollowupCoordinationResult(
            candidate.book_run_id,
            candidate.chapter_request_id,
            candidate.chapter_number,
            action,
            admission.operation_id,
        )


__all__ = [
    "BookFollowupCoordinationResult",
    "PostgresBookFollowupCoordinator",
]
