from copy import deepcopy

from novel_forge.modules.hierarchical_planning.domain import (
    PLAN_REALIZATION,
    PlanContractType,
    RealizationLevel,
    _realization_rank,
)


def bind_semantic_fields(schema: dict, scope: PlanContractType) -> dict:
    value = deepcopy(schema)
    level = PLAN_REALIZATION[scope]
    value["properties"]["realization_level"] = {"type": "string", "const": level.value}
    for manifest in ("world_realization", "character_realization"):
        item = value["properties"][manifest]["items"]
        current, future = deepcopy(item), deepcopy(item)
        current["properties"]["narrative_relevance"] = {"type": "string", "const": "CURRENT"}
        current["properties"]["realization_level"]["enum"] = [
            candidate.value for candidate in RealizationLevel
            if _realization_rank(candidate) >= _realization_rank(level)
        ]
        future["properties"]["narrative_relevance"]["enum"] = ["NEAR_FUTURE", "FUTURE"]
        value["properties"][manifest]["items"] = {"anyOf": [current, future]}
    if "scene_plan" in value["properties"]:
        scene = value["properties"]["scene_plan"]["items"]["properties"]
        scene["narrative_time_relation"]["description"] = (
            "Relations compare scenes in this returned plan, not earlier chapters. "
            "The first scene on each timeline must use ESTABLISHES; this does not replay past events. "
            "Later ADVANCES, FLASHFORWARD or ELLIPSIS starts after the previous end; PARALLEL "
            "overlaps it; FLASHBACK ends before its start. End must not precede start."
        )
        scene["accessible_knowledge"]["description"] = (
            "Only fact IDs already in the POV's frozen accepted known_fact_ids, or declared "
            "CHARACTER_KNOWLEDGE KNOWN gains disclosed in an earlier scene where this character "
            "participated. Never write prose summaries here or invent accepted IDs. A gain in "
            "this scene is not accessible at entry. Selected working-prose experiences may be "
            "continued in entry_state, causal_trigger, beats and actions without populating "
            "accepted-knowledge fields. Use [] when no eligible IDs exist."
        )
    return value
