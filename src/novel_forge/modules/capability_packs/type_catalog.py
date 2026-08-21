"""Governed, immutable policy catalogs used by Capability Pack resolution."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable


@dataclass(frozen=True, slots=True)
class CapabilityTypePolicy:
    capability_type: str
    policy_class: str
    generation: bool
    allows_external_effects: bool
    requires_authority_operation: bool
    requires_attempt_fence: bool
    allows_raw_source: bool
    required_audit_level: str
    allowed_lifecycles: tuple[str, ...]
    allowed_release_channels: tuple[str, ...]
    allowed_status_lifecycle_channels: tuple[tuple[str, str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_type": self.capability_type,
            "policy_class": self.policy_class,
            "generation": self.generation,
            "allows_external_effects": self.allows_external_effects,
            "requires_authority_operation": self.requires_authority_operation,
            "requires_attempt_fence": self.requires_attempt_fence,
            "allows_raw_source": self.allows_raw_source,
            "required_audit_level": self.required_audit_level,
            "allowed_lifecycles": list(self.allowed_lifecycles),
            "allowed_release_channels": list(self.allowed_release_channels),
            "allowed_status_lifecycle_channels": [
                list(item) for item in self.allowed_status_lifecycle_channels
            ],
        }


class CapabilityTypePolicyCatalog:
    """Read-only catalog; P1A intentionally opens one capability type."""

    def __init__(self, policies: Iterable[CapabilityTypePolicy]) -> None:
        values: dict[str, CapabilityTypePolicy] = {}
        for policy in policies:
            existing = values.get(policy.capability_type)
            if existing is not None and existing != policy:
                raise ValueError("capability type policy version conflict")
            values[policy.capability_type] = policy
        self._policies = MappingProxyType(values)

    def resolve(self, capability_type: str) -> CapabilityTypePolicy:
        try:
            return self._policies[capability_type]
        except KeyError as exc:
            raise KeyError(
                f"capability type is not governed: {capability_type}"
            ) from exc

    def policies(self) -> tuple[CapabilityTypePolicy, ...]:
        return tuple(self._policies[key] for key in sorted(self._policies))


def default_capability_type_catalog() -> CapabilityTypePolicyCatalog:
    lifecycle_channels = (
        ("DRAFT", "DESIGN", "DEV"),
        ("DRAFT", "VALIDATION", "DEV"),
        ("CANDIDATE", "VALIDATION", "VALIDATION"),
        ("ACTIVE", "PRODUCTION", "CANARY"),
        ("ACTIVE", "PRODUCTION", "PRODUCTION"),
        ("DEPRECATED", "MAINTENANCE", "PRODUCTION"),
        ("RETIRED", "RETIRED", "PRODUCTION"),
        ("DISABLED", "MAINTENANCE", "DEV"),
        ("DISABLED", "MAINTENANCE", "VALIDATION"),
        ("DISABLED", "MAINTENANCE", "CANARY"),
        ("DISABLED", "MAINTENANCE", "PRODUCTION"),
    )
    return CapabilityTypePolicyCatalog(
        (
            CapabilityTypePolicy(
                capability_type="production_workflow",
                policy_class="AUTHORITY_BOUND_GENERATION",
                generation=True,
                allows_external_effects=True,
                requires_authority_operation=True,
                requires_attempt_fence=True,
                allows_raw_source=False,
                required_audit_level="FULL",
                allowed_lifecycles=(
                    "DESIGN",
                    "VALIDATION",
                    "PRODUCTION",
                    "MAINTENANCE",
                    "RETIRED",
                ),
                allowed_release_channels=("DEV", "VALIDATION", "CANARY", "PRODUCTION"),
                allowed_status_lifecycle_channels=lifecycle_channels,
            ),
            CapabilityTypePolicy(
                capability_type="agent_session_runtime",
                policy_class="AUTHORITY_BOUND_AGENT_EXECUTION",
                generation=False,
                allows_external_effects=True,
                requires_authority_operation=True,
                requires_attempt_fence=True,
                allows_raw_source=False,
                required_audit_level="FULL",
                allowed_lifecycles=(
                    "DESIGN",
                    "VALIDATION",
                    "PRODUCTION",
                    "MAINTENANCE",
                    "RETIRED",
                ),
                allowed_release_channels=(
                    "DEV",
                    "VALIDATION",
                    "CANARY",
                    "PRODUCTION",
                ),
                allowed_status_lifecycle_channels=lifecycle_channels,
            ),
        )
    )


def conservative_capability_type_policy(
    capability_type: str,
) -> CapabilityTypePolicy:
    """Return the fail-closed policy used only while reporting an unknown type."""

    return CapabilityTypePolicy(
        capability_type=capability_type,
        policy_class="UNSUPPORTED_FAIL_CLOSED",
        generation=True,
        allows_external_effects=False,
        requires_authority_operation=True,
        requires_attempt_fence=True,
        allows_raw_source=False,
        required_audit_level="FULL",
        allowed_lifecycles=(),
        allowed_release_channels=(),
        allowed_status_lifecycle_channels=(),
    )


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_ref: str
    allowed_permissions: tuple[str, ...]
    minimum_risk_class: str
    audit_required: bool
    approval_required: bool
    external_capability_patterns: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_ref": self.tool_ref,
            "allowed_permissions": list(self.allowed_permissions),
            "minimum_risk_class": self.minimum_risk_class,
            "audit_required": self.audit_required,
            "approval_required": self.approval_required,
            "external_capability_patterns": list(self.external_capability_patterns),
        }


class ToolDefinitionCatalog:
    def __init__(self, definitions: Iterable[ToolDefinition]) -> None:
        values: dict[str, ToolDefinition] = {}
        for definition in definitions:
            existing = values.get(definition.tool_ref)
            if existing is not None and existing != definition:
                raise ValueError("tool definition conflict")
            values[definition.tool_ref] = definition
        self._definitions = MappingProxyType(values)

    def resolve(self, tool_ref: str) -> ToolDefinition:
        try:
            return self._definitions[tool_ref]
        except KeyError as exc:
            raise KeyError(f"tool is not governed: {tool_ref}") from exc

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


def default_tool_definition_catalog() -> ToolDefinitionCatalog:
    return ToolDefinitionCatalog(
        (
            ToolDefinition(
                "model.provider.invoke",
                ("EXECUTE",),
                "HIGH",
                True,
                False,
                ("model.*",),
            ),
            ToolDefinition(
                "storage.object.put",
                ("EXECUTE",),
                "HIGH",
                True,
                False,
                ("object_store.put",),
            ),
            ToolDefinition(
                "narrative.query_accepted",
                ("QUERY",),
                "LOW",
                True,
                False,
                ("tool.remote.invoke",),
            ),
            ToolDefinition(
                "story_planning.generate_candidate",
                ("EXECUTE",),
                "HIGH",
                True,
                False,
                ("tool.remote.invoke",),
            ),
            ToolDefinition(
                "plan_change.submit",
                ("EXECUTE",),
                "CRITICAL",
                True,
                True,
                ("tool.remote.invoke",),
            ),
        )
    )


__all__ = [
    "CapabilityTypePolicy",
    "CapabilityTypePolicyCatalog",
    "ToolDefinition",
    "ToolDefinitionCatalog",
    "default_capability_type_catalog",
    "default_tool_definition_catalog",
    "conservative_capability_type_policy",
]
