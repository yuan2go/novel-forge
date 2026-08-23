from __future__ import annotations

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260812_0085_corrective_action_terminal_lineage as previous,
    v20260812_0086_corrective_generation_terminal_lineage as migration,
    v20260813_0087_book_initial_narrative_state_binding as latest,
    v20260814_0088_canonical_narrative_architecture as head,
    v20260814_0089_progressive_narrative_design as progressive,
    v20260814_0090_progressive_replan_scopes as current_head,
    v20260814_0091_canonical_longform_runtime_completion as completion,
    v20260814_0092_longform_correctness_closure as correctness,
    v20260820_0093_book_liveness_critical_path_closure as liveness,
    v20260820_0094_industrial_autonomous_novel_os as novel_os,
    v20260821_0095_post_merge_correctness_repair as repair,
    v20260821_0096_runtime_hardening as runtime_hardening,
)


def test_terminal_lineage_is_a_forward_only_projection_fix() -> None:
    validate_migration_chain()
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert latest.DOWN_REVISION == migration.MIGRATION_ID
    assert head.DOWN_REVISION == latest.MIGRATION_ID
    assert progressive.DOWN_REVISION == head.MIGRATION_ID
    assert current_head.DOWN_REVISION == progressive.MIGRATION_ID
    assert completion.DOWN_REVISION == current_head.MIGRATION_ID
    assert correctness.DOWN_REVISION == completion.MIGRATION_ID
    assert liveness.DOWN_REVISION == correctness.MIGRATION_ID
    assert novel_os.DOWN_REVISION == liveness.MIGRATION_ID
    assert repair.DOWN_REVISION == novel_os.MIGRATION_ID
    assert runtime_hardening.DOWN_REVISION == repair.MIGRATION_ID
    assert LATEST_MIGRATION_ID == runtime_hardening.MIGRATION_ID
    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    assert "MIGRATION_ONLY base projection" in sql
    assert "FAILED_FINAL" in sql
    assert "DEAD_LETTER" in sql
    assert "CANCELLED" in sql
    assert "SUPERSEDED" in sql
    assert "chapter.revision.review" in sql
    assert "chapter.quality.evaluate" in sql
    assert "quality-correction:([0-9]+)$" in sql
    assert "CREATE TABLE" not in sql
