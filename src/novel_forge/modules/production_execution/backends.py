from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
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
    ExecutionRecoveryAuthorization,
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
from .evidence import ExecutionRecord, ExecutionRecordStore
from .process_supervisor import (
    CodexProcessSupervisor,
    EnvironmentAllowlist,
    ProcessLaunchRequest,
    ProcessReceiptStatus,
    ProcessTimeout,
    ResultIntegrity,
)
from .security import assert_no_inline_secrets
from .codex_configuration import (
    CODEX_INPUT_ONLY_OVERRIDES, CODEX_SCHEMA_PROJECTION_VERSION,
    codex_output_schema, codex_retry_overrides, require_codex_home,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256(payload: Mapping[str, Any]) -> str:
    return (
        "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    )


def _freeze_output_contract(
    request: ExecutionRequest, payload: ResolvedExecutionPayload, request_hash: str,
) -> dict[str, Any]:
    body = {
        "schema_version": "provider-frozen-output-contract.v1",
        "output_schema": json.loads(_canonical_json(payload.output_schema or {})),
        "output_schema_version": payload.output_schema_version,
        "request_hash": request_hash,
        "execution_request_hash": request.contract_hash,
    }
    return {**body, "contract_hash": _sha256(body)}
def observe_codex_cli_version(
    executable: str | Path,
    *,
    working_directory: str | Path,
    timeout_seconds: int = 15,
) -> str:
    executable_path = Path(executable)
    workspace = Path(working_directory)
    if not executable_path.is_absolute() or not executable_path.is_file():
        raise RuntimeError("controlled Codex executable is unavailable")
    if not workspace.is_dir() or timeout_seconds <= 0:
        raise RuntimeError("controlled Codex identity probe is invalid")
    try:
        completed = subprocess.run(
            (str(executable_path), "--version"),
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=EnvironmentAllowlist.codex_default().build(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "controlled Codex CLI version could not be observed"
        ) from exc
    observed = completed.stdout.strip()
    if not observed:
        raise RuntimeError("controlled Codex CLI version could not be observed")
    return observed


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
    output_schema: Mapping[str, Any] | None = None
    capability_evidence: Mapping[str, Any] | None = None
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request_payload, Mapping):
            raise ValueError("resolved execution request payload must be an object")
        if not self.working_directory or self.timeout_seconds <= 0:
            raise ValueError(
                "resolved execution payload requires workspace and timeout"
            )
        if not self.output_schema_version:
            raise ValueError(
                "resolved execution payload requires an output schema version"
            )
        object.__setattr__(
            self, "allowed_tools", tuple(str(item) for item in self.allowed_tools)
        )
        object.__setattr__(
            self, "denied_tools", tuple(str(item) for item in self.denied_tools)
        )
        if self.output_schema is not None and not isinstance(
            self.output_schema, Mapping
        ):
            raise ValueError("resolved execution output schema must be an object")
        assert_no_inline_secrets(
            {
                "request_payload": self.request_payload,
                "input_text": self.input_text,
                "command": self.command,
                "environment_overrides": self.environment_overrides or {},
                "output_schema": self.output_schema or {},
                "capability_evidence": self.capability_evidence or {},
            },
            label="ResolvedExecutionPayload",
        )


@dataclass(frozen=True, slots=True)
class CodexPricingSnapshot:
    model_id: str
    pricing_ref: str
    currency: str
    input_per_million: str
    cached_input_per_million: str
    output_per_million: str

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.model_id,
                self.pricing_ref,
                self.currency,
                self.input_per_million,
                self.cached_input_per_million,
                self.output_per_million,
            )
        ):
            raise ValueError("Codex pricing snapshot is incomplete")
        for value in (
            self.input_per_million,
            self.cached_input_per_million,
            self.output_per_million,
        ):
            try:
                rate = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("Codex pricing rate must be decimal") from exc
            if rate < 0:
                raise ValueError("Codex pricing rate cannot be negative")

    @property
    def snapshot_hash(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "pricing_ref": self.pricing_ref,
            "currency": self.currency,
            "input_per_million": self.input_per_million,
            "cached_input_per_million": self.cached_input_per_million,
            "output_per_million": self.output_per_million,
        }


@dataclass(frozen=True, slots=True)
class CodexAccountEntitlementSnapshot:
    authorization_ref: str
    account_identity_ref: str
    cli_version: str
    executable_sha256: str
    configuration_ref: str

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.authorization_ref,
                self.account_identity_ref,
                self.cli_version,
                self.executable_sha256,
                self.configuration_ref,
            )
        ):
            raise ValueError("Codex account entitlement snapshot is incomplete")
        if len(self.executable_sha256) != 71 or not self.executable_sha256.startswith(
            "sha256:"
        ):
            raise ValueError("Codex executable digest must be SHA-256")

    @property
    def snapshot_hash(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "authorization_ref": self.authorization_ref,
            "account_identity_ref": self.account_identity_ref,
            "cli_version": self.cli_version,
            "executable_sha256": self.executable_sha256,
            "configuration_ref": self.configuration_ref,
        }


class CodexStructuredResultValidator(Protocol):
    def __call__(
        self,
        stage: str,
        output_schema: Mapping[str, Any],
        value: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


def _validate_frozen_structured_result(
    validator: CodexStructuredResultValidator,
    stage: str,
    schema: Mapping[str, Any],
    value: Mapping[str, Any],
    schema_ref: str,
) -> Mapping[str, Any]:
    if "output_schema_ref" in inspect.signature(validator).parameters:
        return validator(stage, schema, value, output_schema_ref=schema_ref)
    return validator(stage, schema, value)


_CODEX_TOOL_ITEM_TYPES = {
    "command_execution",
    "mcp_tool_call",
    "file_change",
    "web_search",
}


def parse_codex_jsonl_evidence(
    stdout: str,
    *,
    model_id: str,
    pricing: CodexPricingSnapshot | None = None,
    account_entitlement: CodexAccountEntitlementSnapshot | None = None,
    allowed_tools: tuple[str, ...],
    denied_tools: tuple[str, ...] = (),
) -> dict[str, Any]:

    events: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Codex JSONL at line {line_number}") from exc
        if not isinstance(event, Mapping):
            raise ValueError(f"Codex JSONL line {line_number} is not an object")
        events.append(event)
    terminal = next(
        (event for event in reversed(events) if event.get("type") == "turn.completed"),
        None,
    )
    usage = terminal.get("usage") if isinstance(terminal, Mapping) else None
    if not isinstance(usage, Mapping):
        raise ValueError("Codex JSONL has no terminal measured usage")

    def token(name: str) -> int:
        value = usage.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Codex usage {name} must be a non-negative integer")
        return value

    input_tokens = token("input_tokens")
    cached_input_tokens = token("cached_input_tokens")
    output_tokens = token("output_tokens")
    reasoning_output_tokens = token("reasoning_output_tokens")
    if cached_input_tokens > input_tokens:
        raise ValueError("Codex cached input tokens exceed total input tokens")
    if (pricing is None) == (account_entitlement is None):
        raise ValueError(
            "Codex evidence requires exactly one pricing or account entitlement basis"
        )
    uncached_input_tokens = input_tokens - cached_input_tokens
    if pricing is not None:
        if pricing.model_id != model_id:
            raise ValueError(
                "Codex pricing snapshot model differs from execution model"
            )
        million = Decimal(1_000_000)
        amount = (
            Decimal(uncached_input_tokens) * Decimal(pricing.input_per_million)
            + Decimal(cached_input_tokens) * Decimal(pricing.cached_input_per_million)
            + Decimal(output_tokens) * Decimal(pricing.output_per_million)
        ) / million
    invocations: list[dict[str, Any]] = [
        {
            "tool_ref": "model.provider.invoke",
            "event": "provider_execution",
            "call_id": "",
            "status": "completed",
        }
    ]
    for event in events:
        if event.get("type") not in {"item.started", "item.completed"}:
            continue
        item = event.get("item")
        item_type = str(item.get("type") or "") if isinstance(item, Mapping) else ""
        if item_type not in _CODEX_TOOL_ITEM_TYPES:
            continue
        invocations.append(
            {
                "tool_ref": f"codex.{item_type}",
                "event": str(event.get("type") or ""),
                "call_id": str(item.get("id") or "")
                if isinstance(item, Mapping)
                else "",
                "status": str(item.get("status") or "")
                if isinstance(item, Mapping)
                else "",
            }
        )
    invoked = tuple(sorted({item["tool_ref"] for item in invocations}))
    allowed = tuple(sorted(set(allowed_tools)))
    denied = tuple(sorted(set(denied_tools)))
    if set(allowed) & set(denied):
        raise ValueError("Codex Tool policy allows and denies the same Tool")
    unauthorized = tuple(item for item in invoked if item not in allowed)
    cost = (
        {
            "availability": "AVAILABLE",
            "measurement": "ESTIMATED",
            "model": model_id,
            "amount": format(amount, "f"),
            "currency": pricing.currency,
            "pricing_ref": pricing.pricing_ref,
            "pricing_snapshot_hash": pricing.snapshot_hash,
            "pricing_snapshot": pricing.to_dict(),
            "calculation_basis": {
                "formula": (
                    "((input_tokens-cached_input_tokens)*input_rate+"
                    "cached_input_tokens*cached_rate+output_tokens*output_rate)/1000000"
                ),
                "uncached_input_tokens": uncached_input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
            },
            "estimated": True,
            "provider_billed": False,
        }
        if pricing is not None
        else {
            "availability": "UNAVAILABLE",
            "measurement": "UNKNOWN",
            "model": model_id,
            "currency": "UNKNOWN",
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "reason": "monetary_cost_not_observable",
            "authorization_ref": account_entitlement.authorization_ref,
            "entitlement_snapshot_hash": account_entitlement.snapshot_hash,
            "entitlement_snapshot": account_entitlement.to_dict(),
            "provider_billed": "UNKNOWN",
        }
    )
    return {
        "usage": {
            "availability": "AVAILABLE",
            "measurement": "MEASURED",
            "model": model_id,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "uncached_input_tokens": uncached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "cost": cost,
        "tools": {
            "policy": "DEFAULT_DENY",
            "allowed": list(allowed),
            "denied": list(denied),
            "invoked": list(invoked),
            "invocations": invocations,
        },
        "unauthorized_tools": list(unauthorized),
        "terminal_event_observed": True,
        "event_count": len(events),
    }


@dataclass(frozen=True, slots=True)
class LocalProcessExecutionPolicy:
    fixed_working_directory: str
    allowed_command_prefixes: tuple[tuple[str, ...], ...]
    maximum_result_bytes: int

    def __post_init__(self) -> None:
        fixed = str(Path(self.fixed_working_directory).expanduser().resolve())
        prefixes = tuple(
            tuple(str(token) for token in prefix)
            for prefix in self.allowed_command_prefixes
        )
        if (
            not fixed
            or not prefixes
            or any(not prefix for prefix in prefixes)
            or self.maximum_result_bytes <= 0
        ):
            raise ValueError("local process execution policy is incomplete")
        object.__setattr__(self, "fixed_working_directory", fixed)
        object.__setattr__(self, "allowed_command_prefixes", prefixes)

    def assert_payload(self, payload: ResolvedExecutionPayload) -> None:
        working_directory = str(Path(payload.working_directory).expanduser().resolve())
        if working_directory != self.fixed_working_directory:
            raise ValueError("local process working directory is not fixed by policy")
        command = tuple(payload.command)
        if not any(
            command[: len(prefix)] == prefix for prefix in self.allowed_command_prefixes
        ):
            raise ValueError("local process command is not allowlisted")

    def assert_result(self, result_path: str) -> None:
        candidate = Path(result_path)
        if candidate.stat().st_size > self.maximum_result_bytes:
            raise ValueError("local process result exceeds policy size limit")


class ExecutionPayloadResolver(Protocol):
    def resolve(
        self, request: ExecutionRequest, admission: ExecutionAdmission
    ) -> ResolvedExecutionPayload: ...


class StaticExecutionPayloadResolver:
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


class InMemoryExecutionRecordStore:
    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}
        self._evidence: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def put_record(self, record: ExecutionRecord) -> None:
        self._assert_record_safe(record)
        with self._lock:
            existing = self._records.get(record.request.execution_id)
            if existing is not None:
                if existing.request.contract_hash != record.request.contract_hash:
                    raise ValueError("duplicate execution ID has a different request")
                return
            self._records[record.request.execution_id] = record

    def save_record(self, record: ExecutionRecord) -> None:
        self._assert_record_safe(record)
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
            raise ValueError(
                f"execution record is not available: {execution_id}"
            ) from exc

    def find_record(self, execution_id: str) -> ExecutionRecord | None:
        return self._records.get(execution_id)

    def put_evidence(
        self, kind: str, execution_id: str, payload: Mapping[str, Any]
    ) -> str:
        assert_no_inline_secrets(payload, label=f"execution evidence {kind}")
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

    @staticmethod
    def _assert_record_safe(record: ExecutionRecord) -> None:
        assert_no_inline_secrets(
            {
                "request": record.request.to_dict(),
                "raw_evidence": record.raw_evidence,
            },
            label="execution recovery record",
        )


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
        external_receipt_ref: str | None = None,
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
            stdout_ref=(
                record.process_receipt.stdout_path if record.process_receipt else None
            ),
            stderr_ref=(
                record.process_receipt.stderr_path if record.process_receipt else None
            ),
            output_hash=_sha256(normalized),
            schema_version=str(
                record.raw_evidence.get("output_schema_version")
                or "structured-output.v1"
            ),
            files=(),
        )
        output_manifest_ref = self.store.put_evidence(
            "output-manifest", request.execution_id, output_manifest.to_dict()
        )
        base_checks = (
            ValidationCheck("structured_object", "PASSED", normalized_ref),
            ValidationCheck(
                "fencing",
                "PASSED",
                f"authority-attempt:{request.attempt_id}:fence:{request.fencing_token}",
            ),
            ValidationCheck("route_snapshot", "PASSED", request.route_snapshot_id),
        )
        extra_evidence = record.raw_evidence.get("validation_checks")
        extra_checks = (
            tuple(
                ValidationCheck(str(kind), "PASSED", str(evidence_ref))
                for kind, evidence_ref in sorted(extra_evidence.items())
            )
            if isinstance(extra_evidence, Mapping)
            else ()
        )
        checks = (*base_checks, *extra_checks)
        required_check_kinds = tuple(item.check_kind for item in checks)
        validation = ValidationManifest(
            manifest_id=f"validation-manifest:{request.execution_id}",
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            output_manifest_ref=output_manifest_ref,
            validation_policy_ref=request.validation_policy_ref,
            required_check_kinds=required_check_kinds,
            checks=checks,
            decision="ACCEPTED",
        )
        validation_ref = self.store.put_evidence(
            "validation-manifest", request.execution_id, validation.to_dict()
        )
        usage = record.raw_evidence.get("usage")
        usage_receipt = (
            dict(usage)
            if isinstance(usage, Mapping)
            else {
                "availability": "UNAVAILABLE",
                "reason": "backend_did_not_report_usage",
                "backend_id": record.handle.backend_id,
            }
        )
        usage_ref = self.store.put_evidence(
            "usage-receipt", request.execution_id, usage_receipt
        )
        cost = record.raw_evidence.get("cost")
        if isinstance(cost, Mapping):
            availability = str(cost.get("availability") or "").upper()
            if availability == "UNAVAILABLE":
                currency = str(cost.get("currency") or "").upper()
                if (
                    str(cost.get("measurement") or "").upper() != "UNKNOWN"
                    or not str(cost.get("reason") or "").strip()
                    or "amount" in cost
                    or ("currency" in cost and currency != "UNKNOWN")
                ):
                    raise ValueError("unknown execution cost receipt is invalid")
            else:
                try:
                    amount = Decimal(str(cost.get("amount") or "0"))
                except InvalidOperation as exc:
                    raise ValueError(
                        "execution cost receipt amount is invalid"
                    ) from exc
                if amount < 0 or not str(cost.get("currency") or ""):
                    raise ValueError("execution cost receipt is invalid")
            cost_receipt = dict(cost)
        else:
            cost_receipt = {
                "availability": "UNAVAILABLE",
                "reason": "backend_did_not_report_cost",
                "backend_id": record.handle.backend_id,
            }
        cost_ref = self.store.put_evidence(
            "cost-receipt", request.execution_id, cost_receipt
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
            external_receipt_ref=external_receipt_ref,
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
        external_receipt_ref: str | None = None,
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
            external_receipt_ref=external_receipt_ref,
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
            supported_completion_modes=(
                CompletionMode.SYNCHRONOUS,
                CompletionMode.POLL,
            ),
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
        return self._submit(request, admission)

    def submit_recovered(
        self,
        request: ExecutionRequest,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionHandle:
        admission = self.admission.admit_recovery(
            request,
            self.capability_profile,
            authorization,
        )
        return self._submit(request, admission)

    def _submit(
        self,
        request: ExecutionRequest,
        admission: ExecutionAdmission,
    ) -> ExecutionHandle:
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        evidence = dict(payload.request_payload)
        evidence["fixture_protocol_only"] = True
        evidence["real_model_call"] = False
        evidence["production_verified"] = False
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
        record = self.record_store.get_record(handle.execution_id)
        completion_ref = self.record_store.put_evidence(
            "fixture-completion-receipt",
            handle.execution_id,
            {
                "backend_execution_id": handle.backend_execution_id,
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            },
        )
        cancellation = ExecutionCancellationResult(
            execution_id=handle.execution_id,
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            fencing_token=handle.fencing_token,
            backend_id=self.backend_id,
            transport=handle.transport,
            outcome=CancellationOutcome.ALREADY_COMPLETED,
            local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
            upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
            local_execution_receipt_id=None,
            provider_request_id=None,
            provider_cancellation_receipt_ref=None,
            reason=reason,
            requested_at=_utc_now(),
            completed_at=_utc_now(),
            backend_completion_receipt_ref=completion_ref,
        )
        record.cancellation = cancellation
        self.record_store.save_record(record)
        return cancellation


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
        structured_result_validator: Any = None,
    ) -> None:
        if capability_profile.backend_id != backend_id:
            raise ValueError("remote backend capability identity mismatch")
        if (
            capability_profile.runtime_class
            is not ExecutionRuntimeClass.REMOTE_PROVIDER_API
        ):
            raise ValueError("remote backend requires REMOTE_PROVIDER_API capability")
        provider_profile = provider_adapter.capability_profile
        if provider_profile.control_level is not ProviderControlLevel.V2_CONTROLLED:
            raise ValueError(
                "RemoteProviderExecutionBackend requires a V2_CONTROLLED adapter"
            )
        capability_pairs = (
            (
                capability_profile.supports_query,
                provider_profile.supports_query,
                "query",
            ),
            (
                capability_profile.supports_cancel,
                provider_profile.supports_cancel,
                "cancel",
            ),
            (
                capability_profile.supports_callback,
                provider_profile.supports_callback,
                "callback",
            ),
            (
                capability_profile.supports_usage_receipt,
                provider_profile.supports_usage_receipt,
                "usage receipt",
            ),
            (
                capability_profile.supports_cost_receipt,
                provider_profile.supports_cost_receipt,
                "cost receipt",
            ),
            (
                capability_profile.supports_provider_idempotency,
                provider_profile.supports_provider_idempotency,
                "provider idempotency",
            ),
        )
        missing = [
            name
            for required, actual, name in capability_pairs
            if required and not actual
        ]
        if missing:
            raise ValueError(
                "remote backend capability exceeds Provider v2 adapter: "
                + ", ".join(missing)
            )
        if capability_profile.real_provider_validation_eligible and (
            provider_profile.control_level is not ProviderControlLevel.V2_CONTROLLED
            or not provider_profile.real_provider_validation_eligible
        ):
            raise ValueError(
                "remote backend cannot elevate an unqualified provider adapter"
            )
        self.backend_id = backend_id
        self.capability_profile = capability_profile
        self.provider_adapter = provider_adapter
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store
        self.structured_result_validator = structured_result_validator
        self._callback_lock = Lock()

    def _record_provider_result(
        self, record: ExecutionRecord, result: ProviderInvocationResult,
        *, reject_conflict: bool = False,
    ) -> None:
        raw_ref = self.record_store.put_evidence(
            "provider-response", record.request.execution_id,
            {"outcome": result.outcome, "request_sent": result.request_sent,
             "evidence": dict(result.evidence)},
        )
        if not record.frozen_output_contract:
            admission = self.admission._admit_frozen_contracts(record.request, self.capability_profile)
            payload = self.payload_resolver.resolve(record.request, admission)
            from .provider_admission import ProviderRequestEnvelope
            envelope = ProviderRequestEnvelope.from_dict(payload.request_payload)
            record.frozen_output_contract = _freeze_output_contract(record.request, payload, envelope.envelope_hash)
        frozen = record.frozen_output_contract
        body = {key: value for key, value in frozen.items() if key != "contract_hash"}
        if frozen.get("contract_hash") != _sha256(body) or frozen.get("execution_request_hash") != record.request.contract_hash:
            raise ValueError("PROVIDER_FROZEN_CONTRACT_CORRUPT: reconcile the original frozen request")
        host = {key: frozen[key] for key in ("output_schema", "output_schema_version", "request_hash", "execution_request_hash")}
        host.update({"operation_id": record.request.operation_id, "attempt_id": record.request.attempt_id,
                     "fencing_token": record.request.fencing_token, "stage": record.request.stage,
                     "external_effect_id": record.request.external_effect_id,
                     "stable_idempotency_key": record.request.stable_idempotency_key,
                     "provider_request_id": record.handle.provider_request_id,
                     "provider_response_ref": raw_ref, "submission_phase": "PROVIDER_RESULT_RECORDED",
                     "callback_evidence_hashes": record.raw_evidence.get("callback_evidence_hashes", {})})
        evidence = dict(result.evidence)
        conflicts = [key for key, value in host.items() if key in evidence and evidence[key] != value]
        if "frozen_output_contract" in evidence and evidence["frozen_output_contract"] != frozen:
            conflicts.append("frozen_output_contract")
        if conflicts:
            rejection = {"code": "PROVIDER_FROZEN_CONTRACT_CONFLICT", "fields": sorted(conflicts), "provider_response_ref": raw_ref}
            self.record_store.put_evidence("provider-contract-rejection", record.request.execution_id, rejection)
            if reject_conflict:
                raise ValueError("PROVIDER_FROZEN_CONTRACT_CONFLICT: " + ", ".join(sorted(conflicts)))
            evidence.update(failure_class="SCHEMA_REJECTION", output_validation_error=rejection)
            result = replace(result, outcome="final_failure")
        record.raw_evidence = {**evidence, **host}
        record.provider_result = replace(result, evidence=record.raw_evidence)
        self.record_store.save_record(record)

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        return self._submit(request, admission)

    def submit_recovered(
        self,
        request: ExecutionRequest,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionHandle:
        admission = self.admission.admit_recovery(
            request,
            self.capability_profile,
            authorization,
        )
        return self._submit(request, admission)

    def _submit(
        self,
        request: ExecutionRequest,
        admission: ExecutionAdmission,
    ) -> ExecutionHandle:
        if admission.route_snapshot.model_provider != self.provider_adapter.provider:
            raise ValueError("RouteSnapshot provider differs from Provider v2 adapter")
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        from novel_forge.modules.production_execution.provider_admission import (
            ProviderAdmissionReceipt,
            ProviderRequestEnvelope,
            verify_provider_admission,
        )
        from novel_forge.modules.provider_control.contracts import (
            ProviderInvocationRequest,
        )

        envelope = ProviderRequestEnvelope.from_dict(payload.request_payload)
        admission_payload = (
            payload.capability_evidence.get("provider_admission")
            if isinstance(payload.capability_evidence, Mapping)
            else None
        )
        if not isinstance(admission_payload, Mapping):
            raise ValueError(
                "PROVIDER_ADMISSION_REQUIRED: remote Provider request has no frozen receipt"
            )
        admission_receipt = ProviderAdmissionReceipt.from_dict(admission_payload)
        verify_provider_admission(envelope, admission_receipt)
        if (
            envelope.provider != admission.route_snapshot.model_provider
            or envelope.model != admission.route_snapshot.model_id
            or envelope.timeout_seconds != payload.timeout_seconds
            or envelope.stable_idempotency_key != request.stable_idempotency_key
        ):
            raise ValueError("PROVIDER_REQUEST_IDENTITY_DRIFT: route envelope changed")

        provider_request = ProviderInvocationRequest(
            provider=admission.route_snapshot.model_provider,
            model=admission.route_snapshot.model_id,
            capability=request.capability,
            stage=request.stage,
            stable_idempotency_key=request.stable_idempotency_key,
            request_payload=envelope.to_dict(),
            request_hash=envelope.envelope_hash,
            timeout_seconds=payload.timeout_seconds,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            operation_id=request.operation_id,
            external_effect_id=request.external_effect_id,
            budget_reservation_id=request.budget_reservation_id,
            provider_admission=admission_receipt.to_dict(),
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
            frozen_output_contract=_freeze_output_contract(request, payload, envelope.envelope_hash),
            raw_evidence={
                "output_schema": dict(payload.output_schema or {}),
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
        if provider_handle and provider_handle.completion_mode not in {
            "synchronous",
            "sync",
        }:
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
            provider_request_id=(
                provider_handle.provider_request_id if provider_handle else None
            ),
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
        record.handle = handle
        record.provider_result = provider_result
        record.raw_evidence["submission_phase"] = "PROVIDER_RESULT_OBSERVED"
        self.record_store.save_record(record)
        self._record_provider_result(record, provider_result)
        return handle

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self.record_store.get_record(handle.execution_id)
        if record.handle.contract_hash != handle.contract_hash:
            raise ValueError("execution handle differs from its frozen recovery record")
        if record.result is not None and record.result.outcome is not ExecutionOutcome.UNKNOWN:
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
        if (
            provider_result.outcome in {"unknown", "ambiguous"}
            and handle.provider_request_id
        ):
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
                record.raw_evidence["submission_phase"] = "PROVIDER_RESULT_OBSERVED"
                self.record_store.save_record(record)
                self._record_provider_result(record, provider_result)
                provider_result = record.provider_result
        if (not record.frozen_output_contract
                or record.raw_evidence.get("submission_phase") != "PROVIDER_RESULT_RECORDED"):
            self._record_provider_result(record, provider_result)
            provider_result = record.provider_result
        if provider_result.outcome == "success" and self.structured_result_validator is not None:
            evidence = dict(record.raw_evidence)
            try:
                evidence["result"] = dict(_validate_frozen_structured_result(
                    self.structured_result_validator, record.request.stage,
                    evidence.get("output_schema") or {}, evidence.get("result"),
                    str(evidence.get("output_schema_version") or ""),
                ))
            except ValueError as exc:
                evidence["failure_class"] = "SCHEMA_REJECTION"
                evidence["output_validation_error"] = {
                    "code": getattr(exc, "code", "SCHEMA_REJECTION"),
                    "detail": str(exc)[:2048],
                }
                provider_result = replace(provider_result, outcome="final_failure", evidence=evidence)
            else:
                provider_result = replace(provider_result, evidence=evidence)
            record.raw_evidence = evidence
            record.provider_result = provider_result
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
        if (
            not self.capability_profile.supports_cancel
            or not handle.provider_request_id
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
                receipt_ref
                if upstream is UpstreamCancellationOutcome.CANCELLED
                else None
            ),
            reason=reason,
            requested_at=requested_at,
            completed_at=_utc_now()
            if outcome
            in {
                CancellationOutcome.CANCELLED,
                CancellationOutcome.ALREADY_COMPLETED,
            }
            else None,
        )
        record.cancellation = cancellation
        self.record_store.save_record(record)
        return cancellation

    def accept_callback(
        self, handle: ExecutionHandle, receipt: ProviderReceipt
    ) -> ExecutionResult:
        with self._callback_lock:
            return self._accept_callback(handle, receipt)

    def _accept_callback(
        self, handle: ExecutionHandle, receipt: ProviderReceipt,
    ) -> ExecutionResult:
        if not self.capability_profile.supports_callback:
            raise ValueError("remote execution route does not support callbacks")
        if receipt.provider_request_id != handle.provider_request_id:
            raise ValueError("provider callback does not match ExecutionHandle")
        record = self.record_store.get_record(handle.execution_id)
        if record.handle.contract_hash != handle.contract_hash:
            raise ValueError("execution handle differs from its frozen recovery record")
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
            raise ValueError(
                "late provider callback arrived after confirmed cancellation"
            )
        callback_identity = (receipt.payload_hash, receipt.outcome)
        existing_callback = record.callback_receipts.get(receipt.message_id)
        if existing_callback is not None and existing_callback != callback_identity:
            raise ValueError("conflicting callback receipt")
        evidence_hash = _sha256(dict(receipt.evidence))
        saved_hash = record.raw_evidence.get("callback_evidence_hashes", {}).get(receipt.message_id)
        if saved_hash is not None and saved_hash != evidence_hash:
            raise ValueError("conflicting callback evidence")
        if existing_callback is not None and record.result is not None:
            return record.result
        accept = getattr(self.provider_adapter, "accept_callback", None)
        accepted = accept(receipt) if callable(accept) else receipt
        if record.result is not None and record.result.outcome is not ExecutionOutcome.UNKNOWN:
            raw_ref = record.raw_evidence.get("provider_response_ref")
            original = self.record_store.read_evidence(raw_ref) if raw_ref else {}
            if original.get("outcome") != accepted.outcome or original.get("evidence") != dict(accepted.evidence):
                self.record_store.put_evidence("late-provider-callback", handle.execution_id,
                    {"message_id": receipt.message_id, "payload_hash": receipt.payload_hash,
                     "outcome": receipt.outcome, "evidence": dict(receipt.evidence)})
                raise ValueError("conflicting callback after terminal execution")
            record.callback_receipts[receipt.message_id] = callback_identity
            record.raw_evidence.setdefault("callback_evidence_hashes", {})[receipt.message_id] = evidence_hash
            self.record_store.save_record(record)
            return record.result
        prior = record.provider_result
        provider_handle = prior.handle if prior is not None else None
        provider_result = ProviderInvocationResult(
            accepted.outcome,
            provider_handle,
            dict(accepted.evidence),
            True,
        )
        self._record_provider_result(record, provider_result, reject_conflict=True)
        record.callback_receipts[receipt.message_id] = callback_identity
        record.raw_evidence.setdefault("callback_evidence_hashes", {})[receipt.message_id] = evidence_hash
        record.result = None
        self.record_store.save_record(record)
        return self.reconcile(handle)


class _CodexResultFailure(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def codex_protocol_failure(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                continue
            message = event.get("message") if event.get("type") == "error" else None
            detail = json.loads(message) if isinstance(message, str) else {}
            if (isinstance(detail, dict) and detail.get("status") == 400
                and isinstance(detail.get("error"), dict)
                and detail["error"].get("code") == "invalid_json_schema"):
                return "PROVIDER_SCHEMA_REJECTED"
        except (ValueError, TypeError):
            continue
    return None


def _codex_process_failure(
    status: ProcessReceiptStatus,
) -> tuple[str, ExecutionOutcome]:
    if status is ProcessReceiptStatus.START_FAILED:
        return "PROCESS_START_FAILURE", ExecutionOutcome.RETRYABLE_FAILURE
    if status is ProcessReceiptStatus.FAILED:
        return "PROCESS_EXIT_FAILURE", ExecutionOutcome.RETRYABLE_FAILURE
    if status is ProcessReceiptStatus.TIMED_OUT:
        return "PROCESS_TIMEOUT", ExecutionOutcome.TIMED_OUT
    if status is ProcessReceiptStatus.CORRUPT_RESULT:
        return "INVALID_JSON", ExecutionOutcome.RETRYABLE_FAILURE
    if status is ProcessReceiptStatus.CANCELLED:
        return "PROCESS_CANCELLED", ExecutionOutcome.CANCELLED
    if status is ProcessReceiptStatus.ORPHANED:
        return "PROCESS_OUTCOME_UNKNOWN", ExecutionOutcome.ORPHANED
    return (
        "PROCESS_OUTCOME_UNKNOWN",
        ExecutionReconciler.PROCESS_OUTCOMES[status],
    )


class CodexCliExecutionBackend:
    backend_id = "codex-cli"

    def __init__(
        self,
        *,
        admission: AdmissionController,
        payload_resolver: ExecutionPayloadResolver,
        record_store: ExecutionRecordStore,
        supervisor: CodexProcessSupervisor,
        execution_policy: LocalProcessExecutionPolicy,
        backend_version: str = "1.0.0",
        qualification_ref: str = "capability-probe:codex-cli:1",
        codex_executable: str = "",
        codex_home: str = "",
        pricing: CodexPricingSnapshot | None = None,
        account_entitlement: CodexAccountEntitlementSnapshot | None = None,
        retry_policy: str = "",
        structured_result_validator: CodexStructuredResultValidator | None = None,
    ) -> None:
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store
        self.supervisor = supervisor
        self.execution_policy = execution_policy
        self.codex_executable = codex_executable
        self.codex_home = require_codex_home(codex_home) if codex_executable else ""
        self.pricing = pricing
        self.account_entitlement = account_entitlement
        self.retry_policy = retry_policy
        self.retry_overrides = codex_retry_overrides(retry_policy)
        if retry_policy and account_entitlement is None:
            raise ValueError("controlled Codex no-retry policy requires its existing account entitlement")
        self.structured_result_validator = structured_result_validator
        if codex_executable:
            executable = Path(codex_executable)
            if not executable.is_absolute() or not executable.is_file():
                raise ValueError("Codex executable must be an existing absolute file")
            if (pricing is None) == (account_entitlement is None):
                raise ValueError(
                    "real Codex execution requires exactly one pricing or account entitlement basis"
                )
            if structured_result_validator is None:
                raise ValueError("real Codex execution requires semantic validation")
        elif pricing is not None and account_entitlement is not None:
            raise ValueError(
                "Codex backend cannot mix pricing and account entitlement bases"
            )
        measured_evidence = pricing is not None or account_entitlement is not None
        self.capability_profile = ExecutionCapabilityProfile(
            backend_id=self.backend_id,
            backend_version=backend_version,
            runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            supported_completion_modes=(CompletionMode.PROCESS_EXIT,),
            supported_reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=measured_evidence,
            supports_cost_receipt=measured_evidence,
            supports_structured_output=True,
            supports_process_group_control=True,
            supports_persistent_execution_directory=True,
            supports_provider_idempotency=False,
            real_provider_validation_eligible=True,
            qualification_ref=qualification_ref,
        )

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        return self._submit(request, admission)

    def submit_recovered(
        self,
        request: ExecutionRequest,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionHandle:
        admission = self.admission.admit_recovery(
            request,
            self.capability_profile,
            authorization,
        )
        return self._submit(request, admission)

    def _submit(
        self,
        request: ExecutionRequest,
        admission: ExecutionAdmission,
    ) -> ExecutionHandle:
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        payload = self.payload_resolver.resolve(request, admission)
        payload = self._prepare_payload(request, payload, admission)
        if not payload.command:
            raise ValueError("Codex CLI execution requires a governed command")
        model_authority = self._model_authority_evidence(
            admission,
            payload.command,
            require_codex_invocation=bool(self.codex_executable),
        )
        self.execution_policy.assert_payload(payload)
        launch_request = ProcessLaunchRequest(
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
        provisional_handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=f"process-invoking:{request.execution_id}",
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id=None,
            completion_mode=CompletionMode.PROCESS_EXIT,
            query_capability=CapabilityAvailability.SUPPORTED,
            cancel_capability=CapabilityAvailability.SUPPORTED,
            callback_capability=CapabilityAvailability.UNSUPPORTED,
        )
        record = ExecutionRecord(
            request=request,
            handle=provisional_handle,
            started_at=_utc_now(),
            frozen_output_contract=_freeze_output_contract(request, payload, _sha256(payload.request_payload)),
            raw_evidence={
                "submission_phase": "PROCESS_STARTING",
                "output_schema_version": payload.output_schema_version,
                "transport": ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE.value,
                "provider_request_id": None,
                "stage": request.stage,
                "output_schema": dict(payload.output_schema or {}),
                "capability_evidence": dict(payload.capability_evidence or {}),
                "allowed_tools": list(payload.allowed_tools),
                "denied_tools": list(payload.denied_tools),
                "model_authority": model_authority,
            },
        )
        self.record_store.put_record(record)
        try:
            supervised = self.supervisor.run(launch_request)
        except Exception:
            record.raw_evidence["submission_phase"] = "PROCESS_OUTCOME_UNKNOWN"
            self.record_store.save_record(record)
            raise
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
            "submission_phase": "PROCESS_RESULT_RECORDED",
            "output_schema_version": payload.output_schema_version,
            "transport": ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE.value,
            "local_execution_receipt_id": receipt.receipt_id,
            "provider_request_id": None,
            "stage": request.stage,
            "output_schema": dict(payload.output_schema or {}),
            "provider_schema_contract": {
                "version": CODEX_SCHEMA_PROJECTION_VERSION,
                "canonical_hash": _sha256(dict(payload.output_schema or {})),
                "provider_hash": _sha256(codex_output_schema(dict(payload.output_schema or {}))),
                "local_constraints_retained": ["uniqueItems"],
            },
            "capability_evidence": dict(payload.capability_evidence or {}),
            "allowed_tools": list(payload.allowed_tools),
            "denied_tools": list(payload.denied_tools),
            "model_authority": model_authority,
        }
        if self.retry_policy:
            evidence["transport_retry_policy"] = {
                "version": self.retry_policy,
                "invocation_overrides": list(self.retry_overrides),
                "request_max_retries": 0,
                "stream_max_retries": 0,
            }
        if (
            receipt.status is ProcessReceiptStatus.CANCELLED
            and receipt.result_integrity is ResultIntegrity.VALID
        ):
            evidence["late_result_quarantined"] = True
        record.handle = handle
        record.started_at = receipt.process_started_at
        record.raw_evidence = evidence
        record.process_receipt = receipt
        self.record_store.save_record(record)
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
        self.record_store.save_record(record)
        if (
            recovery.receipt.status
            in {ProcessReceiptStatus.SUCCEEDED, ProcessReceiptStatus.CORRUPT_RESULT}
            and recovery.receipt.returncode == 0
        ):
            try:
                self._validate_successful_process(record, recovery.receipt)
            except _CodexResultFailure as failure:
                record.raw_evidence.update(
                    {
                        "failure_code": failure.code,
                        "failure_message": str(failure),
                        "failure_disposition": (
                            "RETRYABLE" if failure.retryable else "FINAL"
                        ),
                    }
                )
                record.result = ExecutionReconciler.non_success(
                    record,
                    (
                        ExecutionOutcome.RETRYABLE_FAILURE
                        if failure.retryable
                        else ExecutionOutcome.FINAL_FAILURE
                    ),
                    process_receipt_ref=receipt_ref,
                )
                record.result = self._rejected_output_receipts(
                    record, recovery.receipt, record.result
                )
            else:
                record.result = ResultValidator(self.record_store).successful_result(
                    record, process_receipt_ref=receipt_ref
                )
        else:
            failure_code, outcome = _codex_process_failure(recovery.receipt.status)
            if recovery.receipt.status is ProcessReceiptStatus.FAILED:
                with Path(recovery.receipt.stdout_path).open(encoding="utf-8") as stdout:
                    protocol_failure = codex_protocol_failure(stdout.read(262144))
                if protocol_failure:
                    failure_code, outcome = protocol_failure, ExecutionOutcome.FINAL_FAILURE
            record.raw_evidence.update(
                {
                    "failure_code": failure_code,
                    "failure_message": recovery.receipt.failure_reason or failure_code,
                    "failure_disposition": (
                        "RETRYABLE"
                        if outcome
                        in {
                            ExecutionOutcome.RETRYABLE_FAILURE,
                            ExecutionOutcome.TIMED_OUT,
                        }
                        else "FINAL"
                    ),
                }
            )
            record.result = ExecutionReconciler.non_success(
                record, outcome, process_receipt_ref=receipt_ref
            )
        self.record_store.save_record(record)
        return record.result

    def _rejected_output_receipts(self, record, receipt, result):
        refs = {}
        if receipt.result_path and Path(receipt.result_path).is_file():
            self.execution_policy.assert_result(receipt.result_path)
            with Path(receipt.result_path).open("rb") as source:
                result_hash = hashlib.file_digest(source, "sha256").hexdigest()
                byte_size = source.tell()
            refs["raw_output_ref"] = self.record_store.put_evidence(
                "rejected-output",
                record.request.execution_id,
                {
                    "result_path": receipt.result_path,
                    "result_sha256": "sha256:" + result_hash,
                    "byte_size": byte_size,
                    "input_sha256": receipt.input_sha256,
                    "validation": "REJECTED",
                    "generation_allowed": False,
                },
            )
        for name in ("usage", "cost"):
            if isinstance(record.raw_evidence.get(name), Mapping):
                refs[name + "_receipt_ref"] = self.record_store.put_evidence(
                    name + "-receipt",
                    record.request.execution_id,
                    record.raw_evidence[name],
                )
        return replace(result, **refs)

    def _prepare_payload(
        self,
        request: ExecutionRequest,
        payload: ResolvedExecutionPayload,
        admission: ExecutionAdmission,
    ) -> ResolvedExecutionPayload:
        if payload.command:
            if self.codex_executable:
                raise ValueError(
                    "real Codex invocation must be generated from the frozen RouteSnapshot"
                )
            return payload
        if not self.codex_executable or payload.output_schema is None:
            return payload
        route = admission.route_snapshot
        layout = self.supervisor.execution_directory.prepare(request.execution_id)
        schema_path = layout.result_path("output.schema.json")
        schema_path.write_text(
            json.dumps(
                codex_output_schema(payload.output_schema),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result_filename = "last-message.json"
        result_path = layout.result_path(result_filename)
        command = (
            self.codex_executable,
            "exec",
            "--model",
            route.model_id,
            "-c",
            f"model_reasoning_effort={route.reasoning_effort}",
            *(
                arg
                for override in (*CODEX_INPUT_ONLY_OVERRIDES, *self.retry_overrides)
                for arg in ("-c", override)
            ),
            *(
                ("-c", 'forced_login_method="chatgpt"')
                if self.account_entitlement
                else ()
            ),
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "--color",
            "never",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--cd",
            self.execution_policy.fixed_working_directory,
            "-",
        )
        return replace(
            payload,
            command=command,
            environment_overrides={
                **(payload.environment_overrides or {}),
                "CODEX_HOME": self.codex_home,
            },
            result_filename=result_filename,
        )

    @staticmethod
    def _model_authority_evidence(
        admission: ExecutionAdmission,
        command: tuple[str, ...],
        *,
        require_codex_invocation: bool,
    ) -> dict[str, Any]:
        route = admission.route_snapshot
        profile = admission.model_profile
        invocation_model = "unavailable"
        invocation_effort = "unavailable"
        model_positions = [
            index for index, value in enumerate(command) if value == "--model"
        ]
        effort_values = [
            value.removeprefix("model_reasoning_effort=")
            for index, value in enumerate(command)
            if index > 0
            and command[index - 1] == "-c"
            and value.startswith("model_reasoning_effort=")
        ]
        if len(model_positions) == 1 and model_positions[0] + 1 < len(command):
            invocation_model = command[model_positions[0] + 1]
        if len(effort_values) == 1:
            invocation_effort = effort_values[0]
        ignores_user_config = command.count("--ignore-user-config") == 1
        if require_codex_invocation:
            if invocation_model != route.model_id:
                raise ValueError(
                    "Codex invocation model differs from the frozen RouteSnapshot"
                )
            if invocation_effort != route.reasoning_effort:
                raise ValueError(
                    "Codex invocation reasoning effort differs from the frozen RouteSnapshot"
                )
            if not ignores_user_config:
                raise ValueError(
                    "Codex invocation must ignore local user configuration"
                )
        return {
            "schema_version": "novelos.model_authority_evidence.v1",
            "policy_requested_model": profile.model_id,
            "frozen_route_model": route.model_id,
            "invocation_model": invocation_model,
            "provider_observed_model": "unavailable",
            "policy_requested_reasoning_effort": profile.reasoning_effort,
            "frozen_route_reasoning_effort": route.reasoning_effort,
            "invocation_reasoning_effort": invocation_effort,
            "provider_observed_reasoning_effort": "unavailable",
            "model_profile_id": route.model_profile_id,
            "model_profile_version": route.model_profile_version,
            "model_profile_hash": route.model_profile_hash,
            "route_policy_id": route.policy_id,
            "route_policy_version": route.policy_version,
            "route_policy_hash": route.route_policy_hash,
            "route_snapshot_id": route.route_snapshot_id,
            "route_snapshot_hash": route.contract_hash,
            "invocation_command_hash": "sha256:"
            + hashlib.sha256(
                json.dumps(command, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "local_user_config_ignored": ignores_user_config,
            "local_user_config_is_model_authority": False,
        }

    def _validate_successful_process(
        self,
        record: ExecutionRecord,
        receipt: Any,
    ) -> None:
        capability_evidence = record.raw_evidence.get("capability_evidence")
        if isinstance(capability_evidence, Mapping) and capability_evidence:
            expected_prompt_hash = str(
                capability_evidence.get("fully_rendered_prompt_hash") or ""
            ).removeprefix("sha256:")
            if not expected_prompt_hash or expected_prompt_hash != receipt.input_sha256:
                raise _CodexResultFailure(
                    "CAPABILITY_MATERIALIZATION_MISMATCH",
                    "actual Codex stdin differs from frozen rendered prompt",
                    retryable=False,
                )
        if self.pricing is not None or self.account_entitlement is not None:
            authority = record.raw_evidence.get("model_authority")
            if not isinstance(authority, Mapping):
                raise _CodexResultFailure(
                    "MODEL_AUTHORITY_EVIDENCE_MISSING",
                    "Codex execution has no frozen model authority evidence",
                    retryable=False,
                )
            frozen_model = str(authority.get("frozen_route_model") or "")
            if not frozen_model:
                raise _CodexResultFailure(
                    "MODEL_AUTHORITY_EVIDENCE_MISSING",
                    "Codex execution has no frozen route model",
                    retryable=False,
                )
            try:
                runtime_evidence = parse_codex_jsonl_evidence(
                    Path(receipt.stdout_path).read_text(encoding="utf-8"),
                    model_id=frozen_model,
                    pricing=self.pricing,
                    account_entitlement=self.account_entitlement,
                    allowed_tools=tuple(
                        str(item)
                        for item in record.raw_evidence.get("allowed_tools") or ()
                    ),
                    denied_tools=tuple(
                        str(item)
                        for item in record.raw_evidence.get("denied_tools") or ()
                    ),
                )
            except (OSError, ValueError) as exc:
                raise _CodexResultFailure(
                    "CODEX_JSONL_EVIDENCE_INVALID",
                    str(exc),
                    retryable=False,
                ) from exc
            record.raw_evidence.update(runtime_evidence)
            if runtime_evidence["unauthorized_tools"]:
                raise _CodexResultFailure(
                    "UNAUTHORIZED_TOOL_INVOCATION",
                    "Codex attempted a Tool outside the frozen Capability policy",
                    retryable=False,
                )
        if (
            not receipt.result_path
            or receipt.result_integrity is not ResultIntegrity.VALID
        ):
            raise _CodexResultFailure(
                "INVALID_JSON", "Codex result is missing or corrupt", retryable=False
            )
        self.execution_policy.assert_result(receipt.result_path)
        try:
            parsed = json.loads(Path(receipt.result_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _CodexResultFailure(
                "INVALID_JSON", "Codex last message is not valid JSON", retryable=False
            ) from exc
        if not isinstance(parsed, Mapping):
            raise _CodexResultFailure(
                "OUTPUT_SCHEMA_FAILURE",
                "Codex result must be a JSON object",
                retryable=False,
            )
        frozen = record.frozen_output_contract or record.raw_evidence
        output_schema = frozen.get("output_schema")
        stage = str(record.raw_evidence.get("stage") or record.request.stage)
        normalized: Mapping[str, Any] = parsed
        if self.structured_result_validator is not None:
            if not isinstance(output_schema, Mapping) or not output_schema:
                raise _CodexResultFailure(
                    "OUTPUT_SCHEMA_FAILURE",
                    "Codex execution has no frozen output schema",
                    retryable=False,
                )
            try:
                normalized = _validate_frozen_structured_result(
                    self.structured_result_validator, stage, output_schema, parsed,
                    str(frozen.get("output_schema_version") or ""),
                )
            except ValueError as exc:
                code = str(getattr(exc, "code", ""))
                failure_code = (
                    "OUTPUT_SCHEMA_FAILURE"
                    if "SCHEMA" in code
                    else "OUTPUT_SEMANTIC_FAILURE"
                )
                raise _CodexResultFailure(
                    failure_code,
                    "structured output failed " + failure_code,
                    retryable=False,
                ) from exc
        if not isinstance(normalized, Mapping) or not normalized:
            raise _CodexResultFailure(
                "OUTPUT_SEMANTIC_FAILURE",
                "Codex semantic validator returned no structured result",
                retryable=False,
            )
        record.raw_evidence["result"] = json.loads(_canonical_json(normalized))
        materialization_ref = (
            str(capability_evidence.get("materialization_hash") or "")
            if isinstance(capability_evidence, Mapping)
            else ""
        )
        tools = record.raw_evidence.get("tools")
        record.raw_evidence["validation_checks"] = {
            "output_schema": str(
                record.raw_evidence.get("output_schema_version") or ""
            ),
            "stage_semantics": f"chapter-stage:{stage}:semantic-validation",
            "capability_materialization": materialization_ref
            or "capability-materialization:not-applicable",
            "tool_policy": (
                f"tool-policy:{_sha256(dict(tools))}"
                if isinstance(tools, Mapping)
                else "tool-policy:not-applicable"
            ),
        }

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        requested_at = _utc_now()
        try:
            recovery = self.supervisor.cancel(
                handle.execution_id,
                reason=reason,
            )
        except FileNotFoundError:
            recovery = None
        receipt = recovery.receipt if recovery is not None else None
        if receipt is None:
            outcome = CancellationOutcome.NOT_FOUND
            local_outcome = LocalTerminationOutcome.NOT_FOUND
        elif receipt.status is ProcessReceiptStatus.CANCELLED:
            outcome = CancellationOutcome.CANCELLED
            local_outcome = LocalTerminationOutcome.TERMINATED
        elif receipt.status in {
            ProcessReceiptStatus.SUCCEEDED,
            ProcessReceiptStatus.FAILED,
            ProcessReceiptStatus.START_FAILED,
            ProcessReceiptStatus.TIMED_OUT,
            ProcessReceiptStatus.CORRUPT_RESULT,
        }:
            outcome = CancellationOutcome.ALREADY_COMPLETED
            local_outcome = LocalTerminationOutcome.ALREADY_EXITED
        else:
            outcome = CancellationOutcome.UNKNOWN
            local_outcome = LocalTerminationOutcome.UNKNOWN
        cancellation = ExecutionCancellationResult(
            execution_id=handle.execution_id,
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            fencing_token=handle.fencing_token,
            backend_id=self.backend_id,
            transport=handle.transport,
            outcome=outcome,
            local_termination_outcome=local_outcome,
            upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
            local_execution_receipt_id=(
                receipt.receipt_id
                if receipt is not None
                else handle.local_execution_receipt_id
            ),
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
        )
        record = self.record_store.find_record(handle.execution_id)
        if record is not None:
            record.cancellation = cancellation
            if receipt is not None:
                record.process_receipt = receipt
                self.record_store.put_evidence(
                    "process-cancellation-receipt",
                    handle.execution_id,
                    receipt.to_dict(),
                )
            self.record_store.save_record(record)
        return cancellation


__all__ = [
    "CodexAccountEntitlementSnapshot",
    "CodexPricingSnapshot",
    "CodexCliExecutionBackend",
    "CodexStructuredResultValidator",
    "ExecutionPayloadResolver",
    "ExecutionReconciler",
    "ExecutionRecord",
    "ExecutionRecordStore",
    "InMemoryExecutionRecordStore",
    "LocalProcessExecutionPolicy",
    "RemoteProviderExecutionBackend",
    "ResolvedExecutionPayload",
    "ResultNormalizer",
    "ResultValidator",
    "ScriptedFixtureExecutionBackend",
    "StaticExecutionPayloadResolver",
    "parse_codex_jsonl_evidence",
    "observe_codex_cli_version",
]
