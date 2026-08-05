"""PostgreSQL read adapters for the Production Execution Plane.

These adapters query existing Command Kernel Attempt/Lease authority and existing
Authority AssetVersions.  They intentionally create no parallel execution tables.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar
from uuid import NAMESPACE_URL, uuid5

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import get_database_runtime

from .contracts import (
    ExecutionRecoveryAuthorization,
    InputManifest,
    ModelProfile,
    RoutePolicy,
    RouteSnapshot,
)


T = TypeVar("T")


class PostgresAttemptFenceVerifier:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def assert_current(
        self, operation_id: str, attempt_id: str, fencing_token: int
    ) -> None:
        self._assert_current(
            operation_id,
            attempt_id,
            fencing_token,
            worker_id="",
        )

    def assert_recovery_current(
        self,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("recovery worker identity is required")
        self._assert_current(
            operation_id,
            attempt_id,
            fencing_token,
            worker_id=worker_id,
        )

    def _assert_current(
        self,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        *,
        worker_id: str,
    ) -> None:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT attempt.status, lease.fencing_token, lease.owner
                    FROM authority_attempt AS attempt
                    JOIN authority_operation AS operation
                      ON operation.operation_id = attempt.operation_id
                    LEFT JOIN LATERAL (
                        SELECT fencing_token, owner
                        FROM authority_lease_acquisition
                        WHERE attempt_id = attempt.attempt_id
                          AND status = 'HELD'
                          AND expires_at > NOW()
                        ORDER BY fencing_token DESC
                        LIMIT 1
                    ) AS lease ON TRUE
                    WHERE attempt.attempt_id = %s
                      AND attempt.operation_id = %s
                    """,
                    [attempt_id, operation_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise ValueError("Authority Attempt does not exist for operation")
        status, current_token, current_owner = row
        if status not in {"LEASED", "RUNNING", "CHECKPOINTED", "RESULT_SUBMITTED"}:
            raise ValueError(f"Authority Attempt is not execution-active: {status}")
        if current_token is None or int(current_token) != fencing_token:
            raise ValueError("stale Authority fencing token")
        if worker_id and str(current_owner) != worker_id:
            raise ValueError("recovery worker does not own the current lease")


class PostgresExecutionRecoveryAuthorizationStore:
    """Persist immutable dual-fence authorization plus its audit/outbox fact."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def record(self, authorization: ExecutionRecoveryAuthorization) -> None:
        event_id = str(
            uuid5(
                NAMESPACE_URL,
                "novel-forge:" + authorization.authorization_id,
            )
        )
        payload = authorization.to_dict()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT project_id FROM authority_operation WHERE operation_id=%s",
                [authorization.operation_id],
            )
            project_row = uow.cursor.fetchone()
            if project_row is None:
                raise KernelError(
                    "EXECUTION_RECOVERY_OPERATION_MISSING",
                    "Recovery Authorization operation does not exist",
                )
            project_id = str(project_row[0])
            uow.cursor.execute(
                """
                INSERT INTO authority_execution_recovery_authorization(
                    authorization_id, project_id, operation_id, attempt_id,
                    external_effect_id, execution_id,
                    execution_fencing_token, recovery_fencing_token,
                    recovery_worker_id, action, trace_id, correlation_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(authorization_id) DO NOTHING
                """,
                [
                    authorization.authorization_id,
                    project_id,
                    authorization.operation_id,
                    authorization.attempt_id,
                    authorization.external_effect_id,
                    authorization.execution_id,
                    authorization.execution_fencing_token,
                    authorization.recovery_fencing_token,
                    authorization.recovery_worker_id,
                    authorization.action.value,
                    authorization.trace_id,
                    authorization.correlation_id,
                ],
            )
            uow.cursor.execute(
                """
                SELECT project_id, operation_id, attempt_id,
                       external_effect_id, execution_id,
                       execution_fencing_token, recovery_fencing_token,
                       recovery_worker_id, action, trace_id, correlation_id
                FROM authority_execution_recovery_authorization
                WHERE authorization_id=%s
                """,
                [authorization.authorization_id],
            )
            recovery_row = uow.cursor.fetchone()
            expected = (
                project_id,
                authorization.operation_id,
                authorization.attempt_id,
                authorization.external_effect_id,
                authorization.execution_id,
                authorization.execution_fencing_token,
                authorization.recovery_fencing_token,
                authorization.recovery_worker_id,
                authorization.action.value,
                authorization.trace_id,
                authorization.correlation_id,
            )
            if recovery_row is None or tuple(recovery_row) != expected:
                raise KernelError(
                    "EXECUTION_RECOVERY_AUTHORIZATION_CONFLICT",
                    "Recovery Authorization identity was reused with different facts",
                )
            uow.cursor.execute(
                "SELECT payload FROM state_event WHERE event_id=%s",
                [event_id],
            )
            row = uow.cursor.fetchone()
            if row is not None:
                if dict(row[0]) != payload:
                    raise KernelError(
                        "EXECUTION_RECOVERY_AUTHORIZATION_CONFLICT",
                        "Recovery Authorization identity was reused with different facts",
                    )
                uow.commit()
                return
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": event_id,
                    "audit_id": str(
                        uuid5(NAMESPACE_URL, "novel-forge:audit:" + event_id)
                    ),
                    "outbox_id": str(
                        uuid5(NAMESPACE_URL, "novel-forge:outbox:" + event_id)
                    ),
                    "aggregate_type": "authority_execution_recovery",
                    "aggregate_id": authorization.external_effect_id,
                    "operation_id": authorization.operation_id,
                    "project_id": project_id,
                    "event_type": "authority.execution.recovery_authorized",
                    "correlation_id": authorization.correlation_id,
                    "causation_id": authorization.external_effect_id,
                    "payload": payload,
                }
            )
            uow.commit()


class PostgresExecutionContractSource:
    """Reads immutable execution contracts from Authority AssetVersion documents."""

    MODEL_PROFILE_PREFIX = "production_execution/model_profiles"
    ROUTE_POLICY_PREFIX = "production_execution/route_policies"

    def __init__(self, database_url: str, *, project_id: str) -> None:
        if not project_id:
            raise ValueError("execution contract source requires project_id")
        self.project_id = project_id
        self.assets = AuthorityAssetQuery(database_url)

    def route_snapshot(self, route_snapshot_id: str) -> RouteSnapshot:
        return self._load(route_snapshot_id, "route_snapshot", RouteSnapshot.from_dict)

    def model_profile(self, profile_id: str, version: int) -> ModelProfile:
        logical_ref = f"{self.MODEL_PROFILE_PREFIX}/{profile_id}/v{version}"
        return self._load(logical_ref, "model_profile", ModelProfile.from_dict)

    def route_policy(self, policy_id: str, version: int) -> RoutePolicy:
        logical_ref = f"{self.ROUTE_POLICY_PREFIX}/{policy_id}/v{version}"
        return self._load(logical_ref, "route_policy", RoutePolicy.from_dict)

    def input_manifest(self, manifest_ref: str) -> InputManifest:
        return self._load(manifest_ref, "input_manifest", InputManifest.from_dict)

    def _load(
        self,
        logical_ref: str,
        expected_asset_type: str,
        parser: Callable[[dict[str, Any]], T],
    ) -> T:
        document = self.assets.require(
            project_id=self.project_id, logical_ref=logical_ref
        )
        self._require_governed(document, expected_asset_type)
        payload = document.content.get("contract", document.content)
        if not isinstance(payload, dict):
            raise ValueError(
                f"{expected_asset_type} AssetVersion has no contract object"
            )
        return parser(payload)

    @staticmethod
    def _require_governed(
        document: AuthorityAssetDocument, expected_asset_type: str
    ) -> None:
        if document.asset_type != expected_asset_type:
            raise ValueError(
                f"execution contract AssetVersion type is {document.asset_type}, "
                f"expected {expected_asset_type}"
            )
        if document.lifecycle != "ACTIVE":
            raise ValueError("execution contract AssetVersion is not ACTIVE")
        if document.eligibility != "ELIGIBLE":
            raise ValueError("execution contract AssetVersion is not ELIGIBLE")
        if document.governance != "CLEAR":
            raise ValueError("execution contract AssetVersion is not governance-clear")


__all__ = [
    "PostgresAttemptFenceVerifier",
    "PostgresExecutionContractSource",
    "PostgresExecutionRecoveryAuthorizationStore",
]
