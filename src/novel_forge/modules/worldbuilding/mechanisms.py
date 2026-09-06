from dataclasses import dataclass
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

from .dynamics import evaluate_requirement, require_contract_fields


@dataclass(frozen=True, slots=True)
class WorldMechanism:
    effect: str
    entity_keys: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorldMechanism":
        require_contract_fields(
            value, required={"contract_version", "effect", "entity_keys"}
        )
        if (
            value["contract_version"] != "world-mechanism.v1"
            or value["effect"]
            not in {"REVIVAL", "INSTANT_TRAVEL", "MULTIPRESENCE", "POWER_TRANSITION"}
            or not isinstance(value["entity_keys"], list)
            or not value["entity_keys"]
            or any(not isinstance(key, str) or not key for key in value["entity_keys"])
        ):
            raise KernelError(
                "WORLD_MECHANISM_CONTRACT_INVALID",
                "mechanisms require a modeled effect and exact entity scope",
            )
        return cls(value["effect"], tuple(value["entity_keys"]))


def require_world_mechanism(
    transition: Any, reality: Mapping[str, Any], state: Mapping[Any, Any]
) -> str:
    from .foundation import WorldRule

    reference = transition.changes.get("world_mechanism")
    if reference is None:
        return ""
    require_contract_fields(
        reference, required={"rule_id", "asset_version_id", "content_hash"}
    )
    selected = [
        source
        for source in reality.get("world_rule_constraints", [])
        if source["asset_version_id"] == reference["asset_version_id"]
        and source["content_hash"] == reference["content_hash"]
        and source["rule"]["rule_id"] == reference["rule_id"]
    ]
    if (
        reality.get("world_dynamics_contract") != "world-dynamics.v2"
        or len(selected) != 1
    ):
        raise KernelError(
            "WORLD_MECHANISM_UNAPPROVED",
            "model flags cannot substitute for an approved exact rule",
        )
    rule = WorldRule.from_mapping(selected[0]["rule"])
    if (
        rule.enforcement != "MECHANISM"
        or rule.mechanism is None
        or transition.state_kind.value not in rule.applicability
        or transition.entity_key not in rule.mechanism.entity_keys
    ):
        raise KernelError(
            "WORLD_MECHANISM_UNAPPROVED",
            "approved mechanism does not apply to this transition",
        )
    if not evaluate_requirement(rule.predicate, state)["satisfied"]:
        raise KernelError(
            "WORLD_MECHANISM_PRECONDITION_FAILED",
            "genre mechanisms cannot bypass their own causal prerequisites",
        )
    return rule.mechanism.effect
