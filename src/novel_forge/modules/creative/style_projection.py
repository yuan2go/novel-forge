from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
from novel_forge.modules.command_kernel.errors import KernelError


def compile_foundation_style(request: AuthorityHandlerRequest) -> dict:
    designs = [item for item in request.inputs if item.asset_type == "book_design"]
    if len(designs) != 1 or len(request.inputs) != 3:
        raise KernelError(
            "FOUNDATION_STYLE_INPUT_INVALID",
            "Style needs one Book Design and its exact creative and character inputs",
        )
    design = designs[0]
    bindings = {
        item["role"]: item
        for item in design.content.get("foundation_set", {}).get("bindings", [])
    }
    sources = {}
    for role in ("CREATIVE_FOUNDATION", "CHARACTER_CAST"):
        binding = bindings.get(role, {})
        matches = [
            item
            for item in request.inputs
            if item.asset_version_id == binding.get("asset_version_id")
            and item.content_hash == binding.get("content_hash")
        ]
        if len(matches) != 1:
            raise KernelError(
                "FOUNDATION_STYLE_SOURCE_DRIFT",
                "Style must reference the exact activated design inputs",
            )
        sources[role] = matches[0]
    creative = sources["CREATIVE_FOUNDATION"].content
    creative = creative.get("candidate_payload", creative)
    cast = sources["CHARACTER_CAST"].content
    cast = cast.get("candidate_payload", cast)
    profile = creative.get("style_profile")
    if not isinstance(profile, dict) or not profile.get("constraints"):
        raise KernelError(
            "FOUNDATION_STYLE_REQUIRED",
            "Creative Foundation lacks an executable style profile",
        )
    voices = []
    for layer, key in (
        ("NARRATOR", "narrator"),
        ("POV", "pov"),
        ("GENRE", "genre_conventions"),
    ):
        if layer != "POV":
            voices.append(
                {
                    "kind": "voice_contract",
                    "layer": layer,
                    "voice_id": f"{design.asset_version_id}:{layer}",
                    "guidance": profile[key],
                    "required_markers": [],
                    "forbidden_markers": [],
                }
            )
    for actor in cast.get("characters", []):
        voices.append(
            {
                "kind": "voice_contract",
                "layer": "CHARACTER",
                "voice_id": f"{design.asset_version_id}:{actor['character_id']}",
                "character_id": actor["character_id"],
                "guidance": actor["voice_anchors"],
                "required_markers": [],
                "forbidden_markers": [],
            }
        )
    return {
        "type": "style_policy",
        "profile_id": f"foundation-style:{design.asset_version_id}",
        "contract_version": "foundation-style-projection.v1",
        "project_id": request.project_id,
        "book_id": sources["CREATIVE_FOUNDATION"].content["book_id"],
        "safe_summary": "Apply the exact approved Foundation voice and original craft examples.",
        "constraints": profile["constraints"],
        "structured_facts": [
            *voices,
            {"key": "creative_style", "value": profile},
            {
                "key": "realization_policy",
                "value": {
                    "contract_version": "scene-craft-tasks.v1",
                    "mode": "WHOLE_CHAPTER_WITH_TARGETED_SPECIALISMS",
                },
            },
        ],
        "source_bindings": [
            {
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
            }
            for item in request.inputs
        ],
        "allowed_use": "generation",
        "raw_source": False,
        "source_expression_included": False,
        "governance_status": "CLEAR",
        "evidence_level": "DERIVED_CREATIVE_POLICY",
        "narrative_truth_mutation_allowed": False,
    }
