"""Typed contracts shared by Chapter and Content Authority runtimes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from novel_forge.modules.command_kernel.errors import KernelError


@dataclass(frozen=True, slots=True)
class AuthorityInputAsset:
    asset_version_id: str
    asset_type: str
    content_hash: str
    content: dict[str, Any]
    lifecycle: str = "ACTIVE"
    eligibility: str = "ELIGIBLE"
    governance: str = "CLEAR"
    qualification_decision: str = "ELIGIBLE"
    qualification_policy_version: str = "implicit-active-v1"
    blobs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AuthorityHandlerRequest:
    operation_id: str
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    definition_name: str
    definition_version: str
    command: dict[str, Any]
    inputs: tuple[AuthorityInputAsset, ...]
    attempt_id: str = ""
    fencing_token: int = 0
    worker_id: str = ""

    def inputs_of_type(self, asset_type: str) -> tuple[AuthorityInputAsset, ...]:
        return tuple(item for item in self.inputs if item.asset_type == asset_type)

    def require_input(self, asset_type: str) -> AuthorityInputAsset:
        matching = self.inputs_of_type(asset_type)
        if len(matching) != 1:
            raise KernelError(
                "AUTHORITY_HANDLER_INPUT_INVALID",
                f"expected exactly one {asset_type} input, found {len(matching)}",
            )
        return matching[0]


@dataclass(frozen=True, slots=True)
class AuthorityAuxiliaryOutput:
    asset_type: str
    output_key: str
    role: str
    content: dict[str, Any]
    qualification_policy: str
    reference_asset_version_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    lifecycle: str = "ACTIVE"
    eligibility: str = "ELIGIBLE"
    governance: str = "CLEAR"


@dataclass(frozen=True, slots=True)
class AuthorityHandlerOutput:
    asset_type: str
    output_key: str
    role: str
    content: dict[str, Any]
    qualification_policy: str
    reference_asset_version_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    auxiliary_outputs: tuple[AuthorityAuxiliaryOutput, ...] = ()
    lifecycle: str = "ACTIVE"
    eligibility: str = "ELIGIBLE"
    governance: str = "CLEAR"


class AuthorityHandler(Protocol):
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput: ...


@dataclass(frozen=True, slots=True)
class AuthorityHandlerRegistration:
    definition_name: str
    definition_version: str
    handler_key: str
    handler_contract_version: str
    output_asset_type: str
    output_key: str
    role: str
    completion_topic: str
    handler: AuthorityHandler


class AuthorityHandlerRegistry(Protocol):
    """Registry seam consumed by the one shared fenced handler scheduler."""

    @property
    def definition_names(self) -> frozenset[str]: ...

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration: ...


@dataclass(frozen=True, slots=True)
class AuthorityMaterializedOutput:
    asset_id: str
    asset_version_id: str
    asset_type: str
    output_key: str
    role: str
    content_hash: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class AuthorityExecutionResult:
    operation_id: str
    asset_id: str
    asset_version_id: str
    content_hash: str
    output_key: str
    replayed: bool
    materialized_outputs: tuple[AuthorityMaterializedOutput, ...] = ()
