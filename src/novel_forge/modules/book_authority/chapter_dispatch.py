from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.chapter_quality_authority import load_accepted_quality_observations
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import compact_canon_facts, compact_current_state_facts
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def reserved_chapter_command(database_url: str, *, book: dict[str, Any], persisted: dict[str, Any],
                             actor_id: str, application_build_id: str, commit_sha: str) -> SingleChapterRequest:
    payload = persisted["command_payload"]
    chapter = int(persisted["chapter_number"])
    if payload["book_run_id"] != book["book_run_id"] or payload["chapter_number"] != chapter:
        raise KernelError("BOOK_CHAPTER_RECOVERY_SCOPE_DRIFT", "Frozen Chapter request identity must match its owned Book reservation")
    from .manuscript import author_first
    candidates = tuple(payload.get("context_candidates") or ()) if author_first(book) else context_candidates_for_dispatch(database_url, book_id=book["book_id"], book_run_id=book["book_run_id"],
        project_id=book["project_id"], chapter_number=chapter, requested=tuple(payload.get("context_candidates") or ()))
    return SingleChapterRequest(project_id=book["project_id"], workspace_id=book["workspace_id"], actor_id=actor_id,
        chapter=chapter, title=payload["title"], premise=payload["premise"],
        trace_id=f"{book['root_operation_id']}:chapter:{chapter}", correlation_id=book["root_operation_id"],
        application_build_id=application_build_id, commit_sha=commit_sha, book_id=book["book_id"],
        chapter_plan_asset_version_id=payload.get("execution_chapter_plan_asset_version_id") or payload["chapter_plan_asset_version_id"],
        chapter_plan_content_hash=payload.get("execution_chapter_plan_content_hash") or payload["chapter_plan_content_hash"],
        context_candidates=candidates, accepted_prose_snapshot=payload.get("accepted_prose_snapshot"),
        context_version_refs=payload.get("context_version_refs"), context_token_budget=payload["context_token_budget"],
        preparation_report=payload.get("preparation_report"), idempotency_key=persisted["stable_idempotency_key"])


def require_reserved_edition_adoption(database_url: str, *, request: SingleChapterRequest, adoption: dict[str, Any]) -> bool:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT to_jsonb(r),to_jsonb(b),
            NOT EXISTS(SELECT 1 FROM authority_book_edition_event event WHERE event.revision_id=%s
                AND event.event_kind='REJECTED' AND event.created_at<=r.created_at)
            FROM authority_book_chapter_request r JOIN authority_book_production b USING(book_run_id)
            WHERE r.project_id=%s AND r.book_run_id=%s AND r.stable_idempotency_key=%s
              AND b.workspace_id=%s AND b.book_id=%s AND r.chapter_number=%s""",
            [adoption["revision_id"],request.project_id,adoption["book_run_id"],request.idempotency_key,
             request.workspace_id,request.book_id,request.chapter])
        row = uow.cursor.fetchone()
    if row is None:
        return False
    persisted, book, before_rejection = row
    if book["active_chapter_request_id"] != persisted["chapter_request_id"] or book["state"] != "CHAPTER_SUBMITTED":
        raise KernelError("EDITION_RESERVED_REQUEST_NOT_RUNNABLE", "Edition recovery requires the active runnable Book reservation")
    if not before_rejection or (persisted["command_payload"].get("preparation_report") or {}).get("author_draft_adoption") != adoption:
        raise KernelError("EDITION_RESERVED_ADOPTION_DRIFT", "Only the exact adoption frozen before rejection may recover")
    expected = reserved_chapter_command(database_url, book=book, persisted=persisted, actor_id=request.actor_id,
        application_build_id=request.application_build_id, commit_sha=request.commit_sha)
    if json.loads(json.dumps(asdict(expected))) != json.loads(json.dumps(asdict(request))):
        raise KernelError("EDITION_RESERVED_ADOPTION_DRIFT", "Chapter recovery must match the complete Book-owned frozen request")
    return True


def context_candidates_for_dispatch(
    database_url: str,
    *,
    book_id: str,
    book_run_id: str,
    project_id: str,
    chapter_number: int,
    requested: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    if chapter_number <= 1:
        return requested
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT state.asset_type, state.asset_version_id,
                   state.content_hash, state.content
            FROM (
                SELECT 'story_state_snapshot'::text AS asset_type,
                       story.asset_version_id,
                       story.content_hash, story.content
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_asset_version AS story
                  ON story.asset_version_id=
                     acceptance.story_state_asset_version_id
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number)
                  AND acceptance.project_id=%s
                  AND acceptance.chapter_number=%s
                  AND acceptance.status='COMMITTED'
                UNION ALL
                SELECT 'canon_snapshot'::text AS asset_type,
                       canon.asset_version_id,
                       canon.content_hash, canon.content
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_asset_version AS canon
                  ON canon.asset_version_id=
                     acceptance.canon_snapshot_asset_version_id
                WHERE acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number)
                  AND acceptance.project_id=%s
                  AND acceptance.chapter_number=%s
                  AND acceptance.status='COMMITTED'
            ) AS state
            ORDER BY state.asset_type, state.asset_version_id
            """,
            [
                book_run_id,
                project_id,
                chapter_number - 1,
                book_run_id,
                project_id,
                chapter_number - 1,
            ],
        )
        rows = uow.cursor.fetchall()
    if {str(row[0]) for row in rows} != {
        "story_state_snapshot",
        "canon_snapshot",
    }:
        raise KernelError(
            "BOOK_PREVIOUS_CHAPTER_STATE_MISSING",
            "next Chapter requires one accepted predecessor Story State and Canon snapshot",
        )
    state_versions = {str(row[0]): str(row[1]) for row in rows}
    governed_items: list[dict[str, Any]] = []
    accepted_quality_observations = load_accepted_quality_observations(
        database_url,
        project_id=project_id,
        book_id=book_id,
        book_run_id=book_run_id,
        accepted_through_chapter=chapter_number - 1,
    )
    for row in rows:
        content = dict(row[3] or {})
        expected_contract = (
            "story-state-snapshot-v2"
            if row[0] == "story_state_snapshot"
            else "canon-snapshot-v2"
        )
        if (
            content.get("contract_version") != expected_contract
            or content.get("project_id") != project_id
            or content.get("book_id") != book_id
            or int(content.get("accepted_through_chapter") or 0)
            != chapter_number - 1
        ):
            raise KernelError(
                "BOOK_PREVIOUS_CHAPTER_STATE_INVALID",
                "predecessor state contract, Project, Book or accepted chapter is invalid",
            )
        safe_summary = (
            f"Accepted chapter {chapter_number - 1} {row[0]} state snapshot."
        )
        structured_facts = (
            compact_current_state_facts(content)
            if row[0] == "story_state_snapshot"
            else compact_canon_facts(content)
        )
        if row[0] == "story_state_snapshot" and accepted_quality_observations:
            structured_facts.append(
                {
                    "key": "accepted_quality_observations",
                    "value": accepted_quality_observations,
                    "provider_visibility": "INTERNAL_QUALITY_ONLY",
                }
            )
        rendered = json.dumps(
            {
                "safe_summary": safe_summary,
                "structured_facts": [
                    fact
                    for fact in structured_facts
                    if fact.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        governed_items.append(
            {
                "asset_type": str(row[0]),
                "physical_asset_type": str(row[0]),
                "asset_version_id": str(row[1]),
                "content_hash": str(row[2]),
                "project_id": project_id,
                "book_id": book_id,
                "accepted_boundary": {
                    "accepted_through_chapter": chapter_number - 1,
                    "story_state_snapshot_version": state_versions[
                        "story_state_snapshot"
                    ],
                    "canon_snapshot_version": state_versions["canon_snapshot"],
                },
                "scope": {
                    "project_id": project_id,
                    "book_id": str(content["book_id"]),
                    "accepted_through_chapter": chapter_number - 1,
                },
                "estimated_tokens": max(1, len(rendered) // 4),
                "safe_summary": safe_summary,
                "structured_facts": structured_facts,
                "narrative_function": "authoritative_story_state",
                "source_use_mode": "generation",
                "allowed_use": "generation",
            }
        )
    governed = tuple(governed_items)
    merged: dict[str, dict[str, Any]] = {
        str(item["asset_version_id"]): dict(item)
        for item in requested
        if str(item.get("asset_type") or "")
        not in {"story_state_snapshot", "canon_snapshot"}
    }
    for item in governed:
        merged[str(item["asset_version_id"])] = item
    return tuple(merged.values())

