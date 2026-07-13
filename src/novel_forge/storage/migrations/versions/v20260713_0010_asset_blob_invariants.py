from __future__ import annotations

MIGRATION_ID = "20260713_0010_asset_blob_invariants"
DOWN_REVISION = "20260713_0009_attempt_lease_invariants"

ASSET_LIFECYCLE_STATES = ("DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED", "DELETED")
ASSET_ELIGIBILITY_STATES = ("PENDING_EVALUATION", "ELIGIBLE", "INELIGIBLE", "REVOKED")
ASSET_GOVERNANCE_STATES = ("CLEAR", "QUARANTINED", "REJECTED", "LEGAL_HOLD")
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
    "DELETE_PENDING",
    "DELETED",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


UPGRADE_STATEMENTS = [
    f"""
    ALTER TABLE authority_asset_version
    ADD CONSTRAINT authority_asset_version_lifecycle_check
    CHECK (lifecycle IN ({_sql_values(ASSET_LIFECYCLE_STATES)}))
    """,
    f"""
    ALTER TABLE authority_asset_version
    ADD CONSTRAINT authority_asset_version_eligibility_check
    CHECK (eligibility IN ({_sql_values(ASSET_ELIGIBILITY_STATES)}))
    """,
    f"""
    ALTER TABLE authority_asset_version
    ADD CONSTRAINT authority_asset_version_governance_check
    CHECK (governance IN ({_sql_values(ASSET_GOVERNANCE_STATES)}))
    """,
    "ALTER TABLE authority_blob ADD COLUMN project_id TEXT",
    "UPDATE authority_blob SET project_id = '__legacy_unscoped__' WHERE project_id IS NULL",
    "ALTER TABLE authority_blob ALTER COLUMN project_id SET NOT NULL",
    f"""
    ALTER TABLE authority_blob
    ADD CONSTRAINT authority_blob_status_check
    CHECK (status IN ({_sql_values(BLOB_STATES)}))
    """,
    """
    ALTER TABLE authority_blob
    ADD CONSTRAINT authority_blob_size_check
    CHECK (
        expected_size >= 0
        AND (actual_size IS NULL OR actual_size >= 0)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_guard_asset_version_mutation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF OLD.lifecycle = 'ACTIVE'
           AND (
               OLD.asset_id IS DISTINCT FROM NEW.asset_id
               OR OLD.version_number IS DISTINCT FROM NEW.version_number
               OR OLD.content IS DISTINCT FROM NEW.content
               OR OLD.content_hash IS DISTINCT FROM NEW.content_hash
           ) THEN
            RAISE EXCEPTION 'ACTIVE asset version content is immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_active_asset_version_immutable';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_asset_version_mutation_guard
    BEFORE UPDATE ON authority_asset_version
    FOR EACH ROW
    EXECUTE FUNCTION authority_guard_asset_version_mutation()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_guard_asset_activation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF NEW.lifecycle = 'ACTIVE'
           AND EXISTS (
               SELECT 1
               FROM authority_asset_version_blob_reference AS reference
               JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
               WHERE reference.asset_version_id = NEW.asset_version_id
                 AND blob.status <> 'AVAILABLE'
           ) THEN
            RAISE EXCEPTION 'asset version references a Blob that is not AVAILABLE'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_asset_activation_available_blob';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_asset_activation_guard
    BEFORE INSERT OR UPDATE OF lifecycle ON authority_asset_version
    FOR EACH ROW
    EXECUTE FUNCTION authority_guard_asset_activation()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_guard_blob_reference()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        asset_project_id TEXT;
        blob_project_id TEXT;
        blob_status TEXT;
        blob_hash TEXT;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'BlobReference is immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_blob_reference_immutable';
        END IF;

        SELECT asset.project_id
        INTO asset_project_id
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
        WHERE version.asset_version_id = NEW.asset_version_id;

        SELECT project_id, status, actual_hash
        INTO blob_project_id, blob_status, blob_hash
        FROM authority_blob
        WHERE blob_id = NEW.blob_id;

        IF asset_project_id IS NOT NULL
           AND blob_project_id IS NOT NULL
           AND asset_project_id <> blob_project_id THEN
            RAISE EXCEPTION 'BlobReference crosses project boundary'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_blob_reference_project_check';
        END IF;

        IF blob_status IS NOT NULL AND blob_status <> 'AVAILABLE' THEN
            RAISE EXCEPTION 'only AVAILABLE Blob can be referenced'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_blob_reference_available_check';
        END IF;

        IF blob_hash IS NOT NULL AND NEW.content_hash <> blob_hash THEN
            RAISE EXCEPTION 'BlobReference content hash does not match Blob evidence'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_blob_reference_hash_check';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_blob_reference_guard
    BEFORE INSERT OR UPDATE OR DELETE
    ON authority_asset_version_blob_reference
    FOR EACH ROW
    EXECUTE FUNCTION authority_guard_blob_reference()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_guard_blob_deletion()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        deletion_requested BOOLEAN;
        target_blob_id TEXT;
    BEGIN
        target_blob_id := OLD.blob_id;
        deletion_requested := TG_OP = 'DELETE';
        IF TG_OP <> 'DELETE' THEN
            deletion_requested := NEW.status IN ('DELETE_PENDING', 'DELETED');
        END IF;

        IF NOT deletion_requested THEN
            RETURN NEW;
        END IF;

        IF OLD.legal_hold THEN
            RAISE EXCEPTION 'Legal Hold Blob cannot be deleted'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_blob_legal_hold_delete_check';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM authority_asset_version_blob_reference
            WHERE blob_id = target_blob_id
        ) THEN
            RAISE EXCEPTION 'referenced Blob cannot be deleted'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'authority_blob_reference_delete_check';
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_blob_deletion_guard
    BEFORE UPDATE OF status OR DELETE ON authority_blob
    FOR EACH ROW
    EXECUTE FUNCTION authority_guard_blob_deletion()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_asset_version_is_production_eligible(
        p_asset_version_id TEXT
    )
    RETURNS BOOLEAN
    LANGUAGE sql
    STABLE
    AS $$
        SELECT EXISTS (
            SELECT 1
            FROM authority_asset_version AS version
            WHERE version.asset_version_id = p_asset_version_id
              AND version.lifecycle = 'ACTIVE'
              AND version.eligibility = 'ELIGIBLE'
              AND version.governance = 'CLEAR'
              AND NOT EXISTS (
                  SELECT 1
                  FROM authority_asset_version_blob_reference AS reference
                  JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
                  WHERE reference.asset_version_id = version.asset_version_id
                    AND blob.status <> 'AVAILABLE'
              )
        )
    $$
    """,
    "CREATE INDEX authority_blob_project_status_idx ON authority_blob(project_id, status)",
    "CREATE INDEX authority_blob_reference_blob_idx ON authority_asset_version_blob_reference(blob_id)",
]

DOWNGRADE_STATEMENTS: list[str] = []
