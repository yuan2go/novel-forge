from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class OperationGraphRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def operation(self, operation_id: str, project_id: str, *, lock: bool = False) -> dict[str, Any]:
        lock_clause = " FOR UPDATE" if lock else ""
        self.cursor.execute(
            f"""
            SELECT operation_id, project_id, status, version, root_operation_id,
                   parent_operation_id, definition_name, saga_id, step_key
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s{lock_clause}
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "operation does not exist in project")
        fields = (
            "operation_id",
            "project_id",
            "status",
            "version",
            "root_operation_id",
            "parent_operation_id",
            "definition_name",
            "saga_id",
            "step_key",
        )
        return dict(zip(fields, row, strict=True))

    def latest_definition_version(self, name: str) -> str:
        self.cursor.execute(
            """
            SELECT definition_version
            FROM authority_operation_definition
            WHERE name = %s AND enabled = TRUE
            ORDER BY created_at DESC, definition_version DESC
            LIMIT 1
            """,
            [name],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_DEFINITION_NOT_FOUND",
                "saga compensation definition is not registered",
            )
        return str(row[0])

    def expected_saga_step_count(self, root_operation_id: str) -> int:
        self.cursor.execute(
            """
            SELECT COALESCE((definition_snapshot->'policy'->>'expected_saga_steps')::int, 0)
            FROM authority_operation
            WHERE operation_id = %s AND root_operation_id = operation_id
            """,
            [root_operation_id],
        )
        row = self.cursor.fetchone()
        return 0 if row is None else int(row[0] or 0)

    def add_dependency(self, operation_id: str, depends_on: str, condition: str) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_operation_dependency (
                operation_id, depends_on_operation_id, dependency_condition
            ) VALUES (%s, %s, %s)
            ON CONFLICT (operation_id, depends_on_operation_id) DO NOTHING
            RETURNING operation_id
            """,
            [operation_id, depends_on, condition],
        )
        inserted = self.cursor.fetchone()
        if inserted:
            return True
        self.cursor.execute(
            """
            SELECT dependency_condition
            FROM authority_operation_dependency
            WHERE operation_id = %s AND depends_on_operation_id = %s
            """,
            [operation_id, depends_on],
        )
        existing = self.cursor.fetchone()
        if existing is None or existing[0] != condition:
            raise KernelError(
                "DEPENDENCY_CONDITION_CONFLICT",
                "operation dependency is already bound to another condition",
            )
        return False

    def graph_rows(self, root_operation_id: str, project_id: str) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT operation_id, status, definition_name, parent_operation_id
            FROM authority_operation
            WHERE project_id = %s
              AND (operation_id = %s OR root_operation_id = %s)
            ORDER BY created_at, operation_id
            """,
            [project_id, root_operation_id, root_operation_id],
        )
        return [
            {
                "operation_id": row[0],
                "status": row[1],
                "definition_name": row[2],
                "parent_operation_id": row[3],
            }
            for row in self.cursor.fetchall()
        ]

    def dependency_rows(self, operation_ids: list[str]) -> list[dict[str, str]]:
        if not operation_ids:
            return []
        self.cursor.execute(
            """
            SELECT operation_id, depends_on_operation_id, dependency_condition
            FROM authority_operation_dependency
            WHERE operation_id = ANY(%s)
            ORDER BY operation_id, depends_on_operation_id
            """,
            [operation_ids],
        )
        return [
            {"operation_id": row[0], "depends_on": row[1], "condition": row[2]}
            for row in self.cursor.fetchall()
        ]

    def passed_manual_gates(self, operation_ids: list[str]) -> set[tuple[str, str]]:
        if not operation_ids:
            return set()
        self.cursor.execute(
            """
            SELECT operation_id, gate_key
            FROM authority_completion_gate
            WHERE operation_id = ANY(%s) AND status = 'PASSED'
            """,
            [operation_ids],
        )
        return {(row[0], row[1]) for row in self.cursor.fetchall()}

    def start_saga(
        self,
        saga_id: str,
        root_operation_id: str,
        project_id: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            INSERT INTO authority_saga (
                saga_id, root_operation_id, project_id, status,
                trace_id, correlation_id
            ) VALUES (%s, %s, %s, 'RUNNING', %s, %s)
            ON CONFLICT (root_operation_id) DO NOTHING
            RETURNING saga_id
            """,
            [saga_id, root_operation_id, project_id, trace_id, correlation_id],
        )
        inserted = self.cursor.fetchone()
        if inserted:
            self.cursor.execute(
                "UPDATE authority_operation SET saga_id = %s WHERE operation_id = %s",
                [saga_id, root_operation_id],
            )
            self.cursor.execute(
                """
                UPDATE authority_saga
                SET root_deadline_at = (
                    SELECT business_deadline_at FROM authority_operation
                    WHERE operation_id = %s
                )
                WHERE saga_id = %s
                """,
                [root_operation_id, saga_id],
            )
            return {"saga_id": saga_id, "replayed": False}
        self.cursor.execute(
            "SELECT saga_id FROM authority_saga WHERE root_operation_id = %s",
            [root_operation_id],
        )
        return {"saga_id": self.cursor.fetchone()[0], "replayed": True}

    def register_step(
        self,
        saga_id: str,
        operation_id: str,
        step_key: str,
        ordinal: int,
        compensation_definition: str,
    ) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_saga_step (
                saga_id, operation_id, step_key, ordinal, compensation_definition
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (saga_id, step_key) DO NOTHING
            RETURNING operation_id
            """,
            [saga_id, operation_id, step_key, ordinal, compensation_definition],
        )
        inserted = self.cursor.fetchone()
        if inserted:
            self.cursor.execute(
                "UPDATE authority_operation SET saga_id = %s, step_key = %s WHERE operation_id = %s",
                [saga_id, step_key, operation_id],
            )
            return True
        self.cursor.execute(
            """
            SELECT operation_id, ordinal, compensation_definition
            FROM authority_saga_step WHERE saga_id = %s AND step_key = %s
            """,
            [saga_id, step_key],
        )
        existing = self.cursor.fetchone()
        if existing != (operation_id, ordinal, compensation_definition):
            raise KernelError("SAGA_STEP_CONFLICT", "saga step key content has drifted")
        return False

    def saga_for_update(self, saga_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT saga_id, root_operation_id, status, version,
                   coordinator_owner, coordinator_lease_id,
                   coordinator_fencing_token, coordinator_expires_at
            FROM authority_saga
            WHERE saga_id = %s AND project_id = %s
            FOR UPDATE
            """,
            [saga_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("SAGA_NOT_FOUND", "saga does not exist in project")
        return {
            "saga_id": row[0],
            "root_operation_id": row[1],
            "status": row[2],
            "version": row[3],
            "coordinator_owner": row[4],
            "coordinator_lease_id": row[5],
            "coordinator_fencing_token": row[6],
            "coordinator_expires_at": row[7],
        }

    def acquire_coordinator(
        self,
        saga: dict[str, Any],
        *,
        owner: str,
        lease_id: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            UPDATE authority_saga
            SET coordinator_owner = %s,
                coordinator_lease_id = %s,
                coordinator_fencing_token = coordinator_fencing_token + 1,
                coordinator_expires_at = NOW() + make_interval(secs => %s),
                coordinator_heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE saga_id = %s
              AND (
                  coordinator_expires_at IS NULL
                  OR coordinator_expires_at <= NOW()
                  OR coordinator_owner = %s
              )
            RETURNING coordinator_fencing_token, coordinator_expires_at
            """,
            [owner, lease_id, lease_seconds, saga["saga_id"], owner],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("SAGA_COORDINATOR_LEASE_HELD", "another coordinator owns the saga")
        return {
            "lease_id": lease_id,
            "fencing_token": int(row[0]),
            "expires_at": row[1],
        }

    def release_coordinator(self, saga_id: str, owner: str, fencing_token: int) -> None:
        self.cursor.execute(
            """
            UPDATE authority_saga
            SET coordinator_expires_at = NULL,
                coordinator_heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE saga_id = %s AND coordinator_owner = %s
              AND coordinator_fencing_token = %s
            """,
            [saga_id, owner, fencing_token],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("SAGA_FENCING_TOKEN_STALE", "coordinator lease is stale")

    def saga_steps(self, saga_id: str) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT step.operation_id, step.step_key, step.ordinal,
                   step.compensation_definition, step.compensation_status,
                   operation.status, step.compensation_operation_id,
                   compensation.status
            FROM authority_saga_step AS step
            JOIN authority_operation AS operation
              ON operation.operation_id = step.operation_id
            LEFT JOIN authority_operation AS compensation
              ON compensation.operation_id = step.compensation_operation_id
            WHERE step.saga_id = %s
            ORDER BY step.ordinal
            FOR UPDATE OF step, operation
            """,
            [saga_id],
        )
        fields = (
            "operation_id",
            "step_key",
            "ordinal",
            "compensation_definition",
            "compensation_status",
            "status",
            "compensation_operation_id",
            "compensation_operation_status",
        )
        return [dict(zip(fields, row, strict=True)) for row in self.cursor.fetchall()]

    def mark_compensation_required(self, operation_ids: list[str]) -> None:
        if not operation_ids:
            return
        self.cursor.execute(
            """
            UPDATE authority_saga_step
            SET compensation_status = 'REQUIRED'
            WHERE operation_id = ANY(%s) AND compensation_status = 'NOT_REQUIRED'
            """,
            [operation_ids],
        )

    def attach_compensation_operation(
        self,
        operation_id: str,
        compensation_operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_saga_step
            SET compensation_operation_id = %s,
                compensation_status = 'COMPENSATING'
            WHERE operation_id = %s
              AND compensation_status IN ('REQUIRED', 'COMPENSATING')
              AND (
                  compensation_operation_id IS NULL
                  OR compensation_operation_id = %s
              )
            """,
            [compensation_operation_id, operation_id, compensation_operation_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "SAGA_COMPENSATION_CHILD_CONFLICT",
                "saga step is already bound to another compensation child",
            )

    def synchronize_compensation_statuses(self, saga_id: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_saga_step AS step
            SET compensation_status = CASE
                WHEN operation.status = 'SUCCEEDED' THEN 'COMPENSATED'
                WHEN operation.status IN ('FAILED_FINAL', 'DEAD_LETTER')
                    THEN 'COMPENSATION_FAILED'
                ELSE step.compensation_status
            END
            FROM authority_operation AS operation
            WHERE step.saga_id = %s
              AND step.compensation_operation_id = operation.operation_id
              AND step.compensation_status = 'COMPENSATING'
            """,
            [saga_id],
        )

    def recover_forward(self, operation_ids: list[str]) -> list[str]:
        if not operation_ids:
            return []
        self.cursor.execute(
            """
            UPDATE authority_operation
            SET status = 'READY', version = version + 1, updated_at = NOW()
            WHERE operation_id = ANY(%s) AND status = 'FAILED_RETRYABLE'
            RETURNING operation_id
            """,
            [operation_ids],
        )
        recovered = [row[0] for row in self.cursor.fetchall()]
        if recovered:
            self.cursor.execute(
                """
                UPDATE authority_saga
                SET forward_recovery_attempts = forward_recovery_attempts + 1
                WHERE saga_id = (
                    SELECT saga_id FROM authority_saga_step
                    WHERE operation_id = ANY(%s) LIMIT 1
                )
                """,
                [recovered],
            )
        return recovered

    def update_saga(self, saga_id: str, expected_version: int, status: str) -> None:
        self.cursor.execute(
            """
            UPDATE authority_saga
            SET status = %s, version = version + 1, updated_at = NOW()
            WHERE saga_id = %s AND version = %s
            """,
            [status, saga_id, expected_version],
        )
        if self.cursor.rowcount != 1:
            raise KernelError("SAGA_VERSION_CONFLICT", "saga changed during coordination")

    def set_ready(self, operation_ids: list[str]) -> list[str]:
        if not operation_ids:
            return []
        self.cursor.execute(
            """
            UPDATE authority_operation
            SET status = 'READY', version = version + 1, updated_at = NOW()
            WHERE operation_id = ANY(%s) AND status = 'ADMITTED'
            RETURNING operation_id
            """,
            [operation_ids],
        )
        return [row[0] for row in self.cursor.fetchall()]

    def complete_root(self, root_operation_id: str, status: str) -> bool:
        self.cursor.execute(
            """
            UPDATE authority_operation
            SET status = %s, version = version + 1, updated_at = NOW()
            WHERE operation_id = %s AND status <> %s
            """,
            [status, root_operation_id, status],
        )
        return self.cursor.rowcount == 1

    def record_event(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM state_event
            WHERE aggregate_type = %(aggregate_type)s AND aggregate_id = %(aggregate_id)s
            """,
            row,
        )
        sequence = self.cursor.fetchone()[0]
        parameters = {**row, "sequence_number": sequence, "payload": Jsonb(row["payload"])}
        self.cursor.execute(
            """
            INSERT INTO state_event (
                event_id, aggregate_type, aggregate_id, project_id, event_type,
                event_version, sequence_number, correlation_id, causation_id, payload
            ) VALUES (
                %(event_id)s, %(aggregate_type)s, %(aggregate_id)s, %(project_id)s,
                %(event_type)s, 1, %(sequence_number)s, %(correlation_id)s,
                %(causation_id)s, %(payload)s
            )
            """,
            parameters,
        )
        self.cursor.execute(
            """
            INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
            VALUES (%(audit_id)s, %(project_id)s, %(operation_id)s, %(event_type)s, %(payload)s)
            """,
            parameters,
        )
        self.cursor.execute(
            """
            INSERT INTO outbox_event (outbox_id, event_id, project_id, topic, status, payload)
            VALUES (
                %(outbox_id)s, %(event_id)s, %(project_id)s,
                %(event_type)s, 'PENDING', %(payload)s
            )
            """,
            parameters,
        )


class CompletionContractRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def operation(self, operation_id: str, project_id: str, *, lock: bool) -> dict[str, Any]:
        lock_clause = " FOR UPDATE" if lock else ""
        self.cursor.execute(
            f"""
            SELECT operation_id, project_id, status, version, definition_name,
                   completion_contract_snapshot, trace_id, correlation_id,
                   definition_snapshot
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s{lock_clause}
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "completion operation does not exist")
        fields = (
            "operation_id",
            "project_id",
            "status",
            "version",
            "definition_name",
            "contract",
            "trace_id",
            "correlation_id",
            "definition_snapshot",
        )
        return dict(zip(fields, row, strict=True))

    def child_states(self, operation_id: str) -> list[tuple[str, str]]:
        self.cursor.execute(
            "SELECT definition_name, status FROM authority_operation WHERE parent_operation_id = %s",
            [operation_id],
        )
        return self.cursor.fetchall()

    def approval_states(self, operation_id: str) -> dict[str, str]:
        self.cursor.execute(
            "SELECT approval_key, status FROM authority_completion_approval WHERE operation_id = %s",
            [operation_id],
        )
        return dict(self.cursor.fetchall())

    def gate_states(self, operation_id: str) -> dict[str, str]:
        self.cursor.execute(
            "SELECT gate_key, status FROM authority_completion_gate WHERE operation_id = %s",
            [operation_id],
        )
        return dict(self.cursor.fetchall())

    def effect_states(self, operation_id: str) -> list[tuple[str, str]]:
        self.cursor.execute(
            "SELECT capability, status FROM authority_external_effect WHERE operation_id = %s",
            [operation_id],
        )
        return self.cursor.fetchall()

    def aggregate_states(self, operation_id: str) -> list[tuple[str, str, str]]:
        self.cursor.execute(
            """
            SELECT aggregate_type, aggregate_id, state
            FROM authority_completion_aggregate_state WHERE operation_id = %s
            """,
            [operation_id],
        )
        return self.cursor.fetchall()

    def qualifying_assets(
        self,
        operation_id: str,
        project_id: str,
        selector: str,
        *,
        output_key: str = "",
        role: str = "",
    ) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT version.asset_version_id, version.lifecycle, version.eligibility,
                   version.governance, binding.output_key, binding.role
            FROM authority_operation_output_asset AS binding
            JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id = binding.asset_version_id
             AND version.asset_id = binding.asset_id
            WHERE binding.operation_id = %s
              AND asset.project_id = %s
              AND asset.asset_type = %s
              AND binding.content_hash = version.content_hash
              AND (%s = '' OR binding.output_key = %s)
              AND (%s = '' OR binding.role = %s)
            """,
            [operation_id, project_id, selector, output_key, output_key, role, role],
        )
        return [
            {
                "asset_version_id": row[0],
                "lifecycle": row[1],
                "eligibility": row[2],
                "governance": row[3],
                "output_key": row[4],
                "role": row[5],
            }
            for row in self.cursor.fetchall()
        ]

    def qualifications(self, asset_version_ids: list[str]) -> dict[str, str]:
        if not asset_version_ids:
            return {}
        self.cursor.execute(
            """
            SELECT DISTINCT ON (asset_version_id) asset_version_id, decision
            FROM authority_asset_qualification
            WHERE asset_version_id = ANY(%s)
            ORDER BY asset_version_id, created_at DESC, qualification_id DESC
            """,
            [asset_version_ids],
        )
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def blob_states(self, asset_version_ids: list[str]) -> list[dict[str, Any]]:
        if not asset_version_ids:
            return []
        self.cursor.execute(
            """
            SELECT reference.asset_version_id, blob.status, reference.role,
                   reference.ordinal, reference.content_hash
            FROM authority_asset_version_blob_reference AS reference
            JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
            WHERE reference.asset_version_id = ANY(%s)
            """,
            [asset_version_ids],
        )
        return [
            {
                "asset_version_id": row[0],
                "status": row[1],
                "role": row[2],
                "ordinal": row[3],
                "content_hash": row[4],
            }
            for row in self.cursor.fetchall()
        ]

    def has_audit(self, operation_id: str) -> bool:
        self.cursor.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM audit_log
                WHERE operation_id = %s
                  AND action <> 'authority.operation.admitted'
            )
            """,
            [operation_id],
        )
        return bool(self.cursor.fetchone()[0])

    def audit_actions(self, operation_id: str) -> set[str]:
        self.cursor.execute(
            "SELECT DISTINCT action FROM audit_log WHERE operation_id = %s",
            [operation_id],
        )
        return {row[0] for row in self.cursor.fetchall()}

    def has_cost(self, operation_id: str) -> bool:
        self.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_operation_cost_evidence WHERE operation_id = %s)",
            [operation_id],
        )
        return bool(self.cursor.fetchone()[0])

    def outbox_topics(self, project_id: str, operation_id: str) -> set[str]:
        self.cursor.execute(
            """
            SELECT DISTINCT topic FROM outbox_event
            WHERE project_id = %s AND payload->>'operation_id' = %s
            UNION
            SELECT DISTINCT topic FROM outbox_event
            WHERE project_id = %s AND event_id IN (
                SELECT event_id FROM state_event
                WHERE aggregate_type = 'authority_operation' AND aggregate_id = %s
            )
            """,
            [project_id, operation_id, project_id, operation_id],
        )
        return {row[0] for row in self.cursor.fetchall()}
