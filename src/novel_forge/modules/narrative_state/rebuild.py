from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository

from .contracts import events_from_chapter_outcome
from .reducers import reduce_story_state_v2


@dataclass(frozen=True, slots=True)
class NarrativeProjectionRebuildResult:
    project_id: str
    book_id: str
    accepted_through_chapter: int
    accepted_outcome_count: int
    source_contract_versions: tuple[str, ...]
    projection: dict[str, Any]
    rebuild_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "book_id": self.book_id,
            "accepted_through_chapter": self.accepted_through_chapter,
            "accepted_outcome_count": self.accepted_outcome_count,
            "source_contract_versions": list(self.source_contract_versions),
            "projection": self.projection,
            "rebuild_hash": self.rebuild_hash,
            "authority_mutated": False,
        }


class NarrativeStateRebuildService:

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def rebuild(
        self, *, project_id: str, book_id: str, through_chapter: int | None = None
    ) -> NarrativeProjectionRebuildResult:
        if not project_id or not book_id or (
            through_chapter is not None and through_chapter <= 0
        ):
            raise ValueError("Project, Book and a positive optional boundary are required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            rows, initial, initial_version = NarrativeRealityRepository(uow.cursor).rebuild_sources(
                project_id=project_id, book_id=book_id, through_chapter=through_chapter,
            )
        if not rows:
            raise KernelError(
                "NARRATIVE_REBUILD_SOURCE_MISSING",
                "no committed ChapterOutcome evidence exists for this Project/Book",
            )
        chapters = [int(row[0]) for row in rows]
        if len(chapters) != len(set(chapters)):
            raise KernelError(
                "NARRATIVE_REBUILD_SOURCE_AMBIGUOUS",
                "more than one committed ChapterOutcome exists for a chapter",
            )
        outcomes = [(str(row[1]), str(row[2]), dict(row[3])) for row in rows]
        if chapters != list(range(1, chapters[-1] + 1)):
            raise KernelError("NARRATIVE_REBUILD_SOURCE_GAP", "rebuild requires a contiguous accepted frontier")
        projection: dict[str, Any] | None = initial
        previous_story_state_asset_version_id = initial_version
        for outcome_asset_version_id, story_asset_version_id, outcome in outcomes:
            projection = reduce_story_state_v2(
                previous=projection,
                events=events_from_chapter_outcome(
                    outcome_asset_version_id, outcome
                ),
                chapter_outcome_asset_version_id=outcome_asset_version_id,
                chapter_outcome_id=str(outcome.get("chapter_outcome_id") or ""),
                previous_story_state_asset_version_id=(
                    previous_story_state_asset_version_id
                ),
            )
            previous_story_state_asset_version_id = story_asset_version_id
        assert projection is not None
        source_contracts = tuple(
            sorted(
                {
                    str(outcome.get("contract_version") or "")
                    for _, _, outcome in outcomes
                }
            )
        )
        digest_payload = {
            "project_id": project_id,
            "book_id": book_id,
            "accepted_outcome_asset_version_ids": [item[0] for item in outcomes],
            "projection_state_hash": projection["state_hash"],
        }
        rebuild_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return NarrativeProjectionRebuildResult(
            project_id=project_id,
            book_id=book_id,
            accepted_through_chapter=int(projection["accepted_through_chapter"]),
            accepted_outcome_count=len(outcomes),
            source_contract_versions=source_contracts,
            projection=projection,
            rebuild_hash=rebuild_hash,
        )


__all__ = ["NarrativeProjectionRebuildResult", "NarrativeStateRebuildService"]
