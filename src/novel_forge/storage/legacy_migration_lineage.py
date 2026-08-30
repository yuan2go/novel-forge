"""Exact approval lineage checks for legacy domain activation.

This module validates existing Legacy Migration Authority facts.  It does not
create approval, qualification, activation, or planning state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def require_approved_legacy_migration_lineage(
    cursor: Any,
    *,
    project_id: str,
    workspace_id: str,
    target_asset_version_id: str,
    target_content_hash: str,
    evidence: Mapping[str, Any],
) -> dict[str, str]:
    """Require one exact, current, independently approved migration lineage."""

    identity = {
        "migration_run_id": str(evidence.get("migration_run_id") or ""),
        "migration_item_id": str(evidence.get("migration_item_id") or ""),
        "migration_decision_id": str(
            evidence.get("migration_decision_id") or ""
        ),
        "migration_validation_id": str(
            evidence.get("migration_validation_id") or ""
        ),
        "source_hash": str(evidence.get("source_hash") or ""),
        "legacy_import_operation_id": str(
            evidence.get("legacy_import_operation_id") or ""
        ),
        "validator_result_hash": str(
            evidence.get("validator_result_hash") or ""
        ),
        "validator_version": str(evidence.get("validator_version") or ""),
    }
    if (
        not project_id
        or not workspace_id
        or not target_asset_version_id
        or not target_content_hash.startswith("sha256:")
        or not all(identity.values())
        or not identity["source_hash"].startswith("sha256:")
        or not identity["validator_result_hash"].startswith("sha256:")
    ):
        raise KernelError(
            "LEGACY_MIGRATION_LINEAGE_INVALID",
            "legacy activation requires complete approved migration identity",
        )

    cursor.execute(
        """
        SELECT decision.operation_id,
               validation.validated_by_operation_id,
               item.operation_id
        FROM authority_legacy_migration_decision AS decision
        JOIN authority_legacy_migration_validation AS validation
          ON validation.migration_validation_id=
             decision.migration_validation_id
        JOIN authority_legacy_migration_item AS item
          ON item.migration_item_id=decision.migration_item_id
        WHERE decision.migration_decision_id=%s
          AND decision.migration_run_id=%s
          AND decision.migration_item_id=%s
          AND decision.migration_validation_id=%s
          AND decision.decision='APPROVE'
          AND decision.source_hash=%s
          AND decision.target_asset_version_id=%s
          AND decision.validation_result_hash=%s
          AND decision.expected_item_version=validation.item_version
          AND validation.migration_run_id=decision.migration_run_id
          AND validation.migration_item_id=decision.migration_item_id
          AND validation.source_hash=decision.source_hash
          AND validation.target_asset_version_id=
              decision.target_asset_version_id
          AND validation.result_hash=decision.validation_result_hash
          AND validation.validator_version=%s
          AND validation.status='PASS'
          AND item.migration_run_id=decision.migration_run_id
          AND item.project_id=%s
          AND item.workspace_id=%s
          AND item.source_hash=decision.source_hash
          AND item.target_asset_version_id=decision.target_asset_version_id
          AND item.target_content_hash=%s
          AND item.operation_id=%s
          AND item.status='QUALIFIED'
          AND item.item_version=decision.expected_item_version+1
        FOR SHARE OF decision, validation, item
        """,
        [
            identity["migration_decision_id"],
            identity["migration_run_id"],
            identity["migration_item_id"],
            identity["migration_validation_id"],
            identity["source_hash"],
            target_asset_version_id,
            identity["validator_result_hash"],
            identity["validator_version"],
            project_id,
            workspace_id,
            target_content_hash,
            identity["legacy_import_operation_id"],
        ],
    )
    row = cursor.fetchone()
    if row is None or not all(str(value or "") for value in row):
        raise KernelError(
            "LEGACY_MIGRATION_LINEAGE_INVALID",
            "legacy activation approval or validation lineage is missing, stale, or outside scope",
        )
    return {
        **identity,
        "decision_operation_id": str(row[0]),
        "validation_operation_id": str(row[1]),
        "import_operation_id": str(row[2]),
        "target_asset_version_id": target_asset_version_id,
        "target_content_hash": target_content_hash,
    }


__all__ = ["require_approved_legacy_migration_lineage"]
