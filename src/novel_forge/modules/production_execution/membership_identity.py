from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def observe_membership_identity(codex_home: str) -> dict[str, str]:
    path = Path(codex_home) / "auth.json"
    try:
        auth: Any = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("CODEX_MEMBERSHIP_AUTH_UNAVAILABLE") from exc
    if (not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt"
            or auth.get("OPENAI_API_KEY") or not isinstance(auth.get("tokens"), dict)):
        raise ValueError("CODEX_MEMBERSHIP_AUTH_REQUIRED")
    tokens = auth["tokens"]
    if not all(isinstance(tokens.get(key), str) and tokens[key].strip()
               for key in ("account_id", "access_token", "refresh_token")):
        raise ValueError("CODEX_MEMBERSHIP_IDENTITY_INCOMPLETE")
    account = hashlib.sha256(tokens["account_id"].encode()).hexdigest()
    return {"version": "codex-membership-identity.v1", "auth_mode": "chatgpt",
            "billing_channel": "ACCOUNT_ENTITLEMENT", "account_ref": "codex-account:sha256:" + account}


def require_membership_identity(codex_home: str, expected: dict[str, str]) -> None:
    if observe_membership_identity(codex_home) != expected:
        raise ValueError("CODEX_MEMBERSHIP_IDENTITY_DRIFT")


def observed_paid_binding(account_ref: str, credential: str) -> dict[str, str]:
    if not account_ref.strip() or not credential.strip():
        return {}
    return {"version": "configured-api-billing-binding.v1", "provider": "deepseek",
            "account_ref": account_ref, "credential_ref": "sha256:" + hashlib.sha256(credential.encode()).hexdigest()}
