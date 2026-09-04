from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping


CONTEXT_POLICY_COMPILER_VERSION = "effective-context-policy-compiler-v1"
SUPPORTED_POLICY_VERSIONS = frozenset(
    {
        "context-policy-v1",
        "production-stage-profile-v1",
        "context-profile-v1",
        "caller-context-limit-v1",
        "provider-context-route-v1",
        "capability-pack-context-policy-v1",
        "provider-route-context-capability-v1",
        "planning-context-contract-v1",
    }
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _string_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _limits(values: Mapping[str, int] | Iterable[tuple[str, int]]) -> dict[str, int]:
    items = values.items() if isinstance(values, Mapping) else values
    result: dict[str, int] = {}
    for key, value in items:
        normalized = str(key).strip()
        amount = int(value)
        if not normalized or amount <= 0:
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: budget limits must be positive")
        result[normalized] = amount
    return dict(sorted(result.items()))


@dataclass(frozen=True, slots=True)
class PolicyIdentity:
    policy_id: str
    version: str
    content_hash: str
    snapshot_ref: str

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.policy_id,
                self.version,
                self.content_hash,
                self.snapshot_ref,
            )
        ):
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: policy identity is incomplete")
        digest = self.content_hash.removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: policy hash is not SHA-256")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextBudgetLimits:
    total: int
    sections: Mapping[str, int] = field(default_factory=dict)
    buckets: Mapping[str, int] = field(default_factory=dict)
    classes: Mapping[str, int] = field(default_factory=dict)
    required_reservation: int = 0

    def __post_init__(self) -> None:
        if self.total <= 0 or self.required_reservation < 0:
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: Context budget is invalid")
        object.__setattr__(self, "sections", MappingProxyType(_limits(self.sections)))
        object.__setattr__(self, "buckets", MappingProxyType(_limits(self.buckets)))
        object.__setattr__(self, "classes", MappingProxyType(_limits(self.classes)))
        if self.required_reservation > self.total:
            raise ValueError(
                "CONTEXT_POLICY_UNRESOLVED: required reservation exceeds total"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "sections": dict(self.sections),
            "buckets": dict(self.buckets),
            "classes": dict(self.classes),
            "required_reservation": self.required_reservation,
        }


@dataclass(frozen=True, slots=True)
class ContextPolicySnapshot:
    identity: PolicyIdentity
    allowed_logical_kinds: tuple[str, ...] = ()
    allowed_physical_types: tuple[str, ...] = ()
    denied_logical_kinds: tuple[str, ...] = ()
    denied_physical_types: tuple[str, ...] = ()
    required_logical_kinds: tuple[str, ...] = ()
    limits: ContextBudgetLimits = field(
        default_factory=lambda: ContextBudgetLimits(total=1)
    )
    permitted_truncation_strategies: tuple[str, ...] = (
        "structured_elements-v1",
    )
    permitted_source_modes: tuple[str, ...] = (
        "generation",
        "structure_only",
    )
    source_risk_threshold: int = 0
    maximum_raw_source_ratio: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "allowed_logical_kinds",
            "allowed_physical_types",
            "denied_logical_kinds",
            "denied_physical_types",
            "required_logical_kinds",
            "permitted_truncation_strategies",
            "permitted_source_modes",
        ):
            object.__setattr__(self, name, _string_tuple(getattr(self, name)))
        if self.source_risk_threshold < 0 or not 0 <= self.maximum_raw_source_ratio <= 1:
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: source limits are invalid")
        if not self.allowed_logical_kinds and not self.allowed_physical_types:
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: policy allowlist is empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "allowed_logical_kinds": list(self.allowed_logical_kinds),
            "allowed_physical_types": list(self.allowed_physical_types),
            "denied_logical_kinds": list(self.denied_logical_kinds),
            "denied_physical_types": list(self.denied_physical_types),
            "required_logical_kinds": list(self.required_logical_kinds),
            "limits": self.limits.to_dict(),
            "permitted_truncation_strategies": list(
                self.permitted_truncation_strategies
            ),
            "permitted_source_modes": list(self.permitted_source_modes),
            "source_risk_threshold": self.source_risk_threshold,
            "maximum_raw_source_ratio": self.maximum_raw_source_ratio,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextPolicySnapshot":
        identity = payload.get("identity")
        limits = payload.get("limits")
        if not isinstance(identity, Mapping) or not isinstance(limits, Mapping):
            raise ValueError("CONTEXT_POLICY_UNRESOLVED: frozen policy is incomplete")
        return cls(
            identity=PolicyIdentity(
                policy_id=str(identity.get("policy_id") or ""),
                version=str(identity.get("version") or ""),
                content_hash=str(identity.get("content_hash") or ""),
                snapshot_ref=str(identity.get("snapshot_ref") or ""),
            ),
            allowed_logical_kinds=tuple(
                str(value) for value in payload.get("allowed_logical_kinds") or ()
            ),
            allowed_physical_types=tuple(
                str(value) for value in payload.get("allowed_physical_types") or ()
            ),
            denied_logical_kinds=tuple(
                str(value) for value in payload.get("denied_logical_kinds") or ()
            ),
            denied_physical_types=tuple(
                str(value) for value in payload.get("denied_physical_types") or ()
            ),
            required_logical_kinds=tuple(
                str(value) for value in payload.get("required_logical_kinds") or ()
            ),
            limits=ContextBudgetLimits(
                total=int(limits.get("total") or 0),
                sections=dict(limits.get("sections") or {}),
                buckets=dict(limits.get("buckets") or {}),
                classes=dict(limits.get("classes") or {}),
                required_reservation=int(limits.get("required_reservation") or 0),
            ),
            permitted_truncation_strategies=tuple(
                str(value)
                for value in payload.get("permitted_truncation_strategies") or ()
            ),
            permitted_source_modes=tuple(
                str(value) for value in payload.get("permitted_source_modes") or ()
            ),
            source_risk_threshold=int(payload.get("source_risk_threshold") or 0),
            maximum_raw_source_ratio=float(
                payload.get("maximum_raw_source_ratio") or 0
            ),
        )


@dataclass(frozen=True, slots=True)
class EffectiveContextPolicy:
    allowed_logical_kinds: tuple[str, ...]
    allowed_physical_types: tuple[str, ...]
    denied_logical_kinds: tuple[str, ...]
    denied_physical_types: tuple[str, ...]
    required_logical_kinds: tuple[str, ...]
    limits: ContextBudgetLimits
    permitted_truncation_strategies: tuple[str, ...]
    permitted_source_modes: tuple[str, ...]
    source_risk_threshold: int
    maximum_raw_source_ratio: float
    compiler_version: str = CONTEXT_POLICY_COMPILER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_version": self.compiler_version,
            "allowed_logical_kinds": list(self.allowed_logical_kinds),
            "allowed_physical_types": list(self.allowed_physical_types),
            "denied_logical_kinds": list(self.denied_logical_kinds),
            "denied_physical_types": list(self.denied_physical_types),
            "required_logical_kinds": list(self.required_logical_kinds),
            "limits": self.limits.to_dict(),
            "permitted_truncation_strategies": list(
                self.permitted_truncation_strategies
            ),
            "permitted_source_modes": list(self.permitted_source_modes),
            "source_risk_threshold": self.source_risk_threshold,
            "maximum_raw_source_ratio": self.maximum_raw_source_ratio,
        }


@dataclass(frozen=True, slots=True)
class ContextPolicyCompilation:
    effective_policy: EffectiveContextPolicy
    receipt: Mapping[str, Any]


def _intersection(values: list[set[str]], *, label: str) -> tuple[str, ...]:
    if not values:
        return ()
    resolved = set.intersection(*values)
    if not resolved:
        raise ValueError(f"CONTEXT_POLICY_CONFLICT: {label} intersection is empty")
    return tuple(sorted(resolved))


def _strictest_named_limits(
    policies: tuple[ContextPolicySnapshot, ...], name: str, total: int
) -> dict[str, int]:
    keys = {
        key
        for policy in policies
        for key in getattr(policy.limits, name)
    }
    return {
        key: min(
            [total]
            + [
                int(getattr(policy.limits, name)[key])
                for policy in policies
                if key in getattr(policy.limits, name)
            ]
        )
        for key in sorted(keys)
    }


def compile_effective_context_policy(
    snapshots: Iterable[ContextPolicySnapshot],
) -> ContextPolicyCompilation:
    policies = tuple(snapshots)
    if not policies:
        raise ValueError("CONTEXT_POLICY_UNRESOLVED: no policy inputs")
    identities: dict[tuple[str, str], str] = {}
    for policy in policies:
        identity = policy.identity
        if identity.version not in SUPPORTED_POLICY_VERSIONS:
            raise ValueError(
                "CONTEXT_POLICY_UNRESOLVED: unsupported policy version "
                + identity.version
            )
        key = (identity.policy_id, identity.version)
        previous = identities.setdefault(key, identity.content_hash)
        if previous != identity.content_hash:
            raise ValueError(
                "CONTEXT_POLICY_IDENTITY_CONFLICT: duplicate identity has different hash"
            )
    logical_allow = _intersection(
        [set(policy.allowed_logical_kinds) for policy in policies if policy.allowed_logical_kinds],
        label="logical allowlist",
    )
    physical_allow = _intersection(
        [set(policy.allowed_physical_types) for policy in policies if policy.allowed_physical_types],
        label="physical allowlist",
    )
    denied_logical = _string_tuple(
        value for policy in policies for value in policy.denied_logical_kinds
    )
    denied_physical = _string_tuple(
        value for policy in policies for value in policy.denied_physical_types
    )
    required = _string_tuple(
        value for policy in policies for value in policy.required_logical_kinds
    )
    effective_logical = tuple(
        value for value in logical_allow if value not in set(denied_logical)
    )
    effective_physical = tuple(
        value for value in physical_allow if value not in set(denied_physical)
    )
    denied_required = set(required) & set(denied_logical)
    unavailable_required = set(required) - set(effective_logical)
    if denied_required:
        raise ValueError(
            "CONTEXT_REQUIRED_SOURCE_DENIED: " + ", ".join(sorted(denied_required))
        )
    if unavailable_required:
        raise ValueError(
            "CONTEXT_REQUIRED_SOURCE_UNAVAILABLE: "
            + ", ".join(sorted(unavailable_required))
        )
    total = min(policy.limits.total for policy in policies)
    truncation_sets = [
        set(policy.permitted_truncation_strategies) for policy in policies
    ]
    mode_sets = [set(policy.permitted_source_modes) for policy in policies]
    effective = EffectiveContextPolicy(
        allowed_logical_kinds=effective_logical,
        allowed_physical_types=effective_physical,
        denied_logical_kinds=denied_logical,
        denied_physical_types=denied_physical,
        required_logical_kinds=required,
        limits=ContextBudgetLimits(
            total=total,
            sections=_strictest_named_limits(policies, "sections", total),
            buckets=_strictest_named_limits(policies, "buckets", total),
            classes=_strictest_named_limits(policies, "classes", total),
            required_reservation=max(
                policy.limits.required_reservation for policy in policies
            ),
        ),
        permitted_truncation_strategies=tuple(
            sorted(set.intersection(*truncation_sets))
        ),
        permitted_source_modes=tuple(sorted(set.intersection(*mode_sets))),
        source_risk_threshold=min(
            policy.source_risk_threshold for policy in policies
        ),
        maximum_raw_source_ratio=min(
            policy.maximum_raw_source_ratio for policy in policies
        ),
    )
    normalized_inputs = [
        policy.to_dict()
        for policy in sorted(
            policies,
            key=lambda value: (
                value.identity.policy_id,
                value.identity.version,
                value.identity.content_hash,
            ),
        )
    ]
    receipt_body = {
        "compiler_version": CONTEXT_POLICY_COMPILER_VERSION,
        "input_policies": normalized_inputs,
        "effective_policy": effective.to_dict(),
        "conflict_decision": "PASS",
    }
    return ContextPolicyCompilation(
        effective_policy=effective,
        receipt={**receipt_body, "receipt_hash": _hash(receipt_body)},
    )


__all__ = [
    "CONTEXT_POLICY_COMPILER_VERSION",
    "ContextBudgetLimits",
    "ContextPolicyCompilation",
    "ContextPolicySnapshot",
    "EffectiveContextPolicy",
    "PolicyIdentity",
    "compile_effective_context_policy",
]
