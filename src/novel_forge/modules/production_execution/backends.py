"""Execution backend implementations behind :mod:`production_execution.gateway`.

Backend records are execution evidence and recovery indexes.  They do not own
Attempt lifecycle, approval, budget, or asset activation state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Protocol

from novel_forge.modules.provider_control.contracts import (
    ProviderCancellationRequest,
    ProviderControlLevel,
    ProviderInvocationResult,
    ProviderQueryRequest,
    ProviderReceipt,
)
from novel_forge.modules.provider_control.registry import ProviderAdapterV2

from .contracts import (
    CancellationOutcome,
    CapabilityAvailability,
    CompletionMode,
    ExecutionCancellationResult,
    ExecutionCapabilityProfile,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeClass,
    LocalTerminationOutcome,
    OutputManifest,
    UpstreamCancellationOutcome,
    ValidationCheck,
    ValidationManifest,
)
from .gateway import AdmissionController, ExecutionAdmission
from .process_supervisor import (
    CodexProcessSupervisor,
    ProcessLaunchRequest,
    ProcessReceipt,
    ProcessReceiptStatus,
    ProcessTimeout,
    ResultIntegrity,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedExecutionPayload:
    request_payload: Mapping[str, Any]
    input_text: str
    working_directory: str
    timeout_seconds: int
    output_schema_version: str
    command: tuple[str, ...] = ()
    result_filename: str = "result.json"
    environment_overrides: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_payload, Mapping):
            raise ValueError("resolved execution request payload must be an object")
        if not self.working_directory or self.timeout_seconds <= 0:
            raise ValueError("resolved execution payload requires workspace and timeout")
        if not self.output_schema_version:
            raise ValueError("resolved execution payload requires an output schema version")


class ExecutionPayloadResolver(Protocol):
    def resolve(
        self, request: ExecutionRequest, admission: ExecutionAdmission
    ) -> ResolvedExecutionPayload: ...


class StaticExecutionPayloadResolver:
    """Explicit fixture resolver. Production uses governed artifact readers."""

    def __init__(self, payloads: Mapping[str, ResolvedExecutionPayload]) -> None:
        self._payloads = dict(payloads)

    def resolve(
        self, request: ExecutionRequest, admission: ExecutionAdmission
    ) -> ResolvedExecutionPayload:
        del admission
        try:
            return self._payloads[request.execution_id]
        except KeyError as exc:
            raise ValueError(
                f"resolved execution payload is not available: {request.execution_id}"
            ) from exc


@dataclass(slots=True)
class ExecutionRecord:
    request: ExecutionRequest
    handle: ExecutionHandle
    started_at: str
    raw_evidence: dict[str, Any]
    provider_result: ProviderInvocationResult | None = None
    process_receipt: ProcessReceipt | None = None
    result: ExecutionResult | None = None
    callback_receipts: dict[str, tuple[str, str]] = field(default_factory=dict)
    cancellation: ExecutionCancellationResult | None = None


class ExecutionRecordStore(Protocol):
    def put_record(self, record: ExecutionRecord) -> None: ...

    def save_record(self, record: ExecutionRecord) -> None: ...

    def get_record(self, execution_id: str) -> ExecutionRecord: ...

    def find_record(self, execution_id: str) -> ExecutionRecord | None: ...

    def put_evidence(
        self, kind: str, execution_id: str, payload: Mapping[str, Any]
    ) -> str: ...

    def read_evidence(self, ref: str) -> dict[str, Any]: ...


class InMemoryExecutionRecordStore:
    """Non-production test store; refs are visibly fixture-only."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}
        self._evidence: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def put_record(self, record: ExecutionRecord) -> None:
        with self._lock:
            existing = self._records.get(record.request.execution_id)
            if existing is not None:
                if existing.request.contract_hash != record.request.contract_hash:
                    raise ValueError("duplicate execution ID has a different request")
                return
            self._records[record.request.execution_id] = record

    def save_record(self, record: ExecutionRecord) -> None:
        with self._lock:
            existing = self._records.get(record.request.execution_id)
            if (
                existing is not None
                and existing.request.contract_hash != record.request.contract_hash
            ):
                raise ValueError("duplicate execution ID has a different request")
            self._records[record.request.execution_id] = record

    def get_record(self, execution_id: str) -> ExecutionRecord:
        try:
            return self._records[execution_id]
        except KeyError as exc:
            raise ValueError(f"execution record is not available: {execution_id}") from exc

    def find_record(self, execution_id: str) -> ExecutionRecord | None:
        return self._records.get(execution_id)

    def put_evidence(
        self, kind: str, execution_id: str, payload: Mapping[str, Any]
    ) -> str:
        frozen = json.loads(_canonical_json(payload))
        digest = hashlib.sha256(_canonical_json(frozen).encode("utf-8")).hexdigest()
        ref = f"fixture-execution-evidence:{kind}:{execution_id}:{digest}"
        with self._lock:
            existing = self._evidence.get(ref)
            if existing is not None and existing != frozen:
                raise ValueError("execution evidence hash collision")
            self._evidence[ref] = frozen
        return ref

    def read_evidence(self, ref: str) -> dict[str, Any]:
        try:
            return dict(self._evidence[ref])
        except KeyError as exc:
            raise ValueError(f"execution evidence is not available: {ref}") from exc


class ResultNormalizer:
    @staticmethod
    def normalize(evidence: Mapping[str, Any]) -> dict[str, Any]:
        candidate = evidence.get("result")
        if not isinstance(candidate, Mapping) or not candidate:
            raise ValueError("execution result has no non-empty structured result")
        return json.loads(_canonical_json(candidate))


class ResultValidator:
    def __init__(self, store: ExecutionRecordStore) -> None:
        self.store = store

    def successful_result(
        self,
        record: ExecutionRecord,
        *,
        provider_receipt_ref: str | None = None,
        process_receipt_ref: str | None = None,
    ) -> ExecutionResult:
        request = record.request
        normalized = ResultNormalizer.normalize(record.raw_evidence)
        raw_ref = self.store.put_evidence(
            "raw-output", request.execution_id, record.raw_evidence
        )
        normalized_ref = self.store.put_evidence(
            "normalized-output", request.execution_id, normalized
        )
        output_manifest = OutputManifest(
            manifest_id=f"output-manifest:{request.execution_id}",
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            raw_output_ref=raw_ref,
            normalized_output_ref=normalized_ref,
            stdout_ref=(record.process_receipt.stdout_path if record.process_receipt else None),
            stderr_ref=(record.process_receipt.stderr_path if record.process_receipt else None),
            output_hash=_sha256(normalized),
            schema_version=str(
                record.raw_evidence.get("output_schema_version") or "structured-output.v1"
            ),
            files=(),
        )
        output_manifest_ref = self.store.put_evidence(
            "output-manifest", request.execution_id, output_manifest.to_dict()
        )
        checks = (
            ValidationCheck("structured_object", "PASSED", normalized_ref),
            ValidationCheck(
                "fencing",
                "PASSED",
                f"authority-attempt:{request.attempt_id}:fence:{request.fencing_token}",
            ),
            ValidationCheck(
                "route_snapshot", "PASSED", request.route_snapshot_id
            ),
        )
        validation = ValidationManifest(
            manifest_id=f"validation-manifest:{request.execution_id}",
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            output_manifest_ref=output_manifest_ref,
            validation_policy_ref=request.validation_policy_ref,
            required_check_kinds=("structured_object", "fencing", "route_snapshot"),
            checks=checks,
            decision="ACCEPTED",
        )
        validation_ref = self.store.put_evidence(
            "validation-manifest", request.execution_id, validation.to_dict()
        )
        usage = record.raw_evidence.get("usage")
        usage_ref = (
            self.store.put_evidence("usage-receipt", request.execution_id, usage)
            if isinstance(usage, Mapping)
            else None
        )
        cost = record.raw_evidence.get("cost")
        cost_ref = None
        if isinstance(cost, Mapping):
            try:
                amount = Decimal(str(cost.get("amount") or "0"))
            except InvalidOperation as exc:
                raise ValueError("execution cost receipt amount is invalid") from exc
            if amount < 0 or not str(cost.get("currency") or ""):
                raise ValueError("execution cost receipt is invalid")
            cost_ref = self.store.put_evidence(
                "cost-receipt", request.execution_id, cost
            )
        return ExecutionResult(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            outcome=ExecutionOutcome.SUCCEEDED,
            process_receipt_ref=process_receipt_ref,
            provider_receipt_ref=provider_receipt_ref,
            raw_output_ref=raw_ref,
            normalized_output_ref=normalized_ref,
            output_manifest_ref=output_manifest_ref,
            usage_receipt_ref=usage_ref,
            cost_receipt_ref=cost_ref,
            validation_report_ref=validation_ref,
            started_at=record.started_at,
            completed_at=_utc_now(),
        )


class ExecutionReconciler:
    PROVIDER_OUTCOMES = {
        "retryable_failure": ExecutionOutcome.RETRYABLE_FAILURE,
        "final_failure": ExecutionOutcome.FINAL_FAILURE,
        "unknown": ExecutionOutcome.UNKNOWN,
        "ambiguous": ExecutionOutcome.UNKNOWN,
        "not_found": ExecutionOutcome.UNKNOWN,
        "cancelled": ExecutionOutcome.CANCELLED,
        "already_completed": ExecutionOutcome.UNKNOWN,
    }
    PROCESS_OUTCOMES = {
        ProcessReceiptStatus.STARTING: ExecutionOutcome.ACCEPTED,
        ProcessReceiptStatus.RUNNING: ExecutionOutcome.RUNNING,
        ProcessReceiptStatus.START_FAILED: ExecutionOutcome.RETRYABLE_FAILURE,
        ProcessReceiptStatus.FAILED: ExecutionOutcome.RETRYABLE_FAILURE,
        ProcessReceiptStatus.CANCELLED: ExecutionOutcome.CANCELLED,
        ProcessReceiptStatus.TIMED_OUT: ExecutionOutcome.TIMED_OUT,
        ProcessReceiptStatus.ORPHANED: ExecutionOutcome.ORPHANED,
        ProcessReceiptStatus.CORRUPT_RESULT: ExecutionOutcome.CORRUPT_RESULT,
    }

    @staticmethod
    def non_success(
        record: ExecutionRecord,
        outcome: ExecutionOutcome,
        *,
        process_receipt_ref: str | None = None,
        provider_receipt_ref: str | None = None,
    ) -> ExecutionResult:
        completed = outcome not in {
            ExecutionOutcome.ACCEPTED,
            ExecutionOutcome.RUNNING,
            ExecutionOutcome.UNKNOWN,
        }
        request = record.request
        return ExecutionResult(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            outcome=outcome,
            process_receipt_ref=process_receipt_ref,
            provider_receipt_ref=provider_receipt_ref,
            raw_output_ref=None,
            normalized_output_ref=None,
            output_manifest_ref=None,
            usage_receipt_ref=None,
            cost_receipt_ref=None,
            validation_report_ref=None,
            started_at=record.started_at,
            completed_at=_utc_now() if completed else None,
        )


class ScriptedFixtureExecutionBackend:
    backend_id = "scripted-fixture"

    def __init__(
        self,
        *,
        admission: AdmissionController,
        payload_resolver: ExecutionPayloadResolver,
        record_store: ExecutionRecordStore,
    ) -> None:
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store
        self.capability_profile = ExecutionCapabilityProfile(
            backend_id=self.backend_id,
            backend_version="1.0.0",
            runtime_class=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
            supported_completion_modes=(CompletionMode.SYNCHRONOUS, CompletionMode.POLL),
            supported_reasoning_efforts=("high", "xhigh"),
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=True,
            supports_cost_receipt=True,
            supports_structured_output=True,
            supports_process_group_control=False,
            supports_persistent_execution_directory=False,
            supports_provider_idempotency=True,
            real_provider_validation_eligible=False,
            qualification_ref="capability-probe:scripted-fixture:1",
        )

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        evidence = dict(payload.request_payload)
        evidence.setdefault("fixture_protocol_only", True)
        evidence.setdefault("real_model_call", False)
        evidence.setdefault("production_verified", False)
        evidence.setdefault("output_schema_version", payload.output_schema_version)
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=f"fixture:{request.execution_id}",
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id=None,
            completion_mode=CompletionMode.SYNCHRONOUS,
            query_capability=CapabilityAvailability.SUPPORTED,
            cancel_capability=CapabilityAvailability.SUPPORTED,
            callback_capability=CapabilityAvailability.UNSUPPORTED,
        )
        self.record_store.put_record(
            ExecutionRecord(request, handle, _utc_now(), evidence)
        )
        return handle

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self.record_store.get_record(handle.execution_id)
        if record.result is None:
            record.result = ResultValidator(self.record_store).successful_result(record)
            self.record_store.save_record(record)
        return record.result

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        return ExecutionCancellationResult(
            execution_id=handle.execution_id,
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            fencing_token=handle.fencing_token,
            backend_id=self.backend_id,
            transport=handle.transport,
            outcome=CancellationOutcome.UNSUPPORTED,
            local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
            upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
            local_execution_receipt_id=None,
            provider_request_id=None,
            provider_cancellation_receipt_ref=None,
            reason=reason,
            requested_at=_utc_now(),
            completed_at=None,
        )


class RemoteProviderExecutionBackend:
    def __init__(
        self,
        *,
        backend_id: str,
        capability_profile: ExecutionCapabilityProfile,
        provider_adapter: ProviderAdapterV2,
        admission: AdmissionController,
        payload_resolver: ExecutionPayloadResolver,
        record_store: ExecutionRecordStore,
    ) -> None:
        if capability_profile.backend_id != backend_id:
            raise ValueError("remote backend capability identity mismatch")
        if capability_profile.runtime_class is not ExecutionRuntimeClass.REMOTE_PROVIDER_API:
            raise ValueError("remote backend requires REMOTE_PROVIDER_API capability")
        provider_profile = provider_adapter.capability_profile
        if provider_profile.control_level is not ProviderControlLevel.V2_CONTROLLED:
            raise ValueError(
                "RemoteProviderExecutionBackend requires a V2_CONTROLLED adapter"
            )
        capability_pairs = (
            (capability_profile.supports_query, provider_profile.supports_query, "query"),
            (capability_profile.supports_cancel, provider_profile.supports_cancel, "cancel"),
            (capability_profile.supports_callback, provider_profile.supports_callback, "callback"),
            (capability_profile.supports_usage_receipt, provider_profile.supports_usage_receipt, "usage receipt"),
            (capability_profile.supports_cost_receipt, provider_profile.supports_cost_receipt, "cost receipt"),
            (capability_profile.supports_provider_idempotency, provider_profile.supports_provider_idempotency, "provider idempotency"),
        )
        missing = [name for required, actual, name in capability_pairs if required and not actual]
        if missing:
            raise ValueError(
                "remote backend capability exceeds Provider v2 adapter: "
                + ", ".join(missing)
            )
        if (
            capability_profile.real_provider_validation_eligible
            and (
                provider_profile.control_level is not ProviderControlLevel.V2_CONTROLLED
                or not provider_profile.real_provider_validation_eligible
            )
        ):
            raise ValueError("remote backend cannot elevate an unqualified provider adapter")
        self.backend_id = backend_id
        self.capability_profile = capability_profile
        self.provider_adapter = provider_adapter
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        if admission.route_snapshot.model_provider != self.provider_adapter.provider:
            raise ValueError("RouteSnapshot provider differs from Provider v2 adapter")
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        from novel_forge.modules.provider_control.contracts import ProviderInvocationRequest

        provider_request = ProviderInvocationRequest(
            provider=admission.route_snapshot.model_provider,
            model=admission.route_snapshot.model_id,
            capability=request.capability,
            stage=request.stage,
            stable_idempotency_key=request.stable_idempotency_key,
            request_payload=dict(payload.request_payload),
            request_hash=_sha256(dict(payload.request_payload)),
            timeout_seconds=payload.timeout_seconds,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            operation_id=request.operation_id,
            external_effect_id=request.external_effect_id,
            budget_reservation_id=request.budget_reservation_id,
        )
        provisional_handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=f"provider-invoking:{request.execution_id}",
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id=None,
            completion_mode=CompletionMode.POLL,
            query_capability=(
                CapabilityAvailability.SUPPORTED
                if self.capability_profile.supports_query
                else CapabilityAvailability.UNSUPPORTED
            ),
            cancel_capability=(
                CapabilityAvailability.SUPPORTED
                if self.capability_profile.supports_cancel
                else CapabilityAvailability.UNSUPPORTED
            ),
            callback_capability=(
                CapabilityAvailability.SUPPORTED
                if self.capability_profile.supports_callback
                else CapabilityAvailability.UNSUPPORTED
            ),
        )
        record = ExecutionRecord(
            request=request,
            handle=provisional_handle,
            started_at=_utc_now(),
            raw_evidence={
                "submission_phase": "PROVIDER_INVOKING",
                "manual_resolution_required_on_restart": True,
                "output_schema_version": payload.output_schema_version,
            },
        )
        self.record_store.put_record(record)
        try:
            provider_result = self.provider_adapter.invoke(provider_request)
        except Exception:
            record.raw_evidence = {
                **record.raw_evidence,
                "submission_phase": "PROVIDER_OUTCOME_UNKNOWN",
            }
            self.record_store.save_record(record)
            raise
        provider_handle = provider_result.handle
        completion_mode = CompletionMode.SYNCHRONOUS
        if provider_handle and provider_handle.completion_mode not in {"synchronous", "sync"}:
            completion_mode = CompletionMode.POLL
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=(
                provider_handle.provider_request_id
                if provider_handle
                else f"remote:{request.execution_id}"
            ),
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id=(provider_handle.provider_request_id if provider_handle else None),
            completion_mode=completion_mode,
            query_capability=(
                CapabilityAvailability.SUPPORTED
                if self.capability_profile.supports_query
                else CapabilityAvailability.UNSUPPORTED
            ),
            cancel_capability=(
                CapabilityAvailability.SUPPORTED
                if self.capability_profile.supports_cancel
                else CapabilityAvailability.UNSUPPORTED
            ),
            callback_capability=(
                CapabilityAvailability.SUPPORTED
                if self.capability_profile.supports_callback
                else CapabilityAvailability.UNSUPPORTED
            ),
        )
        evidence = dict(provider_result.evidence)
        evidence.setdefault("output_schema_version", payload.output_schema_version)
        evidence["submission_phase"] = "PROVIDER_RESULT_RECORDED"
        record.handle = handle
        record.raw_evidence = evidence
        record.provider_result = provider_result
        self.record_store.save_record(record)
        return handle

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self.record_store.get_record(handle.execution_id)
        if record.result is not None:
            return record.result
        if (
            record.cancellation is not None
            and record.cancellation.outcome is CancellationOutcome.CANCELLED
        ):
            record.result = ExecutionReconciler.non_success(
                record,
                ExecutionOutcome.CANCELLED,
                provider_receipt_ref=record.cancellation.provider_cancellation_receipt_ref,
            )
            self.record_store.save_record(record)
            return record.result
        provider_result = record.provider_result
        if provider_result is None:
            raise ValueError("remote execution record has no Provider v2 result")
        if provider_result.outcome in {"unknown", "ambiguous"} and handle.provider_request_id:
            if self.capability_profile.supports_query:
                provider_result = self.provider_adapter.query_v2(
                    ProviderQueryRequest(
                        provider_request_id=handle.provider_request_id,
                        stable_idempotency_key=record.request.stable_idempotency_key,
                        trace_id=record.request.trace_id,
                        correlation_id=record.request.correlation_id,
                    )
                )
                record.provider_result = provider_result
                record.raw_evidence = dict(provider_result.evidence)
        provider_ref = self.record_store.put_evidence(
            "provider-receipt",
            handle.execution_id,
            {
                "outcome": provider_result.outcome,
                "request_sent": provider_result.request_sent,
                "provider_request_id": handle.provider_request_id,
                "evidence": provider_result.evidence,
            },
        )
        if provider_result.outcome == "success":
            record.result = ResultValidator(self.record_store).successful_result(
                record, provider_receipt_ref=provider_ref
            )
        else:
            outcome = ExecutionReconciler.PROVIDER_OUTCOMES[provider_result.outcome]
            record.result = ExecutionReconciler.non_success(
                record, outcome, provider_receipt_ref=provider_ref
            )
        self.record_store.save_record(record)
        return record.result

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        requested_at = _utc_now()
        if not self.capability_profile.supports_cancel or not handle.provider_request_id:
            return ExecutionCancellationResult(
                execution_id=handle.execution_id,
                operation_id=handle.operation_id,
                attempt_id=handle.attempt_id,
                fencing_token=handle.fencing_token,
                backend_id=self.backend_id,
                transport=handle.transport,
                outcome=CancellationOutcome.UNSUPPORTED,
                local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
                upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
                local_execution_receipt_id=None,
                provider_request_id=handle.provider_request_id,
                provider_cancellation_receipt_ref=None,
                reason=reason,
                requested_at=requested_at,
                completed_at=None,
            )
        record = self.record_store.get_record(handle.execution_id)
        result = self.provider_adapter.cancel_v2(
            ProviderCancellationRequest(
                provider_request_id=handle.provider_request_id,
                stable_idempotency_key=record.request.stable_idempotency_key,
                reason=reason,
                trace_id=record.request.trace_id,
                correlation_id=record.request.correlation_id,
            )
        )
        receipt_ref = self.record_store.put_evidence(
            "provider-cancellation",
            handle.execution_id,
            {"outcome": result.outcome, "evidence": result.evidence},
        )
        upstream = {
            "cancelled": UpstreamCancellationOutcome.CANCELLED,
            "already_completed": UpstreamCancellationOutcome.ALREADY_COMPLETED,
            "not_found": UpstreamCancellationOutcome.NOT_FOUND,
        }.get(result.outcome, UpstreamCancellationOutcome.UNKNOWN)
        outcome = {
            "cancelled": CancellationOutcome.CANCELLED,
            "already_completed": CancellationOutcome.ALREADY_COMPLETED,
            "not_found": CancellationOutcome.NOT_FOUND,
        }.get(result.outcome, CancellationOutcome.UNKNOWN)
        cancellation = ExecutionCancellationResult(
            execution_id=handle.execution_id,
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            fencing_token=handle.fencing_token,
            backend_id=self.backend_id,
            transport=handle.transport,
            outcome=outcome,
            local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
            upstream_cancellation_outcome=upstream,
            local_execution_receipt_id=None,
            provider_request_id=handle.provider_request_id,
            provider_cancellation_receipt_ref=(
                receipt_ref if upstream is UpstreamCancellationOutcome.CANCELLED else None
            ),
            reason=reason,
            requested_at=requested_at,
            completed_at=_utc_now() if outcome in {
                CancellationOutcome.CANCELLED,
                CancellationOutcome.ALREADY_COMPLETED,
            } else None,
        )
        record.cancellation = cancellation
        self.record_store.save_record(record)
        return cancellation

    def accept_callback(
        self, handle: ExecutionHandle, receipt: ProviderReceipt
    ) -> ExecutionResult:
        if not self.capability_profile.supports_callback:
            raise ValueError("remote execution route does not support callbacks")
        if receipt.provider_request_id != handle.provider_request_id:
            raise ValueError("provider callback does not match ExecutionHandle")
        record = self.record_store.get_record(handle.execution_id)
        if (
            record.cancellation is not None
            and record.cancellation.outcome is CancellationOutcome.CANCELLED
        ):
            self.record_store.put_evidence(
                "late-provider-callback",
                handle.execution_id,
                {
                    "message_id": receipt.message_id,
                    "payload_hash": receipt.payload_hash,
                    "outcome": receipt.outcome,
                    "evidence": receipt.evidence,
                },
            )
            raise ValueError("late provider callback arrived after confirmed cancellation")
        callback_identity = (receipt.payload_hash, receipt.outcome)
        existing_callback = record.callback_receipts.get(receipt.message_id)
        if existing_callback is not None and existing_callback != callback_identity:
            raise ValueError("conflicting callback receipt")
        if existing_callback is not None and record.result is not None:
            return record.result
        accept = getattr(self.provider_adapter, "accept_callback", None)
        accepted = accept(receipt) if callable(accept) else receipt
        record.callback_receipts[receipt.message_id] = callback_identity
        if record.result is not None and record.raw_evidence == dict(accepted.evidence):
            return record.result
        prior = record.provider_result
        provider_handle = prior.handle if prior is not None else None
        record.provider_result = ProviderInvocationResult(
            accepted.outcome,
            provider_handle,
            dict(accepted.evidence),
            True,
        )
        record.raw_evidence = dict(accepted.evidence)
        record.result = None
        self.record_store.save_record(record)
        return self.reconcile(handle)


class CodexCliExecutionBackend:
    backend_id = "codex-cli"

    def __init__(
        self,
        *,
        admission: AdmissionController,
        payload_resolver: ExecutionPayloadResolver,
        record_store: ExecutionRecordStore,
        supervisor: CodexProcessSupervisor,
        backend_version: str = "1.0.0",
        qualification_ref: str = "capability-probe:codex-cli:1",
    ) -> None:
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store
        self.supervisor = supervisor
        self.capability_profile = ExecutionCapabilityProfile(
            backend_id=self.backend_id,
            backend_version=backend_version,
            runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            supported_completion_modes=(CompletionMode.PROCESS_EXIT,),
            supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=False,
            supports_cost_receipt=False,
            supports_structured_output=True,
            supports_process_group_control=True,
            supports_persistent_execution_directory=True,
            supports_provider_idempotency=False,
            real_provider_validation_eligible=True,
            qualification_ref=qualification_ref,
        )

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        if not payload.command:
            raise ValueError("Codex CLI execution requires a frozen command")
        supervised = self.supervisor.run(
            ProcessLaunchRequest(
                execution_id=request.execution_id,
                command=payload.command,
                cwd=payload.working_directory,
                input_text=payload.input_text,
                timeout=ProcessTimeout(payload.timeout_seconds),
                result_filename=payload.result_filename,
                result_format="json",
                environment_overrides=payload.environment_overrides,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
            )
        )
        receipt = supervised.receipt
        group = receipt.process_group
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=receipt.receipt_id,
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            local_execution_receipt_id=receipt.receipt_id,
            local_process_id=group.pid if group else None,
            local_process_group_id=group.pgid if group else None,
            local_process_start_time=group.process_start_token if group else None,
            provider_request_id=None,
            completion_mode=CompletionMode.PROCESS_EXIT,
            query_capability=CapabilityAvailability.SUPPORTED,
            cancel_capability=CapabilityAvailability.SUPPORTED,
            callback_capability=CapabilityAvailability.UNSUPPORTED,
        )
        evidence: dict[str, Any] = {
            "output_schema_version": payload.output_schema_version,
            "transport": ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE.value,
            "local_execution_receipt_id": receipt.receipt_id,
            "provider_request_id": None,
        }
        if receipt.result_path and receipt.result_integrity is ResultIntegrity.VALID:
            parsed = json.loads(Path(receipt.result_path).read_text(encoding="utf-8"))
            evidence["result"] = parsed
        record = ExecutionRecord(
            request, handle, receipt.process_started_at, evidence,
            process_receipt=receipt,
        )
        self.record_store.put_record(record)
        return handle

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self.record_store.get_record(handle.execution_id)
        recovery = self.supervisor.recover(handle.execution_id)
        record.process_receipt = recovery.receipt
        receipt_ref = self.record_store.put_evidence(
            "process-receipt", handle.execution_id, recovery.receipt.to_dict()
        )
        if record.result is not None:
            return record.result
        if recovery.receipt.status is ProcessReceiptStatus.SUCCEEDED:
            if recovery.receipt.result_path and recovery.receipt.result_integrity is ResultIntegrity.VALID:
                record.raw_evidence["result"] = json.loads(
                    Path(recovery.receipt.result_path).read_text(encoding="utf-8")
                )
            record.result = ResultValidator(self.record_store).successful_result(
                record, process_receipt_ref=receipt_ref
            )
        else:
            outcome = ExecutionReconciler.PROCESS_OUTCOMES[recovery.receipt.status]
            record.result = ExecutionReconciler.non_success(
                record, outcome, process_receipt_ref=receipt_ref
            )
        self.record_store.save_record(record)
        return record.result

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        receipt = self.supervisor.recover(handle.execution_id).receipt
        terminal = receipt.status not in {
            ProcessReceiptStatus.STARTING,
            ProcessReceiptStatus.RUNNING,
        }
        return ExecutionCancellationResult(
            execution_id=handle.execution_id,
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            fencing_token=handle.fencing_token,
            backend_id=self.backend_id,
            transport=handle.transport,
            outcome=(
                CancellationOutcome.ALREADY_COMPLETED
                if terminal else CancellationOutcome.UNKNOWN
            ),
            local_termination_outcome=(
                LocalTerminationOutcome.ALREADY_EXITED
                if terminal else LocalTerminationOutcome.UNKNOWN
            ),
            upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
            local_execution_receipt_id=handle.local_execution_receipt_id,
            provider_request_id=None,
            provider_cancellation_receipt_ref=None,
            reason=reason,
            requested_at=_utc_now(),
            completed_at=_utc_now() if terminal else None,
        )


__all__ = [
    "CodexCliExecutionBackend",
    "ExecutionPayloadResolver",
    "ExecutionReconciler",
    "ExecutionRecord",
    "ExecutionRecordStore",
    "InMemoryExecutionRecordStore",
    "RemoteProviderExecutionBackend",
    "ResolvedExecutionPayload",
    "ResultNormalizer",
    "ResultValidator",
    "ScriptedFixtureExecutionBackend",
    "StaticExecutionPayloadResolver",
]
