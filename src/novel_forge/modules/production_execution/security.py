"""Fail-closed security checks for durable production-execution contracts.

Execution contracts and evidence may name a credential, but they must never carry
the credential value.  This module is intentionally independent from the
execution contracts so every persistence and transport boundary can reuse it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
import os
import re
from typing import Any


_ALLOWED_CREDENTIAL_REFERENCE_KEYS = frozenset(
    {
        "auth_profile_ref",
        "credential_scope",
        "secret_version_ref",
    }
)
CONTROLLED_EXECUTION_ENVIRONMENTS = frozenset(
    {"validation", "provider-validation", "production"}
)
_ALLOWED_TOKEN_EVIDENCE_KEYS = frozenset(
    {
        "fencing_token",
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
    """Reject credential keys or high-confidence credential values recursively."""

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


def execution_environment(value: str = "") -> str:
    return str(
        value or os.environ.get("NOVEL_FORGE_ENVIRONMENT") or "development"
    ).strip().lower()


def assert_legacy_execution_allowed(
    *,
    component: str,
    gateway_backed: bool,
    environment: str = "",
) -> None:
    """Block compatibility execution before a network/process call in control mode."""

    normalized = execution_environment(environment)
    if normalized in CONTROLLED_EXECUTION_ENVIRONMENTS and not gateway_backed:
        raise RuntimeError(
            f"{component} legacy execution is blocked and disabled in {normalized}; "
            "use ProductionExecutionGateway through an Authority-bound request"
        )


__all__ = [
    "CONTROLLED_EXECUTION_ENVIRONMENTS",
    "assert_legacy_execution_allowed",
    "assert_no_inline_secrets",
    "execution_environment",
]
