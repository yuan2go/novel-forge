from __future__ import annotations


MIGRATION_ID = "20260905_0113_policy_completion_fk_indexes"
DOWN_REVISION = "20260905_0112_realization_execution_policy"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "retain policy and completion foreign keys; append missing supporting indexes"


UPGRADE_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS authority_completion_case_workspace_idx ON authority_book_completion_case(workspace_id)",
    "CREATE INDEX IF NOT EXISTS authority_completion_decision_source_idx ON authority_book_completion_decision(case_id, source_digest)",
    "CREATE INDEX IF NOT EXISTS authority_completion_decision_closure_idx ON authority_book_completion_decision(closure_evidence_id)",
    "CREATE INDEX IF NOT EXISTS authority_completion_decision_quality_idx ON authority_book_completion_decision(quality_decision_id)",
    "CREATE INDEX IF NOT EXISTS authority_completion_source_canon_idx ON authority_book_completion_source(canon_version_id)",
    "CREATE INDEX IF NOT EXISTS authority_completion_source_outcome_idx ON authority_book_completion_source(outcome_version_id)",
    "CREATE INDEX IF NOT EXISTS authority_completion_source_state_idx ON authority_book_completion_source(story_state_version_id)",
    "CREATE INDEX IF NOT EXISTS authority_policy_binding_version_idx ON authority_runtime_policy_binding(owner, project_id, policy_version)",
    "CREATE INDEX IF NOT EXISTS authority_policy_selection_version_idx ON authority_runtime_policy_selection(owner, project_id, policy_version)",
    "CREATE INDEX IF NOT EXISTS authority_policy_selection_operation_idx ON authority_runtime_policy_selection(selected_by_operation_id)",
    "CREATE INDEX IF NOT EXISTS authority_policy_version_operation_idx ON authority_runtime_policy_version(created_by_operation_id)",
]
