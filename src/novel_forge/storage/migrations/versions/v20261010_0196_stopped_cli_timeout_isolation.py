from __future__ import annotations

from .v20261009_0195_prose_review_generation_isolation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261010_0196_stopped_cli_timeout_isolation"
DOWN_REVISION = "20261009_0195_prose_review_generation_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit identity-bound stopped CLI timeout history through native pure-generation isolation without rewriting the failed attempt or unknown usage."

UPGRADE_STATEMENTS = [
    PREVIOUS[1].replace(
        "e.status IN ('UNKNOWN','RECONCILIATION_REQUIRED')",
        """(e.status IN ('UNKNOWN','RECONCILIATION_REQUIRED') OR (
          e.status='FAILED_RETRYABLE' AND NEW.proof->>'stopped_legacy_cli'='true'
          AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch
            JOIN authority_attempt attempt ON attempt.attempt_id=dispatch.evidence#>>'{production_execution,execution_result,attempt_id}'
            JOIN authority_asset_version receipt ON receipt.asset_version_id=NEW.proof->>'evidence_asset_version_id'
            JOIN authority_asset receipt_owner ON receipt_owner.asset_id=receipt.asset_id
            WHERE dispatch.external_effect_id=e.external_effect_id AND dispatch.status='FAILED_RETRYABLE'
            AND dispatch.payload_hash=e.request_hash
            AND NEW.proof->'dispatch_ids' ? dispatch.dispatch_id
            AND dispatch.evidence#>>'{production_execution,execution_handle,transport}'='LOCAL_CLI_REMOTE_INFERENCE'
            AND dispatch.evidence#>>'{production_execution,execution_result,outcome}' IN ('UNKNOWN','TIMED_OUT','CANCELLED','ORPHANED')
            AND NULLIF(dispatch.evidence#>>'{production_execution,execution_result,started_at}','') IS NOT NULL
            AND NULLIF(dispatch.evidence#>>'{production_execution,execution_result,usage_receipt_ref}','') IS NULL
            AND dispatch.evidence#>>'{production_execution,execution_result,process_receipt_ref}'='authority-asset-version:'||receipt.asset_version_id
            AND attempt.operation_id=o.operation_id AND attempt.status='FAILED_RETRYABLE'
            AND receipt_owner.project_id=NEW.project_id AND receipt_owner.asset_type='execution_evidence'
            AND receipt.eligibility='ELIGIBLE' AND receipt.governance='CLEAR'
            AND COALESCE(receipt.content->'payload',receipt.content)->>'operation_id'=o.operation_id
            AND COALESCE(receipt.content->'payload',receipt.content)->>'status' IN ('FAILED','TIMED_OUT','ORPHANED','CANCELLED')
            AND COALESCE(receipt.content->'payload',receipt.content)->>'result_integrity'<>'VALID')))""",
    ),
]
DOWNGRADE_STATEMENTS: list[str] = []
