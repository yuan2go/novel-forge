"""Business-oriented read projections for Book production coordination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class BookCoordinationCandidate:
    book_run_id: str
    project_id: str
    state: str
    version: int
    updated_at: datetime
    next_tick_sequence: int


class PostgresBookProductionQuery:
    """Concrete read model shared by Book supervisors and workers."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Book production query requires PostgreSQL")
        self.database_url = database_url

    def coordination_candidates(
        self,
        *,
        active_states: Iterable[str],
        limit: int,
        book_run_id: str = "",
    ) -> tuple[BookCoordinationCandidate, ...]:
        if limit <= 0:
            raise ValueError("coordination candidate limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.book_run_id, book.project_id, book.state, book.version,
                       book.updated_at,
                       COALESCE((
                           SELECT COUNT(*)
                           FROM authority_runtime_job AS job
                           WHERE job.runtime_group='book'
                             AND job.job_kind='BOOK_COORDINATION_TICK'
                             AND job.subject_kind='BOOK_RUN'
                             AND job.subject_id=book.book_run_id
                       ), 0) AS previous_tick_count
                FROM authority_book_production AS book
                WHERE book.state = ANY(%s)
                  AND (%s='' OR book.book_run_id=%s)
                  AND (
                      book.state NOT IN ('READY','COMPLETED')
                      OR (
                          book.state='READY'
                          AND book.input_mode='RESOLVED_AUTHORITY_INPUT'
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM authority_book_chapter_acceptance AS acceptance
                          JOIN authority_book_chapter_request AS request
                            ON request.chapter_request_id=acceptance.chapter_request_id
                          WHERE acceptance.book_run_id=book.book_run_id
                            AND acceptance.chapter_number=(
                                SELECT MAX(latest.chapter_number)
                                FROM authority_book_chapter_acceptance AS latest
                                WHERE latest.book_run_id=book.book_run_id
                            )
                            AND (
                                NOT EXISTS (
                                    SELECT 1
                                    FROM authority_book_followup_operation AS followup
                                    JOIN authority_operation AS operation
                                      ON operation.operation_id=followup.operation_id
                                    WHERE followup.chapter_request_id=request.chapter_request_id
                                      AND followup.followup_type='READER_OUTCOME'
                                      AND operation.status='SUCCEEDED'
                                )
                                OR (
                                    (
                                        MOD(request.chapter_number,
                                            book.light_recap_cadence)=0
                                        OR MOD(request.chapter_number,
                                               book.formal_recap_cadence)=0
                                    )
                                    AND EXISTS (
                                        SELECT 1
                                        FROM authority_book_followup_operation
                                             AS reader_followup
                                        JOIN authority_operation AS reader_operation
                                          ON reader_operation.operation_id=
                                             reader_followup.operation_id
                                        WHERE reader_followup.chapter_request_id=
                                              request.chapter_request_id
                                          AND reader_followup.followup_type=
                                              'READER_OUTCOME'
                                          AND reader_operation.status='SUCCEEDED'
                                    )
                                    AND NOT EXISTS (
                                        SELECT 1
                                        FROM authority_book_followup_operation
                                             AS recap_followup
                                        JOIN authority_operation AS recap_operation
                                          ON recap_operation.operation_id=
                                             recap_followup.operation_id
                                        WHERE recap_followup.chapter_request_id=
                                              request.chapter_request_id
                                          AND recap_followup.followup_type=
                                              'LONGFORM_RECAP'
                                          AND recap_operation.status='SUCCEEDED'
                                    )
                                )
                            )
                      )
                  )
                ORDER BY book.updated_at, book.book_run_id
                LIMIT %s
                """,
                [list(active_states), book_run_id, book_run_id, limit],
            )
            rows = tuple(uow.cursor.fetchall())
        return tuple(
            BookCoordinationCandidate(
                book_run_id=str(row[0]),
                project_id=str(row[1]),
                state=str(row[2]),
                version=int(row[3]),
                updated_at=row[4],
                next_tick_sequence=int(row[5]) + 1,
            )
            for row in rows
        )

    def latest_eligible_role_asset(
        self,
        *,
        project_id: str,
        book_id: str,
        asset_types: Iterable[str],
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
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
                [project_id, list(asset_types), book_id, book_id],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def active_plan_covering_chapter(
        self,
        *,
        project_id: str,
        book_id: str,
        contract_type: str,
        chapter_number: int,
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
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
                [project_id, book_id, contract_type],
            )
            rows = tuple(uow.cursor.fetchall())
        matches = []
        for row in rows:
            content = dict(row[2])
            if contract_type == "CHAPTER":
                applies = (
                    int(content.get("chapter_number") or content.get("chapter") or 0)
                    == chapter_number
                )
            else:
                chapter_range = content.get("chapter_range") or (
                    chapter_number,
                    chapter_number,
                )
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

    def active_chapter_group_run_id(
        self,
        *,
        project_id: str,
        book_run_id: str,
        group_plan_version_id: str = "",
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
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
                    project_id,
                    book_run_id,
                    group_plan_version_id,
                    group_plan_version_id,
                ],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def checkpointable_chapter_request_id(
        self, *, book_run_id: str, accepted_through_chapter: int
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
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
                [book_run_id, accepted_through_chapter],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def checkpoint_replan_report_id(
        self, *, book_run_id: str, accepted_through_chapter: int
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT report_id
                FROM authority_ending_reachability_report
                WHERE book_run_id=%s
                  AND evaluated_through_chapter=%s
                  AND replan_required=TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM authority_book_replan AS replan
                    JOIN authority_asset_version AS recap
                      ON recap.asset_version_id=replan.source_recap_asset_version_id
                    WHERE replan.book_run_id=
                          authority_ending_reachability_report.book_run_id
                      AND recap.content #>>
                          '{observation_snapshot,ending_reachability,report_id}' =
                          authority_ending_reachability_report.report_id
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [book_run_id, accepted_through_chapter],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def require_replan_source(self, *, book_run_id: str) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT recap.asset_version_id, request.asset_version_id,
                       operation.operation_id,
                       COALESCE(NULLIF(request_version.content->>'affected_scope',''),
                                'CHAPTER_GROUP')
                FROM authority_book_followup_operation AS followup
                JOIN authority_operation AS operation
                  ON operation.operation_id=followup.operation_id
                JOIN authority_operation_output_asset AS recap
                  ON recap.operation_id=operation.operation_id
                 AND recap.output_key='longform.recap.report'
                JOIN authority_operation_output_asset AS request
                  ON request.operation_id=operation.operation_id
                 AND request.output_key='longform.recap.replan_request'
                JOIN authority_asset_version AS request_version
                  ON request_version.asset_version_id=request.asset_version_id
                WHERE followup.book_run_id=%s
                  AND followup.followup_type='LONGFORM_RECAP'
                  AND operation.status='SUCCEEDED'
                ORDER BY followup.created_at DESC
                LIMIT 1
                """,
                [book_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_REPLAN_SOURCE_UNAVAILABLE",
                "Replan requires a latest successful Recap request",
            )
        return {
            "recap_asset_version_id": str(row[0]),
            "replan_request_asset_version_id": str(row[1]),
            "recap_operation_id": str(row[2]),
            "affected_scope": str(row[3]),
        }

    def require_input_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book_plan_version, current_volume_plan_version,
                       active_arc_plan_versions, character_state_version,
                       foreshadowing_state_version, quality_trend_version,
                       reward_ledger_version, promise_ledger_version
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s
                """,
                [snapshot_id],
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

    def require_chapter_execution_plan(
        self, planning_candidate_asset_version_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT projection.asset_version_id, projection.content_hash,
                       projection.content
                FROM authority_asset_version AS candidate
                JOIN authority_asset AS candidate_asset
                  ON candidate_asset.asset_id=candidate.asset_id
                JOIN authority_operation AS operation
                  ON operation.project_id=candidate_asset.project_id
                 AND operation.status='SUCCEEDED'
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                 AND output.output_key='story_planning.chapter_plan_projection'
                JOIN authority_asset AS asset ON asset.asset_id=output.asset_id
                 AND asset.asset_type='chapter_plan'
                JOIN authority_asset_version AS projection
                  ON projection.asset_version_id=output.asset_version_id
                WHERE candidate.asset_version_id=%s
                  AND projection.content->>
                      'source_planning_candidate_asset_version_id'=%s
                ORDER BY projection.created_at DESC
                LIMIT 2
                """,
                [
                    planning_candidate_asset_version_id,
                    planning_candidate_asset_version_id,
                ],
            )
            rows = tuple(uow.cursor.fetchall())
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

    def require_chapter_group_range(self, asset_version_id: str) -> tuple[int, int]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content->'chapter_range'
                FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None or not isinstance(row[0], list) or len(row[0]) != 2:
            raise KernelError(
                "BOOK_CHAPTER_GROUP_PLAN_INVALID",
                "Chapter request references an invalid ChapterGroup Plan",
            )
        return int(row[0][0]), int(row[0][1])

    def ending_reachability(
        self, *, book_run_id: str, chapter_number: int
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT report_id, replan_required, ending_contract_reachable,
                       remaining_chapter_budget, reasons, report_hash
                FROM authority_ending_reachability_report
                WHERE book_run_id=%s AND evaluated_through_chapter=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [book_run_id, chapter_number],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return {}
        return {
            "report_id": str(row[0]),
            "replan_required": bool(row[1]),
            "ending_contract_reachable": bool(row[2]),
            "remaining_chapter_budget": int(row[3]),
            "reasons": list(row[4]),
            "report_hash": str(row[5]),
        }

    def latest_accepted_chapter_request_id(
        self, *, book_run_id: str, project_id: str
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT request.chapter_request_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                WHERE acceptance.book_run_id=%s AND acceptance.project_id=%s
                ORDER BY acceptance.chapter_number DESC
                LIMIT 1
                """,
                [book_run_id, project_id],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def followup_operation_id(
        self, *, chapter_request_id: str, followup_type: str
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
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

    def operation_status(self, *, operation_id: str, project_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        return str(state["status"])

    def previous_reader_state(self, *, book_run_id: str, chapter_number: int) -> str:
        if chapter_number <= 1:
            return "NONE"
        with AuthorityUnitOfWork(self.database_url) as uow:
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
                [book_run_id, chapter_number - 1],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else "NONE"

    def require_followup_output(
        self, *, operation_id: str, project_id: str, output_key: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
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


__all__ = ["BookCoordinationCandidate", "PostgresBookProductionQuery"]
