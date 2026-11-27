from __future__ import annotations

MIGRATION_ID = "20261006_0151_creative_design_admission"
DOWN_REVISION = "20261006_0150_creative_pack_admission"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain all frozen admissions; use successor native policy and new execution snapshots"
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_book_production_input_snapshot DROP CONSTRAINT authority_book_production_design_admission_check",
    """ALTER TABLE authority_book_production_input_snapshot ADD CONSTRAINT authority_book_production_design_admission_check
        CHECK (design_admission_status IN ('LEGACY_UNQUALIFIED','LONGFORM_DESIGN_QUALIFIED','AUTHOR_SUPERVISED_DESIGN','CREATIVE_VALIDATION_DESIGN'))""",
]
DOWNGRADE_STATEMENTS: list[str] = []
