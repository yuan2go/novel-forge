from __future__ import annotations

from typing import Literal
from pydantic import Field
from novel_forge.modules.source_authority.corpus import (
    CorpusContract,
    Text,
    corpus_hash,
)
from novel_forge.modules.command_kernel.errors import KernelError


class ChapterReadingScope(CorpusContract):
    version: Literal["chapter-reading.v1"] = "chapter-reading.v1"
    processing_id: Text
    first_unit_version_id: Text
    last_unit_version_id: Text
    context_before: int = Field(default=0, ge=0, le=2)
    context_after: int = Field(default=0, ge=0, le=2)
    max_chapters: int = Field(default=10, ge=1, le=20)
    max_input_bytes_per_chapter: int = Field(default=48000, ge=256, le=128000)
    max_total_input_bytes: int = Field(default=480000, ge=256, le=1000000)
    max_repairs: int = Field(default=1, ge=0, le=2)
    dimensions: tuple[
        Literal[
            "causal_constraints",
            "character_choice_cost",
            "information_gap",
            "foreshadowing_payoff",
            "chapter_hook",
            "point_of_view",
            "conflict",
            "emotion_curve",
            "world_rules",
        ],
        ...,
    ] = Field(
        default=("causal_constraints", "character_choice_cost", "information_gap"),
        min_length=1,
        max_length=9,
    )


def freeze_reading_scope(
    repository,
    project: str,
    selected: list[dict],
    scopes: tuple[ChapterReadingScope, ...],
) -> dict:
    if len({s.processing_id for s in scopes}) != len(scopes):
        raise KernelError(
            "READING_SCOPE_DUPLICATE", "one frozen range per selected member"
        )
    if {s.processing_id for s in scopes} != {m["processing_id"] for m in selected}:
        raise KernelError(
            "READING_SCOPE_MEMBER_MISMATCH",
            "every selected member requires an exact range",
        )
    sources = repository.catalog_processings(project, [s.processing_id for s in scopes])
    result = {}
    for scope in scopes:
        source = sources.get(scope.processing_id)
        if source is None:
            raise KernelError(
                "READING_PROCESSING_MISSING", "exact Processing is unavailable"
            )
        units = repository.catalog_reading_units(
            project, source["source_work_asset_version_id"], scope.model_dump()
        )
        targets = [u for u in units if u["role"] == "TARGET"]
        if not targets or len(targets) > scope.max_chapters:
            raise KernelError(
                "READING_CHAPTER_BOUND", "requested range exceeds frozen chapter bound"
            )
        if any(
            u["kind"] not in {"chapter", "extra"} or u["status"] != "AVAILABLE"
            for u in units
        ):
            raise KernelError(
                "READING_STRUCTURE_UNUSABLE",
                "range contains excluded or non-body units",
            )
        if any(
            u["normalized_byte_end"] - u["normalized_byte_start"]
            > scope.max_input_bytes_per_chapter
            for u in units
        ):
            raise KernelError(
                "READING_WINDOW_TOO_LARGE",
                "split or explicitly narrow the request; no silent truncation",
            )
        if (
            sum(u["normalized_byte_end"] - u["normalized_byte_start"] for u in units)
            > scope.max_total_input_bytes
        ):
            raise KernelError(
                "READING_TOTAL_BOUND", "full selected input exceeds frozen byte bound"
            )
        chunks = repository.catalog_reading_chunks(
            project, source["source_transform_id"], units
        )
        for unit in units:
            unit["chunks"] = [
                c
                for c in chunks
                if c["source_byte_end"] > unit["normalized_byte_start"]
                and c["source_byte_start"] < unit["normalized_byte_end"]
            ]
            covered = sum(
                min(c["source_byte_end"], unit["normalized_byte_end"])
                - max(c["source_byte_start"], unit["normalized_byte_start"])
                for c in unit["chunks"]
            )
            if covered != unit["normalized_byte_end"] - unit["normalized_byte_start"]:
                raise KernelError(
                    "READING_CHUNK_COVERAGE_INVALID",
                    "source unit lacks exact chunk coverage",
                )
        frozen = {
            "contract": scope.model_dump(mode="json"),
            "edition_id": source["edition_id"],
            "processing_id": scope.processing_id,
            "source_work_asset_version_id": source["source_work_asset_version_id"],
            "source_transform_id": source["source_transform_id"],
            "assessment_hash": corpus_hash(source["assessment"]),
            "review_id": source["review_id"],
            "member": next(
                m for m in selected if m["processing_id"] == scope.processing_id
            ),
            "units": units,
            "coverage_claim": "SELECTED_CONTIGUOUS_UNITS_ONLY",
            "outside_range": "NOT_READ",
            "tool_access": "DENY_FILESYSTEM_SHELL_WEB_MCP",
        }
        frozen["identity"] = corpus_hash(frozen)
        result[scope.processing_id] = frozen
    return result


def preview_reading(database_url, project, revision_id, scopes, principal):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.storage.source_authority_repositories import (
        SourceAuthorityRepository,
    )
    from novel_forge.modules.source_authority.curation import curated_availability

    principal.require("source.authority.query", project)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = SourceAuthorityRepository(uow.cursor)
        repository.corpus_authorization_lock(project)
        frozen = repository.catalog_current(
            "curated", project, revision_id, revision=True
        )
        if not frozen or frozen["manifest"]["state"] != "FROZEN":
            raise KernelError(
                "CURATED_CORPUS_NOT_FROZEN", "preview requires an exact frozen revision"
            )
        current = repository.catalog_current("curated", project, frozen["corpus_id"])
        if current["revision_id"] != revision_id:
            raise KernelError(
                "CURATED_REVISION_STALE",
                "preview does not silently substitute the current selection",
            )
        selected = [m for m in frozen["members"] if m["evidence"]["selected"]]
        availability = curated_availability(repository, project, selected)
        if any(not a["available"] for a in availability):
            raise KernelError("CURATED_MEMBERS_UNAVAILABLE", str(availability))
        plans = freeze_reading_scope(
            repository,
            project,
            selected,
            tuple(ChapterReadingScope.model_validate(s) for s in scopes),
        )
    chapters = sum(
        sum(u["role"] == "TARGET" for u in p["units"]) for p in plans.values()
    )
    return {
        "revision_id": revision_id,
        "reading_plans": plans,
        "target_chapters": chapters,
        "planned_calls_without_repairs": 2 * chapters + 4 * len(plans),
        "model_calls": 0,
        "paid_authorization": "NOT_GRANTED_BY_PREVIEW",
        "input_token_accounting": "FINAL_MATERIALIZED_PROVIDER_REQUEST_REQUIRED",
        "state": "PREVIEW_ONLY",
    }
