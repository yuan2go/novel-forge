from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .craft_selection import _hash


def rejection_details(candidate: Mapping[str, Any], selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    cards = {item["knowledge_card_asset_version_id"]: item for item in selection.get("selected", []) if item.get("selected_content", {}).get("craft_mechanism")}
    scene_ids = [scene.get("scene_id") for scene in candidate.get("scene_plan", [])]
    rejected = []
    for translation in candidate.get("knowledge_translations", []):
        identity = translation["knowledge_card_asset_version_id"]
        if identity not in cards or translation["decision"] != "REJECT":
            continue
        scenes = translation.get("rejected_scene_ids")
        condition = translation.get("failure_condition")
        if (not isinstance(scenes, list) or not scenes or len(scenes) != len(set(scenes))
            or set(scenes) - set(scene_ids) or not isinstance(condition, str) or not condition.strip() or len(condition) > 512):
            raise KernelError("CRAFT_REJECTION_SCOPE_INVALID", "A Craft rejection must name actual candidate scenes and its bounded failure condition")
        rejected.append({"knowledge_card_asset_version_id": identity, "content_hash": cards[identity]["content_hash"],
                         "scene_ids": sorted(scenes), "failure_condition": condition,
                         "reason": translation["rationale"], "scene_snapshot_hash": _hash(candidate["scene_plan"])})
    return rejected


def validate_concrete_selection(candidate: Mapping[str, Any], selection: Mapping[str, Any]) -> None:
    if selection.get("craft_policy", {}).get("schema_version") not in {"narrative-craft-budget.v4", "narrative-craft-budget.v5"}:
        return
    for translation in candidate.get("knowledge_translations", []):
        if translation.get("decision") != "REJECT" and (translation.get("rejected_scene_ids") or translation.get("failure_condition")):
            raise KernelError("CRAFT_REJECTION_SCOPE_INVALID", "Adopted uses cannot carry stale rejection exclusions")
    rejected = rejection_details(candidate, selection)
    if rejected:
        raise KernelError("CRAFT_CONCRETE_REJECTED", "Selected Craft was rejected at concrete scenes; record a new bounded selection: " + ", ".join(item["knowledge_card_asset_version_id"] for item in rejected))
    state = selection.get("need", {}).get("craft_context", {}).get("reselection") or {}
    if state:
        scenes = [item.get("scene_id") for item in candidate.get("scene_plan", [])]
        if scenes != state["scene_ids"]:
            raise KernelError("CRAFT_RESELECTION_SCENE_DRIFT", "Concrete repair preserves the exact scene identities and order; structural replanning requires its own decision")
        for translation in candidate.get("knowledge_translations", []):
            for site in translation.get("use_sites", []):
                pointer = site["target_pointer"].split("/")
                if len(pointer) < 3 or pointer[1] != "scene_plan" or not pointer[2].isdigit():
                    continue
                index = int(pointer[2])
                if index >= len(scenes):
                    continue
                for exclusion in state["exclusions"]:
                    if (translation["knowledge_card_asset_version_id"] == exclusion["knowledge_card_asset_version_id"]
                        and translation["content_hash"] == exclusion["content_hash"] and scenes[index] in exclusion["scene_ids"]):
                        raise KernelError("CRAFT_RESELECTION_EXCLUDED_SITE", "This exact Card/scene/failure condition is excluded within the frozen repair task")


def next_reselection_context(*, selection: Mapping[str, Any], source: Mapping[str, Any], task_identity: str) -> dict[str, Any]:
    policy = selection.get("craft_policy") or {}
    if policy.get("schema_version") not in {"narrative-craft-budget.v4", "narrative-craft-budget.v5"}:
        return {}
    prior = deepcopy(selection.get("need", {}).get("craft_context", {}).get("reselection") or {})
    if prior and prior["task_identity"] != task_identity:
        raise KernelError("CRAFT_RESELECTION_TASK_DRIFT", "A failure exclusion cannot cross its exact frozen planning task")
    raw = source["raw_result"]
    diagnostic = source["diagnostic"]
    if diagnostic.get("error_code") != "CRAFT_CONCRETE_REJECTED":
        return prior
    scenes = [item.get("scene_id") for item in raw.get("scene_plan", [])]
    if not scenes or len(scenes) != len(set(scenes)) or any(not isinstance(value, str) or not value for value in scenes):
        raise KernelError("CRAFT_RESELECTION_SCENES_UNAVAILABLE", "Scene applicability needs a complete, distinct concrete scene scope")
    rejected = rejection_details(raw, selection)
    history = prior.get("history", [])
    if len(history) >= policy["reselection_policy"]["maximum_reselections"]:
        raise KernelError("CRAFT_RESELECTION_BUDGET_EXHAUSTED", "Concrete selection attempts exhausted the frozen bound; feasibility beyond the attempted evidence is unknown")
    signature = _hash({"selection": [(item["knowledge_card_asset_version_id"], item["content_hash"]) for item in selection["selected"]], "rejections": rejected})
    if any(item["failure_signature"] == signature for item in history):
        raise KernelError("CRAFT_RESELECTION_CYCLE_DETECTED", "An identical concrete rejection cannot be redispatched")
    entry = {"failure_signature": signature, "failure_class": "BUSINESS_REJECT", "error_code": diagnostic["error_code"],
             "source_asset_version_id": source["asset_version_id"], "source_content_hash": source["content_hash"],
             "source_operation_id": source["source_operation_id"], "selection_digest": selection["selection_digest"],
             "result_hash": _hash(raw), "exclusions": rejected, "execution_evidence": deepcopy(source["execution_evidence"])}
    return {"contract_version": "craft-reselection.v1", "task_identity": task_identity,
            "scene_ids": scenes, "history": [*history, entry], "exclusions": [*prior.get("exclusions", []), *rejected],
            "budget_owner": "NATIVE_PLANNING_ROUTING_LINEAGE_AND_PROVIDER_BUDGET_LEDGER"}
