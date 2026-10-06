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
    plan: Mapping[str, Any],
    style: Mapping[str, Any],
    *,
    core_policy: str = "EXPLICIT_SKELETON_V1",
    information_policy: str = "ENTRY_ONLY_V1",
) -> dict[str, Any]:
    if core_policy not in {"EXPLICIT_SKELETON_V1", "scene-core-slots.v1"}:
        raise KernelError(
            "REALIZATION_CORE_POLICY_INVALID", "Unknown frozen core slot interpretation"
        )
    if information_policy not in {"ENTRY_ONLY_V1", "scene-information-flow.v1"}:
        raise KernelError(
            "REALIZATION_INFORMATION_POLICY_INVALID",
            "Unknown frozen information interpretation",
        )
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
                not in {"chapter-mission-scene.v2", "chapter-mission-scene.v3"}
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
            or (
                core_policy == "EXPLICIT_SKELETON_V1" and "SKELETON" not in capabilities
            )
        ):
            raise KernelError(
                "REALIZATION_CAPABILITY_INVALID",
                "Scene capability selection must be unique, typed and include its narrative skeleton",
            )
        if core_policy == "scene-core-slots.v1":
            capabilities = ["SKELETON", *(c for c in capabilities if c != "SKELETON")]
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
                if information_policy == "scene-information-flow.v1":
                    accessible |= set(scene.get("information_gain", []))
                    chapter = int(plan["chapter"])
                    withheld = {
                        d["fact_id"]
                        for d in plan.get("disclosures", [])
                        if d["mode"] == "WITHHOLD"
                        and d["audience"] in {actor or "READER", "ALL"}
                    }
                    accessible -= withheld
                    if actor:
                        granted = set(known.get(actor, set()))
                        granted |= {
                            b["fact_id"]
                            for b in plan.get("knowledge_boundaries", [])
                            if b["layer"] == "CHARACTER_KNOWLEDGE"
                            and b["subject_id"] == actor
                            and b["status"] == "KNOWN"
                            and b["available_from_chapter"] <= chapter
                        }
                        granted |= {
                            d["fact_id"]
                            for d in plan.get("disclosures", [])
                            if d["audience"] == actor
                            and d["mode"] == "CONFIRM"
                            and d["earliest_chapter"] <= chapter
                        }
                        accessible &= granted
                if actor:
                    if information_policy == "ENTRY_ONLY_V1":
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
    if core_policy == "scene-core-slots.v1":
        body["core_projection"] = {
            "contract_version": core_policy,
            "source_capabilities": {
                s["scene_id"]: s.get("realization_capabilities", ["SKELETON"])
                for s in scenes
            },
            "intrinsic_capability": "SKELETON",
            "authority": "EXECUTION_PROJECTION_ONLY",
        }
    if information_policy == "scene-information-flow.v1":
        body["information_flow"] = {
            "contract_version": information_policy,
            "scene_scope": "ENTRY_PLUS_DECLARED_SCENE_GAIN",
            "character_scope": "EXPLICIT_KNOWN_OR_CONFIRMED",
            "presentation_requirement": "Present the planned observation or disclosure before using newly gained information. Future Scene gains remain unavailable.",
            "authority": "EXECUTION_PROJECTION_ONLY",
        }
    policies = [
        fact["value"]
        for policy in style.get("policies", [])
        for fact in policy.get("structured_facts", [])
        if isinstance(fact, dict) and fact.get("key") == "realization_policy"
    ]
    if policies:
        if len(policies) != 1 or policies[0] not in [
            {
                "contract_version": version,
                "mode": "WHOLE_CHAPTER_WITH_TARGETED_SPECIALISMS",
            }
            for version in ("scene-craft-tasks.v1", "scene-craft-tasks.v2")
        ]:
            raise KernelError(
                "REALIZATION_CRAFT_POLICY_INVALID",
                "Creative realization requires one supported frozen policy",
            )
        body["contract_version"] = "scene-realization-composition.v2"
        body["craft_tasks"] = _scene_craft_tasks(
            scenes, slots, voices, version=policies[0]["contract_version"], plan=plan
        )
        body["composition_method"] = (
            "Write and edit the chapter as one narrative; slots serialize the final prose and are not a proof of integration."
        )
    if "craft_strategy" in plan:
        from .craft_execution import bind_craft_realization

        body = bind_craft_realization(
            body, plan["craft_strategy"], scenes=scenes, plan=plan
        )
    return {**body, "contract_digest": narrative_hash(body)}


def realization_separators(
    artifacts: list[dict[str, Any]], separators: Any = None
) -> list[str]:
    count = max(0, len(artifacts) - 1)
    if separators is None:
        return ["\n\n"] * count
    if (
        not isinstance(separators, list)
        or len(separators) != count
        or any(
            not isinstance(value, str) or (value != "" and not value.isspace())
            for value in separators
        )
    ):
        raise KernelError(
            "REALIZATION_SEPARATOR_INVALID",
            "explicit Scene separators must be whitespace in frozen slot order",
        )
    return list(separators)


def serialize_realization(
    artifacts: list[dict[str, Any]], separators: Any = None
) -> str:
    joins = realization_separators(artifacts, separators)
    return "".join(
        (joins[index - 1] if index else "") + item["text"]
        for index, item in enumerate(artifacts)
    )


def prose_from_output(result: Mapping[str, Any], *, separators: Any = None) -> str:
    artifacts = result.get("scene_artifacts")
    if isinstance(artifacts, list) and artifacts:
        text = serialize_realization(artifacts, separators)
        supplied = result.get("text")
        if supplied is not None and supplied != text:
            raise KernelError(
                "REALIZATION_INTEGRATION_DRIFT",
                "legacy candidate text differs from its frozen Scene slots",
            )
        return text
    return str(result.get("text") or "")


def derive_targeted_revision_slots(
    source: Mapping[str, Any],
    edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifacts = source.get("scene_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise KernelError(
            "REVISION_TARGETED_SLOT_REQUIRED",
            "targeted repair needs frozen Scene slots",
        )
    joins = realization_separators(artifacts, source.get("scene_separators"))
    ranges: list[tuple[int, int]] = []
    offset = 0
    for index, artifact in enumerate(artifacts):
        if index:
            offset += len(joins[index - 1])
        end = offset + len(artifact["text"])
        ranges.append((offset, end))
        offset = end
    copied = [dict(item) for item in artifacts]
    by_slot: dict[int, list[dict[str, Any]]] = {}
    for edit in edits:
        start, end = edit["start"], edit["end"]
        index = next(
            (i for i, (low, high) in enumerate(ranges) if low <= start < end <= high),
            None,
        )
        if index is None:
            raise KernelError(
                "REVISION_TARGETED_SLOT_BOUNDARY",
                "targeted edit crosses a frozen Slot or separator",
            )
        by_slot.setdefault(index, []).append(edit)
    for index, slot_edits in by_slot.items():
        low, _ = ranges[index]
        old = artifacts[index]["text"]
        for edit in reversed(slot_edits):
            start, end = edit["start"] - low, edit["end"] - low
            old = old[:start] + edit["replacement"] + old[end:]
        copied[index]["text"] = old
    return copied


def integrate_realization(
    *, contract: Mapping[str, Any], artifacts: Any, text: str, separators: Any = None
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
    integrated = serialize_realization(artifacts, separators)
    if integrated != text:
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
        **(
            {"scene_separators": realization_separators(artifacts, separators)}
            if separators is not None
            else {}
        ),
        "composition_digest": narrative_hash(
            {
                "contract": contract["contract_digest"],
                "artifacts": artifacts,
                **({"scene_separators": separators} if separators is not None else {}),
            }
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
        text=prose_from_output(result, separators=source.get("scene_separators")),
        separators=source.get("scene_separators"),
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


_CRAFT_OBJECTIVES = {
    "SKELETON": (
        "Render the scene's consequential choice",
        [
            "motive before choice",
            "specific cost and changed options",
            "cause before consequence",
        ],
    ),
    "DIALOGUE": (
        "Dramatize one actor's attempt to influence another",
        [
            "what the actor wants from the exchange",
            "what the actor avoids saying",
            "only this actor's available knowledge and established voice",
        ],
    ),
    "ACTION": (
        "Make action and resistance spatially legible",
        [
            "starting positions and available resources",
            "action, opposing response, resulting cost",
            "no unexplained movement or capability",
        ],
    ),
    "INTERIOR": (
        "Show the viewpoint's competing interpretations",
        [
            "perception versus belief",
            "choice between values under pressure",
            "thought changes an action rather than repeating narration",
        ],
    ),
    "DESCRIPTION": (
        "Select details that affect this scene's choices",
        [
            "viewpoint-directed sensory detail",
            "relevant obstacle or affordance",
            "avoid unneeded exposition",
        ],
    ),
    "TRANSITION": (
        "Carry the previous consequence into the next scene",
        [
            "consistent elapsed time and location",
            "preserve emotional residue",
            "do not restage completed events",
        ],
    ),
    "INTEGRATION": (
        "Edit scene junctions as a continuous chapter",
        [
            "remove duplicated explanation",
            "preserve voice and information boundaries",
            "track the emotional and causal progression",
        ],
    ),
}


def _legacy_scene_craft_tasks(scenes, slots, voices):
    by_scene = {scene["scene_id"]: scene for scene in scenes}
    tasks = []
    for slot in slots:
        goal, checks = _CRAFT_OBJECTIVES[slot["capability"]]
        scene = by_scene[slot["scene_id"]]
        tasks.append(
            {
                "slot_id": slot["slot_id"],
                "specialism": slot["capability"],
                "objective": goal,
                "scene_goal": scene.get("goal", ""),
                "beat_ids": slot["beat_ids"],
                "actor_ids": slot["character_ids"],
                "available_fact_ids": slot["accessible_knowledge"],
                "craft_checks": checks,
                "voice_sources": [
                    {
                        key: voice[key]
                        for key in (
                            "asset_version_id",
                            "voice_id",
                            "layer",
                            "character_id",
                            "guidance",
                        )
                        if key in voice
                    }
                    for voice in voices
                    if not voice.get("character_id")
                    or voice["character_id"] in slot["character_ids"]
                ],
                "output_use": "A passage within the continuous final chapter, subject to grounded review; no state mutation",
            }
        )
    return {
        "contract_version": "scene-craft-tasks.v1",
        "tasks": tasks,
        "chapter_edit": [
            "Assess scene junctions together",
            "Retain causal and epistemic sequence",
            "Remove redundant recaps",
            "Preserve unresolved uncertainty",
        ],
        "semantic_proof": "NOT_CLAIMED_BY_SLOT_COVERAGE_OR_DECLARED_FACT_IDS",
    }


_APPLICABLE_CRAFT_OBJECTIVES = {
    "SKELETON": (
        "Render the frozen scene's events in causal order",
        [
            "follow the scene's function",
            "show motive and consequences when a planned choice calls for them",
            "cause before consequence",
        ],
    ),
    "DIALOGUE": (
        "Let each speaker participate in the actual exchange",
        [
            "follow the speaker's purpose and established voice",
            "use persuasion or subtext only when the exchange calls for it",
            "only this actor's available knowledge",
        ],
    ),
    "ACTION": (
        "Make the planned action spatially legible",
        [
            "starting positions and available resources",
            "show resistance and cost when supported by the frozen scene",
            "no unexplained movement or capability",
        ],
    ),
    "INTERIOR": (
        "Render the viewpoint's relevant perception and thought",
        [
            "distinguish perception from belief",
            "use pressured value choices only when relevant",
            "avoid repeating narration without a reader purpose",
        ],
    ),
    "DESCRIPTION": (
        "Select details that serve the scene's function",
        [
            "viewpoint-directed sensory detail",
            "relevant setting, obstacle or affordance",
            "avoid unneeded exposition",
        ],
    ),
    "TRANSITION": (
        "Carry the actual scene state into the next scene",
        [
            "consistent elapsed time and location",
            "retain relevant emotional residue",
            "do not restage completed events",
        ],
    ),
    "INTEGRATION": _CRAFT_OBJECTIVES["INTEGRATION"],
}


def _scene_craft_tasks(
    scenes, slots, voices, *, version="scene-craft-tasks.v2", plan=None
):
    if version == "scene-craft-tasks.v1":
        return _legacy_scene_craft_tasks(scenes, slots, voices)
    if version != "scene-craft-tasks.v2":
        raise KernelError(
            "REALIZATION_CRAFT_POLICY_INVALID", "Unknown frozen Scene Craft method"
        )
    result = _legacy_scene_craft_tasks(scenes, slots, voices)
    result["contract_version"] = version
    plan = plan or {}
    result["applicability"] = {
        "classification": "CONFIGURABLE_POLICY",
        "sources": {
            key: plan[key]
            for key in (
                "objective",
                "chapter_intent",
                "reader_experience",
                "required_arc_contributions",
            )
            if key in plan
        },
        "instruction": (
            "Apply cost, pressured choice, growth, reversal, reward and hook only when the frozen chapter function, "
            "Scene, actor, author intent, Arc or due accepted obligation calls for them. Use the delivered accepted "
            "Context for obligations. Do not add a technique or penalize its absence merely to fill a template. "
            "An explicit author requirement, accepted fact or due obligation remains binding and cannot be declared inapplicable."
        ),
    }
    for task in result["tasks"]:
        goal, checks = _APPLICABLE_CRAFT_OBJECTIVES[task["specialism"]]
        task["objective"], task["craft_checks"] = goal, list(checks)
    return result
