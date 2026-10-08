import hashlib
import json

from novel_forge.storage.migrations import MIGRATIONS


def test_all_published_main_migration_bodies_remain_exact():
    records = [
        {
            'migration_id': migration.migration_id,
            'down_revision': migration.down_revision,
            'upgrade_statements': migration.upgrade_statements,
            'downgrade_statements': migration.downgrade_statements,
            'strategy': migration.strategy,
            'preflight_statements': migration.preflight_statements,
            'forward_fix': migration.forward_fix,
            'backup_required': migration.backup_required,
        }
        for migration in MIGRATIONS[:184]
    ]
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == '89f90f627a8e8aef74d68bdfc0aed07d9438eb12b3177fa2960cf987ef5241ed'
