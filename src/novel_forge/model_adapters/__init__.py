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
from novel_forge.model_adapters.guarded import GuardedModelAdapter
from novel_forge.model_adapters.providers import (
    PROVIDER_ADAPTERS,
    ChatGPTAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    DeepSeekAdapter,
    ProviderAdapter,
)
from novel_forge.model_adapters.output_validation import ModelOutputValidationError, parse_json_object, validate_model_output
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
    "model_from_env",
    "provider_health",
]
