from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .dynamics import CausalRequirement
from .mechanisms import WorldMechanism
from .foundation_schema import (
    WorldContractError,
    validate_world_foundation_shape,
    validate_world_rule_shape,
    world_value_type,
)


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
