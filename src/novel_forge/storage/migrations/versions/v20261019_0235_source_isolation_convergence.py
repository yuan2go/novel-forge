from __future__ import annotations

from .v20261014_0205_source_observation_generation_isolation import _SOURCE
from .v20261018_0224_working_regeneration_isolation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = '20261019_0235_source_isolation_convergence'
DOWN_REVISION = '20261019_0234_settled_preparation_capacity'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Restore the frozen owned Source method isolation branch while preserving current working-regeneration and Book isolation guards.'

_BASE = PREVIOUS[1]
_ACTOR = "AND o.workspace_id=NEW.workspace_id AND o.actor_id=NEW.proof->>'actor_id'"
_BRANCH = "AND ((o.definition_name='story_planning.generate'"
_CONTRACT = "AND NEW.proof->>'contract_version'='pure-generation-isolation.v1'"
assert all(_BASE.count(token) == 1 for token in (_ACTOR, _BRANCH, _CONTRACT))
UPGRADE_STATEMENTS = [_BASE.replace(_ACTOR,
    "AND o.workspace_id=NEW.workspace_id AND (o.actor_id=NEW.proof->>'actor_id' OR (" + _SOURCE + "))")
    .replace(_BRANCH, "AND ((" + _SOURCE + ") OR (o.definition_name='story_planning.generate'")
    .replace(_CONTRACT, "AND (NEW.proof->>'contract_version'='pure-generation-isolation.v1' OR (" + _SOURCE + "))")]
DOWNGRADE_STATEMENTS: list[str] = []
