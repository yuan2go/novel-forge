from __future__ import annotations

from .v20261014_0205_source_observation_generation_isolation import UPGRADE_STATEMENTS as SOURCE_STATEMENTS

MIGRATION_ID = "20261015_0213_source_method_isolation"
DOWN_REVISION = "20261014_0212_prose_citation_revalidation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append the preserved Source method isolation contract without changing main or craft migration history."

UPGRADE_STATEMENTS = list(SOURCE_STATEMENTS)
DOWNGRADE_STATEMENTS: list[str] = []
