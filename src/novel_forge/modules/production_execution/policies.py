"""Versioned execution policies referenced by InputManifest and Capability."""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
from typing import Any, Mapping


def _hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _Policy:
    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            payload[item.name] = list(value) if isinstance(value, tuple) else value
        return payload

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())


def _require_boolean(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class ContextPolicy(_Policy):
    policy_id: str
    policy_version: str
    maximum_tokens: int
    allowed_asset_types: tuple[str, ...]
    compression_policy_ref: str
    source_policy_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_asset_types",
            tuple(str(item) for item in self.allowed_asset_types),
        )
        if not all(
            (
                self.policy_id,
                self.policy_version,
                self.allowed_asset_types,
                self.compression_policy_ref,
                self.source_policy_ref,
            )
        ):
            raise ValueError("ContextPolicy is incomplete")
        if self.maximum_tokens <= 0:
            raise ValueError("ContextPolicy maximum_tokens must be positive")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextPolicy":
        values = dict(payload)
        values["maximum_tokens"] = int(values.get("maximum_tokens") or 0)
        values["allowed_asset_types"] = tuple(
            values.get("allowed_asset_types") or ()
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class SourcePolicy(_Policy):
    policy_id: str
    policy_version: str
    allowed_eligibility: tuple[str, ...]
    allow_raw_reference_sources: bool
    requires_lineage: bool
    isolation_mode: str

    def __post_init__(self) -> None:
        _require_boolean(
            self.allow_raw_reference_sources,
            "SourcePolicy allow_raw_reference_sources",
        )
        _require_boolean(self.requires_lineage, "SourcePolicy requires_lineage")
        object.__setattr__(
            self,
            "allowed_eligibility",
            tuple(str(item) for item in self.allowed_eligibility),
        )
        if not all(
            (
                self.policy_id,
                self.policy_version,
                self.allowed_eligibility,
                self.isolation_mode,
            )
        ):
            raise ValueError("SourcePolicy is incomplete")
        if self.allow_raw_reference_sources:
            raise ValueError(
                "production execution SourcePolicy cannot admit raw reference sources"
            )
        if not self.requires_lineage:
            raise ValueError("production execution SourcePolicy requires lineage")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourcePolicy":
        values = dict(payload)
        values["allowed_eligibility"] = tuple(
            values.get("allowed_eligibility") or ()
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class ValidationPolicy(_Policy):
    policy_id: str
    policy_version: str
    structural_schema_ref: str
    semantic_validator_refs: tuple[str, ...]
    maximum_repair_attempts: int
    requires_domain_validation: bool

    def __post_init__(self) -> None:
        _require_boolean(
            self.requires_domain_validation,
            "ValidationPolicy requires_domain_validation",
        )
        object.__setattr__(
            self,
            "semantic_validator_refs",
            tuple(str(item) for item in self.semantic_validator_refs),
        )
        if not all(
            (
                self.policy_id,
                self.policy_version,
                self.structural_schema_ref,
                self.semantic_validator_refs,
            )
        ):
            raise ValueError("ValidationPolicy is incomplete")
        if self.maximum_repair_attempts < 0:
            raise ValueError("ValidationPolicy repair attempts cannot be negative")
        if not self.requires_domain_validation:
            raise ValueError("domain validation cannot be delegated to the Gateway")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationPolicy":
        values = dict(payload)
        values["semantic_validator_refs"] = tuple(
            values.get("semantic_validator_refs") or ()
        )
        values["maximum_repair_attempts"] = int(
            values.get("maximum_repair_attempts") or 0
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class CommitPolicy(_Policy):
    policy_id: str
    policy_version: str
    candidate_asset_type: str
    requires_validation_manifest: bool
    requires_approval: bool
    activation_mode: str

    def __post_init__(self) -> None:
        _require_boolean(
            self.requires_validation_manifest,
            "CommitPolicy requires_validation_manifest",
        )
        _require_boolean(self.requires_approval, "CommitPolicy requires_approval")
        if not all(
            (
                self.policy_id,
                self.policy_version,
                self.candidate_asset_type,
                self.activation_mode,
            )
        ):
            raise ValueError("CommitPolicy is incomplete")
        if not self.requires_validation_manifest:
            raise ValueError("CommitPolicy requires a ValidationManifest")
        if self.activation_mode != "DOMAIN_AUTHORITY_ONLY":
            raise ValueError("Gateway cannot own business asset activation")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CommitPolicy":
        values = dict(payload)
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


__all__ = [
    "CommitPolicy",
    "ContextPolicy",
    "SourcePolicy",
    "ValidationPolicy",
]
