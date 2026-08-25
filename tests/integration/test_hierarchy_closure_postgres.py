from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.authority_postgres_support import transaction
from tests.integration.hierarchy_closure_postgres_support import (
    seed_ready_story_foundation,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _principal,
)


def test_story_formation_is_durable_qualified_and_reference_only() -> None:
    harness = CapabilityPackPostgresHarness("hierarchy-formation")
    project_id = harness.project_id
    book_id = harness.book_ids[0]
    result = seed_ready_story_foundation(
        DATABASE_URL,
        project_id=project_id,
        workspace_id=harness.workspace_id,
        book_id=book_id,
        principal=_principal(project_id),
        target_chapters=6,
        release_sha=RELEASE_SHA,
        full_story_design_lifecycle=True,
        exercise_formation_recovery=True,
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT lifecycle,current_stage,foundation_set_digest,
                   book_design_asset_version_id,book_design_content_hash
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            """,
            [result["formation_run_id"]],
        )
        assert uow.cursor.fetchone() == (
            "READY",
            "COMPLETE",
            result["foundation_set_digest"],
            result["book_design_asset_version_id"],
            result["book_design_content_hash"],
        )
        uow.cursor.execute(
            """
            SELECT stage,status
            FROM authority_story_formation_stage
            WHERE formation_run_id=%s
            ORDER BY created_at,stage
            """,
            [result["formation_run_id"]],
        )
        stages = dict(uow.cursor.fetchall())
        assert stages == {
            "CREATIVE_SEARCH": "ACTIVE",
            "CREATIVE_FOUNDATION": "ACTIVE",
            "THEME_CONTRACT": "ACTIVE",
            "ENDING_INTENT": "ACTIVE",
            "READER_PROMISE": "ACTIVE",
            "WORLD_BIBLE": "ACTIVE",
            "CHARACTER_CAST": "ACTIVE",
            "BOOK_DESIGN": "ACTIVE",
        }
        uow.cursor.execute(
            """
            SELECT COUNT(*),COUNT(DISTINCT foundation_role),
                   COUNT(DISTINCT set_generation)
            FROM authority_book_foundation_binding
            WHERE project_id=%s AND book_id=%s AND freshness='CURRENT'
            """,
            [project_id, book_id],
        )
        assert uow.cursor.fetchone() == (6, 6, 1)
        uow.cursor.execute(
            """
            SELECT lifecycle,qualification,approval,planning_scope
            FROM authority_story_design_version_state
            WHERE project_id=%s
              AND asset_version_id=ANY(%s)
            """,
            [project_id, list(result["asset_versions"].values())],
        )
        design_states = uow.cursor.fetchall()
        assert len(design_states) == 6
        assert set(design_states) == {
            ("ACTIVE", "QUALIFIED", "APPROVED", "NOT_APPLICABLE")
        }
        uow.cursor.execute(
            """
            SELECT content
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [result["book_design_asset_version_id"]],
        )
        book_design = dict(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT status,attempt_count
            FROM authority_runtime_job
            WHERE job_kind='STORY_FORMATION_ADVANCE'
              AND subject_id=%s
            """,
            [result["formation_run_id"]],
        )
        jobs = uow.cursor.fetchall()

    assert book_design["schema_version"] == "book-design.v5"
    assert book_design["foundation_set"]["set_digest"] == result[
        "foundation_set_digest"
    ]
    assert "rules" not in book_design
    assert "characters" not in book_design
    assert result["formation_replayed"] is True
    assert result["formation_recovery_exercised"] is True
    assert jobs and {status for status, _attempts in jobs} == {
        "SUCCEEDED",
        "CANCELLED",
    }
    assert sum(status == "CANCELLED" for status, _attempts in jobs) == 1
    assert all(int(attempts) == 1 for _status, attempts in jobs)

    with pytest.raises(KernelError, match="FOUNDATION_FORMATION_NOT_READY"):
        with transaction() as _connection, _connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_story_formation_run
                SET lifecycle='WAITING_APPROVAL', current_stage='BOOK_DESIGN'
                WHERE formation_run_id=%s
                """,
                [result["formation_run_id"]],
            )
            require_current_foundation_set(
                cursor,
                project_id=project_id,
                book_id=book_id,
                require_ready=True,
            )

    with pytest.raises(KernelError, match="FOUNDATION_SET_MIXED_GENERATION"):
        with transaction() as _connection, _connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_book_foundation_binding
                SET set_generation=set_generation+1
                WHERE project_id=%s AND book_id=%s
                  AND foundation_role='CHARACTER_CAST'
                  AND freshness='CURRENT'
                """,
                [project_id, book_id],
            )
            require_current_foundation_set(
                cursor,
                project_id=project_id,
                book_id=book_id,
                require_ready=True,
            )
