from __future__ import annotations

MIGRATION_ID = "20260920_0137_opening_delete_fence"
DOWN_REVISION = "20260916_0136_provider_routing_policy"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Preserve predecessor fencing and pass unfenced DELETE rows to terminal history guards; no row or contract rewrite."

UPGRADE_STATEMENTS = [
    """
    CREATE OR REPLACE FUNCTION authority_bo_capacity_predecessor_fence()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.capacity_successor_opening_run_id IS NOT NULL THEN
            RAISE EXCEPTION 'BOOK_OPENING_CAPACITY_PREDECESSOR_FENCED'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='DELETE' THEN
            RETURN OLD;
        END IF;
        IF NEW.capacity_successor_opening_run_id IS NOT NULL
          AND (OLD.lifecycle<>'FAILED' OR
               to_jsonb(OLD)-'capacity_successor_opening_run_id'<>
               to_jsonb(NEW)-'capacity_successor_opening_run_id') THEN
            RAISE EXCEPTION 'BOOK_OPENING_CAPACITY_SOURCE_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
]
