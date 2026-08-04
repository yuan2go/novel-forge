"""PostgreSQL read adapters for the Production Execution Plane.

These adapters query existing Command Kernel Attempt/Lease authority and existing
Authority AssetVersions.  They intentionally create no parallel execution tables.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
)
from novel_forge.storage.database_runtime import get_database_runtime

from .contracts import InputManifest, ModelProfile, RoutePolicy, RouteSnapshot


T = TypeVar("T")


class PostgresAttemptFenceVerifier:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def assert_current(
        self, operation_id: str, attempt_id: str, fencing_token: int
    ) -> None:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT attempt.status, lease.fencing_token
                    FROM authority_attempt AS attempt
                    JOIN authority_operation AS operation
                      ON operation.operation_id = attempt.operation_id
                    LEFT JOIN LATERAL (
                        SELECT fencing_token
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
        status, current_token = row
        if status not in {"LEASED", "RUNNING", "CHECKPOINTED", "RESULT_SUBMITTED"}:
            raise ValueError(f"Authority Attempt is not execution-active: {status}")
        if current_token is None or int(current_token) != fencing_token:
            raise ValueError("stale Authority fencing token")


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
        return self._load(
            route_snapshot_id, "route_snapshot", RouteSnapshot.from_dict
        )

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
            raise ValueError(f"{expected_asset_type} AssetVersion has no contract object")
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


__all__ = ["PostgresAttemptFenceVerifier", "PostgresExecutionContractSource"]
