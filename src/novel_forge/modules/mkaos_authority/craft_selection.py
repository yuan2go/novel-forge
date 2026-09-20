from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError


DEFAULT_CRAFT_POLICY = {
    "schema_version": "narrative-craft-budget.v1",
    "classification": "CONFIGURABLE_POLICY",
    "max_craft_candidates": 6,
    "max_uses_per_scene": 3,
    "max_uses_per_chapter": 8,
    "recent_chapter_window": 5,
    "cooldown_chapters": 1,
    "max_frequency_in_window": 3,
    "repetition_penalty": 4,
    "pattern_similarity_penalty": 2,
    "pattern_similarity_threshold_percent": 60,
    "salience_penalty": 2,
    "variation_bonus": 1,
}


def validate_craft_policy(value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = {**DEFAULT_CRAFT_POLICY, **dict(value or {})}
    if set(result) != set(DEFAULT_CRAFT_POLICY) or result["schema_version"] != "narrative-craft-budget.v1" or result["classification"] != "CONFIGURABLE_POLICY":
        raise KernelError("CRAFT_POLICY_INVALID", "Craft budget is a versioned configurable policy")
    for key in set(result) - {"schema_version", "classification"}:
        if type(result[key]) is not int or not 0 <= result[key] <= 100:
            raise KernelError("CRAFT_POLICY_INVALID", "Craft policy values must be bounded nonnegative integers")
    if not 1 <= result["max_craft_candidates"] <= 12 or not result["max_uses_per_scene"] or not result["max_uses_per_chapter"]:
        raise KernelError("CRAFT_POLICY_INVALID", "Craft selection and density limits must be positive")
    return result


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _terms(value: Any) -> set[str]:
    text = json.dumps(value, ensure_ascii=False).casefold()
    words = set(re.findall(r"[a-z][a-z_-]+|[\u4e00-\u9fff]+", text))
    return words | {word[index:index + 2] for word in words if re.fullmatch(r"[\u4e00-\u9fff]+", word) for index in range(len(word) - 1)}


def craft_pattern_signature(mechanism: Mapping[str, Any]) -> list[str]:
    return sorted(_terms({key: mechanism[key] for key in ("abstract_mechanism", "affinity")}))[:256]


def craft_candidate_assessment(mechanism: Mapping[str, Any], *, context: Mapping[str, Any], recent_usage: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    from .craft import validate_craft_mechanism

    mechanism = validate_craft_mechanism(mechanism)
    policy = validate_craft_policy(policy)
    reasons: list[str] = []
    score = 0
    searchable = _terms({key: mechanism[key] for key in ("narrative_problem", "desired_reader_effect", "abstract_mechanism", "applicability_conditions", "affinity")})
    for dimension, values in sorted(context.items()):
        overlap = _terms(values) & searchable
        if overlap:
            score += min(5, len(overlap))
            reasons.append(f"CRAFT_CONTEXT:{dimension}:{','.join(sorted(overlap)[:5])}")
    identity = mechanism["mechanism_id"]
    current_chapter = int(context.get("chapter_number") or 0)
    unique = {
        (item.get("chapter"), item.get("use_id")): dict(item)
        for item in recent_usage
        if current_chapter - policy["recent_chapter_window"] <= int(item.get("chapter") or 0) < current_chapter
        and int(item.get("chapter") or 0) > 0 and item.get("use_id") and item.get("external_effect_id") and item.get("external_receipt_ids")
    }
    observations = [unique[key] for key in sorted(unique)]
    matching = [item for item in observations if item.get("mechanism_id") == identity]
    frequency = len(matching)
    repetition_penalty = frequency * policy["repetition_penalty"]
    signature = set(craft_pattern_signature(mechanism))
    similarities = []
    for item in observations:
        other = set(item.get("pattern_signature") or [])
        if other and item.get("mechanism_id") != identity:
            similarity = len(signature & other) * 100 // len(signature | other)
            similarities.append({"use_id": item["use_id"], "chapter": item["chapter"], "method": "ABSTRACT_MECHANISM_AFFINITY_TERM_JACCARD", "similarity_percent": similarity})
    pattern_penalty = sum(item["similarity_percent"] >= policy["pattern_similarity_threshold_percent"] for item in similarities) * policy["pattern_similarity_penalty"]
    salience_penalty = sum(item.get("role") == "PRIMARY" for item in matching) * policy["salience_penalty"]
    if matching:
        reasons.append(f"CRAFT_RECENT_DELIVERY_FREQUENCY:{frequency}")
    elif score:
        score += policy["variation_bonus"]
        reasons.append("CRAFT_VARIATION_BONUS")
    in_cooldown = any(0 < current_chapter - int(item["chapter"]) <= policy["cooldown_chapters"] for item in matching)
    rejection = "CRAFT_COOLDOWN" if in_cooldown else "CRAFT_FREQUENCY_BUDGET" if frequency >= policy["max_frequency_in_window"] else "" if score else "CRAFT_NO_CONTEXT_MATCH"
    return {
        "rejection_reason": rejection,
        "score": max(1, score - repetition_penalty - pattern_penalty - salience_penalty) if score else 0,
        "match_reasons": reasons,
        "budget_assessment": {"frequency": frequency, "repetition_penalty": repetition_penalty, "pattern_similarity_penalty": pattern_penalty, "salience_penalty": salience_penalty, "in_cooldown": in_cooldown, "pattern_signature": sorted(signature), "pattern_comparisons": similarities, "recent_usage": observations, "evidence_ceiling": "DELIVERY_OBSERVATION_NOT_READER_EFFECT"},
        "applicability_judgment": "CONTEXTUAL_ADAPTATION_REQUIRED",
    }


def compose_craft_candidates(ranked: list[dict[str, Any]], *, limit: int, required_ids: set[str], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in ranked:
        mechanism = item["selected_content"].get("craft_mechanism")
        existing = [row["selected_content"]["craft_mechanism"] for row in selected if row["selected_content"].get("craft_mechanism")]
        reason = ""
        if len(selected) >= limit:
            reason = "NARRATIVE_BANDWIDTH_LIMIT"
        elif mechanism and len(existing) >= policy["max_craft_candidates"]:
            reason = "CRAFT_CANDIDATE_BUDGET"
        elif mechanism and any(other["mechanism_id"] in mechanism["composition"]["conflicting"] or mechanism["mechanism_id"] in other["composition"]["conflicting"] for other in existing):
            reason = "CRAFT_COMPOSITION_CONFLICT"
        if reason:
            rejected.append({"knowledge_card_asset_version_id": item["knowledge_card_asset_version_id"], "content_hash": item["content_hash"], "reason": reason, "applicability_assessment": item["applicability_assessment"]})
        else:
            selected.append(item)
    while True:
        identities = {item["selected_content"]["craft_mechanism"]["mechanism_id"] for item in selected if item["selected_content"].get("craft_mechanism")}
        missing = [item for item in selected if item["selected_content"].get("craft_mechanism") and set(item["selected_content"]["craft_mechanism"]["composition"]["requires"]) - identities]
        if not missing:
            break
        for item in missing:
            selected.remove(item)
            rejected.append({"knowledge_card_asset_version_id": item["knowledge_card_asset_version_id"], "content_hash": item["content_hash"], "reason": "CRAFT_DEPENDENCY_UNAVAILABLE", "applicability_assessment": item["applicability_assessment"]})
    if required_ids - {item["knowledge_card_asset_version_id"] for item in selected}:
        raise KernelError("MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE", "required parent mechanisms conflict with the current Craft budget or composition")
    return selected, rejected


def build_craft_strategy(candidate: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any] | None:
    cards = {item["knowledge_card_asset_version_id"]: item for item in selection.get("selected") or () if item.get("selected_content", {}).get("craft_mechanism")}
    if not cards:
        return None
    scenes = candidate.get("scene_plan") or []
    if not isinstance(selection.get("craft_policy"), Mapping) or set(selection["craft_policy"]) != set(DEFAULT_CRAFT_POLICY):
        raise KernelError("CRAFT_FROZEN_POLICY_MISSING", "Craft selection must freeze the complete versioned budget policy before planning")
    policy = validate_craft_policy(selection["craft_policy"])
    uses: list[dict[str, Any]] = []
    for translation in candidate.get("knowledge_translations") or ():
        card = cards.get(translation["knowledge_card_asset_version_id"])
        if card is None or translation["decision"] == "REJECT":
            continue
        mechanism = card["selected_content"]["craft_mechanism"]
        for site in translation["use_sites"]:
            tokens = site["target_pointer"].split("/")
            if len(tokens) < 4 or tokens[1] != "scene_plan" or not tokens[2].isdigit() or int(tokens[2]) >= len(scenes):
                raise KernelError("CRAFT_USE_SITE_UNLOCATED", "Chapter Craft must bind a concrete field within its authoritative scene_plan")
            scene = scenes[int(tokens[2])]
            use = {
                "knowledge_card_asset_version_id": card["knowledge_card_asset_version_id"], "content_hash": card["content_hash"],
                "mechanism_id": mechanism["mechanism_id"], "mechanism_version": mechanism["version"],
                "scene_id": scene["scene_id"], "role": site.get("craft_role"), "sequence": site.get("craft_sequence"),
                "decision": translation["decision"], "intended_reader_effect": site.get("intended_reader_effect"),
                "adaptation_rationale": translation.get("rationale", ""), "prerequisite_resolution": translation.get("prerequisite_resolution", ""),
                "planning_use_site": dict(site), "mechanism": mechanism,
                "preservation_requirements": list(dict.fromkeys([*site["preservation_requirements"], *mechanism["preservation_constraints"]])),
            }
            use["use_id"] = "craft-use:" + _hash({"selection_digest": selection["selection_digest"], "card": card["knowledge_card_asset_version_id"], "scene_id": scene["scene_id"], "pointer": site["target_pointer"]})[-24:]
            uses.append(use)
    uses.sort(key=lambda use: (use["scene_id"], use["sequence"] if type(use["sequence"]) is int else -1, use["use_id"]))
    composition = []
    for scene_id in dict.fromkeys(use["scene_id"] for use in uses):
        group = [use for use in uses if use["scene_id"] == scene_id]
        composition.append({"scene_id": scene_id, "ordered_use_ids": [use["use_id"] for use in group], "intended_combined_reader_effect": "；".join(dict.fromkeys(str(use["intended_reader_effect"] or "") for use in group)), "judgment_basis": "PROVIDER_PLANNING_TRANSLATION_WITH_DETERMINISTIC_COMPATIBILITY_CHECK"})
    strategy = {"schema_version": "narrative-craft-strategy.v1", "selection_digest": selection["selection_digest"], "policy": policy, "uses": uses, "composition": composition, "evidence_ceiling": "PLANNING_JUDGMENT_NOT_READER_EFFECT"}
    strategy["strategy_digest"] = _hash(strategy)
    return validate_craft_strategy(strategy, scenes=scenes)


def validate_craft_strategy(strategy: Mapping[str, Any], *, scenes: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    from .craft import validate_craft_mechanism

    if not isinstance(strategy, Mapping) or set(strategy) != {"schema_version", "selection_digest", "policy", "uses", "composition", "evidence_ceiling", "strategy_digest"} or strategy.get("schema_version") != "narrative-craft-strategy.v1" or strategy.get("evidence_ceiling") != "PLANNING_JUDGMENT_NOT_READER_EFFECT":
        raise KernelError("CRAFT_STRATEGY_INVALID", "Craft strategy requires the versioned governed planning contract")
    if not str(strategy["selection_digest"]).startswith("sha256:") or strategy["strategy_digest"] != _hash({key: value for key, value in strategy.items() if key != "strategy_digest"}):
        raise KernelError("CRAFT_STRATEGY_DRIFT", "Craft strategy must retain its frozen selection and content digest")
    if not isinstance(strategy["policy"], Mapping) or set(strategy["policy"]) != set(DEFAULT_CRAFT_POLICY):
        raise KernelError("CRAFT_FROZEN_POLICY_MISSING", "Strategy replay cannot fill missing policy fields from current defaults")
    policy = validate_craft_policy(strategy["policy"])
    uses = strategy["uses"]
    if not isinstance(uses, list) or len(uses) > policy["max_uses_per_chapter"]:
        raise KernelError("CRAFT_DENSITY_BUDGET", "Craft chapter density exceeds its configurable policy")
    ids: set[str] = set()
    scene_ids = None if scenes is None else {scene["scene_id"] for scene in scenes}
    for use in uses:
        if not isinstance(use, Mapping) or set(use) != {"use_id", "knowledge_card_asset_version_id", "content_hash", "mechanism_id", "mechanism_version", "scene_id", "role", "sequence", "decision", "intended_reader_effect", "adaptation_rationale", "prerequisite_resolution", "planning_use_site", "mechanism", "preservation_requirements"} or not str(use.get("use_id") or "") or use["use_id"] in ids:
            raise KernelError("CRAFT_USE_INVALID", "Craft uses require distinct frozen identities")
        ids.add(use["use_id"])
        mechanism = validate_craft_mechanism(use.get("mechanism"))
        if (use.get("mechanism_id"), use.get("mechanism_version")) != (mechanism["mechanism_id"], mechanism["version"]) or not use.get("knowledge_card_asset_version_id") or not str(use.get("content_hash") or "").startswith("sha256:"):
            raise KernelError("CRAFT_MECHANISM_DRIFT", "Craft use must bind an exact KnowledgeCard and mechanism version")
        if use.get("role") not in {"PRIMARY", "SECONDARY"} or type(use.get("sequence")) is not int or use["sequence"] < 1 or use.get("decision") not in {"ADOPT", "ADAPT"} or not isinstance(use.get("intended_reader_effect"), str) or not use["intended_reader_effect"].strip() or not use.get("preservation_requirements") or not isinstance(use.get("planning_use_site"), Mapping):
            raise KernelError("CRAFT_USE_INVALID", "Craft use requires role, sequence, effect, preservation and a planning location")
        site = use["planning_use_site"]
        if set(site) != {"target_pointer", "realization_excerpt", "expected_application", "preservation_requirements", "verification_checks", "craft_role", "craft_sequence", "intended_reader_effect"}:
            raise KernelError("CRAFT_USE_INVALID", "Craft use must preserve the exact versioned planning use-site schema")
        for text in (use["adaptation_rationale"], use["prerequisite_resolution"], site["target_pointer"], site["realization_excerpt"], site["expected_application"]):
            if not isinstance(text, str) or not text.strip():
                raise KernelError("CRAFT_USE_INVALID", "Craft use needs located planning text, prerequisite resolution and application rationale")
        if len(site["realization_excerpt"].strip()) < 8 or not re.fullmatch(r"/scene_plan/[0-9]+/.+", site["target_pointer"]) or (site["craft_role"], site["craft_sequence"], site["intended_reader_effect"]) != (use["role"], use["sequence"], use["intended_reader_effect"]):
            raise KernelError("CRAFT_USE_INVALID", "Craft application must retain its concrete scene pointer and role/effect judgment")
        for values in (use["preservation_requirements"], site["preservation_requirements"], site["verification_checks"]):
            if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
                raise KernelError("CRAFT_USE_INVALID", "Craft use must retain preservation and verification checks")
        if not set(site["preservation_requirements"] + mechanism["preservation_constraints"]).issubset(use["preservation_requirements"]):
            raise KernelError("CRAFT_PRESERVATION_DRIFT", "Craft use cannot discard mechanism or planning preservation constraints")
        if scene_ids is not None and use.get("scene_id") not in scene_ids:
            raise KernelError("CRAFT_SCENE_DRIFT", "Craft use references a scene outside the active Chapter plan")
    compositions = strategy["composition"]
    if not isinstance(compositions, list) or any(not isinstance(item, Mapping) or set(item) != {"scene_id", "ordered_use_ids", "intended_combined_reader_effect", "judgment_basis"} or item.get("judgment_basis") != "PROVIDER_PLANNING_TRANSLATION_WITH_DETERMINISTIC_COMPATIBILITY_CHECK" for item in compositions) or {item.get("scene_id") for item in compositions} != {use["scene_id"] for use in uses} or len(compositions) != len({item.get("scene_id") for item in compositions}):
        raise KernelError("CRAFT_COMPOSITION_INVALID", "Craft composition must account for every selected scene")
    for composition in compositions:
        group = sorted([use for use in uses if use["scene_id"] == composition["scene_id"]], key=lambda use: (use["sequence"], use["use_id"]))
        if len(group) > policy["max_uses_per_scene"] or sum(use["role"] == "PRIMARY" for use in group) != 1 or len({use["sequence"] for use in group}) != len(group) or composition.get("ordered_use_ids") != [use["use_id"] for use in group] or not composition.get("intended_combined_reader_effect"):
            raise KernelError("CRAFT_COMPOSITION_INVALID", "Scene Craft requires one primary role, unique ordering and bounded density")
        by_mechanism = {use["mechanism_id"]: use for use in group}
        if len(by_mechanism) != len(group):
            raise KernelError("CRAFT_COMPOSITION_INVALID", "A mechanism may appear only once per scene strategy")
        for use in group:
            contract = use["mechanism"]["composition"]
            if set(contract["conflicting"]) & set(by_mechanism) or set(contract["requires"]) - set(by_mechanism):
                raise KernelError("CRAFT_COMPOSITION_CONFLICT", "Craft dependencies and conflicts are checked at the concrete scene")
            if any(by_mechanism[identity]["sequence"] <= use["sequence"] for identity in contract["precedes"] if identity in by_mechanism):
                raise KernelError("CRAFT_COMPOSITION_SEQUENCE", "Craft sequence violates the selected mechanism dependency")
    return json.loads(json.dumps(strategy, ensure_ascii=False))
