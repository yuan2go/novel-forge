from __future__ import annotations

from typing import Any

from novel_forge.model_adapters.base import ModelAdapter
from novel_forge.modules.agent_runs import guard_agent_action
from novel_forge.storage.local import LocalStorage


class GuardedModelAdapter:
    """Model adapter boundary that records Agent allowlist gates before every call."""

    def __init__(self, adapter: ModelAdapter, storage: LocalStorage, agent_run_path: str) -> None:
        self.adapter = adapter
        self.storage = storage
        self.agent_run_path = agent_run_path
        self.name = getattr(adapter, "name", adapter.__class__.__name__)

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._guard()
        return self.adapter.generate(prompt, context)

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._guard()
        return self.adapter.analyze(text, context)

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._guard()
        return self.adapter.review(content, context)

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._guard()
        return self.adapter.revise(content, review, context)

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._guard()
        return self.adapter.batch(prompts, context)

    def health_check(self) -> dict[str, Any]:
        if hasattr(self.adapter, "health_check"):
            return self.adapter.health_check()
        return {"ok": True, "provider": self.name, "model": self.name}

    def _guard(self) -> None:
        guard_agent_action(self.storage, self.agent_run_path, tool_name="call_model_adapter")
