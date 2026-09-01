from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping

from novel_forge.modules.production_execution.security import assert_no_inline_secrets


D0_GATE_NAMES = (
    "real_provider_auth_proven",
    "durable_intent_before_send_proven",
    "provider_request_receipt_proven",
    "provider_usage_cost_latency_proven",
    "ambiguous_outcome_fail_closed",
    "recovery_without_duplicate_send",
)

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class D0ProbeConfig:
    provider: str
    backend_id: str
    model_env: str
    model_version_env: str
    route_policy_version: str
    timeout_seconds: int
    auth_secret_ref: str
    capability: str
    prompt_version: str
    skill_version: str
    schema_version: str = "d0-provider-probe-config.v1"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "D0ProbeConfig":
        allowed = {
            "schema_version", "provider", "backend_id", "model_env",
            "model_version_env", "route_policy_version", "timeout_seconds",
            "auth_secret_ref", "capability", "prompt_version", "skill_version",
        }
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise ValueError(f"D0 config has unsupported fields: {', '.join(unexpected)}")
        if payload.get("schema_version") != "d0-provider-probe-config.v1":
            raise ValueError("D0 config schema_version is unsupported")
        values = {
            key: str(payload.get(key) or "").strip()
            for key in (
                "provider", "backend_id", "model_env", "model_version_env",
                "route_policy_version", "auth_secret_ref", "capability",
                "prompt_version", "skill_version",
            )
        }
        if not all(values.values()):
            raise ValueError("D0 config is incomplete")
        if not values["auth_secret_ref"].startswith("env://"):
            raise ValueError("D0 auth must be a Secret Reference, never a secret value")
        timeout = payload.get("timeout_seconds")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("D0 timeout_seconds must be positive")
        return cls(**values, timeout_seconds=timeout)

    @property
    def auth_environment_name(self) -> str:
        return self.auth_secret_ref.removeprefix("env://")


@dataclass(frozen=True, slots=True)
class D0ProbeReport:
    status: str
    blocker: str
    provider: str
    backend_id: str
    model: str
    model_version: str
    route_policy_version: str
    timeout_seconds: int
    cancel_capability: str
    query_capability: str
    provider_request_id: str
    raw_usage: dict[str, Any]
    normalized_usage: dict[str, Any]
    provider_cost: dict[str, Any]
    calculated_cost: dict[str, Any]
    receipt: dict[str, Any]
    request_object_ref: str
    response_object_ref: str
    contract_checks: dict[str, bool]
    gates: dict[str, bool]
    fixture_protocol_only: bool
    external_execution_proven: bool
    schema_version: str = "d0-provider-probe-report.v1"

    def __post_init__(self) -> None:
        if self.status not in {"PASSED", "FAILED", "BLOCKED_MISSING_CREDENTIALS", "BLOCKED_CONFIGURATION"}:
            raise ValueError("D0 report status is invalid")
        if set(self.gates) != set(D0_GATE_NAMES):
            raise ValueError("D0 report does not declare every gate")
        if self.fixture_protocol_only and any(self.gates.values()):
            raise ValueError("fixture protocol evidence cannot pass real Provider gates")
        if self.status.startswith("BLOCKED") and any(self.gates.values()):
            raise ValueError("a blocked D0 probe cannot pass a real Provider gate")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class D0LiveQualificationEvidence:
    release_sha: str
    implementation_identity: str
    source_operation_id: str
    external_effect_id: str
    request_object_ref: str
    response_object_ref: str
    auth_profile_ref: str
    provider: str
    backend_id: str
    model: str
    model_version: str
    route_snapshot_id: str
    route_snapshot_hash: str
    prompt_version: str
    prompt_hash: str
    instruction_version: str
    instruction_hash: str
    skill_version: str
    skill_hash: str
    request_hash: str
    response_hash: str
    provider_execution_id: str
    provider_request_identity: str
    usage: dict[str, Any]
    cost: dict[str, Any]
    latency: dict[str, Any]
    controlled_failure: dict[str, Any]
    recovery: dict[str, Any]
    dispatch_count: int
    receipt_count: int
    provider_execution_count: int
    duplicate_external_effect_count: int
    fixture_protocol_only: bool
    real_model_call: bool
    schema_version: str = "d0-live-qualification-evidence.v1"

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any]
    ) -> "D0LiveQualificationEvidence":
        if payload.get("fixture_protocol_only") is not False:
            raise ValueError("fixture evidence cannot qualify a real Provider")
        if payload.get("real_model_call") is not True:
            raise ValueError("live qualification requires a real model call")
        if payload.get("schema_version") != "d0-live-qualification-evidence.v1":
            raise ValueError("live qualification evidence schema is unsupported")
        allowed = set(cls.__dataclass_fields__)
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise ValueError(
                "live qualification evidence has unsupported fields: "
                + ", ".join(unexpected)
            )
        required_text = (
            "release_sha",
            "implementation_identity",
            "source_operation_id",
            "external_effect_id",
            "request_object_ref",
            "response_object_ref",
            "auth_profile_ref",
            "provider",
            "backend_id",
            "model",
            "model_version",
            "route_snapshot_id",
            "route_snapshot_hash",
            "prompt_version",
            "prompt_hash",
            "instruction_version",
            "instruction_hash",
            "skill_version",
            "skill_hash",
            "request_hash",
            "response_hash",
            "provider_execution_id",
            "provider_request_identity",
        )
        text_values = {
            name: str(payload.get(name) or "").strip() for name in required_text
        }
        if not all(text_values.values()):
            raise ValueError("live qualification evidence identity is incomplete")
        if not _GIT_SHA.fullmatch(text_values["release_sha"]):
            raise ValueError("live qualification release SHA is invalid")
        for name in (
            "implementation_identity",
            "route_snapshot_hash",
            "prompt_hash",
            "instruction_hash",
            "skill_hash",
            "request_hash",
            "response_hash",
        ):
            if not _SHA256.fullmatch(text_values[name]):
                raise ValueError(f"live qualification {name} is invalid")
        mappings: dict[str, dict[str, Any]] = {}
        for name in (
            "usage",
            "cost",
            "latency",
            "controlled_failure",
            "recovery",
        ):
            value = payload.get(name)
            if not isinstance(value, Mapping):
                raise ValueError(f"live qualification {name} evidence is missing")
            mappings[name] = dict(value)
        usage = mappings["usage"]
        if (
            usage.get("measurement") != "MEASURED"
            or not isinstance(usage.get("total_tokens"), int)
            or isinstance(usage.get("total_tokens"), bool)
            or int(usage["total_tokens"]) <= 0
        ):
            raise ValueError("live qualification requires measured Provider usage")
        cost = mappings["cost"]
        try:
            amount = Decimal(str(cost.get("amount") or ""))
        except InvalidOperation as exc:
            raise ValueError("live qualification cost amount is invalid") from exc
        if amount < 0 or not str(cost.get("currency") or "").strip():
            raise ValueError("live qualification cost evidence is invalid")
        if not _SHA256.fullmatch(str(cost.get("pricing_snapshot_hash") or "")):
            raise ValueError("live qualification pricing identity is invalid")
        duration_ms = mappings["latency"].get("duration_ms")
        if (
            not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
            or duration_ms <= 0
        ):
            raise ValueError("live qualification latency evidence is invalid")
        failure = mappings["controlled_failure"]
        if (
            failure.get("checkpoint")
            != "after_provider_response_before_effect_receipt"
            or failure.get("request_sent") is not True
        ):
            raise ValueError("controlled Provider failure evidence is incomplete")
        recovery = mappings["recovery"]
        if any(
            recovery.get(name) is not True
            for name in (
                "external_state_was_ambiguous",
                "recovered_without_resend",
                "replayed",
            )
        ):
            raise ValueError("ambiguous Provider recovery evidence is incomplete")
        counts = {
            name: payload.get(name)
            for name in (
                "dispatch_count",
                "receipt_count",
                "provider_execution_count",
                "duplicate_external_effect_count",
            )
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in counts.values()
        ):
            raise ValueError("live qualification execution counts are invalid")
        if (
            counts["dispatch_count"] != 1
            or counts["receipt_count"] != 1
            or counts["provider_execution_count"] != 1
            or counts["duplicate_external_effect_count"] != 0
        ):
            raise ValueError("duplicate Provider execution is not qualifiable")
        normalized = {
            **text_values,
            **mappings,
            **counts,
            "fixture_protocol_only": False,
            "real_model_call": True,
            "schema_version": "d0-live-qualification-evidence.v1",
        }
        assert_no_inline_secrets(
            normalized, label="D0 live qualification evidence"
        )
        return cls(**normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def request_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "D0_GATE_NAMES",
    "D0LiveQualificationEvidence",
    "D0ProbeConfig",
    "D0ProbeReport",
    "request_hash",
]
