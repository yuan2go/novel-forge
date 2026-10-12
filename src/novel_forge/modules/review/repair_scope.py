from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

DIAGNOSIS_VERSION = "prose-root-cause.v1"
ROOT_CAUSES = {"LANGUAGE", "SCENE_ORGANIZATION", "CHAPTER_STRUCTURE", "CHARACTER_TRAJECTORY", "UPPER_PLOT", "UNCERTAIN"}
REPAIR_SCOPES = {"LOCAL_PROSE", "SCENE_REVISION", "CHAPTER_REVISION", "FUTURE_REPLAN", "INVESTIGATE"}


def repair_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    properties = {"root_cause": {"enum": sorted(ROOT_CAUSES)}, "problem_owner": {"enum": ["PROSE", "PLAN", "UNKNOWN"]},
                  "repair_scope": {"enum": sorted(REPAIR_SCOPES)}, "revision_goal": text,
                  "preserve": {"type": "array", "items": text, "minItems": 1},
                  "resolution_criteria": {"type": "array", "items": text, "minItems": 1}}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def validate_repair(repair: Mapping[str, Any]) -> None:
    root, owner, scope = (repair.get(key) for key in ("root_cause", "problem_owner", "repair_scope"))
    if (any(not isinstance(value, str) for value in (root, owner, scope))
            or root not in ROOT_CAUSES or owner not in {"PROSE", "PLAN", "UNKNOWN"} or scope not in REPAIR_SCOPES
            or owner == "PLAN" and scope not in {"FUTURE_REPLAN", "INVESTIGATE"}
            or (owner == "UNKNOWN" or root == "UNCERTAIN") and scope != "INVESTIGATE"
            or root == "UPPER_PLOT" and scope not in {"FUTURE_REPLAN", "INVESTIGATE"}
            or owner == "PROSE" and scope == "FUTURE_REPLAN"):
        raise KernelError("PROSE_REPAIR_SCOPE_INVALID", "A prose repair cannot change frozen plan commitments")


def finding_repair_route(finding: Mapping[str, Any]) -> dict[str, Any]:
    repairs = [row["repair"] for row in finding.get("members", []) if row.get("judgment") == "ISSUE" and "repair" in row]
    for repair in repairs:
        validate_repair(repair)
    scopes = {row["repair_scope"] for row in repairs}
    if finding.get("status") == "CONFLICT_REQUIRES_REVIEW" or "INVESTIGATE" in scopes:
        route = "INVESTIGATE"
    elif "FUTURE_REPLAN" in scopes:
        route = "FUTURE_REPLAN"
    else:
        route = max(scopes, key=lambda scope: ["LOCAL_PROSE", "SCENE_REVISION", "CHAPTER_REVISION"].index(scope)) if scopes else "UNCLASSIFIED"
    return {"contract_version": DIAGNOSIS_VERSION, "repair_scope": route,
            "consumer": "NATIVE_PLAN_CHANGE_OR_BOOK_REPLAN" if route == "FUTURE_REPLAN" else
                        "EXACT_CANDIDATE_REVISION" if route in {"LOCAL_PROSE", "SCENE_REVISION", "CHAPTER_REVISION"} else "AUTHOR_DIAGNOSIS",
            "authorization": "PROPOSAL_ONLY"}
