from copy import deepcopy
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    normalize_foundation_payload,
    world_generation_contract,
)
from novel_forge.modules.worldbuilding.foundation import WorldFoundation


def world():
    return {
        "contract_version": "world-foundation.v1",
        "genre_profile": "guofeng-xuanhuan.v1",
        "compiled_scope": "BOOK",
        "sections": {"core_laws": {"depth": "WORKING", "content": "Power costs time."}},
        "entities": [{"entity_id": "school", "kind": "FACTION"}],
        "rules": [{
            "rule_id": "training", "category": "core_laws",
            "statement": "Training consumes time.", "enforcement": "HARD",
            "applicability": ["power_state"], "consequences": ["Training takes a day."],
            "predicate": {
                "requirement_id": "day", "state_kind": "power_state", "entity_key": "school",
                "field": "training_days", "operator": "AT_LEAST", "value": 1,
            },
        }],
    }


@pytest.mark.parametrize("value", [[], {}, 2, None, "", "CHAPTER"])
def test_scope_invalid_results_report_typed_field_diagnostics(value):
    candidate = world()
    candidate["compiled_scope"] = value
    with pytest.raises(KernelError) as failure:
        normalize_foundation_payload("world.design.generate", {
            "world_foundation_json": json.dumps(candidate),
        })
    diagnostic = failure.value.diagnostics[0]
    assert diagnostic["field_path"] == "$.compiled_scope"
    assert diagnostic["expected_type"] == "string"
    assert diagnostic["actual_type"] in {"array", "object", "number", "null", "string"}
    assert diagnostic["code"] in {"WORLD_FIELD_TYPE_INVALID", "WORLD_FIELD_ENUM_INVALID"}


@pytest.mark.parametrize("path", [
    ("genre_profile",), ("sections", "core_laws", "depth"),
    ("sections", "core_laws", "content"), ("rules", 0, "enforcement"),
    ("rules", 0, "predicate", "state_kind"), ("rules", 0, "predicate", "operator"),
    ("entities", 0, "entity_id"),
])
@pytest.mark.parametrize("value", [[], {}, 2, None])
def test_world_fields_never_coerce_bad_external_types(path, value):
    candidate = world()
    current = candidate
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(KernelError) as failure:
        WorldFoundation.from_mapping(candidate)
    assert failure.value.diagnostics
    assert failure.value.diagnostics[0]["code"] == "WORLD_FIELD_TYPE_INVALID"


def test_generation_contract_exposes_single_scope_and_same_schema_as_validator():
    from novel_forge.modules.worldbuilding.foundation_schema import world_foundation_schema

    contract = world_generation_contract()
    assert contract["compiled_scope"] == "BOOK"
    assert contract["schema"] == world_foundation_schema(compiled_scope="BOOK")
    assert contract["schema"]["properties"]["compiled_scope"]["type"] == "string"
    assert contract["schema"]["properties"]["compiled_scope"]["const"] == "BOOK"
    WorldFoundation.from_mapping(contract["example"], expected_compiled_scope="BOOK")


def test_frozen_scope_rejects_valid_but_wider_result_without_mutating_it():
    candidate = world()
    before = deepcopy(candidate)
    with pytest.raises(KernelError, match="WORLD_FOUNDATION_SCOPE_MISMATCH"):
        WorldFoundation.from_mapping(candidate, expected_compiled_scope="ARC")
    assert candidate == before
    assert WorldFoundation.from_mapping(candidate).compiled_scope == "BOOK"


@pytest.mark.parametrize("value", [None, 1, [], {}, "{invalid", "[]", "null"])
def test_inner_world_wrapper_must_decode_to_a_valid_object(value):
    with pytest.raises(KernelError) as failure:
        normalize_foundation_payload("world.design.generate", {"world_foundation_json": value})
    assert failure.value.diagnostics[0]["field_path"] in {"$.world_foundation_json", "$"}


def test_missing_scope_is_distinct_from_unknown_scope():
    candidate = world()
    del candidate["compiled_scope"]
    with pytest.raises(KernelError) as failure:
        WorldFoundation.from_mapping(candidate)
    assert failure.value.diagnostics[0]["code"] == "WORLD_FIELD_REQUIRED"
    assert failure.value.diagnostics[0]["actual_type"] == "missing"


@pytest.mark.parametrize("field,value", [
    ("effect", []), ("effect", {}), ("effect", 2), ("effect", None),
    ("effect", "UNLIMITED_POWER"), ("entity_keys", "school"),
    ("entity_keys", [2]), ("contract_version", []),
])
def test_mechanism_type_errors_have_exact_nested_paths(field, value):
    candidate = world()
    rule = candidate["rules"][0]
    rule["enforcement"] = "MECHANISM"
    rule["mechanism"] = {
        "contract_version": "world-mechanism.v1", "effect": "POWER_TRANSITION", "entity_keys": ["school"],
    }
    rule["mechanism"][field] = value
    with pytest.raises(KernelError) as failure:
        WorldFoundation.from_mapping(candidate)
    assert failure.value.diagnostics[0]["field_path"].startswith(f"$.rules[0].mechanism.{field}")


@pytest.mark.parametrize("value", [[], {}, float("nan"), float("inf"), 10**1000])
def test_predicate_rejects_nonscalar_or_nonfinite_value(value):
    candidate = world()
    candidate["rules"][0]["predicate"]["value"] = value
    with pytest.raises(KernelError) as failure:
        WorldFoundation.from_mapping(candidate)
    assert all(item["field_path"] == "$.rules[0].predicate.value" for item in failure.value.diagnostics)


def test_inner_semantics_are_revalidated_after_a_corrected_scope():
    candidate = world()
    candidate["rules"][0]["predicate"].pop("value")
    with pytest.raises(KernelError) as failure:
        WorldFoundation.from_mapping(candidate, expected_compiled_scope="BOOK")
    assert failure.value.diagnostics[0]["field_path"] == "$.rules[0].predicate.value"
    assert failure.value.diagnostics[0]["code"] == "WORLD_FIELD_REQUIRED"


@pytest.mark.parametrize("scope", ["BOOK", "VOLUME", "ARC"])
def test_published_world_foundation_keeps_single_scope_compatibility(scope):
    candidate = world()
    candidate["compiled_scope"] = scope
    candidate["entities"][0].pop("kind")
    assert WorldFoundation.from_mapping(candidate).compiled_scope == scope


def test_identity_diagnostics_keep_exact_field_after_shape_validation():
    candidate = world()
    candidate["entities"].append(deepcopy(candidate["entities"][0]))
    candidate["rules"][0]["category"] = "not-compiled"
    with pytest.raises(KernelError) as failure:
        WorldFoundation.from_mapping(candidate)
    assert failure.value.code == "WORLD_FOUNDATION_IDENTITY_INVALID"
    assert {item["field_path"] for item in failure.value.diagnostics} == {
        "$.rules[0].category", "$.entities[1].entity_id",
    }


def test_new_foundation_task_freezes_book_scope_and_adoption_enforces_it():
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        FOUNDATION_INPUT_ROLES, foundation_envelope, foundation_task, validate_foundation_payload,
    )

    generator = "world.design.generate"
    envelope = foundation_envelope(generator=generator, inputs=tuple(
        SimpleNamespace(role=role, asset_version_id=f"asset:{role}", content_hash="sha256:" + "a" * 64)
        for role in FOUNDATION_INPUT_ROLES[generator]
    ))
    assert envelope["world_compilation"]["compiled_scope"] == "BOOK"
    assert foundation_task(generator)["world_contract"]["compiled_scope"] == "BOOK"
    candidate = world()
    candidate["compiled_scope"] = "ARC"
    with pytest.raises(KernelError, match="WORLD_FOUNDATION_SCOPE_MISMATCH"):
        validate_foundation_payload(generator, {"candidate_payload": {
            "world_foundation": candidate,
            "constraint_envelope": envelope,
            "foundation_parent_bindings": envelope["foundation_parent_bindings"],
        }})
