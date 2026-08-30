from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any


def normalize_logical_ref(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("logical_ref must be a non-empty project-relative POSIX path")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class AuthorityAssetWriteCommand:
    operation_id: str
    project_id: str
    asset_id: str
    asset_type: str
    schema_version: str
    logical_ref: str
    category: str
    output_key: str
    role: str
    content: dict[str, Any]
    qualification_policy: str
    trace_id: str
    correlation_id: str
    expected_current_asset_version_id: str | None = None
    reference_asset_ids: tuple[str, ...] = ()
    causation_id: str = ""
    lifecycle: str = "ACTIVE"
    eligibility: str = "ELIGIBLE"
    governance: str = "CLEAR"

    def __post_init__(self) -> None:
        required = {
            "operation_id": self.operation_id,
            "project_id": self.project_id,
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "schema_version": self.schema_version,
            "category": self.category,
            "output_key": self.output_key,
            "role": self.role,
            "qualification_policy": self.qualification_policy,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"authority asset command fields must not be empty: {', '.join(missing)}")
        if not isinstance(self.content, dict):
            raise ValueError("authority asset content must be an object")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*\.v[0-9]+", self.schema_version):
            raise ValueError("authority asset schema_version is invalid")
        if self.lifecycle != "ACTIVE":
            raise ValueError("materialized authority output must be ACTIVE")
        if self.eligibility not in {"ELIGIBLE", "INELIGIBLE", "REVOKED", "PENDING_EVALUATION"}:
            raise ValueError("unsupported authority asset eligibility")
        if self.governance not in {"CLEAR", "QUARANTINED", "REJECTED", "LEGAL_HOLD"}:
            raise ValueError("unsupported authority asset governance")
        object.__setattr__(self, "logical_ref", normalize_logical_ref(self.logical_ref))
        object.__setattr__(
            self,
            "reference_asset_ids",
            tuple(dict.fromkeys(str(item).strip() for item in self.reference_asset_ids if str(item).strip())),
        )


__all__ = ["AuthorityAssetWriteCommand", "normalize_logical_ref"]
