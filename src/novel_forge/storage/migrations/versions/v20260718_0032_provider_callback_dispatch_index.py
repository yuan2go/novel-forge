from __future__ import annotations

MIGRATION_ID = "20260718_0032_provider_callback_dispatch_index"
DOWN_REVISION = "20260718_0031_canon_reextraction_governance"

UPGRADE_STATEMENTS = [
    "CREATE INDEX authority_provider_callback_receipt_dispatch_idx ON authority_provider_callback_receipt(dispatch_id) WHERE dispatch_id IS NOT NULL",
]

DOWNGRADE_STATEMENTS: list[str] = []
