"""Persistence for deterministic Story State reducer application evidence."""
from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb


class StoryStateRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def record_reducer_applications(
        self,
        *,
        project_id: str,
        story_state_asset_version_id: str,
        applications: list[dict[str, Any]],
    ) -> int:
        inserted = 0
        for application in applications:
            self.cursor.execute(
                """
                INSERT INTO authority_story_state_reducer_application(
                    reducer_application_id, project_id,
                    chapter_outcome_asset_version_id, reducer_key,
                    input_contract_version, output_state_type,
                    current_state_version, transition_hash, idempotency_key,
                    validation_policy, dependency_keys,
                    story_state_asset_version_id, status,
                    event_id, state_kind, entity_key, reducer_semantics,
                    accepted_chapter
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, 'APPLIED', %s, %s, %s, %s, %s
                )
                ON CONFLICT (project_id, event_id) DO NOTHING
                """,
                [
                    "story-reducer:"
                    + str(application["transition_hash"]).removeprefix(
                        "sha256:"
                    ),
                    project_id,
                    application["chapter_outcome_asset_version_id"],
                    application["reducer_key"],
                    application["input_contract_version"],
                    application["output_state_type"],
                    int(application["current_state_version"]),
                    application["transition_hash"],
                    application["idempotency_key"],
                    application["validation_policy"],
                    Jsonb(application.get("dependencies") or []),
                    story_state_asset_version_id,
                    application["event_id"],
                    application["state_kind"],
                    application["entity_key"],
                    application["reducer_semantics"],
                    int(application["accepted_chapter"]),
                ],
            )
            inserted += self.cursor.rowcount
        return inserted


__all__ = ["StoryStateRepository"]
