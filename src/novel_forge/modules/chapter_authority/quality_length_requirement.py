from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash


def freeze_requirement(context, *, context_id):
    from novel_forge.modules.chapter_quality_authority.context_views import (
        compile_platform_policy,
    )

    rows = []
    for segment in context.get("context_segments", []):
        if segment.get("asset_type") == "platform_profile":
            rules = compile_platform_policy(
                profile_asset_version_id=segment["asset_version_id"], segment=segment
            ).chapter_length_rules
            if {'minimum', 'maximum'} & rules.keys():
                minimum, maximum = _han_bounds(rules)
                rows.append(
                    {
                        "contract_version": "quality-length-preservation.v1",
                        "unit": "HAN_CHARACTERS_V1",
                        "minimum": minimum,
                        "maximum": maximum,
                        "context_asset_version_id": context_id,
                        "platform_profile_asset_version_id": segment[
                            "asset_version_id"
                        ],
                        "platform_profile_content_hash": segment.get("content_digest"),
                        "platform_rules_hash": snapshot_hash(rules),
                    }
                )
    if len(rows) > 1:
        raise KernelError(
            "CHAPTER_LENGTH_SCOPE_PROFILE_CONFLICT",
            "Require one exact frozen Platform length profile",
        )
    return rows[0] if rows else None


def _han_bounds(rules):
    from novel_forge.modules.chapter_quality_authority.context_views import chapter_length_unit

    if chapter_length_unit(rules) != "HAN_CHARACTERS_V1":
        raise KernelError("CHAPTER_LENGTH_UNIT_UNSUPPORTED", "Frozen length preservation requires the manuscript Han-character measurement; correct an incompatible explicit unit")
    minimum, maximum = rules.get("minimum"), rules.get("maximum")
    if type(minimum) is not int or type(maximum) is not int or not 0 < minimum <= maximum:
        raise KernelError("CHAPTER_LENGTH_POLICY_INVALID", "Retain positive ordered frozen Han bounds")
    return minimum, maximum


def require_length(requirement, text):
    from novel_forge.modules.revision.domain import han_characters

    if (
        requirement
        and not requirement["minimum"] <= han_characters(text) <= requirement["maximum"]
    ):
        raise KernelError(
            "CHAPTER_LENGTH_REPAIR_INCOMPLETE",
            f"Actual HAN_CHARACTERS_V1 count {han_characters(text)} is outside frozen bounds {requirement['minimum']}–{requirement['maximum']}; preserve the work scale without padding",
        )


def generation_requirement(context):
    from novel_forge.modules.context_builder.story_projection import visible_business_data

    visible = visible_business_data(context.get("context_segments", []), stage="draft")
    required = freeze_requirement({"context_segments": visible}, context_id="")
    if required is None:
        return None
    return {"contract_version": "chapter-generation-length.v1", "unit": required["unit"],
        "minimum": required["minimum"], "maximum": required["maximum"],
        "planning_target_han_characters": (required["minimum"] + required["maximum"]) // 2,
        "platform_profile_asset_version_id": required["platform_profile_asset_version_id"],
        "platform_profile_content_hash": required["platform_profile_content_hash"],
        "platform_rules_hash": required["platform_rules_hash"]}


def require_generation_binding(context):
    declared = context.get("chapter_generation_length")
    if declared is None:
        return None
    validate_generation_requirement(declared)
    if declared != generation_requirement(context):
        raise KernelError("CHAPTER_GENERATION_LENGTH_BINDING_INVALID", "Author length must retain the exact frozen Platform bounds, unit and source")
    return declared


def validate_generation_requirement(required):
    keys = {"contract_version", "unit", "minimum", "maximum", "planning_target_han_characters",
        "platform_profile_asset_version_id", "platform_profile_content_hash", "platform_rules_hash"}
    if (not isinstance(required, dict) or set(required) != keys
        or required.get("contract_version") != "chapter-generation-length.v1"
        or required.get("unit") != "HAN_CHARACTERS_V1"
        or type(required.get("minimum")) is not int or type(required.get("maximum")) is not int
        or not 0 < required["minimum"] <= required["maximum"]
        or type(required.get("planning_target_han_characters")) is not int
        or required["planning_target_han_characters"] != (required["minimum"] + required["maximum"]) // 2
        or any(not isinstance(required.get(key), str) or not required[key] for key in
            ("platform_profile_asset_version_id", "platform_profile_content_hash", "platform_rules_hash"))):
        raise KernelError("CHAPTER_GENERATION_LENGTH_BINDING_INVALID", "Generation length requires typed Han bounds and exact frozen source identity")
    return required


def freeze_planning_length_source(book_document, production_profile):
    from novel_forge.modules.context_builder.story_projection import visible_business_data

    profile = visible_business_data(production_profile, stage="draft")
    rules = (profile or {}).get("chapter_length")
    if not rules:
        return None
    if book_document.content.get("production_profile") != production_profile:
        raise KernelError("CHAPTER_PLANNING_LENGTH_SOURCE_DRIFT", "Planning author scale must belong to its exact Book record")
    source = {"contract_version": "book-author-length-source.v1",
        "asset_version_id": book_document.asset_version_id, "content_hash": book_document.content_hash,
        "chapter_length": rules}
    compile_planning_length(source)
    return source


def compile_planning_length(source):
    if (not isinstance(source, dict) or set(source) != {"contract_version", "asset_version_id", "content_hash", "chapter_length"}
        or source.get("contract_version") != "book-author-length-source.v1"
        or not isinstance(source.get("chapter_length"), dict)
        or any(not isinstance(source.get(key), str) or not source[key] for key in ("asset_version_id", "content_hash"))):
        raise KernelError("CHAPTER_PLANNING_LENGTH_SOURCE_INVALID", "Planning scale requires its frozen Book author source")
    minimum, maximum = _han_bounds(source["chapter_length"])
    return {"contract_version": "chapter-planning-length.v1", "unit": "HAN_CHARACTERS_V1",
        "minimum": minimum, "maximum": maximum,
        "planning_target_han_characters": (minimum + maximum) // 2,
        "source_book_asset_version_id": source["asset_version_id"], "source_book_content_hash": source["content_hash"],
        "chapter_length_rules_hash": snapshot_hash(source["chapter_length"])}
