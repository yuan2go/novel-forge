from copy import deepcopy
from dataclasses import asdict
import json
from typing import Any, Mapping

from novel_forge.modules.narrative_state.causal_obligations import (
    causal_obligation_requirement,
)
from novel_forge.modules.worldbuilding.dynamics import (
    CausalRequirement,
    evaluate_requirement,
    state_index,
)


def preparation_observations(binding: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not binding:
        return []
    plan = binding["action"]["world_plan"]
    reality = binding["frozen_source"]["reality"]
    prior = {
        entry["state"]["obligation_id"]: entry["state"]
        for entry in reality["current_state"].get("narrative_obligation", [])
    }
    index = state_index(
        {
            **reality,
            "current_state": {
                key: value
                for key, value in reality["current_state"].items()
                if key != "narrative_obligation"
            },
        }
    )
    result = []
    for debt in plan["causal_debts"]:
        if debt["debt_id"] in prior or debt["status"] != "PREPARATION_REQUIRED":
            continue
        requirement = CausalRequirement.from_mapping(
            {
                key: debt["preparation"][key]
                for key in CausalRequirement.__dataclass_fields__
                if key in debt["preparation"]
            }
        )
        chapter = plan["chapter_number"]
        result.append(
            {
                "obligation_id": debt["debt_id"],
                "obligation_type": "CAUSAL_DEBT",
                "status": "OPEN",
                "priority": "MEDIUM",
                "introduced_at": {"chapter": chapter},
                "target_window": {
                    "status": "SCHEDULED",
                    "from_chapter": chapter,
                    "to_chapter": chapter
                    + plan["policy"]["planning_window_chapters"]
                    - 1,
                },
                "causal_requirement": {
                    "payload_json": json.dumps(
                        asdict(requirement), sort_keys=True, separators=(",", ":")
                    )
                },
                "causal_plan_asset_version_id": binding["asset_version_id"],
                "dependencies": list(
                    dict.fromkeys(
                        ref
                        for step in plan["preparation_schedule"]
                        for ref in step["depends_on"]
                    )
                ),
                "preparation_schedule": deepcopy(plan["preparation_schedule"]),
                "selected_candidate_id": plan["selected_candidate_id"],
                "selected_path_id": plan["selected_path_id"],
                "intent_version_id": plan["intent_version_id"],
                "reader_visibility": "HIDDEN",
                "visibility": "HIDDEN",
                "payoff_evidence": {},
                "expected_payoff": asdict(requirement),
                "current_development": "Selected preparation remains unaccepted at the frozen frontier.",
                "fact_origin": {
                    "kind": "GOVERNED_PREPARATION",
                    "contract_version": "world-preparation-origin.v1",
                    "action_asset_version_id": binding["asset_version_id"],
                    "action_content_hash": binding["content_hash"],
                },
                "approval_requirement": "NONE",
                "coverage": "GOVERNED_PLANNING_COMMITMENT",
                "confidence": 1.0,
            }
        )
    for old in prior.values():
        if old.get("obligation_type") != "CAUSAL_DEBT" or old.get("status") in {
            "FULFILLED",
            "CANCELLED",
        }:
            continue
        if (old.get("fact_origin") or {}).get("kind") != "GOVERNED_PREPARATION":
            continue
        if old["intent_version_id"] != plan["intent_version_id"]:
            result.append(
                {
                    **deepcopy(old),
                    "from_status": old["status"],
                    "status": "CANCELLED",
                    "retirement_evidence": {
                        "reason": "APPROVED_INTENT_REPLACED",
                        "intent_version_id": plan["intent_version_id"],
                        "action_asset_version_id": binding["asset_version_id"],
                    },
                    "current_development": "Approved future Intent replaced the preparation target; accepted history remains immutable.",
                }
            )
            continue
        requirement = causal_obligation_requirement(old)
        receipt = evaluate_requirement(requirement, index)
        entry = index.get((requirement.state_kind.value, requirement.entity_key), {})
        draft_id = entry.get("provenance", {}).get("accepted_draft_asset_version_id")
        if receipt["satisfied"] and receipt["source_event_id"] and draft_id:
            result.append(
                {
                    **deepcopy(old),
                    "from_status": old["status"],
                    "status": "FULFILLED",
                    "current_development": "The frozen accepted Reality supplies the exact prerequisite evidence.",
                    "payoff_evidence": {
                        "event_id": receipt["source_event_id"],
                        "asset_version_id": draft_id,
                        "evidence_mode": "ACCEPTED_REALITY_PREDICATE",
                    },
                }
            )
        elif plan["chapter_number"] > old["target_window"]["to_chapter"]:
            result.append(
                {
                    **deepcopy(old),
                    "from_status": old["status"],
                    "status": "CANCELLED",
                    "retirement_evidence": {
                        "reason": "PREPARATION_WINDOW_EXPIRED",
                        "action_asset_version_id": binding["asset_version_id"],
                        "accepted_through_chapter": reality["chapter_number"],
                    },
                    "current_development": "No accepted prerequisite satisfied this frozen window; a future target requires a new preparation commitment.",
                }
            )
    return result
