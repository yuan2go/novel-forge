"""INVARIANT: Pure, serializable contracts for production model execution.

These contracts deliberately contain no scheduler, provider, process, or persistence
implementation.  They bind execution evidence to the existing Authority Attempt and
therefore do not introduce an execution-attempt state machine.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable

from .security import assert_no_inline_secrets


_STABLE_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_VALID_REASONING_EFFORTS = frozenset(
    {"none", "low", "medium", "high", "xhigh", "max", "ultra"}
)


class ExecutionRuntimeClass(StrEnum):
    AUTHORITY_IN_PROCESS = "AUTHORITY_IN_PROCESS"
    LOCAL_CLI_REMOTE_INFERENCE = "LOCAL_CLI_REMOTE_INFERENCE"
    REMOTE_PROVIDER_API = "REMOTE_PROVIDER_API"
    REMOTE_EXTERNAL_ACTION = "REMOTE_EXTERNAL_ACTION"
    AGENT_WORKSPACE_TRANSACTION = "AGENT_WORKSPACE_TRANSACTION"
    SCRIPTED_FIXTURE = "SCRIPTED_FIXTURE"


class CompletionMode(StrEnum):
    SYNCHRONOUS = "SYNCHRONOUS"
    PROCESS_EXIT = "PROCESS_EXIT"
    POLL = "POLL"
    CALLBACK = "CALLBACK"


class CapabilityAvailability(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class ExecutionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    FINAL_FAILURE = "FINAL_FAILURE"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ORPHANED = "ORPHANED"
    CORRUPT_RESULT = "CORRUPT_RESULT"


class ExecutionRecoveryAction(StrEnum):
    DISPATCH_PLANNED = "DISPATCH_PLANNED"
    QUERY = "QUERY"
    CANCEL = "CANCEL"
    CONSUME_RESULT = "CONSUME_RESULT"
    FINALIZE = "FINALIZE"


class CancellationOutcome(StrEnum):
    CANCELLED = "CANCELLED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class LocalTerminationOutcome(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    TERMINATED = "TERMINATED"
    ALREADY_EXITED = "ALREADY_EXITED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class UpstreamCancellationOutcome(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CANCELLED = "CANCELLED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class ModelProfileStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FallbackMode(StrEnum):
    FAIL_CLOSED = "FAIL_CLOSED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ALLOW_LISTED_ROUTE = "ALLOW_LISTED_ROUTE"


class _Contract:
    def to_dict(self) -> dict[str, Any]:
        payload = {item.name: _thaw(getattr(self, item.name)) for item in fields(self)}
        assert_no_inline_secrets(payload, label=type(self).__name__)
        return payload

    @property
    def contract_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class _HashedContract(_Contract):
    @property
    def content_hash(self) -> str:
        return self.contract_hash


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, _Contract):
        return value.to_dict()
    return value


def _required(label: str, *values: Any) -> None:
    if any(
        value is None or (isinstance(value, str) and not value.strip())
        for value in values
    ):
        raise ValueError(f"{label} is incomplete")


def _validate_attempt(operation_id: str, attempt_id: str, fencing_token: int) -> None:
    if not operation_id or not attempt_id:
        raise ValueError("contract must bind an existing Authority Attempt")
    if fencing_token <= 0:
        raise ValueError("Authority fencing token must be positive")


def _as_runtime(value: Any) -> ExecutionRuntimeClass:
    return (
        value
        if isinstance(value, ExecutionRuntimeClass)
        else ExecutionRuntimeClass(str(value))
    )


def _as_completion(value: Any) -> CompletionMode:
    return value if isinstance(value, CompletionMode) else CompletionMode(str(value))


def _as_capability(value: Any) -> CapabilityAvailability:
    return (
        value
        if isinstance(value, CapabilityAvailability)
        else CapabilityAvailability(str(value))
    )


def _as_model_status(value: Any) -> ModelProfileStatus:
    return (
        value
        if isinstance(value, ModelProfileStatus)
        else ModelProfileStatus(str(value))
    )


def _as_execution_outcome(value: Any) -> ExecutionOutcome:
    return (
        value if isinstance(value, ExecutionOutcome) else ExecutionOutcome(str(value))
    )


def _as_cancellation_outcome(value: Any) -> CancellationOutcome:
    return (
        value
        if isinstance(value, CancellationOutcome)
        else CancellationOutcome(str(value))
    )


def _as_local_termination(value: Any) -> LocalTerminationOutcome:
    return (
        value
        if isinstance(value, LocalTerminationOutcome)
        else LocalTerminationOutcome(str(value))
    )


def _as_upstream_cancellation(value: Any) -> UpstreamCancellationOutcome:
    return (
        value
        if isinstance(value, UpstreamCancellationOutcome)
        else UpstreamCancellationOutcome(str(value))
    )


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _strict_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _is_sha256(value: str) -> bool:
    normalized = value.lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    return bool(_HEX_64.fullmatch(normalized))


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(item) for item in value)


@dataclass(frozen=True, slots=True)
class TargetScope(_Contract, Mapping[str, Any]):
    scope_kind: str
    scope_id: str
    project_id: str = ""
    book_id: str = ""
    volume_id: str = ""
    arc_id: str = ""
    chapter_group_id: str = ""
    chapter_id: str = ""
    chapter_number: int | None = None
    asset_version_id: str = ""
    reader_segment_id: str = ""
    experiment_id: str = ""

    def __post_init__(self) -> None:
        _required("TargetScope", self.scope_kind, self.scope_id)
        if not _STABLE_ALIAS.fullmatch(self.scope_kind):
            raise ValueError("TargetScope scope_kind is invalid")
        if self.chapter_number is not None and self.chapter_number <= 0:
            raise ValueError("TargetScope chapter_number must be positive")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scope_kind": self.scope_kind,
            "scope_id": self.scope_id,
        }
        for name in (
            "project_id",
            "book_id",
            "volume_id",
            "arc_id",
            "chapter_group_id",
            "chapter_id",
            "asset_version_id",
            "reader_segment_id",
            "experiment_id",
        ):
            value = getattr(self, name)
            if value:
                payload[name] = value
        if self.chapter_number is not None:
            payload["chapter_number"] = self.chapter_number
        return payload

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        project_id: str = "",
        book_id: str = "",
    ) -> "TargetScope":
        values = dict(payload)
        chapter_number_value = values.get("chapter_number", values.get("chapter"))
        chapter_number = (
            _strict_int(chapter_number_value, "chapter_number")
            if chapter_number_value not in {None, ""}
            else None
        )
        resolved_project = str(values.get("project_id") or project_id)
        resolved_book = str(values.get("book_id") or book_id)
        scope_kind = str(values.get("scope_kind") or "")
        identity_by_kind = {
            "project": resolved_project,
            "book": resolved_book,
            "volume": str(values.get("volume_id") or ""),
            "arc": str(values.get("arc_id") or ""),
            "chapter_group": str(values.get("chapter_group_id") or ""),
            "chapter": str(values.get("chapter_id") or ""),
            "asset_version": str(values.get("asset_version_id") or ""),
            "reader_segment": str(values.get("reader_segment_id") or ""),
            "experiment": str(values.get("experiment_id") or ""),
        }
        scope_id = str(values.get("scope_id") or identity_by_kind.get(scope_kind) or "")
        if not scope_id and scope_kind == "chapter" and chapter_number is not None:
            scope_id = f"chapter-number:{chapter_number}"
        return cls(
            scope_kind=scope_kind,
            scope_id=scope_id,
            project_id=resolved_project,
            book_id=resolved_book,
            volume_id=str(values.get("volume_id") or ""),
            arc_id=str(values.get("arc_id") or ""),
            chapter_group_id=str(values.get("chapter_group_id") or ""),
            chapter_id=str(values.get("chapter_id") or ""),
            chapter_number=chapter_number,
            asset_version_id=str(values.get("asset_version_id") or ""),
            reader_segment_id=str(values.get("reader_segment_id") or ""),
            experiment_id=str(values.get("experiment_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class ArtifactPointer(_Contract):
    artifact_ref: str
    artifact_type: str
    content_hash: str
    schema_version: str
    source_eligibility: str
    asset_version_id: str = ""

    def __post_init__(self) -> None:
        version_id = self.asset_version_id.strip()
        if not version_id and self.artifact_ref.startswith("asset-version:"):
            version_id = self.artifact_ref.removeprefix("asset-version:")
        object.__setattr__(self, "asset_version_id", version_id)
        if (
            not version_id
            or self.artifact_ref.startswith(("/", "./", "../", "file:"))
            or "/" in version_id
            or "\\" in version_id
        ):
            raise ValueError(
                "artifact pointer requires an Authority AssetVersion identity, not a path"
            )
        _required(
            "artifact pointer",
            self.artifact_ref,
            self.asset_version_id,
            self.artifact_type,
            self.content_hash,
            self.schema_version,
            self.source_eligibility,
        )
        if not _is_sha256(self.content_hash):
            raise ValueError("artifact pointer requires a SHA-256 content hash")
        if self.source_eligibility not in {
            "PRODUCTION_ELIGIBLE",
            "NOT_SOURCE_DERIVED",
            "FIXTURE_ELIGIBLE",
            "SOURCE_ANALYSIS_ONLY",
        }:
            raise ValueError(
                "artifact pointer source eligibility is not execution-safe"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ref": self.artifact_ref,
            "asset_version_id": self.asset_version_id,
            "artifact_type": self.artifact_type,
            "content_hash": self.content_hash,
            "schema_version": self.schema_version,
            "source_eligibility": self.source_eligibility,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ArtifactPointer:
        return cls(
            **{
                key: str(payload.get(key) or "")
                for key in (
                    "artifact_ref",
                    "artifact_type",
                    "content_hash",
                    "schema_version",
                    "source_eligibility",
                    "asset_version_id",
                )
            }
        )


@dataclass(frozen=True, slots=True)
class ValidationCheck(_Contract):
    check_kind: str
    status: str
    evidence_ref: str

    def __post_init__(self) -> None:
        _required("validation check", self.check_kind, self.status, self.evidence_ref)
        if self.status not in {"PASSED", "FAILED", "NEEDS_REVIEW", "NOT_APPLICABLE"}:
            raise ValueError("validation check status is invalid")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ValidationCheck:
        return cls(
            check_kind=str(payload.get("check_kind") or ""),
            status=str(payload.get("status") or ""),
            evidence_ref=str(payload.get("evidence_ref") or ""),
        )


@dataclass(frozen=True, slots=True)
class ExecutionCapabilityProfile(_Contract):
    backend_id: str
    backend_version: str
    runtime_class: ExecutionRuntimeClass
    supported_completion_modes: tuple[CompletionMode, ...]
    supported_reasoning_efforts: tuple[str, ...]
    supports_query: bool
    supports_cancel: bool
    supports_callback: bool
    supports_usage_receipt: bool
    supports_cost_receipt: bool
    supports_structured_output: bool
    supports_process_group_control: bool
    supports_persistent_execution_directory: bool
    supports_provider_idempotency: bool
    real_provider_validation_eligible: bool
    qualification_ref: str
    contract_version: str = "execution-capability-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_class", _as_runtime(self.runtime_class))
        object.__setattr__(
            self,
            "supported_completion_modes",
            tuple(_as_completion(item) for item in self.supported_completion_modes),
        )
        efforts = tuple(
            str(item).strip().lower() for item in self.supported_reasoning_efforts
        )
        object.__setattr__(self, "supported_reasoning_efforts", efforts)
        _required(
            "execution capability profile",
            self.backend_id,
            self.backend_version,
            self.qualification_ref,
            self.contract_version,
        )
        if not self.supported_completion_modes:
            raise ValueError("execution capability profile requires a completion mode")
        if not efforts or any(item not in _VALID_REASONING_EFFORTS for item in efforts):
            raise ValueError(
                "execution capability profile has an invalid reasoning effort"
            )
        if self.real_provider_validation_eligible:
            if not self.supports_structured_output:
                raise ValueError("real provider validation requires structured output")
            if self.runtime_class is ExecutionRuntimeClass.SCRIPTED_FIXTURE:
                raise ValueError(
                    "scripted fixtures are not real-provider validation eligible"
                )

    def require_model_profile(self, profile: ModelProfile) -> None:
        if profile.status is not ModelProfileStatus.ACTIVE:
            raise ValueError("ModelProfile must be ACTIVE")
        if profile.backend_id != self.backend_id:
            raise ValueError("ModelProfile backend does not match capability profile")
        if profile.runtime_class is not self.runtime_class:
            raise ValueError(
                "ModelProfile runtime class does not match capability profile"
            )
        if profile.reasoning_effort not in self.supported_reasoning_efforts:
            raise ValueError("requested reasoning effort is unsupported by backend")
        if profile.output_policy_ref and not self.supports_structured_output:
            raise ValueError("ModelProfile requires unsupported structured output")
        if not profile.capability_probe_ref:
            raise ValueError("ModelProfile has no Capability Probe evidence")
        if profile.capability_probe_ref != self.qualification_ref:
            raise ValueError(
                "ModelProfile Capability Probe does not match backend qualification"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionCapabilityProfile:
        return cls(
            backend_id=str(payload.get("backend_id") or ""),
            backend_version=str(payload.get("backend_version") or ""),
            runtime_class=_as_runtime(payload.get("runtime_class")),
            supported_completion_modes=tuple(
                _as_completion(item)
                for item in payload.get("supported_completion_modes") or ()
            ),
            supported_reasoning_efforts=_string_tuple(
                payload.get("supported_reasoning_efforts")
            ),
            supports_query=_strict_bool(
                payload.get("supports_query"), "supports_query"
            ),
            supports_cancel=_strict_bool(
                payload.get("supports_cancel"), "supports_cancel"
            ),
            supports_callback=_strict_bool(
                payload.get("supports_callback"), "supports_callback"
            ),
            supports_usage_receipt=_strict_bool(
                payload.get("supports_usage_receipt"), "supports_usage_receipt"
            ),
            supports_cost_receipt=_strict_bool(
                payload.get("supports_cost_receipt"), "supports_cost_receipt"
            ),
            supports_structured_output=_strict_bool(
                payload.get("supports_structured_output"), "supports_structured_output"
            ),
            supports_process_group_control=_strict_bool(
                payload.get("supports_process_group_control"),
                "supports_process_group_control",
            ),
            supports_persistent_execution_directory=_strict_bool(
                payload.get("supports_persistent_execution_directory"),
                "supports_persistent_execution_directory",
            ),
            supports_provider_idempotency=_strict_bool(
                payload.get("supports_provider_idempotency"),
                "supports_provider_idempotency",
            ),
            real_provider_validation_eligible=_strict_bool(
                payload.get("real_provider_validation_eligible"),
                "real_provider_validation_eligible",
            ),
            qualification_ref=str(payload.get("qualification_ref") or ""),
            contract_version=str(
                payload.get("contract_version") or "execution-capability-v1"
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelProfile(_Contract):
    profile_id: str
    profile_version: int
    backend_id: str
    runtime_class: ExecutionRuntimeClass
    model_provider: str
    model_id: str
    reasoning_effort: str
    timeout_policy_ref: str
    workspace_policy_ref: str
    output_policy_ref: str
    fallback_policy: str
    status: ModelProfileStatus
    capability_probe_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_class", _as_runtime(self.runtime_class))
        object.__setattr__(self, "status", _as_model_status(self.status))
        effort = self.reasoning_effort.strip().lower()
        object.__setattr__(self, "reasoning_effort", effort)
        _required(
            "ModelProfile",
            self.profile_id,
            self.backend_id,
            self.model_provider,
            self.model_id,
            self.timeout_policy_ref,
            self.workspace_policy_ref,
            self.output_policy_ref,
            self.fallback_policy,
        )
        if not _STABLE_ALIAS.fullmatch(self.profile_id):
            raise ValueError("ModelProfile profile_id must be a stable logical alias")
        if self.profile_version <= 0:
            raise ValueError("ModelProfile version must be positive")
        if effort not in _VALID_REASONING_EFFORTS:
            raise ValueError("ModelProfile reasoning effort is invalid")
        if self.fallback_policy not in {"FAIL_CLOSED", "EXPLICIT_ONLY"}:
            raise ValueError(
                "ModelProfile fallback policy must fail closed or be explicit"
            )
        if self.status is ModelProfileStatus.ACTIVE and not self.capability_probe_ref:
            raise ValueError("ACTIVE ModelProfile requires Capability Probe evidence")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModelProfile:
        return cls(
            profile_id=str(payload.get("profile_id") or ""),
            profile_version=int(payload.get("profile_version") or 0),
            backend_id=str(payload.get("backend_id") or ""),
            runtime_class=_as_runtime(payload.get("runtime_class")),
            model_provider=str(payload.get("model_provider") or ""),
            model_id=str(payload.get("model_id") or ""),
            reasoning_effort=str(payload.get("reasoning_effort") or ""),
            timeout_policy_ref=str(payload.get("timeout_policy_ref") or ""),
            workspace_policy_ref=str(payload.get("workspace_policy_ref") or ""),
            output_policy_ref=str(payload.get("output_policy_ref") or ""),
            fallback_policy=str(payload.get("fallback_policy") or ""),
            status=_as_model_status(payload.get("status")),
            capability_probe_ref=str(payload.get("capability_probe_ref") or ""),
        )


@dataclass(frozen=True, slots=True)
class FallbackPolicy(_Contract):
    policy_id: str
    policy_version: int
    mode: FallbackMode
    allowed_route_ids: tuple[str, ...]
    triggers: tuple[str, ...]
    maximum_route_changes: int
    approval_required: bool
    quality_revalidation_required: bool
    status: str

    def __post_init__(self) -> None:
        mode = (
            self.mode
            if isinstance(self.mode, FallbackMode)
            else FallbackMode(str(self.mode))
        )
        routes = _string_tuple(self.allowed_route_ids)
        triggers = _string_tuple(self.triggers)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "allowed_route_ids", routes)
        object.__setattr__(self, "triggers", triggers)
        _required("FallbackPolicy", self.policy_id, self.status)
        if not _STABLE_ALIAS.fullmatch(self.policy_id):
            raise ValueError("FallbackPolicy ID must be stable")
        if self.policy_version <= 0:
            raise ValueError("FallbackPolicy version must be positive")
        if self.maximum_route_changes < 0:
            raise ValueError("FallbackPolicy route changes cannot be negative")
        if self.status not in {"CANDIDATE", "ACTIVE", "RETIRED"}:
            raise ValueError("FallbackPolicy status is invalid")
        if any(not _STABLE_ALIAS.fullmatch(item) for item in routes):
            raise ValueError("FallbackPolicy route allowlist is invalid")
        if any(not _STABLE_ALIAS.fullmatch(item) for item in triggers):
            raise ValueError("FallbackPolicy triggers are invalid")
        if mode is FallbackMode.FAIL_CLOSED:
            if routes or triggers or self.maximum_route_changes != 0:
                raise ValueError(
                    "FAIL_CLOSED FallbackPolicy cannot allow route changes"
                )
        else:
            if not routes:
                raise ValueError("FallbackPolicy route allowlist cannot be empty")
            if not triggers or self.maximum_route_changes <= 0:
                raise ValueError(
                    "FallbackPolicy requires triggers and positive route changes"
                )
            if not self.quality_revalidation_required:
                raise ValueError("fallback route changes require quality revalidation")
        if mode is FallbackMode.APPROVAL_REQUIRED and not self.approval_required:
            raise ValueError("APPROVAL_REQUIRED fallback requires approval")

    @classmethod
    def fail_closed(cls, policy_id: str, policy_version: int) -> FallbackPolicy:
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            mode=FallbackMode.FAIL_CLOSED,
            allowed_route_ids=(),
            triggers=(),
            maximum_route_changes=0,
            approval_required=True,
            quality_revalidation_required=True,
            status="ACTIVE",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FallbackPolicy:
        return cls(
            policy_id=str(payload.get("policy_id") or ""),
            policy_version=_strict_int(payload.get("policy_version"), "policy_version"),
            mode=FallbackMode(str(payload.get("mode") or "")),
            allowed_route_ids=_string_tuple(payload.get("allowed_route_ids")),
            triggers=_string_tuple(payload.get("triggers")),
            maximum_route_changes=_strict_int(
                payload.get("maximum_route_changes"),
                "maximum_route_changes",
            ),
            approval_required=_strict_bool(
                payload.get("approval_required"), "approval_required"
            ),
            quality_revalidation_required=_strict_bool(
                payload.get("quality_revalidation_required"),
                "quality_revalidation_required",
            ),
            status=str(payload.get("status") or ""),
        )


@dataclass(frozen=True, slots=True)
class RoutePolicy(_Contract):
    policy_id: str
    policy_version: int
    default_model_profile_id: str
    allowed_model_profile_ids: tuple[str, ...]
    rule_set_ref: str
    fallback_policy: str
    fallback_policy_ref: str
    fallback_policy_version: int
    reasoning_downgrade_policy: str
    status: str

    def __post_init__(self) -> None:
        aliases = _string_tuple(self.allowed_model_profile_ids)
        object.__setattr__(self, "allowed_model_profile_ids", aliases)
        _required(
            "RoutePolicy",
            self.policy_id,
            self.default_model_profile_id,
            self.rule_set_ref,
            self.fallback_policy,
            self.fallback_policy_ref,
            self.reasoning_downgrade_policy,
            self.status,
        )
        if self.policy_version <= 0 or self.fallback_policy_version <= 0:
            raise ValueError("RoutePolicy version must be positive")
        if not _STABLE_ALIAS.fullmatch(self.policy_id):
            raise ValueError("RoutePolicy ID must be stable")
        if not aliases or self.default_model_profile_id not in aliases:
            raise ValueError("RoutePolicy default profile must be explicitly allowed")
        if any(not _STABLE_ALIAS.fullmatch(item) for item in aliases):
            raise ValueError("RoutePolicy profile IDs must be stable logical aliases")
        if self.fallback_policy not in {item.value for item in FallbackMode}:
            raise ValueError("RoutePolicy fallback mode is not governed")
        if self.reasoning_downgrade_policy != "PROHIBITED":
            raise ValueError("silent reasoning downgrade is prohibited")
        if self.status not in {"CANDIDATE", "ACTIVE", "RETIRED"}:
            raise ValueError("RoutePolicy status is invalid")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RoutePolicy:
        return cls(
            policy_id=str(payload.get("policy_id") or ""),
            policy_version=int(payload.get("policy_version") or 0),
            default_model_profile_id=str(payload.get("default_model_profile_id") or ""),
            allowed_model_profile_ids=_string_tuple(
                payload.get("allowed_model_profile_ids")
            ),
            rule_set_ref=str(payload.get("rule_set_ref") or ""),
            fallback_policy=str(payload.get("fallback_policy") or ""),
            fallback_policy_ref=str(payload.get("fallback_policy_ref") or ""),
            fallback_policy_version=_strict_int(
                payload.get("fallback_policy_version"),
                "fallback_policy_version",
            ),
            reasoning_downgrade_policy=str(
                payload.get("reasoning_downgrade_policy") or ""
            ),
            status=str(payload.get("status") or ""),
        )


@dataclass(frozen=True, slots=True)
class RouteSnapshot(_HashedContract):
    route_snapshot_id: str
    route_decision_id: str
    operation_id: str
    attempt_id: str
    policy_id: str
    policy_version: int
    backend_id: str
    backend_version: str
    runtime_host_id: str
    auth_profile_ref: str
    model_profile_id: str
    model_profile_version: int
    model_profile_hash: str
    route_policy_hash: str
    model_provider: str
    model_id: str
    requested_reasoning_effort: str
    reasoning_effort: str
    prompt_bundle_ref: str
    skill_bundle_ref: str
    context_bundle_ref: str
    output_schema_ref: str
    release_sha: str
    credential_scope: str = ""
    secret_version_ref: str = ""
    route_generation: int = 1
    parent_route_snapshot_id: str = ""
    fallback_policy_ref: str = ""
    fallback_policy_version: int = 0
    fallback_trigger: str = ""
    route_change_index: int = 0
    approval_ref: str = ""
    quality_revalidation_ref: str = ""

    def __post_init__(self) -> None:
        requested = self.requested_reasoning_effort.strip().lower()
        actual = self.reasoning_effort.strip().lower()
        object.__setattr__(self, "requested_reasoning_effort", requested)
        object.__setattr__(self, "reasoning_effort", actual)
        _required(
            "RouteSnapshot",
            self.route_snapshot_id,
            self.route_decision_id,
            self.operation_id,
            self.attempt_id,
            self.policy_id,
            self.backend_id,
            self.backend_version,
            self.runtime_host_id,
            self.auth_profile_ref,
            self.model_profile_id,
            self.model_profile_hash,
            self.route_policy_hash,
            self.model_provider,
            self.model_id,
            self.prompt_bundle_ref,
            self.skill_bundle_ref,
            self.context_bundle_ref,
            self.output_schema_ref,
            self.release_sha,
            self.fallback_policy_ref,
        )
        if (
            self.policy_version <= 0
            or self.model_profile_version <= 0
            or self.fallback_policy_version <= 0
        ):
            raise ValueError("RouteSnapshot versions must be positive")
        if self.route_generation <= 0 or self.route_change_index < 0:
            raise ValueError("RouteSnapshot generation is invalid")
        if self.route_generation == 1:
            if (
                self.parent_route_snapshot_id
                or self.fallback_trigger
                or self.route_change_index != 0
            ):
                raise ValueError("initial RouteSnapshot cannot claim a reroute")
        else:
            _required(
                "rerouted RouteSnapshot",
                self.parent_route_snapshot_id,
                self.fallback_trigger,
                self.quality_revalidation_ref,
            )
            if self.route_change_index != self.route_generation - 1:
                raise ValueError("RouteSnapshot route change index is invalid")
        if (
            requested not in _VALID_REASONING_EFFORTS
            or actual not in _VALID_REASONING_EFFORTS
        ):
            raise ValueError("RouteSnapshot reasoning effort is invalid")
        if requested != actual:
            raise ValueError("requested reasoning effort cannot be silently changed")
        if not _HEX_64.fullmatch(self.model_profile_hash.lower()):
            raise ValueError("RouteSnapshot ModelProfile hash must be SHA-256")
        if not _HEX_64.fullmatch(self.route_policy_hash.lower()):
            raise ValueError("RouteSnapshot RoutePolicy hash must be SHA-256")
        if not _HEX_40.fullmatch(self.release_sha.lower()):
            raise ValueError(
                "RouteSnapshot release SHA must be a full 40-character hexadecimal value"
            )

    @property
    def routing_fingerprint(self) -> str:
        payload = self.to_dict()
        payload.pop("route_snapshot_id", None)
        payload.pop("route_decision_id", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    def require_new_identity_for_change(self, previous: RouteSnapshot) -> None:
        if self.routing_fingerprint == previous.routing_fingerprint:
            return
        if self.route_snapshot_id == previous.route_snapshot_id:
            raise ValueError("route change requires a new RouteSnapshot identity")
        if self.route_decision_id == previous.route_decision_id:
            raise ValueError("route change requires a new RouteDecision identity")

    def require_qualified_binding(
        self,
        profile: ModelProfile,
        capability: ExecutionCapabilityProfile,
    ) -> None:
        capability.require_model_profile(profile)
        bindings = (
            (self.backend_id, profile.backend_id, "backend"),
            (self.backend_version, capability.backend_version, "backend version"),
            (self.model_profile_id, profile.profile_id, "ModelProfile ID"),
            (
                self.model_profile_version,
                profile.profile_version,
                "ModelProfile version",
            ),
            (self.model_profile_hash, profile.contract_hash, "ModelProfile hash"),
            (self.model_provider, profile.model_provider, "model provider"),
            (self.model_id, profile.model_id, "model ID"),
            (self.reasoning_effort, profile.reasoning_effort, "reasoning effort"),
        )
        mismatch = [label for actual, expected, label in bindings if actual != expected]
        if mismatch:
            raise ValueError(
                "RouteSnapshot does not match qualified " + ", ".join(mismatch)
            )

    def require_frozen_policy(self, policy: RoutePolicy) -> None:
        bindings = (
            (self.policy_id, policy.policy_id, "RoutePolicy ID"),
            (self.policy_version, policy.policy_version, "RoutePolicy version"),
            (self.route_policy_hash, policy.contract_hash, "RoutePolicy hash"),
        )
        mismatch = [label for actual, expected, label in bindings if actual != expected]
        if mismatch:
            raise ValueError(
                "RouteSnapshot does not match frozen " + ", ".join(mismatch)
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RouteSnapshot:
        integer_fields = {
            "policy_version",
            "model_profile_version",
            "route_generation",
            "fallback_policy_version",
            "route_change_index",
        }
        values = {
            item.name: str(payload.get(item.name) or "")
            for item in fields(cls)
            if item.name not in integer_fields
        }
        for key in integer_fields:
            default = 1 if key == "route_generation" else 0
            values[key] = _strict_int(payload.get(key, default), key)
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ExecutionRequest(_Contract):
    execution_id: str
    operation_id: str
    root_operation_id: str
    saga_id: str
    attempt_id: str
    fencing_token: int
    project_id: str
    workspace_id: str
    book_id: str
    target_scope: TargetScope
    domain: str
    task_kind: str
    stage: str
    capability: str
    importance_class: str
    risk_class: str
    route_snapshot_id: str
    workspace_snapshot_ref: str
    input_manifest_ref: str
    resource_claims: tuple[str, ...]
    timeout_policy_ref: str
    budget_policy_ref: str
    permission_policy_ref: str
    validation_policy_ref: str
    commit_policy_ref: str
    stable_idempotency_key: str
    origin_chain: tuple[str, ...] = ()
    agent_hop_count: int = 0
    trace_id: str = ""
    correlation_id: str = ""
    external_effect_id: str = ""
    budget_reservation_id: str = ""

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        scope = (
            self.target_scope
            if isinstance(self.target_scope, TargetScope)
            else TargetScope.from_dict(
                self.target_scope,
                project_id=self.project_id,
                book_id=self.book_id,
            )
        )
        object.__setattr__(self, "target_scope", scope)
        object.__setattr__(self, "resource_claims", _string_tuple(self.resource_claims))
        object.__setattr__(self, "origin_chain", _string_tuple(self.origin_chain))
        _required(
            "ExecutionRequest",
            self.execution_id,
            self.root_operation_id,
            self.saga_id,
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.domain,
            self.task_kind,
            self.stage,
            self.capability,
            self.importance_class,
            self.risk_class,
            self.route_snapshot_id,
            self.workspace_snapshot_ref,
            self.input_manifest_ref,
            self.timeout_policy_ref,
            self.budget_policy_ref,
            self.permission_policy_ref,
            self.validation_policy_ref,
            self.commit_policy_ref,
            self.stable_idempotency_key,
        )
        if not _STABLE_ALIAS.fullmatch(self.domain):
            raise ValueError("ExecutionRequest domain is invalid")
        if not _STABLE_ALIAS.fullmatch(self.capability):
            raise ValueError("ExecutionRequest capability is invalid")
        if scope.project_id and scope.project_id != self.project_id:
            raise ValueError("ExecutionRequest target scope belongs to another project")
        if scope.book_id and scope.book_id != self.book_id:
            raise ValueError("ExecutionRequest target scope belongs to another book")
        if self.agent_hop_count < 0:
            raise ValueError("ExecutionRequest agent hop count cannot be negative")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionRequest:
        values = dict(payload)
        if "workspace_snapshot_ref" not in values and "workspace_snapshot_id" in values:
            values["workspace_snapshot_ref"] = values.pop("workspace_snapshot_id")
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["agent_hop_count"] = int(values.get("agent_hop_count") or 0)
        values["resource_claims"] = _string_tuple(values.get("resource_claims"))
        values["origin_chain"] = _string_tuple(values.get("origin_chain"))
        target = values.get("target_scope")
        values["target_scope"] = (
            target
            if isinstance(target, TargetScope)
            else TargetScope.from_dict(
                dict(target or {}),
                project_id=str(values.get("project_id") or ""),
                book_id=str(values.get("book_id") or ""),
            )
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryAuthorization(_Contract):

    authorization_id: str
    execution_id: str
    external_effect_id: str
    operation_id: str
    attempt_id: str
    execution_fencing_token: int
    recovery_fencing_token: int
    recovery_worker_id: str
    action: ExecutionRecoveryAction
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        _required(
            "ExecutionRecoveryAuthorization",
            self.authorization_id,
            self.execution_id,
            self.external_effect_id,
            self.operation_id,
            self.attempt_id,
            self.recovery_worker_id,
            self.trace_id,
            self.correlation_id,
        )
        _validate_attempt(
            self.operation_id,
            self.attempt_id,
            self.execution_fencing_token,
        )
        if self.recovery_fencing_token < self.execution_fencing_token:
            raise ValueError(
                "recovery fencing token cannot precede the execution fence"
            )
        object.__setattr__(
            self,
            "action",
            ExecutionRecoveryAction(self.action),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionRecoveryAuthorization:
        values = dict(payload)
        values["execution_fencing_token"] = int(
            values.get("execution_fencing_token") or 0
        )
        values["recovery_fencing_token"] = int(
            values.get("recovery_fencing_token") or 0
        )
        values["action"] = ExecutionRecoveryAction(values.get("action"))
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ExecutionHandle(_Contract):
    execution_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    backend_execution_id: str
    backend_id: str
    transport: ExecutionRuntimeClass
    local_execution_receipt_id: str | None
    local_process_id: int | None
    local_process_group_id: int | None
    local_process_start_time: str | None
    provider_request_id: str | None
    completion_mode: CompletionMode
    query_capability: CapabilityAvailability
    cancel_capability: CapabilityAvailability
    callback_capability: CapabilityAvailability
    external_request_id: str | None = None

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(self, "transport", _as_runtime(self.transport))
        object.__setattr__(
            self, "completion_mode", _as_completion(self.completion_mode)
        )
        object.__setattr__(
            self, "query_capability", _as_capability(self.query_capability)
        )
        object.__setattr__(
            self, "cancel_capability", _as_capability(self.cancel_capability)
        )
        object.__setattr__(
            self, "callback_capability", _as_capability(self.callback_capability)
        )
        _required(
            "ExecutionHandle",
            self.execution_id,
            self.backend_execution_id,
            self.backend_id,
        )
        process_fields = (
            self.local_process_id,
            self.local_process_group_id,
            self.local_process_start_time,
        )
        if any(item is not None for item in process_fields) and not all(
            item is not None and item != "" for item in process_fields
        ):
            raise ValueError(
                "local process identity requires PID, PGID, and start time"
            )
        if self.transport is ExecutionRuntimeClass.SCRIPTED_FIXTURE and (
            self.provider_request_id or self.external_request_id
        ):
            raise ValueError("scripted fixture cannot claim a remote request ID")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionHandle:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["transport"] = _as_runtime(values.get("transport"))
        values["completion_mode"] = _as_completion(values.get("completion_mode"))
        for key in ("query_capability", "cancel_capability", "callback_capability"):
            values[key] = _as_capability(values.get(key))
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ExecutionResult(_Contract):
    execution_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    outcome: ExecutionOutcome
    process_receipt_ref: str | None
    provider_receipt_ref: str | None
    raw_output_ref: str | None
    normalized_output_ref: str | None
    output_manifest_ref: str | None
    usage_receipt_ref: str | None
    cost_receipt_ref: str | None
    validation_report_ref: str | None
    started_at: str
    completed_at: str | None
    external_receipt_ref: str | None = None

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(self, "outcome", _as_execution_outcome(self.outcome))
        _required("ExecutionResult", self.execution_id, self.started_at)
        if self.outcome is ExecutionOutcome.SUCCEEDED:
            _required(
                "successful ExecutionResult",
                self.output_manifest_ref,
                self.validation_report_ref,
                self.completed_at,
            )
        if (
            self.outcome
            in {
                ExecutionOutcome.RETRYABLE_FAILURE,
                ExecutionOutcome.FINAL_FAILURE,
                ExecutionOutcome.CANCELLED,
                ExecutionOutcome.TIMED_OUT,
                ExecutionOutcome.ORPHANED,
                ExecutionOutcome.CORRUPT_RESULT,
            }
            and not self.completed_at
        ):
            raise ValueError("terminal ExecutionResult requires completed_at")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionResult:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["outcome"] = _as_execution_outcome(values.get("outcome"))
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ExecutionCancellationResult(_Contract):
    execution_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    backend_id: str
    transport: ExecutionRuntimeClass
    outcome: CancellationOutcome
    local_termination_outcome: LocalTerminationOutcome
    upstream_cancellation_outcome: UpstreamCancellationOutcome
    local_execution_receipt_id: str | None
    provider_request_id: str | None
    provider_cancellation_receipt_ref: str | None
    reason: str
    requested_at: str
    completed_at: str | None
    external_request_id: str | None = None
    external_cancellation_receipt_ref: str | None = None
    backend_completion_receipt_ref: str | None = None

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(self, "transport", _as_runtime(self.transport))
        object.__setattr__(self, "outcome", _as_cancellation_outcome(self.outcome))
        object.__setattr__(
            self,
            "local_termination_outcome",
            _as_local_termination(self.local_termination_outcome),
        )
        object.__setattr__(
            self,
            "upstream_cancellation_outcome",
            _as_upstream_cancellation(self.upstream_cancellation_outcome),
        )
        _required(
            "ExecutionCancellationResult",
            self.execution_id,
            self.backend_id,
            self.reason,
            self.requested_at,
        )
        if self.outcome is CancellationOutcome.CANCELLED and not self.completed_at:
            raise ValueError("completed cancellation requires completed_at")
        if self.local_termination_outcome is not LocalTerminationOutcome.NOT_APPLICABLE:
            if not self.local_execution_receipt_id:
                raise ValueError("local termination requires a local execution receipt")
        if (
            self.upstream_cancellation_outcome
            is not UpstreamCancellationOutcome.NOT_APPLICABLE
        ):
            if not (self.provider_request_id or self.external_request_id):
                raise ValueError(
                    "upstream cancellation requires a real Provider or external request ID"
                )
        if (
            self.upstream_cancellation_outcome is UpstreamCancellationOutcome.CANCELLED
            and not (
                self.provider_cancellation_receipt_ref
                or self.external_cancellation_receipt_ref
            )
        ):
            raise ValueError(
                "upstream cancellation requires a Provider or external cancellation receipt"
            )
        if self.outcome is CancellationOutcome.CANCELLED:
            if (
                self.upstream_cancellation_outcome
                is UpstreamCancellationOutcome.ALREADY_COMPLETED
            ):
                raise ValueError(
                    "upstream ALREADY_COMPLETED cannot be reported as CANCELLED"
                )
            local_cancelled = (
                self.local_termination_outcome is LocalTerminationOutcome.TERMINATED
            )
            upstream_cancelled = (
                self.upstream_cancellation_outcome
                is UpstreamCancellationOutcome.CANCELLED
            )
            if not local_cancelled and not upstream_cancelled:
                raise ValueError(
                    "cancelled execution requires terminal local or upstream evidence"
                )
        if self.outcome is CancellationOutcome.ALREADY_COMPLETED:
            already_complete = (
                self.local_termination_outcome is LocalTerminationOutcome.ALREADY_EXITED
                or self.upstream_cancellation_outcome
                is UpstreamCancellationOutcome.ALREADY_COMPLETED
                or bool(self.backend_completion_receipt_ref)
            )
            if not already_complete:
                raise ValueError(
                    "ALREADY_COMPLETED requires matching local or upstream evidence"
                )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionCancellationResult:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["transport"] = _as_runtime(values.get("transport"))
        values["outcome"] = _as_cancellation_outcome(values.get("outcome"))
        values["local_termination_outcome"] = _as_local_termination(
            values.get("local_termination_outcome")
        )
        values["upstream_cancellation_outcome"] = _as_upstream_cancellation(
            values.get("upstream_cancellation_outcome")
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@runtime_checkable
class ExecutionBackend(Protocol):
    backend_id: str
    capability_profile: ExecutionCapabilityProfile

    def submit(self, request: ExecutionRequest) -> ExecutionHandle: ...

    def submit_recovered(
        self,
        request: ExecutionRequest,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionHandle: ...

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult: ...

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult: ...


@dataclass(frozen=True, slots=True)
class InputManifest(_HashedContract):
    manifest_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    project_id: str
    book_id: str
    target_scope: TargetScope
    context_bundle_ref: str
    prompt_bundle_ref: str
    skill_bundle_ref: str
    context_bundle_version: str
    prompt_bundle_version: str
    skill_bundle_version: str
    canon_snapshot_version: str
    story_state_version: str
    planning_version: str
    quality_profile_version: str
    source_policy_ref: str
    source_eligibility: str
    canon_version_refs: tuple[str, ...]
    arc_version_refs: tuple[str, ...]
    input_artifacts: tuple[ArtifactPointer, ...]
    read_set: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(
            self, "canon_version_refs", _string_tuple(self.canon_version_refs)
        )
        object.__setattr__(
            self, "arc_version_refs", _string_tuple(self.arc_version_refs)
        )
        object.__setattr__(self, "input_artifacts", tuple(self.input_artifacts))
        object.__setattr__(self, "read_set", _string_tuple(self.read_set))
        scope = (
            self.target_scope
            if isinstance(self.target_scope, TargetScope)
            else TargetScope.from_dict(
                self.target_scope,
                project_id=self.project_id,
                book_id=self.book_id,
            )
        )
        object.__setattr__(self, "target_scope", scope)
        _required(
            "InputManifest",
            self.manifest_id,
            self.project_id,
            self.book_id,
            self.context_bundle_ref,
            self.prompt_bundle_ref,
            self.skill_bundle_ref,
            self.context_bundle_version,
            self.prompt_bundle_version,
            self.skill_bundle_version,
            self.canon_snapshot_version,
            self.story_state_version,
            self.planning_version,
            self.quality_profile_version,
            self.source_policy_ref,
            self.source_eligibility,
        )
        if not self.input_artifacts or not self.read_set:
            raise ValueError(
                "InputManifest requires artifacts and an explicit read set"
            )
        if self.source_eligibility not in {
            "PRODUCTION_ELIGIBLE",
            "NOT_SOURCE_DERIVED",
            "FIXTURE_ELIGIBLE",
            "SOURCE_ANALYSIS_ONLY",
        }:
            raise ValueError("InputManifest source eligibility is not execution-safe")
        if any(
            item.source_eligibility
            not in {
                self.source_eligibility,
                "NOT_SOURCE_DERIVED",
            }
            for item in self.input_artifacts
        ):
            raise ValueError(
                "InputManifest source eligibility conflicts with an input AssetVersion"
            )
        if scope.project_id and scope.project_id != self.project_id:
            raise ValueError("InputManifest target scope belongs to another project")
        if scope.book_id and scope.book_id != self.book_id:
            raise ValueError("InputManifest target scope belongs to another book")
        artifact_refs = {item.artifact_ref for item in self.input_artifacts}
        if not artifact_refs.issubset(set(self.read_set)):
            raise ValueError("InputManifest read set must contain every input artifact")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> InputManifest:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        target = values.get("target_scope")
        values["target_scope"] = (
            target
            if isinstance(target, TargetScope)
            else TargetScope.from_dict(
                dict(target or {}),
                project_id=str(values.get("project_id") or ""),
                book_id=str(values.get("book_id") or ""),
            )
        )
        values["canon_version_refs"] = _string_tuple(values.get("canon_version_refs"))
        values["arc_version_refs"] = _string_tuple(values.get("arc_version_refs"))
        values["input_artifacts"] = tuple(
            item
            if isinstance(item, ArtifactPointer)
            else ArtifactPointer.from_dict(item)
            for item in values.get("input_artifacts") or ()
        )
        values["read_set"] = _string_tuple(values.get("read_set"))
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ExecutionManifest(_HashedContract):
    manifest_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    route_snapshot_id: str
    input_manifest_ref: str
    backend_id: str
    backend_version: str
    runtime_host_id: str
    auth_profile_ref: str
    cli_version: str | None
    command_summary: tuple[str, ...]
    environment_allowlist_name: str
    timeout_seconds: int
    release_sha: str
    credential_scope: str = ""
    secret_version_ref: str = ""

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(self, "command_summary", _string_tuple(self.command_summary))
        _required(
            "ExecutionManifest",
            self.manifest_id,
            self.route_snapshot_id,
            self.input_manifest_ref,
            self.backend_id,
            self.backend_version,
            self.runtime_host_id,
            self.auth_profile_ref,
            self.environment_allowlist_name,
            self.release_sha,
        )
        if self.timeout_seconds <= 0:
            raise ValueError("ExecutionManifest timeout must be positive")
        if not self.command_summary:
            raise ValueError("ExecutionManifest requires a redacted command summary")
        if not _HEX_40.fullmatch(self.release_sha.lower()):
            raise ValueError("ExecutionManifest release SHA must be full length")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionManifest:
        values = dict(payload)
        values.setdefault("credential_scope", "")
        values.setdefault("secret_version_ref", "")
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["timeout_seconds"] = int(values.get("timeout_seconds") or 0)
        values["command_summary"] = _string_tuple(values.get("command_summary"))
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class OutputManifest(_HashedContract):
    manifest_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    raw_output_ref: str | None
    normalized_output_ref: str | None
    stdout_ref: str | None
    stderr_ref: str | None
    output_hash: str
    schema_version: str
    files: tuple[ArtifactPointer, ...]

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(self, "files", tuple(self.files))
        _required(
            "OutputManifest", self.manifest_id, self.output_hash, self.schema_version
        )
        if not _is_sha256(self.output_hash):
            raise ValueError("OutputManifest output hash must be SHA-256")
        if not self.raw_output_ref and not self.normalized_output_ref:
            raise ValueError("OutputManifest requires raw or normalized output")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> OutputManifest:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["files"] = tuple(
            item
            if isinstance(item, ArtifactPointer)
            else ArtifactPointer.from_dict(item)
            for item in values.get("files") or ()
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ValidationManifest(_HashedContract):
    manifest_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    output_manifest_ref: str
    validation_policy_ref: str
    required_check_kinds: tuple[str, ...]
    checks: tuple[ValidationCheck, ...]
    decision: str

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(
            self, "required_check_kinds", _string_tuple(self.required_check_kinds)
        )
        _required(
            "ValidationManifest",
            self.manifest_id,
            self.output_manifest_ref,
            self.validation_policy_ref,
            self.decision,
        )
        if self.decision not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("ValidationManifest decision is invalid")
        if not self.checks:
            raise ValueError("ValidationManifest requires validation checks")
        if not self.required_check_kinds or "fencing" not in self.required_check_kinds:
            raise ValueError("ValidationManifest policy must require fencing")
        available = {item.check_kind for item in self.checks}
        if set(self.required_check_kinds) - available:
            raise ValueError("ValidationManifest is missing required checks")
        statuses = {item.status for item in self.checks}
        if self.decision == "ACCEPTED" and statuses - {"PASSED", "NOT_APPLICABLE"}:
            raise ValueError(
                "ValidationManifest cannot accept failed or review-required checks"
            )
        if not any(item.check_kind == "fencing" for item in self.checks):
            raise ValueError("ValidationManifest requires fencing validation")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ValidationManifest:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        values["checks"] = tuple(
            item
            if isinstance(item, ValidationCheck)
            else ValidationCheck.from_dict(item)
            for item in values.get("checks") or ()
        )
        values["required_check_kinds"] = _string_tuple(
            values.get("required_check_kinds")
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class CommitManifest(_HashedContract):
    manifest_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    validation_manifest_ref: str
    committed_asset_version_refs: tuple[str, ...]
    authority_commit_ref: str
    projection_materialization_refs: tuple[str, ...]
    rejected_output_refs: tuple[str, ...]
    rollback_ref: str
    decision: str

    def __post_init__(self) -> None:
        _validate_attempt(self.operation_id, self.attempt_id, self.fencing_token)
        object.__setattr__(
            self,
            "committed_asset_version_refs",
            _string_tuple(self.committed_asset_version_refs),
        )
        object.__setattr__(
            self,
            "projection_materialization_refs",
            _string_tuple(self.projection_materialization_refs),
        )
        object.__setattr__(
            self, "rejected_output_refs", _string_tuple(self.rejected_output_refs)
        )
        _required(
            "CommitManifest",
            self.manifest_id,
            self.validation_manifest_ref,
            self.rollback_ref,
            self.decision,
        )
        if self.decision not in {"COMMITTED", "REJECTED"}:
            raise ValueError("CommitManifest decision is invalid")
        if self.decision == "COMMITTED":
            if not self.committed_asset_version_refs:
                raise ValueError("committed AssetVersion evidence is required")
            if not self.authority_commit_ref:
                raise ValueError("Authority commit evidence is required")
        if self.decision == "REJECTED" and not self.rejected_output_refs:
            raise ValueError(
                "rejected CommitManifest requires rejected output evidence"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CommitManifest:
        values = dict(payload)
        values["fencing_token"] = int(values.get("fencing_token") or 0)
        for key in (
            "committed_asset_version_refs",
            "projection_materialization_refs",
            "rejected_output_refs",
        ):
            values[key] = _string_tuple(values.get(key))
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})
