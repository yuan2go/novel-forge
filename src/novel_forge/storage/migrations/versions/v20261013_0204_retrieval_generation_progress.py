from __future__ import annotations

MIGRATION_ID = "20261013_0204_retrieval_generation_progress"
DOWN_REVISION = "20261012_0203_capacity_availability_observation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain immutable retrieval evidence while admitting progress beyond old cumulative rounds and preserving unknown accounting in new snapshots."

UPGRADE_STATEMENTS = [
    """ALTER TABLE authority_retrieval_campaign ADD COLUMN final_result JSONB
        CHECK(final_result IS NULL OR final_result->>'result_fingerprint'=final_result_fingerprint)""",
    "ALTER TABLE authority_retrieval_round DROP CONSTRAINT authority_retrieval_round_round_number_check",
    "ALTER TABLE authority_retrieval_round ADD CONSTRAINT authority_retrieval_round_round_number_check CHECK(round_number >= 0)",
    """ALTER TABLE authority_retrieval_round
        ADD COLUMN snapshot_contract_version TEXT NOT NULL DEFAULT 'retrieval-round-snapshot-v1'
        CHECK(snapshot_contract_version IN ('retrieval-round-snapshot-v1','retrieval-round-snapshot-v2'))""",
    *[f"ALTER TABLE authority_retrieval_round ALTER COLUMN {column} DROP NOT NULL, ALTER COLUMN {column} DROP DEFAULT"
      for column in ("input_tokens", "output_tokens", "cost_amount", "latency_ms")],
    "ALTER TABLE authority_retrieval_round ALTER COLUMN currency DROP DEFAULT",
]
DOWNGRADE_STATEMENTS: list[str] = []
