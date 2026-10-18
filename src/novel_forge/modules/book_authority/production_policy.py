from __future__ import annotations

from dataclasses import asdict
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def require_planning_provider_dispatch(cursor, *, project_id: str, operation_id: str) -> None:
    cursor.execute(
        """SELECT CASE WHEN owner.invalid_search OR cardinality(owner.runs)>0 AND (book.book_run_id IS NULL
                OR (SELECT count(DISTINCT run) FROM unnest(owner.runs) run)>1)
            THEN 'OWNER_INVALID' ELSE book.state END,
            EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=book.root_operation_id),
            EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
                JOIN authority_story_formation_run formation USING(formation_run_id)
                WHERE formation.project_id=book.project_id AND formation.book_id=book.book_id
                  AND book.stable_idempotency_key=formation.formation_run_id||':production')
        FROM authority_story_planning_generation generation JOIN authority_operation operation USING(operation_id)
        CROSS JOIN LATERAL (SELECT array_remove(ARRAY[
            NULLIF(operation.command_payload#>>'{payload,arc_working_set,working_manuscript,book_run_id}',''),
            NULLIF(operation.command_payload#>>'{payload,world_preparation_request,book_run_id}',''),
            NULLIF(operation.command_payload#>>'{payload,edition_execution,book_run_id}',''),
            (SELECT NULLIF(search.book_run_id,'') FROM authority_story_narrative_search search
                WHERE search.search_id=generation.narrative_search_id AND search.project_id=generation.project_id
                    AND search.workspace_id=generation.workspace_id AND search.book_id=generation.book_id)
        ],NULL) runs,
            generation.narrative_search_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM authority_story_narrative_search search WHERE search.search_id=generation.narrative_search_id
                    AND search.project_id=generation.project_id AND search.workspace_id=generation.workspace_id
                    AND search.book_id=generation.book_id) invalid_search) owner
        LEFT JOIN authority_book_production book ON book.project_id=generation.project_id
          AND book.workspace_id=generation.workspace_id AND book.book_id=generation.book_id
          AND (cardinality(owner.runs)=0 OR book.book_run_id=ANY(owner.runs))
        WHERE generation.operation_id=%s AND generation.project_id=%s
        """,
        [operation_id, project_id],
    )
    books = cursor.fetchall()
    if not books:
        return
    if len(books) != 1 or any(row[1] or row[2] or row[0] in {'OWNER_INVALID','ABORTED','CANCELLED','COMPLETED'} for row in books):
        raise KernelError("BOOK_GENERATION_EXECUTION_NOT_LIVE", "Planning requires its uncancelled owning Book")
    if books[0][0] == 'PAUSED':
        raise KernelError("RUNTIME_DISPATCH_PAUSED", "Planning preparation waits at the native Book pause checkpoint")


def chapter_context_policy(content: dict[str, Any]) -> dict[str, Any] | None:
    value = content.get("chapter_context_policy")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "version", "draft_profile", "draft_token_budget", "quality_token_budget"
    } or value.get("version") != "book-chapter-context.v1":
        raise KernelError("BOOK_CONTEXT_POLICY_INVALID", "Chapter Context requires its complete versioned policy")
    maximum = {"draft-context-profile-v2": 16000, "draft-context-profile-v3": 24000, "draft-context-profile-v4": 512000}.get(value["draft_profile"]) if isinstance(value["draft_profile"], str) else None
    if (maximum is None or type(value["draft_token_budget"]) is not int
        or not 1 <= value["draft_token_budget"] <= maximum
        or type(value["quality_token_budget"]) is not int or value["quality_token_budget"] <= 0):
        raise KernelError("BOOK_CONTEXT_POLICY_INVALID", "Context budgets must be positive and Draft must fit the selected profile ceiling")
    return dict(value)


def validate_author_configuration(content: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_policy
    from novel_forge.modules.review.prose_window import window_policy
    from novel_forge.modules.worldbuilding.actor_isolation import validate_actor_policy
    from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy

    if content.get("author_configuration_version") != "book-author-configuration.v1":
        raise KernelError("BOOK_AUTHOR_CONFIGURATION_INVALID", "Unsupported author configuration version")
    result = dict(content)
    context = chapter_context_policy(result)
    if context is None:
        raise KernelError("BOOK_CONTEXT_POLICY_INVALID", "Author configuration must explicitly choose Chapter Context")
    result["chapter_context_policy"] = context
    from .working_prose import working_prose_policy
    working = working_prose_policy(result)
    if working is not None:
        result["working_prose_policy"] = working
    result["craft_budget_policy"] = validate_craft_policy(result.get("craft_budget_policy"))
    if result.get("cross_chapter_review_policy") is not None:
        result["cross_chapter_review_policy"] = window_policy(result["cross_chapter_review_policy"])
    world = WorldProductionPolicy(**(result.get("world_production_policy") or {}))
    result["world_production_policy"] = asdict(world)
    actor = result.get("world_actor_experiment")
    if actor is not None:
        if not isinstance(actor, dict):
            raise KernelError("WORLD_ACTOR_POLICY_INVALID", "Actor policy must be an object")
        result["world_actor_experiment"] = validate_actor_policy(actor, character_ids=actor.get("actor_ids", []), policy=world)
    elif world.version not in {"world-production-policy.v1", "world-production-policy.v4", "world-production-policy.v5"}:
        raise KernelError("WORLD_ACTOR_POLICY_REQUIRED", "Actor World policy requires explicit bounded Actor selection")
    return result
