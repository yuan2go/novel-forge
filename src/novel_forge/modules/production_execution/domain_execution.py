"""Domain-facing candidate port over the Production Execution Gateway.

Domain modules own prompts, semantic validation, repair, approval, and activation.
This module only turns an already frozen Authority ExecutionRequest into a structured
candidate plus execution evidence.  The development adapter is an explicit
strangler seam and is fail-closed in controlled environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol

from novel_forge.modules.production_execution.capability_registry import (
    CONTROLLED_ENVIRONMENTS,
    default_capability_registry,
)
from novel_forge.modules.production_execution.contracts import (
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
)
from novel_forge.modules.production_execution.gateway import ProductionExecutionGateway
from novel_forge.modules.production_execution.evidence import ExecutionRecordStore
from novel_forge.modules.production_execution.security import execution_environment


class CandidateKind(StrEnum):
    GENERATION = "GenerationCandidate"
    RAW_STRUCTURED_OUTPUT = "RawStructuredOutput"
    JUDGE = "JudgeCandidate"
    PLAN_CHANGE = "PlanChangeProposalCandidate"
    AGENT_RESULT = "StructuredAgentResult"
    EXTERNAL_ACTION = "ExternalActionCandidate"


class DomainModelOperation(StrEnum):
    GENERATE = "generate"
    ANALYZE = "analyze"
    REVIEW = "review"
    REVISE = "revise"


@dataclass(frozen=True, slots=True)
class DomainExecutionCommand:
    capability: str
    operation: DomainModelOperation
    candidate_kind: CandidateKind
    prompt: str
    context: Mapping[str, Any]
    review: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        default_capability_registry().resolve(self.capability)
        if not self.prompt.strip():
            raise ValueError("domain execution prompt cannot be empty")
        if self.operation is DomainModelOperation.REVISE and self.review is None:
            raise ValueError("revision execution requires review input")


@dataclass(frozen=True, slots=True)
class DomainExecutionEvidence:
    execution_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    capability: str
    backend_id: str
    route_snapshot_id: str
    input_manifest_ref: str
    output_manifest_ref: str
    validation_manifest_ref: str
    usage_receipt_ref: str
    cost_receipt_ref: str
    fixture_protocol_only: bool
    real_model_call: bool
    production_verified: bool
    legacy_compatibility_only: bool = False
    provider_id: str = ""
    model_id: str = ""
    provider_request_id: str = ""
    external_receipt_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "fencing_token": self.fencing_token,
            "capability": self.capability,
            "backend_id": self.backend_id,
            "route_snapshot_id": self.route_snapshot_id,
            "input_manifest_ref": self.input_manifest_ref,
            "output_manifest_ref": self.output_manifest_ref,
            "validation_manifest_ref": self.validation_manifest_ref,
            "usage_receipt_ref": self.usage_receipt_ref,
            "cost_receipt_ref": self.cost_receipt_ref,
            "fixture_protocol_only": self.fixture_protocol_only,
            "real_model_call": self.real_model_call,
            "production_verified": self.production_verified,
            "legacy_compatibility_only": self.legacy_compatibility_only,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "provider_request_id": self.provider_request_id,
            "external_receipt_ref": self.external_receipt_ref,
        }


@dataclass(frozen=True, slots=True)
class DomainExecutionCandidate:
    candidate_kind: CandidateKind
    raw_output: Mapping[str, Any]
    evidence: DomainExecutionEvidence

    def __post_init__(self) -> None:
        if not self.raw_output:
            raise ValueError("domain execution candidate output cannot be empty")


class DomainExecutionPort(Protocol):
    def execute(self, command: DomainExecutionCommand) -> DomainExecutionCandidate: ...


class GatewayDomainExecutionPort:
    """Submit pre-bound Authority requests and return candidates without committing."""

    production_execution_gateway_backed = True
    # A GatewayDomainExecutionPort is only admissible after its request has
    # been frozen and dispatched by the Command Kernel ExternalEffect runtime.
    # Bare gateway callers must not claim this marker; Planning binds the
    # ExternalEffect-aware port exposed by Agent Runtime instead.
    external_effect_backed = False

    def __init__(
        self,
        *,
        gateway: ProductionExecutionGateway,
        evidence_store: ExecutionRecordStore,
        requests: Mapping[str, ExecutionRequest],
    ) -> None:
        if not requests:
            raise ValueError("Gateway domain execution requires frozen requests")
        self.gateway = gateway
        self.evidence_store = evidence_store
        self.requests = dict(requests)

    def execute(self, command: DomainExecutionCommand) -> DomainExecutionCandidate:
        request = self.requests.get(command.capability)
        if request is None or request.capability != command.capability:
            raise ValueError("no frozen Authority ExecutionRequest for capability")
        handle = self.gateway.submit(request)
        result = self.gateway.reconcile(handle)
        if result.outcome is not ExecutionOutcome.SUCCEEDED:
            raise RuntimeError(
                f"production execution did not produce a candidate: {result.outcome.value}"
            )
        required = {
            "normalized output": result.normalized_output_ref,
            "output manifest": result.output_manifest_ref,
            "validation manifest": result.validation_report_ref,
            "usage receipt": result.usage_receipt_ref,
            "cost receipt": result.cost_receipt_ref,
        }
        missing = [label for label, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                "successful production execution lacks " + ", ".join(missing)
            )
        output = self.evidence_store.read_evidence(str(result.normalized_output_ref))
        if not isinstance(output, Mapping) or not output:
            raise RuntimeError(
                "normalized production output is not a structured object"
            )
        return DomainExecutionCandidate(
            candidate_kind=command.candidate_kind,
            raw_output=dict(output),
            evidence=DomainExecutionEvidence(
                execution_id=request.execution_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                capability=request.capability,
                backend_id=handle.backend_id,
                route_snapshot_id=request.route_snapshot_id,
                input_manifest_ref=request.input_manifest_ref,
                output_manifest_ref=str(result.output_manifest_ref),
                validation_manifest_ref=str(result.validation_report_ref),
                usage_receipt_ref=str(result.usage_receipt_ref),
                cost_receipt_ref=str(result.cost_receipt_ref),
                fixture_protocol_only=(
                    handle.transport is ExecutionRuntimeClass.SCRIPTED_FIXTURE
                ),
                real_model_call=handle.transport
                in {
                    ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                    ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
                },
                production_verified=False,
                provider_request_id=str(handle.provider_request_id or ""),
                external_receipt_ref=str(result.external_receipt_ref or ""),
            ),
        )


def execute_domain_candidate(
    *,
    capability: str,
    operation: DomainModelOperation | str,
    candidate_kind: CandidateKind | str,
    prompt: str,
    context: Mapping[str, Any],
    review: Mapping[str, Any] | None = None,
    execution_port: DomainExecutionPort | None = None,
    legacy_model: object | None = None,
    legacy_model_role: str = "",
    legacy_provider: str = "",
    legacy_model_name: str = "",
    environment: str = "",
    storage: object | None = None,
    agent_run_path: str = "",
    legacy_validation_operation: DomainModelOperation | str | None = None,
) -> DomainExecutionCandidate:
    """Execute through PEP, or an explicitly non-controlled compatibility seam."""

    command = DomainExecutionCommand(
        capability=capability,
        operation=DomainModelOperation(operation),
        candidate_kind=CandidateKind(candidate_kind),
        prompt=prompt,
        context=dict(context),
        review=None if review is None else dict(review),
    )
    if execution_port is not None:
        return execution_port.execute(command)

    normalized_environment = execution_environment(environment)
    if normalized_environment in CONTROLLED_ENVIRONMENTS:
        raise RuntimeError(
            "legacy direct model adapters are disabled; controlled domain execution "
            "requires GatewayDomainExecutionPort"
        )
    if legacy_model is None:
        if not legacy_model_role:
            raise ValueError(
                "development compatibility execution requires a model role"
            )
        from novel_forge.model_adapters import model_from_env
        import os

        legacy_environment = dict(os.environ)
        if legacy_provider:
            legacy_environment["NOVEL_FORGE_MODEL_PROVIDER"] = legacy_provider
        if legacy_model_name:
            legacy_environment["NOVEL_FORGE_MODEL_NAME"] = legacy_model_name
        legacy_model = model_from_env(legacy_model_role, env=legacy_environment)
    model = legacy_model
    if storage is not None and agent_run_path:
        from novel_forge.model_adapters import GuardedModelAdapter

        model = GuardedModelAdapter(legacy_model, storage, agent_run_path)
    if command.operation is DomainModelOperation.GENERATE:
        raw = model.generate(command.prompt, dict(command.context))  # type: ignore[attr-defined]
    elif command.operation is DomainModelOperation.ANALYZE:
        raw = model.analyze(command.prompt, dict(command.context))  # type: ignore[attr-defined]
    elif command.operation is DomainModelOperation.REVIEW:
        raw = model.review(command.prompt, dict(command.context))  # type: ignore[attr-defined]
    else:
        raw = model.revise(  # type: ignore[attr-defined]
            command.prompt,
            dict(command.review or {}),
            dict(command.context),
        )
    from novel_forge.model_adapters import validate_model_output

    validation_operation = (
        DomainModelOperation(legacy_validation_operation).value
        if legacy_validation_operation is not None
        else command.operation.value
    )
    output = validate_model_output(validation_operation, raw)
    model_name = str(getattr(legacy_model, "name", "development-model"))
    return DomainExecutionCandidate(
        candidate_kind=command.candidate_kind,
        raw_output=output,
        evidence=DomainExecutionEvidence(
            execution_id="",
            operation_id="",
            attempt_id="",
            fencing_token=0,
            capability=command.capability,
            backend_id=f"legacy-development:{model_name}",
            route_snapshot_id="",
            input_manifest_ref="",
            output_manifest_ref="",
            validation_manifest_ref="",
            usage_receipt_ref="",
            cost_receipt_ref="",
            fixture_protocol_only=True,
            real_model_call=False,
            production_verified=False,
            legacy_compatibility_only=True,
            provider_id=model_name,
            model_id=model_name,
        ),
    )


def execution_model_name(
    execution_port: DomainExecutionPort | None,
    legacy_model: object | None,
    *,
    legacy_model_role: str,
) -> str:
    if execution_port is not None:
        return "production-execution-gateway"
    return str(getattr(legacy_model, "name", legacy_model_role or "development-model"))


__all__ = [
    "CandidateKind",
    "DomainExecutionCandidate",
    "DomainExecutionCommand",
    "DomainExecutionEvidence",
    "DomainExecutionPort",
    "DomainModelOperation",
    "GatewayDomainExecutionPort",
    "execute_domain_candidate",
    "execution_model_name",
]
