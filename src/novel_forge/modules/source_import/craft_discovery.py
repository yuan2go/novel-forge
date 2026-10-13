from __future__ import annotations

from dataclasses import replace
from typing import Any

from novel_forge.modules.mkaos_authority.craft import craft_mechanism_schema

CRAFT_DISCOVERY_POLICY = "narrative-craft-abstraction.v1"
CRAFT_DISCOVERY_ROUTING = "source-analysis-routing.craft.v1"
WRITING_METHODS_ROUTING = "source-analysis-routing.writing-methods.v1"
WRITING_METHODS_EVIDENCE_ROUTING = "source-analysis-routing.writing-methods.v2"
WRITING_METHOD_ROUTES = {WRITING_METHODS_ROUTING, WRITING_METHODS_EVIDENCE_ROUTING}


def craft_discovery_strategy(strategy: Any) -> Any:
    if strategy.routing_policy_version not in {CRAFT_DISCOVERY_ROUTING, *WRITING_METHOD_ROUTES}:
        return strategy
    if strategy.routing_policy_version in WRITING_METHOD_ROUTES and strategy.content_type.value != "WRITING_THEORY":
        raise ValueError("Writing methods require a governed writing-theory profile")
    if strategy.content_type.value not in {"WEB_NOVEL", "PUBLISHED_FICTION", "CLASSIC_LITERATURE", "WRITING_THEORY"}:
        raise ValueError("Craft discovery requires a governed fiction or writing-theory profile")
    return replace(strategy, profile_id="craft." + strategy.profile_id, profile_version="1.0", abstraction_policy_version=CRAFT_DISCOVERY_POLICY)


def craft_discovery_schema(*, grounded: bool, observation_id: str) -> dict[str, Any]:
    from .execution_contracts import MKAOS_STAGE, content_intelligence_output_schema, grounded_knowledge_output_schema

    schema = grounded_knowledge_output_schema() if grounded else content_intelligence_output_schema(MKAOS_STAGE)
    craft = craft_mechanism_schema()
    craft["properties"]["version"]["const"] = 1
    for field in ("validation_evidence", "effect_evidence"):
        craft["properties"][field]["maxItems"] = 0
    provenance = craft["properties"]["provenance"]["properties"]
    for field, value in {
        "origin": "SOURCE_ABSTRACTION", "confidence": "HYPOTHESIS",
        "abstraction_policy_version": CRAFT_DISCOVERY_POLICY,
        "supersedes_card_asset_version_id": "",
    }.items():
        provenance[field]["const"] = value
    provenance["source_observation_asset_version_ids"]["const"] = [observation_id]
    schema["properties"].update({"craft_mechanism": craft, "usage_role": {"type": "string", "const": "MECHANISM"}})
    schema["properties"]["knowledge_kind"]["const"] = "NARRATIVE_INTELLIGENCE"
    schema["properties"]["semantic_family"]["const"] = "NARRATIVE_MECHANISM"
    schema["required"].extend(["craft_mechanism", "usage_role"])
    return schema


def validate_discovery_schema(schema: dict[str, Any]) -> bool:
    try:
        ids = schema["properties"]["craft_mechanism"]["properties"]["provenance"]["properties"]["source_observation_asset_version_ids"]["const"]
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or not ids[0]:
            return False
        return schema == craft_discovery_schema(grounded="source_finding_codes" in schema["properties"], observation_id=ids[0])
    except (KeyError, TypeError):
        return False
