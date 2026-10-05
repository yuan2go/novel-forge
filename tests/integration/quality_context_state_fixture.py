import hashlib
import json

from novel_forge.modules.authority_handler_runtime.contracts import (
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.creative.style_projection import compile_foundation_style
from novel_forge.modules.story_planning_runtime.application import (
    _chapter_runtime_projection,
)


def current_state_inputs(project, candidates):
    def source(kind, content):
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        return AuthorityInputAsset(
            f"{project}:state-fixture:{kind}:v1", kind, digest, content
        )

    book = f"book:{project}"
    creative = source(
        "creative_foundation",
        {
            "book_id": book,
            "candidate_payload": {
                "style_profile": {
                    "constraints": ["Use concrete witnessed details."],
                    "narrator": "plain observation",
                    "pov": "limited",
                    "genre_conventions": [],
                },
                "serialization_potential": None,
                "applicability": [
                    {
                        "field_path": "$.serialization_potential",
                        "status": "NOT_APPLICABLE",
                        "rationale": "Offline state fixture explicitly declines serial rhythm.",
                    }
                ],
            },
        },
    )
    cast = source(
        "character_cast", {"book_id": book, "candidate_payload": {"characters": []}}
    )
    design = source(
        "book_design",
        {
            "schema_version": "book-design.v7",
            "book_id": book,
            "foundation_set": {
                "bindings": [
                    {
                        "role": role,
                        "asset_version_id": asset.asset_version_id,
                        "content_hash": asset.content_hash,
                    }
                    for role, asset in [
                        ("CREATIVE_FOUNDATION", creative),
                        ("CHARACTER_CAST", cast),
                    ]
                ]
            },
        },
    )
    style = compile_foundation_style(
        AuthorityHandlerRequest(
            "offline-state-style-compilation",
            project,
            f"workspace:{project}",
            "fixture",
            "fixture-trace",
            "fixture-correlation",
            "chapter.style_policy.compile",
            "2.1.4",
            {},
            (design, creative, cast),
        )
    )
    result = list(candidates)
    for candidate in result:
        if candidate["asset_type"] != "chapter_plan":
            continue
        plan = candidate["content"]
        event = f"{project}:offline-state-realization:event:1"
        arcs = [
            item["arc_plan_version_id"] for item in plan["required_arc_contributions"]
        ]
        scene = {
            **plan["scene_plan"][0],
            "trajectory_refs": [],
            "obligation_refs": [],
            "state_transitions": [],
            "realization_event_ids": [event],
            "beats": [
                {
                    "beat_id": f"fixture-beat:{index}",
                    "ordinal": index,
                    "function": value,
                }
                for index, value in enumerate(plan["scene_plan"][0]["beats"], 1)
            ],
        }
        typed = {
            **plan,
            "book_id": book,
            "chapter_contract_schema_version": "chapter-mission-scene.v3",
            "chapter_intent": plan["chapter_objective"],
            "objective": plan["chapter_objective"],
            "primary_function": "observation",
            "arc_schedule": [{"arc_plan_version_id": arc} for arc in arcs],
            "character_participation": [],
            "obligation_actions": [],
            "required_state_transitions": [],
            "narrative_realization_slice": {
                "accepted_through_chapter": 0,
                "chapter_number": 1,
                "contract_digest": "sha256:"
                + hashlib.sha256(event.encode()).hexdigest(),
                "events": [{"event_id": event}],
            },
            "scene_plan": [scene],
            "ending_hook": plan["chapter_hook"],
            "reward_action": None,
            "promise_action": None,
            "antagonist_actions": [],
            "emotional_curve": [],
            "suspense_curve": [],
            "protagonist_charm_mechanism": None,
            "antagonist_pressure": None,
            "serialization_function": None,
            "constraint_envelope": {
                **plan["constraint_envelope"],
                "creative_requirements_contract": "work-requirements.v1",
            },
        }
        candidate["content"] = _chapter_runtime_projection(typed)
    for asset in (creative, cast, design, source("style_policy", style)):
        result.append(
            {
                "asset_type": asset.asset_type,
                "asset_version_id": asset.asset_version_id,
                "content_hash": asset.content_hash,
                "content": asset.content,
                "project_id": project,
                "estimated_tokens": 200,
                "safe_summary": "Explicit OFFLINE state fixture input; no production qualification.",
                "structured_facts": asset.content.get("structured_facts", []),
                "narrative_function": asset.asset_type,
                "allowed_use": "generation",
                "source_use_mode": "generation",
            }
        )
    return tuple(result)
