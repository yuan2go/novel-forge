from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash


class RealizationCapability(StrEnum):
    SKELETON = "SKELETON"
    DIALOGUE = "DIALOGUE"
    ACTION = "ACTION"
    INTERIOR = "INTERIOR"
    DESCRIPTION = "DESCRIPTION"
    TRANSITION = "TRANSITION"
    INTEGRATION = "INTEGRATION"


VOICE_LAYERS = frozenset({"BOOK", "NARRATOR", "POV", "CHARACTER", "DIALOGUE", "GENRE"})


@dataclass(frozen=True, slots=True)
class RealizationSlot:
    slot_id: str
    scene_id: str
    capability: RealizationCapability
    beat_ids: tuple[str, ...]
    character_ids: tuple[str, ...]
    accessible_knowledge: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "scene_id": self.scene_id,
            "capability": self.capability.value,
            "beat_ids": list(self.beat_ids),
            "character_ids": list(self.character_ids),
            "accessible_knowledge": list(self.accessible_knowledge),
        }


def compile_realization_contract(
    plan: Mapping[str, Any], style: Mapping[str, Any]
) -> dict[str, Any]:
    scenes = plan.get("scene_plan") or []
    slots = []
    legacy_beats = False
    for scene in scenes:
        beat_ids = []
        for ordinal, beat in enumerate(scene.get("beats", [])):
            if (
                isinstance(beat, dict)
                and isinstance(beat.get("beat_id"), str)
                and beat["beat_id"]
            ):
                beat_ids.append(beat["beat_id"])
            elif (
                isinstance(beat, str)
                and beat.strip()
                and plan.get("chapter_contract_schema_version")
                != "chapter-mission-scene.v2"
            ):
                legacy_beats = True
                beat_ids.append(f"{scene['scene_id']}:legacy-beat:{ordinal}")
            else:
                raise KernelError(
                    "REALIZATION_BEAT_CONTRACT_INVALID",
                    "current Scene Architecture requires exact typed Beat identities",
                )
        capabilities = scene.get("realization_capabilities", ["SKELETON"])
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or len(set(capabilities)) != len(capabilities)
            or not set(capabilities).issubset(set(RealizationCapability))
            or "SKELETON" not in capabilities
        ):
            raise KernelError(
                "REALIZATION_CAPABILITY_INVALID",
                "Scene capability selection must be unique, typed and include its narrative skeleton",
            )
        known = {
            item["character_id"]: set(item.get("known_fact_ids", []))
            for item in plan.get("character_participation", [])
        }
        for capability in capabilities:
            actors = (
                list(scene.get("participants", []))
                if capability == "DIALOGUE"
                else [str(scene.get("pov_character_id") or "")]
                if capability == "INTERIOR"
                else [""]
            )
            if capability in {"DIALOGUE", "INTERIOR"} and (
                not actors or any(not actor for actor in actors)
            ):
                raise KernelError(
                    "REALIZATION_ACTOR_SCOPE_REQUIRED",
                    "Dialogue and Interior slots require explicit Scene actors",
                )
            for actor in actors:
                accessible = set(scene.get("accessible_knowledge", []))
                if actor:
                    accessible &= known.get(actor, set())
                slot = RealizationSlot(
                    slot_id=f"{scene['scene_id']}:{capability.lower()}"
                    + (f":{actor}" if actor else ""),
                    scene_id=scene["scene_id"],
                    capability=RealizationCapability(capability),
                    beat_ids=tuple(beat_ids),
                    character_ids=(actor,)
                    if actor
                    else tuple(scene.get("participants", [])),
                    accessible_knowledge=tuple(sorted(accessible)),
                )
                slots.append(slot.to_dict())
    voices = []
    voice_identities = set()
    for policy in style.get("policies", []):
        for fact in policy.get("structured_facts", []):
            if not isinstance(fact, dict) or fact.get("kind") != "voice_contract":
                continue
            if fact.get("layer") not in VOICE_LAYERS or not fact.get("voice_id"):
                raise KernelError(
                    "REALIZATION_VOICE_CONTRACT_INVALID",
                    "Voice requires a declared layer and identity",
                )
            if any(
                not isinstance(fact.get(key, []), list)
                or any(
                    not isinstance(item, str) or not item for item in fact.get(key, [])
                )
                for key in ("required_markers", "forbidden_markers")
            ):
                raise KernelError(
                    "REALIZATION_VOICE_CONTRACT_INVALID",
                    "Voice markers must be explicit nonempty strings",
                )
            identity = (
                fact["layer"],
                str(fact.get("character_id") or ""),
                fact["voice_id"],
            )
            if identity in voice_identities or (
                fact["layer"] in {"CHARACTER", "POV"} and not fact.get("character_id")
            ):
                raise KernelError(
                    "REALIZATION_VOICE_SCOPE_INVALID",
                    "Voice contracts need unique scoped identities; Character and POV voices need an actor",
                )
            voice_identities.add(identity)
            voices.append({"asset_version_id": policy["asset_version_id"], **fact})
    body = {
        "contract_version": "scene-realization-composition.v1",
        "plan_version_id": str(plan.get("source_chapter_plan_asset_version_id") or ""),
        "plan_content_hash": str(plan.get("source_chapter_plan_content_hash") or ""),
        "style_digest": narrative_hash(style),
        "plan_representation": "LEGACY_TEXT_BEATS_FROZEN_ADAPTATION"
        if legacy_beats
        else "STRUCTURED_SCENE_BEATS",
        "scene_source_digest": narrative_hash(scenes),
        "slots": slots,
        "voices": voices,
        "integration_policy": "ordered-slot-concatenation.v1",
        "authority": "CANDIDATE_REALIZATION_ONLY",
    }
    return {**body, "contract_digest": narrative_hash(body)}


def integrate_realization(
    *, contract: Mapping[str, Any], artifacts: Any, text: str
) -> dict[str, Any]:
    if not isinstance(artifacts, list):
        raise KernelError(
            "REALIZATION_ARTIFACT_INVALID", "Realization requires structured slots"
        )
    expected = list(contract["slots"])
    if not expected:
        if artifacts:
            raise KernelError(
                "REALIZATION_PLAN_UNBOUND",
                "Structured prose needs a frozen Scene Architecture",
            )
        return {}
    if [item.get("slot_id") for item in artifacts if isinstance(item, dict)] != [
        slot["slot_id"] for slot in expected
    ]:
        raise KernelError(
            "REALIZATION_SLOT_COVERAGE_INVALID",
            "Every selected Scene slot must occur once in frozen order",
        )
    pieces = []
    for slot, artifact in zip(expected, artifacts, strict=True):
        if (
            set(artifact) != {"slot_id", "text", "used_fact_ids"}
            or not isinstance(artifact["text"], str)
            or not artifact["text"].strip()
        ):
            raise KernelError(
                "REALIZATION_ARTIFACT_INVALID",
                "Slots require prose and explicit information-use evidence",
            )
        facts = artifact["used_fact_ids"]
        if (
            not isinstance(facts, list)
            or any(not isinstance(ref, str) for ref in facts)
            or len(set(facts)) != len(facts)
        ):
            raise KernelError(
                "REALIZATION_EPISTEMIC_EVIDENCE_INVALID",
                "Slot information use must name unique fact references",
            )
        if not set(facts).issubset(set(slot["accessible_knowledge"])):
            raise KernelError(
                "REALIZATION_EPISTEMIC_SCOPE_VIOLATION",
                "Scene realization used information outside its frozen epistemic scope",
            )
        pieces.append(artifact["text"].strip())
    integrated = "\n\n".join(pieces)
    if integrated != text.strip():
        raise KernelError(
            "REALIZATION_INTEGRATION_DRIFT",
            "Candidate prose must exactly equal its structured slot integration",
        )
    voice_evidence = []
    for voice in contract["voices"]:
        relevant = []
        for slot, artifact in zip(expected, artifacts, strict=True):
            if (
                voice.get("character_id")
                and voice["character_id"] not in slot["character_ids"]
            ):
                continue
            if voice["layer"] == "DIALOGUE" and slot["capability"] != "DIALOGUE":
                continue
            if voice["layer"] == "NARRATOR" and slot["capability"] in {
                "DIALOGUE",
                "INTERIOR",
            }:
                continue
            if voice["layer"] in {"CHARACTER", "POV"} and slot["capability"] not in {
                "DIALOGUE",
                "INTERIOR",
            }:
                continue
            relevant.append(artifact["text"])
        scoped_text = "\n\n".join(relevant)
        missing = [
            marker
            for marker in voice.get("required_markers", [])
            if relevant and marker not in scoped_text
        ]
        forbidden = [
            marker
            for marker in voice.get("forbidden_markers", [])
            if marker in scoped_text
        ]
        voice_evidence.append(
            {
                "layer": voice["layer"],
                "voice_id": voice["voice_id"],
                "asset_version_id": voice["asset_version_id"],
                "missing_required_markers": missing,
                "forbidden_markers_present": forbidden,
                "status": "DRIFT_DETECTED"
                if missing or forbidden
                else "CONTRACT_MATCH"
                if relevant
                else "NOT_APPLICABLE_TO_SELECTED_SLOTS",
                "proof_ceiling": "DECLARED_TEXTUAL_CONSTRAINTS_ONLY",
            }
        )
    if any(evidence["status"] == "DRIFT_DETECTED" for evidence in voice_evidence):
        raise KernelError(
            "REALIZATION_VOICE_DRIFT", "Candidate violates its frozen style contract"
        )
    return {
        "realization_contract": dict(contract),
        "scene_artifacts": artifacts,
        "composition_digest": narrative_hash(
            {"contract": contract["contract_digest"], "artifacts": artifacts}
        ),
        "voice_evidence": voice_evidence,
    }


def reconcile_revision_composition(
    source: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    contract = source.get("realization_contract")
    if not contract:
        if result.get("scene_artifacts"):
            raise KernelError(
                "REALIZATION_PLAN_UNBOUND", "Revision cannot invent a Scene contract"
            )
        return {}
    integrated = integrate_realization(
        contract=contract,
        artifacts=result.get("scene_artifacts"),
        text=str(result.get("text") or ""),
    )
    previous = {item["slot_id"]: item for item in source["scene_artifacts"]}
    integrated["changed_slot_ids"] = [
        item["slot_id"]
        for item in integrated["scene_artifacts"]
        if item != previous[item["slot_id"]]
    ]
    integrated["previous_composition_digest"] = source["composition_digest"]
    integrated["quality_and_actual_reconciliation"] = (
        "REQUIRED_FOR_NEW_CANDIDATE_VERSION"
    )
    return integrated
