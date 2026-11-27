from __future__ import annotations

MIGRATION_ID = "20260713_0016_asset_blob_protocol"
DOWN_REVISION = "20260713_0015_stale_command_evidence"

BLOB_STATES = (
    "PENDING_UPLOAD",
    "UPLOADING",
    "UPLOADED",
    "VERIFYING",
    "VERIFIED",
    "AVAILABLE",
    "FAILED",
    "ABANDONED",
    "CORRUPT",
    "QUARANTINED",
    "RECONCILIATION_REQUIRED",
    "DELETE_PENDING",
    "DELETED",
)

EFFECT_STATES = (
    "REQUESTED",
    "DISPATCHABLE",
    "IN_FLIGHT",
    "PLANNED",
    "READY",
    "DISPATCHING",
    "DISPATCHED",
    "ACKNOWLEDGED",
    "SUCCEEDED",
    "FAILED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "UNKNOWN",
    "RECONCILIATION_REQUIRED",
    "CANCELLATION_REQUESTED",
    "CANCELLED",
    "COMPENSATION_REQUIRED",
    "COMPENSATED",
)

DISPATCH_STATES = (
    "CREATED",
    "LEASED",
    "DISPATCHING",
    "SENT",
    "ACKNOWLEDGED",
    "SUCCEEDED",
    "FAILED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "TIMED_OUT",
    "UNKNOWN",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "SUPERSEDED",
    "DEAD_LETTER",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_blob DROP CONSTRAINT authority_blob_status_check",
    f"ALTER TABLE authority_blob ADD CONSTRAINT authority_blob_status_check CHECK (status IN ({_sql_values(BLOB_STATES)}))",
    "ALTER TABLE authority_external_effect DROP CONSTRAINT authority_external_effect_status_check",
    f"ALTER TABLE authority_external_effect ADD CONSTRAINT authority_external_effect_status_check CHECK (status IN ({_sql_values(EFFECT_STATES)}))",
    "ALTER TABLE authority_external_effect_dispatch DROP CONSTRAINT authority_external_effect_dispatch_status_check",
    f"ALTER TABLE authority_external_effect_dispatch ADD CONSTRAINT authority_external_effect_dispatch_status_check CHECK (status IN ({_sql_values(DISPATCH_STATES)}))",
    "ALTER TABLE authority_blob ADD COLUMN provider TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_blob ADD COLUMN media_type TEXT NOT NULL DEFAULT 'application/octet-stream'",
    "ALTER TABLE authority_blob ADD COLUMN upload_effect_id TEXT REFERENCES authority_external_effect(external_effect_id)",
    "ALTER TABLE authority_blob ADD COLUMN actual_object_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_blob ADD COLUMN receipt_provider TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_blob ADD CONSTRAINT authority_blob_media_type_check CHECK (media_type ~ '^[a-z0-9.+-]+/[a-z0-9.+-]+$')",
    "ALTER TABLE authority_external_effect ADD COLUMN request_payload JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE authority_external_effect_dispatch ADD COLUMN provider TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_external_receipt ADD COLUMN payload JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CREATE UNIQUE INDEX authority_effect_stable_key_unique ON authority_external_effect(effect_type, stable_idempotency_key)",
    "CREATE INDEX authority_blob_upload_effect_idx ON authority_blob(upload_effect_id) WHERE upload_effect_id IS NOT NULL",
    "ALTER TABLE authority_asset_qualification ADD CONSTRAINT authority_asset_qualification_decision_check CHECK (decision IN ('ELIGIBLE', 'INELIGIBLE', 'REVOKED'))",
]

DOWNGRADE_STATEMENTS: list[str] = []
