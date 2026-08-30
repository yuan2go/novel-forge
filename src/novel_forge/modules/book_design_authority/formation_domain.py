"""INVARIANT: Durable Story Formation coordination contracts; never Story truth."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .foundation import FoundationRole


STORY_FORMATION_POLICY_VERSION = "story-formation-policy.v1"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class StoryFormationStage(StrEnum):
    CREATIVE_SEARCH = "CREATIVE_SEARCH"
    CREATIVE_FOUNDATION = "CREATIVE_FOUNDATION"
    THEME_CONTRACT = "THEME_CONTRACT"
    ENDING_INTENT = "ENDING_INTENT"
    READER_PROMISE = "READER_PROMISE"
    WORLD_BIBLE = "WORLD_BIBLE"
    CHARACTER_CAST = "CHARACTER_CAST"
    BOOK_DESIGN = "BOOK_DESIGN"
    COMPLETE = "COMPLETE"


FORMATION_SEQUENCE = tuple(StoryFormationStage)


@dataclass(frozen=True, slots=True)
class FormationLayerInput:
    role: FoundationRole
    asset_version_id: str
    content_hash: str
    schema_version: str
    generation_operation_id: str
    qualification_evidence_asset_version_id: str
    qualification_hash: str
    activation_operation_id: str
    candidate_asset_version_ids: tuple[str, ...]
    selection_reason: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", FoundationRole(self.role))
        required = (
            self.asset_version_id,
            self.content_hash,
            self.schema_version,
            self.generation_operation_id,
            self.qualification_evidence_asset_version_id,
            self.qualification_hash,
            self.activation_operation_id,
        )
        if any(not item.strip() for item in required):
            raise ValueError(f"{self.role.value} Formation input is incomplete")
        if any(
            len(value) != 71 or not value.startswith("sha256:")
            for value in (self.content_hash, self.qualification_hash)
        ):
            raise ValueError("Formation content and qualification must be hash-bound")
        if (
            not self.candidate_asset_version_ids
            or len(set(self.candidate_asset_version_ids))
            != len(self.candidate_asset_version_ids)
            or self.asset_version_id not in self.candidate_asset_version_ids
            or not self.selection_reason
        ):
            raise ValueError("Formation selection evidence is incomplete")
        if self.role is FoundationRole.CREATIVE_FOUNDATION and len(
            self.candidate_asset_version_ids
        ) < 2:
            raise ValueError("Creative Search requires at least two compared candidates")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FormationLayerInput":
        expected = {
            "role",
            "asset_version_id",
            "content_hash",
            "schema_version",
            "generation_operation_id",
            "qualification_evidence_asset_version_id",
            "qualification_hash",
            "activation_operation_id",
            "candidate_asset_version_ids",
            "selection_reason",
        }
        if set(value) != expected:
            raise KernelError(
                "STORY_FORMATION_INPUT_INVALID",
                "Formation layer input fields must match exactly",
            )
        return cls(
            role=FoundationRole(str(value["role"])),
            asset_version_id=str(value["asset_version_id"]),
            content_hash=str(value["content_hash"]),
            schema_version=str(value["schema_version"]),
            generation_operation_id=str(value["generation_operation_id"]),
            qualification_evidence_asset_version_id=str(
                value["qualification_evidence_asset_version_id"]
            ),
            qualification_hash=str(value["qualification_hash"]),
            activation_operation_id=str(value["activation_operation_id"]),
            candidate_asset_version_ids=tuple(
                str(item) for item in value["candidate_asset_version_ids"]
            ),
            selection_reason=tuple(str(item) for item in value["selection_reason"]),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["role"] = self.role.value
        value["candidate_asset_version_ids"] = list(
            self.candidate_asset_version_ids
        )
        value["selection_reason"] = list(self.selection_reason)
        return value


@dataclass(frozen=True, slots=True)
class StoryFormationInput:
    layers: tuple[FormationLayerInput, ...]
    book_design_asset_version_id: str = ""
    book_design_content_hash: str = ""

    def __post_init__(self) -> None:
        by_role = {item.role: item for item in self.layers}
        if len(by_role) != len(self.layers) or set(by_role) != set(FoundationRole):
            raise ValueError("Story Formation requires one input for every Foundation role")
        has_version = bool(self.book_design_asset_version_id.strip())
        has_hash = bool(self.book_design_content_hash.strip())
        if has_version != has_hash or (
            has_hash
            and (
                len(self.book_design_content_hash) != 71
                or not self.book_design_content_hash.startswith("sha256:")
            )
        ):
            raise ValueError(
                "Story Formation BookDesign input must be absent or exactly hash-bound"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StoryFormationInput":
        if set(value) != {
            "layers",
            "book_design_asset_version_id",
            "book_design_content_hash",
        } or not isinstance(value.get("layers"), list):
            raise KernelError(
                "STORY_FORMATION_INPUT_INVALID",
                "Story Formation input fields must match exactly",
            )
        return cls(
            layers=tuple(FormationLayerInput.from_mapping(item) for item in value["layers"]),
            book_design_asset_version_id=str(value["book_design_asset_version_id"]),
            book_design_content_hash=str(value["book_design_content_hash"]),
        )

    @property
    def by_role(self) -> dict[FoundationRole, FormationLayerInput]:
        return {item.role: item for item in self.layers}

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers": [item.to_dict() for item in self.layers],
            "book_design_asset_version_id": self.book_design_asset_version_id,
            "book_design_content_hash": self.book_design_content_hash,
        }

    @property
    def digest(self) -> str:
        return _canonical_hash(self.to_dict())


__all__ = [
    "FORMATION_SEQUENCE",
    "FormationLayerInput",
    "STORY_FORMATION_POLICY_VERSION",
    "StoryFormationInput",
    "StoryFormationStage",
]
