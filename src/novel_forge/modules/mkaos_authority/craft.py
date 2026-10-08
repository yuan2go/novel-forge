from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

CRAFT_SCHEMA_VERSION = "narrative-craft-mechanism.v1"
CRAFT_SCHEMA_V2 = "narrative-craft-mechanism.v2"
CRAFT_FAMILIES = frozenset({
    "ATTENTION", "ACTION", "DIALOGUE", "CHARACTERIZATION", "EMOTION", "SUSPENSE",
    "REVEAL", "SCENE", "PACING", "DESCRIPTION", "RELATIONSHIP", "HUMOR",
    "PAYOFF", "SERIALIZATION", "PROSE", "WUXIA_XUANHUAN",
})
CRAFT_ORIGINAL_POLICY = "repository-original-craft-v1"
_TEXT_FIELDS = {
    "name", "narrative_problem", "desired_reader_effect", "abstract_mechanism",
    "planning_guidance", "scene_realization_guidance", "prose_realization_guidance",
}
_LIST_FIELDS = {
    "prerequisites", "applicability_conditions", "contraindications", "success_signals",
    "failure_modes", "review_checks", "repair_strategies", "preservation_constraints",
}


def craft_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def craft_semantic_hash(mechanism: Mapping[str, Any]) -> str:
    return craft_hash({key: mechanism[key] for key in sorted((_TEXT_FIELDS - {"name"}) | _LIST_FIELDS | {"composition"})})


def _fail(message: str) -> None:
    raise KernelError("MKAOS_CRAFT_INVALID", message)


def _strings(value: Any, field: str, *, empty: bool = False) -> None:
    if not isinstance(value, list) or len(value) > 32 or (not value and not empty):
        _fail(f"{field} requires a bounded string list")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in value) or len(set(value)) != len(value):
        _fail(f"{field} contains invalid or duplicate values")


def validate_craft_mechanism(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("Craft mechanism must be an object")
    required = _TEXT_FIELDS | _LIST_FIELDS | {
        "schema_version", "mechanism_id", "version", "family", "affinity", "composition",
        "provenance", "validation_evidence", "effect_evidence",
    }
    if value.get("schema_version") == CRAFT_SCHEMA_V2:
        required.add("affinity_evidence")
    if set(value) != required or value.get("schema_version") not in {CRAFT_SCHEMA_VERSION, CRAFT_SCHEMA_V2}:
        _fail("Craft schema/version or exact field set is invalid")
    if not isinstance(value["mechanism_id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,79}", value["mechanism_id"]):
        _fail("Craft mechanism_id must be a stable slug")
    if type(value["version"]) is not int or value["version"] < 1 or not isinstance(value["family"], str) or value["family"] not in CRAFT_FAMILIES:
        _fail("Craft version or family is invalid")
    for field in _TEXT_FIELDS:
        if not isinstance(value[field], str) or not value[field].strip() or len(value[field]) > 2000:
            _fail(f"{field} requires bounded abstract guidance")
    for field in _LIST_FIELDS:
        _strings(value[field], field)
    for field, keys in (
        ("affinity", {"genre", "scene_type", "pov", "pacing"}),
        ("composition", {"compatible", "complementary", "conflicting", "requires", "precedes"}),
    ):
        if not isinstance(value[field], Mapping) or set(value[field]) != keys:
            _fail(f"{field} has an invalid shape")
        for key, items in value[field].items():
            _strings(items, f"{field}.{key}", empty=True)
            if field == "composition" and any(not re.fullmatch(r"[a-z][a-z0-9-]{2,79}", item) or item == value["mechanism_id"] for item in items):
                _fail("Composition must reference distinct stable mechanism IDs")
    composition = value["composition"]
    if set(composition["conflicting"]) & set(composition["compatible"] + composition["complementary"] + composition["requires"]):
        _fail("Composition cannot require or encourage a conflicting mechanism")
    provenance = value["provenance"]
    if not isinstance(provenance, Mapping) or set(provenance) != {
        "origin", "attribution", "abstraction_policy_version", "source_observation_asset_version_ids",
        "confidence", "supersedes_card_asset_version_id",
    }:
        _fail("Craft provenance is incomplete")
    if not isinstance(provenance["origin"], str) or provenance["origin"] not in {"REPOSITORY_ORIGINAL", "SOURCE_ABSTRACTION"} or not isinstance(provenance["confidence"], str) or provenance["confidence"] not in {"HYPOTHESIS", "EDITORIAL_REVIEWED"}:
        _fail("Craft provenance origin/confidence is invalid")
    for field in ("attribution", "abstraction_policy_version"):
        if not isinstance(provenance[field], str) or not provenance[field].strip() or len(provenance[field]) > 1000:
            _fail(f"Craft provenance.{field} is invalid")
    source_ids = provenance["source_observation_asset_version_ids"]
    _strings(source_ids, "source_observation_asset_version_ids", empty=True)
    if (provenance["origin"] == "SOURCE_ABSTRACTION") != bool(source_ids):
        _fail("Source abstractions require Observation identities; originals cannot claim Source evidence")
    if not isinstance(provenance["supersedes_card_asset_version_id"], str) or (provenance["origin"] == "SOURCE_ABSTRACTION" and value["version"] > 1 and not provenance["supersedes_card_asset_version_id"].strip()):
        _fail("Revised mechanisms must name the preceding governed Card")
    for field in ("validation_evidence", "effect_evidence"):
        evidence = value[field]
        if not isinstance(evidence, list) or len(evidence) > 64:
            _fail(f"{field} must be a bounded evidence reference list")
        for item in evidence:
            if not isinstance(item, Mapping) or set(item) != {"kind", "asset_version_id", "claim"}:
                _fail("Craft evidence must bind its kind, immutable asset and claim")
            if not isinstance(item["kind"], str) or item["kind"] not in {"STRUCTURAL", "MODEL_JUDGMENT", "EDITORIAL", "HUMAN_READER", "CONTROLLED_COMPARISON"}:
                _fail("Craft evidence class is invalid")
            if any(not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > 1000 for key in item):
                _fail("Craft evidence references must be explicit and bounded")
    if value.get("schema_version") == CRAFT_SCHEMA_V2:
        bindings = value["affinity_evidence"]
        if not isinstance(bindings, list) or len(bindings) > 64:
            _fail("Affinity evidence requires bounded exact bindings")
        evidence_ids = {item["asset_version_id"] for item in value["effect_evidence"] if item["kind"] in {"EDITORIAL", "HUMAN_READER", "CONTROLLED_COMPARISON"}}
        seen = set()
        for binding in bindings:
            if not isinstance(binding, Mapping) or set(binding) != {"dimension", "value", "asset_version_id"}:
                _fail("Affinity evidence requires dimension, value and effect evidence identity")
            dimension, tag, evidence_id = (binding[key] for key in ("dimension", "value", "asset_version_id"))
            if any(not isinstance(item, str) or not item.strip() for item in (dimension, tag, evidence_id)):
                _fail("Affinity evidence bindings must be explicit strings")
            if dimension not in value["affinity"] or tag not in value["affinity"][dimension] or evidence_id not in evidence_ids:
                _fail("Affinity evidence must bind an exact descriptive tag and governed effect evidence")
            identity = (dimension, tag, evidence_id)
            if identity in seen:
                _fail("Affinity evidence bindings must be unique")
            seen.add(identity)
    if provenance["confidence"] == "EDITORIAL_REVIEWED" and not any(item["kind"] == "EDITORIAL" for item in value["validation_evidence"]):
        _fail("Editorial confidence requires an explicit editorial validation evidence reference")
    from novel_forge.modules.mkaos_authority.domain import assert_abstract_content_safe
    assert_abstract_content_safe(value)
    return deepcopy(dict(value))


def core_catalog() -> list[dict[str, Any]]:
    from novel_forge.modules.mkaos_authority.craft_catalog import CORE_CRAFT_MECHANISMS
    catalog = [validate_craft_mechanism(item) for item in CORE_CRAFT_MECHANISMS]
    ids = {item["mechanism_id"] for item in catalog}
    if len(ids) != len(catalog):
        _fail("Core catalog contains duplicate mechanism identities")
    for item in catalog:
        if item["provenance"]["origin"] != "REPOSITORY_ORIGINAL" or item["provenance"]["supersedes_card_asset_version_id"]:
            _fail("Core catalog templates must be original and independent of project Card identities")
        if any(ref not in ids for refs in item["composition"].values() for ref in refs):
            _fail("Core catalog composition references an unavailable mechanism")
    return catalog


def core_catalog_hash() -> str:
    return craft_hash(core_catalog())


def require_core_mechanism(mechanism_id: str, catalog_hash: str) -> dict[str, Any]:
    if catalog_hash != core_catalog_hash():
        raise KernelError("MKAOS_CRAFT_CATALOG_DRIFT", "The reviewed exact catalog hash does not match this application build")
    for item in core_catalog():
        if item["mechanism_id"] == mechanism_id:
            return item
    raise KernelError("MKAOS_CRAFT_NOT_FOUND", "Unknown core Craft mechanism")


def craft_candidate(mechanism: Mapping[str, Any]) -> dict[str, Any]:
    craft = validate_craft_mechanism(mechanism)
    return {
        "concept_name": craft["name"], "discipline": "narrative_design",
        "abstract_principle": craft["abstract_mechanism"],
        "constraints": craft["preservation_constraints"],
        "conflict_generators": [craft["narrative_problem"]],
        "review_checks": craft["review_checks"],
        "copyright_boundaries": ["只迁移抽象机制，不迁移作品表达、实体、独特事件序列或替名模板。"],
        "knowledge_kind": "NARRATIVE_INTELLIGENCE", "semantic_family": "NARRATIVE_MECHANISM",
        "mechanism": craft["abstract_mechanism"], "applicability": craft["applicability_conditions"],
        "failure_conditions": craft["contraindications"], "repetition_key": craft["mechanism_id"],
        "selection_tags": {"genre": craft["affinity"]["genre"] if craft["schema_version"] == CRAFT_SCHEMA_VERSION else [], "conflict": craft["affinity"]["scene_type"] if craft["schema_version"] == CRAFT_SCHEMA_VERSION else [], "reader_effect": [craft["desired_reader_effect"]], "theme": []},
        "originality_boundary": {"source_specific_sequence_reusable": False, "named_entity_substitution_allowed": False, "expression_reuse_allowed": False},
        "usage_role": "MECHANISM", "craft_mechanism": craft,
    }


def craft_mechanism_schema(version: str = CRAFT_SCHEMA_VERSION) -> dict[str, Any]:
    if version not in {CRAFT_SCHEMA_VERSION, CRAFT_SCHEMA_V2}:
        _fail("Unsupported Craft schema version")
    def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "required": sorted(properties), "additionalProperties": False}

    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    strings = {"type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 1000}}
    refs = {**strings, "minItems": 0}
    evidence = {"type": "array", "maxItems": 64, "items": object_schema({
        "kind": {"type": "string", "enum": ["STRUCTURAL", "MODEL_JUDGMENT", "EDITORIAL", "HUMAN_READER", "CONTROLLED_COMPARISON"]},
        "asset_version_id": {"type": "string", "minLength": 1, "maxLength": 1000},
        "claim": {"type": "string", "minLength": 1, "maxLength": 1000},
    })}
    result = object_schema({
        **{key: deepcopy(text) for key in sorted(_TEXT_FIELDS)},
        **{key: deepcopy(strings) for key in sorted(_LIST_FIELDS)},
        "schema_version": {"type": "string", "const": version},
        "mechanism_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{2,79}$"},
        "version": {"type": "integer", "minimum": 1},
        "family": {"type": "string", "enum": sorted(CRAFT_FAMILIES)},
        "affinity": object_schema({key: deepcopy(refs) for key in ("genre", "scene_type", "pov", "pacing")}),
        "composition": object_schema({key: deepcopy(refs) for key in ("compatible", "complementary", "conflicting", "requires", "precedes")}),
        "provenance": object_schema({
            "origin": {"type": "string", "enum": ["REPOSITORY_ORIGINAL", "SOURCE_ABSTRACTION"]},
            "attribution": {"type": "string", "minLength": 1, "maxLength": 1000},
            "abstraction_policy_version": {"type": "string", "minLength": 1, "maxLength": 1000},
            "source_observation_asset_version_ids": deepcopy(refs),
            "confidence": {"type": "string", "enum": ["HYPOTHESIS", "EDITORIAL_REVIEWED"]},
            "supersedes_card_asset_version_id": {"type": "string"},
        }),
        "validation_evidence": deepcopy(evidence), "effect_evidence": deepcopy(evidence),
    })
    if version == CRAFT_SCHEMA_V2:
        result["properties"]["affinity_evidence"] = {"type": "array", "maxItems": 64, "uniqueItems": True,
            "items": object_schema({"dimension": {"type": "string", "enum": ["genre", "scene_type", "pov", "pacing"]},
                "value": deepcopy(text), "asset_version_id": deepcopy(text)})}
        result["required"].append("affinity_evidence")
    return result
