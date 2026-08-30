from __future__ import annotations


MIGRATION_ID = "20260830_0105_p0_backend_qualification_repairs"
DOWN_REVISION = "20260829_0104_book_opening_workflow_nodes"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "apply the complete left-prefix indexes for every foreign key introduced "
    "by the 0104 Book Opening workflow migration"
)


UPGRADE_STATEMENTS = [
    "SET CONSTRAINTS ALL IMMEDIATE",
    """
    CREATE INDEX authority_bo_legacy_entitlement_snapshot_fk_idx
    ON authority_book_opening_legacy_snapshot_entitlement(
        snapshot_id,project_id,workspace_id,book_id,snapshot_hash
    )
    """,
    """
    CREATE INDEX authority_bo_node_receipt_checkpoint_fk_idx
    ON authority_book_opening_node_receipt(
        opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
    )
    """,
    """
    CREATE INDEX authority_bo_transition_source_receipt_fk_idx
    ON authority_book_opening_workflow_transition_receipt(
        opening_run_id,source_node_receipt_id
    )
    """,
    """
    CREATE INDEX authority_bo_snapshot_binding_receipt_fk_idx
    ON authority_book_opening_input_snapshot_binding(
        opening_run_id,node_receipt_id
    )
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
