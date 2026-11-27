from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
import inspect
import json
import logging
import os
import re
from threading import Lock
import time
import traceback
from uuid import uuid4


_LOGGER = logging.getLogger("novel_forge.execution")
_CONTEXT = ContextVar("execution_diagnostics", default={})
_LOCK = Lock()
_CONFIGURED = False
_IDENTITY = re.compile(r"[A-Za-z0-9:._/@+-]{1,256}")
_FIELDS = frozenset({
    "project_id", "book_id", "operation_id", "external_effect_id", "execution_id",
    "attempt_id", "fencing_token", "trace_id", "correlation_id", "backend_id",
    "contract_hash", "request_digest", "input_sha256", "command_sha256", "stage",
    "route_snapshot_id", "input_manifest_ref", "output_schema_version", "receipt_id",
    "dispatch_id", "generation", "reservation_id", "status", "outcome",
    "result_integrity", "returncode", "elapsed_ms", "disposition", "replayed",
    "opening_run_id", "recovery_assessment_id", "kind", "reconciliation",
    "error_type", "error_code", "cached_result", "usage_present", "cost_present",
    "result_present", "stdout_bytes", "stderr_bytes", "stream_disconnected",
    "response_body_decode_failed", "turn_completed", "scan_truncated", "remote_outcome",
    "duration_ms",
})


def _safe_fields(value):
    fields = {}
    for name in _FIELDS:
        item = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if isinstance(item, (bool, int)):
            fields[name] = item
        elif (isinstance(item, str) and _IDENTITY.fullmatch(item)
              and not item.startswith(("sk-", "ghp_", "gho_")) and "://" not in item):
            fields[name] = item
    return fields


def execution_event(step, phase, **fields):
    global _CONFIGURED
    try:
        if not _CONFIGURED and os.environ.get("NOVEL_FORGE_EXECUTION_DIAGNOSTICS") == "1":
            with _LOCK:
                if not _CONFIGURED:
                    handler = logging.StreamHandler()
                    handler.setFormatter(logging.Formatter("%(message)s"))
                    _LOGGER.addHandler(handler)
                    _LOGGER.setLevel(logging.INFO)
                    _CONFIGURED = True
        payload = {**_CONTEXT.get(), **_safe_fields(fields),
            "diagnostic_version": "execution-diagnostics.v1", "step": step,
            "phase": phase, "timestamp": datetime.now(UTC).isoformat()}
        _LOGGER.info(json.dumps(payload, sort_keys=True))
    except Exception:
        return


def execution_exception(step, exc):
    if os.environ.get("NOVEL_FORGE_EXECUTION_DIAGNOSTICS_EXCEPTION_TEXT") != "1":
        return
    try:
        from novel_forge.modules.production_execution.security import redact_secret_text

        payload = {**_CONTEXT.get(), "diagnostic_version": "execution-diagnostics.v1",
            "step": step, "phase": "exception", "timestamp": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__, "error_message": redact_secret_text(str(exc)),
            "traceback": redact_secret_text("".join(traceback.format_exception(exc)))}
        _LOGGER.info(json.dumps(payload, sort_keys=True))
    except Exception:
        return


def execution_error_message(step, message):
    if os.environ.get("NOVEL_FORGE_EXECUTION_DIAGNOSTICS_EXCEPTION_TEXT") != "1":
        return
    try:
        from novel_forge.modules.production_execution.security import redact_secret_text

        _LOGGER.info(json.dumps({**_CONTEXT.get(), "diagnostic_version": "execution-diagnostics.v1",
            "step": step, "phase": "provider_error", "timestamp": datetime.now(UTC).isoformat(),
            "error_message": redact_secret_text(message)}, sort_keys=True))
    except Exception:
        return


def execution_step(step):
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def observed(*args, **kwargs):
            arguments = signature.bind(*args, **kwargs).arguments
            fields = {**_CONTEXT.get(), **_safe_fields(arguments)}
            if "effect_id" in arguments:
                fields.update(_safe_fields({"external_effect_id": arguments["effect_id"]}))
            fields.update(_safe_fields({"project_id": getattr(arguments.get("self"), "project_id", None)}))
            for name in ("context", "request", "handle", "record", "receipt"):
                value = arguments.get(name)
                if value is not None:
                    fields.update(_safe_fields(value))
                    if name == "record":
                        fields.update(_safe_fields(value.request))
            binding = getattr(arguments.get("self"), "binding", None)
            if binding is not None:
                fields.update(_safe_fields(binding.request))
            fields["parent_span_id"] = fields.get("span_id", "")
            fields["span_id"] = str(uuid4())
            token = _CONTEXT.set(fields)
            started = time.monotonic()
            execution_event(step, "started")
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                error_fields = {"error_type": type(exc).__name__}
                code = getattr(exc, "code", "")
                if isinstance(code, str) and _IDENTITY.fullmatch(code):
                    error_fields["error_code"] = code
                execution_event(step, "failed", **error_fields,
                    duration_ms=int((time.monotonic() - started) * 1000))
                execution_exception(step, exc)
                raise
            else:
                summary = _safe_fields(result)
                receipt = getattr(result, "receipt", None)
                if receipt is not None:
                    summary.update(_safe_fields(receipt))
                execution_event(step, "completed", **{**summary,
                    "duration_ms": int((time.monotonic() - started) * 1000)})
                return result
            finally:
                _CONTEXT.reset(token)

        return observed

    return decorate
