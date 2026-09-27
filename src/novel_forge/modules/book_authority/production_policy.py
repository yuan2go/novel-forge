from __future__ import annotations

from dataclasses import asdict
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def chapter_context_policy(content: dict[str, Any]) -> dict[str, Any] | None:
    value = content.get("chapter_context_policy")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "version", "draft_profile", "draft_token_budget", "quality_token_budget"
    } or value.get("version") != "book-chapter-context.v1":
        raise KernelError("BOOK_CONTEXT_POLICY_INVALID", "Chapter Context requires its complete versioned policy")
    maximum = {"draft-context-profile-v2": 16000, "draft-context-profile-v3": 24000}.get(value["draft_profile"]) if isinstance(value["draft_profile"], str) else None
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
    result["craft_budget_policy"] = validate_craft_policy(result.get("craft_budget_policy"))
    if result.get("cross_chapter_review_policy") is not None:
        result["cross_chapter_review_policy"] = window_policy(result["cross_chapter_review_policy"])
    world = WorldProductionPolicy(**(result.get("world_production_policy") or {}))
    result["world_production_policy"] = asdict(world)
    actor = result.get("world_actor_experiment")
    if actor is not None:
        if not isinstance(actor, dict):
            raise KernelError("WORLD_ACTOR_POLICY_INVALID", "Actor policy must be an object")
        # INVARIANT: These are future intent IDs; World preparation checks membership against the exact approved Foundation before dispatch.
        result["world_actor_experiment"] = validate_actor_policy(actor, character_ids=actor.get("actor_ids", []), policy=world)
    elif world.version != "world-production-policy.v1":
        raise KernelError("WORLD_ACTOR_POLICY_REQUIRED", "Actor World policy requires explicit bounded Actor selection")
    return result
