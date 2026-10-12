from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def bind_craft_realization(
    contract: Mapping[str, Any], strategy: Mapping[str, Any], *, scenes: list,
    plan: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_strategy
    from .realization_composition import _scene_craft_tasks

    frozen = validate_craft_strategy(strategy, scenes=scenes)
    result = deepcopy(dict(contract))
    if not frozen["uses"]:
        return result
    result["contract_version"] = "scene-realization-composition.v2"
    result["craft_strategy"] = frozen
    tasks = result.get("craft_tasks") or _scene_craft_tasks(
        scenes, result["slots"], result["voices"], plan=plan
    )
    tasks["strategy_digest"] = frozen["strategy_digest"]
    slots = {slot["slot_id"]: slot for slot in result["slots"]}
    for task in tasks["tasks"]:
        scene_id = slots[task["slot_id"]]["scene_id"]
        task["craft_use_ids"] = [
            use["use_id"] for use in frozen["uses"] if use["scene_id"] == scene_id
        ]
    tasks["scene_strategies"] = deepcopy(frozen["composition"])
    tasks["application_boundary"] = (
        "Realize only the adopted use sites and intended effects. Preserve planned events, "
        "POV, voice, knowledge, causality and satisfied mechanisms. Techniques do not "
        "authorize new facts, powers, characters, outcomes or additional uses."
    )
    if any(scene["judgment_basis"].startswith("NEED_DRIVEN_") for scene in frozen["composition"]):
        tasks["metadata_boundary"] = "Craft affinity and family are descriptive, not author requirements. Realize the frozen adopted needs and preserve their actual prerequisites and constraints."
    result["craft_tasks"] = tasks
    result["composition_method"] = (
        "Write one continuous chapter using the frozen scene strategies; serialize the "
        "final prose into slots. Technique names and slot coverage do not prove effects."
    )
    return result


def require_craft_delivery(
    *, plan: Mapping[str, Any], intent: Mapping[str, Any],
    memo: Mapping[str, Any], context: Mapping[str, Any],
) -> dict[str, Any]:
    strategy = plan.get("craft_strategy")
    diagnostics = []
    if strategy != intent.get("craft_strategy") or strategy != memo.get("craft_strategy"):
        diagnostics.append({"code": "CRAFT_EXECUTION_BINDING_DRIFT", "canonical_source": "CHAPTER_PLAN"})
    if not strategy:
        return {"status": "DIAGNOSTIC_ONLY", "diagnostics": diagnostics}
    from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_strategy

    validated = validate_craft_strategy(strategy, scenes=plan.get("scene_plan", []))
    selected = {
        item["asset_version_id"]: item
        for item in context.get("context_manifest", {}).get("selected_inputs", [])
    }
    for use in validated["uses"]:
        card = selected.get(use["knowledge_card_asset_version_id"], {})
        if card.get("content_digest") != use["content_hash"]:
            diagnostics.append({"code": "CRAFT_CONTEXT_DELIVERY_MISSING",
                "knowledge_card_asset_version_id": use["knowledge_card_asset_version_id"]})
    return {"status": "DIAGNOSTIC_ONLY", "diagnostics": diagnostics,
            "author_required_inputs": "ENFORCED_BY_FROZEN_CONTEXT_AND_CAPABILITY_BINDINGS"}
