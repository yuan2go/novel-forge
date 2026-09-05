from __future__ import annotations

MIGRATION_ID = "20260905_0109_chapter_window_execution_policy"
DOWN_REVISION = "20260903_0108_context_governance_projection"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append a replacement execution window; never change a frozen policy or accepted history"

UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_chapter_group_production
      DROP CONSTRAINT authority_chapter_group_production_check1,
      ADD COLUMN window_policy JSONB,
      ADD COLUMN window_policy_digest TEXT
    """,
    """
    UPDATE authority_chapter_group_production
      SET window_policy='{"maximum_chapters":8,"policy_id":"chapter-window","schema_version":"chapter-window-policy.v1","version":"legacy-three-to-eight"}'::jsonb,
          window_policy_digest='sha256:d364017b3e27d7daec6f39a18494c4174dc49c9a1b942a0baa627786882d683d'
    """,
    """
    ALTER TABLE authority_chapter_group_production
      ALTER COLUMN window_policy SET NOT NULL,
      ALTER COLUMN window_policy_digest SET NOT NULL,
      ADD CONSTRAINT chapter_window_policy_contract CHECK (
        jsonb_typeof(window_policy)='object'
        AND window_policy->>'schema_version'='chapter-window-policy.v1'
        AND COALESCE(window_policy->>'policy_id','')<>''
        AND COALESCE(window_policy->>'version','')<>''
        AND COALESCE(window_policy->>'maximum_chapters','') ~ '^[1-9][0-9]*$'
        AND chapter_end - chapter_start + 1 <= (window_policy->>'maximum_chapters')::integer
        AND window_policy_digest=authority_sha256_jsonb(window_policy)
        AND window_policy ?& ARRAY['schema_version','policy_id','version','maximum_chapters']
        AND window_policy - ARRAY['schema_version','policy_id','version','maximum_chapters']='{}'::jsonb
      )
    """,
    """
    CREATE FUNCTION nf_guard_chapter_window_policy() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
      admitted_policy JSONB;
      admitted_payload JSONB;
      frozen_range JSONB;
    BEGIN
      IF TG_OP='INSERT' THEN
        SELECT operation.command_payload->'payload', version.content->'chapter_range'
          INTO admitted_payload, frozen_range
        FROM authority_operation AS operation
        JOIN authority_asset_version AS version
          ON version.asset_version_id=NEW.group_plan_version_id
         AND version.content_hash=operation.command_payload->'payload'->>'group_plan_content_hash'
        WHERE operation.operation_id=NEW.root_operation_id
          AND operation.project_id=NEW.project_id
          AND operation.definition_name='chapter_group.production.run'
          AND operation.idempotency_scope='project:chapter-group-production'
          AND operation.idempotency_key=NEW.stable_idempotency_key
          AND operation.command_payload->'payload'->>'book_run_id'=NEW.book_run_id
          AND operation.command_payload->'payload'->>'group_plan_version_id'=NEW.group_plan_version_id;
        IF admitted_payload IS NULL OR frozen_range IS DISTINCT FROM jsonb_build_array(NEW.chapter_start,NEW.chapter_end) THEN
          RAISE EXCEPTION 'execution window differs from admitted frozen plan'
            USING ERRCODE='23514', CONSTRAINT='chapter_window_admission_scope';
        END IF;
        admitted_policy=admitted_payload->'window_policy';
        IF admitted_policy IS NULL THEN
          admitted_policy='{"maximum_chapters":8,"policy_id":"chapter-window","schema_version":"chapter-window-policy.v1","version":"legacy-three-to-eight"}'::jsonb;
          IF NEW.chapter_end-NEW.chapter_start+1 NOT BETWEEN 3 AND 8 THEN
            RAISE EXCEPTION 'historical execution window must preserve its original range policy'
              USING ERRCODE='23514', CONSTRAINT='chapter_window_legacy_policy';
          END IF;
        END IF;
        IF NEW.window_policy IS DISTINCT FROM admitted_policy
           OR NEW.window_policy_digest IS DISTINCT FROM authority_sha256_jsonb(admitted_policy) THEN
          RAISE EXCEPTION 'execution window policy differs from admitted snapshot'
            USING ERRCODE='23514', CONSTRAINT='chapter_window_admitted_policy';
        END IF;
        RETURN NEW;
      END IF;
      IF (NEW.window_policy, NEW.window_policy_digest, NEW.chapter_start, NEW.chapter_end)
          IS DISTINCT FROM
         (OLD.window_policy, OLD.window_policy_digest, OLD.chapter_start, OLD.chapter_end)
      THEN
        RAISE EXCEPTION 'frozen execution window policy and range are immutable'
          USING ERRCODE='23514', CONSTRAINT='chapter_window_policy_immutable';
      END IF;
      RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER chapter_window_policy_immutable
      BEFORE INSERT OR UPDATE ON authority_chapter_group_production
      FOR EACH ROW EXECUTE FUNCTION nf_guard_chapter_window_policy()
    """,
]

DOWNGRADE_STATEMENTS = []
