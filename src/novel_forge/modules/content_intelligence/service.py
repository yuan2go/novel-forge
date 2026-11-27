from __future__ import annotations

from typing import Any

from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import aggregate_pacing_windows


class PacingAnalysisService:

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def aggregate_at(
        self,
        *,
        project_id: str,
        chapter: int,
        scopes: dict[str, tuple[int, int]] | None = None,
    ) -> dict[str, Any]:
        if not project_id.strip() or chapter <= 0:
            raise ValueError("project_id and a positive chapter are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content
                FROM authority_longform_observation_projection
                WHERE project_id=%s
                  AND asset_type='pacing_observation'
                  AND accepted_chapter <= %s
                ORDER BY accepted_chapter, recorded_at, asset_version_id
                """,
                [project_id, chapter],
            )
            observations = [dict(row[0]) for row in uow.cursor.fetchall()]
        return aggregate_pacing_windows(
            project_id=project_id,
            as_of_chapter=chapter,
            observations=observations,
            scopes=scopes,
        )

    def hook_analyses_at(
        self,
        *,
        project_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        if not project_id.strip() or chapter <= 0:
            raise ValueError("project_id and a positive chapter are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT accepted_chapter, asset_version_id, content
                FROM authority_longform_observation_projection
                WHERE project_id=%s
                  AND asset_type='hook_analysis'
                  AND accepted_chapter <= %s
                ORDER BY accepted_chapter, recorded_at, asset_version_id
                """,
                [project_id, chapter],
            )
            rows = uow.cursor.fetchall()
        return {
            "project_id": project_id,
            "as_of_chapter": chapter,
            "boundary": "INCLUSIVE",
            "accepted_state_only": True,
            "analyses": [
                {
                    **dict(row[2]),
                    "accepted_chapter": int(row[0]),
                    "asset_version_id": str(row[1]),
                }
                for row in rows
            ],
        }


__all__ = ["PacingAnalysisService"]
