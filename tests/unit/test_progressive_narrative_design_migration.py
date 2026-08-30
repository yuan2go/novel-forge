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
from novel_forge.storage.migrations.versions import (
    v20260820_0093_book_liveness_critical_path_closure as liveness,
)
from novel_forge.storage.migrations.versions import (
    v20260820_0094_industrial_autonomous_novel_os as novel_os,
)
from novel_forge.storage.migrations.versions import (
    v20260821_0095_post_merge_correctness_repair as repair,
)
from novel_forge.storage.migrations.versions import (
    v20260821_0096_runtime_hardening as runtime_hardening,
)
from novel_forge.storage.migrations.versions import (
    v20260824_0097_narrative_evaluator_codex_lineage as codex_lineage,
    v20260825_0098_narrative_evolution_engine as evolution,
    v20260825_0099_creative_engineering_convergence as convergence,
    v20260825_0100_hierarchy_closure as hierarchy_closure,
    v20260826_0101_quality_qualification as quality_qualification,
    v20260828_0102_book_opening_recovery_closure as recovery_closure,
    v20260829_0103_book_opening_semantic_runtime_hardening as semantic_hardening,
)


def test_progressive_narrative_design_is_forward_only_head() -> None:
    validate_migration_chain()

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert current_head.DOWN_REVISION == migration.MIGRATION_ID
    assert completion.DOWN_REVISION == current_head.MIGRATION_ID
    assert correctness.DOWN_REVISION == completion.MIGRATION_ID
    assert liveness.DOWN_REVISION == correctness.MIGRATION_ID
    assert novel_os.DOWN_REVISION == liveness.MIGRATION_ID
    assert repair.DOWN_REVISION == novel_os.MIGRATION_ID
    assert runtime_hardening.DOWN_REVISION == repair.MIGRATION_ID
    assert codex_lineage.DOWN_REVISION == runtime_hardening.MIGRATION_ID
    assert evolution.DOWN_REVISION == codex_lineage.MIGRATION_ID
    assert convergence.DOWN_REVISION == evolution.MIGRATION_ID
    assert hierarchy_closure.DOWN_REVISION == convergence.MIGRATION_ID
    assert quality_qualification.DOWN_REVISION == hierarchy_closure.MIGRATION_ID
    assert recovery_closure.DOWN_REVISION == quality_qualification.MIGRATION_ID
    assert semantic_hardening.DOWN_REVISION == recovery_closure.MIGRATION_ID
    assert LATEST_MIGRATION_ID == "20260830_0105_p0_backend_qualification_repairs"
    sql = "\n".join(migration.UPGRADE_STATEMENTS)
    assert "CREATE TABLE authority_narrative_design_qualification" in sql
    assert "LONGFORM_DESIGN_QUALIFIED" in sql
    assert "design_qualification_hash" in sql
    assert "authority_current_narrative_design_qualification" in sql
    assert "novel_forge_reject_immutable_mutation" in sql
    scope_sql = "\n".join(current_head.UPGRADE_STATEMENTS)
    assert "'ARC_SEGMENT'" in scope_sql
    assert "'NARRATIVE_SEGMENT'" in scope_sql
