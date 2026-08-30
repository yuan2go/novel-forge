from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping


D0_GATE_NAMES = (
    "real_provider_auth_proven",
    "provider_request_receipt_proven",
    "provider_usage_proven",
    "provider_cost_proven",
    "provider_timeout_query_cancel_behavior_recorded",
    "unknown_reconciliation_proven",
)


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


def request_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["D0_GATE_NAMES", "D0ProbeConfig", "D0ProbeReport", "request_hash"]
