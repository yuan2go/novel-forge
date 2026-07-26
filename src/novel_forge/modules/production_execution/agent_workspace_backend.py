"""Bounded Agent workspace transaction execution contracts.

The backend may produce patch/decision/report candidates only.  Authority and
domain handlers remain responsible for validation, approval, commit, activation,
and Git acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol

from .backends import (
    ExecutionPayloadResolver,
    ExecutionRecord,
    ExecutionRecordStore,
    ExecutionReconciler,
    ResultValidator,
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


_ALLOWED_RESULT_KINDS = frozenset(
    {
        "patch_candidate",
        "structured_decision",
        "analysis_report",
        "proposed_asset_version",
        "workspace_manifest",
    }
)
_NETWORK_POLICIES = frozenset({"DENY", "ALLOW_LISTED"})


def _relative_path(value: str, label: str) -> str:
    normalized = str(value).strip().replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or ".." in candidate.parts
        or normalized.startswith("~")
    ):
        raise ValueError(f"{label} must contain bounded relative paths")
    return normalized


@dataclass(frozen=True, slots=True)
class AgentWorkspaceExecutionContract:
    workspace_snapshot_ref: str
    read_set: tuple[str, ...]
    write_set: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_commands: tuple[tuple[str, ...], ...]
    network_policy: str
    git_base_sha: str
    expected_output_contract: str
    maximum_agent_hops: int
    maximum_files_changed: int
    maximum_cost: str
    approval_policy: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.workspace_snapshot_ref,
                self.git_base_sha,
                self.expected_output_contract,
                self.approval_policy,
            )
        ):
            raise ValueError("agent workspace contract is incomplete")
        if self.network_policy not in _NETWORK_POLICIES:
            raise ValueError("agent workspace network policy is not governed")
        if self.maximum_agent_hops < 0 or self.maximum_files_changed < 0:
            raise ValueError("agent workspace limits cannot be negative")
        if len(self.git_base_sha) != 40 or any(
            char not in "0123456789abcdef" for char in self.git_base_sha.lower()
        ):
            raise ValueError("agent workspace git base must be a full SHA")
        try:
            maximum_cost = Decimal(self.maximum_cost)
        except InvalidOperation as exc:
            raise ValueError("agent workspace maximum cost is invalid") from exc
        if maximum_cost < 0:
            raise ValueError("agent workspace maximum cost cannot be negative")
        object.__setattr__(
            self,
            "read_set",
            tuple(_relative_path(item, "read_set") for item in self.read_set),
        )
        object.__setattr__(
            self,
            "write_set",
            tuple(_relative_path(item, "write_set") for item in self.write_set),
        )
        object.__setattr__(
            self,
            "allowed_tools",
            tuple(str(item).strip() for item in self.allowed_tools if str(item).strip()),
        )
        commands: list[tuple[str, ...]] = []
        for command in self.allowed_commands:
            frozen = tuple(str(item) for item in command)
            if not frozen or any(not token for token in frozen):
                raise ValueError("agent workspace command allowlist is invalid")
            if any(token in {"|", "&&", "||", ";", ">", ">>"} for token in frozen):
                raise ValueError("agent workspace commands cannot contain shell operators")
            commands.append(frozen)
        object.__setattr__(self, "allowed_commands", tuple(commands))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_snapshot_ref": self.workspace_snapshot_ref,
            "read_set": list(self.read_set),
            "write_set": list(self.write_set),
            "allowed_tools": list(self.allowed_tools),
            "allowed_commands": [list(item) for item in self.allowed_commands],
            "network_policy": self.network_policy,
            "git_base_sha": self.git_base_sha,
            "expected_output_contract": self.expected_output_contract,
            "maximum_agent_hops": self.maximum_agent_hops,
            "maximum_files_changed": self.maximum_files_changed,
            "maximum_cost": self.maximum_cost,
            "approval_policy": self.approval_policy,
        }

    @property
    def contract_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class AgentWorkspaceContractSource(Protocol):
    def require(
        self, workspace_snapshot_ref: str
    ) -> AgentWorkspaceExecutionContract: ...


class StaticAgentWorkspaceContractSource:
    def __init__(
        self, contracts: tuple[AgentWorkspaceExecutionContract, ...]
    ) -> None:
        self._contracts = {
            contract.workspace_snapshot_ref: contract for contract in contracts
        }
        if len(self._contracts) != len(contracts):
            raise ValueError("duplicate agent workspace snapshot contract")

    def require(
        self, workspace_snapshot_ref: str
    ) -> AgentWorkspaceExecutionContract:
        try:
            return self._contracts[workspace_snapshot_ref]
        except KeyError as exc:
            raise ValueError(
                f"agent workspace contract is unavailable: {workspace_snapshot_ref}"
            ) from exc


@dataclass(frozen=True, slots=True)
class AgentWorkspaceRunnerProfile:
    runner_id: str
    runner_version: str
    fixture_protocol_only: bool
    real_agent_validation_eligible: bool
    qualification_ref: str

    def __post_init__(self) -> None:
        if not self.runner_id or not self.runner_version or not self.qualification_ref:
            raise ValueError("agent workspace runner profile is incomplete")
        if self.fixture_protocol_only and self.real_agent_validation_eligible:
            raise ValueError("fixture agent runner cannot be real-validation eligible")


class AgentWorkspaceRunner(Protocol):
    capability_profile: AgentWorkspaceRunnerProfile

    def execute(
        self,
        *,
        request: ExecutionRequest,
        contract: AgentWorkspaceExecutionContract,
        instruction_payload: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class ScriptedAgentWorkspaceRunner:
    capability_profile = AgentWorkspaceRunnerProfile(
        runner_id="scripted-agent-workspace",
        runner_version="1.0.0",
        fixture_protocol_only=True,
        real_agent_validation_eligible=False,
        qualification_ref="capability-probe:scripted-agent-workspace:1",
    )

    def execute(
        self,
        *,
        request: ExecutionRequest,
        contract: AgentWorkspaceExecutionContract,
        instruction_payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del instruction_payload
        return {
            "result": {
                "result_kind": "workspace_manifest",
                "workspace_manifest": {
                    "workspace_snapshot_ref": contract.workspace_snapshot_ref,
                    "git_base_sha": contract.git_base_sha,
                    "files_changed": [],
                    "proposed_only": True,
                    "operation_id": request.operation_id,
                },
            },
            "fixture_protocol_only": True,
            "real_model_call": False,
            "production_verified": False,
        }


class AgentWorkspaceExecutionBackend:
    backend_id = "agent-workspace"

    def __init__(
        self,
        *,
        runner: AgentWorkspaceRunner,
        workspace_contracts: AgentWorkspaceContractSource,
        admission: AdmissionController,
        payload_resolver: ExecutionPayloadResolver,
        record_store: ExecutionRecordStore,
        backend_version: str = "1.0.0",
    ) -> None:
        runner_profile = runner.capability_profile
        if (
            runner_profile.fixture_protocol_only
            and admission.environment in {"validation", "provider-validation", "production"}
        ):
            raise ValueError(
                "fixture agent workspace runner is prohibited in a controlled environment"
            )
        self.runner = runner
        self.workspace_contracts = workspace_contracts
        self.admission = admission
        self.payload_resolver = payload_resolver
        self.record_store = record_store
        self.capability_profile = ExecutionCapabilityProfile(
            backend_id=self.backend_id,
            backend_version=backend_version,
            runtime_class=ExecutionRuntimeClass.AGENT_WORKSPACE_TRANSACTION,
            supported_completion_modes=(CompletionMode.SYNCHRONOUS,),
            supported_reasoning_efforts=("none",),
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=False,
            supports_cost_receipt=False,
            supports_structured_output=True,
            supports_process_group_control=False,
            supports_persistent_execution_directory=False,
            supports_provider_idempotency=False,
            real_provider_validation_eligible=(
                runner_profile.real_agent_validation_eligible
            ),
            qualification_ref=runner_profile.qualification_ref,
        )

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        admission = self.admission.admit(request, self.capability_profile)
        existing = self.record_store.find_record(request.execution_id)
        if existing is not None:
            if existing.request.contract_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
            return existing.handle
        contract = self.workspace_contracts.require(request.workspace_snapshot_ref)
        if request.agent_hop_count > contract.maximum_agent_hops:
            raise ValueError("agent hop limit exceeded")
        payload = self.payload_resolver.resolve(request, admission)
        if (
            PurePosixPath(payload.working_directory).is_absolute()
            or ".." in PurePosixPath(payload.working_directory).parts
        ):
            raise ValueError("agent working directory must be workspace-relative")
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id=f"workspace-transaction:{request.execution_id}",
            backend_id=self.backend_id,
            transport=ExecutionRuntimeClass.AGENT_WORKSPACE_TRANSACTION,
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
        record = ExecutionRecord(
            request=request,
            handle=handle,
            started_at=_utc_now(),
            raw_evidence={
                "submission_phase": "AGENT_WORKSPACE_INVOKING",
                "workspace_contract_hash": contract.contract_hash,
                "workspace_contract": contract.to_dict(),
                "output_schema_version": payload.output_schema_version,
            },
        )
        self.record_store.put_record(record)
        try:
            runner_evidence = self.runner.execute(
                request=request,
                contract=contract,
                instruction_payload=dict(payload.request_payload),
            )
        except Exception:
            record.raw_evidence["submission_phase"] = "AGENT_WORKSPACE_OUTCOME_UNKNOWN"
            self.record_store.save_record(record)
            raise
        result = runner_evidence.get("result")
        self._validate_candidate(result, contract)
        qualified_evidence = dict(runner_evidence)
        if self.runner.capability_profile.fixture_protocol_only:
            qualified_evidence["fixture_protocol_only"] = True
            qualified_evidence["real_model_call"] = False
            qualified_evidence["production_verified"] = False
        record.raw_evidence = {
            **qualified_evidence,
            "submission_phase": "AGENT_WORKSPACE_RESULT_RECORDED",
            "workspace_contract_hash": contract.contract_hash,
            "workspace_contract": contract.to_dict(),
            "output_schema_version": payload.output_schema_version,
        }
        self.record_store.save_record(record)
        return handle

    @staticmethod
    def _validate_candidate(
        result: Any, contract: AgentWorkspaceExecutionContract
    ) -> None:
        if not isinstance(result, Mapping):
            raise ValueError("agent workspace result must be structured")
        result_kind = str(result.get("result_kind") or "")
        if result_kind not in _ALLOWED_RESULT_KINDS:
            raise ValueError("agent workspace result is not an allowed candidate kind")
        manifest = result.get("workspace_manifest")
        if isinstance(manifest, Mapping):
            files = manifest.get("files_changed") or []
            if not isinstance(files, (list, tuple)):
                raise ValueError("agent workspace files_changed must be a list")
            if len(files) > contract.maximum_files_changed:
                raise ValueError("agent workspace changed too many files")
            for path in files:
                normalized = _relative_path(str(path), "files_changed")
                if not any(
                    normalized == allowed
                    or normalized.startswith(f"{allowed.rstrip('/')}/")
                    for allowed in contract.write_set
                ):
                    raise ValueError("agent workspace result escaped write_set")

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self.record_store.get_record(handle.execution_id)
        if record.result is None:
            if (
                record.cancellation is not None
                and record.cancellation.outcome is CancellationOutcome.CANCELLED
            ):
                record.result = ExecutionReconciler.non_success(
                    record, outcome=ExecutionOutcome.CANCELLED
                )
            elif record.raw_evidence.get("submission_phase") == (
                "AGENT_WORKSPACE_OUTCOME_UNKNOWN"
            ):
                record.result = ExecutionReconciler.non_success(
                    record, outcome=ExecutionOutcome.UNKNOWN
                )
            else:
                record.result = ResultValidator(
                    self.record_store
                ).successful_result(record)
            self.record_store.save_record(record)
        return record.result

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        record = self.record_store.get_record(handle.execution_id)
        completed = record.raw_evidence.get("submission_phase") == (
            "AGENT_WORKSPACE_RESULT_RECORDED"
        )
        completion_receipt_ref = (
            self.record_store.put_evidence(
                "agent-workspace-completion-receipt",
                handle.execution_id,
                {
                    "backend_execution_id": handle.backend_execution_id,
                    "workspace_contract_hash": record.raw_evidence.get(
                        "workspace_contract_hash"
                    ),
                    "candidate_only": True,
                },
            )
            if completed
            else None
        )
        cancellation = ExecutionCancellationResult(
            execution_id=handle.execution_id,
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            fencing_token=handle.fencing_token,
            backend_id=self.backend_id,
            transport=handle.transport,
            outcome=(
                CancellationOutcome.ALREADY_COMPLETED
                if completed
                else CancellationOutcome.UNSUPPORTED
            ),
            local_termination_outcome=(
                LocalTerminationOutcome.NOT_APPLICABLE
            ),
            upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
            local_execution_receipt_id=None,
            provider_request_id=None,
            provider_cancellation_receipt_ref=None,
            reason=reason,
            requested_at=_utc_now(),
            completed_at=_utc_now() if completed else None,
            backend_completion_receipt_ref=completion_receipt_ref,
        )
        record.cancellation = cancellation
        self.record_store.save_record(record)
        return cancellation


__all__ = [
    "AgentWorkspaceContractSource",
    "AgentWorkspaceExecutionBackend",
    "AgentWorkspaceExecutionContract",
    "AgentWorkspaceRunner",
    "AgentWorkspaceRunnerProfile",
    "ScriptedAgentWorkspaceRunner",
    "StaticAgentWorkspaceContractSource",
]
