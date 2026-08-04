from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


ACTIVE_JOB_STATUSES = frozenset({"CLAIMED", "RUNNING", "CHECKPOINTED"})
SCHEDULABLE_JOB_STATUSES = frozenset({"READY", "RETRY_WAIT"})
TERMINAL_JOB_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "DEAD_LETTER", "CANCELLED"}
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def canonical_payload_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_runtime_job_id(
    *, runtime_group: str, job_kind: str, dedupe_key: str
) -> str:
    identity = "\x1f".join((runtime_group, job_kind, dedupe_key))
    return "runtime-job:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeJobSpec:
    job_kind: str
    runtime_group: str
    subject_kind: str
    subject_id: str
    project_id: str
    dedupe_key: str
    input_snapshot: dict[str, Any]
    priority: int = 100
    max_attempts: int = 5
    available_at: datetime | None = None

    def __post_init__(self) -> None:
        required = (
            self.job_kind,
            self.runtime_group,
            self.subject_kind,
            self.subject_id,
            self.dedupe_key,
        )
        if any(not str(item).strip() for item in required):
            raise ValueError("runtime job execution identity fields are required")
        if self.max_attempts <= 0:
            raise ValueError("runtime job max_attempts must be positive")
        if self.priority < 0:
            raise ValueError("runtime job priority cannot be negative")
        if self.available_at is not None and self.available_at.tzinfo is None:
            raise ValueError("runtime job available_at must be timezone-aware")

    @property
    def runtime_job_id(self) -> str:
        return deterministic_runtime_job_id(
            runtime_group=self.runtime_group,
            job_kind=self.job_kind,
            dedupe_key=self.dedupe_key,
        )

    @property
    def input_hash(self) -> str:
        return canonical_payload_hash(self.input_snapshot)


@dataclass(frozen=True, slots=True)
class RuntimeJobClaim:
    runtime_job_id: str
    job_kind: str
    runtime_group: str
    subject_kind: str
    subject_id: str
    project_id: str
    attempt_id: str
    attempt_number: int
    worker_id: str
    lease_id: str
    fencing_token: int
    lease_expires_at: datetime
    input_snapshot: dict[str, Any]


class RuntimeJobAuthority:
    """Transactional execution coordinator for non-business runtime work."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Runtime Job Authority requires a database URL")
        self.database_url = database_url

    def schedule(self, spec: RuntimeJobSpec) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id, job_kind, runtime_group, subject_kind,
                    subject_id, project_id, dedupe_key, input_snapshot,
                    input_hash, status, priority, available_at, max_attempts
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,'READY',%s,
                    COALESCE(%s, NOW()),%s
                )
                ON CONFLICT DO NOTHING
                """,
                [
                    spec.runtime_job_id,
                    spec.job_kind,
                    spec.runtime_group,
                    spec.subject_kind,
                    spec.subject_id,
                    spec.project_id,
                    spec.dedupe_key,
                    Jsonb(spec.input_snapshot),
                    spec.input_hash,
                    spec.priority,
                    spec.available_at,
                    spec.max_attempts,
                ],
            )
            created = uow.cursor.rowcount == 1
            uow.cursor.execute(
                """
                SELECT runtime_job_id, input_hash, status, current_attempt_id,
                       dedupe_key
                FROM authority_runtime_job
                WHERE runtime_group=%s AND job_kind=%s
                  AND (
                      dedupe_key=%s
                      OR (
                          subject_kind=%s AND subject_id=%s
                          AND status IN (
                              'READY','CLAIMED','RUNNING','CHECKPOINTED','RETRY_WAIT'
                          )
                      )
                  )
                ORDER BY CASE WHEN dedupe_key=%s THEN 0 ELSE 1 END, created_at
                LIMIT 1
                FOR UPDATE
                """,
                [
                    spec.runtime_group,
                    spec.job_kind,
                    spec.dedupe_key,
                    spec.subject_kind,
                    spec.subject_id,
                    spec.dedupe_key,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "RUNTIME_JOB_SCHEDULE_CONFLICT",
                    "runtime job insert conflicted without a recoverable identity",
                )
            exact_dedupe = str(row[4]) == spec.dedupe_key
            if exact_dedupe and str(row[1]) != spec.input_hash:
                raise KernelError(
                    "RUNTIME_JOB_IDEMPOTENCY_CONFLICT",
                    "runtime job dedupe identity was reused with different input",
                )
            runtime_job_id = str(row[0])
            if created:
                self._append_event(
                    uow,
                    runtime_job_id=runtime_job_id,
                    attempt_id="",
                    event_type="runtime_job.scheduled",
                    worker_id="",
                    fencing_token=0,
                    payload={
                        "job_kind": spec.job_kind,
                        "runtime_group": spec.runtime_group,
                        "subject_kind": spec.subject_kind,
                        "subject_id": spec.subject_id,
                        "input_hash": spec.input_hash,
                    },
                )
            uow.commit()
        return {
            "runtime_job_id": runtime_job_id,
            "status": str(row[2]),
            "current_attempt_id": str(row[3] or ""),
            "created": created,
            "deduplicated": not created,
            "coalesced_active_subject": not exact_dedupe,
            "input_hash": spec.input_hash,
        }

    def claim(
        self,
        *,
        runtime_group: str,
        worker_id: str,
        lease_seconds: int,
        job_kinds: Iterable[str] = (),
        subject_kind: str = "",
        subject_id: str = "",
    ) -> RuntimeJobClaim | None:
        if not runtime_group or not worker_id or lease_seconds <= 0:
            raise ValueError("runtime group, worker and positive lease are required")
        if bool(subject_kind) != bool(subject_id):
            raise ValueError("runtime job subject filter requires kind and id")
        kinds = tuple(dict.fromkeys(str(item) for item in job_kinds if str(item)))
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT job.runtime_job_id, job.job_kind, job.subject_kind,
                       job.subject_id, job.project_id, job.attempt_count,
                       job.current_attempt_id, job.current_fencing_token,
                       job.status, job.input_snapshot, job.max_attempts
                FROM authority_runtime_job AS job
                WHERE job.runtime_group=%s
                  AND (%s::text[]='{}'::text[] OR job.job_kind=ANY(%s))
                  AND (%s='' OR (job.subject_kind=%s AND job.subject_id=%s))
                  AND (
                      (
                          job.status IN ('READY','RETRY_WAIT')
                          AND job.attempt_count < job.max_attempts
                          AND job.available_at <= NOW()
                      )
                      OR (
                          job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                          AND EXISTS (
                              SELECT 1 FROM authority_runtime_job_lease AS lease
                              WHERE lease.attempt_id=job.current_attempt_id
                                AND lease.status='HELD'
                                AND lease.lease_expires_at <= NOW()
                          )
                      )
                  )
                ORDER BY job.priority, job.available_at, job.created_at,
                         job.runtime_job_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                [
                    runtime_group,
                    list(kinds),
                    list(kinds),
                    subject_kind,
                    subject_kind,
                    subject_id,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                return None
            runtime_job_id = str(row[0])
            previous_attempt_id = str(row[6] or "")
            previous_status = str(row[8])
            if previous_status in ACTIVE_JOB_STATUSES:
                uow.cursor.execute(
                    """
                    UPDATE authority_runtime_job_lease
                    SET status='EXPIRED', released_at=NOW(),
                        release_reason='lease_expired_takeover'
                    WHERE attempt_id=%s AND status='HELD'
                      AND lease_expires_at <= NOW()
                    """,
                    [previous_attempt_id],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "RUNTIME_JOB_LEASE_NOT_EXPIRED",
                        "runtime job takeover requires an expired held lease",
                    )
                uow.cursor.execute(
                    """
                    UPDATE authority_runtime_job_attempt
                    SET status='ABANDONED', completed_at=NOW(),
                        error=%s
                    WHERE attempt_id=%s
                    """,
                    [Jsonb({"code": "LEASE_EXPIRED_TAKEOVER"}), previous_attempt_id],
                )
                self._append_event(
                    uow,
                    runtime_job_id=runtime_job_id,
                    attempt_id=previous_attempt_id,
                    event_type="runtime_job.lease_expired",
                    worker_id=worker_id,
                    fencing_token=int(row[7]),
                    payload={"previous_status": previous_status},
                )
                if int(row[5]) >= int(row[10]):
                    terminal_error = {
                        "code": "FINAL_ATTEMPT_LEASE_EXPIRED",
                        "attempt_id": previous_attempt_id,
                    }
                    uow.cursor.execute(
                        """
                        UPDATE authority_runtime_job
                        SET status='DEAD_LETTER', claimed_by='',
                            last_error=%s, completed_at=NOW(), updated_at=NOW()
                        WHERE runtime_job_id=%s
                          AND current_attempt_id=%s
                          AND current_fencing_token=%s
                        """,
                        [
                            Jsonb(terminal_error),
                            runtime_job_id,
                            previous_attempt_id,
                            int(row[7]),
                        ],
                    )
                    if uow.cursor.rowcount != 1:
                        self._raise_stale_claim()
                    self._append_event(
                        uow,
                        runtime_job_id=runtime_job_id,
                        attempt_id=previous_attempt_id,
                        event_type="runtime_job.dead_lettered",
                        worker_id=worker_id,
                        fencing_token=int(row[7]),
                        payload=terminal_error,
                    )
                    uow.commit()
                    return None
            attempt_number = int(row[5]) + 1
            fencing_token = int(row[7]) + 1
            attempt_id = f"runtime-attempt:{uuid4()}"
            lease_id = f"runtime-lease:{uuid4()}"
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job_attempt(
                    attempt_id, runtime_job_id, attempt_number, worker_id,
                    status, lease_id, fencing_token, lease_expires_at,
                    heartbeat_at, started_at
                ) VALUES (
                    %s,%s,%s,%s,'CLAIMED',%s,%s,
                    NOW() + (%s * INTERVAL '1 second'),NOW(),NOW()
                )
                """,
                [
                    attempt_id,
                    runtime_job_id,
                    attempt_number,
                    worker_id,
                    lease_id,
                    fencing_token,
                    lease_seconds,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job_lease(
                    lease_id, runtime_job_id, attempt_id, worker_id,
                    fencing_token, lease_expires_at, heartbeat_at, status
                ) VALUES (
                    %s,%s,%s,%s,%s,
                    NOW() + (%s * INTERVAL '1 second'),NOW(),'HELD'
                )
                RETURNING lease_expires_at
                """,
                [
                    lease_id,
                    runtime_job_id,
                    attempt_id,
                    worker_id,
                    fencing_token,
                    lease_seconds,
                ],
            )
            lease_expires_at = uow.cursor.fetchone()[0]
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status='CLAIMED', claimed_by=%s, current_attempt_id=%s,
                    current_fencing_token=%s, attempt_count=%s, updated_at=NOW()
                WHERE runtime_job_id=%s
                """,
                [
                    worker_id,
                    attempt_id,
                    fencing_token,
                    attempt_number,
                    runtime_job_id,
                ],
            )
            self._append_event(
                uow,
                runtime_job_id=runtime_job_id,
                attempt_id=attempt_id,
                event_type=(
                    "runtime_job.taken_over"
                    if previous_status in ACTIVE_JOB_STATUSES
                    else "runtime_job.claimed"
                ),
                worker_id=worker_id,
                fencing_token=fencing_token,
                payload={
                    "lease_id": lease_id,
                    "attempt_number": attempt_number,
                    "lease_seconds": lease_seconds,
                },
            )
            uow.commit()
        return RuntimeJobClaim(
            runtime_job_id=runtime_job_id,
            job_kind=str(row[1]),
            runtime_group=runtime_group,
            subject_kind=str(row[2]),
            subject_id=str(row[3]),
            project_id=str(row[4] or ""),
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            worker_id=worker_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            lease_expires_at=lease_expires_at,
            input_snapshot=dict(row[9] or {}),
        )

    def start(self, claim: RuntimeJobClaim) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_and_assert_claim(uow, claim)
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='RUNNING', started_at=COALESCE(started_at,NOW())
                WHERE attempt_id=%s AND status='CLAIMED'
                """,
                [claim.attempt_id],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "RUNTIME_JOB_STATE_CONFLICT",
                    "runtime job attempt must be CLAIMED before start",
                )
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job SET status='RUNNING', updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                """,
                [claim.runtime_job_id, claim.attempt_id],
            )
            self._append_event(
                uow,
                runtime_job_id=claim.runtime_job_id,
                attempt_id=claim.attempt_id,
                event_type="runtime_job.started",
                worker_id=claim.worker_id,
                fencing_token=claim.fencing_token,
                payload={},
            )
            uow.commit()
        return {"runtime_job_id": claim.runtime_job_id, "status": "RUNNING"}

    def heartbeat(
        self, claim: RuntimeJobClaim, *, lease_seconds: int
    ) -> dict[str, Any]:
        if lease_seconds <= 0:
            raise ValueError("runtime job heartbeat lease must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_and_assert_claim(uow, claim)
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_lease
                SET heartbeat_at=NOW(),
                    lease_expires_at=NOW() + (%s * INTERVAL '1 second')
                WHERE lease_id=%s AND attempt_id=%s AND worker_id=%s
                  AND fencing_token=%s AND status='HELD'
                  AND lease_expires_at > NOW()
                RETURNING lease_expires_at
                """,
                [
                    lease_seconds,
                    claim.lease_id,
                    claim.attempt_id,
                    claim.worker_id,
                    claim.fencing_token,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                self._raise_stale_claim()
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET heartbeat_at=NOW(), lease_expires_at=%s
                WHERE attempt_id=%s
                """,
                [row[0], claim.attempt_id],
            )
            uow.commit()
        return {"lease_expires_at": row[0], "fencing_token": claim.fencing_token}

    def checkpoint(
        self, claim: RuntimeJobClaim, checkpoint: dict[str, Any]
    ) -> dict[str, Any]:
        checkpoint_hash = canonical_payload_hash(checkpoint)
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_and_assert_claim(uow, claim)
            uow.cursor.execute(
                """
                SELECT COALESCE(MAX(checkpoint_sequence),0)+1
                FROM authority_runtime_job_checkpoint
                WHERE attempt_id=%s
                """,
                [claim.attempt_id],
            )
            sequence = int(uow.cursor.fetchone()[0])
            checkpoint_id = f"runtime-checkpoint:{uuid4()}"
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job_checkpoint(
                    checkpoint_id, runtime_job_id, attempt_id,
                    checkpoint_sequence, fencing_token, checkpoint,
                    checkpoint_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    checkpoint_id,
                    claim.runtime_job_id,
                    claim.attempt_id,
                    sequence,
                    claim.fencing_token,
                    Jsonb(checkpoint),
                    checkpoint_hash,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='CHECKPOINTED', checkpoint=%s,
                    checkpoint_hash=%s, checkpoint_sequence=%s,
                    heartbeat_at=NOW()
                WHERE attempt_id=%s
                """,
                [Jsonb(checkpoint), checkpoint_hash, sequence, claim.attempt_id],
            )
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status='CHECKPOINTED', updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                """,
                [claim.runtime_job_id, claim.attempt_id],
            )
            self._append_event(
                uow,
                runtime_job_id=claim.runtime_job_id,
                attempt_id=claim.attempt_id,
                event_type="runtime_job.checkpointed",
                worker_id=claim.worker_id,
                fencing_token=claim.fencing_token,
                payload={
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_sequence": sequence,
                    "checkpoint_hash": checkpoint_hash,
                },
            )
            uow.commit()
        return {
            "checkpoint_id": checkpoint_id,
            "checkpoint_sequence": sequence,
            "checkpoint_hash": checkpoint_hash,
        }

    def complete(
        self, claim: RuntimeJobClaim, result: dict[str, Any]
    ) -> dict[str, Any]:
        result_hash = canonical_payload_hash(result)
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_and_assert_claim(uow, claim)
            result_id = f"runtime-result:{uuid4()}"
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job_result(
                    result_id, runtime_job_id, attempt_id, fencing_token,
                    status, result, result_hash
                ) VALUES (%s,%s,%s,%s,'SUCCEEDED',%s,%s)
                """,
                [
                    result_id,
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                    Jsonb(result),
                    result_hash,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='SUCCEEDED', result_hash=%s, completed_at=NOW()
                WHERE attempt_id=%s
                """,
                [result_hash, claim.attempt_id],
            )
            self._release_lease(uow, claim, reason="completed")
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status='SUCCEEDED', claimed_by='', result_hash=%s,
                    completed_at=NOW(), updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                  AND current_fencing_token=%s
                """,
                [
                    result_hash,
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            self._append_event(
                uow,
                runtime_job_id=claim.runtime_job_id,
                attempt_id=claim.attempt_id,
                event_type="runtime_job.succeeded",
                worker_id=claim.worker_id,
                fencing_token=claim.fencing_token,
                payload={"result_id": result_id, "result_hash": result_hash},
            )
            uow.commit()
        return {
            "runtime_job_id": claim.runtime_job_id,
            "attempt_id": claim.attempt_id,
            "status": "SUCCEEDED",
            "result_id": result_id,
            "result_hash": result_hash,
        }

    def fail(
        self,
        claim: RuntimeJobClaim,
        error: dict[str, Any],
        *,
        retry_delay_seconds: int = 0,
    ) -> dict[str, Any]:
        if retry_delay_seconds < 0:
            raise ValueError("runtime job retry delay cannot be negative")
        error_hash = canonical_payload_hash(error)
        with AuthorityUnitOfWork(self.database_url) as uow:
            job = self._lock_and_assert_claim(uow, claim)
            terminal = int(job[2]) >= int(job[3])
            job_status = "DEAD_LETTER" if terminal else "RETRY_WAIT"
            result_id = f"runtime-result:{uuid4()}"
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job_result(
                    result_id, runtime_job_id, attempt_id, fencing_token,
                    status, result, result_hash
                ) VALUES (%s,%s,%s,%s,'FAILED',%s,%s)
                """,
                [
                    result_id,
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                    Jsonb(error),
                    error_hash,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='FAILED', error=%s, result_hash=%s,
                    completed_at=NOW()
                WHERE attempt_id=%s
                """,
                [Jsonb(error), error_hash, claim.attempt_id],
            )
            self._release_lease(uow, claim, reason="attempt_failed")
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status=%s, claimed_by='', last_error=%s,
                    available_at=NOW() + (%s * INTERVAL '1 second'),
                    completed_at=CASE WHEN %s='DEAD_LETTER' THEN NOW() ELSE NULL END,
                    updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                  AND current_fencing_token=%s
                """,
                [
                    job_status,
                    Jsonb(error),
                    retry_delay_seconds,
                    job_status,
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            self._append_event(
                uow,
                runtime_job_id=claim.runtime_job_id,
                attempt_id=claim.attempt_id,
                event_type=(
                    "runtime_job.dead_lettered"
                    if terminal
                    else "runtime_job.retry_scheduled"
                ),
                worker_id=claim.worker_id,
                fencing_token=claim.fencing_token,
                payload={
                    "error_hash": error_hash,
                    "retry_delay_seconds": retry_delay_seconds,
                },
            )
            uow.commit()
        return {
            "runtime_job_id": claim.runtime_job_id,
            "attempt_id": claim.attempt_id,
            "status": job_status,
            "error_hash": error_hash,
        }

    def get(self, runtime_job_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT runtime_job_id, job_kind, runtime_group, subject_kind,
                       subject_id, project_id, dedupe_key, input_snapshot,
                       input_hash, status, priority, available_at,
                       attempt_count, max_attempts, claimed_by,
                       current_attempt_id, current_fencing_token,
                       result_hash, last_error, created_at, updated_at,
                       completed_at
                FROM authority_runtime_job WHERE runtime_job_id=%s
                """,
                [runtime_job_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("RUNTIME_JOB_NOT_FOUND", "runtime job does not exist")
        keys = (
            "runtime_job_id",
            "job_kind",
            "runtime_group",
            "subject_kind",
            "subject_id",
            "project_id",
            "dedupe_key",
            "input_snapshot",
            "input_hash",
            "status",
            "priority",
            "available_at",
            "attempt_count",
            "max_attempts",
            "claimed_by",
            "current_attempt_id",
            "current_fencing_token",
            "result_hash",
            "last_error",
            "created_at",
            "updated_at",
            "completed_at",
        )
        return dict(zip(keys, row, strict=True))

    def _lock_and_assert_claim(
        self, uow: AuthorityUnitOfWork, claim: RuntimeJobClaim
    ) -> tuple[Any, ...]:
        uow.cursor.execute(
            """
            SELECT job.status, job.current_attempt_id, job.attempt_count,
                   job.max_attempts, job.current_fencing_token,
                   attempt.worker_id, attempt.status, attempt.lease_id,
                   lease.lease_id, lease.worker_id, lease.status,
                   lease.lease_expires_at
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s
              AND lease.lease_expires_at > NOW()
            FOR UPDATE OF job, attempt, lease
            """,
            [claim.runtime_job_id],
        )
        row = uow.cursor.fetchone()
        valid = bool(
            row is not None
            and str(row[1]) == claim.attempt_id
            and int(row[4]) == claim.fencing_token
            and str(row[5]) == claim.worker_id
            and str(row[7]) == claim.lease_id
            and str(row[8]) == claim.lease_id
            and str(row[9]) == claim.worker_id
            and str(row[10]) == "HELD"
            and str(row[0]) in ACTIVE_JOB_STATUSES
        )
        if not valid:
            self._raise_stale_claim()
        return row

    @staticmethod
    def _release_lease(
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        *,
        reason: str,
    ) -> None:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET status='RELEASED', released_at=NOW(), release_reason=%s
            WHERE lease_id=%s AND attempt_id=%s AND worker_id=%s
              AND fencing_token=%s AND status='HELD'
            """,
            [
                reason,
                claim.lease_id,
                claim.attempt_id,
                claim.worker_id,
                claim.fencing_token,
            ],
        )
        if uow.cursor.rowcount != 1:
            RuntimeJobAuthority._raise_stale_claim()

    @staticmethod
    def _raise_stale_claim() -> None:
        raise KernelError(
            "RUNTIME_JOB_FENCE_STALE",
            "runtime job result or checkpoint carries a stale fencing claim",
        )

    @staticmethod
    def _append_event(
        uow: AuthorityUnitOfWork,
        *,
        runtime_job_id: str,
        attempt_id: str,
        event_type: str,
        worker_id: str,
        fencing_token: int,
        payload: dict[str, Any],
    ) -> None:
        uow.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number),0)+1
            FROM authority_runtime_job_event
            WHERE runtime_job_id=%s
            """,
            [runtime_job_id],
        )
        sequence = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job_event(
                runtime_job_event_id, runtime_job_id, attempt_id,
                sequence_number, event_type, worker_id, fencing_token,
                payload
            ) VALUES (%s,%s,NULLIF(%s,''),%s,%s,%s,%s,%s)
            """,
            [
                f"runtime-event:{uuid4()}",
                runtime_job_id,
                attempt_id,
                sequence,
                event_type,
                worker_id,
                fencing_token,
                Jsonb(payload),
            ],
        )


__all__ = [
    "ACTIVE_JOB_STATUSES",
    "RuntimeJobAuthority",
    "RuntimeJobClaim",
    "RuntimeJobSpec",
    "SCHEDULABLE_JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "canonical_payload_hash",
    "deterministic_runtime_job_id",
]
