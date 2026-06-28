from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from novel_forge.model_adapters.base import ModelAdapter, ModelAdapterConfig
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

DEFAULT_MODEL_PROVIDER = "claude-code"


def model_from_env(operation: str = "", env: Mapping[str, str] | None = None) -> ModelAdapter:
    values = env or os.environ
    explicit_provider = _explicit_provider_name(operation, values)
    route = {} if explicit_provider else _policy_route(operation, values)
    provider = explicit_provider or str(route.get("provider", "")).strip().lower() or DEFAULT_MODEL_PROVIDER
    if provider in {"", "mock", "local", "offline"}:
        return MockModelAdapter()
    adapter_cls = PROVIDER_ADAPTERS.get(provider)
    if adapter_cls is None:
        known = ", ".join(["mock", *sorted(PROVIDER_ADAPTERS)])
        raise ValueError(f"unknown model provider '{provider}'. Expected one of: {known}")
    model_name = str(route.get("model_name", "")).strip()
    if model_name:
        base_config = adapter_cls.config
        return adapter_cls(
            ModelAdapterConfig(
                provider=base_config.provider,
                role=base_config.role,
                default_model=model_name,
                required_env_vars=list(base_config.required_env_vars),
                external_api=base_config.external_api,
            )
        )
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
    return _explicit_provider_name(operation, values) or DEFAULT_MODEL_PROVIDER


def _explicit_provider_name(operation: str, values: Mapping[str, str]) -> str:
    operation_key = OPERATION_ENV_KEYS.get(operation.strip().lower(), "")
    return (
        values.get(operation_key, "")
        or values.get("NOVEL_FORGE_MODEL_PROVIDER", "")
        or values.get("NOVEL_FORGE_PROVIDER", "")
    ).strip().lower()


def _policy_route(operation: str, values: Mapping[str, str]) -> dict[str, str]:
    if str(values.get("NOVEL_FORGE_MODEL_ROUTING", "1")).strip().lower() in {"0", "false", "off", "disabled"}:
        return {}
    root = Path(values.get("NOVEL_FORGE_ROOT", ".")).resolve()
    runs_dir = root / "data" / "runs"
    if not runs_dir.exists():
        return {}
    task_type = operation.strip().lower() or "generate"
    policies: list[dict] = []
    for path in runs_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_routing_policy":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if content.get("status") != "active":
            continue
        policies.append({**data, "_path": str(path)})
    if not policies:
        return {}
    latest = sorted(policies, key=lambda item: str(item.get("updated_at", "")), reverse=True)[0]
    content = latest.get("content", {}) if isinstance(latest.get("content", {}), dict) else {}
    routes = content.get("task_routes", {}) if isinstance(content.get("task_routes", {}), dict) else {}
    route = routes.get(task_type) or routes.get(_fallback_task_type(task_type)) or routes.get("generate") or {}
    if not isinstance(route, dict):
        return {}
    return {key: str(route.get(key, "")) for key in ["provider", "model_name"] if route.get(key)}


def _fallback_task_type(task_type: str) -> str:
    if task_type in {"draft", "outline", "chapter_plan", "topic"}:
        return "generate"
    if task_type in {"decompose"}:
        return "analysis"
    if task_type in {"revise", "revision_executor", "final_draft"}:
        return "revision"
    return task_type


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
