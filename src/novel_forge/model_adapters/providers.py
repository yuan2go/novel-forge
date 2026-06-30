from __future__ import annotations

import json
import importlib.util
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from novel_forge.model_adapters.base import AdapterNotConfiguredError, ModelAdapterConfig
from novel_forge.model_adapters.output_validation import parse_json_object, validate_model_output
from novel_forge.model_adapters.prompts import build_messages
from novel_forge.model_adapters.runtime import (
    ProviderRuntimeGuardViolation,
    estimate_provider_cost,
    estimate_usage_from_text,
    normalize_provider_usage,
    provider_runtime_controller,
    provider_runtime_guard_from_context,
)


class ProviderAdapter:
    """Base adapter for providers that do not implement in-process calls.

    Manual/operator adapters inherit this fail-closed behavior. Automated providers
    such as OpenAICompatibleChatAdapter override generation/review methods.
    """

    config: ModelAdapterConfig

    def __init__(self, config: ModelAdapterConfig | None = None) -> None:
        if config is not None:
            self.config = config
        self.name = self.config.provider

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        raise self._not_configured("generate")

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        raise self._not_configured("analyze")

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        raise self._not_configured("review")

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        raise self._not_configured("revise")

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        raise self._not_configured("batch")

    def health_check(self) -> dict[str, Any]:
        missing = [name for name in self.config.required_env_vars if not os.environ.get(name)]
        return {
            "model": self.config.default_model,
            "provider": self.config.provider,
            "role": self.config.role,
            "ok": not missing,
            "configured": not missing,
            "external_api": self.config.external_api,
            "required_env_vars": self.config.required_env_vars,
            "missing_env_vars": missing,
            "implemented": False,
            "message": "manual or base adapter only; no in-process model call is implemented",
        }

    def _not_configured(self, operation: str) -> AdapterNotConfiguredError:
        return AdapterNotConfiguredError(
            f"{self.config.provider} adapter cannot run {operation}: "
            "this adapter does not implement in-process model calls"
        )


class LocalCodexCliWorkerMixin:
    """Local Codex CLI worker.

    The worker uses `codex exec` in non-interactive mode, constrains the final
    response with a JSON schema, and validates the parsed output before returning.
    Providers can choose whether this worker is enabled by default.
    """

    cli_env_prefix = "NOVEL_FORGE_CODEX"
    default_codex_home = ""
    local_cli_enabled_by_default = False

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_local_codex_operation("generate", prompt, context)

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_local_codex_operation("analyze", text, context)

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_local_codex_operation("review", content, context)

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_local_codex_operation("revise", content, {**(context or {}), "review": review})

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [self.generate(prompt, context) for prompt in prompts]

    def _run_local_codex_operation(self, operation: str, payload: str, context: dict[str, Any] | None) -> dict[str, Any]:
        if not self._local_cli_enabled():
            raise self._not_configured(operation)
        command_base = self._codex_command_base()
        executable = command_base[0] if command_base else ""
        if not _which_executable(executable):
            raise AdapterNotConfiguredError(
                f"{self.config.provider} adapter cannot run {operation}: local Codex CLI executable not found: {executable}"
            )
        canonical = _canonical_local_operation(operation)
        context_payload = context or {}
        guard = provider_runtime_guard_from_context(context_payload)
        controller = provider_runtime_controller(operation=canonical, provider=self.config.provider, guard=guard)
        controller.start()
        with tempfile.TemporaryDirectory(prefix="novel-forge-codex-") as tmp:
            tmpdir = Path(tmp)
            schema_path = tmpdir / "output.schema.json"
            output_path = tmpdir / "last-message.json"
            schema_path.write_text(json.dumps(_codex_output_schema(canonical), ensure_ascii=False, indent=2), encoding="utf-8")
            prompt = _codex_prompt(canonical, payload, context_payload)
            command = self._codex_command(schema_path=schema_path, output_path=output_path, context=context_payload)
            env = self._codex_env()
            timeout = max(1, int(guard.timeout_ms / 1000)) if guard.timeout_ms > 0 else self._codex_timeout_seconds()
            started = time.monotonic()
            try:
                completed = _run_process_with_runtime_guard(
                    command,
                    input_text=prompt,
                    timeout_seconds=timeout,
                    cwd=str(self._codex_workdir(context_payload)),
                    env=env,
                    controller=controller,
                    provider=self.config.provider,
                )
            except ProviderRuntimeGuardViolation as exc:
                controller.fail(str(exc))
                raise RuntimeError(str(exc)) from exc
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                controller.fail(f"{self.config.provider} local Codex CLI failed with exit {completed.returncode}: {detail[:1000]}")
                raise RuntimeError(f"{self.config.provider} local Codex CLI failed with exit {completed.returncode}: {detail[:1000]}")
            raw = output_path.read_text(encoding="utf-8") if output_path.exists() else _extract_last_json_text(completed.stdout)
            parsed = parse_json_object(raw)
            parsed.setdefault("model", self._codex_model() or self.config.default_model)
            parsed.setdefault("provider", self.config.provider)
            usage = _codex_usage_from_stdout(completed.stdout, elapsed_ms=elapsed_ms)
            if usage.get("total_tokens", 0) <= 0:
                usage = estimate_usage_from_text(prompt, json.dumps(parsed, ensure_ascii=False), elapsed_ms=elapsed_ms, usage_source="codex_stdout_estimated")
            parsed["usage"] = usage
            if guard.cost_profile and "cost" not in parsed:
                parsed["cost"] = estimate_provider_cost(usage, guard.cost_profile)
            controller.finish(usage, elapsed_ms=elapsed_ms)
            validated = validate_model_output(canonical, parsed)
            validated["usage"] = usage
            validated["runtime_events"] = controller.to_dict()["events"]
            if "cost" in parsed:
                validated["cost"] = parsed["cost"]
            return validated

    def _local_cli_health(self, base: dict[str, Any]) -> dict[str, Any]:
        enabled = self._local_cli_enabled()
        command = self._codex_command_base()
        executable = command[0] if command else ""
        configured = enabled and bool(_which_executable(executable))
        return {
            **base,
            "implemented": "local_cli_worker" if enabled else base.get("implemented", False),
            "configured": configured,
            "ok": configured,
            "external_api": False,
            "command": command,
            "codex_home": self._codex_home_display(),
            "launch_command": self._launch_command_display(),
            "automation_isolation": self._codex_automation_isolation(),
            "message": "ready for local Codex CLI worker" if configured else self._local_cli_disabled_message(enabled, executable),
        }

    def _local_cli_enabled(self) -> bool:
        local_value = os.environ.get(f"{self.cli_env_prefix}_CLI_ENABLED")
        global_value = os.environ.get("NOVEL_FORGE_LOCAL_CODEX_CLI_ENABLED")
        for value in [local_value, global_value]:
            if value is not None and str(value).strip():
                return _truthy(value)
        return self.local_cli_enabled_by_default

    def _codex_command(self, *, schema_path: Path, output_path: Path, context: dict[str, Any]) -> list[str]:
        command = [*self._codex_command_base(), "exec"]
        model = self._codex_model()
        profile = os.environ.get(f"{self.cli_env_prefix}_PROFILE", "").strip()
        sandbox = os.environ.get(f"{self.cli_env_prefix}_SANDBOX", "read-only").strip() or "read-only"
        if model:
            command.extend(["--model", model])
        if profile:
            command.extend(["--profile", profile])
        command.extend(["--sandbox", sandbox, "--skip-git-repo-check", "--json", "--output-schema", str(schema_path), "--output-last-message", str(output_path), "--color", "never"])
        isolation = self._codex_automation_isolation()
        if isolation["ignore_user_config"]:
            command.append("--ignore-user-config")
        if isolation["ignore_rules"]:
            command.append("--ignore-rules")
        if _truthy(os.environ.get(f"{self.cli_env_prefix}_EPHEMERAL", "1")):
            command.append("--ephemeral")
        command.extend(["--cd", str(self._codex_workdir(context)), "-"])
        return command

    def _codex_automation_isolation(self) -> dict[str, Any]:
        return {
            "ignore_user_config": _truthy(os.environ.get(f"{self.cli_env_prefix}_IGNORE_USER_CONFIG", os.environ.get("NOVEL_FORGE_CODEX_IGNORE_USER_CONFIG", "1"))),
            "ignore_rules": _truthy(os.environ.get(f"{self.cli_env_prefix}_IGNORE_RULES", os.environ.get("NOVEL_FORGE_CODEX_IGNORE_RULES", "1"))),
            "ephemeral": _truthy(os.environ.get(f"{self.cli_env_prefix}_EPHEMERAL", "1")),
            "sandbox": os.environ.get(f"{self.cli_env_prefix}_SANDBOX", "read-only").strip() or "read-only",
        }

    def _codex_command_base(self) -> list[str]:
        raw = os.environ.get(f"{self.cli_env_prefix}_COMMAND", "codex").strip() or "codex"
        return shlex.split(raw)

    def _codex_env(self) -> dict[str, str]:
        env = dict(os.environ)
        codex_home = self._codex_home()
        if codex_home:
            env["CODEX_HOME"] = codex_home
        return env

    def _codex_home(self) -> str:
        value = os.environ.get(f"{self.cli_env_prefix}_CODEX_HOME", self.default_codex_home).strip()
        return str(Path(value).expanduser()) if value else ""

    def _codex_home_display(self) -> str:
        return os.environ.get(f"{self.cli_env_prefix}_CODEX_HOME", self.default_codex_home).strip()

    def _codex_model(self) -> str:
        return os.environ.get(f"{self.cli_env_prefix}_MODEL", "").strip()

    def _codex_timeout_seconds(self) -> int:
        try:
            return max(1, int(os.environ.get(f"{self.cli_env_prefix}_TIMEOUT_SECONDS", "300")))
        except Exception:
            return 300

    def _codex_workdir(self, context: dict[str, Any]) -> Path:
        raw = str(context.get("codex_workdir") or context.get("workspace_path") or os.environ.get(f"{self.cli_env_prefix}_WORKDIR", ".") or ".").strip()
        path = Path(raw).expanduser().resolve()
        return path if path.exists() and path.is_dir() else Path(".").resolve()

    def _launch_command_display(self) -> str:
        prefix = f"CODEX_HOME={self._codex_home_display()} " if self._codex_home_display() else ""
        return f"{prefix}{' '.join(self._codex_command_base())}".strip()

    def _local_cli_disabled_message(self, enabled: bool, executable: str) -> str:
        if not enabled:
            return f"local Codex CLI worker disabled; set {self.cli_env_prefix}_CLI_ENABLED=1 to enable"
        return f"local Codex CLI executable not found: {executable}"

    def _not_configured(self, operation: str) -> AdapterNotConfiguredError:
        return AdapterNotConfiguredError(
            f"{self.config.provider} adapter cannot run {operation}: local Codex CLI worker is disabled. "
            f"Set {self.cli_env_prefix}_CLI_ENABLED=1 to opt in."
        )


class OpenAICompatibleChatAdapter(ProviderAdapter):
    """Real JSON-chat provider for OpenAI-compatible APIs.

    Network calls only happen when required secrets are present and a caller explicitly
    selects this adapter. Deterministic tests can still force MockModelAdapter through
    NOVEL_FORGE_MODEL_PROVIDER=mock.
    """

    api_key_env = ""
    model_env = ""
    base_url_env = ""
    default_base_url = ""
    timeout_seconds = 90

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_json_operation("generate", prompt, context)

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_json_operation("analyze", text, context)

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._run_json_operation("review", content, context)

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        merged_context = {**(context or {}), "review": review}
        return self._run_json_operation("revise", content, merged_context)

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [self.generate(prompt, context) for prompt in prompts]

    def health_check(self) -> dict[str, Any]:
        status = super().health_check()
        return {
            **status,
            "implemented": True,
            "configured": bool(self._api_key()),
            "ok": bool(self._api_key()),
            "base_url": self._base_url(),
            "model": self._model(),
            "sdk_streaming_supported": _openai_sdk_available(),
            "sdk_streaming_enabled": _provider_sdk_streaming_enabled({}, self),
            "message": "ready for JSON chat completions" if self._api_key() else "missing API key",
        }

    def _run_json_operation(self, operation: str, payload: str, context: dict[str, Any] | None) -> dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            raise self._not_configured(operation)
        context_payload = context or {}
        guard = provider_runtime_guard_from_context(context_payload)
        controller = provider_runtime_controller(operation=operation, provider=self.config.provider, guard=guard)
        controller.start()
        messages = build_messages(operation, payload, context)
        request_payload = {
            "model": self._model(),
            "messages": messages,
            "temperature": float(os.environ.get("NOVEL_FORGE_MODEL_TEMPERATURE", "0.3")),
            "response_format": {"type": "json_object"},
        }
        streaming = _streaming_enabled(context_payload)
        if streaming:
            request_payload["stream"] = True
            request_payload["stream_options"] = {"include_usage": True}
        started = time.monotonic()
        try:
            timeout = max(1, int(guard.timeout_ms / 1000)) if guard.timeout_ms > 0 else self.timeout_seconds
            controller.cancel_if_requested()
            if streaming and _provider_sdk_streaming_enabled(context_payload, self):
                response_data = _run_openai_compatible_sdk_stream(
                    adapter=self,
                    api_key=api_key,
                    request_payload=request_payload,
                    controller=controller,
                    operation=operation,
                )
            else:
                request = urllib.request.Request(
                    self._base_url(),
                    data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if streaming:
                        response_data = _read_openai_compatible_stream(
                            response,
                            controller=controller,
                            operation=operation,
                            provider=self.config.provider,
                        )
                    else:
                        response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            controller.fail(f"{self.config.provider} API returned HTTP {exc.code}: {detail[:500]}")
            raise RuntimeError(f"{self.config.provider} API returned HTTP {exc.code}: {detail[:500]}") from exc
        except ProviderRuntimeGuardViolation as exc:
            controller.fail(str(exc))
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            controller.fail(f"{self.config.provider} API call failed: {exc}")
            raise RuntimeError(f"{self.config.provider} API call failed: {exc}") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)

        try:
            content = response_data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"{self.config.provider} API response missing choices[0].message.content") from exc
        parsed = parse_json_object(str(content))
        parsed.setdefault("model", self._model())
        parsed.setdefault("provider", self.config.provider)
        raw_usage = response_data.get("usage", {}) if isinstance(response_data.get("usage", {}), dict) else {}
        usage = normalize_provider_usage(raw_usage, elapsed_ms=elapsed_ms, usage_source="provider")
        if usage.get("total_tokens", 0) <= 0:
            usage = estimate_usage_from_text(json.dumps(messages, ensure_ascii=False), str(content), elapsed_ms=elapsed_ms, usage_source="estimated")
        parsed["usage"] = usage
        if guard.cost_profile and "cost" not in parsed:
            parsed["cost"] = estimate_provider_cost(usage, guard.cost_profile)
        controller.finish(usage, elapsed_ms=elapsed_ms)
        validated = validate_model_output(operation, parsed)
        validated["usage"] = usage
        validated["runtime_events"] = controller.to_dict()["events"]
        if "cost" in parsed:
            validated["cost"] = parsed["cost"]
        return validated

    def _api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    def _model(self) -> str:
        return os.environ.get(self.model_env, self.config.default_model)

    def _base_url(self) -> str:
        return os.environ.get(self.base_url_env, self.default_base_url)

    def _not_configured(self, operation: str) -> AdapterNotConfiguredError:
        return AdapterNotConfiguredError(
            f"{self.config.provider} adapter cannot run {operation}: missing {self.api_key_env}"
        )


class ClaudeCodeAdapter(LocalCodexCliWorkerMixin, ProviderAdapter):
    config = ModelAdapterConfig(
        provider="claude-code",
        role="chief editor / workflow controller / audit owner",
        default_model="manual-claude-code-runtime",
        required_env_vars=[],
        external_api=False,
    )
    cli_env_prefix = "NOVEL_FORGE_CLAUDE_CODE"
    default_codex_home = "~/.codex-claude"
    local_cli_enabled_by_default = True

    def create_handoff_packet(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a bounded manual task packet for the current Claude Code runtime.

        This does not call Claude Code as an API. It makes the supported integration
        explicit: write/read schema-backed files and let the human-approved Claude Code
        session execute the task.
        """

        return {
            "provider": self.config.provider,
            "model": self.config.default_model,
            "operation": operation,
            "status": "manual_handoff_required",
            "external_api": False,
            "automated_model_call": False,
            "payload": payload,
            "context": context or {},
            "instructions": [
                "Read the referenced project files before producing output.",
                "Write results as schema-backed JSON assets through Novel Forge CLI or storage rules.",
                "Do not treat this packet as permission to call external APIs or bypass validation.",
                "Run relevant validation after writing outputs.",
            ],
            "expected_return": {
                "asset_path": "path to a schema-backed JSON asset",
                "validation_command": "make validate or a narrower relevant check",
            },
        }

    def health_check(self) -> dict[str, Any]:
        status = super().health_check()
        manual = {
            **status,
            "implemented": "manual_handoff_only",
            "message": "Claude Code is available as an operator workflow, not as an in-process LLM API",
        }
        return self._local_cli_health(manual) if self._local_cli_enabled() else manual


class CodexAdapter(LocalCodexCliWorkerMixin, ProviderAdapter):
    config = ModelAdapterConfig(
        provider="codex",
        role="engineering editor / code implementation reviewer",
        default_model="manual-codex-runtime",
        required_env_vars=[],
        external_api=False,
    )

    def health_check(self) -> dict[str, Any]:
        return self._local_cli_health(super().health_check())


class ChatGPTAdapter(OpenAICompatibleChatAdapter):
    config = ModelAdapterConfig(
        provider="chatgpt",
        role="advanced review / multidisciplinary synthesis / commercial logic analysis",
        default_model="gpt-4o-mini",
        required_env_vars=["OPENAI_API_KEY"],
        external_api=True,
    )
    api_key_env = "OPENAI_API_KEY"
    model_env = "OPENAI_MODEL"
    base_url_env = "OPENAI_CHAT_COMPLETIONS_URL"
    default_base_url = "https://api.openai.com/v1/chat/completions"


class DeepSeekAdapter(OpenAICompatibleChatAdapter):
    config = ModelAdapterConfig(
        provider="deepseek",
        role="long-form draft generation",
        default_model="deepseek-chat",
        required_env_vars=["DEEPSEEK_API_KEY"],
        external_api=True,
    )
    api_key_env = "DEEPSEEK_API_KEY"
    model_env = "DEEPSEEK_MODEL"
    base_url_env = "DEEPSEEK_CHAT_COMPLETIONS_URL"
    default_base_url = "https://api.deepseek.com/chat/completions"


PROVIDER_ADAPTERS = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "chatgpt": ChatGPTAdapter,
    "deepseek": DeepSeekAdapter,
}


def _canonical_local_operation(operation: str) -> str:
    value = operation.strip().lower()
    if value in {"draft", "topic", "generate", "outline", "chapter_plan"}:
        return "generate"
    if value in {"decompose", "analysis", "analyze"}:
        return "analyze"
    if value in {"review", "revise"}:
        return value
    raise ValueError(f"unsupported local Codex operation: {operation}")


def _codex_prompt(operation: str, payload: str, context: dict[str, Any]) -> str:
    messages = build_messages(operation, payload, context)
    return "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)


def _codex_output_schema(operation: str) -> dict[str, Any]:
    schemas = {
        "generate": {
            "type": "object",
            "required": ["text", "notes", "copyright_boundary"],
            "properties": {
                "text": {"type": "string", "minLength": 8},
                "notes": {"type": "array", "items": {"type": "string"}},
                "copyright_boundary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "analyze": {
            "type": "object",
            "required": ["summary", "word_count", "patterns"],
            "properties": {
                "summary": {"type": "string", "minLength": 1},
                "word_count": {"type": "integer", "minimum": 0},
                "patterns": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "additionalProperties": False,
        },
        "review": {
            "type": "object",
            "required": ["score", "strengths", "weaknesses", "issues", "risk_level", "revision_suggestions", "next_action"],
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 100},
                "strengths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "weaknesses": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {"type": "string"},
                            "severity": {"type": "string"},
                            "message": {"type": "string"},
                            "recommendation": {"type": "string"},
                        },
                        "required": ["dimension", "severity", "message", "recommendation"],
                        "additionalProperties": False,
                    },
                },
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "revision_suggestions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "next_action": {"type": "string", "enum": ["approve", "revise", "rewrite", "block"]},
            },
            "additionalProperties": False,
        },
        "revise": {
            "type": "object",
            "required": ["plan", "target_score"],
            "properties": {
                "plan": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "target_score": {"type": "number"},
            },
            "additionalProperties": False,
        },
    }
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schemas[operation]}


def _extract_last_json_text(stdout: str) -> str:
    text = stdout.strip()
    if not text:
        raise RuntimeError("local Codex CLI produced no output")
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                event = json.loads(candidate)
            except Exception:
                return candidate
            if isinstance(event, dict):
                message = event.get("message") or event.get("content") or event.get("text") or event.get("last_message")
                if isinstance(message, str) and message.strip():
                    return message
                if any(key in event for key in ["text", "summary", "score", "plan"]):
                    return json.dumps(event, ensure_ascii=False)
    return text


def _codex_usage_from_stdout(stdout: str, *, elapsed_ms: int = 0) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        candidate = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        if candidate:
            usage.update(candidate)
    return normalize_provider_usage(usage, elapsed_ms=elapsed_ms, usage_source="codex_stdout")


def _run_process_with_runtime_guard(
    command: list[str],
    *,
    input_text: str,
    timeout_seconds: int,
    cwd: str,
    env: dict[str, str],
    controller: Any,
    provider: str,
) -> subprocess.CompletedProcess[str]:
    """Run a local worker process while polling cancel/timeout guards.

    `subprocess.run()` can only interrupt on its own timeout. This wrapper lets
    the same provider runtime controller observe elapsed time and cancel flags
    while the local Codex/Claude Code worker is still running.
    """

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
    )
    input_sent = False
    while True:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        try:
            controller.cancel_if_requested()
            if timeout_seconds > 0 and elapsed_ms > timeout_seconds * 1000:
                raise ProviderRuntimeGuardViolation(f"{provider} local worker timed out after {timeout_seconds}s")
            stdout, stderr = process.communicate(input=input_text if not input_sent else None, timeout=0.25)
            return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)
        except subprocess.TimeoutExpired:
            input_sent = True
            controller.observe_usage_delta({"elapsed_ms": elapsed_ms, "usage_source": "process_poll"}, elapsed_ms=elapsed_ms)
            continue
        except ProviderRuntimeGuardViolation:
            process.kill()
            try:
                stdout, stderr = process.communicate(timeout=1)
            except Exception:
                stdout, stderr = "", ""
            raise


def _streaming_enabled(context: dict[str, Any]) -> bool:
    value = context.get("stream") if "stream" in context else context.get("provider_stream")
    guard = context.get("provider_runtime_guard", {}) if isinstance(context.get("provider_runtime_guard", {}), dict) else {}
    if value is None and "stream" in guard:
        value = guard.get("stream")
    if value is None:
        value = os.environ.get("NOVEL_FORGE_PROVIDER_STREAMING", "")
    return _truthy(str(value)) if value is not None else False


def _provider_sdk_streaming_enabled(context: dict[str, Any], adapter: OpenAICompatibleChatAdapter) -> bool:
    value = context.get("provider_sdk_stream") if isinstance(context, dict) else None
    if value is None:
        value = context.get("sdk_stream") if isinstance(context, dict) else None
    env_names = [
        f"NOVEL_FORGE_{adapter.config.provider.upper().replace('-', '_')}_SDK_STREAMING",
        f"{adapter.config.provider.upper().replace('-', '_')}_SDK_STREAMING",
        "NOVEL_FORGE_PROVIDER_SDK_STREAMING",
    ]
    for env_name in env_names:
        if value is None and os.environ.get(env_name, "") != "":
            value = os.environ.get(env_name, "")
    return _truthy(str(value)) if value is not None else False


def _openai_sdk_available() -> bool:
    try:
        return importlib.util.find_spec("openai") is not None
    except (ImportError, ValueError):
        return False


def _run_openai_compatible_sdk_stream(
    *,
    adapter: OpenAICompatibleChatAdapter,
    api_key: str,
    request_payload: dict[str, Any],
    controller: Any,
    operation: str,
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - exercised by health when SDK is absent
        raise RuntimeError("OpenAI-compatible SDK streaming requires optional dependency: openai") from exc
    client = OpenAI(api_key=api_key, base_url=_openai_sdk_base_url(adapter._base_url()))
    stream = client.chat.completions.create(**request_payload)
    return _read_openai_sdk_stream(stream, controller=controller, operation=operation, provider=adapter.config.provider)


def _openai_sdk_base_url(url: str) -> str:
    value = str(url or "").rstrip("/")
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")]
    return value


def _read_openai_sdk_stream(stream: Any, *, controller: Any, operation: str, provider: str) -> dict[str, Any]:
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason = ""
    chunk_count = 0
    try:
        for chunk in stream:
            chunk_count += 1
            event = _sdk_chunk_to_dict(chunk)
            event_usage = event.get("usage") if isinstance(event.get("usage", {}), dict) else {}
            if event_usage:
                usage.update(event_usage)
                controller.observe_usage_delta({**event_usage, "usage_source": "provider_sdk_stream"})
            choices = event.get("choices", []) if isinstance(event.get("choices", []), list) else []
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
                delta = choice.get("delta", {}) if isinstance(choice.get("delta", {}), dict) else {}
                fragment = str(delta.get("content") or "")
                if fragment:
                    content_parts.append(fragment)
                    controller.observe_usage_delta(estimate_usage_from_text("", fragment, usage_source="provider_sdk_stream_estimated"))
            controller.cancel_if_requested()
    except ProviderRuntimeGuardViolation:
        _close_stream(stream)
        raise
    normalized_usage = normalize_provider_usage({**usage, "finish_reason": finish_reason}, usage_source="provider_sdk_stream")
    return {
        "choices": [{"message": {"content": "".join(content_parts)}, "finish_reason": finish_reason}],
        "usage": normalized_usage,
        "stream": {"enabled": True, "adapter": "openai_compatible_sdk", "chunk_count": chunk_count, "finish_reason": finish_reason},
    }


def _sdk_chunk_to_dict(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    if hasattr(chunk, "model_dump"):
        try:
            data = chunk.model_dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    choices = []
    for choice in getattr(chunk, "choices", []) or []:
        delta = getattr(choice, "delta", None)
        choices.append(
            {
                "finish_reason": getattr(choice, "finish_reason", None),
                "delta": {
                    "content": getattr(delta, "content", "") if delta is not None else "",
                },
            }
        )
    usage = getattr(chunk, "usage", None)
    usage_payload = usage if isinstance(usage, dict) else (usage.model_dump() if hasattr(usage, "model_dump") else {})
    return {"choices": choices, "usage": usage_payload}


def _close_stream(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            return


def _read_openai_compatible_stream(response: Any, *, controller: Any, operation: str, provider: str) -> dict[str, Any]:
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason = ""
    chunks: list[dict[str, Any]] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        chunks.append(event)
        event_usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        if event_usage:
            usage.update(event_usage)
            controller.observe_usage_delta({**event_usage, "usage_source": "provider_stream"})
        choices = event.get("choices", []) if isinstance(event.get("choices", []), list) else []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                finish_reason = str(choice.get("finish_reason") or "")
            delta = choice.get("delta", {}) if isinstance(choice.get("delta", {}), dict) else {}
            fragment = str(delta.get("content") or "")
            if fragment:
                content_parts.append(fragment)
                controller.observe_usage_delta(estimate_usage_from_text("", fragment, usage_source="provider_stream_estimated"))
        controller.cancel_if_requested()
    content = "".join(content_parts)
    normalized_usage = normalize_provider_usage({**usage, "finish_reason": finish_reason}, usage_source="provider_stream")
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": normalized_usage,
        "stream": {"enabled": True, "chunk_count": len(chunks), "finish_reason": finish_reason},
    }


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _which_executable(executable: str) -> str:
    if not executable:
        return ""
    if Path(executable).expanduser().exists():
        return str(Path(executable).expanduser())
    return shutil.which(executable) or ""
