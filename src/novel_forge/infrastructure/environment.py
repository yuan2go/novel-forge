from __future__ import annotations

from enum import StrEnum


class RuntimeControlLevel(StrEnum):
    """How strictly a runtime environment is composed and admitted."""

    LOCAL = "LOCAL"
    CONTROLLED = "CONTROLLED"


class RuntimeEnvironment(StrEnum):
    """Canonical deployment environment used by every production boundary."""

    DEVELOPMENT = "development"
    TEST = "test"
    VALIDATION = "validation"
    PRODUCTION = "production"

    @classmethod
    def parse(cls, value: str | "RuntimeEnvironment") -> "RuntimeEnvironment":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                f"environment {normalized!r} must be development, test, "
                "validation, or production"
            ) from exc

    @property
    def control_level(self) -> RuntimeControlLevel:
        if self in {self.VALIDATION, self.PRODUCTION}:
            return RuntimeControlLevel.CONTROLLED
        return RuntimeControlLevel.LOCAL

    @property
    def controlled(self) -> bool:
        return self.control_level is RuntimeControlLevel.CONTROLLED

    @property
    def fixture_allowed(self) -> bool:
        return not self.controlled


def runtime_environment(value: str | RuntimeEnvironment) -> RuntimeEnvironment:
    return RuntimeEnvironment.parse(value)


def is_controlled_environment(value: str | RuntimeEnvironment) -> bool:
    return RuntimeEnvironment.parse(value).controlled


__all__ = [
    "RuntimeControlLevel",
    "RuntimeEnvironment",
    "is_controlled_environment",
    "runtime_environment",
]
