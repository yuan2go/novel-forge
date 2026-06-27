from __future__ import annotations

import os
from typing import Mapping

from novel_forge.model_adapters.base import ModelAdapter
from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.model_adapters.providers import PROVIDER_ADAPTERS


OPERATION_ENV_KEYS = {
    "analyze": "NOVEL_FORGE_ANALYZE_PROVIDER",
    "decompose": "NOVEL_FORGE_ANALYZE_PROVIDER",
    "draft": "NOVEL_FORGE_DRAFT_PROVIDER",
    "generate": "NOVEL_FORGE_DRAFT_PROVIDER",
    "outline": "NOVEL_FORGE_OUTLINE_PROVIDER",
    "chapter_plan": "NOVEL_FORGE_CHAPTER_PLAN_PROVIDER",
    "review": "NOVEL_FORGE_REVIEW_PROVIDER",
    "revise": "NOVEL_FORGE_REVISION_PROVIDER",
    "revision_executor": "NOVEL_FORGE_REVISION_EXECUTOR_PROVIDER",
    "final_draft": "NOVEL_FORGE_REVISION_EXECUTOR_PROVIDER",
    "topic": "NOVEL_FORGE_TOPIC_PROVIDER",
}


def model_from_env(operation: str = "", env: Mapping[str, str] | None = None) -> ModelAdapter:
    values = env or os.environ
    provider = _provider_name(operation, values)
    if provider in {"", "mock", "local", "offline"}:
        return MockModelAdapter()
    adapter_cls = PROVIDER_ADAPTERS.get(provider)
    if adapter_cls is None:
        known = ", ".join(["mock", *sorted(PROVIDER_ADAPTERS)])
        raise ValueError(f"unknown model provider '{provider}'. Expected one of: {known}")
    return adapter_cls()


def provider_health(env: Mapping[str, str] | None = None) -> dict[str, dict]:
    values = env or os.environ
    health = {"mock": MockModelAdapter().health_check()}
    for name, adapter_cls in PROVIDER_ADAPTERS.items():
        adapter = adapter_cls()
        with _patched_environ(values):
            health[name] = adapter.health_check()
    return health


def _provider_name(operation: str, values: Mapping[str, str]) -> str:
    operation_key = OPERATION_ENV_KEYS.get(operation.strip().lower(), "")
    return (
        values.get(operation_key, "")
        or values.get("NOVEL_FORGE_MODEL_PROVIDER", "")
        or values.get("NOVEL_FORGE_PROVIDER", "")
        or "mock"
    ).strip().lower()


class _patched_environ:
    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = values
        self.original: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for key, value in self.values.items():
            self.original[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *args: object) -> None:
        for key, value in self.original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
