"""Business-oriented read projections for Book production coordination."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.book_authority.production import (
    actionable_book_production_states,
    book_production_state_semantics,
)
from novel_forge.modules.book_authority.input_resolver import (
    project_current_plan_cursor,
)
from novel_forge.modules.story_design_authority import required_qualification_profiles
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class BookCoordinationCandidate:
    book_run_id: str
    project_id: str
    state: str
    version: int
    updated_at: datetime
    next_tick_sequence: int


@dataclass(frozen=True, slots=True)
class BookFollowupAdmissionCandidate:
    book_run_id: str
    project_id: str
    chapter_request_id: str
    chapter_number: int
    reader_operation_id: str
    reader_status: str
    recap_operation_id: str


@dataclass(frozen=True, slots=True)
class BookProgressProjection:
    """Operational read model; never owns or advances Book production state."""

    book_run_id: str
    project_id: str
    state: str
    state_class: str
    accepted_through_chapter: int
    target_chapter_count: int
    last_narrative_progress_at: datetime | None
    next_expected_transition: str
    blocking_class: str
    blocking_reason: str
    blocking_operation_id: str
    blocking_since: datetime | None
    wake_condition: str
    retry_count: int
    max_attempts: int
    next_retry_at: datetime | None
    active_chapter_number: int | None
    active_chapter_request_id: str
    active_operation_id: str
    active_operation_status: str
    next_chapter_number: int
    next_chapter_request_id: str
    next_chapter_dispatch_state: str
    pending_sidecar_backlog: dict[str, Any]
    authoritative_repair_status: str = "NOT_REQUIRED"
    authoritative_repair_next_chapter: int | None = None
    authoritative_repair_target_chapter: int | None = None
    authoritative_repair_last_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PostgresBookProductionQuery:
    """Concrete read model shared by Book supervisors and workers."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Book production query requires PostgreSQL")
        self.database_url = database_url

    def coordination_candidates(
        self,
        *,
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
                  AND NOT EXISTS (
                      SELECT 1
                      FROM authority_book_projection_repair AS repair
                      WHERE repair.book_run_id=book.book_run_id
                        AND repair.authoritative_status<>
                            'AUTHORITATIVE_REPAIR_COMPLETE'
                  )
                  AND (
                      book.state <> 'READY'
                      OR book.input_mode='RESOLVED_AUTHORITY_INPUT'
                  )
                ORDER BY book.updated_at, book.book_run_id
                LIMIT %s
                """,
                [
                    list(actionable_book_production_states()),
                    book_run_id,
                    book_run_id,
                    limit,
                ],
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

    def progress(self, *, book_run_id: str) -> BookProgressProjection:
        """Project liveness from PostgreSQL Authority without inventing Authority."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.book_run_id, book.project_id, book.state,
                       book.accepted_through_chapter, book.target_chapter_count,
                       book.active_chapter_number,
                       COALESCE(book.active_chapter_request_id, ''),
                       book.paused_reason, book.failure_reason, book.updated_at,
                       COALESCE(request.chapter_root_operation_id, ''),
                       COALESCE(request.status_reference, ''), request.updated_at,
                       COALESCE(operation.status, '')
                FROM authority_book_production AS book
                LEFT JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=book.active_chapter_request_id
                LEFT JOIN authority_operation AS operation
                  ON operation.operation_id=request.chapter_root_operation_id
                WHERE book.book_run_id=%s
                """,
                [book_run_id],
            )
            book = uow.cursor.fetchone()
            if book is None:
                raise KernelError(
                    "BOOK_RUN_NOT_FOUND", "Book Authority run does not exist"
                )
            uow.cursor.execute(
                """
                SELECT MAX(created_at)
                FROM authority_book_chapter_acceptance
                WHERE book_run_id=%s AND status='COMMITTED'
                """,
                [book_run_id],
            )
            last_narrative_progress_at = uow.cursor.fetchone()[0]
            next_chapter = int(book[3]) + 1
            uow.cursor.execute(
                """
                SELECT chapter_request_id, status_reference,
                       COALESCE(chapter_root_operation_id, '')
                FROM authority_book_chapter_request
                WHERE book_run_id=%s AND chapter_number=%s
                ORDER BY created_at DESC LIMIT 1
                """,
                [book_run_id, next_chapter],
            )
            next_request = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT group_run_id, state
                FROM authority_chapter_group_production
                WHERE book_run_id=%s
                  AND state IN (
                      'PREPARING','READY','CHAPTER_RUNNING',
                      'CLOSURE_PENDING','PAUSED'
                  )
                ORDER BY created_at DESC LIMIT 1
                """,
                [book_run_id],
            )
            active_group = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT status, attempt_count, max_attempts, available_at,
                       COALESCE(last_error, '{}'::jsonb), updated_at
                FROM authority_runtime_job
                WHERE runtime_group='book'
                  AND job_kind='BOOK_COORDINATION_TICK'
                  AND subject_kind='BOOK_RUN' AND subject_id=%s
                ORDER BY created_at DESC LIMIT 1
                """,
                [book_run_id],
            )
            runtime_job = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT authoritative_status, next_chapter,
                       target_accepted_through_chapter, last_error
                FROM authority_book_projection_repair
                WHERE book_run_id=%s
                """,
                [book_run_id],
            )
            projection_repair = uow.cursor.fetchone()
            active_operation_id = str(book[10])
            attempt = None
            if active_operation_id:
                uow.cursor.execute(
                    """
                    SELECT attempt_number, max_attempts, status,
                           COALESCE(error, '{}'::jsonb),
                           COALESCE(finished_at, started_at, queued_at)
                    FROM authority_attempt
                    WHERE operation_id=%s
                    ORDER BY attempt_number DESC LIMIT 1
                    """,
                    [active_operation_id],
                )
                attempt = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT link.followup_type, operation.status, COUNT(*)
                FROM authority_book_followup_operation AS link
                JOIN authority_operation AS operation
                  ON operation.operation_id=link.operation_id
                WHERE link.book_run_id=%s
                  AND operation.status NOT IN ('SUCCEEDED','CANCELLED')
                GROUP BY link.followup_type, operation.status
                ORDER BY link.followup_type, operation.status
                """,
                [book_run_id],
            )
            sidecar_status_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT status, COUNT(*)
                FROM authority_runtime_job
                WHERE runtime_group='book_followup'
                  AND job_kind='BOOK_FOLLOWUP_ADMISSION'
                  AND project_id=%s
                  AND input_snapshot->>'book_run_id'=%s
                  AND status NOT IN ('SUCCEEDED','CANCELLED')
                GROUP BY status ORDER BY status
                """,
                [str(book[1]), book_run_id],
            )
            sidecar_admission_job_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_book_chapter_acceptance AS acceptance
                WHERE acceptance.book_run_id=%s AND acceptance.status='COMMITTED'
                  AND NOT EXISTS (
                    SELECT 1 FROM authority_book_followup_operation AS followup
                    WHERE followup.chapter_request_id=acceptance.chapter_request_id
                      AND followup.followup_type='READER_OUTCOME'
                  )
                """,
                [book_run_id],
            )
            reader_admission_pending = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_production AS production
                  ON production.book_run_id=acceptance.book_run_id
                WHERE acceptance.book_run_id=%s AND acceptance.status='COMMITTED'
                  AND (
                    MOD(
                        acceptance.chapter_number,
                        COALESCE(
                            NULLIF(
                                acceptance.evidence #>>
                                '{followup_snapshot,light_recap_cadence}',
                                ''
                            )::integer,
                            production.light_recap_cadence
                        )
                    )=0
                    OR MOD(
                        acceptance.chapter_number,
                        COALESCE(
                            NULLIF(
                                acceptance.evidence #>>
                                '{followup_snapshot,formal_recap_cadence}',
                                ''
                            )::integer,
                            production.formal_recap_cadence
                        )
                    )=0
                    OR EXISTS (
                      SELECT 1
                      FROM authority_chapter_group_chapter AS child
                      JOIN authority_chapter_group_production AS group_run
                        ON group_run.group_run_id=child.group_run_id
                      WHERE child.chapter_request_id=acceptance.chapter_request_id
                        AND acceptance.chapter_number=group_run.chapter_end
                    )
                  )
                  AND EXISTS (
                    SELECT 1
                    FROM authority_book_followup_operation AS reader
                    JOIN authority_operation AS reader_operation
                      ON reader_operation.operation_id=reader.operation_id
                    WHERE reader.chapter_request_id=acceptance.chapter_request_id
                      AND reader.followup_type='READER_OUTCOME'
                      AND reader_operation.status='SUCCEEDED'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM authority_book_followup_operation AS recap
                    WHERE recap.chapter_request_id=acceptance.chapter_request_id
                      AND recap.followup_type='LONGFORM_RECAP'
                  )
                """,
                [book_run_id],
            )
            recap_admission_pending = int(uow.cursor.fetchone()[0])

        state = str(book[2])
        semantics = book_production_state_semantics(state)
        blocking_operation_id = active_operation_id
        blocking_since = book[12] or book[9]
        retry_count = int(attempt[0]) if attempt is not None else 0
        max_attempts = int(attempt[1]) if attempt is not None else 0
        next_retry_at = None
        error: dict[str, Any] = dict(attempt[3] or {}) if attempt is not None else {}
        if runtime_job is not None:
            if not blocking_operation_id and str(runtime_job[0]) in {
                "CLAIMED",
                "RUNNING",
                "CHECKPOINTED",
                "RETRY_WAIT",
                "FAILED",
                "DEAD_LETTER",
            }:
                blocking_since = runtime_job[5]
            if retry_count == 0:
                retry_count = int(runtime_job[1])
                max_attempts = int(runtime_job[2])
                error = dict(runtime_job[4] or {})
            if str(runtime_job[0]) == "RETRY_WAIT":
                next_retry_at = runtime_job[3]
        blocking_reason = str(book[7] or book[8] or "")
        if not blocking_reason and error:
            blocking_reason = str(
                error.get("message") or error.get("code") or error
            )
        if not blocking_reason:
            blocking_reason = semantics.blocking_reason
        if semantics.blocking_class == "NONE":
            blocking_operation_id = ""
            blocking_since = None
        sidecar_by_status: dict[str, int] = {
            f"{str(row[0]).lower()}:{str(row[1]).lower()}": int(row[2])
            for row in sidecar_status_rows
        }
        admission_jobs_by_status: dict[str, int] = {
            str(row[0]).lower(): int(row[1])
            for row in sidecar_admission_job_rows
        }
        sidecar_backlog = {
            "blocking": False,
            "reader_admission_pending": reader_admission_pending,
            "recap_admission_pending": recap_admission_pending,
            "admission_runtime_job_status_counts": admission_jobs_by_status,
            "operation_status_counts": sidecar_by_status,
            "total": (
                reader_admission_pending
                + recap_admission_pending
                + sum(sidecar_by_status.values())
            ),
        }
        next_request_id = str(next_request[0]) if next_request is not None else ""
        next_dispatch_state = (
            str(next_request[1]) if next_request is not None else "NOT_CREATED"
        )
        next_expected_transition = semantics.next_expected_transition
        if state == "READY" and next_chapter > int(book[4]):
            next_expected_transition = (
                "CLOSE_CHAPTER_GROUP"
                if active_group is not None
                and str(active_group[1]) == "CLOSURE_PENDING"
                else "COMPLETE_BOOK_PRODUCTION"
            )
        return BookProgressProjection(
            book_run_id=str(book[0]),
            project_id=str(book[1]),
            state=state,
            state_class=semantics.state_class.value,
            accepted_through_chapter=int(book[3]),
            target_chapter_count=int(book[4]),
            last_narrative_progress_at=last_narrative_progress_at,
            next_expected_transition=next_expected_transition,
            blocking_class=semantics.blocking_class,
            blocking_reason=blocking_reason,
            blocking_operation_id=blocking_operation_id,
            blocking_since=blocking_since,
            wake_condition=semantics.wake_condition,
            retry_count=retry_count,
            max_attempts=max_attempts,
            next_retry_at=next_retry_at,
            active_chapter_number=(int(book[5]) if book[5] is not None else None),
            active_chapter_request_id=str(book[6]),
            active_operation_id=active_operation_id,
            active_operation_status=str(book[13]),
            next_chapter_number=next_chapter,
            next_chapter_request_id=next_request_id,
            next_chapter_dispatch_state=next_dispatch_state,
            pending_sidecar_backlog=sidecar_backlog,
            authoritative_repair_status=(
                str(projection_repair[0])
                if projection_repair is not None
                else "NOT_REQUIRED"
            ),
            authoritative_repair_next_chapter=(
                int(projection_repair[1])
                if projection_repair is not None
                else None
            ),
            authoritative_repair_target_chapter=(
                int(projection_repair[2])
                if projection_repair is not None
                else None
            ),
            authoritative_repair_last_error=(
                dict(projection_repair[3] or {})
                if projection_repair is not None
                else None
            ),
        )

    def governance_action_versions(
        self, *, project_id: str, input_version_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Project governed overrides inherited by the supplied plan inputs."""
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s::text[])
                """,
                [project_id, list(input_version_ids)],
            )
            contents = [dict(row[0]) for row in uow.cursor.fetchall()]
        actions: list[str] = []
        for content in contents:
            envelope = content.get("constraint_envelope")
            policy = (
                envelope.get("narrative_load_policy")
                if isinstance(envelope, dict)
                else content.get("narrative_load_policy")
            )
            if not isinstance(policy, dict):
                continue
            for override in policy.get("governed_overrides") or ():
                if isinstance(override, dict):
                    asset_version_id = str(
                        override.get("governance_action_asset_version_id") or ""
                    )
                    if asset_version_id and asset_version_id not in actions:
                        actions.append(asset_version_id)
        return tuple(actions)

    def followup_admission_candidates(
        self, *, limit: int
    ) -> tuple[BookFollowupAdmissionCandidate, ...]:
        """Return durable acceptance heads needing advisory follow-up admission."""

        if limit <= 0:
            raise ValueError("follow-up admission candidate limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.book_run_id, acceptance.project_id,
                       acceptance.chapter_request_id, acceptance.chapter_number,
                       COALESCE(reader.operation_id, ''),
                       COALESCE(reader_operation.status, ''),
                       COALESCE(recap.operation_id, '')
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_production AS book
                  ON book.book_run_id=acceptance.book_run_id
                LEFT JOIN authority_book_followup_operation AS reader
                  ON reader.chapter_request_id=acceptance.chapter_request_id
                 AND reader.followup_type='READER_OUTCOME'
                LEFT JOIN authority_operation AS reader_operation
                  ON reader_operation.operation_id=reader.operation_id
                LEFT JOIN authority_book_followup_operation AS recap
                  ON recap.chapter_request_id=acceptance.chapter_request_id
                 AND recap.followup_type='LONGFORM_RECAP'
                WHERE acceptance.status='COMMITTED'
                  AND (
                      reader.operation_id IS NULL
                      OR (
                          reader_operation.status='SUCCEEDED'
                          AND recap.operation_id IS NULL
                          AND (
                              MOD(
                                  acceptance.chapter_number,
                                  COALESCE(
                                      NULLIF(
                                          acceptance.evidence #>>
                                          '{followup_snapshot,light_recap_cadence}',
                                          ''
                                      )::integer,
                                      book.light_recap_cadence
                                  )
                              )=0
                              OR MOD(
                                  acceptance.chapter_number,
                                  COALESCE(
                                      NULLIF(
                                          acceptance.evidence #>>
                                          '{followup_snapshot,formal_recap_cadence}',
                                          ''
                                      )::integer,
                                      book.formal_recap_cadence
                                  )
                              )=0
                              OR EXISTS (
                                  SELECT 1
                                  FROM authority_chapter_group_chapter AS child
                                  JOIN authority_chapter_group_production AS group_run
                                    ON group_run.group_run_id=child.group_run_id
                                  WHERE child.chapter_request_id=
                                        acceptance.chapter_request_id
                                    AND acceptance.chapter_number=
                                        group_run.chapter_end
                              )
                              OR EXISTS (
                                  SELECT 1
                                  FROM authority_ending_reachability_report AS report
                                  WHERE report.book_run_id=acceptance.book_run_id
                                    AND report.evaluated_through_chapter=
                                        acceptance.chapter_number
                                    AND report.replan_required=TRUE
                              )
                              OR EXISTS (
                                  SELECT 1
                                  FROM authority_arc_checkpoint_followup AS arc_followup
                                  WHERE arc_followup.book_run_id=acceptance.book_run_id
                                    AND arc_followup.accepted_through_chapter=
                                        acceptance.chapter_number
                                    AND arc_followup.status IN (
                                        'READY','RUNNING','FAILED_RETRYABLE'
                                    )
                              )
                          )
                      )
                  )
                ORDER BY acceptance.chapter_number, acceptance.created_at,
                         acceptance.chapter_request_id
                LIMIT %s
                """,
                [limit],
            )
            rows = uow.cursor.fetchall()
        return tuple(
            BookFollowupAdmissionCandidate(
                book_run_id=str(row[0]),
                project_id=str(row[1]),
                chapter_request_id=str(row[2]),
                chapter_number=int(row[3]),
                reader_operation_id=str(row[4]),
                reader_status=str(row[5]),
                recap_operation_id=str(row[6]),
            )
            for row in rows
        )

    def arc_checkpoint_followup(
        self, *, book_run_id: str, chapter_number: int
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT followup.followup_id, followup.decision,
                       followup.reason_evidence,
                       followup.target_plan_version_ids,
                       followup.checkpoint_id, followup.projection_set_id,
                       followup.status
                FROM authority_arc_checkpoint_followup AS followup
                WHERE followup.book_run_id=%s
                  AND followup.accepted_through_chapter=%s
                  AND followup.status IN (
                      'READY','RUNNING','PROPOSED','FAILED_RETRYABLE',
                      'RECONCILIATION_REQUIRED'
                  )
                ORDER BY followup.created_at, followup.followup_id
                LIMIT 1
                """,
                [book_run_id, chapter_number],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return {
            "followup_id": str(row[0]),
            "decision": str(row[1]),
            "reason_evidence": dict(row[2] or {}),
            "target_plan_version_ids": list(row[3] or []),
            "checkpoint_id": str(row[4]),
            "projection_set_id": str(row[5]),
            "status": str(row[6]),
        }

    def require_accepted_followup_snapshot(
        self, *, chapter_request_id: str
    ) -> dict[str, Any]:
        """Load the immutable accepted head for a delayed advisory operation."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.book_run_id, acceptance.project_id,
                       acceptance.chapter_number,
                       acceptance.chapter_outcome_asset_version_id,
                       acceptance.story_state_asset_version_id,
                       acceptance.canon_snapshot_asset_version_id,
                       acceptance.acceptance_operation_id, acceptance.evidence,
                       request.chapter_plan_version,
                       request.parent_group_version_id,
                       request.production_profile_version,
                       request.command_payload,
                       request.chapter_root_operation_id,
                       book.workspace_id, book.book_id,
                       book.book_design_version, book.book_plan_version,
                       book.longform_context_versions,
                       COALESCE(book.input_snapshot_id, ''),
                       book.light_recap_cadence, book.formal_recap_cadence
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                JOIN authority_book_production AS book
                  ON book.book_run_id=acceptance.book_run_id
                WHERE acceptance.chapter_request_id=%s
                  AND acceptance.status='COMMITTED'
                """,
                [chapter_request_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTANCE_MISSING",
                "advisory follow-up requires a committed Chapter acceptance",
            )
        evidence = dict(row[7] or {})
        frozen = dict(evidence.get("followup_snapshot") or {})
        command = dict(row[11] or {})
        context_refs = dict(command.get("context_version_refs") or {})
        longform_refs = dict(row[17] or {})
        if not frozen:
            frozen = {
                "schema_version": "book-followup-accepted-snapshot-v1",
                "observed_through_chapter": int(row[2]),
                "book_production_input_snapshot_id": str(
                    context_refs.get("book_production_input_snapshot_id")
                    or row[18]
                    or ""
                ),
                "book_design_version": str(
                    context_refs.get("book_design_version") or row[15]
                ),
                "book_plan_version": str(
                    context_refs.get("book_plan_version") or row[16]
                ),
                "volume_plan_version": str(
                    context_refs.get("volume_plan_version")
                    or longform_refs.get("volume_plan_version")
                    or ""
                ),
                "arc_plan_versions": list(
                    context_refs.get("arc_plan_versions")
                    or longform_refs.get("arc_plan_versions")
                    or ()
                ),
                "chapter_group_plan_version": str(
                    context_refs.get("chapter_group_plan_version") or row[9] or ""
                ),
                "chapter_plan_version": str(row[8]),
                "production_profile_version": str(row[10]),
                "light_recap_cadence": int(row[19]),
                "formal_recap_cadence": int(row[20]),
                "reader_segment_version": str(
                    context_refs.get("reader_segment_version")
                    or longform_refs.get("reader_segment_version")
                    or ""
                ),
                "reader_contract_version": str(
                    context_refs.get("reader_contract_version")
                    or longform_refs.get("reader_contract_version")
                    or ""
                ),
                "platform_profile_version": str(
                    context_refs.get("platform_profile_version")
                    or longform_refs.get("platform_profile_version")
                    or ""
                ),
                "quality_trend_version": str(
                    context_refs.get("quality_trend_version")
                    or longform_refs.get("quality_trend_version")
                    or ""
                ),
                "accepted_chapter_outcome_version": str(row[3]),
                "accepted_story_state_version": str(row[4]),
                "accepted_canon_snapshot_version": str(row[5]),
                "acceptance_operation_id": str(row[6]),
                "chapter_root_operation_id": str(row[12]),
            }
        frozen.update(
            {
                "book_run_id": str(row[0]),
                "project_id": str(row[1]),
                "workspace_id": str(row[13]),
                "book_id": str(row[14]),
                "chapter_request_id": chapter_request_id,
                "chapter_number": int(row[2]),
            }
        )
        required = (
            "book_production_input_snapshot_id",
            "book_design_version",
            "book_plan_version",
            "volume_plan_version",
            "arc_plan_versions",
            "chapter_plan_version",
            "production_profile_version",
            "light_recap_cadence",
            "formal_recap_cadence",
            "reader_segment_version",
            "reader_contract_version",
            "platform_profile_version",
            "quality_trend_version",
            "accepted_chapter_outcome_version",
            "accepted_story_state_version",
            "accepted_canon_snapshot_version",
            "acceptance_operation_id",
            "chapter_root_operation_id",
        )
        missing = [name for name in required if frozen.get(name) in (None, "", [])]
        if missing:
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_INCOMPLETE",
                "accepted advisory snapshot is missing: " + ", ".join(missing),
            )
        if int(frozen.get("observed_through_chapter") or 0) != int(row[2]):
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_DRIFT",
                "advisory snapshot cursor differs from Chapter acceptance",
            )
        immutable_identities = {
            "chapter_plan_version": str(row[8]),
            "production_profile_version": str(row[10]),
            "accepted_chapter_outcome_version": str(row[3]),
            "accepted_story_state_version": str(row[4]),
            "accepted_canon_snapshot_version": str(row[5]),
            "acceptance_operation_id": str(row[6]),
            "chapter_root_operation_id": str(row[12]),
        }
        if any(
            str(frozen.get(name) or "") != expected
            for name, expected in immutable_identities.items()
        ):
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_DRIFT",
                "advisory snapshot identity differs from committed acceptance",
            )
        if (
            int(frozen["light_recap_cadence"]) <= 0
            or int(frozen["formal_recap_cadence"]) <= 0
        ):
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_INCOMPLETE",
                "accepted advisory snapshot has an invalid Recap cadence",
            )
        return frozen

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

    def require_replan_source(self, *, book_run_id: str) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT recap.asset_version_id, request.asset_version_id,
                       operation.operation_id,
                       COALESCE(NULLIF(request_version.content->>'affected_scope',''),
                                'CHAPTER_GROUP'),
                       COALESCE(
                           request_version.content #>> '{target_plan_version_ids,0}',
                           ''
                       )
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
            "target_asset_version_id": str(row[4]),
        }

    def require_input_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book_plan_version, current_volume_plan_version,
                       volume_portfolio_plan_versions,
                       arc_portfolio_plan_versions,
                       current_relevant_arc_plan_versions,
                       active_arc_plan_versions, character_state_version,
                       foreshadowing_state_version, quality_trend_version,
                       reward_ledger_version, promise_ledger_version,
                       COALESCE(initial_story_state_version, ''),
                       COALESCE(initial_canon_snapshot_version, ''),
                       design_admission_status, design_qualification,
                       design_qualification_hash
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
            "volume_portfolio_plan_versions",
            "arc_portfolio_plan_versions",
            "current_relevant_arc_plan_versions",
            "active_arc_plan_versions",
            "character_state_version",
            "foreshadowing_state_version",
            "quality_trend_version",
            "reward_ledger_version",
            "promise_ledger_version",
            "initial_story_state_version",
            "initial_canon_snapshot_version",
            "design_admission_status",
            "design_qualification",
            "design_qualification_hash",
        )
        return dict(zip(keys, row, strict=True))

    def require_cursor_plan_projection(
        self, *, snapshot_id: str, chapter_cursor: int
    ) -> dict[str, Any]:
        snapshot = self.require_input_snapshot(snapshot_id)
        volume_ids = tuple(
            str(item) for item in snapshot["volume_portfolio_plan_versions"]
        )
        arc_ids = tuple(str(item) for item in snapshot["arc_portfolio_plan_versions"])
        portfolio_ids = (*volume_ids, *arc_ids)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.contract_type,
                       binding.freshness, version.content, version.content_hash
                FROM active_story_plan_version AS active
                JOIN story_plan_binding AS binding
                  ON binding.binding_id=active.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [list(portfolio_ids)],
            )
            rows = uow.cursor.fetchall()
        by_id = {str(row[0]): row for row in rows}
        if (
            len(portfolio_ids) != len(set(portfolio_ids))
            or set(by_id) != set(portfolio_ids)
            or any(str(row[2]) != "CURRENT" for row in rows)
            or any(
                str(by_id[item][1]) != expected
                for expected, ids in (("VOLUME", volume_ids), ("ARC", arc_ids))
                for item in ids
            )
        ):
            raise KernelError(
                "BOOK_INPUT_PORTFOLIO_STALE",
                "frozen global Volume/Arc portfolio is no longer current and complete",
            )
        volumes = [
            {"asset_version_id": item, "content": dict(by_id[item][3])}
            for item in volume_ids
        ]
        arcs = [
            {"asset_version_id": item, "content": dict(by_id[item][3])}
            for item in arc_ids
        ]
        volume, relevant_arcs = project_current_plan_cursor(
            volumes=volumes,
            arcs=arcs,
            chapter_cursor=chapter_cursor,
        )
        return {
            "chapter_cursor": chapter_cursor,
            "volume_plan_version": str(volume["asset_version_id"]),
            "arc_plan_versions": relevant_arcs,
        }

    def require_chapter_production_admission(
        self,
        *,
        snapshot_id: str,
        chapter_group_plan_version_id: str,
        chapter_plan_version_id: str,
        chapter_number: int,
        accepted_through_chapter: int,
        active_story_state_version_id: str = "",
        active_canon_snapshot_version_id: str = "",
    ) -> dict[str, Any]:
        if chapter_number != accepted_through_chapter + 1:
            raise KernelError(
                "CHAPTER_PRODUCTION_SEQUENCE_INVALID",
                "Chapter production admission must target the next unaccepted chapter",
            )
        cursor_projection = self.require_cursor_plan_projection(
            snapshot_id=snapshot_id,
            chapter_cursor=chapter_number,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT snapshot.project_id, snapshot.book_id,
                       snapshot.expected_book_version,
                       snapshot.design_admission_status,
                       snapshot.design_qualification,
                       snapshot.design_qualification_hash,
                       snapshot.book_design_version,
                       snapshot.book_plan_version,
                       snapshot.current_volume_plan_version,
                       snapshot.current_relevant_arc_plan_versions
                FROM authority_book_production_input_snapshot AS snapshot
                WHERE snapshot.snapshot_id=%s
                """,
                [snapshot_id],
            )
            snapshot = uow.cursor.fetchone()
            if snapshot is None or str(snapshot[3]) != "LONGFORM_DESIGN_QUALIFIED":
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_REQUIRED",
                    "Chapter production requires a qualified Book input snapshot",
                )
            global_qualification = dict(snapshot[4])
            if global_qualification.get(
                "admission"
            ) != "LONGFORM_DESIGN_QUALIFIED" or canonical_hash(
                global_qualification
            ) != str(snapshot[5]):
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_CORRUPT",
                    "Book input design qualification failed its content hash",
                )
            global_receipts = global_qualification.get("receipts")
            if not isinstance(global_receipts, list) or not global_receipts:
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_CORRUPT",
                    "Book input design qualification has no layer receipts",
                )
            global_version_ids = sorted(
                {
                    str(item.get("asset_version_id") or "")
                    for item in global_receipts
                    if isinstance(item, dict)
                }
            )
            if "" in global_version_ids:
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_CORRUPT",
                    "Book input design qualification has an empty asset identity",
                )
            uow.cursor.execute(
                """
                SELECT asset_version_id, design_layer, profile_hash,
                       evaluation_hash, qualification_hash
                FROM authority_current_narrative_design_qualification AS qualification
                JOIN authority_operation AS operation
                  ON operation.operation_id=qualification.source_operation_id
                WHERE qualification.project_id=%s AND qualification.book_id=%s
                  AND qualification.asset_version_id=ANY(%s)
                  AND qualification.freshness='CURRENT'
                  AND operation.status IN ('WAITING_GATE', 'SUCCEEDED')
                """,
                [str(snapshot[0]), str(snapshot[1]), global_version_ids],
            )
            current_global = {
                (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))
                for row in uow.cursor.fetchall()
            }
            expected_global = {
                (
                    str(item.get("asset_version_id") or ""),
                    str(item.get("design_layer") or ""),
                    str(item.get("profile_hash") or ""),
                    str(item.get("evaluation_hash") or ""),
                    str(item.get("qualification_hash") or ""),
                )
                for item in global_receipts
                if isinstance(item, dict)
            }
            if current_global != expected_global:
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_STALE",
                    "Book input design qualification no longer names current active design",
                )
            uow.cursor.execute(
                """
                SELECT binding.contract_type, binding.asset_version_id,
                       COALESCE(binding.parent_version_id, ''),
                       binding.execution_scope, binding.freshness,
                       version.content
                FROM active_story_plan_version AS active
                JOIN story_plan_binding AS binding
                  ON binding.binding_id=active.binding_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [
                    str(snapshot[0]),
                    str(snapshot[1]),
                    [chapter_group_plan_version_id, chapter_plan_version_id],
                ],
            )
            plan_rows = uow.cursor.fetchall()
            plans = {str(row[0]): row for row in plan_rows}
            if set(plans) != {"CHAPTER_GROUP", "CHAPTER"}:
                raise KernelError(
                    "CHAPTER_PRODUCTION_DESIGN_INCOMPLETE",
                    "active Scheduling and Chapter design are required",
                )
            group = plans["CHAPTER_GROUP"]
            chapter = plans["CHAPTER"]
            if (
                str(group[1]) != chapter_group_plan_version_id
                or str(chapter[1]) != chapter_plan_version_id
                or str(group[2]) != str(cursor_projection["volume_plan_version"])
                or str(chapter[2]) != chapter_group_plan_version_id
                or str(group[3]) != "FROZEN"
                or str(chapter[3]) != "FROZEN"
                or str(group[4]) != "CURRENT"
                or str(chapter[4]) != "CURRENT"
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_DESIGN_STALE",
                    "Scheduling or Chapter design is not the current frozen plan",
                )
            chapter_content = dict(chapter[5])
            group_content = dict(group[5])
            group_range = group_content.get("chapter_range")
            if (
                int(chapter_content.get("chapter_number") or 0) != chapter_number
                or not isinstance(group_range, list)
                or len(group_range) != 2
                or not int(group_range[0]) <= chapter_number <= int(group_range[1])
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_DESIGN_SCOPE_INVALID",
                    "Scheduling and Chapter design do not cover the target chapter",
                )
            matrix_rows = [
                item
                for item in group_content.get("chapter_function_matrix") or ()
                if isinstance(item, dict)
                and int(item.get("chapter_number") or 0) == chapter_number
            ]
            if len(matrix_rows) != 1:
                raise KernelError(
                    "CHAPTER_PRODUCTION_SCHEDULE_ROW_INVALID",
                    "Narrative Scheduling must contain one row for the target Chapter",
                )
            schedule_row = matrix_rows[0]
            scheduled_arcs = {
                str(item.get("arc_plan_version_id") or "")
                for item in schedule_row.get("arc_cadence") or ()
                if isinstance(item, dict) and str(item.get("action") or "") != "DORMANT"
            }
            if (
                not scheduled_arcs
                or "" in scheduled_arcs
                or not scheduled_arcs.issubset(
                    set(cursor_projection["arc_plan_versions"])
                )
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_ARC_PROJECTION_STALE",
                    "Scheduling Arc cadence must be a subset of the cursor-projected global portfolio",
                )
            scheduled_fields = (
                "primary_function",
                "secondary_functions",
                "required_state_delta",
                "promise_action",
                "foreshadow_action",
                "reward_action",
                "ending_hook",
                "prohibited_outcomes",
                "narrative_density",
                "arc_cadence",
                "obligation_actions",
            )
            if any(
                canonical_hash(schedule_row.get(field))
                != canonical_hash(chapter_content.get(field))
                for field in scheduled_fields
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_SCHEDULE_DRIFT",
                    "Chapter Execution Plan differs from its active Scheduling row",
                )
            scheduled_experience = schedule_row.get("reader_experience")
            chapter_experience = chapter_content.get("reader_experience")
            if not isinstance(scheduled_experience, dict) or not isinstance(
                chapter_experience, dict
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_SCHEDULE_DRIFT",
                    "Scheduling and Chapter design require typed Reader Experience",
                )
            if any(
                canonical_hash(scheduled_experience.get(field))
                != canonical_hash(chapter_experience.get(field))
                for field in ("target_emotion", "reward_mode")
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_SCHEDULE_DRIFT",
                    "Chapter Reader Experience changed its scheduled target",
                )
            boundary = dict(
                (chapter_content.get("constraint_envelope") or {}).get(
                    "accepted_state_boundary"
                )
                or {}
            )
            if int(boundary.get("accepted_through_chapter") or 0) != (
                accepted_through_chapter
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_NARRATIVE_STATE_STALE",
                    "Chapter design was derived from another accepted-state cursor",
                )
            frozen_inputs = {
                str(item.get("role") or ""): str(item.get("asset_version_id") or "")
                for item in chapter_content.get("frozen_inputs") or ()
                if isinstance(item, dict)
            }
            if accepted_through_chapter > 0 and (
                frozen_inputs.get("story_state") != active_story_state_version_id
                or frozen_inputs.get("canon_snapshot")
                != active_canon_snapshot_version_id
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_NARRATIVE_STATE_STALE",
                    "Chapter design is not bound to current accepted Story State and Canon",
                )
            expected_receipts = []
            for stage, asset_version_id in (
                ("chapter_group_plan.generate", chapter_group_plan_version_id),
                ("chapter_plan.generate", chapter_plan_version_id),
            ):
                expected_receipts.extend(
                    (asset_version_id, profile)
                    for profile in required_qualification_profiles(stage)
                )
            uow.cursor.execute(
                """
                SELECT asset_version_id, design_layer, profile_id,
                       profile_version, profile_hash, qualification_hash,
                       evaluation_hash, evaluator_execution_class,
                       source_operation_id
                FROM authority_current_narrative_design_qualification AS qualification
                JOIN authority_operation AS operation
                  ON operation.operation_id=qualification.source_operation_id
                WHERE qualification.project_id=%s AND qualification.book_id=%s
                  AND qualification.asset_version_id=ANY(%s)
                  AND qualification.freshness='CURRENT'
                  AND operation.status IN ('WAITING_GATE', 'SUCCEEDED')
                ORDER BY asset_version_id, design_layer
                """,
                [
                    str(snapshot[0]),
                    str(snapshot[1]),
                    [chapter_group_plan_version_id, chapter_plan_version_id],
                ],
            )
            rows = uow.cursor.fetchall()
        by_identity: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            by_identity.setdefault((str(row[0]), str(row[1])), []).append(row)
        receipts: list[dict[str, Any]] = []
        for asset_version_id, profile in expected_receipts:
            matches = by_identity.get((asset_version_id, profile.layer.value), [])
            if len(matches) != 1:
                raise KernelError(
                    "CHAPTER_PRODUCTION_QUALIFICATION_INCOMPLETE",
                    f"{profile.layer.value} requires one current qualification",
                )
            row = matches[0]
            if tuple(str(item) for item in row[2:5]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "CHAPTER_PRODUCTION_QUALIFICATION_STALE",
                    f"{profile.layer.value} differs from current policy",
                )
            receipts.append(
                {
                    "asset_version_id": asset_version_id,
                    "design_layer": profile.layer.value,
                    "profile_hash": str(row[4]),
                    "qualification_hash": str(row[5]),
                    "evaluation_hash": str(row[6]),
                    "evaluator_execution_class": str(row[7]),
                    "source_operation_id": str(row[8]),
                }
            )
        admission = {
            "schema_version": "chapter-production-admission.v1",
            "admission": "CHAPTER_PRODUCTION_ADMITTED",
            "snapshot_id": snapshot_id,
            "longform_design_qualification_hash": str(snapshot[5]),
            "book_version": int(snapshot[2]),
            "chapter_number": chapter_number,
            "accepted_through_chapter": accepted_through_chapter,
            "current_volume_plan_version": cursor_projection["volume_plan_version"],
            "current_relevant_arc_plan_versions": list(
                cursor_projection["arc_plan_versions"]
            ),
            "chapter_group_plan_version_id": chapter_group_plan_version_id,
            "chapter_plan_version_id": chapter_plan_version_id,
            "receipts": sorted(
                receipts,
                key=lambda item: item["design_layer"],
            ),
        }
        return {**admission, "admission_hash": canonical_hash(admission)}

    def require_chapter_execution_plan(
        self, planning_candidate_asset_version_id: str
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT projection.asset_version_id, projection.content_hash,
                       projection.content, candidate.content_hash
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
                  AND candidate.lifecycle='ACTIVE'
                  AND candidate.eligibility='ELIGIBLE'
                  AND candidate.governance='CLEAR'
                  AND projection.lifecycle='ACTIVE'
                  AND projection.eligibility='ELIGIBLE'
                  AND projection.governance='CLEAR'
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
            "source_content_hash": str(rows[0][3]),
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


__all__ = [
    "BookCoordinationCandidate",
    "BookFollowupAdmissionCandidate",
    "BookProgressProjection",
    "PostgresBookProductionQuery",
]
