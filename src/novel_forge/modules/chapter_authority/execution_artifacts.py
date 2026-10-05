from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def _hash(value: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def validate_chapter_execution_intent(
    intent: Mapping[str, Any],
    *,
    expected_plan_asset_version_id: str = "",
    expected_plan_content_hash: str = "",
) -> dict[str, Any]:

    normalized = dict(intent)
    intent_fingerprint = str(normalized.pop("intent_fingerprint", ""))
    mission = normalized.get("chapter_mission")
    source_plan = normalized.get("source_chapter_plan")
    if (
        normalized.get("type") != "ChapterExecutionIntent"
        or normalized.get("contract_version")
        not in {
            "chapter-execution-intent-v2",
            "chapter-execution-intent-v3",
            "chapter-execution-intent-v4",
        }
        or not isinstance(mission, Mapping)
        or not isinstance(source_plan, Mapping)
        or not source_plan.get("locked")
    ):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_INVALID",
            "ExecutionIntent v2 requires a locked Plan and compiled Mission",
        )
    mission_body = dict(mission)
    mission_fingerprint = str(mission_body.pop("mission_fingerprint", ""))
    if not mission_fingerprint or mission_fingerprint != _hash(mission_body):
        raise KernelError(
            "CHAPTER_MISSION_FINGERPRINT_INVALID",
            "Chapter Mission content differs from its compiled fingerprint",
        )
    if not intent_fingerprint or intent_fingerprint != _hash(normalized):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_FINGERPRINT_INVALID",
            "ExecutionIntent content differs from its immutable fingerprint",
        )
    if expected_plan_asset_version_id and (
        source_plan.get("asset_version_id") != expected_plan_asset_version_id
    ):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_PLAN_DRIFT",
            "ExecutionIntent is bound to another ChapterPlan AssetVersion",
        )
    if expected_plan_content_hash and (
        source_plan.get("content_hash") != expected_plan_content_hash
    ):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_PLAN_DRIFT",
            "ExecutionIntent is bound to another ChapterPlan content hash",
        )
    mission_arc_ids = {
        str(item.get("arc_plan_version_id") or "")
        for item in mission.get("arc_contributions") or ()
        if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
    }
    scene_arc_ids = {
        str(arc_id)
        for scene in normalized.get("scene_plans") or ()
        if isinstance(scene, Mapping)
        for arc_id in scene.get("arc_progress") or ()
        if str(arc_id)
    }
    if (
        not mission_arc_ids
        and normalized.get("contract_version") != "chapter-execution-intent-v4"
    ) or mission_arc_ids != scene_arc_ids:
        raise KernelError(
            "CHAPTER_MISSION_ARC_COMPOSITION_INVALID",
            "ExecutionIntent Scenes must cover the exact compiled Mission Arc set",
        )
    realization = mission.get("narrative_realization")
    if not isinstance(realization, Mapping):
        raise KernelError(
            "CHAPTER_MISSION_REALIZATION_INVALID",
            "ExecutionIntent realization evidence must be an object",
        )
    # COMPATIBILITY: direct Chapter operations replay, while resolved Book
    # production requires non-empty exact realization slices.
    if realization and (
        int(realization.get("chapter_number") or 0)
        != int(normalized.get("chapter") or 0)
        or not realization.get("events")
        or not str(realization.get("contract_digest") or "").startswith("sha256:")
    ):
        raise KernelError(
            "CHAPTER_MISSION_REALIZATION_INVALID",
            "ExecutionIntent does not preserve its Frozen realization slice",
        )
    if normalized.get("contract_version") == "chapter-execution-intent-v3" or (
        normalized.get("contract_version") == "chapter-execution-intent-v4"
        and normalized.get("mission_schema_version")
        in {"chapter-mission-scene.v2", "chapter-mission-scene.v3"}
    ):
        from novel_forge.modules.hierarchical_planning.chapter_contracts import (
            ChapterMission,
            validate_scene_mission_coverage,
        )

        validate_scene_mission_coverage(
            ChapterMission(
                chapter_number=int(normalized["chapter"]),
                intent=str(mission["why_this_chapter_exists"]),
                primary_function=str(mission["primary_function"]),
                arc_plan_version_ids=frozenset(mission_arc_ids),
                trajectory_refs=frozenset(mission["trajectory_refs"]),
                obligation_refs=frozenset(mission["obligation_refs"]),
                state_transition_refs=frozenset(
                    str(item["entity_key"])
                    for item in mission["required_outcomes"]["state_transitions"]
                ),
                realization_event_ids=frozenset(
                    str(item["event_id"]) for item in realization["events"]
                ),
            ),
            normalized.get("scene_plans") or (),
        )
    if "craft_strategy" in normalized:
        from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_strategy
        validate_craft_strategy(normalized["craft_strategy"], scenes=normalized.get("scene_plans", []))
    return dict(intent)


def validate_chapter_memo(
    memo: Mapping[str, Any],
    *,
    intent: Mapping[str, Any],
    intent_asset_version_id: str,
) -> dict[str, Any]:

    validated_intent = validate_chapter_execution_intent(intent)
    normalized = dict(memo)
    memo_fingerprint = str(normalized.pop("memo_fingerprint", ""))
    mission = dict(validated_intent["chapter_mission"])
    if (
        normalized.get("type") != "ChapterMemo"
        or normalized.get("contract_version") != "chapter-memo-v2"
        or normalized.get("qualification") != "QUALIFIED"
        or normalized.get("source_chapter_execution_intent_asset_version_id")
        != intent_asset_version_id
        or normalized.get("source_chapter_plan")
        != validated_intent.get("source_chapter_plan")
        or normalized.get("accepted_boundary")
        != validated_intent.get("accepted_boundary")
        or normalized.get("mission_fingerprint") != mission.get("mission_fingerprint")
        or normalized.get("narrative_realization")
        != mission.get("narrative_realization")
    ):
        raise KernelError(
            "CHAPTER_MEMO_INTENT_DRIFT",
            "ChapterMemo no longer matches its exact ExecutionIntent",
        )
    if not memo_fingerprint or memo_fingerprint != _hash(normalized):
        raise KernelError(
            "CHAPTER_MEMO_FINGERPRINT_INVALID",
            "ChapterMemo content differs from its immutable fingerprint",
        )
    if normalized.get("craft_strategy") != validated_intent.get("craft_strategy"):
        raise KernelError("CHAPTER_MEMO_CRAFT_DRIFT", "Memo must retain the frozen planning Craft strategy")
    expected_scene_ids = {
        str(item.get("scene_id") or "")
        for item in validated_intent.get("scene_plans") or ()
        if isinstance(item, Mapping) and str(item.get("scene_id") or "")
    }
    actual_scene_ids = {
        str(item.get("scene_id") or "")
        for item in normalized.get("scene_directives") or ()
        if isinstance(item, Mapping) and str(item.get("scene_id") or "")
    }
    expected_arc_ids = {
        str(item.get("arc_plan_version_id") or "")
        for item in mission.get("arc_contributions") or ()
        if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
    }
    actual_arc_ids = {
        str(item.get("arc_plan_version_id") or "")
        for item in normalized.get("arc_actions") or ()
        if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
    }
    if actual_scene_ids != expected_scene_ids or actual_arc_ids != expected_arc_ids:
        raise KernelError(
            "CHAPTER_MEMO_MISSION_DRIFT",
            "ChapterMemo directives must cover the exact locked Mission Scenes and Arcs",
        )
    return dict(memo)


def build_chapter_execution_intent(
    *,
    project_id: str,
    operation_id: str,
    chapter_plan_asset_version_id: str,
    chapter_plan_content_hash: str,
    chapter_plan: Mapping[str, Any],
    accepted_inputs: Iterable[Mapping[str, Any]],
    work_requirements: bool = False,
    style_view: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_contract = None
    if chapter_plan.get("chapter_contract_schema_version"):
        from novel_forge.modules.hierarchical_planning.chapter_contracts import (
            require_chapter_contracts,
        )

        current_contract = require_chapter_contracts(chapter_plan)

    chapter = int(
        chapter_plan.get("chapter") or chapter_plan.get("chapter_number") or 0
    )
    if (
        chapter <= 0
        or not chapter_plan_asset_version_id
        or not chapter_plan_content_hash
    ):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_PLAN_INVALID",
            "ExecutionIntent requires an exact authoritative ChapterPlan version",
        )
    accepted_by_type = {
        str(item.get("asset_type") or ""): dict(item) for item in accepted_inputs
    }
    story = accepted_by_type.get("story_state_snapshot")
    canon = accepted_by_type.get("canon_snapshot")
    expected_boundary = chapter - 1
    if bool(story) != bool(canon):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_BOUNDARY_INCOMPLETE",
            "accepted Story State and Canon inputs must be present together",
        )
    if story and canon:
        story_boundary = int(story.get("accepted_through_chapter") or 0)
        canon_boundary = int(canon.get("accepted_through_chapter") or 0)
        if story_boundary != expected_boundary or canon_boundary != expected_boundary:
            raise KernelError(
                "CHAPTER_EXECUTION_INTENT_BOUNDARY_MISMATCH",
                "ExecutionIntent can only use the immediately preceding Accepted Chapter",
            )
    scenes = []
    for ordinal, raw in enumerate(chapter_plan.get("scene_plan") or (), start=1):
        if not isinstance(raw, Mapping) or not str(raw.get("scene_id") or ""):
            raise KernelError(
                "CHAPTER_EXECUTION_INTENT_SCENE_INVALID",
                "ExecutionIntent requires addressable ScenePlan children",
            )
        beats = []
        for beat_ordinal, raw_beat in enumerate(raw.get("beats") or (), start=1):
            beat = (
                dict(raw_beat)
                if isinstance(raw_beat, Mapping)
                else {
                    "beat_id": f"{raw['scene_id']}:beat:{beat_ordinal}",
                    "function": str(raw_beat),
                    "expected_reader_effect": "",
                }
            )
            beats.append(
                {
                    "beat_id": str(
                        beat.get("beat_id") or f"{raw['scene_id']}:beat:{beat_ordinal}"
                    ),
                    "ordinal": beat_ordinal,
                    "function": str(beat.get("function") or ""),
                    "expected_reader_effect": str(
                        beat.get("expected_reader_effect") or ""
                    ),
                }
            )
        scenes.append(
            {
                "scene_id": str(raw["scene_id"]),
                "scene_version": int(raw.get("scene_version") or 1),
                "ordinal": ordinal,
                "goal": str(raw.get("goal") or ""),
                "conflict": str(raw.get("conflict") or ""),
                "participants": [str(item) for item in raw.get("participants") or ()],
                "arc_progress": [str(item) for item in raw.get("arc_progress") or ()],
                **(
                    {
                        field: list(raw[field])
                        for field in ("trajectory_refs", "obligation_refs", "realization_event_ids")
                    }
                    if current_contract is not None else {}
                ),
                "information_gain": [
                    str(item) for item in raw.get("information_gain") or ()
                ],
                "state_transitions": [
                    str(item) for item in raw.get("state_transitions") or ()
                ],
                "entry_state": str(raw.get("entry_state") or ""),
                "exit_state": str(raw.get("exit_state") or ""),
                "reader_effect": str(raw.get("reader_effect") or ""),
                "beats": beats,
            }
        )
    envelope = chapter_plan.get("constraint_envelope")
    working_set = (
        dict(envelope.get("arc_working_set") or {})
        if isinstance(envelope, Mapping)
        else {}
    )
    selected_contributions = [
        dict(item)
        for item in working_set.get("selected_contributions") or ()
        if isinstance(item, Mapping)
    ]
    if not selected_contributions:
        selected_contributions = [
            {
                "arc_plan_version_id": str(
                    item.get("arc_plan_version_id") or item.get("arc_id") or ""
                ),
                "role": "PRIMARY" if index == 0 else "SECONDARY",
                "action": str(
                    item.get("contribution")
                    or item.get("contribution_kind")
                    or "ADVANCE"
                ),
            }
            for index, item in enumerate(
                chapter_plan.get("required_arc_contributions") or ()
            )
            if isinstance(item, Mapping)
        ]
    if work_requirements:
        planned_arc_ids = {
            str(item.get("arc_plan_version_id") or "")
            for item in chapter_plan.get("required_arc_contributions") or ()
            if isinstance(item, Mapping)
        }
        selected_contributions = [
            item
            for item in selected_contributions
            if item["arc_plan_version_id"] in planned_arc_ids
        ]
    required_arc_ids = {
        str(item.get("arc_plan_version_id") or "")
        for item in selected_contributions
        if str(item.get("arc_plan_version_id") or "")
    }
    scene_arc_ids = {
        arc_id for scene in scenes for arc_id in scene["arc_progress"] if arc_id
    }
    if (
        not required_arc_ids and not work_requirements
    ) or scene_arc_ids != required_arc_ids:
        raise KernelError(
            "CHAPTER_MISSION_ARC_COMPOSITION_INVALID",
            "Chapter Mission requires every selected Arc to be composed into its Scene events",
        )
    if (
        not work_requirements
        and len(required_arc_ids) > 1
        and not any(len(set(scene["arc_progress"])) > 1 for scene in scenes)
    ):
        raise KernelError(
            "CHAPTER_MISSION_ARC_COMPOSITION_FRAGMENTED",
            "Multi-Arc Chapter Missions require at least one shared causal Scene event",
        )
    required_transitions = [
        dict(item)
        for item in chapter_plan.get("required_state_transitions") or ()
        if isinstance(item, Mapping)
    ]
    composition_events = [
        _composition_event(scene=scene, transitions=required_transitions)
        for scene in scenes
    ]
    required_beats = [
        {"scene_id": scene["scene_id"], **dict(beat)}
        for scene in scenes
        for beat in scene["beats"]
    ]
    reader_experience = dict(chapter_plan.get("reader_experience") or {})
    mission_body = {
        "why_this_chapter_exists": str(
            chapter_plan.get("chapter_intent")
            or chapter_plan.get("objective")
            or chapter_plan.get("primary_function")
            or ""
        ),
        "entry_state": {
            "entry_state_ref": str(chapter_plan.get("entry_state_ref") or ""),
            "first_scene_state": str(scenes[0]["entry_state"] if scenes else ""),
            "previous_accepted_ending": str((story or {}).get("previous_ending") or ""),
        },
        "required_outcomes": {
            "required_state_delta": dict(
                chapter_plan.get("required_state_delta") or {}
            ),
            "state_transitions": required_transitions,
            "required_events": [
                str(item) for item in chapter_plan.get("required_events") or ()
            ],
            "required_payoffs": [
                str(item) for item in chapter_plan.get("required_payoffs") or ()
            ],
        },
        "required_beats": required_beats,
        "arc_contributions": selected_contributions,
        "forbidden_changes": {
            "hard_constraints": [
                str(item) for item in chapter_plan.get("hard_constraints") or ()
            ],
            "prohibited_outcomes": [
                str(item) for item in chapter_plan.get("prohibited_outcomes") or ()
            ],
            "forbidden_events": [
                str(item) for item in chapter_plan.get("forbidden_events") or ()
            ],
            "forbidden_payoffs": [
                str(item) for item in chapter_plan.get("forbidden_payoffs") or ()
            ],
        },
        "knowledge_and_disclosure_boundaries": {
            "knowledge_boundaries": [
                dict(item)
                for item in chapter_plan.get("knowledge_boundaries") or ()
                if isinstance(item, Mapping)
            ],
            "disclosures": [
                dict(item)
                for item in chapter_plan.get("disclosures") or ()
                if isinstance(item, Mapping)
            ],
        },
        "reader_effect": reader_experience,
        "hook_intent": {
            "ending_hook": str(
                chapter_plan.get("ending_hook")
                or chapter_plan.get("closing_hook")
                or ""
            ),
            "unresolved_exit_question": str(
                reader_experience.get("exit_question") or ""
            ),
        },
        "unresolved_obligation_intent": {
            "setups": [
                dict(item)
                for item in chapter_plan.get("setups") or ()
                if isinstance(item, Mapping)
            ],
            "payoffs": [
                dict(item)
                for item in chapter_plan.get("payoffs") or ()
                if isinstance(item, Mapping)
            ],
            "scheduled_actions": [
                dict(item)
                for item in chapter_plan.get("obligation_actions") or ()
                if isinstance(item, Mapping)
            ],
        },
        "expected_exit_state": dict(chapter_plan.get("expected_exit_state") or {}),
        "narrative_composition": {
            "contract_version": "chapter-narrative-composition-v1",
            "event_count": len(composition_events),
            "multi_arc_event_count": sum(
                len(set(item["arc_contributions"])) > 1 for item in composition_events
            ),
            "events": composition_events,
            "composition_rule": "CAUSAL_MULTI_FUNCTION_EVENTS",
        },
        "arc_working_set": {
            "working_set_digest": str(working_set.get("working_set_digest") or ""),
            "accepted_reality": dict(working_set.get("accepted_reality") or {}),
            "schedule_correction": dict(working_set.get("schedule_correction") or {}),
        },
        "narrative_realization": dict(
            chapter_plan.get("narrative_realization_slice") or {}
        ),
    }
    mission = {**mission_body, "mission_fingerprint": _hash(mission_body)}
    if current_contract is not None:
        mission_body.pop("required_beats")
        mission_body.update({
            "primary_function": current_contract.mission.primary_function,
            "trajectory_refs": sorted(current_contract.mission.trajectory_refs),
            "obligation_refs": sorted(current_contract.mission.obligation_refs),
        })
        mission = {**mission_body, "mission_fingerprint": _hash(mission_body)}
    intent = {
        "type": "ChapterExecutionIntent",
        "contract_version": (
            "chapter-execution-intent-v4"
            if work_requirements
            else "chapter-execution-intent-v3"
            if current_contract is not None
            else "chapter-execution-intent-v2"
        ),
        **({"required_beats": required_beats} if current_contract is not None else {}),
        **(
            {
                "mission_schema_version": chapter_plan.get(
                    "chapter_contract_schema_version"
                )
                or "LEGACY"
            }
            if work_requirements
            else {}
        ),
        "project_id": project_id,
        "chapter": chapter,
        "source_chapter_plan": {
            "asset_version_id": chapter_plan_asset_version_id,
            "content_hash": chapter_plan_content_hash,
            "locked": True,
        },
        "accepted_boundary": {
            "accepted_through_chapter": expected_boundary,
            "story_state_asset_version_id": str(
                (story or {}).get("asset_version_id") or ""
            ),
            "canon_snapshot_asset_version_id": str(
                (canon or {}).get("asset_version_id") or ""
            ),
        },
        "chapter_objective": str(
            chapter_plan.get("objective") or chapter_plan.get("primary_function") or ""
        ),
        "required_arc_contributions": list(
            chapter_plan.get("required_arc_contributions") or ()
        ),
        "active_obligations": list(
            ((story or {}).get("current_state") or {}).get("narrative_obligation", ())
        ),
        "retrieval_graph": {
            key: sorted(
                {
                    *(str(item) for item in chapter_plan.get(key) or () if str(item)),
                    *(
                        str(item)
                        for source in accepted_by_type.values()
                        for item in _graph_ids(source, key)
                        if str(item)
                    ),
                }
            )
            for key in (
                "entity_ids",
                "character_ids",
                "relationship_ids",
            )
        },
        "previous_ending": str((story or {}).get("previous_ending") or ""),
        "reader_tension": dict((story or {}).get("reader_tension") or {}),
        "scene_plans": scenes,
        "chapter_mission": mission,
        "created_by_operation_id": operation_id,
    }
    if "craft_strategy" in chapter_plan:
        from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_strategy
        intent["craft_strategy"] = validate_craft_strategy(chapter_plan["craft_strategy"], scenes=scenes)
    if work_requirements:
        from .chapter_plan_views import build_draft_plan_view

        view = build_draft_plan_view(dict(chapter_plan), work_requirements=True)
        intent["creative_requirements"] = {
            key: view[key]
            for key in (
                "style_constraints",
                "point_of_view",
                "target_word_count",
                "prohibited_outcomes",
                "author_design_guidance",
                "method_choices",
            )
            if key in view
        }
        if style_view is not None:
            intent["creative_requirements"]["style"] = dict(style_view)
    intent["intent_fingerprint"] = _hash(intent)
    return intent


def _composition_event(
    *, scene: Mapping[str, Any], transitions: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    transition_by_entity = {
        str(item.get("entity_key") or ""): str(item.get("state_kind") or "")
        for item in transitions
        if str(item.get("entity_key") or "")
    }
    state_kinds = {
        transition_by_entity.get(str(entity), "")
        for entity in scene.get("state_transitions") or ()
    }
    functions = {"PLOT"}
    if scene.get("participants") or any("character" in item for item in state_kinds):
        functions.add("CHARACTER")
    if any("relationship" in item for item in state_kinds):
        functions.add("RELATIONSHIP")
    if any("world" in item or "faction" in item for item in state_kinds):
        functions.add("WORLD")
    if scene.get("information_gain"):
        functions.add("MYSTERY_DISCLOSURE")
    if any("power" in item or "resource" in item for item in state_kinds):
        functions.add("POWER_RESOURCE")
    if scene.get("reader_effect") or scene.get("beats"):
        functions.add("READER_EXPERIENCE")
    return {
        "event_id": str(scene.get("scene_id") or ""),
        "causal_intent": {
            "goal": str(scene.get("goal") or ""),
            "conflict": str(scene.get("conflict") or ""),
            "entry_state": str(scene.get("entry_state") or ""),
            "exit_state": str(scene.get("exit_state") or ""),
        },
        "arc_contributions": list(scene.get("arc_progress") or ()),
        "narrative_functions": sorted(functions),
        "participants": list(scene.get("participants") or ()),
        "information_gain": list(scene.get("information_gain") or ()),
        "state_transitions": list(scene.get("state_transitions") or ()),
        "reader_effect": str(scene.get("reader_effect") or ""),
        "beat_ids": [
            str(item.get("beat_id") or "")
            for item in scene.get("beats") or ()
            if isinstance(item, Mapping)
        ],
    }


def _graph_ids(value: Any, target_key: str) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == target_key and isinstance(item, (list, tuple, set)):
                found.update(str(entry) for entry in item if str(entry))
            elif key == target_key[:-1] and isinstance(item, str) and item:
                found.add(item)
            found.update(_graph_ids(item, target_key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_graph_ids(item, target_key))
    return found


def qualify_chapter_memo(
    *,
    intent: Mapping[str, Any],
    intent_asset_version_id: str,
    result: Mapping[str, Any],
    execution_evidence: Mapping[str, Any],
) -> dict[str, Any]:

    validated_intent = validate_chapter_execution_intent(intent)

    required = (
        "execution_strategy",
        "tension_strategy",
        "scene_directives",
        "retrieval_queries",
        "obligation_actions",
        "arc_actions",
    )
    if any(key not in result for key in required):
        raise KernelError(
            "CHAPTER_MEMO_UNQUALIFIED",
            "ChapterMemo provider output is incomplete",
        )
    source_plan = dict(validated_intent.get("source_chapter_plan") or {})
    mission = dict(validated_intent.get("chapter_mission") or {})
    if not source_plan.get("locked") or not intent_asset_version_id:
        raise KernelError(
            "CHAPTER_MEMO_INTENT_INVALID",
            "ChapterMemo requires a locked, materialized ExecutionIntent",
        )
    if not mission.get("mission_fingerprint"):
        raise KernelError(
            "CHAPTER_MEMO_MISSION_INVALID",
            "ChapterMemo requires the compiled Chapter Mission",
        )
    expected_scene_ids = {
        str(item.get("scene_id") or "")
        for item in validated_intent.get("scene_plans") or ()
        if isinstance(item, Mapping)
    }
    actual_scene_ids = {
        str(item.get("scene_id") or "")
        for item in result["scene_directives"]
        if isinstance(item, Mapping)
    }
    expected_arc_ids = {
        str(item.get("arc_plan_version_id") or "")
        for item in mission.get("arc_contributions") or ()
        if isinstance(item, Mapping)
    }
    actual_arc_ids = {
        str(item.get("arc_plan_version_id") or "")
        for item in result["arc_actions"]
        if isinstance(item, Mapping)
    }
    if actual_scene_ids != expected_scene_ids or actual_arc_ids != expected_arc_ids:
        raise KernelError(
            "CHAPTER_MEMO_MISSION_DRIFT",
            "ChapterMemo directives must cover the exact locked Mission Scenes and Arcs",
        )
    memo = {
        "type": "ChapterMemo",
        "contract_version": "chapter-memo-v2",
        "chapter": int(validated_intent.get("chapter") or 0),
        "source_chapter_execution_intent_asset_version_id": intent_asset_version_id,
        "source_chapter_plan": source_plan,
        "accepted_boundary": dict(validated_intent.get("accepted_boundary") or {}),
        "mission_fingerprint": str(mission["mission_fingerprint"]),
        "execution_strategy": str(result.get("execution_strategy") or ""),
        "tension_strategy": str(result.get("tension_strategy") or ""),
        "composition_strategy": str(
            result.get("composition_strategy")
            or "realize the locked causal multi-function event graph"
        ),
        "event_directives": [
            {
                "event_id": str(item.get("event_id") or ""),
                "arc_contributions": list(item.get("arc_contributions") or ()),
                "narrative_functions": list(item.get("narrative_functions") or ()),
                "causal_intent": dict(item.get("causal_intent") or {}),
            }
            for item in (mission.get("narrative_composition") or {}).get("events") or ()
            if isinstance(item, Mapping)
        ],
        "narrative_realization": dict(mission.get("narrative_realization") or {}),
        "scene_directives": [dict(item) for item in result["scene_directives"]],
        "retrieval_queries": [str(item) for item in result["retrieval_queries"]],
        "obligation_actions": [dict(item) for item in result["obligation_actions"]],
        "arc_actions": [dict(item) for item in result["arc_actions"]],
        "forbidden_changes": dict(mission.get("forbidden_changes") or {}),
        "reader_effect": dict(mission.get("reader_effect") or {}),
        "hook_intent": dict(mission.get("hook_intent") or {}),
        "stop_conditions": [str(item) for item in result.get("stop_conditions") or ()],
        "execution_evidence": dict(execution_evidence),
        "qualification": "QUALIFIED",
    }
    if "creative_guidance" in result:
        memo["creative_guidance"] = dict(result["creative_guidance"])
        memo["creative_contract_version"] = "creative-memo.v1"
    if "craft_strategy" in validated_intent:
        from copy import deepcopy
        memo["craft_strategy"] = deepcopy(validated_intent["craft_strategy"])
    memo["memo_fingerprint"] = _hash(memo)
    return validate_chapter_memo(
        memo,
        intent=validated_intent,
        intent_asset_version_id=intent_asset_version_id,
    )


__all__ = [
    "build_chapter_execution_intent",
    "qualify_chapter_memo",
    "validate_chapter_execution_intent",
    "validate_chapter_memo",
]
