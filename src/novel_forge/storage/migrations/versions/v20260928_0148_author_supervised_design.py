from __future__ import annotations

MIGRATION_ID = "20260928_0148_author_supervised_design"
DOWN_REVISION = "20260927_0147_runtime_job_dispatch_pause"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain frozen strict and supervised snapshots; repair policy in a successor version without relabelling qualification"
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_book_production_input_snapshot DROP CONSTRAINT authority_book_production_design_admission_check",
    """ALTER TABLE authority_book_production_input_snapshot ADD CONSTRAINT authority_book_production_design_admission_check
        CHECK (design_admission_status IN ('LEGACY_UNQUALIFIED','LONGFORM_DESIGN_QUALIFIED','AUTHOR_SUPERVISED_DESIGN'))""",
]
DOWNGRADE_STATEMENTS: list[str] = []
