from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

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
from novel_forge.modules.longform_narrative import (
    build_arc_working_set,
    reduce_accepted_obligations,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
from novel_forge.storage.narrative_realization_repositories import (
    NarrativeRealizationRepository,
)


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

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Book production query requires PostgreSQL")
        self.database_url = database_url

    def author_workspace(self, *, project_id: str, book_id: str = "") -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            cur = uow.cursor
            cur.execute("""SELECT b.book_id,b.workspace_id,b.version,b.status,
                    COALESCE(v.content->>'title',b.book_id),b.production_profile,b.runtime_policy
                FROM authority_book b JOIN authority_asset_version v
                  ON v.asset_version_id=b.current_book_asset_version_id
                WHERE b.project_id=%s ORDER BY b.book_id""", [project_id])
            books = [dict(zip(("book_id", "workspace_id", "version", "status", "title", "production_profile", "runtime_policy"), row, strict=True)) for row in cur.fetchall()]
            if book_id and book_id not in {book["book_id"] for book in books}:
                raise KernelError("BOOK_NOT_FOUND", "Book does not belong to this project")
            if not book_id:
                return {"books": books, "runs": [], "profiles": [], "snapshots": [], "budget_scopes": []}
            cur.execute("""SELECT to_jsonb(b),p.content,p.content_hash,s.snapshot_hash,r.command_payload
                FROM authority_book_production b
                LEFT JOIN authority_asset_version p ON p.asset_version_id=b.production_profile_version
                LEFT JOIN authority_book_production_input_snapshot s ON s.snapshot_id=b.input_snapshot_id
                LEFT JOIN authority_book_chapter_request r ON r.chapter_request_id=b.active_chapter_request_id
                WHERE b.project_id=%s AND b.book_id=%s ORDER BY b.created_at DESC LIMIT 100""", [project_id, book_id])
            runs = [{**row[0], "frozen_profile": row[1], "profile_hash": row[2], "snapshot_hash": row[3], "chapter_configuration": {key: value for key, value in (row[4] or {}).items()
                     if key in {"context_token_budget", "context_version_refs", "preparation_report", "production_profile_version", "chapter_plan_version"}}} for row in cur.fetchall()]
            cur.execute("""SELECT v.asset_version_id,v.content_hash,v.content
                FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
                WHERE a.project_id=%s AND a.asset_type='production_profile'
                  AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'
                  AND COALESCE(v.content->>'book_id','') IN ('',%s)
                ORDER BY v.created_at DESC LIMIT 100""", [project_id, book_id])
            profiles = [dict(zip(("asset_version_id", "content_hash", "content"), row, strict=True)) for row in cur.fetchall()]
            cur.execute("""SELECT cast_asset.asset_version_id, cast_asset.content_hash, cast_asset.content
                FROM authority_book b
                JOIN authority_asset_version design ON design.asset_version_id=b.current_book_design_asset_version_id
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(design.content->'foundation_set'->'bindings','[]'::jsonb)) binding
                JOIN authority_asset_version cast_asset ON cast_asset.asset_version_id=binding->>'asset_version_id'
                  AND cast_asset.content_hash=binding->>'content_hash'
                JOIN authority_asset cast_owner ON cast_owner.asset_id=cast_asset.asset_id
                WHERE b.project_id=%s AND b.book_id=%s AND binding->>'role'='CHARACTER_CAST'
                  AND cast_owner.project_id=b.project_id
                  AND (cast_owner.asset_type='character_cast' OR (cast_owner.asset_type='planning_generation_candidate'
                    AND cast_asset.content->>'generator_operation_name'='character.cast.generate'))""", [project_id, book_id])
            characters = []
            for version, content_hash, content in cur.fetchall():
                for character in content.get("candidate_payload", content).get("characters", []):
                    if character.get("character_id"):
                        characters.append({"character_id": character["character_id"], "name": character.get("name") or character["character_id"], "source_asset_version_id": version, "source_content_hash": content_hash})
            cur.execute("""SELECT to_jsonb(s) FROM authority_book_production_input_snapshot s
                WHERE project_id=%s AND book_id=%s ORDER BY created_at DESC LIMIT 100""", [project_id, book_id])
            snapshots = [row[0] for row in cur.fetchall()]
            cur.execute("""SELECT budget_scope_id,owner_kind,owner_id,deadline_at,
                    deadline_at<=NOW(),policy_snapshot
                FROM authority_provider_budget_scope WHERE project_id=%s ORDER BY deadline_at DESC""", [project_id])
            budgets = [dict(zip(("budget_scope_id", "owner_kind", "owner_id", "deadline_at", "expired", "policy"), row, strict=True)) for row in cur.fetchall()]
            cur.execute("""SELECT v.content,v.content_hash,s.selected_by_operation_id
                FROM authority_runtime_policy_selection s JOIN authority_runtime_policy_version v
                  USING(owner,project_id,policy_version)
                WHERE s.owner='BOOK_CONTROL' AND s.project_id=%s""", [project_id])
            selected = cur.fetchone()
            editorial_control = {"policy": selected[0], "content_hash": selected[1], "selected_by_operation_id": selected[2], "scope": "PROJECT_FUTURE_SUBJECTS"} if selected else None
            subjects = [f"{run['book_run_id']}:chapter:{int(run['accepted_through_chapter']) + 1}" for run in runs]
            cur.execute("""SELECT b.subject_id,v.content,v.content_hash
                FROM authority_runtime_policy_binding b JOIN authority_runtime_policy_version v
                  USING(owner,project_id,policy_version)
                WHERE b.owner='BOOK_CONTROL' AND b.project_id=%s AND b.subject_id=ANY(%s)""", [project_id, subjects])
            bindings = {row[0]: {"subject_id": row[0], "policy": row[1], "content_hash": row[2]} for row in cur.fetchall()}
            for run in runs:
                run["frozen_editorial_control"] = bindings.get(f"{run['book_run_id']}:chapter:{int(run['accepted_through_chapter']) + 1}")
        return {"books": books, "runs": runs, "profiles": profiles, "snapshots": snapshots, "budget_scopes": budgets, "approved_characters": characters, "editorial_control": editorial_control}

    def narrative_reality(self, *, book_run_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return NarrativeRealityRepository(uow.cursor).require(book_run_id=book_run_id, chapter_number=chapter_number)

    def reality_context(self, *, book_run_id: str, role: str, token_budget: int, character_ids: tuple[str, ...] = ()) -> dict[str, Any]:
        from novel_forge.modules.context_builder.reality_projection import project_role_context
        return project_role_context(reality=self.narrative_reality(book_run_id=book_run_id), role=role, token_budget=token_budget, character_ids=character_ids)

    def reality_view(self, *, book_run_id: str, view: str, chapter_number: int | None = None, offset: int = 0, limit: int = 100, event_id: str = "") -> dict[str, Any]:
        from novel_forge.modules.narrative_state.read_models import project_reality_view, project_why_trace
        reality = self.narrative_reality(book_run_id=book_run_id, chapter_number=chapter_number)
        if view == "why":
            with AuthorityUnitOfWork(self.database_url) as uow:
                reality = NarrativeRealityRepository(uow.cursor).why_sources(reality=reality, event_id=event_id)
            return project_why_trace(reality, event_id=event_id)
        projection = project_reality_view(reality, view=view, offset=offset, limit=limit)
        if view == "reader":
            with AuthorityUnitOfWork(self.database_url) as uow:
                projection["reader_response_evidence"] = NarrativeRealityRepository(uow.cursor).reader_evidence(reality=reality)
        return projection

    def causal_action_versions(self, *, book_run_id: str, chapter_number: int) -> tuple[str, ...]:
        from novel_forge.storage.causal_planning_repositories import CausalPlanningRepository
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SELECT accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s", [book_run_id])
            row = uow.cursor.fetchone()
            if row is None or not int(row[0]):
                return ()
            reality = NarrativeRealityRepository(uow.cursor).require(book_run_id=book_run_id, chapter_number=int(row[0]))
            version = CausalPlanningRepository(uow.cursor).current_action(project_id=reality["project_id"], book_run_id=book_run_id, reality_revision_id=reality["revision_id"], chapter_number=chapter_number)
            return (version,) if version else ()

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
                WHERE (
                      book.state = ANY(%s)
                      OR (
                          book.state='CHECKPOINT_PENDING'
                          AND EXISTS (
                              SELECT 1
                              FROM authority_book_chapter_acceptance AS acceptance
                              WHERE acceptance.book_run_id=book.book_run_id
                                AND acceptance.chapter_number=
                                    book.accepted_through_chapter
                                AND acceptance.status='COMMITTED'
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM authority_book_volume_checkpoint AS checkpoint
                                    WHERE checkpoint.book_run_id=book.book_run_id
                                      AND checkpoint.accepted_through_chapter=
                                          acceptance.chapter_number
                                )
                          )
                      )
                  )
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
                FROM authority_book_acceptance_lineage(%s)
                WHERE status='COMMITTED'
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
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number) AND acceptance.status='COMMITTED'
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
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number) AND acceptance.status='COMMITTED'
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
            blocking_reason = str(error.get("message") or error.get("code") or error)
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
            str(row[0]).lower(): int(row[1]) for row in sidecar_admission_job_rows
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
                int(projection_repair[1]) if projection_repair is not None else None
            ),
            authoritative_repair_target_chapter=(
                int(projection_repair[2]) if projection_repair is not None else None
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
        self, *, limit: int, project_ids: Iterable[str] = ()
    ) -> tuple[BookFollowupAdmissionCandidate, ...]:

        if limit <= 0:
            raise ValueError("follow-up admission candidate limit must be positive")
        projects = tuple(dict.fromkeys(str(item) for item in project_ids if str(item)))
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
                      %s::text[]='{}'::text[]
                      OR acceptance.project_id=ANY(%s)
                  )
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
                [list(projects), list(projects), limit],
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
        try:
            request_context_token_budget = int(
                command.get("context_token_budget") or 0
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_INCOMPLETE",
                "accepted Chapter request has an invalid context token budget",
            ) from exc
        if request_context_token_budget <= 0:
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_INCOMPLETE",
                "accepted Chapter request requires a positive context token budget",
            )
        context_refs = dict(command.get("context_version_refs") or {})
        longform_refs = dict(row[17] or {})
        if not frozen:
            frozen = {
                "schema_version": "book-followup-accepted-snapshot-v2",
                "observed_through_chapter": int(row[2]),
                "context_token_budget": request_context_token_budget,
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
        elif "context_token_budget" not in frozen:
            # COMPATIBILITY: v1 snapshots predate the explicit Provider ceiling. The Chapter
            # request command is immutable Authority evidence, so its frozen
            # value is the only legal compatibility source.
            frozen["context_token_budget"] = request_context_token_budget
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
            "context_token_budget",
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
            int(frozen["context_token_budget"]) != request_context_token_budget
            or int(frozen["context_token_budget"]) <= 0
        ):
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_SNAPSHOT_DRIFT",
                "advisory snapshot token ceiling differs from the Chapter request",
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
        book_run_id: str = "",
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SELECT 1 FROM authority_book_edition_run WHERE book_run_id=%s AND role='VALIDATION'", [book_run_id])
            edition_run = book_run_id if uow.cursor.fetchone() else ""
            book = None
            if edition_run and contract_type == "CHAPTER":
                uow.cursor.execute("SELECT to_jsonb(book) FROM authority_book_production book WHERE book_run_id=%s AND project_id=%s AND book_id=%s",
                    [book_run_id, project_id, book_id])
                row = uow.cursor.fetchone()
                book = row[0] if row else None
        revision_id = ""
        if book and chapter_number > int(book["accepted_through_chapter"]):
            from .edition_planning import edition_plan_scope
            scope = edition_plan_scope(self.database_url, book=book, chapter=chapter_number, generator="chapter_plan.generate")
            revision_id = scope["revision_id"] if scope else ""
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
                  AND COALESCE(version.content#>>'{constraint_envelope,edition_execution,book_run_id}','')=%s
                  AND (%s='' OR version.content#>>'{constraint_envelope,edition_execution,revision_id}'=%s)
                ORDER BY active.activated_at DESC
                """,
                [project_id, book_id, contract_type, edition_run, revision_id, revision_id],
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

    def chapter_group_execution_lineage(
        self, *, project_id: str, book_run_id: str, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("ChapterGroup lineage requires offset >= 0 and limit 1..500")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            uow.cursor.execute(
                "SELECT book_id, accepted_through_chapter FROM authority_book_production WHERE project_id=%s AND book_run_id=%s",
                [project_id, book_run_id],
            )
            book = uow.cursor.fetchone()
            if book is None:
                raise KernelError("BOOK_PRODUCTION_NOT_FOUND", "ChapterGroup lineage requires the exact owned Book Run")
            uow.cursor.execute(
                """
                SELECT to_jsonb(g), version.content_hash, version.content,
                       binding.project_id, binding.book_id, binding.parent_version_id
                FROM authority_chapter_group_production AS g
                JOIN authority_asset_version AS version ON version.asset_version_id=g.group_plan_version_id
                LEFT JOIN story_plan_binding AS binding ON binding.asset_version_id=g.group_plan_version_id
                  AND binding.contract_type='CHAPTER_GROUP'
                WHERE g.project_id=%s AND g.book_run_id=%s
                ORDER BY g.chapter_start, g.created_at, g.group_run_id
                LIMIT %s OFFSET %s
                """,
                [project_id, book_run_id, limit + 1, offset],
            )
            rows = uow.cursor.fetchall()
            groups = []
            for raw, digest, content, owner, book_id, parent in rows[:limit]:
                if (
                    raw["book_id"] != book[0] or (owner, book_id) != (project_id, book[0])
                    or parent != raw["volume_plan_version_id"]
                    or content.get("chapter_range") != [raw["chapter_start"], raw["chapter_end"]]
                    or canonical_hash(content) != digest
                ):
                    raise KernelError("BOOK_CHAPTER_GROUP_LINEAGE_INVALID", "Group Run scope and immutable plan binding differ")
                uow.cursor.execute(
                    """
                    SELECT to_jsonb(child), to_jsonb(request), to_jsonb(acceptance)
                    FROM authority_chapter_group_chapter AS child
                    JOIN authority_book_chapter_request AS request USING(chapter_request_id)
                    LEFT JOIN authority_book_chapter_acceptance AS acceptance USING(chapter_request_id)
                    WHERE child.group_run_id=%s
                    ORDER BY child.chapter_number
                    """, [raw["group_run_id"]],
                )
                chapters = []
                for child, request, accepted in uow.cursor.fetchall():
                    number = child["chapter_number"]
                    if (
                        child["project_id"] != project_id
                        or request["project_id"] != project_id or request["book_run_id"] != book_run_id
                        or request["chapter_number"] != number
                        or request["chapter_plan_version"] != child["chapter_plan_version_id"]
                        or request["chapter_root_operation_id"] != child["child_root_operation_id"]
                        or not raw["chapter_start"] <= number <= raw["chapter_end"]
                    ):
                        raise KernelError("BOOK_CHAPTER_GROUP_LINEAGE_INVALID", "Group child differs from its owned Chapter request")
                    if child["status"] == "ACCEPTED" and (
                        not accepted or accepted["status"] != "COMMITTED"
                        or accepted["project_id"] != project_id or accepted["book_run_id"] != book_run_id
                        or accepted["chapter_number"] != number or number > book[1]
                        or accepted["acceptance_operation_id"] != child["acceptance_operation_id"]
                        or accepted["delegation_id"] != child["child_delegation_id"]
                        or accepted["chapter_outcome_asset_version_id"] != child["chapter_outcome_version_id"]
                        or not accepted.get("story_state_asset_version_id") or not accepted.get("canon_snapshot_asset_version_id")
                    ):
                        raise KernelError("BOOK_CHAPTER_GROUP_LINEAGE_INVALID", "Accepted group child has no matching committed Book outcome")
                    chapters.append({
                        **{key: child[key] for key in (
                            "chapter_number", "chapter_plan_version_id", "chapter_request_id", "child_root_operation_id",
                            "status", "acceptance_operation_id", "chapter_outcome_version_id",
                        )},
                        "acceptance_id": (accepted or {}).get("acceptance_id"),
                        "acceptance_status": (accepted or {}).get("status"),
                        "story_state_asset_version_id": (accepted or {}).get("story_state_asset_version_id"),
                        "canon_snapshot_asset_version_id": (accepted or {}).get("canon_snapshot_asset_version_id"),
                    })
                if raw["state"] == "COMPLETED" and (
                    [item["chapter_number"] for item in chapters] != list(range(raw["chapter_start"], raw["chapter_end"] + 1))
                    or any(item["status"] != "ACCEPTED" for item in chapters)
                    or raw["accepted_through_chapter"] != raw["chapter_end"]
                ):
                    raise KernelError("BOOK_CHAPTER_GROUP_LINEAGE_INVALID", "Completed Group lacks complete accepted Chapter coverage")
                groups.append({
                    **{key: raw[key] for key in (
                        "group_run_id", "project_id", "book_id", "book_run_id", "root_operation_id",
                        "group_plan_version_id", "volume_plan_version_id", "state", "accepted_through_chapter",
                    )},
                    "chapter_range": [raw["chapter_start"], raw["chapter_end"]],
                    "plan": {"asset_version_id": raw["group_plan_version_id"], "content_hash": digest, "content": content},
                    "chapters": chapters,
                })
        return {
            "contract_version": "book-chapter-group-lineage.v1", "project_id": project_id,
            "book_id": book[0], "book_run_id": book_run_id, "accepted_through_chapter": book[1],
            "groups": groups, "offset": offset, "limit": limit, "has_more": len(rows) > limit,
        }

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
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number) AND acceptance.chapter_number=%s
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
                       foundation_set, foundation_set_digest,
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
            "foundation_set",
            "foundation_set_digest",
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
            "volume_chapter_range": tuple(
                int(item) for item in volume["content"]["chapter_range"]
            ),
            "arc_plan_versions": relevant_arcs,
        }

    def require_arc_working_set(
        self,
        *,
        book_run_id: str,
        snapshot_id: str,
        chapter_number: int,
        schedule_row: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:

        cursor = self.require_cursor_plan_projection(
            snapshot_id=snapshot_id, chapter_cursor=chapter_number
        )
        arc_ids = tuple(str(item) for item in cursor["arc_plan_versions"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.project_id, book.book_id,
                       snapshot.initial_story_state_version
                FROM authority_book_production AS book
                JOIN authority_book_production_input_snapshot AS snapshot
                  ON snapshot.snapshot_id=book.input_snapshot_id
                WHERE book.book_run_id=%s AND snapshot.snapshot_id=%s
                """,
                [book_run_id, snapshot_id],
            )
            scope = uow.cursor.fetchone()
            if scope is None:
                raise KernelError(
                    "ARC_WORKING_SET_BOOK_SCOPE_INVALID",
                    "Arc working-set input does not belong to the Book run",
                )
            project_id, book_id = str(scope[0]), str(scope[1])
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash,
                       version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                """,
                [project_id, list(arc_ids)],
            )
            arc_rows = tuple(uow.cursor.fetchall())
            if {str(row[0]) for row in arc_rows} != set(arc_ids):
                raise KernelError(
                    "ARC_WORKING_SET_PLAN_DRIFT",
                    "Arc working-set selection requires every current eligible Arc Plan",
                )
            arc_plans = {str(row[0]): dict(row[2]) for row in arc_rows}
            policies: dict[str, dict[str, Any]] = {}
            for content in arc_plans.values():
                envelope = content.get("constraint_envelope")
                if not isinstance(envelope, Mapping):
                    candidate = content.get("candidate_payload")
                    envelope = (
                        candidate.get("constraint_envelope")
                        if isinstance(candidate, Mapping)
                        else None
                    )
                policy = (
                    envelope.get("narrative_load_policy")
                    if isinstance(envelope, Mapping)
                    else None
                )
                if isinstance(policy, Mapping) and policy.get("policy_hash"):
                    policies[str(policy["policy_hash"])] = dict(policy)
            if len(policies) != 1:
                raise KernelError(
                    "ARC_WORKING_SET_LOAD_POLICY_INVALID",
                    "Current Arc Plans must share one frozen Narrative Load Policy",
                )
            if chapter_number == 1:
                initial_story_state_id = str(scope[2] or "")
                obligation_states: list[dict[str, Any]] = []
                uow.cursor.execute(
                    """
                    SELECT version.content_hash, version.content
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset
                      ON asset.asset_id=version.asset_id
                    WHERE asset.project_id=%s
                      AND version.asset_version_id=%s
                    """,
                    [project_id, initial_story_state_id],
                )
                state_row = uow.cursor.fetchone()
                if state_row is None:
                    raise KernelError(
                        "ARC_WORKING_SET_INITIAL_STATE_MISSING",
                        "Initial accepted Story State is unavailable",
                    )
                story_state_hash = str(state_row[0])
                state_content = dict(state_row[1])
                entries = [
                    dict(item)
                    for item in (state_content.get("current_state") or {}).get(
                        "narrative_obligation", ()
                    )
                    if isinstance(item, Mapping)
                ]
                obligation_states = reduce_accepted_obligations(
                    entries=entries, chapter_number=chapter_number
                )
                accepted_narrative_state = {
                    "asset_version_id": initial_story_state_id,
                    "content_hash": story_state_hash,
                    "content": state_content,
                }
                accepted_projection: dict[str, Any] = {
                    "accepted_boundary": {"chapter_number": 0},
                    "source_story_state_asset_version_id": initial_story_state_id,
                    "source_story_state_content_hash": story_state_hash,
                    "arc_states": [],
                    "arc_progress": [],
                    "arc_checkpoints": [],
                    "obligation_states": obligation_states,
                }
            else:
                uow.cursor.execute(
                    """
                    SELECT projection.projection_set_id,
                           projection.projection_hash, projection.arc_state,
                           projection.obligation_state,
                           projection.story_state_asset_version_id,
                           story.content_hash, story.content
                    FROM authority_book_narrative_projection_set AS projection
                    JOIN authority_asset_version AS story
                      ON story.asset_version_id=
                         projection.story_state_asset_version_id
                    WHERE projection.book_run_id=authority_book_source_run(%s,projection.chapter_number)
                      AND projection.project_id=%s AND projection.book_id=%s
                      AND projection.chapter_number=%s
                      AND projection.status='COMPLETE'
                    """,
                    [book_run_id, project_id, book_id, chapter_number - 1],
                )
                projection_row = uow.cursor.fetchone()
                if projection_row is None:
                    raise KernelError(
                        "ARC_WORKING_SET_ACCEPTED_PROJECTION_MISSING",
                        "Arc working set requires the immediately preceding accepted projection",
                    )
                projection_set_id = str(projection_row[0])
                uow.cursor.execute(
                    """
                    SELECT arc_plan_version_id, progress_id,
                           observation_status, contribution_kind,
                           progress_units, cumulative_progress_units, evidence
                    FROM authority_arc_progress_v2
                    WHERE projection_set_id=%s
                    """,
                    [projection_set_id],
                )
                progress_rows = [
                    {
                        "arc_plan_version_id": str(row[0]),
                        "progress_id": str(row[1]),
                        "observation_status": str(row[2]),
                        "contribution_kind": str(row[3]),
                        "progress_units": int(row[4]),
                        "cumulative_progress_units": int(row[5]),
                        "evidence": dict(row[6] or {}),
                    }
                    for row in uow.cursor.fetchall()
                ]
                uow.cursor.execute(
                    """
                    SELECT checkpoint
                    FROM authority_arc_checkpoint_v2
                    WHERE projection_set_id=%s
                    """,
                    [projection_set_id],
                )
                checkpoint_rows = [dict(row[0]) for row in uow.cursor.fetchall()]
                accepted_projection = {
                    "projection_set_id": projection_set_id,
                    "projection_hash": str(projection_row[1]),
                    "accepted_boundary": {"chapter_number": chapter_number - 1},
                    "arc_states": list(projection_row[2] or ()),
                    # WHY: The persisted projection records the obligation at the
                    # accepted Chapter N boundary.  Scheduling Chapter N+1
                    # must preserve that state while evaluating due/overdue
                    # debt at the new planning coordinate.
                    "obligation_states": reduce_accepted_obligations(
                        entries=[
                            dict(item)
                            for item in projection_row[3] or ()
                            if isinstance(item, Mapping)
                        ],
                        chapter_number=chapter_number,
                    ),
                    "arc_progress": progress_rows,
                    "arc_checkpoints": checkpoint_rows,
                }
                accepted_narrative_state = {
                    "asset_version_id": str(projection_row[4]),
                    "content_hash": str(projection_row[5]),
                    "content": dict(projection_row[6]),
                }
        row = dict(schedule_row or {})
        return build_arc_working_set(
            project_id=project_id,
            book_id=book_id,
            chapter_number=chapter_number,
            arc_plan_snapshots=arc_plans,
            accepted_projection=accepted_projection,
            accepted_narrative_state=accepted_narrative_state,
            narrative_load_policy=next(iter(policies.values())),
            schedule_row=row,
            reader_intent=(
                dict(row.get("reader_experience") or {})
                if isinstance(row.get("reader_experience"), Mapping)
                else {}
            ),
        )

    def require_chapter_production_admission(
        self,
        *,
        book_run_id: str,
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
            if snapshot is None or str(snapshot[3]) not in {"LONGFORM_DESIGN_QUALIFIED", "AUTHOR_SUPERVISED_DESIGN"}:
                raise KernelError(
                    "LONGFORM_DESIGN_QUALIFICATION_REQUIRED",
                    "Chapter production requires a qualified Book input snapshot",
                )
            global_qualification = dict(snapshot[4])
            if global_qualification.get(
                "admission"
            ) != str(snapshot[3]) or canonical_hash(
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
            supervised = str(snapshot[3]) == "AUTHOR_SUPERVISED_DESIGN"
            if supervised:
                from novel_forge.modules.book_design_authority.author_supervision import approved_book_design_receipt
                from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt, reusable_qualified_design_receipt
                if global_qualification.get("book_authorization"):
                    from novel_forge.modules.production_execution.author_supervision import verify_book_supervision
                    verify_book_supervision(uow.cursor, global_qualification["book_authorization"])
                for receipt in global_receipts:
                    if receipt.get("mode") == "STRICT_QUALIFIED":
                        current = reusable_qualified_design_receipt(uow.cursor, project_id=str(snapshot[0]), book_id=str(snapshot[1]),
                            asset_version_id=receipt["asset_version_id"], generator=receipt["design_layer"])
                        if current != receipt:
                            raise KernelError("LONGFORM_DESIGN_QUALIFICATION_STALE", "Reused strict design receipt changed")
                        continue
                    resolver = approved_book_design_receipt if receipt["design_layer"] == "book_design.propose" else approved_design_receipt
                    current = resolver(uow.cursor, project_id=str(snapshot[0]), book_id=str(snapshot[1]), asset_version_id=receipt["asset_version_id"])
                    if current is None or {**current, "design_layer": receipt["design_layer"]} != receipt:
                        raise KernelError("AUTHOR_SUPERVISION_APPROVAL_STALE", "Frozen author decision differs from current design")
            else:
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
            for content in (chapter_content, group_content):
                edition_scope = (content.get("constraint_envelope") or {}).get("edition_execution")
                if edition_scope and edition_scope.get("book_run_id") != book_run_id:
                    raise KernelError("EDITION_PLAN_SCOPE_INVALID", "Edition execution plans cannot enter another Book run")
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
            realization = NarrativeRealizationRepository(
                uow.cursor
            ).require_current_for_chapter(
                project_id=str(snapshot[0]),
                book_id=str(snapshot[1]),
                chapter_group_plan_version_id=chapter_group_plan_version_id,
                chapter_number=chapter_number,
            )
            declared_realization = dict(
                chapter_content.get("narrative_realization_slice") or {}
            )
            if declared_realization != realization:
                raise KernelError(
                    "CHAPTER_NARRATIVE_REALIZATION_DRIFT",
                    "ChapterPlan does not bind the current Frozen realization slice",
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
            author_receipts = []
            if supervised:
                for stage, version_id in (("chapter_group_plan.generate", chapter_group_plan_version_id), ("chapter_plan.generate", chapter_plan_version_id)):
                    receipt = approved_design_receipt(uow.cursor, project_id=str(snapshot[0]), book_id=str(snapshot[1]), asset_version_id=version_id)
                    if receipt is None:
                        author_receipts.append(reusable_qualified_design_receipt(uow.cursor, project_id=str(snapshot[0]), book_id=str(snapshot[1]),
                            asset_version_id=version_id, generator=stage))
                        continue
                    if receipt["lifecycle"] != "ACTIVE" or receipt["author_id"] != global_qualification["author_id"]:
                        raise KernelError("AUTHOR_SUPERVISION_APPROVAL_REQUIRED", "Chapter execution requires its exact author decision")
                    author_receipts.append({**receipt, "design_layer": stage})
                expected_receipts = []
        authoritative_working_set = self.require_arc_working_set(
            book_run_id=book_run_id,
            snapshot_id=snapshot_id,
            chapter_number=chapter_number,
            schedule_row=schedule_row,
        )
        declared_working_set = dict(
            (chapter_content.get("constraint_envelope") or {}).get("arc_working_set")
            or {}
        )
        if (
            not declared_working_set
            or declared_working_set != authoritative_working_set
        ):
            raise KernelError(
                "CHAPTER_PRODUCTION_ARC_WORKING_SET_STALE",
                "Chapter design does not bind the current Accepted-Reality Arc Working Set",
            )
        by_identity: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            by_identity.setdefault((str(row[0]), str(row[1])), []).append(row)
        receipts: list[dict[str, Any]] = list(author_receipts)
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
        reality_id = ""
        if accepted_through_chapter:
            reality = self.narrative_reality(book_run_id=book_run_id, chapter_number=accepted_through_chapter)
            if (reality["state_version_id"], reality["canon_version_id"]) != (active_story_state_version_id, active_canon_snapshot_version_id):
                raise KernelError("NARRATIVE_REALITY_ADMISSION_STALE", "Chapter admission must bind the current accepted Reality")
            reality_id = str(reality["revision_id"])
        admission = {
            "schema_version": "chapter-production-admission.v1",
            "narrative_reality_revision_id": reality_id,
            "admission": "CHAPTER_PRODUCTION_ADMITTED",
            **({"execution_mode": "AUTHOR_SUPERVISED", "literary_qualification": "NOT_PROVEN"} if supervised else {}),
            "snapshot_id": snapshot_id,
            "longform_design_qualification_hash": str(snapshot[5]),
            "book_version": int(snapshot[2]),
            "chapter_number": chapter_number,
            "accepted_through_chapter": accepted_through_chapter,
            "current_volume_plan_version": cursor_projection["volume_plan_version"],
            "current_relevant_arc_plan_versions": list(
                cursor_projection["arc_plan_versions"]
            ),
            "arc_working_set_digest": authoritative_working_set["working_set_digest"],
            "selected_arc_contributions": list(
                authoritative_working_set["selected_contributions"]
            ),
            "chapter_group_plan_version_id": chapter_group_plan_version_id,
            "chapter_plan_version_id": chapter_plan_version_id,
            "narrative_realization_id": realization["realization_id"],
            "narrative_realization_slice_id": realization["slice_id"],
            "narrative_realization_contract_digest": realization["contract_digest"],
            "narrative_realization_event_ids": list(realization["event_ids"]),
            "receipts": sorted(
                receipts,
                key=lambda item: item["design_layer"],
            ),
        }
        return {**admission, "admission_hash": canonical_hash(admission)}

    def require_chapter_execution_plan(
        self, planning_candidate_asset_version_id: str, *, allow_missing: bool = False
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT projection.asset_version_id, projection.content_hash,
                       projection.content, candidate.content_hash,
                       projection.lifecycle, projection.eligibility,
                       projection.governance, operation.status
                FROM authority_asset_version AS candidate
                JOIN authority_asset AS candidate_asset
                  ON candidate_asset.asset_id=candidate.asset_id
                JOIN authority_operation AS operation
                  ON operation.project_id=candidate_asset.project_id
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
                ORDER BY projection.created_at DESC
                LIMIT 2
                """,
                [
                    planning_candidate_asset_version_id,
                    planning_candidate_asset_version_id,
                ],
            )
            rows = tuple(uow.cursor.fetchall())
            if not rows and allow_missing:
                uow.cursor.execute(
                    """
                    SELECT 1 FROM authority_asset_version AS candidate
                    WHERE candidate.asset_version_id=%s
                      AND candidate.lifecycle='ACTIVE'
                      AND candidate.eligibility='ELIGIBLE'
                      AND candidate.governance='CLEAR'
                      AND NOT EXISTS (
                          SELECT 1 FROM authority_operation_output_asset AS output
                          JOIN authority_asset_version AS projection
                            ON projection.asset_version_id=output.asset_version_id
                          WHERE output.output_key='story_planning.chapter_plan_projection'
                            AND projection.content->>
                                'source_planning_candidate_asset_version_id'=%s
                      )
                    """,
                    [planning_candidate_asset_version_id, planning_candidate_asset_version_id],
                )
                if uow.cursor.fetchone() is not None:
                    return None
        if len(rows) != 1 or tuple(rows[0][4:]) != ("ACTIVE", "ELIGIBLE", "CLEAR", "SUCCEEDED"):
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
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number) AND acceptance.project_id=%s
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
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number)
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
