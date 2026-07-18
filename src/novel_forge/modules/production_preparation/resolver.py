from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_preparation.contracts import ResolvedProductionAsset
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class PostgresProductionAssetResolver:
    """Read-only resolver for latest qualified Authority AssetVersions."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def resolve_latest(
        self, *, project_id: str, asset_type: str
    ) -> ResolvedProductionAsset | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id, asset.asset_id, version.asset_version_id,
                       asset.asset_type, version.content_hash, version.content,
                       COALESCE(qualification.decision, 'ELIGIBLE')
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id = asset.asset_id
                LEFT JOIN LATERAL (
                    SELECT decision
                    FROM authority_asset_qualification
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC
                    LIMIT 1
                ) AS qualification ON TRUE
                WHERE asset.project_id = %s AND asset.asset_type = %s
                  AND version.lifecycle = 'ACTIVE'
                  AND version.eligibility = 'ELIGIBLE'
                  AND version.governance = 'CLEAR'
                  AND COALESCE(qualification.decision, 'ELIGIBLE') = 'ELIGIBLE'
                ORDER BY version.created_at DESC, version.version_number DESC,
                         version.asset_version_id DESC
                LIMIT 1
                """,
                [project_id, asset_type],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return self._asset(row, "latest eligible authority version")

    def resolve_override(
        self, *, project_id: str, asset_version_id: str
    ) -> ResolvedProductionAsset:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id, asset.asset_id, version.asset_version_id,
                       asset.asset_type, version.content_hash, version.content,
                       COALESCE(qualification.decision, 'ELIGIBLE'),
                       version.lifecycle, version.eligibility, version.governance
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                LEFT JOIN LATERAL (
                    SELECT decision
                    FROM authority_asset_qualification
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC
                    LIMIT 1
                ) AS qualification ON TRUE
                WHERE version.asset_version_id = %s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("PREPARATION_OVERRIDE_NOT_FOUND", "override AssetVersion is missing")
        if row[0] != project_id:
            raise KernelError(
                "PREPARATION_CROSS_PROJECT_INPUT",
                "override AssetVersion belongs to another project",
            )
        if tuple(row[7:10]) != ("ACTIVE", "ELIGIBLE", "CLEAR") or row[6] != "ELIGIBLE":
            raise KernelError(
                "PREPARATION_OVERRIDE_NOT_ELIGIBLE",
                "override AssetVersion is stale, revoked, or quarantined",
            )
        return self._asset(row[:7], "explicit audited AssetVersion override")

    @staticmethod
    def _asset(row: tuple[object, ...], reason: str) -> ResolvedProductionAsset:
        return ResolvedProductionAsset(
            project_id=str(row[0]),
            asset_id=str(row[1]),
            asset_version_id=str(row[2]),
            asset_type=str(row[3]),
            content_hash=str(row[4]),
            content=dict(row[5] or {}),
            qualification=str(row[6]),
            selected_reason=reason,
        )

