from __future__ import annotations

MIGRATION_ID = "20260713_0015_stale_command_evidence"
DOWN_REVISION = "20260713_0014_cancellation_compensation"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_late_result_evidence ADD COLUMN authoritative_attempt_status TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_late_result_evidence ADD COLUMN current_worker_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_late_result_evidence ADD COLUMN current_lease_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_late_result_evidence ADD COLUMN trace_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_late_result_evidence ADD COLUMN correlation_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_late_result_evidence ADD COLUMN causation_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_worker_cancel_signal ADD COLUMN acknowledged_fencing_token BIGINT",
    "ALTER TABLE authority_worker_cancel_signal ADD COLUMN acknowledged_worker_id TEXT NOT NULL DEFAULT ''",
]

DOWNGRADE_STATEMENTS: list[str] = []
