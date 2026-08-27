"""Exact qualified Foundation Set contracts.

The contracts bind existing immutable StoryDesign AssetVersions.  They do not
create another Story Authority and deliberately contain no mutable projection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

FOUNDATION_SET_SCHEMA_VERSION = "qualified-foundation-set.v1"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_hash(value: str, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise KernelError(
            "FOUNDATION_BINDING_INVALID",
            f"{field} must be an exact SHA-256 content binding",
        )


class FoundationRole(StrEnum):
    CREATIVE_FOUNDATION = "CREATIVE_FOUNDATION"
    THEME_CONTRACT = "THEME_CONTRACT"
    ENDING_INTENT = "ENDING_INTENT"
    READER_PROMISE = "READER_PROMISE"
    WORLD_BIBLE = "WORLD_BIBLE"
    CHARACTER_CAST = "CHARACTER_CAST"

    @property
    def required_parents(self) -> tuple["FoundationRole", ...]:
        if self is FoundationRole.CREATIVE_FOUNDATION:
            return ()
        creative_contracts = (
            FoundationRole.CREATIVE_FOUNDATION,
            FoundationRole.THEME_CONTRACT,
            FoundationRole.ENDING_INTENT,
            FoundationRole.READER_PROMISE,
        )
        if self in {
            FoundationRole.THEME_CONTRACT,
            FoundationRole.ENDING_INTENT,
            FoundationRole.READER_PROMISE,
        }:
            return (FoundationRole.CREATIVE_FOUNDATION,)
        if self is FoundationRole.WORLD_BIBLE:
            return creative_contracts
        return (*creative_contracts, FoundationRole.WORLD_BIBLE)


_AUTHORITY_BY_ROLE = MappingProxyType(
    {role: "STORY_DESIGN_AUTHORITY" for role in FoundationRole}
)


@dataclass(frozen=True, slots=True)
class FoundationBinding:
    role: FoundationRole
    authority: str
    asset_version_id: str
    content_hash: str
    schema_version: str
    qualification_evidence_asset_version_id: str
    qualification_hash: str
    activation_id: str
    upstream_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", FoundationRole(self.role))
        required = (
            self.authority,
            self.asset_version_id,
            self.schema_version,
            self.qualification_evidence_asset_version_id,
            self.activation_id,
        )
        if any(not value.strip() for value in required):
            raise KernelError(
                "FOUNDATION_BINDING_INVALID",
                f"{self.role.value} binding identity is incomplete",
            )
        if self.authority != _AUTHORITY_BY_ROLE[self.role]:
            raise KernelError(
                "FOUNDATION_AUTHORITY_INVALID",
                f"{self.role.value} is not owned by the declared Authority",
            )
        _require_hash(self.content_hash, "content_hash")
        _require_hash(self.qualification_hash, "qualification_hash")
        if self.role.required_parents:
            _require_hash(self.upstream_digest, "upstream_digest")
        elif self.upstream_digest:
            raise KernelError(
                "FOUNDATION_LINEAGE_DRIFT",
                "Creative Foundation cannot claim an upstream Story binding",
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FoundationBinding":
        allowed = {
            "role",
            "authority",
            "asset_version_id",
            "content_hash",
            "schema_version",
            "qualification_evidence_asset_version_id",
            "qualification_hash",
            "activation_id",
            "upstream_digest",
        }
        if set(value) != allowed:
            raise KernelError(
                "FOUNDATION_BINDING_INVALID",
                "Foundation binding fields must match the typed contract exactly",
            )
        return cls(
            role=FoundationRole(str(value["role"])),
            authority=str(value["authority"]),
            asset_version_id=str(value["asset_version_id"]),
            content_hash=str(value["content_hash"]),
            schema_version=str(value["schema_version"]),
            qualification_evidence_asset_version_id=str(
                value["qualification_evidence_asset_version_id"]
            ),
            qualification_hash=str(value["qualification_hash"]),
            activation_id=str(value["activation_id"]),
            upstream_digest=str(value["upstream_digest"]),
        )

    def to_dict(self) -> dict[str, str]:
        value = asdict(self)
        value["role"] = self.role.value
        return value


def foundation_upstream_digest(bindings: Iterable[FoundationBinding]) -> str:
    ordered = sorted(bindings, key=lambda item: item.role.value)
    return _canonical_hash(
        [
            {
                "role": item.role.value,
                "asset_version_id": item.asset_version_id,
                "content_hash": item.content_hash,
                "qualification_hash": item.qualification_hash,
                "activation_id": item.activation_id,
            }
            for item in ordered
        ]
    )


@dataclass(frozen=True, slots=True)
class QualifiedFoundationSet:
    bindings: tuple[FoundationBinding, ...]
    set_digest: str
    schema_version: str = FOUNDATION_SET_SCHEMA_VERSION

    @classmethod
    def from_bindings(
        cls, bindings: tuple[FoundationBinding, ...]
    ) -> "QualifiedFoundationSet":
        by_role: dict[FoundationRole, FoundationBinding] = {}
        for binding in bindings:
            if binding.role in by_role:
                raise KernelError(
                    "FOUNDATION_BINDING_DUPLICATE",
                    f"duplicate Foundation binding for {binding.role.value}",
                )
            by_role[binding.role] = binding
        missing = set(FoundationRole) - set(by_role)
        if missing:
            raise KernelError(
                "FOUNDATION_SET_INCOMPLETE",
                "Foundation Set is missing: "
                + ", ".join(sorted(role.value for role in missing)),
            )
        for role, binding in by_role.items():
            parents = tuple(by_role[parent] for parent in role.required_parents)
            expected = foundation_upstream_digest(parents) if parents else ""
            if binding.upstream_digest != expected:
                raise KernelError(
                    "FOUNDATION_LINEAGE_DRIFT",
                    f"{role.value} does not bind the exact required parent versions",
                )
        ordered = tuple(by_role[role] for role in FoundationRole)
        return cls(
            bindings=ordered,
            set_digest=_canonical_hash([item.to_dict() for item in ordered]),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QualifiedFoundationSet":
        if set(value) != {"schema_version", "bindings", "set_digest"}:
            raise KernelError(
                "FOUNDATION_SET_INVALID",
                "Foundation Set fields must match the typed contract exactly",
            )
        if value.get("schema_version") != FOUNDATION_SET_SCHEMA_VERSION:
            raise KernelError(
                "FOUNDATION_SET_INVALID", "Foundation Set schema is unsupported"
            )
        raw = value.get("bindings")
        if not isinstance(raw, list):
            raise KernelError(
                "FOUNDATION_SET_INVALID", "Foundation bindings must be an array"
            )
        parsed = cls.from_bindings(
            tuple(
                FoundationBinding.from_mapping(item)
                for item in raw
                if isinstance(item, Mapping)
            )
        )
        if len(parsed.bindings) != len(raw) or parsed.set_digest != value.get(
            "set_digest"
        ):
            raise KernelError(
                "FOUNDATION_SET_DIGEST_DRIFT",
                "Foundation Set content differs from its frozen digest",
            )
        return parsed

    @property
    def by_role(self) -> Mapping[FoundationRole, FoundationBinding]:
        return MappingProxyType({item.role: item for item in self.bindings})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bindings": [item.to_dict() for item in self.bindings],
            "set_digest": self.set_digest,
        }


__all__ = [
    "FOUNDATION_SET_SCHEMA_VERSION",
    "FoundationBinding",
    "FoundationRole",
    "QualifiedFoundationSet",
    "foundation_upstream_digest",
]
