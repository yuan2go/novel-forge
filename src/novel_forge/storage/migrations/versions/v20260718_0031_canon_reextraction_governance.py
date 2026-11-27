from __future__ import annotations

MIGRATION_ID = "20260718_0031_canon_reextraction_governance"
DOWN_REVISION = "20260718_0030_provider_callback_authority"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_canon_reextraction_generation DROP CONSTRAINT authority_canon_reextraction_generation_status_check",
    "ALTER TABLE authority_canon_reextraction_generation ADD CONSTRAINT authority_canon_reextraction_generation_status_check CHECK (status IN ('REEXTRACTION_PENDING','EXTRACTION_RUNNING','PROPOSAL_PENDING','PROPOSAL_RUNNING','WAITING_APPROVAL','WAITING_OPERATOR','RESOLVED','CANCELLED'))",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN policy_snapshot JSONB NOT NULL DEFAULT '{\"policy_version\":\"canon-reextraction-policy-v1\",\"maximum_generations\":3,\"maximum_total_cost\":\"5.00\",\"generation_timeout_seconds\":900,\"same_digest_limit\":2,\"no_progress_limit\":2,\"operator_escalation_after\":2}'::jsonb",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN deadline_at TIMESTAMPTZ",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN extraction_digest TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN proposal_digest TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN change_set_digest TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN conflict_set_digest TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN no_progress_count INTEGER NOT NULL DEFAULT 0 CHECK (no_progress_count >= 0)",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN estimated_cost NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0)",
    "ALTER TABLE authority_canon_reextraction_generation ADD COLUMN escalation_reason TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX authority_canon_reextraction_deadline_idx ON authority_canon_reextraction_generation(status, deadline_at) WHERE status NOT IN ('RESOLVED','CANCELLED')",
]

DOWNGRADE_STATEMENTS: list[str] = []
