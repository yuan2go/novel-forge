from __future__ import annotations


MIGRATION_ID = "20260811_0074_longform_native_intelligence"
DOWN_REVISION = "20260806_0073_core_functional_loops"
FORWARD_ONLY = True
FORWARD_FIX = (
    "repair invalid Chapter acceptance or output qualification through its owning "
    "Authority, then rebuild the read projection"
)


_ACCEPTED_OUTPUT_SCOPE = """
    FROM authority_book_chapter_acceptance AS acceptance
    JOIN authority_book_production AS production
      ON production.book_run_id=acceptance.book_run_id
     AND production.project_id=acceptance.project_id
    JOIN authority_child_delegation AS delegation
      ON delegation.delegation_id=acceptance.delegation_id
     AND delegation.project_id=acceptance.project_id
     AND delegation.owner_id=acceptance.book_run_id
    JOIN authority_operation AS operation
      ON operation.root_operation_id=delegation.child_root_operation_id
     AND operation.project_id=acceptance.project_id
     AND operation.status='SUCCEEDED'
    JOIN authority_operation_output_asset AS binding
      ON binding.operation_id=operation.operation_id
    JOIN authority_asset AS asset
      ON asset.asset_id=binding.asset_id
     AND asset.project_id=acceptance.project_id
    JOIN authority_asset_version AS version
      ON version.asset_version_id=binding.asset_version_id
     AND version.asset_id=asset.asset_id
     AND version.lifecycle IN ('ACTIVE', 'SUPERSEDED')
     AND version.eligibility='ELIGIBLE'
     AND version.governance='CLEAR'
    LEFT JOIN LATERAL (
        SELECT qualification.decision
        FROM authority_asset_qualification AS qualification
        WHERE qualification.asset_version_id=version.asset_version_id
        ORDER BY qualification.created_at DESC, qualification.qualification_id DESC
        LIMIT 1
    ) AS latest_qualification ON TRUE
"""


UPGRADE_STATEMENTS = [
    f"""
    CREATE VIEW authority_temporal_state_event_projection AS
    SELECT acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           operation.operation_id,
           operation.trace_id,
           acceptance.chapter_number AS accepted_chapter,
           version.content->>'state_kind' AS state_kind,
           asset.asset_type,
           version.asset_version_id,
           change.payload,
           change.event_ordinal,
           binding.created_at AS recorded_at
    {_ACCEPTED_OUTPUT_SCOPE}
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(version.content->'changes')='array'
            THEN version.content->'changes'
            ELSE '[]'::jsonb
        END
    ) WITH ORDINALITY AS change(payload, event_ordinal)
    WHERE acceptance.status='COMMITTED'
      AND delegation.status='ACCEPTED'
      AND binding.role='state_snapshot'
      AND COALESCE(version.content->>'project_id', acceptance.project_id)
          = acceptance.project_id
      AND COALESCE(version.content->>'state_kind', '') <> ''
      AND COALESCE(latest_qualification.decision, 'ELIGIBLE')='ELIGIBLE'
    """,
    f"""
    CREATE VIEW authority_longform_observation_projection AS
    SELECT acceptance.project_id,
           production.book_id,
           acceptance.book_run_id,
           acceptance.acceptance_id,
           acceptance.chapter_number AS accepted_chapter,
           asset.asset_type,
           version.asset_version_id,
           binding.output_key,
           version.content,
           binding.created_at AS recorded_at
    {_ACCEPTED_OUTPUT_SCOPE}
    WHERE acceptance.status='COMMITTED'
      AND delegation.status='ACCEPTED'
      AND binding.role='longform_observation'
      AND COALESCE(version.content->>'project_id', acceptance.project_id)
          = acceptance.project_id
      AND COALESCE(latest_qualification.decision, 'ELIGIBLE')='ELIGIBLE'
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
