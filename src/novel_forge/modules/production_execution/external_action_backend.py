"""Governed backend for non-model remote actions.

Publishing, feedback retrieval, source fetches, notifications, and webhooks use
this contract instead of pretending to be model Providers.  Records remain
evidence/projections of the existing Authority Attempt and ExternalEffect.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Mapping, Protocol

from .backends import (
    ExecutionPayloadResolver,
    ExecutionRecord,
    ExecutionRecordStore,
    ExecutionReconciler,
    ResultValidator,
    _sha256,
    _utc_now,
)
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
    UpstreamCancellationOutcome,
)
from .gateway import AdmissionController


@dataclass(frozen=True, slots=True)
class ExternalActionAdapterProfile:
    adapter_id: str
    adapter_version: str
    supports_query: bool
    supports_cancel: bool
    supports_callback: bool
    supports_idempotency: bool
    real_external_validation_eligible: bool
    fixture_protocol_only: bool
    qualification_ref: str

    def __post_init__(self) -> None:
        if not self.adapter_id or not self.adapter_version or not self.qualification_ref:
            raise ValueError("external action adapter profile is incomplete")
        if self.fixture_protocol_only and self.real_external_validation_eligible:
            raise ValueError("fixture external adapter cannot be real-validation eligible")


@dataclass(frozen=True, slots=True)
class ExternalActionRequest:
    external_effect_id: str
    stable_idempotency_key: str
    capability: str
    request_payload: Mapping[str, Any]
    request_hash: str
    timeout_seconds: int
    trace_id: str
    correlation_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class ExternalActionInvocationResult:
    outcome: str
    external_request_id: str | None
    completion_mode: str
    evidence: Mapping[str, Any]
    request_sent: bool

    def __post_init__(self) -> None:
        if self.outcome not in {
            "success",
            "retryable_failure",
            "final_failure",
            "unknown",
            "ambiguous",
            "not_found",
            "cancelled",
            "already_completed",
        }:
            raise ValueError(f"unsupported external action outcome: {self.outcome}")
        if self.request_sent and not self.external_request_id:
            raise ValueError("sent external action requires a request identity")


@dataclass(frozen=True, slots=True)
class ExternalActionCallbackReceipt:
    message_id: str
    external_request_id: str
    payload_hash: str
    outcome: str
    evidence: Mapping[str, Any]
    verified: bool

    def __post_init__(self) -> None:
        if not all(
            (
                self.message_id,
                self.external_request_id,
                self.payload_hash,
                self.outcome,
            )
        ):
            raise ValueError("external callback identity is incomplete")
        normalized_hash = self.payload_hash.removeprefix("sha256:")
        if len(normalized_hash) != 64 or any(
            character not in "0123456789abcdef"
            for character in normalized_hash.lower()
        ):
            raise ValueError("external callback payload hash is invalid")
        if not self.verified:
            raise ValueError("external callback must be verified before acceptance")


class ExternalActionAdapter(Protocol):
    capability_profile: ExternalActionAdapterProfile

    def submit(
        self, request: ExternalActionRequest
    ) -> ExternalActionInvocationResult: ...

    def query(
        self, request: ExternalActionRequest, external_request_id: str
    ) -> ExternalActionInvocationResult: ...

    def cancel(
        self,
        request: ExternalActionRequest,
        external_request_id: str,
        reason: str,
    ) -> ExternalActionInvocationResult: ...

    def accept_callback(
        self, receipt: ExternalActionCallbackReceipt
    ) -> ExternalActionInvocationResult: ...


class ScriptedExternalActionAdapter:
    """Deterministic protocol fixture; never production-qualified."""

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.submit_calls = 0
        self._results: dict[str, ExternalActionInvocationResult] = {}
        self._lock = Lock()
        self.capability_profile = ExternalActionAdapterProfile(
            adapter_id="scripted-external-action",
            adapter_version="1.0.0",
            supports_query=True,
            supports_cancel=True,
            supports_callback=True,
            supports_idempotency=True,
            real_external_validation_eligible=False,
            fixture_protocol_only=True,
            qualification_ref="capability-probe:scripted-external-action:1",
        )

    @staticmethod
    def _evidence(**extra: Any) -> dict[str, Any]:
        return {
            "result": {"external_action": "fixture", **extra},
            "fixture_protocol_only": True,
            "real_model_call": False,
            "production_verified": False,
        }

    def submit(
        self, request: ExternalActionRequest
    ) -> ExternalActionInvocationResult:
        with self._lock:
            existing = self._results.get(request.stable_idempotency_key)
            if existing is not None:
                return existing
            self.submit_calls += 1
            external_request_id = (
                f"fixture-external:{request.stable_idempotency_key}"
            )
            if self.scenario == "unknown":
                outcome = "unknown"
                completion_mode = "poll"
            elif self.scenario == "final_failure":
                outcome = "final_failure"
                completion_mode = "synchronous"
            else:
                outcome = "success"
                completion_mode = "synchronous"
            result = ExternalActionInvocationResult(
                outcome=outcome,
                external_request_id=external_request_id,
                completion_mode=completion_mode,
                evidence=self._evidence(outcome=outcome),
                request_sent=True,
            )
            self._results[request.stable_idempotency_key] = result
            return result

    def query(
        self, request: ExternalActionRequest, external_request_id: str
    ) -> ExternalActionInvocationResult:
        del external_request_id
        with self._lock:
            current = self._results.get(request.stable_idempotency_key)
            if current is None:
                return ExternalActionInvocationResult(
                    "not_found",
                    None,
                    "poll",
                    self._evidence(found=False),
                    False,
                )
            if current.outcome in {"unknown", "ambiguous"}:
                current = ExternalActionInvocationResult(
                    "success",
                    current.external_request_id,
                    "synchronous",
                    self._evidence(reconciled=True),
                    True,
                )
                self._results[request.stable_idempotency_key] = current
            return current

    def cancel(
        self,
        request: ExternalActionRequest,
        external_request_id: str,
        reason: str,
    ) -> ExternalActionInvocationResult:
        with self._lock:
            self._results[request.stable_idempotency_key] = (
                ExternalActionInvocationResult(
                    "cancelled",
                    external_request_id,
                    "synchronous",
                    self._evidence(cancelled=True, reason=reason),
                    True,
                )
            )
            return self._results[request.stable_idempotency_key]

    def accept_callback(
        self, receipt: ExternalActionCallbackReceipt
    ) -> ExternalActionInvocationResult:
        evidence = dict(receipt.evidence)
        evidence["fixture_protocol_only"] = True
        evidence["real_model_call"] = False
        evidence["production_verified"] = False
        return ExternalActionInvocationResult(
            receipt.outcome,
            receipt.external_request_id,
            "callback",
            evidence,
            True,
        )


class RemoteExternalActionBackend:
    backend_id = "remote-external-action"

    def __init__(
        self,
        *,
        adapter: ExternalActionAdapter,
        admission: AdmissionController,
        payload_resolver: ExecutionPayloadResolver,
        record_store: ExecutionRecordStore,
        backend_version: str = "1.0.0",
    ) -> None:
        profile = adapter.capability_profile
        if (
            profile.fixture_protocol_only
            and admission.environment in {"validation", "provider-validation", "production"}
        ):
            raise ValueError(
                "fixture external action adapter is prohibited in a controlled environment"
            )
        self.adapter = adapter
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store
        self.capability_profile = ExecutionCapabilityProfile(
            backend_id=self.backend_id,
            backend_version=backend_version,
            runtime_class=ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
            supported_completion_modes=(
                CompletionMode.SYNCHRONOUS,
                CompletionMode.POLL,
                CompletionMode.CALLBACK,
            ),
            supported_reasoning_efforts=("none",),
            supports_query=profile.supports_query,
            supports_cancel=profile.supports_cancel,
            supports_callback=profile.supports_callback,
            supports_usage_receipt=False,
            supports_cost_receipt=False,
            supports_structured_output=True,
            supports_process_group_control=False,
            supports_persistent_execution_directory=False,
            supports_provider_idempotency=profile.supports_idempotency,
            real_provider_validation_eligible=profile.real_external_validation_eligible,
            qualification_ref=profile.qualification_ref,
        )

    def _qualified_evidence(
        self, evidence: Mapping[str, Any]
    ) -> dict[str, Any]:
        qualified = dict(evidence)
        if self.adapter.capability_profile.fixture_protocol_only:
            qualified["fixture_protocol_only"] = True
            qualified["real_model_call"] = False
            qualified["production_verified"] = False
        return qualified

    def _adapter_request(
        self, record: ExecutionRecord
    ) -> ExternalActionRequest:
        payload = record.raw_evidence.get("request_payload")
        if not isinstance(payload, Mapping):
            raise ValueError("external action request payload is unavailable")
        return ExternalActionRequest(
            external_effect_id=record.request.external_effect_id,
            stable_idempotency_key=record.request.stable_idempotency_key,
            capability=record.request.capability,
            request_payload=dict(payload),
            request_hash=_sha256(dict(payload)),
            timeout_seconds=int(record.raw_evidence["timeout_seconds"]),
            trace_id=record.request.trace_id,
            correlation_id=record.request.correlation_id,
            operation_id=record.request.operation_id,
            attempt_id=record.request.attempt_id,
            fencing_token=record.request.fencing_token,
        )

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        provisional = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=f"external-invoking:{request.execution_id}",
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id=None,
            completion_mode=CompletionMode.POLL,
            query_capability=self._availability(
                self.capability_profile.supports_query
            ),
            cancel_capability=self._availability(
                self.capability_profile.supports_cancel
            ),
            callback_capability=self._availability(
                self.capability_profile.supports_callback
            ),
        )
        record = ExecutionRecord(
            request=request,
            handle=provisional,
            started_at=_utc_now(),
            raw_evidence={
                "submission_phase": "EXTERNAL_ACTION_INVOKING",
                "manual_resolution_required_on_restart": True,
                "request_payload": dict(payload.request_payload),
                "timeout_seconds": payload.timeout_seconds,
                "output_schema_version": payload.output_schema_version,
            },
        )
        self.record_store.put_record(record)
        try:
            invocation = self.adapter.submit(self._adapter_request(record))
        except Exception:
            record.raw_evidence["submission_phase"] = "EXTERNAL_ACTION_OUTCOME_UNKNOWN"
            self.record_store.save_record(record)
            raise
        if invocation.request_sent and not invocation.external_request_id:
            raise ValueError("external action adapter omitted request identity")
        completion_mode = {
            "synchronous": CompletionMode.SYNCHRONOUS,
            "poll": CompletionMode.POLL,
            "callback": CompletionMode.CALLBACK,
        }.get(invocation.completion_mode, CompletionMode.POLL)
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=(
                invocation.external_request_id
                or f"external-unsent:{request.execution_id}"
            ),
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id=None,
            completion_mode=completion_mode,
            query_capability=provisional.query_capability,
            cancel_capability=provisional.cancel_capability,
            callback_capability=provisional.callback_capability,
            external_request_id=invocation.external_request_id,
        )
        record.handle = handle
        record.raw_evidence = {
            **self._qualified_evidence(invocation.evidence),
            "submission_phase": "EXTERNAL_ACTION_RESULT_RECORDED",
            "output_schema_version": payload.output_schema_version,
            "request_payload": dict(payload.request_payload),
            "timeout_seconds": payload.timeout_seconds,
        }
        record.external_result = invocation
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
                external_receipt_ref=(
                    record.cancellation.external_cancellation_receipt_ref
                ),
            )
            self.record_store.save_record(record)
            return record.result
        invocation = record.external_result
        if invocation is None:
            raise ValueError("external action outcome is UNKNOWN; reconcile manually")
        if invocation.outcome in {"unknown", "ambiguous"}:
            if (
                not self.capability_profile.supports_query
                or not handle.external_request_id
            ):
                record.result = ExecutionReconciler.non_success(
                    record, ExecutionOutcome.UNKNOWN
                )
                self.record_store.save_record(record)
                return record.result
            invocation = self.adapter.query(
                self._adapter_request(record), handle.external_request_id
            )
            record.external_result = invocation
            record.raw_evidence = {
                **record.raw_evidence,
                **self._qualified_evidence(invocation.evidence),
                "submission_phase": "EXTERNAL_ACTION_RECONCILED",
            }
        receipt_ref = self.record_store.put_evidence(
            "external-action-receipt",
            handle.execution_id,
            {
                "outcome": invocation.outcome,
                "request_sent": invocation.request_sent,
                "external_request_id": invocation.external_request_id,
                "evidence": self._qualified_evidence(invocation.evidence),
            },
        )
        if invocation.outcome == "success":
            record.result = ResultValidator(self.record_store).successful_result(
                record, external_receipt_ref=receipt_ref
            )
        else:
            outcome = {
                "retryable_failure": ExecutionOutcome.RETRYABLE_FAILURE,
                "final_failure": ExecutionOutcome.FINAL_FAILURE,
                "not_found": ExecutionOutcome.UNKNOWN,
                "unknown": ExecutionOutcome.UNKNOWN,
                "ambiguous": ExecutionOutcome.UNKNOWN,
                "cancelled": ExecutionOutcome.CANCELLED,
                "already_completed": ExecutionOutcome.UNKNOWN,
            }[invocation.outcome]
            record.result = ExecutionReconciler.non_success(
                record, outcome, external_receipt_ref=receipt_ref
            )
        self.record_store.save_record(record)
        return record.result

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        requested_at = _utc_now()
        record = self.record_store.get_record(handle.execution_id)
        if (
            not self.capability_profile.supports_cancel
            or not handle.external_request_id
        ):
            return ExecutionCancellationResult(
                execution_id=handle.execution_id,
                operation_id=handle.operation_id,
                attempt_id=handle.attempt_id,
                fencing_token=handle.fencing_token,
                backend_id=self.backend_id,
                transport=handle.transport,
                outcome=CancellationOutcome.UNSUPPORTED,
                local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
                upstream_cancellation_outcome=(
                    UpstreamCancellationOutcome.UNSUPPORTED
                    if handle.external_request_id
                    else UpstreamCancellationOutcome.NOT_APPLICABLE
                ),
                local_execution_receipt_id=None,
                provider_request_id=None,
                provider_cancellation_receipt_ref=None,
                reason=reason,
                requested_at=requested_at,
                completed_at=None,
                external_request_id=handle.external_request_id,
            )
        invocation = self.adapter.cancel(
            self._adapter_request(record),
            handle.external_request_id,
            reason,
        )
        receipt_ref = self.record_store.put_evidence(
            "external-action-cancellation",
            handle.execution_id,
            {
                "outcome": invocation.outcome,
                "external_request_id": invocation.external_request_id,
                "evidence": self._qualified_evidence(invocation.evidence),
            },
        )
        upstream = {
            "cancelled": UpstreamCancellationOutcome.CANCELLED,
            "already_completed": UpstreamCancellationOutcome.ALREADY_COMPLETED,
            "not_found": UpstreamCancellationOutcome.NOT_FOUND,
        }.get(invocation.outcome, UpstreamCancellationOutcome.UNKNOWN)
        outcome = {
            "cancelled": CancellationOutcome.CANCELLED,
            "already_completed": CancellationOutcome.ALREADY_COMPLETED,
            "not_found": CancellationOutcome.NOT_FOUND,
        }.get(invocation.outcome, CancellationOutcome.UNKNOWN)
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
            provider_request_id=None,
            provider_cancellation_receipt_ref=None,
            reason=reason,
            requested_at=requested_at,
            completed_at=(
                _utc_now()
                if outcome
                in {
                    CancellationOutcome.CANCELLED,
                    CancellationOutcome.ALREADY_COMPLETED,
                }
                else None
            ),
            external_request_id=handle.external_request_id,
            external_cancellation_receipt_ref=receipt_ref,
        )
        record.cancellation = cancellation
        record.external_result = invocation
        self.record_store.save_record(record)
        return cancellation

    def accept_callback(
        self,
        handle: ExecutionHandle,
        receipt: ExternalActionCallbackReceipt,
    ) -> ExecutionResult:
        if not self.capability_profile.supports_callback:
            raise ValueError("external action route does not support callbacks")
        if receipt.external_request_id != handle.external_request_id:
            raise ValueError("external callback does not match ExecutionHandle")
        record = self.record_store.get_record(handle.execution_id)
        if (
            record.cancellation is not None
            and record.cancellation.outcome is CancellationOutcome.CANCELLED
        ):
            self.record_store.put_evidence(
                "late-external-callback",
                handle.execution_id,
                {
                    "message_id": receipt.message_id,
                    "payload_hash": receipt.payload_hash,
                    "outcome": receipt.outcome,
                },
            )
            raise ValueError("late external callback arrived after confirmed cancellation")
        identity = (receipt.payload_hash, receipt.outcome)
        existing = record.callback_receipts.get(receipt.message_id)
        if existing is not None and existing != identity:
            raise ValueError("conflicting external callback receipt")
        if existing is not None and record.result is not None:
            return record.result
        invocation = self.adapter.accept_callback(receipt)
        record.callback_receipts[receipt.message_id] = identity
        record.external_result = invocation
        record.raw_evidence = {
            **record.raw_evidence,
            **self._qualified_evidence(invocation.evidence),
            "submission_phase": "EXTERNAL_CALLBACK_ACCEPTED",
        }
        record.result = None
        self.record_store.save_record(record)
        return self.reconcile(handle)

    @staticmethod
    def _availability(supported: bool) -> CapabilityAvailability:
        return (
            CapabilityAvailability.SUPPORTED
            if supported
            else CapabilityAvailability.UNSUPPORTED
        )


__all__ = [
    "ExternalActionAdapter",
    "ExternalActionAdapterProfile",
    "ExternalActionCallbackReceipt",
    "ExternalActionInvocationResult",
    "ExternalActionRequest",
    "RemoteExternalActionBackend",
    "ScriptedExternalActionAdapter",
]
