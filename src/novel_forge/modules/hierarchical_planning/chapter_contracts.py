from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


CHAPTER_CONTRACT_SCHEMA_VERSION = "chapter-mission-scene.v2"


@dataclass(frozen=True, slots=True)
class ChapterMission:
    chapter_number: int
    intent: str
    primary_function: str
    arc_plan_version_ids: frozenset[str]
    trajectory_refs: frozenset[str]
    obligation_refs: frozenset[str]
    state_transition_refs: frozenset[str]
    realization_event_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class SceneArchitecture:
    scene_ids: tuple[str, ...]
    beat_refs: tuple[tuple[str, str], ...]
    mission: ChapterMission


def require_chapter_contracts(content: Mapping[str, Any]) -> SceneArchitecture:
    if (
        content.get("chapter_contract_schema_version")
        != CHAPTER_CONTRACT_SCHEMA_VERSION
    ):
        raise KernelError(
            "CHAPTER_CONTRACT_VERSION_REQUIRED",
            "new Chapter planning requires the current Mission and Scene contract",
        )
    realization = content.get("narrative_realization_slice") or {}
    events = realization.get("events") or ()
    event_ids = frozenset(str(item.get("event_id") or "") for item in events)
    chapter_number = int(content.get("chapter_number") or content.get("chapter") or 0)
    intent = str(content.get("chapter_intent") or "").strip()
    primary = str(content.get("primary_function") or "").strip()
    if (
        chapter_number <= 0
        or not intent
        or not primary
        or not event_ids
        or "" in event_ids
        or len(event_ids) != len(events)
        or int(realization.get("accepted_through_chapter") or 0) >= chapter_number
    ):
        raise KernelError(
            "CHAPTER_MISSION_INCOMPLETE",
            "Mission needs intent, function and a future-only Frozen realization slice",
        )
    mission = ChapterMission(
        chapter_number=chapter_number,
        intent=intent,
        primary_function=primary,
        arc_plan_version_ids=frozenset(
            str(item.get("arc_plan_version_id") or "")
            for item in content.get("arc_schedule") or ()
        ),
        trajectory_refs=frozenset(
            str(ref)
            for item in content.get("character_participation") or ()
            for ref in item.get("trajectory_refs") or ()
        ),
        obligation_refs=frozenset(
            str(item.get("obligation_id") or "")
            for item in content.get("obligation_actions") or ()
        ),
        state_transition_refs=frozenset(
            str(item.get("entity_key") or "")
            for item in content.get("required_state_transitions") or ()
        ),
        realization_event_ids=event_ids,
    )
    scenes = content.get("scene_plan") or ()
    return validate_scene_mission_coverage(mission, scenes)


def validate_scene_mission_coverage(
    mission: ChapterMission, scenes: Any
) -> SceneArchitecture:
    scene_ids = tuple(str(item.get("scene_id") or "") for item in scenes)
    if not scenes or "" in scene_ids or len(set(scene_ids)) != len(scene_ids):
        raise KernelError(
            "SCENE_MISSION_IDENTITY_INVALID", "Scenes need unique identities"
        )
    required_refs = {
        "arc_progress": mission.arc_plan_version_ids,
        "trajectory_refs": mission.trajectory_refs,
        "obligation_refs": mission.obligation_refs,
        "state_transitions": mission.state_transition_refs,
        "realization_event_ids": mission.realization_event_ids,
    }
    for field, expected in required_refs.items():
        covered: set[str] = set()
        for scene in scenes:
            refs = scene.get(field)
            if (
                not isinstance(refs, list)
                or any(
                    not isinstance(ref, str) or not ref or ref not in expected
                    for ref in refs
                )
                or len(set(refs)) != len(refs)
            ):
                raise KernelError(
                    "SCENE_MISSION_REFERENCE_INVALID",
                    f"Scene {field} must reference unique frozen Mission commitments",
                )
            covered.update(refs)
        if covered != expected or "" in expected:
            raise KernelError(
                "SCENE_MISSION_COVERAGE_INCOMPLETE",
                f"Scene Architecture does not realize all Mission {field}",
            )
    beat_refs: list[tuple[str, str]] = []
    for scene in scenes:
        beats = scene.get("beats") or ()
        if not beats:
            raise KernelError(
                "SCENE_MISSION_BEAT_INVALID", "each Scene requires typed Beats"
            )
        for ordinal, beat in enumerate(beats, 1):
            if (
                not isinstance(beat, dict)
                or not str(beat.get("beat_id") or "")
                or beat.get("ordinal") != ordinal
                or not str(beat.get("function") or "").strip()
            ):
                raise KernelError(
                    "SCENE_MISSION_BEAT_INVALID", "current Beats must be typed"
                )
            beat_refs.append((str(scene["scene_id"]), str(beat["beat_id"])))
    if len(set(beat_refs)) != len(beat_refs):
        raise KernelError(
            "SCENE_MISSION_BEAT_INVALID", "Beat identities must be Scene-unique"
        )
    return SceneArchitecture(
        scene_ids=scene_ids, beat_refs=tuple(beat_refs), mission=mission
    )
