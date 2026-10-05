from __future__ import annotations
import json
from typing import Any, Mapping
from novel_forge.modules.book_design_authority.foundation import FoundationRole
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.domain import GENERATOR_CATALOG

FOUNDATION_GENERATORS = {
    "creative.candidates.generate": FoundationRole.CREATIVE_FOUNDATION,
    "theme.candidates.generate": FoundationRole.THEME_CONTRACT,
    "ending.intent.generate": FoundationRole.ENDING_INTENT,
    "reader.promise.generate": FoundationRole.READER_PROMISE,
    "world.design.generate": FoundationRole.WORLD_BIBLE,
    "character.cast.generate": FoundationRole.CHARACTER_CAST,
}
FOUNDATION_CAPABILITIES = tuple(
    (name, GENERATOR_CATALOG[name].capability) for name in FOUNDATION_GENERATORS
)
FOUNDATION_INPUT_ROLES = {
    name: (
        "creative_brief",
        *(parent.value.lower() for parent in role.required_parents),
    )
    for name, role in FOUNDATION_GENERATORS.items()
}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _text() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _texts() -> dict[str, Any]:
    return {"type": "array", "items": _text(), "maxItems": 24}


def _records(fields: str, *, minimum: int = 1, maximum: int = 16) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _object({field: _text() for field in fields.split()}),
        "minItems": minimum,
        "maxItems": maximum,
    }


def _apply_work_schema(properties: dict[str, Any], role: FoundationRole) -> None:
    optional = {
        FoundationRole.CREATIVE_FOUNDATION: "subgenre core_desire core_fear core_conflict serialization_potential",
        FoundationRole.ENDING_INTENT: "protagonist_cost",
    }
    for field in optional.get(role, "").split():
        properties[field] = {"type": ["string", "null"], "minLength": 1}
    if role is FoundationRole.THEME_CONTRACT:
        properties["choice_tests"]["minItems"] = 0
        properties["choice_tests"]["items"]["properties"]["cost"] = {
            "type": ["string", "null"],
            "minLength": 1,
        }
    if role is FoundationRole.READER_PROMISE:
        properties["setup_progress_payoff"]["minItems"] = 0
    if role is FoundationRole.WORLD_BIBLE:
        for field in ("cost", "exception", "consequence"):
            properties["rules"]["items"]["properties"][field] = {
                "type": ["string", "null"],
                "minLength": 1,
            }
    if role is FoundationRole.CHARACTER_CAST:
        character = properties["characters"]["items"]["properties"]
        for field in "need fear wound false_belief private_history arc_direction contradiction relationship_function".split():
            character[field] = {"type": ["string", "null"], "minLength": 1}
        character["voice_anchors"]["minItems"] = 0
    properties["applicability"] = {
        "type": "array",
        "maxItems": 256,
        "items": _object(
            {
                "field_path": _text(),
                "status": {
                    "type": "string",
                    "enum": [
                        "APPLICABLE",
                        "NOT_APPLICABLE",
                        "PROHIBITED",
                        "UNDETERMINED",
                    ],
                },
                "rationale": _text(),
            }
        ),
    }


def validate_foundation_applicability(
    payload: Mapping[str, Any], schema: Mapping[str, Any]
) -> None:
    nullable: dict[str, Any] = {}

    def visit(value: Any, contract: Mapping[str, Any], path: str) -> None:
        if isinstance(contract.get("type"), list) and "null" in contract["type"]:
            nullable[path] = value
        if isinstance(value, Mapping):
            for field, child in contract.get("properties", {}).items():
                if field in value:
                    visit(value[field], child, f"{path}.{field}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, contract.get("items", {}), f"{path}[{index}]")

    visit(payload, schema, "$")
    declarations: dict[str, Mapping[str, Any]] = {}
    for item in payload.get("applicability", []):
        path = item["field_path"]
        if path not in nullable or path in declarations:
            raise KernelError(
                "FOUNDATION_APPLICABILITY_INVALID",
                "Applicability must identify a unique optional field in this candidate",
            )
        declarations[path] = item
        if (nullable[path] is None) != (item["status"] != "APPLICABLE"):
            raise KernelError(
                "FOUNDATION_APPLICABILITY_INVALID",
                "Applicability and the exact field value disagree",
            )
    if any(
        value is None and path not in declarations for path, value in nullable.items()
    ):
        raise KernelError(
            "FOUNDATION_APPLICABILITY_REQUIRED",
            "Null features require an explicit status and rationale; missing and inapplicable are distinct",
        )


def foundation_output_schema(
    generator: str, *, work_requirements: bool = False
) -> dict[str, Any]:
    role = FOUNDATION_GENERATORS[generator]
    properties: dict[str, Any] = {
        "objective": _text(),
        "constraints": _texts(),
        "prohibited_outcomes": _texts(),
    }
    if role is FoundationRole.CREATIVE_FOUNDATION:
        properties.update(
            {
                field: _text()
                for field in (
                    "target_reader why_worth_writing genre subgenre core_desire core_fear "
                    "core_conflict narrative_engine differentiation emotional_contract serialization_potential"
                ).split()
            }
        )
        properties["style_profile"] = _object(
            {
                "narrator": _text(),
                "pov": _text(),
                "genre_conventions": _texts(),
                "constraints": _texts(),
                "original_examples": _records("purpose example explanation", maximum=6),
            }
        )
    elif role is FoundationRole.THEME_CONTRACT:
        properties.update(
            {
                "thematic_question": _text(),
                "opposing_answers": _texts(),
                "choice_tests": _records("choice cost thematic_pressure"),
            }
        )
    elif role is FoundationRole.ENDING_INTENT:
        properties.update(
            {
                "ending_direction": _text(),
                "protagonist_cost": _text(),
                "closure_conditions": _texts(),
                "unacceptable_shortcuts": _texts(),
            }
        )
    elif role is FoundationRole.READER_PROMISE:
        properties.update(
            {
                "reader_promise": _text(),
                "setup_progress_payoff": _records("promise setup progress payoff"),
                "disappointment_risks": _texts(),
            }
        )
    elif role is FoundationRole.WORLD_BIBLE:
        properties.update(
            {
                "rules": _records("rule cost exception consequence narrative_function"),
                "world_foundation_json": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 24000,
                    "description": "JSON encoded world-foundation.v1 object conforming to foundation_task.world_contract.schema. compiled_scope is exactly the frozen single string, never an array of enum choices. Decoded inner fields are strictly validated before candidate persistence.",
                },
                "dimensions": _records(
                    "dimension scope current_need definition constraints extension_trigger",
                    maximum=20,
                ),
                "factions": _records(
                    "faction_id goal resources pressure information_access", minimum=0
                ),
                "deferred_dimensions": _records("dimension reason trigger", minimum=0),
            }
        )
    else:
        character_fields = (
            "character_id name narrative_function desire need fear wound false_belief "
            "moral_boundary agency capability weakness voice private_history relationship_function arc_direction "
            "background contradiction behavioral_pattern risk_preference"
        )
        character = _object({field: _text() for field in character_fields.split()})
        character["properties"].update(
            {
                "aliases": _texts(),
                "pronouns": _texts(),
                "values": _texts(),
                "voice_anchors": _records("situation utterance motivation", maximum=4),
            }
        )
        character["required"] = list(character["properties"])
        properties["characters"] = {
            "type": "array",
            "items": character,
            "minItems": 1,
            "maxItems": 12,
        }
        properties["relationships"] = _records(
            "source_character_id target_character_id tension dependency change_pressure",
            minimum=0,
        )
    if work_requirements:
        _apply_work_schema(properties, role)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(properties),
    }


def foundation_task(
    generator: str, *, work_requirements: bool = False, aligned_methods: bool = False
) -> dict[str, Any]:
    role = FOUNDATION_GENERATORS[generator]
    tasks = {
        FoundationRole.CREATIVE_FOUNDATION: "Develop a distinctive, sustainable conflict from the brief. Explain reader value, choices and costs; create original operational style examples, never imitate reference prose.",
        FoundationRole.THEME_CONTRACT: "Turn the approved premise into opposing thematic answers tested by costly character decisions; avoid a moral slogan.",
        FoundationRole.ENDING_INTENT: "Design an earned ending direction with irreversible costs, required closures and forbidden shortcuts; this is future intent, not a predetermined accepted event.",
        FoundationRole.READER_PROMISE: "Specify what readers may expect, observable preparation, escalation and payoff; distinguish promise from fact and leave timing to Planning.",
        FoundationRole.WORLD_BIBLE: "Compile only world depth needed by the approved conflict. Consider laws, geography/time, resources, power, history/culture, existence and information; explain deferred dimensions and extension triggers. Rules need costs, exceptions and story consequences.",
        FoundationRole.CHARACTER_CAST: "Build a cast with distinct narrative functions, then deepen each through desire, fear, contradiction, beliefs and choices. Derive voice anchors from biography and motives. Ground relationships and capabilities in the approved world, never invent accepted history.",
    }
    if work_requirements:
        tasks = {
            FoundationRole.CREATIVE_FOUNDATION: "Develop this work's premise, narrative purpose, reader experience and sustainable form from the author brief and selected design. Conflict and serialization are choices, not universal requirements. Create original operational style examples, never imitate reference prose.",
            FoundationRole.THEME_CONTRACT: "Express this work's thematic question and suitable means of exploring it. Observation, ambiguity, deliberation or explicit exposition may be appropriate. Costly choices and opposing answers are optional methods unless selected by this work.",
            FoundationRole.ENDING_INTENT: "Design an ending direction consistent with this work, including an open ending when selected. Preserve applicable commitments and prohibitions. Do not invent irreversible costs, closure or a sequel bridge. Intent is not accepted history.",
            FoundationRole.READER_PROMISE: "Describe the intended reader experience and only commitments this work actually makes. Preparation, escalation, rewards and payoff are conditional strategies; do not turn permission into a promise or impose a commercial rhythm.",
            FoundationRole.WORLD_BIBLE: "Compile the world depth needed by this work using the frozen typed world contract. Preserve laws, limits and knowledge boundaries. A rule need not impose a cost; distinguish an inapplicable cost from an unknown consequence. Explain deferred dimensions and extension triggers.",
            FoundationRole.CHARACTER_CAST: "Design characters suitable for this work and distinct voices grounded in their circumstances. Wounds, false beliefs, secrets and transformation are optional, not mandatory identities. Preserve exact references, capabilities, knowledge and approved initial conditions; never invent accepted history.",
        }
    return {
        "contract_version": "foundation-generation.v3" if aligned_methods else "foundation-generation.v2"
        if work_requirements
        else "foundation-generation.v1",
        "role": role.value,
        "task": tasks[role],
        "parent_roles": [parent.value for parent in role.required_parents],
        "authority_boundary": "Generate a candidate only. Upstream versions are immutable. No Canon, knowledge or accepted-history writes. Independent diagnosis and activation follow.",
        **(
            {"world_contract": world_generation_contract()}
            if role is FoundationRole.WORLD_BIBLE
            else {}
        ),
        "repair_contract": "When repair evidence is present, address each unresolved diagnosis, preserve unaffected constraints and explain uncertainty through the candidate rather than silently replacing upstream decisions.",
        **(
            {
                "applicability_contract": "All fields remain required. Use null for an inapplicable or prohibited optional feature and declare its exact field path, status and rationale in applicability. UNDETERMINED records uncertainty, not permission to invent. Empty collections mean confirmed zero members, never missing input. Apply author requirements and accepted design at their original scope and strength; report conflicts rather than silently replacing them."
            }
            if work_requirements
            else {}
        ),
    }


def foundation_envelope(
    *, generator: str, inputs: tuple[Any, ...], work_requirements: bool = False, aligned_methods: bool = False
) -> dict[str, Any]:
    role = FOUNDATION_GENERATORS[generator]
    by_role = {item.role: item for item in inputs}
    if set(by_role) != set(FOUNDATION_INPUT_ROLES[generator]):
        raise KernelError(
            "FOUNDATION_INPUT_BOUNDARY_INVALID",
            "Foundation input roles differ from the frozen dependency contract",
        )
    return {
        "contract_version": "foundation-generation.v3" if aligned_methods else "foundation-generation.v2"
        if work_requirements
        else "foundation-generation.v1",
        "role": role.value,
        "foundation_parent_bindings": {
            parent.value: {
                "asset_version_id": by_role[parent.value.lower()].asset_version_id,
                "content_hash": by_role[parent.value.lower()].content_hash,
            }
            for parent in role.required_parents
        },
        "creative_brief": {
            "asset_version_id": by_role["creative_brief"].asset_version_id,
            "content_hash": by_role["creative_brief"].content_hash,
        },
        **(
            {
                "world_compilation": {
                    "contract_version": "world-foundation.v1",
                    "compiled_scope": "BOOK",
                }
            }
            if role is FoundationRole.WORLD_BIBLE
            else {}
        ),
    }


def validate_foundation_payload(generator: str, content: Mapping[str, Any]) -> None:
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        validate_chapter_provider_output_against_schema,
    )

    payload = dict(content["candidate_payload"])
    envelope = payload.pop("constraint_envelope", {})
    bindings = payload.pop("foundation_parent_bindings", {})
    if bindings != envelope.get("foundation_parent_bindings"):
        raise KernelError(
            "FOUNDATION_PARENT_BINDING_DRIFT",
            "Generated Foundation parents differ from frozen inputs",
        )
    if generator == "world.design.generate":
        from novel_forge.modules.worldbuilding.foundation import WorldFoundation

        world = payload.pop("world_foundation")
        WorldFoundation.from_mapping(
            world,
            expected_compiled_scope=(envelope.get("world_compilation") or {}).get("compiled_scope"),
        )
        payload["world_foundation_json"] = json.dumps(
            world, ensure_ascii=False, separators=(",", ":")
        )
    work_requirements = envelope.get("contract_version") in {"foundation-generation.v2", "foundation-generation.v3"}
    schema = foundation_output_schema(generator, work_requirements=work_requirements)
    if envelope.get("author_design"):
        from novel_forge.modules.story_design_authority.author_input import add_author_decision_contract, frozen_author_projection, validate_author_decisions
        projection = frozen_author_projection({"constraint_envelope": envelope}, generator=generator, logical_key=str(content.get("logical_key") or ""))
        schema = add_author_decision_contract(schema, projection)
        validate_author_decisions(payload, projection)
    translations = payload.get("knowledge_translations")
    if translations:
        from .knowledge_translation import add_translation_contract

        if not isinstance(translations, list) or any(not isinstance(item, Mapping) for item in translations):
            raise KernelError("PLANNING_KNOWLEDGE_TRANSLATION_INVALID", "Foundation translations must be structured decisions")
        schema = add_translation_contract(schema, {
            "policy_version": "knowledge-grounded-selection-v2",
            "selected": [{
                "knowledge_card_asset_version_id": item.get("knowledge_card_asset_version_id", ""),
                "content_hash": item.get("content_hash", ""),
            } for item in translations],
        })
    elif translations == []:
        payload.pop("knowledge_translations")
    validate_chapter_provider_output_against_schema(generator, schema, payload)
    if work_requirements:
        validate_foundation_applicability(payload, schema)
    if generator == "character.cast.generate":
        ids = [character["character_id"] for character in payload["characters"]]
        if len(ids) != len(set(ids)) or any(
            relation[field] not in ids
            for relation in payload["relationships"]
            for field in ("source_character_id", "target_character_id")
        ):
            raise KernelError(
                "FOUNDATION_CHARACTER_REFERENCE_INVALID",
                "Character identities and relationship endpoints must resolve within the generated cast",
            )


def world_generation_contract(*, compiled_scope: str = "BOOK") -> dict[str, Any]:
    from novel_forge.modules.worldbuilding.foundation import CORE_WORLD_ONTOLOGY
    from novel_forge.modules.worldbuilding.foundation_schema import (
        world_foundation_example,
        world_foundation_schema,
    )

    return {
        "contract_version": "world-foundation.v1",
        "compiled_scope": compiled_scope,
        "schema": world_foundation_schema(compiled_scope=compiled_scope),
        "example": world_foundation_example(compiled_scope=compiled_scope),
        "enum_contract": "Every enum is one scalar string. Schema enum arrays list choices; they are never the field's returned value. compiled_scope is fixed by this task.",
        "sections": {
            "key_rule": "core_laws is required; include only needed ontology dimensions or genre:/book: extensions",
            "ontology": sorted(CORE_WORLD_ONTOLOGY),
            "content": "concrete approved initial conditions, rules and limits",
        },
        "rules": {
            "category": "one compiled section key",
            "applicability_and_consequences": "nonempty string arrays",
            "predicate": {
                "required_for": "every enforcement except SOFT_CAUSAL",
                "value": "typed scalar; only EXISTS may omit value",
            },
            "mechanism": "Use MECHANISM only when the existing typed WorldMechanism contract can express the rule; otherwise request explicit design clarification. Do not replace a hard rule with soft reasoning.",
        },
        "entities": "nonempty array of unique entity_id and kind records; references must resolve; approved initial conditions are not accepted events",
    }


def normalize_foundation_payload(
    generator: str, raw: Mapping[str, Any], *, expected_compiled_scope: str | None = None
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise KernelError(
            "FOUNDATION_PAYLOAD_TYPE_INVALID",
            f"$: expected object; actual type {type(raw).__name__}",
        )
    payload = dict(raw)
    if generator == "world.design.generate":
        from novel_forge.modules.worldbuilding.foundation import WorldFoundation
        from novel_forge.modules.worldbuilding.foundation_schema import WorldContractError, world_value_type

        encoded = payload.pop("world_foundation_json", None)
        if not isinstance(encoded, str):
            raise WorldContractError("FOUNDATION_WORLD_PARSE_FAILED", [{
                "code": "WORLD_FIELD_TYPE_INVALID" if "world_foundation_json" in raw else "WORLD_FIELD_REQUIRED",
                "field_path": "$.world_foundation_json", "expected_type": "string",
                "actual_type": world_value_type(encoded) if "world_foundation_json" in raw else "missing",
                "constraint": "World compilation must be a JSON encoded object conforming to the frozen schema.",
            }])
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise WorldContractError("FOUNDATION_WORLD_PARSE_FAILED", [{
                "code": "WORLD_FIELD_JSON_INVALID", "field_path": "$.world_foundation_json",
                "expected_type": "string", "actual_type": "string",
                "constraint": f"Invalid inner JSON at line {error.lineno}, column {error.colno}: {error.msg}",
            }]) from error
        WorldFoundation.from_mapping(value, expected_compiled_scope=expected_compiled_scope)
        payload["world_foundation"] = value
    return payload
