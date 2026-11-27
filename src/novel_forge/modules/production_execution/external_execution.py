from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping, Protocol

from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.modules.production_execution.contracts import (
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
)
from novel_forge.modules.production_execution.gateway import ProductionExecutionGateway
from novel_forge.modules.production_execution.evidence import ExecutionRecordStore
from novel_forge.modules.production_execution.security import assert_no_inline_secrets


class ExternalActionKind(StrEnum):
    PUBLISH_SUBMIT = "publishing.release.submit"
    PUBLISH_QUERY = "publishing.release.query"
    PUBLISH_WITHDRAW = "publishing.release.withdraw"
    FEEDBACK_FETCH = "feedback.platform.fetch"
    SOURCE_FETCH = "source.remote.fetch"
    NOTIFICATION_SEND = "notification.send"
    STORAGE_OBJECT_PUT = "storage.object.put"
    TOOL_REMOTE_INVOKE = "tool.remote.invoke"
    ANALYTICS_QUERY_EXECUTE = "analytics.query.execute"
    RETRIEVAL_INDEX_UPSERT = "retrieval.index.upsert"
    RETRIEVAL_INDEX_QUERY = "retrieval.index.query"


@dataclass(frozen=True, slots=True)
class ExternalActionCommand:
    capability: str
    request_payload: Mapping[str, Any]
    stable_idempotency_key: str
    data_classification: str
    privacy_policy_ref: str
    rate_limit_policy_ref: str
    quota_policy_ref: str

    def __post_init__(self) -> None:
        definition = default_capability_registry().resolve(self.capability)
        if (
            ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION
            not in definition.allowed_runtime_classes
        ):
            raise ValueError("capability is not a remote external action")
        if not self.request_payload:
            raise ValueError("external action request payload cannot be empty")
        if not all(
            (
                self.stable_idempotency_key,
                self.data_classification,
                self.privacy_policy_ref,
                self.rate_limit_policy_ref,
                self.quota_policy_ref,
            )
        ):
            raise ValueError("external action governance contract is incomplete")
        assert_no_inline_secrets(self.to_dict(), label="ExternalActionCommand")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "capability": self.capability,
            "request_payload": dict(self.request_payload),
            "stable_idempotency_key": self.stable_idempotency_key,
            "data_classification": self.data_classification,
            "privacy_policy_ref": self.privacy_policy_ref,
            "rate_limit_policy_ref": self.rate_limit_policy_ref,
            "quota_policy_ref": self.quota_policy_ref,
        }
        assert_no_inline_secrets(payload, label="ExternalActionCommand")
        return payload

    @property
    def contract_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ExternalActionExecutionEvidence:
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
    external_receipt_ref: str
    usage_receipt_ref: str
    cost_receipt_ref: str
    external_request_id: str
    query_supported: bool
    cancel_supported: bool
    callback_supported: bool
    fixture_protocol_only: bool
    real_model_call: bool = False
    real_external_action: bool = False
    production_verified: bool = False

    def __post_init__(self) -> None:
        if self.real_model_call:
            raise ValueError("external action evidence cannot claim a model call")
        if self.fixture_protocol_only and (
            self.real_external_action or self.production_verified
        ):
            raise ValueError("fixture external action cannot claim real evidence")

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
            "external_receipt_ref": self.external_receipt_ref,
            "usage_receipt_ref": self.usage_receipt_ref,
            "cost_receipt_ref": self.cost_receipt_ref,
            "external_request_id": self.external_request_id,
            "query_supported": self.query_supported,
            "cancel_supported": self.cancel_supported,
            "callback_supported": self.callback_supported,
            "fixture_protocol_only": self.fixture_protocol_only,
            "real_model_call": self.real_model_call,
            "real_external_action": self.real_external_action,
            "production_verified": self.production_verified,
        }


@dataclass(frozen=True, slots=True)
class ExternalActionCandidate:
    raw_output: Mapping[str, Any]
    evidence: ExternalActionExecutionEvidence

    def __post_init__(self) -> None:
        if not self.raw_output:
            raise ValueError("external action candidate output cannot be empty")


class ExternalActionExecutionPort(Protocol):
    def execute(self, command: ExternalActionCommand) -> ExternalActionCandidate: ...


class GatewayExternalActionExecutionPort:

    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        gateway: ProductionExecutionGateway,
        evidence_store: ExecutionRecordStore,
        requests: Mapping[str, ExecutionRequest],
    ) -> None:
        if not requests:
            raise ValueError("Gateway external execution requires frozen requests")
        self.gateway = gateway
        self.evidence_store = evidence_store
        self.requests = dict(requests)

    def execute(self, command: ExternalActionCommand) -> ExternalActionCandidate:
        request = self.requests.get(command.capability)
        if request is None or request.capability != command.capability:
            raise ValueError("no frozen Authority ExecutionRequest for capability")
        if request.stable_idempotency_key != command.stable_idempotency_key:
            raise ValueError("external action idempotency key differs from frozen request")
        handle = self.gateway.submit(request)
        result = self.gateway.reconcile(handle)
        if result.outcome is not ExecutionOutcome.SUCCEEDED:
            raise RuntimeError(
                f"external action did not succeed: {result.outcome.value}"
            )
        required = {
            "normalized output": result.normalized_output_ref,
            "output manifest": result.output_manifest_ref,
            "validation manifest": result.validation_report_ref,
            "external receipt": result.external_receipt_ref,
            "usage receipt": result.usage_receipt_ref,
            "cost receipt": result.cost_receipt_ref,
            "external request ID": handle.external_request_id,
        }
        missing = [label for label, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                "successful external action lacks " + ", ".join(missing)
            )
        output = self.evidence_store.read_evidence(str(result.normalized_output_ref))
        if not isinstance(output, Mapping) or not output:
            raise RuntimeError("normalized external output is not a structured object")
        external_receipt = self.evidence_store.read_evidence(
            str(result.external_receipt_ref)
        )
        receipt_evidence = (
            external_receipt.get("evidence")
            if isinstance(external_receipt, Mapping)
            else {}
        )
        fixture = bool(
            output.get("fixture_protocol_only")
            or (
                isinstance(receipt_evidence, Mapping)
                and receipt_evidence.get("fixture_protocol_only")
            )
        )
        return ExternalActionCandidate(
            raw_output=dict(output),
            evidence=ExternalActionExecutionEvidence(
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
                external_receipt_ref=str(result.external_receipt_ref),
                usage_receipt_ref=str(result.usage_receipt_ref),
                cost_receipt_ref=str(result.cost_receipt_ref),
                external_request_id=str(handle.external_request_id),
                query_supported=handle.query_capability.value == "SUPPORTED",
                cancel_supported=handle.cancel_capability.value == "SUPPORTED",
                callback_supported=handle.callback_capability.value == "SUPPORTED",
                fixture_protocol_only=fixture,
                real_external_action=not fixture,
                production_verified=False,
            ),
        )


def execute_external_action(
    *,
    capability: ExternalActionKind | str,
    request_payload: Mapping[str, Any],
    stable_idempotency_key: str,
    data_classification: str,
    privacy_policy_ref: str,
    rate_limit_policy_ref: str,
    quota_policy_ref: str,
    execution_port: ExternalActionExecutionPort,
) -> ExternalActionCandidate:
    return execution_port.execute(
        ExternalActionCommand(
            capability=ExternalActionKind(capability).value,
            request_payload=dict(request_payload),
            stable_idempotency_key=stable_idempotency_key,
            data_classification=data_classification,
            privacy_policy_ref=privacy_policy_ref,
            rate_limit_policy_ref=rate_limit_policy_ref,
            quota_policy_ref=quota_policy_ref,
        )
    )


__all__ = [
    "ExternalActionCandidate",
    "ExternalActionCommand",
    "ExternalActionExecutionEvidence",
    "ExternalActionExecutionPort",
    "ExternalActionKind",
    "GatewayExternalActionExecutionPort",
    "execute_external_action",
]
