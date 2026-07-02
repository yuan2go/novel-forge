from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ProviderRuntimeGuardViolation(RuntimeError):
    """Raised when live provider usage violates token, timeout, or cancel guard."""


@dataclass(frozen=True)
class ProviderRuntimeGuard:
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    max_total_tokens: int = 0
    max_cost: float = 0.0
    timeout_ms: int = 0
    cancel_file: str = ""
    cancel_requested: bool = False
    cost_profile: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProviderRuntimeGuard":
        payload = data or {}
        max_total = _int(payload.get("max_total_tokens", payload.get("max_tokens", payload.get("token_cutoff", 0))))
        return cls(
            max_input_tokens=_int(payload.get("max_input_tokens", payload.get("input_token_cutoff", 0))),
            max_output_tokens=_int(payload.get("max_output_tokens", payload.get("output_token_cutoff", 0))),
            max_total_tokens=max_total,
            max_cost=_float(payload.get("max_cost", payload.get("max_cost_usd", payload.get("cost_cutoff", 0.0)))),
            timeout_ms=_int(payload.get("timeout_ms", payload.get("max_elapsed_ms", 0))),
            cancel_file=str(payload.get("cancel_file", "") or ""),
            cancel_requested=bool(payload.get("cancel_requested", False)),
            cost_profile=payload.get("cost_profile", {}) if isinstance(payload.get("cost_profile", {}), dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    elapsed_ms: int = 0
    provider_request_id: str = ""
    finish_reason: str = ""
    usage_source: str = "estimated"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderRuntimeEvent:
    event_type: str
    operation: str = ""
    provider: str = ""
    message: str = ""
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    guard: ProviderRuntimeGuard = field(default_factory=ProviderRuntimeGuard)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["usage"] = self.usage.to_dict()
        data["guard"] = self.guard.to_dict()
        return data


class ProviderRuntimeController:
    """Live usage/cancel guard for provider calls.

    Providers that stream usage can call `observe_usage_delta` for each chunk.
    Non-streaming providers can still use `start` and `finish` so every adapter
    emits the same runtime event contract.
    """

    def __init__(self, *, operation: str, provider: str = "", guard: ProviderRuntimeGuard | dict[str, Any] | None = None) -> None:
        self.operation = operation
        self.provider = provider
        self.guard = guard if isinstance(guard, ProviderRuntimeGuard) else ProviderRuntimeGuard.from_dict(guard if isinstance(guard, dict) else {})
        self.usage = ProviderUsage().to_dict()
        self.events: list[dict[str, Any]] = []
        self.status = "prepared"
        self.message = ""

    def start(self) -> dict[str, Any]:
        result = evaluate_provider_runtime_guard(operation=self.operation, provider=self.provider, usage=self.usage, guard=self.guard, phase="preflight")
        self.events.extend(result.get("events", []))
        self.status = "running" if result.get("status") == "passed" else "failed"
        self.message = str(result.get("message", ""))
        if result.get("status") == "failed":
            raise ProviderRuntimeGuardViolation(self.message)
        return result

    def observe_usage_delta(self, usage_delta: dict[str, Any] | None = None, *, elapsed_ms: int = 0) -> dict[str, Any]:
        delta = normalize_provider_usage(usage_delta or {}, elapsed_ms=elapsed_ms, usage_source=str((usage_delta or {}).get("usage_source", "provider_stream") if isinstance(usage_delta, dict) else "provider_stream"))
        self.usage = _merge_usage(self.usage, delta, elapsed_ms=elapsed_ms)
        result = evaluate_provider_runtime_guard(operation=self.operation, provider=self.provider, usage=self.usage, guard=self.guard, phase="stream")
        self.events.extend(result.get("events", []))
        self.message = str(result.get("message", ""))
        if result.get("status") == "failed":
            self.status = "failed"
            raise ProviderRuntimeGuardViolation(self.message)
        self.status = "running"
        return result

    def cancel_if_requested(self) -> dict[str, Any]:
        result = evaluate_provider_runtime_guard(operation=self.operation, provider=self.provider, usage=self.usage, guard=self.guard, phase="stream")
        self.events.extend(result.get("events", []))
        self.message = str(result.get("message", ""))
        if result.get("status") == "failed" and result.get("error_type") == "ProviderExecutionCancelled":
            self.status = "cancelled"
            raise ProviderRuntimeGuardViolation(self.message)
        return result

    def finish(self, usage: dict[str, Any] | None = None, *, elapsed_ms: int = 0) -> dict[str, Any]:
        if usage:
            self.usage = normalize_provider_usage(usage, elapsed_ms=elapsed_ms, usage_source=str(usage.get("usage_source", "provider") if isinstance(usage, dict) else "provider"))
        elif elapsed_ms:
            self.usage = {**self.usage, "elapsed_ms": max(_int(self.usage.get("elapsed_ms", 0)), elapsed_ms)}
        result = evaluate_provider_runtime_guard(operation=self.operation, provider=self.provider, usage=self.usage, guard=self.guard, phase="postflight")
        self.events.extend(result.get("events", []))
        self.status = "succeeded" if result.get("status") == "passed" else "failed"
        self.message = str(result.get("message", ""))
        if result.get("status") == "failed":
            raise ProviderRuntimeGuardViolation(self.message)
        return result

    def fail(self, message: str) -> dict[str, Any]:
        self.status = "failed"
        self.message = message
        event = _event("provider_call_failed", self.operation, self.provider, self.usage, self.guard, message)
        self.events.append(event)
        return {"status": "failed", "message": message, "usage": self.usage, "events": list(self.events)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "provider": self.provider,
            "status": self.status,
            "message": self.message,
            "usage": self.usage,
            "guard": self.guard.to_dict(),
            "events": list(self.events),
        }


def provider_runtime_controller(*, operation: str, provider: str = "", guard: ProviderRuntimeGuard | dict[str, Any] | None = None) -> ProviderRuntimeController:
    return ProviderRuntimeController(operation=operation, provider=provider, guard=guard)


def provider_runtime_guard_from_context(context: dict[str, Any] | None) -> ProviderRuntimeGuard:
    payload = context or {}
    if not isinstance(payload, dict):
        payload = {}
    guard = payload.get("provider_runtime_guard", payload.get("runtime_guard", {}))
    if not isinstance(guard, dict):
        guard = {}
    return ProviderRuntimeGuard.from_dict(guard)


def normalize_provider_usage(data: dict[str, Any] | None, *, elapsed_ms: int = 0, usage_source: str = "estimated") -> dict[str, Any]:
    payload = data or {}
    if not isinstance(payload, dict):
        payload = {}
    input_tokens = _int(
        payload.get(
            "input_tokens",
            payload.get("prompt_tokens", payload.get("prompt_token_count", payload.get("tokens_in", 0))),
        )
    )
    output_tokens = _int(
        payload.get(
            "output_tokens",
            payload.get("completion_tokens", payload.get("completion_token_count", payload.get("tokens_out", 0))),
        )
    )
    total_tokens = _int(payload.get("total_tokens", payload.get("total_token_count", 0)))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    usage = ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=_int(payload.get("cached_tokens", payload.get("prompt_tokens_details", {}).get("cached_tokens", 0) if isinstance(payload.get("prompt_tokens_details"), dict) else 0)),
        reasoning_tokens=_int(payload.get("reasoning_tokens", payload.get("completion_tokens_details", {}).get("reasoning_tokens", 0) if isinstance(payload.get("completion_tokens_details"), dict) else 0)),
        elapsed_ms=max(_int(payload.get("elapsed_ms", 0)), _int(elapsed_ms)),
        provider_request_id=str(payload.get("provider_request_id", payload.get("request_id", payload.get("id", ""))) or ""),
        finish_reason=str(payload.get("finish_reason", "") or ""),
        usage_source=str(payload.get("usage_source", payload.get("token_source", usage_source)) or usage_source),
    )
    return usage.to_dict()


def estimate_usage_from_text(input_text: str = "", output_text: str = "", *, elapsed_ms: int = 0, usage_source: str = "estimated") -> dict[str, Any]:
    input_tokens = _rough_token_count(input_text)
    output_tokens = _rough_token_count(output_text)
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        elapsed_ms=elapsed_ms,
        usage_source=usage_source,
    ).to_dict()


def estimate_provider_cost(usage: dict[str, Any], cost_profile: dict[str, Any] | None, *, currency: str = "USD") -> dict[str, Any]:
    profile = cost_profile or {}
    input_per_1k = _float(profile.get("input_per_1k", profile.get("prompt_per_1k", 0.0)))
    output_per_1k = _float(profile.get("output_per_1k", profile.get("completion_per_1k", 0.0)))
    total_per_1k = _float(profile.get("total_per_1k", profile.get("per_1k", 0.0)))
    input_tokens = _int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    output_tokens = _int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
    total_tokens = _int(usage.get("total_tokens", input_tokens + output_tokens))
    amount = 0.0
    if total_per_1k > 0:
        amount = total_tokens * total_per_1k / 1000.0
    else:
        amount = (input_tokens * input_per_1k + output_tokens * output_per_1k) / 1000.0
    return {"amount": round(max(0.0, amount), 8), "currency": str(profile.get("currency", currency) or currency), "source": "provider_usage"}


def evaluate_provider_runtime_guard(
    *,
    operation: str,
    provider: str = "",
    usage: dict[str, Any] | None = None,
    guard: ProviderRuntimeGuard | dict[str, Any] | None = None,
    phase: str = "postflight",
) -> dict[str, Any]:
    resolved_guard = guard if isinstance(guard, ProviderRuntimeGuard) else ProviderRuntimeGuard.from_dict(guard if isinstance(guard, dict) else {})
    normalized_usage = normalize_provider_usage(usage or {}, elapsed_ms=_int((usage or {}).get("elapsed_ms", 0)), usage_source=str((usage or {}).get("usage_source", "estimated") if isinstance(usage, dict) else "estimated"))
    failures: list[str] = []
    error_type = "ProviderRuntimeGuardFailed"
    events = [
        ProviderRuntimeEvent(
            event_type="provider_call_started" if phase == "preflight" else "provider_usage_delta",
            operation=operation,
            provider=provider,
            usage=ProviderUsage(**normalized_usage),
            guard=resolved_guard,
        ).to_dict()
    ]
    estimated_cost = estimate_provider_cost(normalized_usage, resolved_guard.cost_profile) if resolved_guard.cost_profile else {"amount": 0.0, "currency": "USD", "source": "provider_runtime_guard_no_cost_profile"}
    hard_stop = {
        "token": {
            "triggered": False,
            "input_limit": resolved_guard.max_input_tokens,
            "output_limit": resolved_guard.max_output_tokens,
            "total_limit": resolved_guard.max_total_tokens,
            "input_used": _int(normalized_usage.get("input_tokens", 0)),
            "output_used": _int(normalized_usage.get("output_tokens", 0)),
            "total_used": _int(normalized_usage.get("total_tokens", 0)),
        },
        "cost": {
            "triggered": False,
            "limit": resolved_guard.max_cost,
            "amount": float(estimated_cost.get("amount", 0.0) or 0.0),
            "currency": str(estimated_cost.get("currency", "USD")),
            "source": str(estimated_cost.get("source", "")),
        },
        "cancel": {
            "triggered": False,
            "requested": bool(resolved_guard.cancel_requested or _cancel_file_requested(resolved_guard.cancel_file)),
            "cancel_file": resolved_guard.cancel_file,
        },
        "timeout": {
            "triggered": False,
            "limit_ms": resolved_guard.timeout_ms,
            "elapsed_ms": _int(normalized_usage.get("elapsed_ms", 0)),
        },
    }

    if resolved_guard.cancel_requested or _cancel_file_requested(resolved_guard.cancel_file):
        hard_stop["cancel"]["triggered"] = True
        failures.append("provider execution cancellation requested")
        error_type = "ProviderExecutionCancelled"
        events.append(_event("provider_cancel_requested", operation, provider, normalized_usage, resolved_guard, failures[-1]))

    if resolved_guard.max_input_tokens > 0 and _int(normalized_usage.get("input_tokens", 0)) > resolved_guard.max_input_tokens:
        hard_stop["token"]["triggered"] = True
        failures.append(f"provider input token cutoff exceeded: used {normalized_usage.get('input_tokens')}, limit {resolved_guard.max_input_tokens}")
        error_type = "ProviderTokenCutoffExceeded"
        events.append(_event("provider_token_cutoff", operation, provider, normalized_usage, resolved_guard, failures[-1]))

    if resolved_guard.max_output_tokens > 0 and _int(normalized_usage.get("output_tokens", 0)) > resolved_guard.max_output_tokens:
        hard_stop["token"]["triggered"] = True
        failures.append(f"provider output token cutoff exceeded: used {normalized_usage.get('output_tokens')}, limit {resolved_guard.max_output_tokens}")
        error_type = "ProviderTokenCutoffExceeded"
        events.append(_event("provider_token_cutoff", operation, provider, normalized_usage, resolved_guard, failures[-1]))

    if resolved_guard.max_total_tokens > 0 and _int(normalized_usage.get("total_tokens", 0)) > resolved_guard.max_total_tokens:
        hard_stop["token"]["triggered"] = True
        failures.append(f"provider token cutoff exceeded: used {normalized_usage.get('total_tokens')}, limit {resolved_guard.max_total_tokens}")
        error_type = "ProviderTokenCutoffExceeded"
        events.append(_event("provider_token_cutoff", operation, provider, normalized_usage, resolved_guard, failures[-1]))

    if resolved_guard.max_cost > 0 and float(estimated_cost.get("amount", 0.0) or 0.0) > resolved_guard.max_cost:
        hard_stop["cost"]["triggered"] = True
        failures.append(f"provider cost cutoff exceeded: estimated {estimated_cost.get('amount')} {estimated_cost.get('currency', 'USD')}, limit {resolved_guard.max_cost}")
        error_type = "ProviderCostCutoffExceeded"
        events.append(_event("provider_cost_cutoff", operation, provider, normalized_usage, resolved_guard, failures[-1]))

    if resolved_guard.timeout_ms > 0 and _int(normalized_usage.get("elapsed_ms", 0)) > resolved_guard.timeout_ms:
        hard_stop["timeout"]["triggered"] = True
        failures.append(f"provider timeout exceeded: elapsed {normalized_usage.get('elapsed_ms')}ms, limit {resolved_guard.timeout_ms}ms")
        error_type = "ProviderTimeoutExceeded"
        events.append(_event("provider_timeout", operation, provider, normalized_usage, resolved_guard, failures[-1]))

    if failures:
        return {
            "status": "failed",
            "operation": operation,
            "provider": provider,
            "message": "; ".join(failures),
            "usage": normalized_usage,
            "guard": resolved_guard.to_dict(),
            "estimated_cost": estimated_cost,
            "hard_stop": hard_stop,
            "events": events,
            "error_type": error_type,
        }

    if phase == "preflight":
        passed_event = "provider_guard_ready"
    elif phase in {"postflight", "finish", "finished"}:
        passed_event = "provider_call_finished"
    else:
        passed_event = "provider_stream_guard_ok"
    events.append(_event(passed_event, operation, provider, normalized_usage, resolved_guard, "provider runtime guard passed"))
    return {
        "status": "passed",
        "operation": operation,
        "provider": provider,
        "message": "provider runtime guard passed",
        "usage": normalized_usage,
        "guard": resolved_guard.to_dict(),
        "estimated_cost": estimated_cost,
        "hard_stop": hard_stop,
        "events": events,
    }


def _event(event_type: str, operation: str, provider: str, usage: dict[str, Any], guard: ProviderRuntimeGuard, message: str) -> dict[str, Any]:
    return ProviderRuntimeEvent(
        event_type=event_type,
        operation=operation,
        provider=provider,
        message=message,
        usage=ProviderUsage(**normalize_provider_usage(usage)),
        guard=guard,
    ).to_dict()


def _merge_usage(current: dict[str, Any], delta: dict[str, Any], *, elapsed_ms: int = 0) -> dict[str, Any]:
    input_tokens = _int(current.get("input_tokens", 0)) + _int(delta.get("input_tokens", 0))
    output_tokens = _int(current.get("output_tokens", 0)) + _int(delta.get("output_tokens", 0))
    total_tokens = _int(current.get("total_tokens", 0)) + _int(delta.get("total_tokens", 0))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=_int(current.get("cached_tokens", 0)) + _int(delta.get("cached_tokens", 0)),
        reasoning_tokens=_int(current.get("reasoning_tokens", 0)) + _int(delta.get("reasoning_tokens", 0)),
        elapsed_ms=max(_int(current.get("elapsed_ms", 0)), _int(delta.get("elapsed_ms", 0)), elapsed_ms),
        provider_request_id=str(delta.get("provider_request_id") or current.get("provider_request_id") or ""),
        finish_reason=str(delta.get("finish_reason") or current.get("finish_reason") or ""),
        usage_source=str(delta.get("usage_source") or current.get("usage_source") or "provider_stream"),
    ).to_dict()


def _cancel_file_requested(cancel_file: str) -> bool:
    if not cancel_file:
        return False
    path = Path(cancel_file).expanduser()
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8").strip().lower()
    except Exception:
        content = ""
    return content in {"", "1", "true", "yes", "cancel", "cancelled", "canceled"}


def _rough_token_count(text: str) -> int:
    value = str(text or "")
    if not value:
        return 0
    return max(1, int(len(value) / 4))


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0
