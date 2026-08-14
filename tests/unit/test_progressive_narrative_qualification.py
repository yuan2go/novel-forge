from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.modules.story_design_authority.qualification import (
    GENERATOR_QUALIFICATION_PROFILES,
    NarrativeDesignLayer,
    qualification_provider_schema,
    scripted_qualification,
    validate_narrative_qualification,
)


def test_every_qualification_profile_binds_a_governed_execution_capability() -> None:
    registry = default_capability_registry()

    for profiles in GENERATOR_QUALIFICATION_PROFILES.values():
        for profile in profiles:
            assert registry.resolve(profile.capability_id).capability_id.value == (
                profile.capability_id
            )


@pytest.mark.parametrize(
    ("generator", "layers"),
    (
        (
            "book_plan.generate",
            {
                NarrativeDesignLayer.BOOK_ARCHITECTURE,
                NarrativeDesignLayer.CHARACTER_DEVELOPMENT,
                NarrativeDesignLayer.DISCLOSURE_OBLIGATION,
            },
        ),
        (
            "volume_plan.generate",
            {NarrativeDesignLayer.VOLUME_ARCHITECTURE},
        ),
        (
            "arc_plan.generate",
            {NarrativeDesignLayer.NARRATIVE_ARC_GRAPH},
        ),
        (
            "chapter_group_plan.generate",
            {NarrativeDesignLayer.NARRATIVE_SCHEDULING},
        ),
        (
            "chapter_plan.generate",
            {
                NarrativeDesignLayer.CHAPTER_EXECUTION_PLAN,
                NarrativeDesignLayer.SCENE_ARCHITECTURE,
            },
        ),
    ),
)
def test_each_generator_uses_exact_layer_specific_profiles(
    generator: str, layers: set[NarrativeDesignLayer]
) -> None:
    payload = scripted_qualification(generator)

    result = validate_narrative_qualification(
        generator_operation_name=generator,
        value=payload,
    )

    assert result.status == "PASS"
    assert {receipt.layer for receipt in result.receipts} == layers
    assert len({receipt.profile_id for receipt in result.receipts}) == len(layers)
    assert all(receipt.profile_hash.startswith("sha256:") for receipt in result.receipts)
    assert all(receipt.criterion_count >= 4 for receipt in result.receipts)


def test_semantic_evaluation_fails_closed_when_one_required_criterion_is_missing() -> None:
    payload = scripted_qualification("book_plan.generate")
    payload["evaluations"][0]["criteria"].pop()

    with pytest.raises(KernelError) as raised:
        validate_narrative_qualification(
            generator_operation_name="book_plan.generate",
            value=payload,
        )

    assert raised.value.code == "NARRATIVE_SEMANTIC_EVALUATION_INVALID"
    assert "criteria" in raised.value.message


def test_semantic_failure_requires_repair_and_cannot_be_declared_pass() -> None:
    payload = scripted_qualification("chapter_group_plan.generate")
    evaluation = payload["evaluations"][0]
    evaluation["criteria"][0].update(
        verdict="FAIL",
        repair_directive="redistribute three consecutive setup chapters",
    )

    with pytest.raises(KernelError) as raised:
        validate_narrative_qualification(
            generator_operation_name="chapter_group_plan.generate",
            value=payload,
        )

    assert raised.value.code == "NARRATIVE_SEMANTIC_QUALIFICATION_FAILED"

    rejected = validate_narrative_qualification(
        generator_operation_name="chapter_group_plan.generate",
        value=payload,
        require_pass=False,
    )
    assert rejected.status == "FAIL"
    assert rejected.receipts[0].status == "FAIL"


def test_provider_schema_is_strict_and_exposes_no_universal_judge() -> None:
    schema = qualification_provider_schema("chapter_plan.generate")

    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == (
        "progressive-narrative-qualification.v1"
    )
    evaluations = schema["properties"]["evaluations"]
    assert evaluations["minItems"] == evaluations["maxItems"] == 2
    assert set(evaluations["items"]["properties"]["layer"]["enum"]) == {
        "CHAPTER_EXECUTION_PLAN",
        "SCENE_ARCHITECTURE",
    }
