"""PostgreSQL outbox dispatcher with durable idempotent internal receipts."""
from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.command_kernel.worker_execution import WorkerSupervisor
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import close_all_database_runtimes
from novel_forge.storage.worker_health import PostgresWorkerHealthObserver


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
    """Claims globally but commits each delivery receipt in a short transaction."""

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
            uow.commit()
        return claims

    def deliver(self, claim: OutboxClaim) -> bool:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, claimed_by, lease_id, fencing_token, runtime_group
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
            uow.commit()
        return inserted


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
                    dispatcher.deliver(claim)
                except Exception:
                    failures += 1
                    supervisor.operation_finished(claim.outbox_id, succeeded=False)
                else:
                    supervisor.operation_finished(claim.outbox_id, succeeded=True)
            supervisor.batch_completed(range(failures))  # only the count is observed
        supervisor.draining()
        supervisor.stopped()
        return 0
    finally:
        close_all_database_runtimes()


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
