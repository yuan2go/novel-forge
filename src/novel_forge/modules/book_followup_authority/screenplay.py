from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.book_authority.editions import require_manifest
from novel_forge.modules.command_kernel.errors import KernelError


SCREENPLAY_STAGES = ("screenplay_generate", "screenplay_review", "screenplay_revision")
SCREENPLAY_DIMENSIONS = ("SOURCE_FIDELITY", "CHARACTER_KNOWLEDGE", "DRAMATIC_ACTION", "DIALOGUE", "PERFORMABILITY")
SOURCE_TYPE = "screenplay_source_contract"
CANDIDATE_TYPE = "screenplay_candidate"
REVIEW_TYPE = "screenplay_review"
ACCEPTED_TYPE = "accepted_screenplay"


def source_contract(*, revision_id: str, manifest: dict[str, Any], selected_unit_ids: list[str],
                    scene_plan: list[dict[str, Any]], policy: dict[str, Any], predecessor_source_id: str = "", update_task_asset_version_id: str = "") -> dict[str, Any]:
    require_manifest(manifest)
    available = {unit["unit_id"]: unit for unit in manifest["units"]}
    if (not revision_id or not selected_unit_ids or len(set(selected_unit_ids)) != len(selected_unit_ids)
        or set(selected_unit_ids) - set(available)):
        raise KernelError("SCREENPLAY_SOURCE_INVALID", "Select explicit stable units from one exact validated edition")
    if (not policy.get("policy_version") or not policy.get("must_preserve")
        or not isinstance(policy.get("allowed_changes"), list) or not policy.get("knowledge_contract")
        or type(policy.get("context_token_budget")) is not int or not 512 <= policy["context_token_budget"] <= 200000
        or type(policy.get("max_revision_rounds")) is not int or not 0 <= policy["max_revision_rounds"] <= 5):
        raise KernelError("SCREENPLAY_POLICY_INVALID", "Adaptation requires preservation, allowed changes, knowledge and bounded execution policies")
    knowledge = policy["knowledge_contract"]
    if (not isinstance(knowledge, dict) or not isinstance(knowledge.get("reader_allowed_fact_ids"), list)
        or not isinstance(knowledge.get("character_known_fact_ids"), dict)):
        raise KernelError("SCREENPLAY_KNOWLEDGE_REQUIRED", "Reader and each character's information access must be explicit")
    if not scene_plan or len(scene_plan) > 100:
        raise KernelError("SCREENPLAY_PLAN_REQUIRED", "A bounded scene/action/dialogue plan is required")
    ids, covered = set(), set()
    for scene in scene_plan:
        if (not all(scene.get(key) for key in ("scene_id", "source_unit_ids", "location", "time", "participants", "dramatic_goal"))
            or scene["scene_id"] in ids or set(scene["source_unit_ids"]) - set(selected_unit_ids)
            or set(scene["participants"]) - set(knowledge["character_known_fact_ids"])
            or not isinstance(scene.get("required_fact_ids"), list)):
            raise KernelError("SCREENPLAY_SCENE_PLAN_INVALID", "Scenes require stable IDs, exact source mapping, participants and dramatic goals")
        ids.add(scene["scene_id"])
        covered.update(scene["source_unit_ids"])
    if covered != set(selected_unit_ids):
        raise KernelError("SCREENPLAY_SOURCE_COVERAGE_INVALID", "Every selected source unit needs an explicit scene mapping")
    result = {"schema_version": "screenplay-source.v2", "target_form": "SCENE_SCREENPLAY",
              "project_id": manifest["project_id"], "workspace_id": manifest["workspace_id"], "book_id": manifest["book_id"],
              "book_run_id": manifest["book_run_id"], "source_revision_id": revision_id,
              "source_manifest_digest": manifest["manifest_digest"], "selected_unit_ids": selected_unit_ids,
              "source_units": [deepcopy(available[key]) for key in selected_unit_ids], "scene_plan": deepcopy(scene_plan),
              "policy": deepcopy(policy), "predecessor_source_id": predecessor_source_id,
              "update_task_asset_version_id": update_task_asset_version_id,
              "novel_canon_mutation_allowed": False, "publication_authorized": False}
    result["source_digest"] = completion_digest(result)
    return result


def require_source(source: Mapping[str, Any]) -> None:
    if (source.get("schema_version") not in {"screenplay-source.v1", "screenplay-source.v2"}
        or source.get("source_digest") != completion_digest({key: value for key, value in source.items() if key != "source_digest"})):
        raise KernelError("SCREENPLAY_SOURCE_DRIFT", "Source identity, range or adaptation policy changed")


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def screenplay_output_schema(stage: str, *, craft: bool = True) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": text}
    if stage == "screenplay_review":
        schema = _object({"schema_version": {"const": "screenplay-review.v1"}, "source_digest": text,
            "candidate_digest": text, "verdict": {"enum": ["APPROVE", "REVISE", "REJECT", "INDETERMINATE"]},
            "reviewed_dimensions": {"type": "array", "items": {"enum": list(SCREENPLAY_DIMENSIONS)}, "uniqueItems": True},
            "findings": {"type": "array", "items": _object({"finding_id": text, "scene_id": text,
                "beat_id": {"type": "string"}, "dimension": {"enum": list(SCREENPLAY_DIMENSIONS)},
                "severity": {"enum": ["MINOR", "MAJOR", "CRITICAL"]}, "description": text, "preservation_requirement": text})},
            "rationale": text})
    else:
        schema = _object({"schema_version": {"const": "scene-screenplay.v1"}, "source_digest": text,
            "scenes": {"type": "array", "minItems": 1, "maxItems": 100, "items": _object({
                "scene_id": text, "source_unit_ids": strings, "location": text, "time": text, "participants": strings,
                "retained_fact_ids": strings, "adaptation_changes": strings,
                "beats": {"type": "array", "minItems": 1, "maxItems": 500, "items": _object({
                    "beat_id": text, "kind": {"enum": ["ACTION", "DIALOGUE"]}, "character_id": {"type": "string"},
                    "text": {"type": "string", "minLength": 1, "maxLength": 10000}, "fact_ids": strings})}})}})
    if craft:
        key = "craft_checks" if stage == "screenplay_review" else "craft_realizations"
        properties = {"use_id": text, "scene_id": text, "beat_ids": {**strings, "uniqueItems": True}, "reason": text}
        if stage == "screenplay_review":
            properties.update(status={"enum": ["ACHIEVED", "FAILED", "UNCERTAIN", "REJECT", "NOT_USED"]},
                              interference={"enum": ["CLEAR", "PRESENT", "UNCERTAIN"]})
        else:
            properties["decision"] = {"enum": ["ADOPT", "OMIT"]}
        schema["properties"][key] = {"type": "array", "maxItems": 100, "items": _object(properties)}
        schema["required"].append(key)
        schema["properties"]["schema_version"] = {"const": "screenplay-review.v2" if stage == "screenplay_review" else "scene-screenplay.v2"}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def validate_candidate(output: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    require_source(source)
    _validate_schema(output, "screenplay_generate", craft=source["schema_version"] == "screenplay-source.v2")
    if output["source_digest"] != source["source_digest"] or [s["scene_id"] for s in output["scenes"]] != [s["scene_id"] for s in source["scene_plan"]]:
        raise KernelError("SCREENPLAY_PLAN_DRIFT", "The screenplay must implement the frozen scene plan and source")
    knowledge = source["policy"]["knowledge_contract"]
    for scene, plan in zip(output["scenes"], source["scene_plan"], strict=True):
        if (scene["source_unit_ids"] != plan["source_unit_ids"] or scene["participants"] != plan["participants"]
            or scene["location"] != plan["location"] or scene["time"] != plan["time"]
            or set(plan["required_fact_ids"]) - set(scene["retained_fact_ids"])
            or set(scene["adaptation_changes"]) - set(source["policy"]["allowed_changes"])):
            raise KernelError("SCREENPLAY_FIDELITY_CONTRACT_INVALID", "Source mapping, cast and required facts cannot change outside approved policy")
        scene_knowledge = source.get("accepted_source_evidence", {}).get("scenes", {}).get(scene["scene_id"], knowledge)
        ids = set()
        for beat in scene["beats"]:
            if beat["beat_id"] in ids:
                raise KernelError("SCREENPLAY_BEAT_IDENTITY_INVALID", "Beat IDs are stable within a scene")
            ids.add(beat["beat_id"])
            if beat["kind"] == "DIALOGUE":
                if beat["character_id"] not in scene["participants"]:
                    raise KernelError("SCREENPLAY_SPEAKER_INVALID", "Dialogue must belong to a participant in the frozen scene")
                allowed = scene_knowledge["character_known_fact_ids"][beat["character_id"]]
            else:
                if beat["character_id"]:
                    raise KernelError("SCREENPLAY_ACTION_SPEAKER_INVALID", "An action beat has no dialogue speaker")
                allowed = scene_knowledge["reader_allowed_fact_ids"]
            if set(beat["fact_ids"]) - set(allowed):
                raise KernelError("SCREENPLAY_KNOWLEDGE_VIOLATION", "A beat declares information unavailable to its character or reader")
    if source["schema_version"] == "screenplay-source.v2":
        from .screenplay_craft import validate_realizations
        validate_realizations(output, source)
    result = deepcopy(output)
    result["candidate_digest"] = completion_digest(output)
    if "character_display" in source:
        result["character_display"] = deepcopy(source["character_display"])
    return result


def validate_review(output: dict[str, Any], source: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    require_source(source)
    _validate_schema(output, "screenplay_review", craft=source["schema_version"] == "screenplay-source.v2")
    if (output["source_digest"] != source["source_digest"] or output["candidate_digest"] != candidate["candidate_digest"]
        or set(output["reviewed_dimensions"]) != set(SCREENPLAY_DIMENSIONS)):
        raise KernelError("SCREENPLAY_REVIEW_SCOPE_INVALID", "Review must cover this exact source, candidate and every required dimension")
    scenes = {s["scene_id"]: s for s in candidate["scenes"]}
    ids = set()
    for finding in output["findings"]:
        if (finding["finding_id"] in ids or finding["scene_id"] not in scenes
            or finding["beat_id"] and finding["beat_id"] not in {beat["beat_id"] for beat in scenes[finding["scene_id"]]["beats"]}):
            raise KernelError("SCREENPLAY_FINDING_LOCATION_INVALID", "Review findings require unique identities and real scene/beat locations")
        ids.add(finding["finding_id"])
    if output["verdict"] == "APPROVE" and output["findings"]:
        raise KernelError("SCREENPLAY_REVIEW_CONTRADICTORY", "Unresolved findings cannot approve a screenplay")
    if source["schema_version"] == "screenplay-source.v2":
        from .screenplay_craft import validate_craft_checks
        validate_craft_checks(output, source, candidate)
    return deepcopy(output)


def _validate_schema(output: dict[str, Any], stage: str, *, craft: bool) -> None:
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    try:
        validate_chapter_provider_output_against_schema(stage, screenplay_output_schema(stage, craft=craft), output)
    except KernelError as exc:
        raise KernelError("SCREENPLAY_OUTPUT_CONTRACT_INVALID", str(exc)) from exc


def screenplay_text(candidate: dict[str, Any]) -> str:
    parts = []
    for scene in candidate["scenes"]:
        parts.append(f"场景 {scene['scene_id']} · {scene['location']} · {scene['time']}")
        names = candidate.get("character_display", {}).get("scenes", {}).get(scene["scene_id"], {})
        for beat in scene["beats"]:
            parts.append(f"{names.get(beat['character_id'], beat['character_id'])}：{beat['text']}" if beat["kind"] == "DIALOGUE" else f"（{beat['text']}）")
        parts.append("")
    return "\n\n".join(parts).rstrip() + "\n"
