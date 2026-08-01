"""Transaction-only PostgreSQL repositories for Core OS runtime authority."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


class ConcurrentUpdateError(RuntimeError):
    pass


class InvalidLifecycleTransitionError(RuntimeError):
    pass


class ProductionOperationRepository:
    def __init__(self, cursor: Any): self.cursor = cursor
    def create(self, row: dict[str, Any]) -> None:
        self.cursor.execute("""INSERT INTO production_operation(operation_id,operation_type,project_id,parent_operation_id,status,idempotency_key,request_digest,environment,metadata,started_at) VALUES (%(operation_id)s,%(operation_type)s,%(project_id)s,%(parent_operation_id)s,%(status)s,%(idempotency_key)s,%(request_digest)s,%(environment)s,%(metadata)s,NOW())""", {**row, "metadata": Jsonb(row.get("metadata", {}))})
    def get_by_id(self, operation_id: str, project_id: str) -> dict[str, Any] | None:
        self.cursor.execute("SELECT operation_id,operation_type,project_id,status,version,idempotency_key,request_digest,environment,current_attempt,metadata FROM production_operation WHERE operation_id=%s AND project_id=%s", [operation_id, project_id]); return _one(self.cursor)
    def compare_and_set_status(self, operation_id: str, project_id: str, expected_version: int, expected_status: str, status: str) -> int:
        allowed={"pending":{"running","cancelled"},"running":{"paused","completed","failed","cancelled"},"paused":{"running","cancelled"},"failed":{"running"}}
        if status not in allowed.get(expected_status,set()):
            raise InvalidLifecycleTransitionError(f"{expected_status} -> {status} is not allowed")
        self.cursor.execute("UPDATE production_operation SET status=%s,version=version+1,updated_at=NOW() WHERE operation_id=%s AND project_id=%s AND version=%s AND status=%s RETURNING version", [status,operation_id,project_id,expected_version,expected_status]); row=self.cursor.fetchone()
        if not row: raise ConcurrentUpdateError("operation version/status conflict")
        return int(row[0])


class IdempotencyRepository:
    def __init__(self, cursor: Any): self.cursor=cursor
    def get(self, scope: str, key: str) -> dict[str, Any] | None:
        self.cursor.execute("SELECT request_digest,operation_id FROM idempotency_record WHERE scope=%s AND idempotency_key=%s",[scope,key]); return _one(self.cursor)
    def create(self, scope: str, key: str, digest: str, operation_id: str) -> None:
        self.cursor.execute("INSERT INTO idempotency_record(scope,idempotency_key,request_digest,operation_id) VALUES (%s,%s,%s,%s)",[scope,key,digest,operation_id])


class StateEventRepository:
    def __init__(self,cursor: Any): self.cursor=cursor
    def append(self,row: dict[str,Any]) -> None:
        self.cursor.execute("INSERT INTO state_event(event_id,aggregate_type,aggregate_id,project_id,event_type,event_version,sequence_number,correlation_id,causation_id,payload) VALUES (%(event_id)s,%(aggregate_type)s,%(aggregate_id)s,%(project_id)s,%(event_type)s,%(event_version)s,%(sequence_number)s,%(correlation_id)s,%(causation_id)s,%(payload)s)",{**row,"payload":Jsonb(row.get("payload",{}))})


class LifecycleCommandRepository:
    def __init__(self, cursor: Any): self.cursor = cursor
    def record(self, row: dict[str, Any]) -> None:
        self.cursor.execute("INSERT INTO production_operation_command(command_id,command_version,operation_id,project_id,action,expected_status,expected_version,idempotency_key,actor,reason,correlation_id,causation_id,checkpoint_ref,result) VALUES (%(command_id)s,%(command_version)s,%(operation_id)s,%(project_id)s,%(action)s,%(expected_status)s,%(expected_version)s,%(idempotency_key)s,%(actor)s,%(reason)s,%(correlation_id)s,%(causation_id)s,%(checkpoint_ref)s,%(result)s)",{**row,"result":Jsonb(row.get("result",{}))})
    def mark_applied(self, command_id: str, result: dict[str, Any]) -> None:
        self.cursor.execute("UPDATE production_operation_command SET applied_at=NOW(),result=%s WHERE command_id=%s",[Jsonb(result),command_id])


class OutboxRepository:
    def __init__(self,cursor: Any): self.cursor=cursor
    def enqueue(self,row: dict[str,Any]) -> None:
        self.cursor.execute("INSERT INTO outbox_event(outbox_id,event_id,project_id,topic,status,payload) VALUES (%(outbox_id)s,%(event_id)s,%(project_id)s,%(topic)s,'queued',%(payload)s)",{**row,"payload":Jsonb(row.get("payload",{}))})
    def claim(self, consumer: str, project_id: str, limit: int, lease_seconds: int) -> list[dict[str,Any]]:
        self.cursor.execute("""WITH selected AS (SELECT outbox_id FROM outbox_event WHERE project_id=%s AND status IN ('pending','queued','failed') AND available_at<=NOW() AND (lease_expires_at IS NULL OR lease_expires_at<NOW()) ORDER BY available_at,created_at FOR UPDATE SKIP LOCKED LIMIT %s) UPDATE outbox_event o SET status='claimed',claimed_by=%s,claimed_at=NOW(),lease_expires_at=NOW()+(%s * INTERVAL '1 second'),attempt_count=o.attempt_count+1,updated_at=NOW() FROM selected WHERE o.outbox_id=selected.outbox_id RETURNING o.outbox_id,o.event_id,o.project_id,o.topic,o.payload,o.attempt_count""",[project_id,limit,consumer,lease_seconds]); return [_row(self.cursor,r) for r in self.cursor.fetchall()]
    def ack(self, outbox_id: str, consumer: str) -> bool:
        self.cursor.execute("UPDATE outbox_event SET status='acked',acked_at=NOW(),updated_at=NOW() WHERE outbox_id=%s AND claimed_by=%s AND status='claimed'", [outbox_id, consumer])
        return self.cursor.rowcount == 1
    def fail(self, outbox_id: str, consumer: str, error: str, max_attempts: int) -> str:
        self.cursor.execute("UPDATE outbox_event SET status=CASE WHEN attempt_count >= %s THEN 'dead_letter' ELSE 'failed' END,last_error=%s,available_at=NOW()+INTERVAL '1 second',lease_expires_at=NULL,updated_at=NOW() WHERE outbox_id=%s AND claimed_by=%s AND status='claimed' RETURNING status",[max_attempts,error,outbox_id,consumer]); row=self.cursor.fetchone()
        if not row: raise ConcurrentUpdateError("outbox claim is no longer owned by consumer")
        return str(row[0])


class AuditLogRepository:
    def __init__(self,cursor: Any): self.cursor=cursor
    def append(self,row:dict[str,Any])->None: self.cursor.execute("INSERT INTO audit_log(audit_id,project_id,operation_id,action,payload) VALUES (%(audit_id)s,%(project_id)s,%(operation_id)s,%(action)s,%(payload)s)",{**row,"payload":Jsonb(row.get("payload",{}))})


class ConsumerDeliveryRepository:
    def __init__(self, cursor: Any): self.cursor = cursor
    def record_once(self, consumer_name: str, event_id: str) -> bool:
        self.cursor.execute("INSERT INTO outbox_consumer_delivery(consumer_name,event_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", [consumer_name,event_id])
        return self.cursor.rowcount == 1


class OperationLeaseRepository:
    def __init__(self, cursor: Any): self.cursor = cursor
    def acquire(self, operation_id: str, owner: str, lease_seconds: int) -> bool:
        self.cursor.execute("""INSERT INTO operation_lease(operation_id,lease_owner,lease_expires_at) VALUES (%s,%s,NOW()+(%s * INTERVAL '1 second')) ON CONFLICT(operation_id) DO UPDATE SET lease_owner=EXCLUDED.lease_owner,lease_expires_at=EXCLUDED.lease_expires_at,version=operation_lease.version+1,updated_at=NOW() WHERE operation_lease.lease_expires_at < NOW() RETURNING operation_id""",[operation_id,owner,lease_seconds])
        return self.cursor.fetchone() is not None
    def release(self, operation_id: str, owner: str) -> bool:
        self.cursor.execute("DELETE FROM operation_lease WHERE operation_id=%s AND lease_owner=%s",[operation_id,owner]); return self.cursor.rowcount == 1

OperationAttemptRepository = StateSnapshotRepository = AuditLogRepository

def _one(cursor: Any) -> dict[str,Any] | None:
    row=cursor.fetchone(); return _row(cursor,row) if row else None
def _row(cursor: Any,row: Any)->dict[str,Any]: return dict(zip([d.name for d in cursor.description],row))
