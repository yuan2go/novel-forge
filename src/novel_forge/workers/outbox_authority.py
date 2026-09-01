from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.worker_execution import WorkerSupervisor
from novel_forge.modules.runtime_job import canonical_payload_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


def _safe_error(error: dict[str, object]) -> str:
    return str(error.get("code") or "OUTBOX_DELIVERY_FAILED")[:200]


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    outbox_id: str
    event_id: str
    project_id: str
    topic: str
    lease_id: str
    fencing_token: int
    runtime_group: str


class PostgresOutboxDispatcher:

    def __init__(
        self,
        database_url: str,
        *,
        worker_id: str,
        consumer_name: str = "authority-internal-event-bus",
        lease_seconds: int = 30,
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError("outbox dispatcher configuration is invalid")
        self.database_url = database_url
        self.worker_id = worker_id
        self.consumer_name = consumer_name
        self.lease_seconds = lease_seconds

    def claim(
        self, *, limit: int, project_id: str = ""
    ) -> tuple[OutboxClaim, ...]:
        if limit <= 0:
            raise ValueError("outbox claim limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                WITH selected AS (
                    SELECT outbox_id
                    FROM outbox_event
                    WHERE LOWER(status) IN ('pending','queued','failed')
                      AND (%s='' OR project_id=%s)
                      AND available_at <= NOW()
                      AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
                    ORDER BY available_at, created_at, outbox_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE outbox_event AS event
                SET status='claimed', claimed_by=%s, claimed_at=NOW(),
                    lease_expires_at=NOW() + (%s * INTERVAL '1 second'),
                    attempt_count=event.attempt_count + 1,
                    fencing_token=event.fencing_token + 1,
                    lease_id=event.outbox_id || ':' || (event.fencing_token + 1)::text,
                    runtime_group='outbox', updated_at=NOW()
                FROM selected
                WHERE event.outbox_id=selected.outbox_id
                RETURNING event.outbox_id, event.event_id,
                          event.project_id, event.topic, event.lease_id,
                          event.fencing_token, event.runtime_group
                """,
                [project_id, project_id, limit, self.worker_id, self.lease_seconds],
            )
            claims = tuple(
                OutboxClaim(
                    outbox_id=str(row[0]),
                    event_id=str(row[1]),
                    project_id=str(row[2]),
                    topic=str(row[3]),
                    lease_id=str(row[4]),
                    fencing_token=int(row[5]),
                    runtime_group=str(row[6]),
                )
                for row in uow.cursor.fetchall()
            )
            for claim in claims:
                uow.cursor.execute(
                    """
                    INSERT INTO authority_outbox_delivery_execution(
                        outbox_delivery_execution_id, outbox_id, event_id,
                        worker_id, lease_id, fencing_token, status,
                        lease_expires_at
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,'CLAIMED',
                        NOW() + (%s * INTERVAL '1 second')
                    )
                    """,
                    [
                        f"outbox-execution:{claim.outbox_id}:{claim.fencing_token}",
                        claim.outbox_id,
                        claim.event_id,
                        self.worker_id,
                        claim.lease_id,
                        claim.fencing_token,
                        self.lease_seconds,
                    ],
                )
            uow.commit()
        return claims

    def heartbeat(self, claim: OutboxClaim) -> dict[str, object]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_claim(uow, claim)
            uow.cursor.execute(
                """
                UPDATE outbox_event
                SET lease_expires_at=NOW() + (%s * INTERVAL '1 second'),
                    updated_at=NOW()
                WHERE outbox_id=%s AND claimed_by=%s AND lease_id=%s
                  AND fencing_token=%s AND LOWER(status)='claimed'
                  AND lease_expires_at > NOW()
                RETURNING lease_expires_at
                """,
                [
                    self.lease_seconds,
                    claim.outbox_id,
                    self.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise RuntimeError("outbox heartbeat carries a stale fencing claim")
            uow.cursor.execute(
                """
                UPDATE authority_outbox_delivery_execution
                SET heartbeat_at=NOW(), lease_expires_at=%s
                WHERE lease_id=%s AND worker_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [row[0], claim.lease_id, self.worker_id, claim.fencing_token],
            )
            uow.commit()
        return {
            "lease_expires_at": row[0],
            "fencing_token": claim.fencing_token,
        }

    def checkpoint(
        self, claim: OutboxClaim, checkpoint: dict[str, object]
    ) -> dict[str, object]:
        checkpoint_hash = canonical_payload_hash(checkpoint)
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_claim(uow, claim)
            uow.cursor.execute(
                """
                UPDATE authority_outbox_delivery_execution
                SET status='CHECKPOINTED',
                    checkpoint_sequence=checkpoint_sequence+1,
                    checkpoint=%s, checkpoint_hash=%s, heartbeat_at=NOW()
                WHERE lease_id=%s AND worker_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                RETURNING checkpoint_sequence
                """,
                [
                    Jsonb(checkpoint),
                    checkpoint_hash,
                    claim.lease_id,
                    self.worker_id,
                    claim.fencing_token,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise RuntimeError("outbox checkpoint carries a stale fencing claim")
            uow.cursor.execute(
                """
                UPDATE outbox_event
                SET lease_expires_at=NOW() + (%s * INTERVAL '1 second'),
                    updated_at=NOW()
                WHERE outbox_id=%s AND claimed_by=%s AND lease_id=%s
                  AND fencing_token=%s AND LOWER(status)='claimed'
                """,
                [
                    self.lease_seconds,
                    claim.outbox_id,
                    self.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise RuntimeError("outbox checkpoint lost its fenced claim")
            uow.commit()
        return {
            "checkpoint_sequence": int(row[0]),
            "checkpoint_hash": checkpoint_hash,
        }

    def deliver(self, claim: OutboxClaim) -> bool:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, claimed_by, lease_id, fencing_token, runtime_group,
                       lease_expires_at > NOW() AS lease_fresh
                FROM outbox_event
                WHERE outbox_id=%s AND event_id=%s AND project_id=%s
                FOR UPDATE
                """,
                [claim.outbox_id, claim.event_id, claim.project_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise RuntimeError("claimed outbox event disappeared")
            if str(row[0]).lower() == "acked":
                return False
            if str(row[0]).lower() != "claimed" or str(row[1]) != self.worker_id:
                raise RuntimeError("outbox lease is no longer owned by this worker")
            if (
                str(row[2]) != claim.lease_id
                or int(row[3]) != claim.fencing_token
                or str(row[4]) != claim.runtime_group
            ):
                raise RuntimeError("outbox fencing evidence no longer matches the claim")
            if not bool(row[5]):
                raise RuntimeError("outbox stale claim lease has expired")
            uow.cursor.execute(
                """
                INSERT INTO outbox_consumer_delivery(consumer_name, event_id)
                VALUES (%s, %s)
                ON CONFLICT (consumer_name, event_id) DO NOTHING
                """,
                [self.consumer_name, claim.event_id],
            )
            inserted = uow.cursor.rowcount == 1
            uow.cursor.execute(
                """
                UPDATE outbox_event
                SET status='acked', published_at=COALESCE(published_at, NOW()),
                    acked_at=COALESCE(acked_at, NOW()), lease_expires_at=NULL,
                    updated_at=NOW()
                WHERE outbox_id=%s AND claimed_by=%s AND LOWER(status)='claimed'
                  AND lease_id=%s AND fencing_token=%s AND runtime_group=%s
                """,
                [
                    claim.outbox_id,
                    self.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                    claim.runtime_group,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise RuntimeError("outbox acknowledgement lost its fenced claim")
            result_hash = canonical_payload_hash(
                {
                    "consumer_name": self.consumer_name,
                    "event_id": claim.event_id,
                    "delivered": inserted,
                    "delivery_scope": "INTERNAL",
                }
            )
            uow.cursor.execute(
                """
                UPDATE authority_outbox_delivery_execution
                SET status='SUCCEEDED', result_hash=%s,
                    heartbeat_at=NOW(), completed_at=NOW()
                WHERE lease_id=%s AND worker_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [
                    result_hash,
                    claim.lease_id,
                    self.worker_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise RuntimeError("outbox delivery execution lost its fenced claim")
            uow.commit()
        return inserted

    def fail(
        self,
        claim: OutboxClaim,
        error: dict[str, object],
        *,
        retry_delay_seconds: int = 0,
    ) -> dict[str, object]:
        if retry_delay_seconds < 0:
            raise ValueError("outbox retry delay cannot be negative")
        error_hash = canonical_payload_hash(error)
        with AuthorityUnitOfWork(self.database_url) as uow:
            row = self._lock_claim(uow, claim)
            status = "dead_letter" if int(row[6]) >= 5 else "failed"
            uow.cursor.execute(
                """
                UPDATE outbox_event
                SET status=%s, available_at=NOW() + (%s * INTERVAL '1 second'),
                    lease_expires_at=NULL, last_error=%s,
                    dead_letter_at=CASE WHEN %s='dead_letter' THEN NOW()
                                        ELSE dead_letter_at END,
                    updated_at=NOW()
                WHERE outbox_id=%s AND claimed_by=%s AND lease_id=%s
                  AND fencing_token=%s AND LOWER(status)='claimed'
                """,
                [
                    status,
                    retry_delay_seconds,
                    _safe_error(error),
                    status,
                    claim.outbox_id,
                    self.worker_id,
                    claim.lease_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise RuntimeError("outbox failure lost its fenced claim")
            uow.cursor.execute(
                """
                UPDATE authority_outbox_delivery_execution
                SET status=%s, error=%s, result_hash=%s,
                    heartbeat_at=NOW(), completed_at=NOW()
                WHERE lease_id=%s AND worker_id=%s AND fencing_token=%s
                  AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                """,
                [
                    "DEAD_LETTER" if status == "dead_letter" else "FAILED",
                    Jsonb(error),
                    error_hash,
                    claim.lease_id,
                    self.worker_id,
                    claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise RuntimeError("outbox failure execution lost its fenced claim")
            uow.commit()
        return {"status": status, "error_hash": error_hash}

    def recover_expired_claims(self, *, limit: int) -> tuple[dict[str, object], ...]:
        if limit <= 0:
            raise ValueError("outbox recovery limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                WITH selected AS (
                    SELECT outbox_id
                    FROM outbox_event
                    WHERE LOWER(status)='claimed' AND lease_expires_at <= NOW()
                    ORDER BY lease_expires_at, outbox_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE outbox_event AS event
                SET status=CASE WHEN attempt_count >= 5
                                THEN 'dead_letter' ELSE 'failed' END,
                    dead_letter_at=CASE WHEN attempt_count >= 5
                                        THEN NOW() ELSE dead_letter_at END,
                    available_at=NOW(), lease_expires_at=NULL,
                    last_error='outbox_lease_expired', updated_at=NOW()
                FROM selected
                WHERE event.outbox_id=selected.outbox_id
                RETURNING event.outbox_id, event.lease_id,
                          event.fencing_token, event.status
                """,
                [limit],
            )
            recovered = tuple(
                {
                    "outbox_id": str(row[0]),
                    "lease_id": str(row[1]),
                    "fencing_token": int(row[2]),
                    "status": str(row[3]),
                }
                for row in uow.cursor.fetchall()
            )
            for item in recovered:
                uow.cursor.execute(
                    """
                    UPDATE authority_outbox_delivery_execution
                    SET status=CASE WHEN %s='dead_letter'
                                    THEN 'DEAD_LETTER' ELSE 'ABANDONED' END,
                        error=%s, completed_at=NOW()
                    WHERE lease_id=%s AND fencing_token=%s
                      AND status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                    """,
                    [
                        item["status"],
                        Jsonb({"code": "OUTBOX_LEASE_EXPIRED"}),
                        item["lease_id"],
                        item["fencing_token"],
                    ],
                )
            uow.commit()
        return recovered

    def _lock_claim(
        self, uow: AuthorityUnitOfWork, claim: OutboxClaim
    ) -> tuple[object, ...]:
        uow.cursor.execute(
            """
            SELECT status, claimed_by, lease_id, fencing_token, runtime_group,
                   lease_expires_at, attempt_count
            FROM outbox_event
            WHERE outbox_id=%s AND event_id=%s AND project_id=%s
              AND lease_expires_at > NOW()
            FOR UPDATE
            """,
            [claim.outbox_id, claim.event_id, claim.project_id],
        )
        row = uow.cursor.fetchone()
        if not (
            row is not None
            and str(row[0]).lower() == "claimed"
            and str(row[1]) == self.worker_id
            and str(row[2]) == claim.lease_id
            and int(row[3]) == claim.fencing_token
            and str(row[4]) == claim.runtime_group
            and row[5] is not None
        ):
            raise RuntimeError("outbox stale fencing claim is no longer owned")
        return row


def main() -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Outbox worker requires PostgreSQL authority")
    worker_id = str(
        os.environ.get("NOVEL_FORGE_OUTBOX_WORKER_ID") or "outbox-worker"
    ).strip()
    poll_seconds = max(
        0.05, float(os.environ.get("NOVEL_FORGE_AUTHORITY_POLL_SECONDS") or "1")
    )
    batch_size = max(
        1, int(os.environ.get("NOVEL_FORGE_AUTHORITY_BATCH_SIZE") or "50")
    )
    dispatcher = PostgresOutboxDispatcher(
        settings.database_url, worker_id=worker_id
    )
    supervisor = WorkerSupervisor(
        worker_kind="outbox",
        worker_id=worker_id,
        observer=PostgresWorkerHealthObserver(settings.database_url),
    )
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            claims = dispatcher.claim(limit=batch_size)
            if not claims:
                supervisor.polled(idle=True)
                time.sleep(poll_seconds)
                continue
            supervisor.polled(idle=False)
            failures = 0
            for claim in claims:
                if stopping:
                    break
                supervisor.operation_started(claim.outbox_id)
                try:
                    dispatcher.checkpoint(
                        claim,
                        {"stage": "INTERNAL_DELIVERY_STARTED"},
                    )
                    dispatcher.deliver(claim)
                except Exception as exc:
                    failures += 1
                    try:
                        dispatcher.fail(
                            claim,
                            {"code": type(exc).__name__},
                        )
                    except Exception:
                        # INVARIANT: A concurrent higher fence owns recovery now.
                        pass
                    supervisor.operation_finished(claim.outbox_id, succeeded=False)
                else:
                    supervisor.operation_finished(claim.outbox_id, succeeded=True)
            supervisor.batch_completed(range(failures))  # WHY: only the count is observed
        supervisor.draining()
        supervisor.stopped()
        return 0
    finally:
        close_all_database_runtimes()


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
