from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ChapterMission:
    source_asset_version_id: str
    source_content_hash: str
    chapter: int
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "chapter-mission.v1",
            "owner": "hierarchical-planning",
            "source_asset_version_id": self.source_asset_version_id,
            "source_content_hash": self.source_content_hash,
            "chapter": self.chapter,
            "requirements": json.loads(self.payload_json),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class SceneArchitecture:
    source_asset_version_id: str
    source_content_hash: str
    chapter: int
    mission_digest: str
    scenes_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "scene-architecture.v1",
            "owner": "hierarchical-planning",
            "source_asset_version_id": self.source_asset_version_id,
            "source_content_hash": self.source_content_hash,
            "chapter": self.chapter,
            "mission_digest": self.mission_digest,
            "dependency_kind": "PLANNING_DEPENDENCY",
            "containment_kind": "STRUCTURAL_CONTAINMENT",
            "scenes": json.loads(self.scenes_json),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


def compile_chapter_contracts(
    content: dict[str, Any], *, asset_version_id: str, content_hash: str,
) -> tuple[ChapterMission, SceneArchitecture]:
    chapter = content.get("chapter_number", content.get("chapter"))
    transitions = content.get("required_state_transitions")
    schedule = content.get("arc_schedule")
    if (
        type(chapter) is not int or chapter <= 0
        or not asset_version_id or not content_hash
        or not str(content.get("chapter_intent") or "").strip()
        or not isinstance(transitions, list) or not transitions
        or not isinstance(schedule, list) or not schedule
        or not content.get("reader_experience")
        or not content.get("expected_exit_state")
    ):
        raise KernelError("CHAPTER_MISSION_INCOMPLETE", "mission requires exact source, change, trajectory, reader and exit commitments")
    transition_entities: set[str] = set()
    for item in transitions:
        if not isinstance(item, dict) or not item.get("entity_key") or (
            not item.get("state_kind") or item.get("from_state") == item.get("to_state")
        ):
            raise KernelError("CHAPTER_MISSION_TRANSITION_INVALID", "mission requires identifiable non-noop state changes")
        entity = str(item["entity_key"])
        if entity in transition_entities:
            raise KernelError(
                "SCENE_MISSION_TRANSITION_AMBIGUOUS",
                "distinct state changes sharing an entity require typed scene transition references",
            )
        transition_entities.add(entity)
    if any(not isinstance(item, dict) for item in schedule):
        raise KernelError("CHAPTER_MISSION_TRAJECTORY_INVALID", "trajectory schedule entries must be objects")
    arcs = {str(item.get("arc_plan_version_id") or "") for item in schedule}
    required_arcs = {str(item["arc_plan_version_id"]) for item in schedule if item.get("role") != "HOLD" and item.get("arc_plan_version_id")}
    if "" in arcs or not arcs:
        raise KernelError("CHAPTER_MISSION_TRAJECTORY_INVALID", "mission must bind exact trajectory versions")
    fields = (
        "chapter_intent", "required_state_transitions", "arc_schedule",
        "setups", "payoffs", "obligation_actions", "reader_experience",
        "expected_exit_state", "prohibited_outcomes", "character_participation",
        "knowledge_boundaries", "disclosures", "narrative_realization_slice",
    )
    mission = ChapterMission(asset_version_id, content_hash, chapter, _json({
        key: content[key] for key in fields if key in content
    }))
    scenes = content.get("scene_plan")
    if not isinstance(scenes, list) or not scenes or any(not isinstance(s, dict) for s in scenes):
        raise KernelError("SCENE_ARCHITECTURE_REQUIRED", "scene architecture requires an ordered scene set")
    ids = [str(scene.get("scene_id") or "") for scene in scenes]
    if "" in ids or len(set(ids)) != len(ids):
        raise KernelError("SCENE_ARCHITECTURE_IDENTITY_DUPLICATE", "scene identities must be unique")
    realized_entities = {str(ref) for scene in scenes for ref in scene.get("state_transitions") or ()}
    realized_arcs = {str(ref) for scene in scenes for ref in scene.get("arc_progress") or ()}
    if realized_entities != transition_entities or not required_arcs <= realized_arcs or not realized_arcs <= arcs:
        raise KernelError(
            "SCENE_MISSION_COVERAGE_INVALID",
            "scenes must cover every mission state change and trajectory without undeclared contributions",
        )
    architecture = SceneArchitecture(asset_version_id, content_hash, chapter, mission.digest, _json(scenes))
    return mission, architecture


def chapter_contract_evidence(content: dict[str, Any], *, asset_version_id: str, content_hash: str) -> dict[str, Any]:
    mission, scenes = compile_chapter_contracts(content, asset_version_id=asset_version_id, content_hash=content_hash)
    return {
        "schema_version": "chapter-planning-boundaries.v1",
        "chapter_mission": mission.to_dict(),
        "chapter_mission_digest": mission.digest,
        "scene_architecture": scenes.to_dict(),
        "scene_architecture_digest": scenes.digest,
        "gate": "STRUCTURAL_COVERAGE_PASS",
        "proof_ceiling": "NARRATIVE_CONTRACT_ONLY",
        "accepted_fact_mutation": False,
    }
