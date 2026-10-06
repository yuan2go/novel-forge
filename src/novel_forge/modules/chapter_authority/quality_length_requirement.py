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
            if rules.get("unit") == "HAN_CHARACTERS_V1":
                minimum, maximum = rules.get("minimum"), rules.get("maximum")
                if (
                    type(minimum) is not int
                    or type(maximum) is not int
                    or not 0 < minimum <= maximum
                ):
                    raise KernelError(
                        "CHAPTER_LENGTH_POLICY_INVALID",
                        "Retain positive ordered frozen Han bounds",
                    )
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
