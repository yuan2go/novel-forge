import pytest
from novel_forge.storage.migrations.runner import MIGRATIONS, pending_migrations


def test_foreign_branch_ledger_rejected_before_returning_pending_ddl():
    applied = {m.migration_id for m in MIGRATIONS}
    applied.add('20261006_0157_planning_result_admission')
    with pytest.raises(ValueError):
        pending_migrations(applied)


def test_hole_ledger_rejected_before_returning_pending_ddl():
    applied = {m.migration_id for m in MIGRATIONS}
    applied.remove(MIGRATIONS[1].migration_id)
    with pytest.raises(ValueError):
        pending_migrations(applied)
