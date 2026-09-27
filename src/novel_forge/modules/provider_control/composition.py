from __future__ import annotations

import os
from typing import Mapping

from novel_forge.infrastructure.environment import RuntimeEnvironment

from .openai_v2 import build_openai_provider_adapter
from .registry import ProviderAdapterFactory, ProviderAdapterRegistry
from .scripted import ScriptedProviderAdapterV2


CHAPTER_PROVIDER_ENVIRONMENT_KEYS = (
    "NOVEL_FORGE_MODEL_PROVIDER",
    "NOVEL_FORGE_PLANNING_PROVIDER",
    "NOVEL_FORGE_DRAFT_PROVIDER",
    "NOVEL_FORGE_REVIEW_PROVIDER",
    "NOVEL_FORGE_REVISION_PROVIDER",
    "NOVEL_FORGE_CANON_EXTRACTION_PROVIDER",
    "NOVEL_FORGE_QUALITY_PROVIDER",
    "NOVEL_FORGE_READER_OUTCOME_PROVIDER",
    "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER",
    "NOVEL_FORGE_AGENT_PROVIDER",
)


def normalize_provider_id(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"mock", "local", "offline"}:
        return "scripted_provider_v2"
    return normalized


def configured_chapter_provider_ids(
    values: Mapping[str, str],
) -> frozenset[str]:
    return frozenset(
        provider_id
        for key in CHAPTER_PROVIDER_ENVIRONMENT_KEYS
        if (provider_id := normalize_provider_id(str(values.get(key) or "")))
    )


def build_provider_adapter_registry(
    *,
    environment: RuntimeEnvironment | str,
    provider_ids: set[str] | frozenset[str],
    env: Mapping[str, str] | None = None,
) -> ProviderAdapterRegistry:

    runtime_environment = RuntimeEnvironment.parse(environment)
    values = os.environ if env is None else env
    normalized_ids = {normalize_provider_id(item) for item in provider_ids if item}
    if runtime_environment is RuntimeEnvironment.PRODUCTION or str(
        values.get("NOVEL_FORGE_PROVIDER_ROUTER") or ""
    ).strip() == "quality-cost-v1":
        # WHY: the Router's execution templates require these adapters even when
        # the caller's legacy stage configuration selects only Codex CLI.
        from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates

        normalized_ids.update(candidate.provider for candidate in deepseek_candidates(available=True))
    adapter_ids = normalized_ids - {"codex-cli"}
    factory = ProviderAdapterFactory()
    if runtime_environment.fixture_allowed:
        factory.register(
            "scripted_provider_v2", lambda: ScriptedProviderAdapterV2("success")
        )
    if "openai" in adapter_ids:
        api_key = str(values.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "OpenAI Provider composition requires the OPENAI_API_KEY secret"
            )
        factory.register("openai", lambda: build_openai_provider_adapter(api_key))
    if "deepseek" in adapter_ids:
        from .deepseek import DeepSeekProviderAdapter
        from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates

        deepseek_key = str(values.get("DEEPSEEK_API_KEY") or "").strip()
        if not deepseek_key:
            raise RuntimeError("DeepSeek credential is not configured: DEEPSEEK_API_KEY is required")
        factory.register("deepseek", lambda: DeepSeekProviderAdapter(
            deepseek_key, pricing={item.model: item.pricing for item in deepseek_candidates(available=True)},
        ))
    try:
        return factory.build_registry(adapter_ids)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


__all__ = [
    "CHAPTER_PROVIDER_ENVIRONMENT_KEYS",
    "build_provider_adapter_registry",
    "configured_chapter_provider_ids",
    "normalize_provider_id",
]
