from copy import deepcopy
from typing import Any, Mapping


def disclosed_fact_projection(entry: Mapping[str, Any]) -> dict[str, Any]:
    projected = deepcopy(dict(entry))
    state = projected.get("state") or {}
    if (state.get("fact_origin") or {}).get("kind") in {
        "GOVERNED_BACKGROUND",
        "GOVERNED_PREPARATION",
    }:
        projected["state"] = {
            key: value
            for key, value in state.items()
            if key
            not in {
                "fact_origin",
                "world_transition",
                "causal_batch",
                "causality",
                "approval_resolution",
                "preparation_schedule",
                "dependencies",
                "expected_payoff",
                "causal_requirement",
                "retirement_evidence",
            }
        }
    return projected
