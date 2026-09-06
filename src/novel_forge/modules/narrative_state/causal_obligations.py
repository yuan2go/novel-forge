from __future__ import annotations

import json
from typing import Any, Mapping, TYPE_CHECKING

from novel_forge.modules.command_kernel.errors import KernelError

if TYPE_CHECKING:
    from novel_forge.modules.worldbuilding.dynamics import CausalRequirement


def causal_obligation_requirement(payload: Mapping[str, Any]) -> CausalRequirement:
    from novel_forge.modules.worldbuilding.dynamics import CausalRequirement

    envelope = payload.get("causal_requirement")
    try:
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"payload_json"}
            or not isinstance(envelope["payload_json"], str)
        ):
            raise ValueError("causal predicate is missing")
        predicate = CausalRequirement.from_mapping(json.loads(envelope["payload_json"]))
        if (
            not isinstance(payload.get("causal_plan_asset_version_id"), str)
            or not payload["causal_plan_asset_version_id"]
        ):
            raise ValueError("causal plan origin is missing")
        if predicate.state_kind.value in {
            "reader_knowledge",
            "reader_promise",
            "narrative_obligation",
            "disclosure_event",
        }:
            raise ValueError(
                "reader evidence cannot discharge a physical causal condition"
            )
        return predicate
    except (ValueError, TypeError) as exc:
        raise KernelError("CAUSAL_OBLIGATION_CONTRACT_INVALID", str(exc)) from exc


def validate_causal_obligation_transition(
    *,
    payload: Mapping[str, Any],
    old: Mapping[str, Any],
    current: Mapping[Any, Mapping[str, Any]],
) -> None:
    if payload.get("obligation_type") != "CAUSAL_DEBT":
        return
    from novel_forge.modules.worldbuilding.dynamics import evaluate_requirement

    requirement = causal_obligation_requirement(payload)
    if old and any(
        payload.get(key) != old.get(key)
        for key in ("causal_requirement", "causal_plan_asset_version_id")
    ):
        raise KernelError(
            "CAUSAL_OBLIGATION_ORIGIN_IMMUTABLE",
            "causal debt cannot change its origin or conditions during repayment",
        )
    if payload.get("status") != "FULFILLED":
        return
    index = {
        (kind.value, key): entry
        for kind, entries in current.items()
        for key, entry in entries.items()
    }
    receipt = evaluate_requirement(requirement, index)
    payoff = payload.get("payoff_evidence") or {}
    source = index.get((requirement.state_kind.value, requirement.entity_key), {})
    draft_version = source.get("provenance", {}).get("accepted_draft_asset_version_id")
    if (
        not receipt["satisfied"]
        or not receipt["source_event_id"]
        or payoff.get("event_id") != receipt["source_event_id"]
        or not draft_version
        or payoff.get("asset_version_id") != draft_version
    ):
        raise KernelError(
            "CAUSAL_OBLIGATION_NOT_DISCHARGED",
            "causal debt requires its condition and exact accepted payoff event; a plan cannot close it",
        )
