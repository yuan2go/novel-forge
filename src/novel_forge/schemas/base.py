from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar

from novel_forge.core.ids import make_id, utc_now

T = TypeVar("T", bound="BaseAsset")

COMMON_FIELDS = [
    "id",
    "type",
    "title",
    "name",
    "source",
    "tags",
    "created_at",
    "updated_at",
    "version",
    "content",
    "metadata",
    "references",
]


@dataclass
class BaseAsset:
    id: str = ""
    type: str = "asset"
    title: str = ""
    name: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    version: str = "0.1.0"
    content: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.title and self.name:
            self.title = self.name
        if not self.name and self.title:
            self.name = self.title
        if not self.id:
            self.id = make_id(self.type, self.title or self.name or self.type)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type
        return data

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        allowed = {field.name for field in fields(cls)}
        filtered = {key: value for key, value in data.items() if key in allowed}
        return cls(**filtered)


def validate_common_fields(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in COMMON_FIELDS:
        if key not in data:
            errors.append(f"missing common field: {key}")
    if data.get("type") == "source_document" and not data.get("source"):
        errors.append("source_document must keep original source path")
    if data.get("type") in {"decomposition_report", "knowledge_card", "material_card"}:
        boundary = data.get("metadata", {}).get("copyright_boundary", "")
        if "abstract" not in boundary.lower() and "structure" not in boundary.lower():
            errors.append("reference-derived assets must declare abstract structure copyright boundary")
    return errors
