from novel_forge.model_adapters.base import AdapterNotConfiguredError, ModelAdapter, ModelAdapterConfig
from novel_forge.model_adapters.embeddings import (
    EmbeddingAdapter,
    HashEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    cosine_similarity,
    embedding_adapter_from_env,
    embedding_provider_health,
)
from novel_forge.model_adapters.local_rules import LocalRuleEngine
from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.model_adapters.providers import (
    PROVIDER_ADAPTERS,
    ChatGPTAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    DeepSeekAdapter,
    ProviderAdapter,
)
from novel_forge.model_adapters.output_validation import ModelOutputValidationError, parse_json_object, validate_model_output
from novel_forge.model_adapters.runtime import (
    ProviderRuntimeEvent,
    ProviderRuntimeGuard,
    ProviderRuntimeController,
    ProviderRuntimeGuardViolation,
    ProviderUsage,
    estimate_provider_cost,
    estimate_usage_from_text,
    evaluate_provider_runtime_guard,
    normalize_provider_usage,
    provider_runtime_controller,
    provider_runtime_guard_from_context,
)
from novel_forge.model_adapters.selection import model_from_env, provider_health

__all__ = [
    "AdapterNotConfiguredError",
    "ModelAdapter",
    "ModelAdapterConfig",
    "EmbeddingAdapter",
    "HashEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
    "embedding_adapter_from_env",
    "embedding_provider_health",
    "cosine_similarity",
    "MockModelAdapter",
    "GuardedModelAdapter",
    "ProviderRuntimeGuardError",
    "LocalRuleEngine",
    "ProviderAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "ChatGPTAdapter",
    "DeepSeekAdapter",
    "PROVIDER_ADAPTERS",
    "ModelOutputValidationError",
    "parse_json_object",
    "validate_model_output",
    "ProviderRuntimeEvent",
    "ProviderRuntimeGuard",
    "ProviderRuntimeController",
    "ProviderRuntimeGuardViolation",
    "ProviderUsage",
    "estimate_provider_cost",
    "estimate_usage_from_text",
    "evaluate_provider_runtime_guard",
    "normalize_provider_usage",
    "provider_runtime_controller",
    "provider_runtime_guard_from_context",
    "model_from_env",
    "provider_health",
]


def __getattr__(name: str):
    if name in {"GuardedModelAdapter", "ProviderRuntimeGuardError"}:
        from novel_forge.model_adapters.guarded import GuardedModelAdapter, ProviderRuntimeGuardError

        return {"GuardedModelAdapter": GuardedModelAdapter, "ProviderRuntimeGuardError": ProviderRuntimeGuardError}[name]
    raise AttributeError(name)
