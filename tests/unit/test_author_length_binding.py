from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
from novel_forge.modules.chapter_authority.quality_length_requirement import compile_planning_length, freeze_planning_length_source, freeze_requirement, generation_requirement, require_generation_binding
from novel_forge.modules.command_kernel.errors import KernelError


def context():
    return {"context_segments": [{"asset_type": "platform_profile", "allowed_use": "evidence_only",
        "asset_version_id": "profile:author", "content_digest": "sha256:author-profile", "safe_summary": "Policy",
        "structured_facts": [{"key": "platform_rules", "value": {"chapter_length": {"minimum": 4000, "maximum": 5000},
            "publish_metadata": {"title_required": True}}}]}]}


def test_source_bound_han_requirement_reaches_writer_without_exposing_evidence_only_policy():
    original = context()
    assert build_provider_context_view("draft", original, {})["segments"] == []
    current = deepcopy(original)
    current["chapter_generation_length"] = generation_requirement(current)
    view = build_provider_context_view("draft", current, {})
    assert view["chapter_generation_length"]["unit"] == "HAN_CHARACTERS_V1"
    assert view["chapter_generation_length"]["minimum"] == 4000
    assert view["chapter_generation_length"]["maximum"] == 5000
    assert view["chapter_generation_length"]["planning_target_han_characters"] == 4500
    assert view["chapter_generation_length"]["platform_profile_asset_version_id"] == "profile:author"
    assert view["segments"] == []
    assert original == context()


@pytest.mark.parametrize("field,value", [("minimum", 3000), ("maximum", 7000), ("unit", "WORDS"),
    ("platform_profile_asset_version_id", "another"), ("platform_profile_content_hash", "other-hash"),
    ("platform_rules_hash", "other-rules"), ("planning_target_han_characters", 4200)])
def test_changed_length_unit_bounds_or_source_cannot_reuse_a_frozen_generation_binding(field, value):
    current = context()
    current["chapter_generation_length"] = generation_requirement(current)
    current["chapter_generation_length"][field] = value
    with pytest.raises(KernelError, match="CHAPTER_GENERATION_LENGTH_BINDING_INVALID"):
        require_generation_binding(current)


def test_conflicting_or_unsupported_platform_length_is_not_silently_reinterpreted():
    current = context()
    current["context_segments"].append(deepcopy(current["context_segments"][0]))
    with pytest.raises(KernelError, match="CHAPTER_LENGTH_SCOPE_PROFILE_CONFLICT"):
        generation_requirement(current)
    current = context()
    current["context_segments"][0]["structured_facts"][0]["value"]["chapter_length"]["unit"] = "WORDS"
    with pytest.raises(KernelError, match="CHAPTER_LENGTH_UNIT_UNSUPPORTED"):
        generation_requirement(current)


@pytest.mark.parametrize("location", ["segment", "fact", "rules", "length"])
def test_internal_quality_bounds_stay_internal_without_changing_quality_measurement(location):
    current = context()
    segment = current["context_segments"][0]
    fact = segment["structured_facts"][0]
    selected = {"segment": segment, "fact": fact, "rules": fact["value"], "length": fact["value"]["chapter_length"]}[location]
    selected["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
    assert freeze_requirement(current, context_id="context:quality")["minimum"] == 4000
    assert generation_requirement(current) is None
    assert "chapter_generation_length" not in build_provider_context_view("draft", current, {})
    current["chapter_generation_length"] = generation_requirement(context())
    with pytest.raises(KernelError, match="CHAPTER_GENERATION_LENGTH_BINDING_INVALID"):
        require_generation_binding(current)


def test_planning_uses_exact_book_author_scale_and_rejects_changed_source_or_unsupported_unit():
    profile = {"chapter_length": {"minimum": 4000, "maximum": 5000}}
    document = SimpleNamespace(asset_version_id="book:author", content_hash="sha256:book", content={"production_profile": deepcopy(profile)})
    source = freeze_planning_length_source(document, profile)
    requirement = compile_planning_length(source)
    assert requirement["minimum"] == 4000 and requirement["maximum"] == 5000
    assert requirement["unit"] == "HAN_CHARACTERS_V1" and requirement["planning_target_han_characters"] == 4500
    assert requirement["source_book_asset_version_id"] == document.asset_version_id
    assert requirement["source_book_content_hash"] == document.content_hash
    changed = deepcopy(profile)
    changed["chapter_length"]["maximum"] = 9000
    with pytest.raises(KernelError, match="CHAPTER_PLANNING_LENGTH_SOURCE_DRIFT"):
        freeze_planning_length_source(document, changed)
    source["chapter_length"]["unit"] = "WORDS"
    with pytest.raises(KernelError, match="CHAPTER_LENGTH_UNIT_UNSUPPORTED"):
        compile_planning_length(source)


@pytest.mark.parametrize("location", ["profile", "length"])
def test_planning_does_not_publish_internal_book_policy(location):
    profile = {"chapter_length": {"minimum": 4000, "maximum": 5000}}
    (profile if location == "profile" else profile["chapter_length"])["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
    document = SimpleNamespace(asset_version_id="book:internal", content_hash="sha256:internal", content={"production_profile": profile})
    assert freeze_planning_length_source(document, profile) is None

