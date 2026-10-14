from __future__ import annotations

import hashlib
import json

import pytest

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS
from novel_forge.storage.migrations.runner import pending_migrations


def test_published_main_migration_bodies_remain_exact():
    records = [
        {
            "migration_id": migration.migration_id,
            "down_revision": migration.down_revision,
            "upgrade_statements": migration.upgrade_statements,
            "downgrade_statements": migration.downgrade_statements,
            "strategy": migration.strategy,
            "preflight_statements": migration.preflight_statements,
            "forward_fix": migration.forward_fix,
            "backup_required": migration.backup_required,
        }
        for migration in MIGRATIONS[:169]
    ]
    assert MIGRATIONS[168].migration_id == "20261007_0168_derived_step_revalidation"
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == "610c8feff8e8e2354af141daf0853932927e938153ff4d94ba0d34f76834a275"


def test_registered_forward_upgrade_uses_one_continuous_identity_chain():
    published = {migration.migration_id for migration in MIGRATIONS[:169]}
    pending = pending_migrations(published)
    assert pending == list(MIGRATIONS[169:])
    assert pending[-1].migration_id == LATEST_MIGRATION_ID
    assert all(current.down_revision == prior.migration_id for prior, current in zip(pending, pending[1:]))
    assert pending[0].down_revision == "20261007_0168_derived_step_revalidation"


@pytest.mark.parametrize("source_identity", [
    "20261007_0160_world_agency_contract_successor",
    "20261007_0163_failed_step_successor",
    "20261007_0166_retained_graph_continuation",
    "20261007_0169_quality_correction_control",
])
def test_source_branch_identity_cannot_enter_published_migration_history(source_identity):
    with pytest.raises(ValueError, match="MIGRATION_HISTORY_FOREIGN"):
        pending_migrations({migration.migration_id for migration in MIGRATIONS[:169]} | {source_identity})
