from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from copy import deepcopy

from novel_forge.modules.command_kernel.errors import KernelError
from .dynamics import CausalRequirement
from .mechanisms import WorldMechanism
from .foundation_schema import (
    WorldContractError,
    validate_world_foundation_shape,
    validate_world_rule_shape,
    world_value_type,
)
from novel_forge.modules.narrative_state.reality import narrative_hash


CORE_WORLD_ONTOLOGY = frozenset(
    {
        "core_laws",
        "space_time_geography",
        "ecology_resources",
        "society_class",
        "politics_factions",
        "economy",
        "history_culture",
        "religion",
        "technology_power",
        "life_death_disease",
        "information_communication",
    }
)


def project_foundation_rule_background(*, reality: Mapping[str, Any], foundation: Mapping[str, Any], source_binding: Mapping[str, str]) -> dict[str, Any]:
    WorldFoundation.from_mapping(foundation)
    if set(source_binding) != {"asset_version_id", "content_hash"} or any(not isinstance(value, str) or not value for value in source_binding.values()):
        raise KernelError("WORLD_FOUNDATION_BACKGROUND_SOURCE_INVALID", "Background fields require an exact approved Foundation binding")
    result = deepcopy(dict(reality))
    entities = {entity["entity_id"]: (index, entity) for index, entity in enumerate(foundation["entities"])}
    fields = []
    for raw in foundation["rules"]:
        rule = WorldRule.from_mapping(raw)
        predicate = rule.predicate
        if predicate is None or predicate.state_kind.value != "world_rule" or predicate.entity_key not in entities:
            continue
        index, entity = entities[predicate.entity_key]
        if predicate.field not in entity or not isinstance(entity[predicate.field], (str, int, float, bool, type(None))):
            continue
        fields.append({"state_kind": "world_rule", "entity_key": predicate.entity_key, "field": predicate.field,
            "source_field_path": f"$.world_foundation.entities[{index}].{predicate.field}", "value": entity[predicate.field]})
    result["foundation_rule_background"] = {"contract_version": "foundation-rule-background.v1",
        "source_binding": dict(source_binding), "field_bindings": fields,
        "character_knowledge_granted": False, "accepted_history_mutation_allowed": False}
    return result


def foundation_revalidation_reality(source: Mapping[str, Any], proof: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not proof or proof.get("contract_version") != "world-host-revalidation.v3":
        return source["reality"]
    binding = proof["foundation_binding"]
    if (source["contract_version"] != "world-preparation-source.v3"
        or proof.get("character_knowledge_granted") is not False
        or proof.get("accepted_history_mutation_allowed") is not False
        or not any(all(rule.get(key) == binding[key] for key in ("asset_version_id", "content_hash"))
            for rule in source["reality"].get("world_rule_constraints", []))):
        raise KernelError("WORLD_FOUNDATION_BACKGROUND_SOURCE_INVALID", "The background view must retain its frozen Foundation and semantic boundaries")
    result = project_foundation_rule_background(reality=source["reality"], foundation=source["world_foundation"], source_binding=binding)
    if narrative_hash(result["foundation_rule_background"]) != proof.get("background_projection_hash"):
        raise KernelError("WORLD_HOST_REVALIDATION_DRIFT", "The derived background view differs from its registered proof")
    return result


@dataclass(frozen=True, slots=True)
class WorldRule:
    rule_id: str
    category: str
    statement: str
    enforcement: str
    applicability: tuple[str, ...]
    consequences: tuple[str, ...]
    predicate: CausalRequirement | None
    mechanism: WorldMechanism | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> WorldRule:
        validate_world_rule_shape(raw)
        if raw["enforcement"] != "SOFT_CAUSAL" and raw.get("predicate") is None:
            raise WorldContractError("WORLD_RULE_CONTRACT_INVALID", [{
                "code": "WORLD_FIELD_REQUIRED", "field_path": "$.predicate",
                "expected_type": "object", "actual_type": "null" if "predicate" in raw else "missing",
                "constraint": "Deterministic rules require an executable predicate.",
            }])
        if (raw["enforcement"] == "MECHANISM") != (raw.get("mechanism") is not None):
            raise WorldContractError("WORLD_RULE_CONTRACT_INVALID", [{
                "code": "WORLD_FIELD_VALUE_INVALID", "field_path": "$.mechanism",
                "expected_type": "object" if raw["enforcement"] == "MECHANISM" else "null",
                "actual_type": "object" if raw.get("mechanism") is not None else "null",
                "constraint": "Only MECHANISM enforcement supplies a typed mechanism.",
            }])
        predicate = None
        if raw.get("predicate") is not None:
            source = raw["predicate"]
            if source["operator"] != "EXISTS" and "value" not in source:
                raise WorldContractError("CAUSAL_REQUIREMENT_INVALID", [{
                    "code": "WORLD_FIELD_REQUIRED", "field_path": "$.predicate.value",
                    "expected_type": "string|number|boolean|null", "actual_type": "missing",
                    "constraint": "Only EXISTS may omit a predicate value.",
                }])
            try:
                predicate = CausalRequirement.from_mapping(source)
            except (KernelError, OverflowError) as error:
                code = error.code if isinstance(error, KernelError) else "CAUSAL_QUANTITY_INVALID"
                constraint = error.message if isinstance(error, KernelError) else "Quantity exceeds the causal evaluator's finite numeric range."
                raise WorldContractError(code, [{
                    "code": "WORLD_FIELD_VALUE_INVALID", "field_path": "$.predicate.value",
                    "expected_type": "number", "actual_type": world_value_type(source.get("value")),
                    "constraint": constraint,
                }]) from error
        rule = cls(
            raw["rule_id"],
            raw["category"],
            raw["statement"],
            raw["enforcement"],
            tuple(raw["applicability"]),
            tuple(raw["consequences"]),
            predicate,
            WorldMechanism.from_mapping(raw["mechanism"]) if raw.get("mechanism") is not None else None,
        )
        return rule


@dataclass(frozen=True, slots=True)
class WorldFoundation:
    ontology_version: str
    genre_profile: str
    compiled_scope: str
    sections: tuple[str, ...]
    rules: tuple[WorldRule, ...]
    entity_ids: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], *, expected_compiled_scope: str | None = None
    ) -> WorldFoundation:
        validate_world_foundation_shape(raw, expected_compiled_scope=expected_compiled_scope)
        sections = raw.get("sections")
        if not isinstance(sections, dict) or "core_laws" not in sections:
            raise WorldContractError("WORLD_FOUNDATION_CORE_REQUIRED", [{
                "code": "WORLD_FIELD_REQUIRED", "field_path": "$.sections.core_laws",
                "expected_type": "object", "actual_type": "missing",
                "constraint": "Progressive world compilation starts with core laws.",
            }])
        for key in sections:
            if key not in CORE_WORLD_ONTOLOGY and not key.startswith(
                ("genre:", "book:")
            ):
                raise WorldContractError("WORLD_FOUNDATION_EXTENSION_SCOPE_INVALID", [{
                    "code": "WORLD_FIELD_UNKNOWN", "field_path": f"$.sections.{key}",
                    "expected_type": "object", "actual_type": "object",
                    "constraint": "Section keys must be core ontology dimensions or genre:/book: extensions.",
                }])
        rules = []
        for index, source in enumerate(raw["rules"]):
            try:
                rules.append(WorldRule.from_mapping(source))
            except WorldContractError as error:
                raise WorldContractError(error.code, [{
                    **item, "field_path": f"$.rules[{index}]" + item["field_path"][1:]
                } for item in error.diagnostics]) from error
        rules = tuple(rules)
        entities = raw.get("entities", [])
        ids = tuple(entity["entity_id"] for entity in entities)
        diagnostics = []
        seen_rules = set()
        for index, rule in enumerate(rules):
            if rule.rule_id in seen_rules or rule.category not in sections:
                field = "rule_id" if rule.rule_id in seen_rules else "category"
                diagnostics.append({
                    "code": "WORLD_FIELD_IDENTITY_INVALID", "field_path": f"$.rules[{index}].{field}",
                    "expected_type": "string", "actual_type": "string",
                    "constraint": "Rule identities must be unique and categories must resolve to compiled sections.",
                })
            seen_rules.add(rule.rule_id)
        seen_entities = set()
        for index, entity_id in enumerate(ids):
            if entity_id in seen_entities:
                diagnostics.append({
                    "code": "WORLD_FIELD_IDENTITY_INVALID", "field_path": f"$.entities[{index}].entity_id",
                    "expected_type": "string", "actual_type": "string",
                    "constraint": "World entity identities must be unique.",
                })
            seen_entities.add(entity_id)
        if diagnostics:
            raise WorldContractError("WORLD_FOUNDATION_IDENTITY_INVALID", diagnostics)
        return cls(
            "core-world-ontology.v1",
            raw["genre_profile"],
            raw["compiled_scope"],
            tuple(sorted(sections)),
            rules,
            ids,
        )
