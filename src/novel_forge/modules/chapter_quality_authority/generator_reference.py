from __future__ import annotations

from typing import Any


GENERATOR_REFERENCE_PROTOCOL = "native-generator-quality.v1"
DIRECT_GENERATOR_DIMENSIONS = {
    **{f"world_candidates.actor_{index}": ("goal_consistency", "epistemic_isolation", "commitment_continuity", "action_causality") for index in range(3)},
    "memo": ("plan_fidelity", "epistemic_grounding", "execution_usefulness"),
    "canon_extraction": ("prose_grounding", "state_delta_completeness", "epistemic_isolation"),
}


def generator_reference_contract(task_type: str, producer_contract_hash: str) -> dict[str, Any]:
    if not task_type or not producer_contract_hash.startswith("sha256:"):
        raise ValueError("GENERATOR_REFERENCE_PRODUCER_REQUIRED")
    return {
        "protocol_version": GENERATOR_REFERENCE_PROTOCOL,
        "evaluation_version": f"{GENERATOR_REFERENCE_PROTOCOL}:{task_type}:{producer_contract_hash}",
        "task_type": task_type,
        "producer_contract_hash": producer_contract_hash,
        "dimensions": list(DIRECT_GENERATOR_DIMENSIONS.get(task_type, ())),
        "score_basis": "MINIMUM_ADJUDICATED_LOWER_ENDPOINT",
        "maximum_score_interval_width": 20,
        "independent_humans_required": 2,
        "independent_adjudicator_required": True,
        "sample_promotion_allowed": False,
    }
