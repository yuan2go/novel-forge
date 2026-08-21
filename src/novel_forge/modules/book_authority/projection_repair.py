"""Durable post-0094 repair owned by Book Authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.runtime_job import RuntimeJobClaim
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .longform_projection import (
    AcceptedLongformEvidence,
    frozen_arc_plan_version_ids,
    project_accepted_longform,
)


BOOK_PROJECTION_REPAIR_DEFINITION = "book.projection.repair"
BOOK_PROJECTION_REPAIR_DEFINITION_VERSION = "1.0.0"
BOOK_PROJECTION_REPAIR_HANDLER = "novel_forge.book_authority.projection_repair"


def _hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()
    )


def validate_terminal_repair_rows(
    *, target_chapter: int, rows: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Validate complete contiguous authoritative coverage before pointer CAS."""

    chapters = [int(row["chapter_number"]) for row in rows]
    expected = list(range(1, target_chapter + 1))
    if chapters != expected:
        raise KernelError(
            "BOOK_PROJECTION_REPAIR_SEQUENCE_INVALID",
            "repair terminal validation requires contiguous accepted chapters",
        )
    for row in rows:
        if str(row.get("projection_status") or "") != "COMPLETE":
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_PROJECTION_INCOMPLETE",
                "repair terminal validation found an incomplete projection",
            )
        if str(row.get("acceptance_projection_set_id") or "") != str(
            row.get("projection_set_id") or ""
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_ACCEPTANCE_POINTER_INVALID",
                "acceptance projection pointer is missing or misaligned",
            )
        for source in (
            "chapter_outcome_asset_version_id",
            "story_state_asset_version_id",
            "canon_snapshot_asset_version_id",
        ):
            if str(row.get(f"acceptance_{source}") or "") != str(
                row.get(f"projection_{source}") or ""
            ):
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_SOURCE_MISMATCH",
                    f"projection source differs from committed acceptance: {source}",
                )
        if not str(row.get("checkpoint_id") or ""):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_CHECKPOINT_MISSING",
                "repair terminal validation requires every chapter checkpoint",
            )
        if str(row.get("checkpoint_projection_hash") or "") != str(
            row.get("projection_hash") or ""
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_CHECKPOINT_DRIFT",
                "repair checkpoint and projection hashes differ",
            )
    final = rows[-1]
    proof = {
        "target_chapter": target_chapter,
        "chapter_sequence": chapters,
        "acceptance_ids": [str(row["acceptance_id"]) for row in rows],
        "projection_set_ids": [str(row["projection_set_id"]) for row in rows],
        "projection_hashes": [str(row["projection_hash"]) for row in rows],
        "final_projection_set_id": str(final["projection_set_id"]),
    }
    proof["terminal_digest"] = _hash(proof)
    return proof


@dataclass(frozen=True, slots=True)
class ProjectionRepairBatchResult:
    repair_id: str
    book_run_id: str
    processed_chapters: tuple[int, ...]
    next_chapter: int
    target_chapter: int
    authoritative_status: str
    terminal_digest: str = ""

    @property
    def complete(self) -> bool:
        return self.authoritative_status == "AUTHORITATIVE_REPAIR_COMPLETE"


class PostgresBookProjectionRepairAuthority:
    """Runs bounded repair batches through fenced Command Kernel worker Operations."""

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        failure_injector: Any | None = None,
        worker_id: str = "book-projection-repair-worker",
        command_lease_seconds: int = 30,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("repair requires PostgreSQL and a full release identity")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.failure_injector = failure_injector
        if not worker_id or command_lease_seconds <= 0:
            raise ValueError("repair worker identity and lease duration are required")
        self.worker_id = worker_id
        self.command_lease_seconds = command_lease_seconds
        with AuthorityUnitOfWork(database_url) as uow:
            uow.repositories.definitions.register(
                book_projection_repair_definition(
                    application_build_id=application_build_id,
                    commit_sha=commit_sha,
                )
            )
            uow.commit()

    def require(self, repair_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT repair_id, project_id, book_id, book_run_id,
                       runtime_job_id, operation_id,
                       target_accepted_through_chapter,
                       discovered_acceptance_count, next_chapter,
                       authoritative_status, semantic_projection_status,
                       target_evidence_digest, terminal_validation,
                       terminal_digest, last_error, version
                FROM authority_book_projection_repair
                WHERE repair_id=%s
                """,
                [repair_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_NOT_FOUND", "projection repair was not found"
            )
        keys = (
            "repair_id",
            "project_id",
            "book_id",
            "book_run_id",
            "runtime_job_id",
            "operation_id",
            "target_accepted_through_chapter",
            "discovered_acceptance_count",
            "next_chapter",
            "authoritative_status",
            "semantic_projection_status",
            "target_evidence_digest",
            "terminal_validation",
            "terminal_digest",
            "last_error",
            "version",
        )
        return dict(zip(keys, row, strict=True))

    def run_batch(
        self,
        claim: RuntimeJobClaim,
        *,
        actor_id: str,
        maximum_chapters: int = 4,
    ) -> ProjectionRepairBatchResult:
        if (
            claim.job_kind != "BOOK_PROJECTION_REPAIR"
            or claim.runtime_group != "book_repair"
            or claim.subject_kind != "BOOK_RUN"
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_JOB_INVALID",
                "repair received an invalid RuntimeJob envelope",
            )
        if maximum_chapters <= 0 or maximum_chapters > 32:
            raise ValueError("repair batch must contain between 1 and 32 chapters")
        repair_id = str(claim.input_snapshot.get("repair_id") or "")
        repair = self.require(repair_id)
        if str(repair["runtime_job_id"]) != claim.runtime_job_id:
            self._adopt_continuation_claim(repair, claim)
            repair = self.require(repair_id)
        if (
            str(repair["book_run_id"]) != claim.subject_id
            or str(repair["project_id"]) != claim.project_id
            or str(repair["runtime_job_id"]) != claim.runtime_job_id
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_JOB_IDENTITY_DRIFT",
                "repair and RuntimeJob identities do not match",
            )
        if repair["authoritative_status"] == "FAILED_TERMINAL":
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_TERMINAL",
                "repair discovery found invalid accepted history",
            )
        if repair["authoritative_status"] == "AUTHORITATIVE_REPAIR_COMPLETE":
            return self._result(repair, ())
        self._assert_runtime_claim(claim)
        self._recover_committed_operation(repair, claim, actor_id=actor_id)
        repair = self.require(repair_id)
        if repair["authoritative_status"] == "AUTHORITATIVE_REPAIR_COMPLETE":
            return self._result(repair, ())
        processed: list[int] = []
        for _ in range(maximum_chapters):
            repair = self.require(repair_id)
            chapter = int(repair["next_chapter"])
            target = int(repair["target_accepted_through_chapter"])
            if chapter > target:
                repair = self._activate_terminal(claim, repair, actor_id=actor_id)
                break
            self._repair_one_chapter(
                claim,
                repair,
                chapter_number=chapter,
                actor_id=actor_id,
            )
            processed.append(chapter)
        repair = self.require(repair_id)
        if (
            int(repair["next_chapter"]) > int(repair["target_accepted_through_chapter"])
            and repair["authoritative_status"] != "AUTHORITATIVE_REPAIR_COMPLETE"
        ):
            repair = self._activate_terminal(claim, repair, actor_id=actor_id)
        return self._result(repair, tuple(processed))

    def _assert_runtime_claim(self, claim: RuntimeJobClaim) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT job.current_attempt_id, job.current_fencing_token,
                       job.status, attempt.worker_id, attempt.lease_id,
                       lease.lease_id, lease.worker_id, lease.status
                FROM authority_runtime_job AS job
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.attempt_id=attempt.attempt_id
                 AND lease.lease_id=attempt.lease_id
                WHERE job.runtime_job_id=%s
                  AND lease.lease_expires_at>NOW()
                """,
                [claim.runtime_job_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or str(row[0]) != claim.attempt_id
            or int(row[1]) != claim.fencing_token
            or str(row[2]) not in {"RUNNING", "CHECKPOINTED"}
            or str(row[3]) != claim.worker_id
            or str(row[4]) != claim.lease_id
            or str(row[5]) != claim.lease_id
            or str(row[6]) != claim.worker_id
            or str(row[7]) != "HELD"
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_STALE_RUNTIME_FENCE",
                "repair RuntimeJob lease or fence is stale",
            )

    def _recover_committed_operation(
        self,
        repair: Mapping[str, Any],
        claim: RuntimeJobClaim,
        *,
        actor_id: str,
    ) -> None:
        operation_id = str(repair.get("operation_id") or "")
        if not operation_id:
            return
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, command_payload #>> '{payload,action}'
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                """,
                [operation_id, repair["project_id"]],
            )
            row = uow.cursor.fetchone()
        if row is None or str(row[0]) == "SUCCEEDED":
            return
        action = str(row[1] or "")
        if str(row[0]) not in {"EXECUTING", "FAILED_RETRYABLE"} or not action:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_OPERATION_RECOVERY_REQUIRED",
                "latest projection repair Operation is not recoverable",
            )
        if (
            self._durable_operation_result(
                operation_id=operation_id,
                repair_id=str(repair["repair_id"]),
                action=action,
            )
            is None
        ):
            return

        def unexpected_handler(
            _uow: AuthorityUnitOfWork,
            _operation_id: str,
            _worker: WorkerLeaseCommand,
        ) -> dict[str, Any]:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_DURABLE_RESULT_MISSING",
                "committed repair recovery lost its durable checkpoint",
            )

        self._execute_operation(
            repair,
            claim,
            actor_id=actor_id,
            action=action,
            handler=unexpected_handler,
        )

    def link_continuation(
        self, *, repair_id: str, prior_runtime_job_id: str, runtime_job_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_book_projection_repair
                SET runtime_job_id=%s, version=version+1, updated_at=NOW()
                WHERE repair_id=%s AND runtime_job_id=%s
                  AND authoritative_status IN (
                    'REGISTERED','RUNNING','CHECKPOINTED','FAILED_RETRYABLE'
                  )
                """,
                [runtime_job_id, repair_id, prior_runtime_job_id],
            )
            if uow.cursor.rowcount != 1:
                uow.cursor.execute(
                    """
                    SELECT runtime_job_id FROM authority_book_projection_repair
                    WHERE repair_id=%s
                    """,
                    [repair_id],
                )
                row = uow.cursor.fetchone()
                if row is None or str(row[0] or "") != runtime_job_id:
                    raise KernelError(
                        "BOOK_PROJECTION_REPAIR_CONTINUATION_CAS_FAILED",
                        "repair continuation pointer changed",
                    )
            uow.commit()

    def _adopt_continuation_claim(
        self, repair: Mapping[str, Any], claim: RuntimeJobClaim
    ) -> None:
        """Recover a crash after atomic RuntimeJob handoff but before pointer CAS."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT previous.status, current.status,
                       current.input_snapshot->>'repair_id'
                FROM authority_runtime_job AS previous
                JOIN authority_runtime_job AS current
                  ON current.runtime_job_id=%s
                 AND current.project_id=previous.project_id
                 AND current.runtime_group=previous.runtime_group
                 AND current.job_kind=previous.job_kind
                 AND current.subject_kind=previous.subject_kind
                 AND current.subject_id=previous.subject_id
                WHERE previous.runtime_job_id=%s
                """,
                [claim.runtime_job_id, repair["runtime_job_id"]],
            )
            row = uow.cursor.fetchone()
            if (
                row is None
                or str(row[0]) != "SUCCEEDED"
                or str(row[1]) not in {"CLAIMED", "RUNNING", "CHECKPOINTED"}
                or str(row[2] or "") != str(repair["repair_id"])
            ):
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_JOB_IDENTITY_DRIFT",
                    "repair cannot adopt an unrelated RuntimeJob",
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_projection_repair
                SET runtime_job_id=%s, version=version+1, updated_at=NOW()
                WHERE repair_id=%s AND runtime_job_id=%s
                """,
                [claim.runtime_job_id, repair["repair_id"], repair["runtime_job_id"]],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_CONTINUATION_CAS_FAILED",
                    "repair continuation adoption raced with another worker",
                )
            uow.commit()

    def _repair_one_chapter(
        self,
        claim: RuntimeJobClaim,
        repair: Mapping[str, Any],
        *,
        chapter_number: int,
        actor_id: str,
    ) -> dict[str, Any]:
        repair_id = str(repair["repair_id"])

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            worker: WorkerLeaseCommand,
        ) -> dict[str, Any]:
            context = self._lock_context(uow, claim, repair_id, worker)
            if int(context["next_chapter"]) != chapter_number:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_CURSOR_CONFLICT",
                    "repair cursor changed before chapter projection",
                )
            source = self._load_chapter_source(uow, context, chapter_number)
            previous_arc_states = self._load_previous_arc_states(
                uow, context, chapter_number
            )
            active_arcs = frozen_arc_plan_version_ids(
                request_payload=source["command_payload"],
                book_context=context["longform_context_versions"],
            )
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash,
                       version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=ANY(%s) AND asset.project_id=%s
                """,
                [list(active_arcs), context["project_id"]],
            )
            arc_plan_rows = uow.cursor.fetchall()
            arc_plan_snapshots = {
                str(row[0]): dict(row[2] or {}) for row in arc_plan_rows
            }
            arc_plan_content_hashes = {
                str(row[0]): str(row[1]) for row in arc_plan_rows
            }
            if set(arc_plan_snapshots) != set(active_arcs):
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_FROZEN_ARC_PLAN_MISSING",
                    "repair requires every frozen ArcPlan AssetVersion",
                )
            expected_progress = {
                str(item.get("arc_plan_version_id") or item.get("arc_id") or ""): int(
                    item["expected_progress_units"]
                )
                for item in source["chapter_plan"].get("required_arc_contributions")
                or ()
                if isinstance(item, Mapping)
                and str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
                and item.get("expected_progress_units") is not None
            }
            projection = project_accepted_longform(
                AcceptedLongformEvidence(
                    project_id=context["project_id"],
                    book_id=context["book_id"],
                    book_run_id=context["book_run_id"],
                    chapter_request_id=source["chapter_request_id"],
                    chapter_number=chapter_number,
                    acceptance_id=source["acceptance_id"],
                    acceptance_operation_id=source["acceptance_operation_id"],
                    chapter_outcome_asset_version_id=source[
                        "chapter_outcome_asset_version_id"
                    ],
                    chapter_outcome_content_hash=source["chapter_outcome_content_hash"],
                    story_state_asset_version_id=source["story_state_asset_version_id"],
                    story_state_content_hash=source["story_state_content_hash"],
                    canon_snapshot_asset_version_id=source[
                        "canon_snapshot_asset_version_id"
                    ],
                    canon_snapshot_content_hash=source["canon_snapshot_content_hash"],
                    chapter_plan_asset_version_id=source[
                        "chapter_plan_asset_version_id"
                    ],
                    chapter_plan_content_hash=source["chapter_plan_content_hash"],
                    active_arc_plan_version_ids=active_arcs,
                    expected_progress_units=expected_progress,
                    previous_arc_states=previous_arc_states,
                    arc_plan_snapshots=arc_plan_snapshots,
                    arc_plan_content_hashes=arc_plan_content_hashes,
                    chapter_outcome=source["chapter_outcome"],
                    story_state=source["story_state"],
                    source_contract=str(
                        source["chapter_outcome"].get("contract_version") or "UNKNOWN"
                    ),
                )
            )
            uow.repositories.book_authority.commit_longform_projection_set(projection)
            self._assert_projection_equal(uow, projection)
            uow.cursor.execute(
                """
                UPDATE authority_book_chapter_acceptance
                SET longform_projection_set_id=%s
                WHERE acceptance_id=%s AND project_id=%s
                  AND status='COMMITTED'
                  AND longform_projection_set_id IS NOT DISTINCT FROM %s
                """,
                [
                    projection["projection_set_id"],
                    source["acceptance_id"],
                    context["project_id"],
                    source["longform_projection_set_id"] or None,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_ACCEPTANCE_CAS_FAILED",
                    "accepted Chapter projection pointer changed during repair",
                )
            checkpoint_id = (
                "book-projection-repair-checkpoint:"
                + hashlib.sha256(
                    f"{repair_id}:{chapter_number}:{projection['projection_hash']}".encode()
                ).hexdigest()
            )
            adaptation = dict(projection["projection_provenance"])
            source_digest = _hash(
                {
                    "acceptance_id": source["acceptance_id"],
                    "source_versions": projection["source_versions"],
                    "source_content_hashes": adaptation["source_content_hashes"],
                }
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_book_projection_repair_checkpoint(
                    checkpoint_id, repair_id, project_id, book_run_id,
                    chapter_number, acceptance_id, projection_set_id,
                    source_evidence_digest, projection_hash, projector_version,
                    adaptation_evidence, operation_id, attempt_id, fencing_token,
                    runtime_job_id, runtime_attempt_id, runtime_fencing_token
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT(repair_id, chapter_number) DO NOTHING
                """,
                [
                    checkpoint_id,
                    repair_id,
                    context["project_id"],
                    context["book_run_id"],
                    chapter_number,
                    source["acceptance_id"],
                    projection["projection_set_id"],
                    source_digest,
                    projection["projection_hash"],
                    adaptation["projector_version"],
                    Jsonb(adaptation),
                    operation_id,
                    worker.attempt_id,
                    worker.fencing_token,
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                ],
            )
            self._assert_checkpoint_equal(
                uow,
                repair_id=repair_id,
                chapter_number=chapter_number,
                projection=projection,
                source_digest=source_digest,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_projection_repair
                SET authoritative_status='CHECKPOINTED', next_chapter=%s,
                    operation_id=%s, version=version+1, updated_at=NOW()
                WHERE repair_id=%s AND version=%s AND next_chapter=%s
                  AND runtime_job_id=%s
                  AND authoritative_status IN (
                    'REGISTERED','RUNNING','CHECKPOINTED','FAILED_RETRYABLE'
                  )
                """,
                [
                    chapter_number + 1,
                    operation_id,
                    repair_id,
                    context["repair_version"],
                    chapter_number,
                    claim.runtime_job_id,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_CHECKPOINT_CAS_FAILED",
                    "repair cursor changed before checkpoint commit",
                )
            self._record_event(
                uow,
                operation_id=operation_id,
                context=context,
                event_type="book.projection_repair.chapter_checkpointed",
                payload={
                    "repair_id": repair_id,
                    "chapter_number": chapter_number,
                    "projection_set_id": projection["projection_set_id"],
                    "projection_hash": projection["projection_hash"],
                    "runtime_fencing_token": claim.fencing_token,
                },
            )
            self._checkpoint("after_projection_repair_checkpoint")
            return {
                "repair_id": repair_id,
                "chapter_number": chapter_number,
                "projection_set_id": projection["projection_set_id"],
                "projection_hash": projection["projection_hash"],
                "next_chapter": chapter_number + 1,
            }

        return self._execute_operation(
            repair,
            claim,
            actor_id=actor_id,
            action=f"chapter:{chapter_number}",
            handler=handler,
        )

    def _activate_terminal(
        self,
        claim: RuntimeJobClaim,
        repair: Mapping[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        repair_id = str(repair["repair_id"])

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            worker: WorkerLeaseCommand,
        ) -> dict[str, Any]:
            context = self._lock_context(uow, claim, repair_id, worker)
            target = int(context["target_chapter"])
            if int(context["next_chapter"]) != target + 1:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_NOT_TERMINAL",
                    "terminal activation requires every Chapter checkpoint",
                )
            rows = self._terminal_rows(uow, repair_id, context["book_run_id"])
            proof = validate_terminal_repair_rows(target_chapter=target, rows=rows)
            current_target_digest = self._target_evidence_digest(
                uow, context["book_run_id"], context["project_id"], target
            )
            if current_target_digest != context["target_evidence_digest"]:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_TARGET_EVIDENCE_DRIFT",
                    "accepted evidence changed after repair discovery",
                )
            proof["target_evidence_digest"] = current_target_digest
            proof["terminal_digest"] = _hash(
                {key: value for key, value in proof.items() if key != "terminal_digest"}
            )
            final_projection = str(proof["final_projection_set_id"])
            final_row = rows[-1]
            uow.cursor.execute(
                """
                UPDATE authority_book_production
                SET active_longform_projection_set_id=%s,
                    state=CASE
                        WHEN state='READY' AND EXISTS (
                            SELECT 1
                            FROM authority_arc_checkpoint_followup AS followup
                            WHERE followup.book_run_id=
                                  authority_book_production.book_run_id
                              AND followup.status='READY'
                        ) THEN 'CHECKPOINT_PENDING'
                        ELSE state
                    END,
                    version=version+1, updated_at=NOW()
                WHERE book_run_id=%s AND project_id=%s
                  AND version=%s AND accepted_through_chapter=%s
                  AND active_chapter_request_id IS NULL
                  AND active_longform_projection_set_id IS NOT DISTINCT FROM %s
                  AND active_story_state_version_id=%s
                  AND active_canon_snapshot_version_id=%s
                  AND last_chapter_outcome_version_id=%s
                """,
                [
                    final_projection,
                    context["book_run_id"],
                    context["project_id"],
                    context["book_version"],
                    target,
                    context["active_projection_set_id"] or None,
                    final_row["projection_story_state_asset_version_id"],
                    final_row["projection_canon_snapshot_asset_version_id"],
                    final_row["projection_chapter_outcome_asset_version_id"],
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_TERMINAL_CAS_FAILED",
                    "Book changed before terminal projection activation",
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_projection_repair
                SET authoritative_status='AUTHORITATIVE_REPAIR_COMPLETE',
                    terminal_validation=%s, terminal_digest=%s,
                    terminal_attempt_id=%s,
                    terminal_command_fencing_token=%s,
                    terminal_runtime_attempt_id=%s,
                    terminal_runtime_fencing_token=%s,
                    operation_id=%s,
                    version=version+1, completed_at=NOW(), updated_at=NOW()
                WHERE repair_id=%s AND version=%s
                  AND next_chapter=target_accepted_through_chapter+1
                  AND runtime_job_id=%s
                  AND authoritative_status='CHECKPOINTED'
                """,
                [
                    Jsonb(proof),
                    proof["terminal_digest"],
                    worker.attempt_id,
                    worker.fencing_token,
                    claim.attempt_id,
                    claim.fencing_token,
                    operation_id,
                    repair_id,
                    context["repair_version"],
                    claim.runtime_job_id,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_TERMINAL_STATE_CAS_FAILED",
                    "repair state changed before terminal activation",
                )
            self._record_event(
                uow,
                operation_id=operation_id,
                context=context,
                event_type="book.projection_repair.activated",
                payload={
                    "repair_id": repair_id,
                    "final_projection_set_id": final_projection,
                    "terminal_digest": proof["terminal_digest"],
                    "runtime_fencing_token": claim.fencing_token,
                },
            )
            self._checkpoint("after_projection_repair_terminal_cas")
            return proof

        self._execute_operation(
            repair,
            claim,
            actor_id=actor_id,
            action="terminal-activation",
            handler=handler,
        )
        return self.require(repair_id)

    def _execute_operation(
        self,
        repair: Mapping[str, Any],
        claim: RuntimeJobClaim,
        *,
        actor_id: str,
        action: str,
        handler: Any,
    ) -> dict[str, Any]:
        project_id = str(repair["project_id"])
        workspace_id, input_assets = self._operation_inputs(repair, action)
        trace_id = f"book-projection-repair:{repair['repair_id']}:{action}"
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": BOOK_PROJECTION_REPAIR_DEFINITION,
                "definition_version": BOOK_PROJECTION_REPAIR_DEFINITION_VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": str(repair["book_id"]),
                "actor_id": actor_id,
                "idempotency_scope": "book:projection-repair",
                "idempotency_key": f"{repair['repair_id']}:{action}",
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": str(repair["repair_id"]),
                "causation_id": str(repair["repair_id"]),
                "input": {
                    "project_id": project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in input_assets
                    ],
                    "payload": {
                        "repair_id": str(repair["repair_id"]),
                        "book_run_id": str(repair["book_run_id"]),
                        "action": action,
                        "target_evidence_digest": str(repair["target_evidence_digest"]),
                    },
                },
                "input_assets": input_assets,
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({BOOK_PROJECTION_REPAIR_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        state = self._operation_state(operation_id, project_id)
        if state["operation_status"] == "SUCCEEDED":
            return {"operation_id": operation_id, "replayed": True}
        if state["operation_status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["operation_version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="projection repair inputs frozen",
                    trace_id=trace_id,
                    correlation_id=str(repair["repair_id"]),
                    causation_id=str(repair["repair_id"]),
                ),
            )
            state = self._operation_state(operation_id, project_id)

        if state["operation_status"] in {"READY", "FAILED_RETRYABLE"}:
            attempt = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=3,
                trace_id=trace_id,
                correlation_id=str(repair["repair_id"]),
            )
            if attempt["dead_letter"] or attempt["attempt_id"] is None:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_RETRY_EXHAUSTED",
                    "projection repair Command retry policy is exhausted",
                )
            attempt_id = str(attempt["attempt_id"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=trace_id,
                correlation_id=str(repair["repair_id"]),
            )
            attempt_status = "QUEUED"
        elif state["operation_status"] == "EXECUTING" and state["attempt_id"]:
            attempt_id = str(state["attempt_id"])
            attempt_status = str(state["attempt_status"])
        else:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_OPERATION_STATE_INVALID",
                f"projection repair Operation is {state['operation_status']}",
            )

        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            lease_seconds=self.command_lease_seconds,
            trace_id=trace_id,
            correlation_id=str(repair["repair_id"]),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=trace_id,
            correlation_id=str(repair["repair_id"]),
            causation_id=operation_id,
        )
        if attempt_status in {"QUEUED", "LEASED"}:
            start_attempt(self.database_url, worker)
        elif attempt_status not in {"RUNNING", "CHECKPOINTED"}:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_ATTEMPT_STATE_INVALID",
                f"projection repair Attempt is {attempt_status}",
            )
        try:
            existing = self._durable_operation_result(
                operation_id=operation_id,
                repair_id=str(repair["repair_id"]),
                action=action,
            )
            if existing is None:
                with AuthorityUnitOfWork(self.database_url) as uow:
                    result = handler(uow, operation_id, worker)
                    uow.commit()
                self._checkpoint("after_projection_repair_business_commit")
            else:
                result = existing
            current = self._operation_state(operation_id, project_id)
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_status=str(current["operation_status"]),
                    expected_operation_version=int(current["operation_version"]),
                ),
                outcome="success",
                result={
                    **result,
                    "recovered_from_durable_checkpoint": existing is not None,
                },
            )
            return {
                "operation_id": operation_id,
                **result,
                "replayed": bool(admitted["replayed"]),
            }
        except Exception as exc:
            retryable = not (
                isinstance(exc, KernelError)
                and exc.code.endswith(("_INVALID", "_MISMATCH", "_CONFLICT"))
            )
            try:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=retryable,
                    error_code=exc.code
                    if isinstance(exc, KernelError)
                    else "PROGRAMMING_BUG",
                    error_message=str(exc),
                    failure_class="RETRYABLE" if retryable else "FINAL",
                )
            except KernelError:
                pass
            self._record_failure(str(repair["repair_id"]), exc, retryable=retryable)
            raise

    def _operation_inputs(
        self, repair: Mapping[str, Any], action: str
    ) -> tuple[str, list[dict[str, str]]]:
        """Freeze stable accepted evidence; execution fences never enter this digest."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT workspace_id, longform_context_versions
                FROM authority_book_production
                WHERE book_run_id=%s AND project_id=%s
                """,
                [repair["book_run_id"], repair["project_id"]],
            )
            book = uow.cursor.fetchone()
            if book is None:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_BOOK_MISSING",
                    "projection repair Book no longer exists",
                )
            asset_ids: list[str] = []
            if action.startswith("chapter:"):
                chapter_number = int(action.partition(":")[2])
                uow.cursor.execute(
                    """
                    SELECT acceptance.chapter_outcome_asset_version_id,
                           acceptance.story_state_asset_version_id,
                           acceptance.canon_snapshot_asset_version_id,
                           request.chapter_plan_version, request.command_payload
                    FROM authority_book_chapter_acceptance AS acceptance
                    JOIN authority_book_chapter_request AS request
                      ON request.chapter_request_id=acceptance.chapter_request_id
                     AND request.book_run_id=acceptance.book_run_id
                    WHERE acceptance.book_run_id=%s
                      AND acceptance.project_id=%s
                      AND acceptance.chapter_number=%s
                      AND acceptance.status='COMMITTED'
                    """,
                    [repair["book_run_id"], repair["project_id"], chapter_number],
                )
                source = uow.cursor.fetchone()
                if source is None:
                    raise KernelError(
                        "BOOK_PROJECTION_REPAIR_ACCEPTED_SOURCE_MISSING",
                        "repair Operation cannot freeze missing accepted evidence",
                    )
                command_payload = dict(source[4] or {})
                plan_version = str(
                    command_payload.get("execution_chapter_plan_asset_version_id")
                    or source[3]
                    or ""
                )
                asset_ids.extend(str(value) for value in source[:3])
                if plan_version:
                    asset_ids.append(plan_version)
                asset_ids.extend(
                    frozen_arc_plan_version_ids(
                        request_payload=command_payload,
                        book_context=dict(book[1] or {}),
                    )
                )
            unique_ids = tuple(dict.fromkeys(value for value in asset_ids if value))
            if unique_ids:
                uow.cursor.execute(
                    """
                    SELECT asset_version_id, content_hash
                    FROM authority_asset_version
                    WHERE asset_version_id = ANY(%s)
                    """,
                    [list(unique_ids)],
                )
                hashes = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
            else:
                hashes = {}
        missing = [asset_id for asset_id in unique_ids if asset_id not in hashes]
        if missing:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_FROZEN_INPUT_MISSING",
                "repair Operation source AssetVersion is missing: "
                + ", ".join(missing),
            )
        return str(book[0]), [
            {"asset_version_id": asset_id, "content_hash": hashes[asset_id]}
            for asset_id in unique_ids
        ]

    def _operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, operation.version,
                       attempt.attempt_id, attempt.status
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT attempt_id, status
                    FROM authority_attempt
                    WHERE operation_id=operation.operation_id
                    ORDER BY attempt_number DESC
                    LIMIT 1
                ) AS attempt ON TRUE
                WHERE operation.operation_id=%s AND operation.project_id=%s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_OPERATION_MISSING",
                "projection repair Operation does not exist",
            )
        return {
            "operation_status": str(row[0]),
            "operation_version": int(row[1]),
            "attempt_id": str(row[2] or ""),
            "attempt_status": str(row[3] or ""),
        }

    def _durable_operation_result(
        self, *, operation_id: str, repair_id: str, action: str
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            if action.startswith("chapter:"):
                chapter_number = int(action.partition(":")[2])
                uow.cursor.execute(
                    """
                    SELECT projection_set_id, projection_hash
                    FROM authority_book_projection_repair_checkpoint
                    WHERE repair_id=%s AND chapter_number=%s AND operation_id=%s
                    """,
                    [repair_id, chapter_number, operation_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    return None
                return {
                    "repair_id": repair_id,
                    "chapter_number": chapter_number,
                    "projection_set_id": str(row[0]),
                    "projection_hash": str(row[1]),
                    "next_chapter": chapter_number + 1,
                }
            uow.cursor.execute(
                """
                SELECT terminal_validation
                FROM authority_book_projection_repair
                WHERE repair_id=%s AND operation_id=%s
                  AND authoritative_status='AUTHORITATIVE_REPAIR_COMPLETE'
                """,
                [repair_id, operation_id],
            )
            row = uow.cursor.fetchone()
        return None if row is None else dict(row[0] or {})

    @staticmethod
    def _target_evidence_digest(
        uow: AuthorityUnitOfWork,
        book_run_id: str,
        project_id: str,
        target_chapter: int,
    ) -> str:
        uow.cursor.execute(
            """
            SELECT authority_sha256_jsonb(jsonb_build_object(
                'book_run_id', %s::text,
                'target_accepted_through_chapter', %s::integer,
                'accepted_evidence', jsonb_agg(
                    jsonb_build_object(
                        'chapter_number', acceptance.chapter_number,
                        'acceptance_id', acceptance.acceptance_id,
                        'acceptance_operation_id',
                            acceptance.acceptance_operation_id,
                        'acceptance_operation_status', operation.status,
                        'chapter_outcome_asset_version_id',
                            acceptance.chapter_outcome_asset_version_id,
                        'chapter_outcome_content_hash', outcome.content_hash,
                        'story_state_asset_version_id',
                            acceptance.story_state_asset_version_id,
                        'story_state_content_hash', story.content_hash,
                        'canon_snapshot_asset_version_id',
                            acceptance.canon_snapshot_asset_version_id,
                        'canon_snapshot_content_hash', canon.content_hash,
                        'chapter_plan_asset_version_id', COALESCE(
                            NULLIF(
                                request.command_payload->>
                                'execution_chapter_plan_asset_version_id',
                                ''
                            ),
                            request.chapter_plan_version
                        ),
                        'chapter_plan_content_hash', plan.content_hash
                    ) ORDER BY acceptance.chapter_number
                )
            ))
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
             AND request.book_run_id=acceptance.book_run_id
            LEFT JOIN authority_operation AS operation
              ON operation.operation_id=acceptance.acceptance_operation_id
            JOIN authority_asset_version AS outcome
              ON outcome.asset_version_id=
                 acceptance.chapter_outcome_asset_version_id
            JOIN authority_asset_version AS story
              ON story.asset_version_id=acceptance.story_state_asset_version_id
            JOIN authority_asset_version AS canon
              ON canon.asset_version_id=acceptance.canon_snapshot_asset_version_id
            LEFT JOIN authority_asset_version AS plan
              ON plan.asset_version_id=COALESCE(
                  NULLIF(
                      request.command_payload->>
                      'execution_chapter_plan_asset_version_id',
                      ''
                  ),
                  request.chapter_plan_version
              )
            WHERE acceptance.book_run_id=%s
              AND acceptance.project_id=%s
              AND acceptance.status='COMMITTED'
            """,
            [book_run_id, target_chapter, book_run_id, project_id],
        )
        row = uow.cursor.fetchone()
        if row is None or not str(row[0] or ""):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_TARGET_EVIDENCE_MISSING",
                "repair terminal validation cannot hash accepted evidence",
            )
        return str(row[0])

    def _record_failure(
        self, repair_id: str, exc: Exception, *, retryable: bool
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_book_projection_repair
                SET authoritative_status=%s, last_error=%s,
                    version=version+1, updated_at=NOW()
                WHERE repair_id=%s
                  AND authoritative_status NOT IN (
                    'AUTHORITATIVE_REPAIR_COMPLETE','FAILED_TERMINAL'
                  )
                """,
                [
                    "FAILED_RETRYABLE" if retryable else "FAILED_TERMINAL",
                    Jsonb(
                        {
                            "code": exc.code
                            if isinstance(exc, KernelError)
                            else "PROGRAMMING_BUG",
                            "message": str(exc)[:2000],
                        }
                    ),
                    repair_id,
                ],
            )
            uow.commit()

    def _checkpoint(self, name: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(name)

    @staticmethod
    def _lock_context(
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        repair_id: str,
        worker: WorkerLeaseCommand,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT repair.project_id, repair.book_id, repair.book_run_id,
                   repair.runtime_job_id,
                   repair.target_accepted_through_chapter,
                   repair.next_chapter, repair.authoritative_status,
                   repair.version, repair.target_evidence_digest,
                   production.workspace_id, production.longform_context_versions,
                   production.version, production.accepted_through_chapter,
                   production.active_longform_projection_set_id,
                   production.active_story_state_version_id,
                   production.active_canon_snapshot_version_id,
                   production.last_chapter_outcome_version_id
            FROM authority_book_projection_repair AS repair
            JOIN authority_book_production AS production
              ON production.book_run_id=repair.book_run_id
             AND production.project_id=repair.project_id
            WHERE repair.repair_id=%s
            FOR UPDATE OF repair, production
            """,
            [repair_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_NOT_FOUND", "projection repair was not found"
            )
        uow.cursor.execute(
            """
            SELECT job.current_attempt_id, job.current_fencing_token, job.status,
                   attempt.worker_id, attempt.lease_id,
                   lease.lease_id, lease.worker_id, lease.status
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
             AND lease.lease_id=attempt.lease_id
            WHERE job.runtime_job_id=%s
              AND lease.lease_expires_at > NOW()
            FOR SHARE OF job, attempt, lease
            """,
            [claim.runtime_job_id],
        )
        job = uow.cursor.fetchone()
        if (
            job is None
            or str(job[0] or "") != claim.attempt_id
            or int(job[1]) != claim.fencing_token
            or str(job[2]) not in {"RUNNING", "CHECKPOINTED"}
            or str(job[3]) != claim.worker_id
            or str(job[4]) != claim.lease_id
            or str(job[5]) != claim.lease_id
            or str(job[6]) != claim.worker_id
            or str(job[7]) != "HELD"
            or str(row[3] or "") != claim.runtime_job_id
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_STALE_RUNTIME_FENCE",
                "repair RuntimeJob lease or fence is stale",
            )
        valid_command_fence, _ = uow.repositories.attempt_runtime.current_fence(
            worker.attempt_id, worker.worker_id, worker.fencing_token
        )
        uow.cursor.execute(
            """
            SELECT attempt.operation_id, operation.project_id
            FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id=attempt.operation_id
            WHERE attempt.attempt_id=%s
            """,
            [worker.attempt_id],
        )
        command_attempt = uow.cursor.fetchone()
        if (
            not valid_command_fence
            or command_attempt is None
            or str(command_attempt[0]) != worker.causation_id
            or str(command_attempt[1]) != worker.project_id
        ):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_STALE_COMMAND_FENCE",
                "repair Command Attempt lease or fence is stale",
            )
        if int(row[12]) != int(row[4]):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_TARGET_DRIFT",
                "Book accepted cursor changed after repair discovery",
            )
        return {
            "repair_id": repair_id,
            "project_id": str(row[0]),
            "book_id": str(row[1]),
            "book_run_id": str(row[2]),
            "target_chapter": int(row[4]),
            "next_chapter": int(row[5]),
            "authoritative_status": str(row[6]),
            "repair_version": int(row[7]),
            "target_evidence_digest": str(row[8]),
            "workspace_id": str(row[9]),
            "longform_context_versions": dict(row[10] or {}),
            "book_version": int(row[11]),
            "active_projection_set_id": str(row[13] or ""),
            "active_story_state_version_id": str(row[14] or ""),
            "active_canon_snapshot_version_id": str(row[15] or ""),
            "last_chapter_outcome_version_id": str(row[16] or ""),
        }

    @staticmethod
    def _load_chapter_source(
        uow: AuthorityUnitOfWork,
        context: Mapping[str, Any],
        chapter_number: int,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT acceptance.acceptance_id,
                   acceptance.acceptance_operation_id,
                   acceptance.chapter_request_id,
                   acceptance.chapter_outcome_asset_version_id,
                   outcome.content_hash, outcome.content,
                   acceptance.story_state_asset_version_id,
                   story.content_hash, story.content,
                   acceptance.canon_snapshot_asset_version_id,
                   canon.content_hash,
                   request.chapter_plan_version, request.command_payload,
                   acceptance.longform_projection_set_id
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
             AND request.book_run_id=acceptance.book_run_id
            JOIN authority_operation AS operation
              ON operation.operation_id=acceptance.acceptance_operation_id
             AND operation.status='SUCCEEDED'
            JOIN authority_asset_version AS outcome
              ON outcome.asset_version_id=
                 acceptance.chapter_outcome_asset_version_id
            JOIN authority_asset_version AS story
              ON story.asset_version_id=acceptance.story_state_asset_version_id
            JOIN authority_asset_version AS canon
              ON canon.asset_version_id=acceptance.canon_snapshot_asset_version_id
            WHERE acceptance.book_run_id=%s AND acceptance.project_id=%s
              AND acceptance.chapter_number=%s
              AND acceptance.status='COMMITTED'
            """,
            [context["book_run_id"], context["project_id"], chapter_number],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_ACCEPTED_SOURCE_MISSING",
                "repair requires one committed acceptance and accepted assets",
            )
        command_payload = dict(row[12] or {})
        plan_version = str(
            command_payload.get("execution_chapter_plan_asset_version_id")
            or row[11]
            or ""
        )
        uow.cursor.execute(
            """
            SELECT content_hash, content
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [plan_version],
        )
        plan = uow.cursor.fetchone()
        if plan is None:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_FROZEN_PLAN_MISSING",
                "repair requires the frozen ChapterPlan AssetVersion",
            )
        return {
            "acceptance_id": str(row[0]),
            "acceptance_operation_id": str(row[1]),
            "chapter_request_id": str(row[2]),
            "chapter_outcome_asset_version_id": str(row[3]),
            "chapter_outcome_content_hash": str(row[4]),
            "chapter_outcome": dict(row[5] or {}),
            "story_state_asset_version_id": str(row[6]),
            "story_state_content_hash": str(row[7]),
            "story_state": dict(row[8] or {}),
            "canon_snapshot_asset_version_id": str(row[9]),
            "canon_snapshot_content_hash": str(row[10]),
            "chapter_plan_asset_version_id": plan_version,
            "chapter_plan_content_hash": str(plan[0]),
            "chapter_plan": dict(plan[1] or {}),
            "command_payload": command_payload,
            "longform_projection_set_id": str(row[13] or ""),
        }

    @staticmethod
    def _load_previous_arc_states(
        uow: AuthorityUnitOfWork,
        context: Mapping[str, Any],
        chapter_number: int,
    ) -> dict[str, dict[str, Any]]:
        if chapter_number <= 1:
            return {}
        uow.cursor.execute(
            """
            SELECT arc_state
            FROM authority_book_narrative_projection_set
            WHERE book_run_id=%s AND chapter_number=%s AND status='COMPLETE'
            """,
            [context["book_run_id"], chapter_number - 1],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_PREVIOUS_PROJECTION_MISSING",
                "repair must rebuild accepted projections in chapter order",
            )
        states = {
            str(item.get("arc_plan_version_id") or ""): dict(item)
            for item in row[0] or ()
            if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
        }
        uow.cursor.execute(
            """
            SELECT outcome.arc_plan_version_id, outcome.status,
                   outcome.accepted_through_chapter
            FROM authority_arc_outcome_v2 AS outcome
            JOIN authority_book_narrative_projection_set AS projection
              ON projection.projection_set_id=outcome.projection_set_id
            WHERE projection.book_run_id=%s
              AND outcome.accepted_through_chapter < %s
            """,
            [context["book_run_id"], chapter_number],
        )
        for arc_id, lifecycle, accepted_chapter in uow.cursor.fetchall():
            states.setdefault(
                str(arc_id),
                {
                    "arc_plan_version_id": str(arc_id),
                    "lifecycle_status": str(lifecycle),
                    "accepted_through_chapter": int(accepted_chapter),
                    "cumulative_progress_units": 0,
                },
            )
        return states

    @staticmethod
    def _assert_projection_equal(
        uow: AuthorityUnitOfWork, projection: Mapping[str, Any]
    ) -> None:
        uow.cursor.execute(
            """
            SELECT projection_set_id, chapter_outcome_asset_version_id,
                   story_state_asset_version_id, canon_snapshot_asset_version_id,
                   arc_state, obligation_state, projection_hash,
                   projection_provenance, status
            FROM authority_book_narrative_projection_set
            WHERE acceptance_id=%s
            """,
            [projection["accepted_boundary"]["acceptance_id"]],
        )
        row = uow.cursor.fetchone()
        sources = dict(projection["source_versions"])
        expected = (
            projection["projection_set_id"],
            sources["chapter_outcome_asset_version_id"],
            sources["story_state_asset_version_id"],
            sources["canon_snapshot_asset_version_id"],
            list(projection["arc_states"]),
            list(projection["obligation_states"]),
            projection["projection_hash"],
            dict(projection["projection_provenance"]),
            "COMPLETE",
        )
        if row is None or tuple(row) != expected:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_IDEMPOTENCY_CONFLICT",
                "existing projection differs from canonical projector output",
            )
        PostgresBookProjectionRepairAuthority._assert_projection_components_equal(
            uow, projection
        )

    @staticmethod
    def _assert_projection_components_equal(
        uow: AuthorityUnitOfWork, projection: Mapping[str, Any]
    ) -> None:
        projection_set_id = str(projection["projection_set_id"])
        checks: tuple[tuple[str, str, tuple[tuple[Any, ...], ...]], ...] = (
            (
                "ArcProgress",
                """
                SELECT progress_id, projection_set_id, evidence
                FROM authority_arc_progress_v2
                WHERE projection_set_id=%s ORDER BY progress_id
                """,
                tuple(
                    sorted(
                        (
                            str(item["progress_id"]),
                            projection_set_id,
                            dict(item["evidence"]),
                        )
                        for item in projection["arc_progress"]
                    )
                ),
            ),
            (
                "ArcCheckpoint",
                """
                SELECT checkpoint_id, projection_set_id, checkpoint
                FROM authority_arc_checkpoint_v2
                WHERE projection_set_id=%s ORDER BY checkpoint_id
                """,
                tuple(
                    sorted(
                        (
                            str(item["checkpoint_id"]),
                            projection_set_id,
                            dict(item),
                        )
                        for item in projection["arc_checkpoints"]
                    )
                ),
            ),
            (
                "ArcOutcome",
                """
                SELECT arc_outcome_id, projection_set_id, completion_evidence
                FROM authority_arc_outcome_v2
                WHERE projection_set_id=%s ORDER BY arc_outcome_id
                """,
                tuple(
                    sorted(
                        (
                            str(item["arc_outcome_id"]),
                            projection_set_id,
                            dict(item["completion_evidence"]),
                        )
                        for item in projection["arc_outcomes"]
                    )
                ),
            ),
        )
        for label, sql, expected_rows in checks:
            uow.cursor.execute(sql, [projection_set_id])
            actual_rows = tuple(
                (str(row[0]), str(row[1]), dict(row[2] or {}))
                for row in uow.cursor.fetchall()
            )
            if actual_rows != expected_rows:
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_COMPONENT_CONFLICT",
                    f"existing {label} components differ from canonical output",
                )
        for state in projection["arc_states"]:
            uow.cursor.execute(
                """
                SELECT projection_set_id, state
                FROM authority_arc_actual_state
                WHERE project_id=%s AND book_id=%s AND arc_plan_version_id=%s
                """,
                [
                    projection["project_id"],
                    projection["book_id"],
                    state["arc_plan_version_id"],
                ],
            )
            row = uow.cursor.fetchone()
            if (
                row is None
                or str(row[0]) != projection_set_id
                or dict(row[1]) != dict(state)
            ):
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_COMPONENT_CONFLICT",
                    "ArcActualState does not match the canonical projection",
                )
        for obligation in projection["obligation_states"]:
            state = dict(obligation.get("state") or {})
            obligation_id = str(
                state.get("obligation_id") or obligation.get("entity_key") or ""
            )
            uow.cursor.execute(
                """
                SELECT projection_set_id, state
                FROM authority_narrative_obligation_state
                WHERE project_id=%s AND book_id=%s AND obligation_id=%s
                """,
                [projection["project_id"], projection["book_id"], obligation_id],
            )
            row = uow.cursor.fetchone()
            if (
                row is None
                or str(row[0]) != projection_set_id
                or dict(row[1]) != dict(obligation)
            ):
                raise KernelError(
                    "BOOK_PROJECTION_REPAIR_COMPONENT_CONFLICT",
                    "NarrativeObligation state does not match canonical projection",
                )
        uow.cursor.execute(
            """
            SELECT COUNT(*), BOOL_AND(metadata->>'projection_set_id'=%s)
            FROM authority_narrative_retrieval_document
            WHERE project_id=%s AND book_id=%s
              AND metadata->>'projection_set_id'=%s
            """,
            [
                projection_set_id,
                projection["project_id"],
                projection["book_id"],
                projection_set_id,
            ],
        )
        retrieval = uow.cursor.fetchone()
        if retrieval is None or int(retrieval[0]) < 5 or not bool(retrieval[1]):
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_COMPONENT_CONFLICT",
                "accepted retrieval projections are incomplete",
            )

    @staticmethod
    def _assert_checkpoint_equal(
        uow: AuthorityUnitOfWork,
        *,
        repair_id: str,
        chapter_number: int,
        projection: Mapping[str, Any],
        source_digest: str,
    ) -> None:
        uow.cursor.execute(
            """
            SELECT projection_set_id, source_evidence_digest, projection_hash
            FROM authority_book_projection_repair_checkpoint
            WHERE repair_id=%s AND chapter_number=%s
            """,
            [repair_id, chapter_number],
        )
        row = uow.cursor.fetchone()
        expected = (
            projection["projection_set_id"],
            source_digest,
            projection["projection_hash"],
        )
        if row is None or tuple(row) != expected:
            raise KernelError(
                "BOOK_PROJECTION_REPAIR_CHECKPOINT_CONFLICT",
                "existing repair checkpoint differs from canonical output",
            )

    @staticmethod
    def _terminal_rows(
        uow: AuthorityUnitOfWork, repair_id: str, book_run_id: str
    ) -> list[dict[str, Any]]:
        uow.cursor.execute(
            """
            SELECT acceptance.chapter_number, acceptance.acceptance_id,
                   acceptance.longform_projection_set_id,
                   acceptance.chapter_outcome_asset_version_id,
                   acceptance.story_state_asset_version_id,
                   acceptance.canon_snapshot_asset_version_id,
                   projection.projection_set_id, projection.status,
                   projection.chapter_outcome_asset_version_id,
                   projection.story_state_asset_version_id,
                   projection.canon_snapshot_asset_version_id,
                   projection.projection_hash,
                   checkpoint.checkpoint_id, checkpoint.projection_hash
            FROM authority_book_chapter_acceptance AS acceptance
            LEFT JOIN authority_book_narrative_projection_set AS projection
              ON projection.projection_set_id=
                 acceptance.longform_projection_set_id
            LEFT JOIN authority_book_projection_repair_checkpoint AS checkpoint
              ON checkpoint.repair_id=%s
             AND checkpoint.chapter_number=acceptance.chapter_number
            WHERE acceptance.book_run_id=%s AND acceptance.status='COMMITTED'
            ORDER BY acceptance.chapter_number
            """,
            [repair_id, book_run_id],
        )
        keys = (
            "chapter_number",
            "acceptance_id",
            "acceptance_projection_set_id",
            "acceptance_chapter_outcome_asset_version_id",
            "acceptance_story_state_asset_version_id",
            "acceptance_canon_snapshot_asset_version_id",
            "projection_set_id",
            "projection_status",
            "projection_chapter_outcome_asset_version_id",
            "projection_story_state_asset_version_id",
            "projection_canon_snapshot_asset_version_id",
            "projection_hash",
            "checkpoint_id",
            "checkpoint_projection_hash",
        )
        return [dict(zip(keys, row, strict=True)) for row in uow.cursor.fetchall()]

    @staticmethod
    def _record_event(
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        context: Mapping[str, Any],
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_projection_repair",
                "aggregate_id": str(context["repair_id"]),
                "operation_id": operation_id,
                "project_id": str(context["project_id"]),
                "event_type": event_type,
                "correlation_id": str(context["repair_id"]),
                "causation_id": "",
                "payload": dict(payload),
            }
        )

    @staticmethod
    def _result(
        repair: Mapping[str, Any], processed: tuple[int, ...]
    ) -> ProjectionRepairBatchResult:
        return ProjectionRepairBatchResult(
            repair_id=str(repair["repair_id"]),
            book_run_id=str(repair["book_run_id"]),
            processed_chapters=processed,
            next_chapter=int(repair["next_chapter"]),
            target_chapter=int(repair["target_accepted_through_chapter"]),
            authoritative_status=str(repair["authoritative_status"]),
            terminal_digest=str(repair.get("terminal_digest") or ""),
        )


def book_projection_repair_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": BOOK_PROJECTION_REPAIR_DEFINITION,
        "definition_version": BOOK_PROJECTION_REPAIR_DEFINITION_VERSION,
        "family": "book_authority",
        "enabled": True,
        "definition_status": "enabled",
        "command_schema_version": "book.projection.repair.command.v1",
        "result_schema_version": "book.projection.repair.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "BookProjectionRepairResult"},
        "handler_key": BOOK_PROJECTION_REPAIR_HANDLER,
        "handler_contract_version": "book-projection-repair-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "book:projection-repair",
        "concurrency_key_template": "book:{book_id}:projection-repair",
        "retry_policy": {"max_attempts": 3},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "accepted evidence is immutable and repair is idempotent",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "execution_classification": "attempt_worker",
            "authority": "PostgresBookAuthority",
            "canonical_projector": "accepted-longform-projector-v2",
            "terminal_pointer_activation": "fenced_cas",
            "external_effects": "forbidden",
        },
        "completion_contract": {
            "version": "book-projection-repair-completion-v1",
            "required_evidence": ["trace", "audit"],
        },
    }


__all__ = [
    "BOOK_PROJECTION_REPAIR_DEFINITION",
    "PostgresBookProjectionRepairAuthority",
    "ProjectionRepairBatchResult",
    "book_projection_repair_definition",
    "validate_terminal_repair_rows",
]
