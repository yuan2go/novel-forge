from __future__ import annotations

MIGRATION_ID = "20261006_0152_validation_realization_admission"
DOWN_REVISION = "20261006_0151_creative_design_admission"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "preserve historical qualification and proof identities; validation successors use ADMITTED"
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_narrative_realization DROP CONSTRAINT authority_narrative_realization_lifecycle_check",
    """ALTER TABLE authority_narrative_realization ADD CONSTRAINT authority_narrative_realization_lifecycle_check
        CHECK (lifecycle IN ('PROPOSED','ADMITTED','QUALIFIED','APPROVED','FROZEN','EXECUTED','REJECTED','STALE','SUPERSEDED'))""",
    """ALTER TABLE authority_narrative_realization ADD CONSTRAINT authority_realization_admission_proof_check
        CHECK (lifecycle<>'ADMITTED' OR (proof->>'schema_version'='narrative-realization-proof.v3'
            AND proof #>> '{design_admission,mode}'='CREATIVE_VALIDATION'
            AND proof #>> '{design_admission,literary_qualification}'='NOT_RUN') IS TRUE)""",
]
DOWNGRADE_STATEMENTS: list[str] = []
