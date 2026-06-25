from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelAdapterConfig:
    provider: str
    role: str
    default_model: str = ""
    required_env_vars: list[str] = field(default_factory=list)
    external_api: bool = True


class AdapterNotConfiguredError(RuntimeError):
    """Raised when a provider adapter is missing implementation or required configuration."""


class ModelAdapter(Protocol):
    name: str

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def health_check(self) -> dict[str, Any]: ...
