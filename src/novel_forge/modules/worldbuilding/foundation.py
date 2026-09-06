from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .dynamics import CausalRequirement, require_contract_fields, require_text_fields


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

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> WorldRule:
        require_contract_fields(
            raw,
            required={
                "rule_id",
                "category",
                "statement",
                "enforcement",
                "applicability",
                "consequences",
            },
            optional={"predicate"},
        )
        require_text_fields(raw, ("rule_id", "category", "statement", "enforcement"))
        if any(
            not isinstance(raw[key], list)
            or any(not isinstance(v, str) or not v for v in raw[key])
            for key in ("applicability", "consequences")
        ):
            raise KernelError(
                "WORLD_RULE_CONTRACT_INVALID",
                "rule applicability and consequences must be string arrays",
            )
        rule = cls(
            str(raw["rule_id"]),
            str(raw["category"]),
            str(raw["statement"]),
            str(raw["enforcement"]),
            tuple(raw["applicability"]),
            tuple(raw["consequences"]),
            CausalRequirement.from_mapping(raw["predicate"])
            if raw.get("predicate") is not None
            else None,
        )
        if (
            not rule.rule_id
            or not rule.statement
            or rule.enforcement
            not in {"HARD", "QUANTITATIVE", "TEMPORAL", "SOFT_CAUSAL"}
            or not rule.applicability
            or not rule.consequences
            or (rule.enforcement != "SOFT_CAUSAL" and rule.predicate is None)
        ):
            raise KernelError(
                "WORLD_RULE_CONTRACT_INVALID",
                "deterministic world rules require an executable predicate; soft causal rules remain proposals",
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
    def from_mapping(cls, raw: Mapping[str, Any]) -> WorldFoundation:
        require_contract_fields(
            raw,
            required={
                "contract_version",
                "genre_profile",
                "compiled_scope",
                "sections",
                "rules",
                "entities",
            },
        )
        if raw.get("contract_version") != "world-foundation.v1":
            raise KernelError(
                "WORLD_FOUNDATION_VERSION_INVALID",
                "World Foundation requires its typed contract",
            )
        sections = raw.get("sections")
        if not isinstance(sections, dict) or "core_laws" not in sections:
            raise KernelError(
                "WORLD_FOUNDATION_CORE_REQUIRED",
                "progressive world compilation starts with core laws",
            )
        for key, value in sections.items():
            if key not in CORE_WORLD_ONTOLOGY and not key.startswith(
                ("genre:", "book:")
            ):
                raise KernelError(
                    "WORLD_FOUNDATION_EXTENSION_SCOPE_INVALID",
                    "world extensions must declare genre or Book ownership",
                )
            if (
                not isinstance(value, dict)
                or value.get("depth") not in {"SEED", "WORKING", "DETAILED"}
                or not str(value.get("content") or "").strip()
            ):
                raise KernelError(
                    "WORLD_FOUNDATION_SECTION_INVALID",
                    "compiled world sections require explicit depth and content",
                )
        if any(
            not isinstance(raw.get(key), list)
            or any(not isinstance(item, dict) for item in raw[key])
            for key in ("rules", "entities")
        ):
            raise KernelError(
                "WORLD_FOUNDATION_COLLECTION_INVALID",
                "world rules and entities must be arrays of structured objects",
            )
        rules = tuple(WorldRule.from_mapping(r) for r in raw["rules"])
        entities = raw.get("entities", [])
        ids = tuple(str(entity.get("entity_id") or "") for entity in entities)
        if (
            not rules
            or len({r.rule_id for r in rules}) != len(rules)
            or any(r.category not in sections for r in rules)
            or not ids
            or "" in ids
            or len(set(ids)) != len(ids)
        ):
            raise KernelError(
                "WORLD_FOUNDATION_IDENTITY_INVALID",
                "world rules and entities need unique identities in compiled categories",
            )
        if not raw.get("genre_profile") or raw.get("compiled_scope") not in {
            "BOOK",
            "VOLUME",
            "ARC",
        }:
            raise KernelError(
                "WORLD_FOUNDATION_SCOPE_INVALID",
                "progressive compilation requires genre and a bounded narrative scope",
            )
        return cls(
            "core-world-ontology.v1",
            str(raw["genre_profile"]),
            str(raw["compiled_scope"]),
            tuple(sorted(sections)),
            rules,
            ids,
        )
