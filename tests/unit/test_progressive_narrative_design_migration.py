from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260814_0088_canonical_narrative_architecture as previous,
)
from novel_forge.storage.migrations.versions import (
    v20260814_0089_progressive_narrative_design as migration,
)
from novel_forge.storage.migrations.versions import (
    v20260814_0090_progressive_replan_scopes as current_head,
)
from novel_forge.storage.migrations.versions import (
    v20260814_0091_canonical_longform_runtime_completion as completion,
)
from novel_forge.storage.migrations.versions import (
    v20260814_0092_longform_correctness_closure as correctness,
)


def test_progressive_narrative_design_is_forward_only_head() -> None:
    validate_migration_chain()

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert current_head.DOWN_REVISION == migration.MIGRATION_ID
    assert completion.DOWN_REVISION == current_head.MIGRATION_ID
    assert correctness.DOWN_REVISION == completion.MIGRATION_ID
    assert LATEST_MIGRATION_ID == correctness.MIGRATION_ID
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    assert "CREATE TABLE authority_narrative_design_qualification" in sql
    assert "LONGFORM_DESIGN_QUALIFIED" in sql
    assert "design_qualification_hash" in sql
    assert "authority_current_narrative_design_qualification" in sql
    assert "novel_forge_reject_immutable_mutation" in sql
    scope_sql = "\n".join(current_head.UPGRADE_STATEMENTS)
    assert "'ARC_SEGMENT'" in scope_sql
    assert "'NARRATIVE_SEGMENT'" in scope_sql
