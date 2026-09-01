"""SECURITY: durable contracts may name a credential but must never contain its value."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
import json
import logging
import os
import re
from typing import Any, Callable
import uuid

from novel_forge.infrastructure.environment import RuntimeEnvironment


_ALLOWED_CREDENTIAL_REFERENCE_KEYS = frozenset(
    {
        "auth_profile_ref",
        "credential_scope",
        "secret_version_ref",
    }
)
CONTROLLED_EXECUTION_ENVIRONMENTS = frozenset(
    environment.value
    for environment in RuntimeEnvironment
    if environment.controlled
)
_ALLOWED_TOKEN_EVIDENCE_KEYS = frozenset(
    {
        "fencing_token",
        "execution_fencing_token",
        "recovery_fencing_token",
        "process_start_token",
        "supervisor_process_start_token",
        "input_token",
        "input_tokens",
        "output_token",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "total_tokens",
        "maximum_tokens",
        "max_tokens",
        "token_count",
        "token_budget",
    }
)
_PROHIBITED_EXACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "passwd",
        "authorization",
        "proxy_authorization",
        "access_token",
        "refresh_token",
        "bearer_token",
        "client_secret",
        "private_key",
        "secret",
        "credential",
        "credentials",
    }
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bbearer\s+[a-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-(?:proj-|ant-)?[a-z0-9_-]{8,}", re.IGNORECASE),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*[^\s,;]{8,}",
        re.IGNORECASE,
    ),
)
_LEGACY_USAGE_LOGGER = logging.getLogger(
    "novel_forge.production_execution.legacy_usage"
)


@dataclass(frozen=True, slots=True)
class LegacyUsageEvent:

    schema_version: str
    event_id: str
    occurred_at: str
    component: str
    environment: str
    decision: str
    gateway_backed: bool
    production_proof_eligible: bool = False
    production_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _is_prohibited_key(key: str) -> bool:
    if key in _ALLOWED_CREDENTIAL_REFERENCE_KEYS:
        return False
    if key in _ALLOWED_TOKEN_EVIDENCE_KEYS or key.endswith("_tokens"):
        return False
    if key in _PROHIBITED_EXACT_KEYS:
        return True
    if key.endswith(("_api_key", "_password", "_client_secret", "_private_key")):
        return True
    if key.endswith("_token") and not key.endswith("_version_token"):
        return True
    if key.endswith("_credential") or key.endswith("_credentials"):
        return True
    return False


def _contains_secret_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def assert_no_inline_secrets(
    payload: Any,
    *,
    label: str = "production execution payload",
) -> None:

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Enum):
            visit(value.value, path)
            return
        if isinstance(value, Mapping):
            for raw_key, item in value.items():
                key = _normalized_key(raw_key)
                child_path = f"{path}.{raw_key}"
                if _is_prohibited_key(key):
                    raise ValueError(
                        f"{label} contains inline secret material at {child_path}; "
                        "store auth_profile_ref, credential_scope, and "
                        "secret_version_ref instead"
                    )
                visit(item, child_path)
            return
        if isinstance(value, str):
            if _contains_secret_value(value):
                raise ValueError(
                    f"{label} contains inline secret material at {path}; "
                    "store a governed credential reference instead"
                )
            return
        if isinstance(value, Sequence) and not isinstance(
            value, (bytes, bytearray, memoryview)
        ):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(payload, "$")


def execution_environment(value: str = "") -> RuntimeEnvironment:
    raw = str(
        value or os.environ.get("NOVEL_FORGE_ENVIRONMENT") or "development"
    ).strip().lower()
    # COMPATIBILITY: normalize the accepted OS-envelope aliases once at the
    # execution boundary so downstream policy receives one typed environment.
    normalized = {
        "dev": "development",
        "local": "development",
        "sample": "development",
        "fixture": "development",
        "compat": "development",
        "prod": "production",
        "operating_system": "production",
        "strict": "production",
    }.get(raw, raw)
    return RuntimeEnvironment.parse(normalized)


def assert_legacy_execution_allowed(
    *,
    component: str,
    gateway_backed: bool,
    environment: str = "",
    recorder: Callable[[LegacyUsageEvent], None] | None = None,
) -> LegacyUsageEvent:

    normalized = execution_environment(environment)
    blocked = (
        normalized.controlled
        and not gateway_backed
    )
    event = LegacyUsageEvent(
        schema_version="legacy-usage-event.v1",
        event_id=f"legacy-usage:{uuid.uuid4()}",
        occurred_at=datetime.now(UTC).isoformat(),
        component=component,
        environment=normalized,
        decision=(
            "GATEWAY_BACKED"
            if gateway_backed
            else "BLOCKED_CONTROLLED"
            if blocked
            else "ALLOWED_DEVELOPMENT_ONLY"
        ),
        gateway_backed=gateway_backed,
    )
    if recorder is not None:
        recorder(event)
    _LEGACY_USAGE_LOGGER.info(
        json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
    )
    if blocked:
        raise RuntimeError(
            f"{component} legacy execution is blocked and disabled in {normalized}; "
            "use ProductionExecutionGateway through an Authority-bound request"
        )
    return event


__all__ = [
    "CONTROLLED_EXECUTION_ENVIRONMENTS",
    "LegacyUsageEvent",
    "assert_legacy_execution_allowed",
    "assert_no_inline_secrets",
    "execution_environment",
]
