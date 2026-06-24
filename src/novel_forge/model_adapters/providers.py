from __future__ import annotations

import os
from typing import Any

from novel_forge.model_adapters.base import AdapterNotConfiguredError, ModelAdapterConfig


class ProviderAdapter:
    """Contract skeleton for future external model providers.

    These classes intentionally do not call external APIs. They expose health checks and
    fail closed for generation/review operations until a concrete provider implementation
    is added through an ADR-backed dependency and secret policy.
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
            "message": "contract skeleton only; no external API call is implemented",
        }

    def _not_configured(self, operation: str) -> AdapterNotConfiguredError:
        return AdapterNotConfiguredError(
            f"{self.config.provider} adapter cannot run {operation}: "
            "provider skeleton is not implemented and must not call external APIs in tests"
        )


class ClaudeCodeAdapter(ProviderAdapter):
    config = ModelAdapterConfig(
        provider="claude-code",
        role="chief editor / workflow controller / audit owner",
        default_model="manual-claude-code-runtime",
        required_env_vars=[],
        external_api=False,
    )


class CodexAdapter(ProviderAdapter):
    config = ModelAdapterConfig(
        provider="codex",
        role="engineering editor / code implementation reviewer",
        default_model="manual-codex-runtime",
        required_env_vars=[],
        external_api=False,
    )


class ChatGPTAdapter(ProviderAdapter):
    config = ModelAdapterConfig(
        provider="chatgpt",
        role="advanced review / multidisciplinary synthesis / commercial logic analysis",
        default_model="future-chatgpt-provider",
        required_env_vars=["OPENAI_API_KEY"],
        external_api=True,
    )


class DeepSeekAdapter(ProviderAdapter):
    config = ModelAdapterConfig(
        provider="deepseek",
        role="long-form draft generation",
        default_model="future-deepseek-provider",
        required_env_vars=["DEEPSEEK_API_KEY"],
        external_api=True,
    )


PROVIDER_ADAPTERS = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "chatgpt": ChatGPTAdapter,
    "deepseek": DeepSeekAdapter,
}
