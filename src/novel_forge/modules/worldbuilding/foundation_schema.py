from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import NarrativeStateKind
from .dynamics import RequirementOperator


WorldScope = Literal["BOOK", "VOLUME", "ARC"]
WorldDepth = Literal["SEED", "WORKING", "DETAILED"]
WorldEnforcement = Literal["HARD", "QUANTITATIVE", "TEMPORAL", "SOFT_CAUSAL", "MECHANISM"]
WorldMechanismEffect = Literal["REVIVAL", "INSTANT_TRAVEL", "MULTIPRESENCE", "POWER_TRANSITION"]
_Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
_Scalar = str | int | Annotated[float, Field(allow_inf_nan=False)] | bool | None


class _WorldContract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class _SectionContract(_WorldContract):
    model_config = ConfigDict(strict=True, extra="allow")
    depth: WorldDepth
    content: _Text


class _EntityContract(_WorldContract):
    model_config = ConfigDict(strict=True, extra="allow")
    entity_id: _Text
    kind: _Text = Field(default=None, validate_default=False)


class _PredicateContract(_WorldContract):
    requirement_id: _Text
    state_kind: Literal[tuple(item.value for item in NarrativeStateKind)]
    entity_key: _Text
    field: _Text
    operator: Literal[tuple(item.value for item in RequirementOperator)]
    value: _Scalar = None


class _MechanismContract(_WorldContract):
    contract_version: Literal["world-mechanism.v1"]
    effect: WorldMechanismEffect
    entity_keys: Annotated[list[_Text], Field(min_length=1)]


class WorldRuleContract(_WorldContract):
    rule_id: _Text
    category: _Text
    statement: _Text
    enforcement: WorldEnforcement
    applicability: Annotated[list[_Text], Field(min_length=1)]
    consequences: Annotated[list[_Text], Field(min_length=1)]
    predicate: _PredicateContract | None = None
    mechanism: _MechanismContract | None = None


class WorldFoundationContract(_WorldContract):
    contract_version: Literal["world-foundation.v1"]
    genre_profile: _Text
    compiled_scope: WorldScope
    sections: dict[_Text, _SectionContract]
    rules: Annotated[list[WorldRuleContract], Field(min_length=1)]
    entities: Annotated[list[_EntityContract], Field(min_length=1)]


class WorldContractError(KernelError):
    def __init__(self, code: str, diagnostics: list[dict[str, Any]]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__(code, json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")))


def world_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _resolved_schema(schema: Mapping[str, Any], definitions: Mapping[str, Any]) -> Mapping[str, Any]:
    if "$ref" in schema:
        return definitions[schema["$ref"].rsplit("/", 1)[-1]]
    alternatives = schema.get("anyOf", [])
    concrete = [part for part in alternatives if part.get("type") != "null"]
    if len(concrete) == 1:
        return _resolved_schema(concrete[0], definitions)
    return schema


def _error_diagnostic(error: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})
    current = schema
    path = "$"
    for component in error["loc"]:
        current = _resolved_schema(current, definitions)
        if current.get("anyOf") or component == "[key]":
            break
        if isinstance(component, int):
            path += f"[{component}]"
            current = current.get("items", {})
        else:
            path += f".{component}"
            current = current.get("properties", {}).get(component, current.get("additionalProperties", {}))
            if not isinstance(current, Mapping):
                current = {}
    current = _resolved_schema(current, definitions)
    types = [part.get("type", "object") for part in current.get("anyOf", [])]
    expected = current.get("type") or "|".join(types) or "declared field"
    actual = "missing" if error["type"] == "missing" else world_value_type(error["input"])
    code = "WORLD_FIELD_VALUE_INVALID"
    if actual == "missing":
        code = "WORLD_FIELD_REQUIRED"
    elif error["type"] == "extra_forbidden":
        code = "WORLD_FIELD_UNKNOWN"
    elif actual not in expected.split("|") and not (actual == "number" and "integer" in expected):
        code = "WORLD_FIELD_TYPE_INVALID"
    elif error["type"] == "literal_error":
        code = "WORLD_FIELD_ENUM_INVALID"
    return {
        "code": code,
        "field_path": path,
        "expected_type": expected,
        "actual_type": actual,
        "constraint": error["msg"],
    }


def _validate_shape(model: type[BaseModel], raw: Any) -> None:
    try:
        model.model_validate(raw, strict=True)
    except ValidationError as error:
        schema = model.model_json_schema()
        diagnostics = [_error_diagnostic(item, schema) for item in error.errors(include_url=False)]
        diagnostics = list({json.dumps(item, sort_keys=True): item for item in diagnostics}.values())
        code = "WORLD_FOUNDATION_SCHEMA_INVALID"
        if any(item["field_path"].startswith(("$.rules[", "$.entities[")) and item["expected_type"] == "object" for item in diagnostics):
            code = "WORLD_FOUNDATION_COLLECTION_INVALID"
        raise WorldContractError(code, diagnostics) from error


def validate_world_rule_shape(raw: Any) -> None:
    _validate_shape(WorldRuleContract, raw)


def validate_world_foundation_shape(raw: Any, *, expected_compiled_scope: str | None = None) -> None:
    _validate_shape(WorldFoundationContract, raw)
    if expected_compiled_scope is not None:
        scope = world_foundation_schema(compiled_scope=expected_compiled_scope)["properties"]["compiled_scope"]
        if raw["compiled_scope"] != scope["const"]:
            raise WorldContractError("WORLD_FOUNDATION_SCOPE_MISMATCH", [{
                "code": "WORLD_FIELD_FROZEN_VALUE_MISMATCH",
                "field_path": "$.compiled_scope",
                "expected_type": "string",
                "actual_type": "string",
                "expected_value": expected_compiled_scope,
                "actual_value": raw["compiled_scope"],
                "constraint": "Compilation scope must equal the frozen task; it cannot be inferred or expanded by a model.",
            }])


def world_foundation_schema(*, compiled_scope: str | None = None) -> dict[str, Any]:
    schema = WorldFoundationContract.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    if compiled_scope is not None:
        scope = schema["properties"]["compiled_scope"]
        if not isinstance(compiled_scope, str) or compiled_scope not in scope["enum"]:
            raise KernelError("WORLD_FROZEN_SCOPE_INVALID", "Frozen scope must be one BOOK, VOLUME or ARC string")
        scope["const"] = compiled_scope
    return schema


def world_foundation_example(*, compiled_scope: str) -> dict[str, Any]:
    value = {
        "contract_version": "world-foundation.v1",
        "genre_profile": "original-genre.v1",
        "compiled_scope": compiled_scope,
        "sections": {"core_laws": {"depth": "SEED", "content": "An original constraint changes choices."}},
        "rules": [{
            "rule_id": "rule:choice", "category": "core_laws",
            "statement": "A faction may defend its interests.", "enforcement": "SOFT_CAUSAL",
            "applicability": ["faction_state"], "consequences": ["A proposed response still needs accepted causes."],
        }],
        "entities": [{"entity_id": "faction:example", "kind": "FACTION"}],
    }
    validate_world_foundation_shape(value, expected_compiled_scope=compiled_scope)
    return value
