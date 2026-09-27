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
TERMINAL_JOB_STATUSES = frozenset({"SUCCEEDED", "FAILED", "DEAD_LETTER", "CANCELLED"})
SAME_JOB_TAKEOVER = "SAME_JOB_TAKEOVER"
AUTHORITY_CONVERGENCE_REQUIRED = "AUTHORITY_CONVERGENCE_REQUIRED"
LEASE_LOSS_POLICIES = frozenset({SAME_JOB_TAKEOVER, AUTHORITY_CONVERGENCE_REQUIRED})
BOOK_OPENING_LEGACY_JOB_KIND = "BOOK_OPENING_EXECUTE"
BOOK_OPENING_LEGACY_RUNTIME_GROUP = "book_opening"
BOOK_OPENING_WORKFLOW_JOB_KIND = "BOOK_OPENING_WORKFLOW_NODE_EXECUTE"
BOOK_OPENING_WORKFLOW_RUNTIME_GROUP = "book_opening_workflow_v1"
BOOK_OPENING_RUNTIME_JOB_IDENTITIES = frozenset(
    {
        (BOOK_OPENING_LEGACY_JOB_KIND, BOOK_OPENING_LEGACY_RUNTIME_GROUP),
        (BOOK_OPENING_WORKFLOW_JOB_KIND, BOOK_OPENING_WORKFLOW_RUNTIME_GROUP),
    }
)
MODEL_COORDINATION_RUNTIME_GROUPS = ("story_formation", "book", "book_followup", BOOK_OPENING_LEGACY_RUNTIME_GROUP, BOOK_OPENING_WORKFLOW_RUNTIME_GROUP)
BOOK_OPENING_RUNTIME_JOB_KINDS = frozenset(
    job_kind for job_kind, _runtime_group in BOOK_OPENING_RUNTIME_JOB_IDENTITIES
)
OPERATIONAL_RUNTIME_JOB_CONTRACTS = {
    "STORY_FORMATION_ADVANCE": ("story_formation", "STORY_FORMATION_RUN"),
    BOOK_OPENING_LEGACY_JOB_KIND: (
        BOOK_OPENING_LEGACY_RUNTIME_GROUP,
        "BOOK_OPENING_RUN",
    ),
    BOOK_OPENING_WORKFLOW_JOB_KIND: (
        BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
        "BOOK_OPENING_RUN",
    ),
    "BOOK_COORDINATION_TICK": ("book", "BOOK_RUN"),
    "BOOK_FOLLOWUP_ADMISSION": ("book_followup", "CHAPTER_ACCEPTANCE"),
    "BOOK_PROJECTION_REPAIR": ("book_repair", "BOOK_RUN"),
    "OPERATION_DEADLINE_SCAN": ("maintenance", "AUTHORITY_MAINTENANCE_SCAN"),
    "ATTEMPT_LEASE_EXPIRY_SCAN": ("maintenance", "AUTHORITY_MAINTENANCE_SCAN"),
    "OUTBOX_RECOVERY_SCAN": ("maintenance", "AUTHORITY_MAINTENANCE_SCAN"),
    "EXTERNAL_EFFECT_RECONCILIATION_SCAN": (
        "maintenance",
        "AUTHORITY_MAINTENANCE_SCAN",
    ),
    "BOOK_OPENING_EXECUTION_LOSS_SCAN": (
        "maintenance",
        "AUTHORITY_MAINTENANCE_SCAN",
    ),
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def canonical_payload_hash(value: Any) -> str:
    return (
        "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    )


def deterministic_runtime_job_id(
    *, project_id: str, runtime_group: str, job_kind: str, dedupe_key: str
) -> str:
    identity = "\x1f".join((project_id, runtime_group, job_kind, dedupe_key))
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
    lease_loss_policy: str = SAME_JOB_TAKEOVER

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
        expected = OPERATIONAL_RUNTIME_JOB_CONTRACTS.get(self.job_kind)
        if expected is None:
            raise ValueError(
                "RuntimeJob accepts operational scheduling envelopes only; "
                "business work requires a Command Kernel Operation"
            )
        if (self.runtime_group, self.subject_kind) != expected:
            raise ValueError(
                "runtime job group and subject do not match its operational contract"
            )
        if self.runtime_group != "maintenance" and not self.project_id.strip():
            raise ValueError("project-scoped runtime jobs require a project identity")
        if self.max_attempts <= 0:
            raise ValueError("runtime job max_attempts must be positive")
        if self.priority < 0:
            raise ValueError("runtime job priority cannot be negative")
        if self.available_at is not None and self.available_at.tzinfo is None:
            raise ValueError("runtime job available_at must be timezone-aware")
        if self.lease_loss_policy not in LEASE_LOSS_POLICIES:
            raise ValueError("runtime job lease-loss policy is invalid")
        opening_runtime_identity = (self.job_kind, self.runtime_group)
        if (
            opening_runtime_identity in BOOK_OPENING_RUNTIME_JOB_IDENTITIES
            and self.lease_loss_policy != AUTHORITY_CONVERGENCE_REQUIRED
        ):
            raise ValueError(
                "Book Opening RuntimeJobs require Authority loss convergence"
            )
        if (
            opening_runtime_identity in BOOK_OPENING_RUNTIME_JOB_IDENTITIES
            and self.max_attempts != 1
        ):
            raise ValueError(
                "Book Opening requires exactly one RuntimeJob attempt per "
                "execution generation"
            )

    @property
    def runtime_job_id(self) -> str:
        return deterministic_runtime_job_id(
            project_id=self.project_id,
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

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Runtime Job Authority requires a database URL")
        self.database_url = database_url

    def schedule(self, spec: RuntimeJobSpec) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            scheduled = self.schedule_in_uow(uow, spec)
            uow.commit()
        return scheduled

    def schedule_in_uow(
        self, uow: AuthorityUnitOfWork, spec: RuntimeJobSpec
    ) -> dict[str, Any]:

        uow.cursor.execute(
            """
                INSERT INTO authority_runtime_job(
                    runtime_job_id, job_kind, runtime_group, subject_kind,
                    subject_id, project_id, dedupe_key, input_snapshot,
                    input_hash, status, priority, available_at, max_attempts,
                    lease_loss_policy
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,'READY',%s,
                    COALESCE(%s, NOW()),%s,%s
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
                spec.lease_loss_policy,
            ],
        )
        created = uow.cursor.rowcount == 1
        uow.cursor.execute(
            """
                SELECT runtime_job_id, input_hash, status, current_attempt_id,
                       dedupe_key, lease_loss_policy
                FROM authority_runtime_job
                WHERE project_id=%s AND runtime_group=%s AND job_kind=%s
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
                spec.project_id,
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
        if exact_dedupe and str(row[5]) != spec.lease_loss_policy:
            raise KernelError(
                "RUNTIME_JOB_IDEMPOTENCY_CONFLICT",
                "runtime job dedupe identity was reused with different lease-loss policy",
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
                    "lease_loss_policy": spec.lease_loss_policy,
                },
            )
        return {
            "runtime_job_id": runtime_job_id,
            "status": str(row[2]),
            "current_attempt_id": str(row[3] or ""),
            "created": created,
            "deduplicated": not created,
            "coalesced_active_subject": not exact_dedupe,
            "input_hash": spec.input_hash,
            "lease_loss_policy": str(row[5]),
        }

    def cancel_pending_for_subject(
        self,
        *,
        job_kind: str,
        runtime_group: str,
        subject_kind: str,
        subject_id: str,
        project_id: str,
        reason: str,
    ) -> tuple[str, ...]:

        if any(
            not value.strip()
            for value in (
                job_kind,
                runtime_group,
                subject_kind,
                subject_id,
                project_id,
                reason,
            )
        ):
            raise ValueError("runtime job cancellation scope is incomplete")
        if job_kind in BOOK_OPENING_RUNTIME_JOB_KINDS:
            raise KernelError(
                "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED",
                "Book Opening RuntimeJobs may be cancelled only by Book Authority",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT runtime_job_id
                FROM authority_runtime_job
                WHERE job_kind=%s AND runtime_group=%s AND subject_kind=%s
                  AND subject_id=%s AND project_id=%s
                  AND status IN ('READY','RETRY_WAIT')
                ORDER BY runtime_job_id
                FOR UPDATE
                """,
                [job_kind, runtime_group, subject_kind, subject_id, project_id],
            )
            job_ids = tuple(str(row[0]) for row in uow.cursor.fetchall())
            if job_ids:
                uow.cursor.execute(
                    """
                    UPDATE authority_runtime_job
                    SET status='CANCELLED', last_error=%s, updated_at=NOW()
                    WHERE runtime_job_id=ANY(%s)
                      AND status IN ('READY','RETRY_WAIT')
                    """,
                    [
                        Jsonb({"code": "SUPERSEDED_BY_RESUME", "reason": reason}),
                        list(job_ids),
                    ],
                )
                if uow.cursor.rowcount != len(job_ids):
                    raise KernelError(
                        "RUNTIME_JOB_CANCEL_CONFLICT",
                        "runtime job became active while resume superseded it",
                    )
                for runtime_job_id in job_ids:
                    self._append_event(
                        uow,
                        runtime_job_id=runtime_job_id,
                        attempt_id="",
                        event_type="runtime_job.cancelled",
                        worker_id="",
                        fencing_token=0,
                        payload={"reason": reason},
                    )
            uow.commit()
        return job_ids

    def claim(
        self,
        *,
        runtime_group: str,
        worker_id: str,
        lease_seconds: int,
        job_kinds: Iterable[str] = (),
        project_id: str = "",
        project_ids: Iterable[str] = (),
        subject_kind: str = "",
        subject_id: str = "",
    ) -> RuntimeJobClaim | None:
        if not runtime_group or not worker_id or lease_seconds <= 0:
            raise ValueError("runtime group, worker and positive lease are required")
        if bool(subject_kind) != bool(subject_id):
            raise ValueError("runtime job subject filter requires kind and id")
        kinds = tuple(dict.fromkeys(str(item) for item in job_kinds if str(item)))
        projects = tuple(dict.fromkeys(str(item) for item in project_ids if str(item)))
        if project_id and projects:
            raise ValueError("runtime job claim accepts one project filter form")
        from novel_forge.modules.command_kernel.dispatch_control import process_dispatch_suspended
        if runtime_group in MODEL_COORDINATION_RUNTIME_GROUPS and process_dispatch_suspended():
            return None
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT job.runtime_job_id, job.job_kind, job.subject_kind,
                       job.subject_id, job.project_id, job.attempt_count,
                       job.current_attempt_id, job.current_fencing_token,
                       job.status, job.input_snapshot, job.max_attempts
                FROM authority_runtime_job AS job
                WHERE job.runtime_group=%s
                  AND job.lease_loss_policy='SAME_JOB_TAKEOVER'
                  AND (NOT (job.runtime_group=ANY(%s)) OR NOT EXISTS (
                      SELECT 1 FROM authority_runtime_dispatch_control control WHERE control.project_id=job.project_id AND control.state='PAUSED'))
                  AND (%s::text[]='{}'::text[] OR job.job_kind=ANY(%s))
                  AND (%s='' OR job.project_id=%s)
                  AND (%s::text[]='{}'::text[] OR job.project_id=ANY(%s))
                  AND (%s='' OR (job.subject_kind=%s AND job.subject_id=%s))
                  AND (
                      (
                          job.status IN ('READY','RETRY_WAIT')
                          AND job.attempt_count - (SELECT count(*) FROM authority_runtime_job_attempt paused
                              WHERE paused.runtime_job_id=job.runtime_job_id AND paused.status='FAILED'
                              AND paused.error @> '{"dispatch_pause_contract":"runtime-dispatch-control.v1","code":"RUNTIME_DISPATCH_PAUSED","request_sent":false}'::jsonb) < job.max_attempts
                          AND job.available_at <= NOW()
                      )
                      OR (
                          job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                          AND job.lease_loss_policy='SAME_JOB_TAKEOVER'
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
                    list(MODEL_COORDINATION_RUNTIME_GROUPS),
                    list(kinds),
                    list(kinds),
                    project_id,
                    project_id,
                    list(projects),
                    list(projects),
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
                if int(row[5]) - self._paused_attempt_count(uow, runtime_job_id) >= int(row[10]):
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

    def claim_ready_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        runtime_job_id: str,
        worker_id: str,
        lease_seconds: int,
        expected_job_kind: str = BOOK_OPENING_LEGACY_JOB_KIND,
        expected_runtime_group: str = BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    ) -> RuntimeJobClaim:
        """INVARIANT: Claim one exact no-takeover Book Opening job under its owner UoW.

        The Book Opening coordinator must already hold its aggregate and
        execution locks. This primitive locks only RuntimeJob next, creates the
        first and only Attempt/Lease, and deliberately does not commit.
        """
        if not runtime_job_id or not worker_id or lease_seconds <= 0:
            raise ValueError(
                "runtime job identity, worker and positive lease are required"
            )
        uow.cursor.execute(
            """
            SELECT job_kind,runtime_group,subject_kind,subject_id,project_id,
                   attempt_count,current_attempt_id,current_fencing_token,
                   status,input_snapshot,max_attempts,lease_loss_policy
            FROM authority_runtime_job
            WHERE runtime_job_id=%s
            FOR UPDATE
            """,
            [runtime_job_id],
        )
        row = uow.cursor.fetchone()
        expected_identity = (expected_job_kind, expected_runtime_group)
        if expected_identity not in BOOK_OPENING_RUNTIME_JOB_IDENTITIES:
            raise ValueError("Book Opening RuntimeJob identity is not supported")
        valid = bool(
            row is not None
            and (str(row[0]), str(row[1])) == expected_identity
            and str(row[2]) == "BOOK_OPENING_RUN"
            and int(row[5]) == 0
            and not str(row[6] or "")
            and int(row[7]) == 0
            and str(row[8]) == "READY"
            and int(row[10]) == 1
            and str(row[11]) == AUTHORITY_CONVERGENCE_REQUIRED
        )
        if not valid:
            raise KernelError(
                "RUNTIME_JOB_AUTHORITY_CLAIM_CONFLICT",
                "Book Opening coordinator requires an unclaimed READY RuntimeJob",
            )

        from novel_forge.modules.command_kernel.dispatch_control import require_dispatch_enabled
        require_dispatch_enabled(uow.cursor, str(row[4]))
        attempt_id = f"runtime-attempt:{uuid4()}"
        lease_id = f"runtime-lease:{uuid4()}"
        fencing_token = 1
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job_attempt(
                attempt_id,runtime_job_id,attempt_number,worker_id,status,
                lease_id,fencing_token,lease_expires_at,heartbeat_at,started_at
            ) VALUES (
                %s,%s,1,%s,'CLAIMED',%s,%s,
                transaction_timestamp() + (%s * INTERVAL '1 second'),
                transaction_timestamp(),transaction_timestamp()
            )
            """,
            [
                attempt_id,
                runtime_job_id,
                worker_id,
                lease_id,
                fencing_token,
                lease_seconds,
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job_lease(
                lease_id,runtime_job_id,attempt_id,worker_id,fencing_token,
                lease_expires_at,heartbeat_at,status
            ) VALUES (
                %s,%s,%s,%s,%s,
                transaction_timestamp() + (%s * INTERVAL '1 second'),
                transaction_timestamp(),'HELD'
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
            SET status='CLAIMED',claimed_by=%s,current_attempt_id=%s,
                current_fencing_token=%s,attempt_count=1,
                updated_at=transaction_timestamp()
            WHERE runtime_job_id=%s AND status='READY' AND attempt_count=0
              AND current_attempt_id IS NULL AND current_fencing_token=0
              AND max_attempts=1
              AND lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
            """,
            [worker_id, attempt_id, fencing_token, runtime_job_id],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "RUNTIME_JOB_AUTHORITY_CLAIM_CONFLICT",
                "Book Opening RuntimeJob changed during coordinated claim",
            )
        self._append_event(
            uow,
            runtime_job_id=runtime_job_id,
            attempt_id=attempt_id,
            event_type="runtime_job.authority_claimed",
            worker_id=worker_id,
            fencing_token=fencing_token,
            payload={
                "lease_id": lease_id,
                "attempt_number": 1,
                "lease_seconds": lease_seconds,
                "lease_loss_policy": AUTHORITY_CONVERGENCE_REQUIRED,
            },
        )
        return RuntimeJobClaim(
            runtime_job_id=runtime_job_id,
            job_kind=str(row[0]),
            runtime_group=str(row[1]),
            subject_kind=str(row[2]),
            subject_id=str(row[3]),
            project_id=str(row[4] or ""),
            attempt_id=attempt_id,
            attempt_number=1,
            worker_id=worker_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            lease_expires_at=lease_expires_at,
            input_snapshot=dict(row[9] or {}),
        )

    def start(self, claim: RuntimeJobClaim) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            result = self.start_in_uow(uow, claim)
            uow.commit()
        return result

    def start_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
    ) -> dict[str, Any]:

        return self._start_in_uow(
            uow,
            claim,
            authority_coordinated=False,
        )

    def start_authority_owned_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
    ) -> dict[str, Any]:

        return self._start_in_uow(
            uow,
            claim,
            authority_coordinated=True,
        )

    def _start_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        *,
        authority_coordinated: bool,
    ) -> dict[str, Any]:
        locked = self._lock_and_assert_claim(uow, claim)
        job_kind = str(locked[14])
        lease_loss_policy = str(locked[15])
        if authority_coordinated:
            if (
                (claim.job_kind, claim.runtime_group)
                not in BOOK_OPENING_RUNTIME_JOB_IDENTITIES
                or job_kind != claim.job_kind
                or lease_loss_policy != AUTHORITY_CONVERGENCE_REQUIRED
            ):
                raise KernelError(
                    "RUNTIME_JOB_AUTHORITY_COORDINATOR_INVALID",
                    "coordinated start requires a no-takeover Book Opening job",
                )
        else:
            self._require_generic_terminal_allowed(
                job_kind=job_kind,
                lease_loss_policy=lease_loss_policy,
            )
        if str(locked[0]) in {"RUNNING", "CHECKPOINTED"}:
            return {
                "runtime_job_id": claim.runtime_job_id,
                "attempt_id": claim.attempt_id,
                "status": str(locked[0]),
                "replayed": True,
            }
        if str(locked[0]) != "CLAIMED" or str(locked[6]) != "CLAIMED":
            raise KernelError(
                "RUNTIME_JOB_STATE_CONFLICT",
                "runtime job and Attempt must both be CLAIMED before start",
            )
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_attempt
            SET status='RUNNING', started_at=COALESCE(started_at,NOW())
            WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
              AND lease_id=%s AND fencing_token=%s AND status='CLAIMED'
            """,
            [
                claim.attempt_id,
                claim.runtime_job_id,
                claim.worker_id,
                claim.lease_id,
                claim.fencing_token,
            ],
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
              AND current_fencing_token=%s AND status='CLAIMED'
            """,
            [claim.runtime_job_id, claim.attempt_id, claim.fencing_token],
        )
        if uow.cursor.rowcount != 1:
            self._raise_stale_claim()
        self._append_event(
            uow,
            runtime_job_id=claim.runtime_job_id,
            attempt_id=claim.attempt_id,
            event_type=(
                "runtime_job.authority_started"
                if authority_coordinated
                else "runtime_job.started"
            ),
            worker_id=claim.worker_id,
            fencing_token=claim.fencing_token,
            payload={
                "authority_coordinated": authority_coordinated,
            },
        )
        return {
            "runtime_job_id": claim.runtime_job_id,
            "attempt_id": claim.attempt_id,
            "status": "RUNNING",
            "replayed": False,
        }

    def heartbeat(
        self, claim: RuntimeJobClaim, *, lease_seconds: int
    ) -> dict[str, Any]:
        if lease_seconds <= 0:
            raise ValueError("runtime job heartbeat lease must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            locked = self._lock_and_assert_claim(uow, claim)
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
                WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
                  AND lease_id=%s AND fencing_token=%s AND status=%s
                """,
                [
                    row[0],
                    claim.attempt_id,
                    claim.runtime_job_id,
                    claim.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                    str(locked[6]),
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            uow.commit()
        return {"lease_expires_at": row[0], "fencing_token": claim.fencing_token}

    def checkpoint(
        self, claim: RuntimeJobClaim, checkpoint: dict[str, Any]
    ) -> dict[str, Any]:
        checkpoint_hash = canonical_payload_hash(checkpoint)
        with AuthorityUnitOfWork(self.database_url) as uow:
            locked = self._lock_and_assert_claim(uow, claim)
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
                WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
                  AND lease_id=%s AND fencing_token=%s AND status=%s
                """,
                [
                    Jsonb(checkpoint),
                    checkpoint_hash,
                    sequence,
                    claim.attempt_id,
                    claim.runtime_job_id,
                    claim.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                    str(locked[6]),
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status='CHECKPOINTED', updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                  AND current_fencing_token=%s AND status=%s
                """,
                [
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                    str(locked[0]),
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
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
        with AuthorityUnitOfWork(self.database_url) as uow:
            completed = self.complete_in_uow(uow, claim, result)
            uow.commit()
        return completed

    def complete_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        result: dict[str, Any],
    ) -> dict[str, Any]:

        return self._complete_in_uow(
            uow,
            claim,
            result,
            authority_coordinated=False,
        )

    def complete_authority_owned_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        result: dict[str, Any],
    ) -> dict[str, Any]:

        return self._complete_in_uow(
            uow,
            claim,
            result,
            authority_coordinated=True,
        )

    def _complete_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        result: dict[str, Any],
        *,
        authority_coordinated: bool,
    ) -> dict[str, Any]:
        """INVARIANT: Terminalize one exact claim inside its coordinator transaction.

        A committed response may be lost.  Repeating the same exact claim and
        result therefore returns the immutable result row; a different result
        or execution identity fails closed instead of rewriting history.
        """
        result_hash = canonical_payload_hash(result)
        uow.cursor.execute(
            """
            SELECT job.status,job.current_attempt_id,job.current_fencing_token,
                   job.result_hash,attempt.status,attempt.worker_id,
                   attempt.lease_id,attempt.fencing_token,attempt.result_hash,
                   lease.status,lease.worker_id,lease.fencing_token,
                   job.job_kind,job.lease_loss_policy
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
             AND lease.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s
            FOR UPDATE OF job,attempt,lease
            """,
            [claim.runtime_job_id],
        )
        terminal = uow.cursor.fetchone()
        exact_identity = bool(
            terminal is not None
            and str(terminal[1]) == claim.attempt_id
            and int(terminal[2]) == claim.fencing_token
            and str(terminal[5]) == claim.worker_id
            and str(terminal[6]) == claim.lease_id
            and int(terminal[7]) == claim.fencing_token
            and str(terminal[10]) == claim.worker_id
            and int(terminal[11]) == claim.fencing_token
        )
        if not exact_identity:
            self._raise_stale_claim()
        if not authority_coordinated:
            self._require_generic_terminal_allowed(
                job_kind=str(terminal[12]),
                lease_loss_policy=str(terminal[13]),
            )
        if str(terminal[0]) == "SUCCEEDED":
            if (
                str(terminal[3]) != result_hash
                or str(terminal[4]) != "SUCCEEDED"
                or str(terminal[8]) != result_hash
                or str(terminal[9]) != "RELEASED"
            ):
                raise KernelError(
                    "RUNTIME_JOB_COMPLETION_IDEMPOTENCY_CONFLICT",
                    "runtime job completion replay carries a different result",
                )
            uow.cursor.execute(
                """
                SELECT result_id,result_hash
                FROM authority_runtime_job_result
                WHERE runtime_job_id=%s AND attempt_id=%s
                  AND fencing_token=%s AND status='SUCCEEDED'
                ORDER BY created_at,result_id
                """,
                [
                    claim.runtime_job_id,
                    claim.attempt_id,
                    claim.fencing_token,
                ],
            )
            rows = uow.cursor.fetchall()
            if len(rows) != 1 or str(rows[0][1]) != result_hash:
                raise KernelError(
                    "RUNTIME_JOB_TERMINAL_HISTORY_INVALID",
                    "runtime job completion has ambiguous immutable result evidence",
                )
            return {
                "runtime_job_id": claim.runtime_job_id,
                "attempt_id": claim.attempt_id,
                "status": "SUCCEEDED",
                "result_id": str(rows[0][0]),
                "result_hash": result_hash,
                "replayed": True,
            }
        if str(terminal[0]) not in ACTIVE_JOB_STATUSES:
            self._raise_stale_claim()

        # INVARIANT: temporal validity is rechecked under the exact relational locks.
        self._lock_and_assert_claim(uow, claim)
        result_id = (
            "runtime-result:success:"
            + hashlib.sha256(
                "\x1f".join(
                    (
                        claim.runtime_job_id,
                        claim.attempt_id,
                        str(claim.fencing_token),
                        result_hash,
                    )
                ).encode("utf-8")
            ).hexdigest()
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job_result(
                result_id,runtime_job_id,attempt_id,fencing_token,
                status,result,result_hash
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
            SET status='SUCCEEDED',result_hash=%s,
                completed_at=transaction_timestamp()
            WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
              AND lease_id=%s AND fencing_token=%s
              AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
            """,
            [
                result_hash,
                claim.attempt_id,
                claim.runtime_job_id,
                claim.worker_id,
                claim.lease_id,
                claim.fencing_token,
            ],
        )
        if uow.cursor.rowcount != 1:
            self._raise_stale_claim()
        self._release_lease(uow, claim, reason="completed")
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job
            SET status='SUCCEEDED',claimed_by='',result_hash=%s,
                completed_at=transaction_timestamp(),
                updated_at=transaction_timestamp()
            WHERE runtime_job_id=%s AND current_attempt_id=%s
              AND current_fencing_token=%s
              AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
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
        return {
            "runtime_job_id": claim.runtime_job_id,
            "attempt_id": claim.attempt_id,
            "status": "SUCCEEDED",
            "result_id": result_id,
            "result_hash": result_hash,
            "replayed": False,
        }

    def complete_and_schedule_continuation(
        self,
        claim: RuntimeJobClaim,
        result: dict[str, Any],
        continuation: RuntimeJobSpec,
    ) -> dict[str, Any]:

        if (
            continuation.project_id != claim.project_id
            or continuation.runtime_group != claim.runtime_group
            or continuation.job_kind != claim.job_kind
            or continuation.subject_kind != claim.subject_kind
            or continuation.subject_id != claim.subject_id
            or continuation.runtime_job_id == claim.runtime_job_id
        ):
            raise ValueError(
                "RuntimeJob continuation must preserve its governed subject"
            )
        result_hash = canonical_payload_hash(result)
        with AuthorityUnitOfWork(self.database_url) as uow:
            job = self._lock_and_assert_claim(uow, claim)
            self._require_generic_terminal_allowed(
                job_kind=str(job[14]),
                lease_loss_policy=str(job[15]),
            )
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
                WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
                  AND lease_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [
                    result_hash,
                    claim.attempt_id,
                    claim.runtime_job_id,
                    claim.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            self._release_lease(uow, claim, reason="bounded_continuation")
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status='SUCCEEDED', claimed_by='', result_hash=%s,
                    completed_at=NOW(), updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                  AND current_fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
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
                event_type="runtime_job.succeeded_with_continuation",
                worker_id=claim.worker_id,
                fencing_token=claim.fencing_token,
                payload={
                    "result_id": result_id,
                    "result_hash": result_hash,
                    "continuation_runtime_job_id": continuation.runtime_job_id,
                },
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job(
                    runtime_job_id, job_kind, runtime_group, subject_kind,
                    subject_id, project_id, dedupe_key, input_snapshot,
                    input_hash, status, priority, available_at, max_attempts,
                    lease_loss_policy
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,'READY',%s,
                    COALESCE(%s, NOW()),%s,%s
                )
                ON CONFLICT DO NOTHING
                """,
                [
                    continuation.runtime_job_id,
                    continuation.job_kind,
                    continuation.runtime_group,
                    continuation.subject_kind,
                    continuation.subject_id,
                    continuation.project_id,
                    continuation.dedupe_key,
                    Jsonb(continuation.input_snapshot),
                    continuation.input_hash,
                    continuation.priority,
                    continuation.available_at,
                    continuation.max_attempts,
                    continuation.lease_loss_policy,
                ],
            )
            created = uow.cursor.rowcount == 1
            uow.cursor.execute(
                """
                SELECT input_hash, status
                FROM authority_runtime_job
                WHERE runtime_job_id=%s AND project_id=%s
                FOR UPDATE
                """,
                [continuation.runtime_job_id, continuation.project_id],
            )
            next_row = uow.cursor.fetchone()
            if next_row is None or str(next_row[0]) != continuation.input_hash:
                raise KernelError(
                    "RUNTIME_JOB_IDEMPOTENCY_CONFLICT",
                    "continuation identity belongs to different input",
                )
            if created:
                self._append_event(
                    uow,
                    runtime_job_id=continuation.runtime_job_id,
                    attempt_id="",
                    event_type="runtime_job.scheduled",
                    worker_id="",
                    fencing_token=0,
                    payload={
                        "job_kind": continuation.job_kind,
                        "runtime_group": continuation.runtime_group,
                        "subject_kind": continuation.subject_kind,
                        "subject_id": continuation.subject_id,
                        "input_hash": continuation.input_hash,
                        "continued_from": claim.runtime_job_id,
                    },
                )
            uow.commit()
        return {
            "runtime_job_id": claim.runtime_job_id,
            "status": "SUCCEEDED",
            "result_id": result_id,
            "result_hash": result_hash,
            "continuation_runtime_job_id": continuation.runtime_job_id,
            "continuation_status": str(next_row[1]),
            "continuation_created": created,
        }

    @staticmethod
    def _paused_attempt_count(uow: AuthorityUnitOfWork, runtime_job_id: str) -> int:
        uow.cursor.execute("""SELECT count(*) FROM authority_runtime_job_attempt WHERE runtime_job_id=%s AND status='FAILED'
            AND error @> '{"dispatch_pause_contract":"runtime-dispatch-control.v1","code":"RUNTIME_DISPATCH_PAUSED","request_sent":false}'::jsonb""", [runtime_job_id])
        return int(uow.cursor.fetchone()[0])

    def fail(
        self,
        claim: RuntimeJobClaim,
        error: dict[str, Any],
        *,
        retry_delay_seconds: int = 0,
        cause: BaseException | None = None,
    ) -> dict[str, Any]:
        if retry_delay_seconds < 0:
            raise ValueError("runtime job retry delay cannot be negative")
        with AuthorityUnitOfWork(self.database_url) as uow:
            job = self._lock_and_assert_claim(uow, claim)
            from novel_forge.modules.command_kernel.dispatch_control import confirmed_dispatch_pause
            pause = confirmed_dispatch_pause(uow.cursor, cause, claim.project_id)
            error = {key: value for key, value in error.items() if key not in {"dispatch_pause_contract", "control_evidence", "disposition"}}
            if pause is not None:
                error = {**error, "code": "RUNTIME_DISPATCH_PAUSED", "dispatch_pause_contract": "runtime-dispatch-control.v1",
                    "control_evidence": pause, "disposition": "PAUSED_AWAITING_CONTROL", "request_sent": False}
            error_hash = canonical_payload_hash(error)
            self._require_generic_terminal_allowed(
                job_kind=str(job[14]),
                lease_loss_policy=str(job[15]),
            )
            terminal = pause is None and int(job[2]) - self._paused_attempt_count(uow, claim.runtime_job_id) >= int(job[3])
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
                WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
                  AND lease_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [
                    Jsonb(error),
                    error_hash,
                    claim.attempt_id,
                    claim.runtime_job_id,
                    claim.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            self._release_lease(uow, claim, reason="attempt_failed")
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job
                SET status=%s, claimed_by='', last_error=%s,
                    paused_attempt_count=paused_attempt_count+%s,
                    available_at=NOW() + (%s * INTERVAL '1 second'),
                    completed_at=CASE WHEN %s='DEAD_LETTER' THEN NOW() ELSE NULL END,
                    updated_at=NOW()
                WHERE runtime_job_id=%s AND current_attempt_id=%s
                  AND current_fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [
                    job_status,
                    Jsonb(error),
                    int(pause is not None),
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

    def terminalize_execution_loss_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        runtime_job_id: str,
        expected_attempt_id: str,
        expected_lease_id: str,
        expected_fencing_token: int,
        reason: dict[str, Any],
    ) -> dict[str, Any]:
        """INVARIANT: Fence an expired no-takeover execution without authorizing a successor.

        The Book Authority coordinator owns the surrounding transaction.  This
        primitive owns only RuntimeJob/Attempt/Lease terminalization and never
        creates recovery authorization or executes business work.
        """
        if (
            not runtime_job_id
            or not expected_attempt_id
            or not expected_lease_id
            or expected_fencing_token <= 0
        ):
            raise ValueError("execution-loss identity is incomplete")
        reason_hash = canonical_payload_hash(reason)
        uow.cursor.execute(
            """
            SELECT job.status, job.lease_loss_policy, job.current_attempt_id,
                   job.current_fencing_token, attempt.status, attempt.lease_id,
                   attempt.worker_id, lease.status, lease.lease_expires_at,
                   lease.worker_id,job.result_hash,job.last_error,
                   attempt.fencing_token,attempt.error,attempt.result_hash,
                   lease.fencing_token,lease.release_reason
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
             AND lease.lease_id=attempt.lease_id
            WHERE job.runtime_job_id=%s
            FOR UPDATE OF job, attempt, lease
            """,
            [runtime_job_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "RUNTIME_JOB_LOSS_BINDING_MISSING",
                "execution-loss RuntimeJob binding is missing",
            )
        exact = (
            str(row[1]) == AUTHORITY_CONVERGENCE_REQUIRED
            and str(row[2] or "") == expected_attempt_id
            and int(row[3]) == expected_fencing_token
            and str(row[5]) == expected_lease_id
            and str(row[9]) == str(row[6])
            and int(row[12]) == expected_fencing_token
            and int(row[15]) == expected_fencing_token
        )
        if not exact:
            raise KernelError(
                "RUNTIME_JOB_LOSS_BINDING_DRIFT",
                "execution-loss RuntimeJob binding changed and requires reassessment",
            )
        if str(row[0]) == "FAILED":
            if str(row[4]) != "ABANDONED" or str(row[7]) != "EXPIRED":
                raise KernelError(
                    "RUNTIME_JOB_TERMINAL_HISTORY_INVALID",
                    "terminal loss history is internally inconsistent",
                )
            if (
                str(row[10]) != reason_hash
                or str(row[14]) != reason_hash
                or canonical_payload_hash(dict(row[11] or {})) != reason_hash
                or canonical_payload_hash(dict(row[13] or {})) != reason_hash
                or str(row[16]) != "authority_execution_loss"
            ):
                raise KernelError(
                    "RUNTIME_JOB_LOSS_IDEMPOTENCY_CONFLICT",
                    "execution-loss replay carries a different terminal reason",
                )
            result_id = self._terminal_result_replay_in_uow(
                uow,
                runtime_job_id=runtime_job_id,
                attempt_id=expected_attempt_id,
                fencing_token=expected_fencing_token,
                expected_hash=reason_hash,
                conflict_code="RUNTIME_JOB_LOSS_IDEMPOTENCY_CONFLICT",
            )
            return {
                "runtime_job_id": runtime_job_id,
                "attempt_id": expected_attempt_id,
                "lease_id": expected_lease_id,
                "fencing_token": expected_fencing_token,
                "status": "FAILED",
                "reason_hash": reason_hash,
                "result_id": result_id,
                "replayed": True,
            }
        if str(row[0]) not in ACTIVE_JOB_STATUSES:
            raise KernelError(
                "RUNTIME_JOB_LOSS_STATE_DRIFT",
                "execution-loss requires the assessed active RuntimeJob",
            )
        if str(row[7]) == "HELD":
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_lease
                SET status='EXPIRED', released_at=transaction_timestamp(),
                    release_reason='authority_execution_loss'
                WHERE lease_id=%s AND attempt_id=%s AND worker_id=%s
                  AND fencing_token=%s AND status='HELD'
                  AND lease_expires_at <= transaction_timestamp()
                """,
                [
                    expected_lease_id,
                    expected_attempt_id,
                    str(row[9]),
                    expected_fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "RUNTIME_JOB_LOSS_LEASE_NOT_EXPIRED",
                    "execution-loss lease is still temporally valid or changed",
                )
        elif str(row[7]) != "EXPIRED":
            raise KernelError(
                "RUNTIME_JOB_LOSS_LEASE_DRIFT",
                "execution-loss lease is not held-expired evidence",
            )
        if str(row[4]) != "ABANDONED":
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='ABANDONED', completed_at=transaction_timestamp(),
                    error=%s,result_hash=%s
                WHERE attempt_id=%s AND runtime_job_id=%s
                  AND lease_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [
                    Jsonb(reason),
                    reason_hash,
                    expected_attempt_id,
                    runtime_job_id,
                    expected_lease_id,
                    expected_fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "RUNTIME_JOB_LOSS_ATTEMPT_DRIFT",
                    "execution-loss Attempt changed and requires reassessment",
                )
        result_id = (
            "runtime-result:loss:"
            + hashlib.sha256(
                "\x1f".join((runtime_job_id, expected_attempt_id, reason_hash)).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job_result(
                result_id, runtime_job_id, attempt_id, fencing_token,
                status, result, result_hash
            ) VALUES (%s,%s,%s,%s,'FAILED',%s,%s)
            """,
            [
                result_id,
                runtime_job_id,
                expected_attempt_id,
                expected_fencing_token,
                Jsonb(reason),
                reason_hash,
            ],
        )
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job
            SET status='FAILED', claimed_by='', last_error=%s,
                result_hash=%s, completed_at=transaction_timestamp(),
                updated_at=transaction_timestamp()
            WHERE runtime_job_id=%s AND current_attempt_id=%s
              AND current_fencing_token=%s
              AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
            """,
            [
                Jsonb(reason),
                reason_hash,
                runtime_job_id,
                expected_attempt_id,
                expected_fencing_token,
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "RUNTIME_JOB_LOSS_STATE_DRIFT",
                "execution-loss RuntimeJob changed and requires reassessment",
            )
        self._append_event(
            uow,
            runtime_job_id=runtime_job_id,
            attempt_id=expected_attempt_id,
            event_type="runtime_job.execution_lost",
            worker_id=str(row[6]),
            fencing_token=expected_fencing_token,
            payload={"reason_hash": reason_hash, **reason},
        )
        return {
            "runtime_job_id": runtime_job_id,
            "attempt_id": expected_attempt_id,
            "lease_id": expected_lease_id,
            "fencing_token": expected_fencing_token,
            "status": "FAILED",
            "reason_hash": reason_hash,
            "result_id": result_id,
            "replayed": False,
        }

    def terminalize_authority_abort_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        runtime_job_id: str,
        reason: dict[str, Any],
    ) -> dict[str, Any]:
        """INVARIANT: Cancel one Book Opening envelope under its business Authority lock.

        The coordinator locks Opening and OpeningExecution first.  This method
        then locks RuntimeJob -> Attempt -> Lease, revokes any winning claim,
        and returns the exact terminal binding for the Opening execution row.
        """
        reason_hash = canonical_payload_hash(reason)
        uow.cursor.execute(
            """
            SELECT status,current_attempt_id,current_fencing_token,
                   lease_loss_policy,job_kind,runtime_group,subject_kind,
                   input_snapshot,result_hash,last_error
            FROM authority_runtime_job
            WHERE runtime_job_id=%s
            FOR UPDATE
            """,
            [runtime_job_id],
        )
        job = uow.cursor.fetchone()
        if job is None:
            raise KernelError(
                "RUNTIME_JOB_ABORT_BINDING_MISSING",
                "Book Opening abort RuntimeJob is missing",
            )
        if (
            str(job[3]) != AUTHORITY_CONVERGENCE_REQUIRED
            or (str(job[4]), str(job[5])) not in BOOK_OPENING_RUNTIME_JOB_IDENTITIES
            or str(job[6]) != "BOOK_OPENING_RUN"
        ):
            raise KernelError(
                "RUNTIME_JOB_ABORT_BINDING_INVALID",
                "Authority abort accepts only a no-takeover Book Opening job",
            )
        status = str(job[0])
        input_snapshot = dict(job[7] or {})
        if status == "CANCELLED":
            if (
                str(job[8]) != reason_hash
                or canonical_payload_hash(dict(job[9] or {})) != reason_hash
            ):
                raise KernelError(
                    "RUNTIME_JOB_ABORT_IDEMPOTENCY_CONFLICT",
                    "Authority abort replay carries a different terminal reason",
                )
            attempt_id = str(job[1] or "")
            lease_id = ""
            worker_id = ""
            if attempt_id:
                uow.cursor.execute(
                    """
                    SELECT attempt.status,attempt.worker_id,attempt.lease_id,
                           attempt.fencing_token,attempt.error,
                           lease.status,lease.worker_id,lease.fencing_token,
                           lease.release_reason
                    FROM authority_runtime_job_attempt AS attempt
                    JOIN authority_runtime_job_lease AS lease
                      ON lease.lease_id=attempt.lease_id
                     AND lease.attempt_id=attempt.attempt_id
                    WHERE attempt.runtime_job_id=%s AND attempt.attempt_id=%s
                    FOR UPDATE OF attempt,lease
                    """,
                    [runtime_job_id, attempt_id],
                )
                terminal = uow.cursor.fetchone()
                if (
                    terminal is None
                    or str(terminal[0]) != "ABANDONED"
                    or int(terminal[3]) != int(job[2])
                    or str(terminal[5]) != "RELEASED"
                    or str(terminal[6]) != str(terminal[1])
                    or int(terminal[7]) != int(job[2])
                    or str(terminal[8]) != "book_opening_authority_aborted"
                ):
                    raise KernelError(
                        "RUNTIME_JOB_TERMINAL_HISTORY_INVALID",
                        "Authority abort history is internally inconsistent",
                    )
                if canonical_payload_hash(dict(terminal[4] or {})) != reason_hash:
                    raise KernelError(
                        "RUNTIME_JOB_ABORT_IDEMPOTENCY_CONFLICT",
                        "Authority abort Attempt carries a different reason",
                    )
                self._terminal_result_replay_in_uow(
                    uow,
                    runtime_job_id=runtime_job_id,
                    attempt_id=attempt_id,
                    fencing_token=int(job[2]),
                    expected_hash=reason_hash,
                    conflict_code="RUNTIME_JOB_ABORT_IDEMPOTENCY_CONFLICT",
                )
                worker_id = str(terminal[1])
                lease_id = str(terminal[2])
            return {
                "runtime_job_id": runtime_job_id,
                "status": "CANCELLED",
                "attempt_id": attempt_id,
                "lease_id": lease_id,
                "worker_id": worker_id,
                "fencing_token": int(job[2]),
                "replacement_evaluation_operation_id": str(
                    input_snapshot.get("replacement_evaluation_operation_id") or ""
                ),
                "semantic_evaluation_operation_id": str(
                    input_snapshot.get("semantic_evaluation_operation_id") or ""
                ),
                "semantic_evaluation_execution_id": str(
                    input_snapshot.get("semantic_evaluation_execution_id") or ""
                ),
                "semantic_evaluation_generation": int(
                    input_snapshot.get("semantic_evaluation_generation") or 0
                ),
                "semantic_execution_mode": str(
                    input_snapshot.get("semantic_execution_mode") or "NONE"
                ),
                "replayed": True,
            }
        if status not in SCHEDULABLE_JOB_STATUSES | ACTIVE_JOB_STATUSES:
            raise KernelError(
                "RUNTIME_JOB_ABORT_STATE_CONFLICT",
                "Book Opening RuntimeJob is already terminal with another outcome",
            )

        attempt_id = str(job[1] or "")
        lease_id = ""
        worker_id = ""
        fencing_token = int(job[2])
        if status in ACTIVE_JOB_STATUSES:
            uow.cursor.execute(
                """
                SELECT attempt.status,attempt.worker_id,attempt.lease_id,
                       attempt.fencing_token,lease.status,lease.worker_id,
                       lease.fencing_token,
                       lease.lease_expires_at > clock_timestamp()
                FROM authority_runtime_job_attempt AS attempt
                JOIN authority_runtime_job_lease AS lease
                  ON lease.lease_id=attempt.lease_id
                 AND lease.attempt_id=attempt.attempt_id
                WHERE attempt.runtime_job_id=%s AND attempt.attempt_id=%s
                  AND attempt.fencing_token=%s
                FOR UPDATE OF attempt,lease
                """,
                [runtime_job_id, attempt_id, fencing_token],
            )
            execution = uow.cursor.fetchone()
            if execution is None:
                raise KernelError(
                    "RUNTIME_JOB_ABORT_BINDING_INVALID",
                    "claimed Book Opening job lacks its exact Attempt/Lease",
                )
            worker_id = str(execution[1])
            lease_id = str(execution[2])
            if (
                str(execution[0]) not in {"CLAIMED", "RUNNING", "CHECKPOINTED"}
                or int(execution[3]) != fencing_token
                or str(execution[4]) != "HELD"
                or str(execution[5]) != worker_id
                or int(execution[6]) != fencing_token
                or not bool(execution[7])
            ):
                raise KernelError(
                    "RUNTIME_JOB_ABORT_BINDING_INVALID",
                    "claimed Book Opening Attempt/Lease/fence binding drifted",
                )
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_lease
                SET status='RELEASED',released_at=transaction_timestamp(),
                    release_reason='book_opening_authority_aborted'
                WHERE lease_id=%s AND status='HELD'
                  AND lease_expires_at > clock_timestamp()
                """,
                [lease_id],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_attempt
                SET status='ABANDONED',error=%s,
                    completed_at=transaction_timestamp()
                WHERE attempt_id=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [Jsonb(reason), attempt_id],
            )
            if uow.cursor.rowcount != 1:
                self._raise_stale_claim()
            result_id = (
                "runtime-result:abort:"
                + hashlib.sha256(
                    "\x1f".join((runtime_job_id, attempt_id, reason_hash)).encode(
                        "utf-8"
                    )
                ).hexdigest()
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_runtime_job_result(
                    result_id,runtime_job_id,attempt_id,fencing_token,
                    status,result,result_hash
                ) VALUES (%s,%s,%s,%s,'FAILED',%s,%s)
                """,
                [
                    result_id,
                    runtime_job_id,
                    attempt_id,
                    fencing_token,
                    Jsonb(reason),
                    reason_hash,
                ],
            )
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job
            SET status='CANCELLED',claimed_by='',last_error=%s,
                result_hash=%s,completed_at=transaction_timestamp(),
                updated_at=transaction_timestamp()
            WHERE runtime_job_id=%s
              AND status IN ('READY','RETRY_WAIT','CLAIMED','RUNNING','CHECKPOINTED')
            """,
            [Jsonb(reason), reason_hash, runtime_job_id],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "RUNTIME_JOB_ABORT_STATE_CONFLICT",
                "Book Opening RuntimeJob changed during Authority abort",
            )
        self._append_event(
            uow,
            runtime_job_id=runtime_job_id,
            attempt_id=attempt_id,
            event_type="runtime_job.authority_aborted",
            worker_id=worker_id,
            fencing_token=fencing_token,
            payload={"reason_hash": reason_hash},
        )
        return {
            "runtime_job_id": runtime_job_id,
            "status": "CANCELLED",
            "attempt_id": attempt_id,
            "lease_id": lease_id,
            "worker_id": worker_id,
            "fencing_token": fencing_token,
            "replacement_evaluation_operation_id": str(
                input_snapshot.get("replacement_evaluation_operation_id") or ""
            ),
            "semantic_evaluation_operation_id": str(
                input_snapshot.get("semantic_evaluation_operation_id") or ""
            ),
            "semantic_evaluation_execution_id": str(
                input_snapshot.get("semantic_evaluation_execution_id") or ""
            ),
            "semantic_evaluation_generation": int(
                input_snapshot.get("semantic_evaluation_generation") or 0
            ),
            "semantic_execution_mode": str(
                input_snapshot.get("semantic_execution_mode") or "NONE"
            ),
            "replayed": False,
        }

    def terminalize_authority_failure_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        claim: RuntimeJobClaim,
        error: dict[str, Any],
    ) -> dict[str, Any]:

        error_hash = canonical_payload_hash(error)
        uow.cursor.execute(
            """
            SELECT job.status,job.current_attempt_id,job.current_fencing_token,
                   job.result_hash,job.last_error,job.lease_loss_policy,
                   attempt.status,attempt.worker_id,attempt.lease_id,
                   attempt.fencing_token,attempt.result_hash,attempt.error,
                   lease.status,lease.worker_id,lease.fencing_token,
                   lease.release_reason
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
             AND lease.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s
            FOR UPDATE OF job,attempt,lease
            """,
            [claim.runtime_job_id],
        )
        terminal = uow.cursor.fetchone()
        exact_identity = bool(
            terminal is not None
            and str(terminal[1]) == claim.attempt_id
            and int(terminal[2]) == claim.fencing_token
            and str(terminal[5]) == AUTHORITY_CONVERGENCE_REQUIRED
            and str(terminal[7]) == claim.worker_id
            and str(terminal[8]) == claim.lease_id
            and int(terminal[9]) == claim.fencing_token
            and str(terminal[13]) == claim.worker_id
            and int(terminal[14]) == claim.fencing_token
        )
        if not exact_identity:
            self._raise_stale_claim()
        if str(terminal[0]) == "FAILED":
            if str(terminal[6]) != "FAILED" or str(terminal[12]) != "RELEASED":
                raise KernelError(
                    "RUNTIME_JOB_TERMINAL_HISTORY_INVALID",
                    "Authority failure history is internally inconsistent",
                )
            if (
                str(terminal[3]) != error_hash
                or str(terminal[10]) != error_hash
                or canonical_payload_hash(dict(terminal[4] or {})) != error_hash
                or canonical_payload_hash(dict(terminal[11] or {})) != error_hash
                or str(terminal[15]) != "authority_failed"
            ):
                raise KernelError(
                    "RUNTIME_JOB_FAILURE_IDEMPOTENCY_CONFLICT",
                    "Authority failure replay carries a different terminal error",
                )
            result_id = self._terminal_result_replay_in_uow(
                uow,
                runtime_job_id=claim.runtime_job_id,
                attempt_id=claim.attempt_id,
                fencing_token=claim.fencing_token,
                expected_hash=error_hash,
                conflict_code="RUNTIME_JOB_FAILURE_IDEMPOTENCY_CONFLICT",
            )
            return {
                "runtime_job_id": claim.runtime_job_id,
                "attempt_id": claim.attempt_id,
                "status": "FAILED",
                "result_id": result_id,
                "error_hash": error_hash,
                "replayed": True,
            }
        if str(terminal[0]) not in ACTIVE_JOB_STATUSES:
            self._raise_stale_claim()
        self._lock_and_assert_claim(uow, claim)
        result_id = (
            "runtime-result:authority-failure:"
            + hashlib.sha256(
                "\x1f".join(
                    (claim.runtime_job_id, claim.attempt_id, error_hash)
                ).encode("utf-8")
            ).hexdigest()
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_runtime_job_result(
                result_id,runtime_job_id,attempt_id,fencing_token,
                status,result,result_hash
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
            SET status='FAILED',error=%s,result_hash=%s,
                completed_at=transaction_timestamp()
            WHERE attempt_id=%s AND runtime_job_id=%s AND worker_id=%s
              AND lease_id=%s AND fencing_token=%s
              AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
            """,
            [
                Jsonb(error),
                error_hash,
                claim.attempt_id,
                claim.runtime_job_id,
                claim.worker_id,
                claim.lease_id,
                claim.fencing_token,
            ],
        )
        if uow.cursor.rowcount != 1:
            self._raise_stale_claim()
        self._release_lease(uow, claim, reason="authority_failed")
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job
            SET status='FAILED',claimed_by='',last_error=%s,result_hash=%s,
                completed_at=transaction_timestamp(),updated_at=transaction_timestamp()
            WHERE runtime_job_id=%s AND current_attempt_id=%s
              AND current_fencing_token=%s
              AND lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
              AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
            """,
            [
                Jsonb(error),
                error_hash,
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
            event_type="runtime_job.authority_failed",
            worker_id=claim.worker_id,
            fencing_token=claim.fencing_token,
            payload={"error_hash": error_hash},
        )
        return {
            "runtime_job_id": claim.runtime_job_id,
            "attempt_id": claim.attempt_id,
            "status": "FAILED",
            "result_id": result_id,
            "error_hash": error_hash,
            "replayed": False,
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
                       completed_at, lease_loss_policy, paused_attempt_count
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
            "lease_loss_policy",
            "paused_attempt_count",
        )
        return dict(zip(keys, row, strict=True))

    def assert_live(self, claim: RuntimeJobClaim) -> dict[str, Any]:

        with AuthorityUnitOfWork(self.database_url) as uow:
            locked = self._lock_and_assert_claim(uow, claim)
        return {
            "runtime_job_id": claim.runtime_job_id,
            "attempt_id": claim.attempt_id,
            "status": str(locked[0]),
            "fencing_token": claim.fencing_token,
            "lease_expires_at": locked[13],
        }

    def _lock_and_assert_claim(
        self, uow: AuthorityUnitOfWork, claim: RuntimeJobClaim
    ) -> tuple[Any, ...]:
        uow.cursor.execute(
            """
            SELECT job.status, job.current_attempt_id, job.attempt_count,
                   job.max_attempts, job.current_fencing_token,
                   attempt.worker_id, attempt.status, attempt.lease_id,
                   attempt.fencing_token,lease.lease_id,lease.worker_id,
                   lease.status,lease.fencing_token,lease.lease_expires_at,
                   job.job_kind,job.lease_loss_policy
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
             AND lease.lease_id=attempt.lease_id
            WHERE job.runtime_job_id=%s
              AND lease.lease_expires_at > clock_timestamp()
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
            and int(row[8]) == claim.fencing_token
            and str(row[9]) == claim.lease_id
            and str(row[10]) == claim.worker_id
            and str(row[11]) == "HELD"
            and int(row[12]) == claim.fencing_token
            and str(row[0]) in ACTIVE_JOB_STATUSES
            and str(row[6]) == str(row[0])
        )
        if not valid:
            self._raise_stale_claim()
        return row

    @staticmethod
    def _terminal_result_replay_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        runtime_job_id: str,
        attempt_id: str,
        fencing_token: int,
        expected_hash: str,
        conflict_code: str,
    ) -> str:
        uow.cursor.execute(
            """
            SELECT result_id,result,result_hash
            FROM authority_runtime_job_result
            WHERE runtime_job_id=%s AND attempt_id=%s
              AND fencing_token=%s AND status='FAILED'
            ORDER BY created_at,result_id
            """,
            [runtime_job_id, attempt_id, fencing_token],
        )
        rows = uow.cursor.fetchall()
        if len(rows) != 1:
            raise KernelError(
                "RUNTIME_JOB_TERMINAL_HISTORY_INVALID",
                "RuntimeJob terminal state lacks one exact immutable result",
            )
        if (
            str(rows[0][2]) != expected_hash
            or canonical_payload_hash(dict(rows[0][1] or {})) != expected_hash
        ):
            raise KernelError(
                conflict_code,
                "RuntimeJob terminal replay carries different result evidence",
            )
        return str(rows[0][0])

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
    def _require_generic_terminal_allowed(
        *, job_kind: str, lease_loss_policy: str
    ) -> None:
        if (
            job_kind in BOOK_OPENING_RUNTIME_JOB_KINDS
            or lease_loss_policy == AUTHORITY_CONVERGENCE_REQUIRED
        ):
            raise KernelError(
                "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED",
                "Authority-owned RuntimeJob terminalization requires its "
                "business coordinator",
            )

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
    "OPERATIONAL_RUNTIME_JOB_CONTRACTS",
]
