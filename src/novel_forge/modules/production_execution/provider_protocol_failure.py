from __future__ import annotations

import json
import hashlib
from pathlib import Path

from novel_forge.logging.execution import execution_error_message


def observed_provider_failure(stdout: str, *, status: str, request=None) -> dict:
    from .security import redact_secret_text

    causes = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") not in {
            "error",
            "turn.failed",
        }:
            continue
        nested = event.get("error") or {}
        message = event.get("message") or (
            nested.get("message") if isinstance(nested, dict) else nested
        )
        if isinstance(message, str):
            causes.append(
                {"event": event["type"], "message": redact_secret_text(message)}
            )
    message = " ".join(item["message"] for item in causes).lower()
    rules = (
        (
            ("stream disconnected", "stream interrupted"),
            "PROVIDER_STREAM_INTERRUPTED",
            "RESPONSE_STREAM",
            True,
        ),
        (
            ("401", "unauthorized", "authentication", "invalid api key"),
            "PROVIDER_AUTH_FAILED",
            "AUTHENTICATION",
            False,
        ),
        (
            ("429", "rate limit", "too many requests"),
            "PROVIDER_RATE_LIMITED",
            "PROVIDER_ADMISSION",
            True,
        ),
        (
            ("connection refused", "connection reset", "failed to connect", "dns"),
            "PROVIDER_CONNECTION_FAILED",
            "CONNECTION",
            True,
        ),
        (
            ("invalid_json_schema",),
            "PROVIDER_SCHEMA_REJECTED",
            "OUTPUT_CONTRACT_ADMISSION",
            False,
        ),
        (
            ("503", "service unavailable"),
            "PROVIDER_UNAVAILABLE",
            "PROVIDER_ADMISSION",
            True,
        ),
    )
    code, phase, retryable = {
        "START_FAILED": ("PROCESS_START_FAILURE", "PROCESS_LAUNCH", True),
        "TIMED_OUT": ("PROVIDER_RESPONSE_TIMEOUT", "RESPONSE_WAIT", True),
        "ORPHANED": ("GENERATION_PARENT_EXITED", "PROCESS_SUPERVISION", True),
        "CORRUPT_RESULT": ("RESULT_JSON_INVALID", "RESULT_READ", False),
        "CANCELLED": ("PROCESS_CANCELLED", "PROCESS_SUPERVISION", False),
    }.get(str(status), ("GENERATION_PROCESS_EXITED", "PROCESS_EXECUTION", True))
    for markers, observed_code, observed_phase, observed_retryable in rules:
        if any(marker in message for marker in markers):
            code, phase, retryable = observed_code, observed_phase, observed_retryable
            break
    identity = {
        key: getattr(request, key)
        for key in (
            "execution_id",
            "operation_id",
            "attempt_id",
            "fencing_token",
            "project_id",
            "book_id",
        )
        if request is not None and hasattr(request, key)
    }
    cause_code = (
        "CODEX_RESPONSE_BODY_DECODE_FAILED"
        if "error decoding response body" in message
        else code
    )
    return {
        "contract_version": "provider-failure.v1",
        "cause_code": cause_code,
        "provider_error_code": code,
        "stage": phase,
        "error_code": code,
        "phase": phase,
        "causes": causes,
        "identity": identity,
        "retryable": retryable,
        "recovery_action": "RETRY_CONFIRMED_UNSENT"
        if str(status) == "START_FAILED"
        else "REUSE_RESULT_OR_ISOLATE_PURE_GENERATION"
        if retryable
        else "CORRECT_AUTH_OR_CONTRACT",
        "recovery_state": "REQUIRED",
        "scope": "ORIGINAL_LOGICAL_TASK",
        "exit_condition": "TRUSTED_RESULT_OR_DURABLE_ISOLATION_AND_SUCCESSOR",
        "business_impact": "CURRENT_TASK_BLOCKED",
        "remote_outcome": "UNESTABLISHED",
    }


def provider_invocation_failure(evidence, *, request):
    detail = observed_provider_failure("", status="PROVIDER_RESPONSE", request=request)
    observed = str(evidence.get("failure_class") or "PROVIDER_RESPONSE_INVALID")
    code, phase, retryable = {
        "AUTHENTICATION_FAILED": ("PROVIDER_AUTH_FAILED", "AUTHENTICATION", False),
        "PROVIDER_BUDGET_EXHAUSTED": (
            "PROVIDER_BUDGET_INSUFFICIENT",
            "PROVIDER_ADMISSION",
            False,
        ),
        "RATE_LIMIT": ("PROVIDER_RATE_LIMITED", "PROVIDER_ADMISSION", True),
        "PROVIDER_UNAVAILABLE": ("PROVIDER_UNAVAILABLE", "PROVIDER_RESPONSE", True),
        "TRANSIENT_NETWORK": (
            "PROVIDER_CONNECTION_FAILED",
            "CONNECTION_OR_RESPONSE_READ",
            True,
        ),
        "TIMEOUT": ("PROVIDER_RESPONSE_TIMEOUT", "RESPONSE_WAIT", True),
        "OUTPUT_CAPACITY_EXCEEDED": ("RESULT_TRUNCATED", "RESULT_COMPLETENESS", True),
        "RESPONSE_CAPACITY_EXCEEDED": ("RESULT_TRUNCATED", "RESPONSE_READ", True),
        "MALFORMED_PROVIDER_RECEIPT": (
            "PROVIDER_RECEIPT_INVALID",
            "RESPONSE_PARSE",
            False,
        ),
        "MALFORMED_STRUCTURED_OUTPUT": ("RESULT_JSON_INVALID", "RESULT_PARSE", True),
        "SCHEMA_REJECTION": ("RESULT_SCHEMA_INVALID", "RESULT_VALIDATION", True),
        "CONTRACT_REJECTION": (
            "PROVIDER_CONTRACT_REJECTED",
            "PROVIDER_ADMISSION",
            False,
        ),
        "POLICY_REJECTION": ("PROVIDER_POLICY_REJECTED", "PROVIDER_ADMISSION", False),
    }.get(observed, (observed, "PROVIDER_RESPONSE", False))
    from .security import redact_secret_text

    detail.update(
        error_code=code,
        phase=phase,
        stage=phase,
        retryable=retryable,
        causes=[
            {
                "event": "provider.response",
                "code": observed,
                "message": redact_secret_text(
                    str(evidence.get("failure_cause") or observed)
                ),
                **(
                    {"http_status": evidence["http_status"]}
                    if "http_status" in evidence
                    else {}
                ),
            }
        ],
        recovery_action="REUSE_RESULT_OR_ISOLATE_PURE_GENERATION"
        if retryable
        else "CORRECT_AUTH_OR_CONTRACT",
        remote_outcome="REJECTED_BEFORE_EXECUTION"
        if evidence.get("submission_state") == "REJECTED_BEFORE_EXECUTION"
        else "UNESTABLISHED",
    )
    return detail


def codex_stream_summary(stdout: str) -> dict:
    summary = {
        "version": "codex-stream-diagnostics.v1",
        "event_counts": {},
        "turn_completed": False,
        "usage_present": False,
        "stream_disconnected": False,
        "response_body_decode_failed": False,
        "remote_outcome": "UNESTABLISHED",
    }
    allowed = {
        "thread.started",
        "turn.started",
        "turn.completed",
        "turn.failed",
        "error",
        "item.started",
        "item.updated",
        "item.completed",
    }
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError, RecursionError):
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if not isinstance(kind, str) or kind not in allowed:
            continue
        counts = summary["event_counts"]
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "thread.started" and isinstance(event.get("thread_id"), str):
            summary["local_thread_id"] = event["thread_id"]
        if kind == "turn.completed":
            summary["turn_completed"] = True
            summary["usage_present"] = isinstance(event.get("usage"), dict)
        if kind in {"error", "turn.failed"}:
            error = event.get("error")
            message = event.get("message") or (
                error.get("message") if isinstance(error, dict) else ""
            )
            if isinstance(message, str):
                execution_error_message("codex.stream", message)
                summary["stream_disconnected"] |= (
                    "stream disconnected before completion" in message
                )
                summary["response_body_decode_failed"] |= (
                    "error decoding response body" in message
                )
    return summary


def read_codex_stream_summary(path: str) -> dict:
    try:
        with Path(path).open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(0)
            data = stream.read(524288)
            if size > 1048576:
                stream.seek(-524288, 2)
                data += b"\n" + stream.read(524288)
            else:
                data += stream.read(524288)
        with Path(path).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return {
            **codex_stream_summary(data.decode("utf-8", errors="replace")),
            "stdout_sha256": digest,
            "stdout_bytes": size,
            "scan_truncated": size > 1048576,
        }
    except OSError:
        return {
            "version": "codex-stream-diagnostics.v1",
            "status": "UNAVAILABLE",
            "remote_outcome": "UNESTABLISHED",
        }


def codex_protocol_failure(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                continue
            message = event.get("message") if event.get("type") == "error" else None
            detail = json.loads(message) if isinstance(message, str) else {}
            if (
                isinstance(detail, dict)
                and detail.get("status", 400) == 400
                and isinstance(detail.get("error"), dict)
                and detail["error"].get("code") == "invalid_json_schema"
            ):
                return "PROVIDER_SCHEMA_REJECTED"
        except (ValueError, TypeError):
            continue
    return None


def codex_completed_turn(stdout: str) -> bool:
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    except (ValueError, TypeError, RecursionError):
        return False
    if not events or any(not isinstance(event, dict) for event in events):
        return False
    kinds = [event.get("type") for event in events]
    return (
        kinds[-1] == "turn.completed"
        and kinds.count("turn.completed") == 1
        and kinds.count("turn.started") <= 1
        and kinds.count("thread.started") <= 1
        and "turn.failed" not in kinds
        and "error" not in kinds
        and (
            events[-1].get("usage") is None
            or (
                isinstance(events[-1].get("usage"), dict)
                and all(
                    type(events[-1]["usage"].get(key)) is int
                    and events[-1]["usage"][key] >= 0
                    for key in ("input_tokens", "output_tokens")
                )
            )
        )
    )
