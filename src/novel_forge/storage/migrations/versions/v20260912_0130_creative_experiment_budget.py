from __future__ import annotations

MIGRATION_ID = "20260912_0130_creative_experiment_budget"
DOWN_REVISION = "20260912_0129_corpus_member_fk_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append experiment authorization policies; retain immutable allocations and Effect budget bindings"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_runtime_policy_version DROP CONSTRAINT authority_runtime_policy_version_owner_check",
    "ALTER TABLE authority_runtime_policy_version ADD CONSTRAINT authority_runtime_policy_version_owner_check CHECK (owner IN ('CHAPTER_GROUP_EXECUTION', 'READER_PROXY', 'BOOK_CONTROL', 'CREATIVE_EXPERIMENT_BUDGET'))",
    """CREATE FUNCTION preserve_creative_budget_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.evidence ? 'creative_experiment' AND
         NEW.evidence->'creative_experiment' IS DISTINCT FROM OLD.evidence->'creative_experiment' THEN
        RAISE EXCEPTION 'the Effect creative experiment budget binding is immutable';
      END IF;
      RETURN NEW;
    END $$""",
    """CREATE TRIGGER authority_budget_creative_binding_immutable
    BEFORE UPDATE ON authority_budget_reservation
    FOR EACH ROW EXECUTE FUNCTION preserve_creative_budget_evidence()""",
]
