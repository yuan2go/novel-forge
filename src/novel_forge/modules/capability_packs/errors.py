"""Structured errors returned by the Capability Pack P0 boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityPackValidationIssue:
    code: str
    path: str
    message: str
    severity: str


@dataclass(frozen=True, slots=True)
class CapabilityPackValidationReport:
    ok: bool
    pack_id: str
    version: str
    manifest_hash: str
    errors: tuple[CapabilityPackValidationIssue, ...]
    warnings: tuple[CapabilityPackValidationIssue, ...]
    resolved_capabilities: tuple[str, ...]


class CapabilityPackLoadError(ValueError):
    """Fail-closed Loader error with a stable machine-readable code."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.issue = CapabilityPackValidationIssue(
            code=code,
            path=path,
            message=message,
            severity="ERROR",
        )
        super().__init__(f"{code} at {path}: {message}")


__all__ = [
    "CapabilityPackLoadError",
    "CapabilityPackValidationIssue",
    "CapabilityPackValidationReport",
]
