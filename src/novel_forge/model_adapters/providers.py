from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from novel_forge.model_adapters.base import AdapterNotConfiguredError, ModelAdapterConfig
from novel_forge.model_adapters.output_validation import parse_json_object, validate_model_output
from novel_forge.model_adapters.prompts import build_messages


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


class OpenAICompatibleChatAdapter(ProviderAdapter):
    """Real JSON-chat provider for OpenAI-compatible APIs.

    Network calls only happen when required secrets are present and a caller explicitly
    selects this adapter. Tests and local demo paths still default to MockModelAdapter.
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
            "message": "ready for JSON chat completions" if self._api_key() else "missing API key",
        }

    def _run_json_operation(self, operation: str, payload: str, context: dict[str, Any] | None) -> dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            raise self._not_configured(operation)
        messages = build_messages(operation, payload, context)
        request_payload = {
            "model": self._model(),
            "messages": messages,
            "temperature": float(os.environ.get("NOVEL_FORGE_MODEL_TEMPERATURE", "0.3")),
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self._base_url(),
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.config.provider} API returned HTTP {exc.code}: {detail[:500]}") from exc
        except Exception as exc:
            raise RuntimeError(f"{self.config.provider} API call failed: {exc}") from exc

        try:
            content = response_data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"{self.config.provider} API response missing choices[0].message.content") from exc
        parsed = parse_json_object(str(content))
        parsed.setdefault("model", self._model())
        parsed.setdefault("provider", self.config.provider)
        return validate_model_output(operation, parsed)

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


class ClaudeCodeAdapter(ProviderAdapter):
    config = ModelAdapterConfig(
        provider="claude-code",
        role="chief editor / workflow controller / audit owner",
        default_model="manual-claude-code-runtime",
        required_env_vars=[],
        external_api=False,
    )

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
        return {
            **status,
            "implemented": "manual_handoff_only",
            "message": "Claude Code is available as an operator workflow, not as an in-process LLM API",
        }


class CodexAdapter(ProviderAdapter):
    config = ModelAdapterConfig(
        provider="codex",
        role="engineering editor / code implementation reviewer",
        default_model="manual-codex-runtime",
        required_env_vars=[],
        external_api=False,
    )


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
