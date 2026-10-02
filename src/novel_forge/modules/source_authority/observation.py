from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_serializer, model_validator

from .corpus import CorpusContract, Digest, Identity
from novel_forge.modules.command_kernel.errors import KernelError


class ObservationSpan(CorpusContract):
    unit_version_id: Identity
    chunk_asset_version_id: Identity
    byte_start: int = Field(ge=0)
    byte_end: int = Field(gt=0)
    content_hash: Digest
    chapter: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> ObservationSpan:
        if self.byte_end <= self.byte_start:
            raise ValueError("observation span must be nonempty")
        return self


class SourceObservationBoundary(CorpusContract):
    boundary_type: Literal["SOURCE_OBSERVATION"]
    task_id: Identity
    source_id: Identity
    edition_id: Identity
    processing_id: Identity
    source_work_asset_version_id: Identity
    source_hash: Digest
    mode: Literal["PREFIX", "RETROSPECTIVE"]
    visible_through_chapter: int = Field(gt=0)
    spans: tuple[ObservationSpan, ...] = Field(min_length=1, max_length=4096)
    authorization_ref: Identity
    authorized_actor_id: Identity
    expires_at: datetime
    use: Literal["SOURCE_ANALYSIS"]
    transmission: Literal["PRIVATE_DESIGNATED_ACCOUNT"]
    provider: Literal["codex-cli"]
    model: Literal["gpt-6.1-sol"]
    reasoning_effort: Literal["high"]
    acknowledged_numbering_issue_ids: tuple[Digest, ...] = Field(default=(), max_length=32)

    @model_serializer(mode="wrap")
    def frozen_boundary(self, handler: Any) -> dict[str, Any]:
        value = handler(self)
        if not self.acknowledged_numbering_issue_ids:
            value.pop("acknowledged_numbering_issue_ids", None)
        return value

    @model_validator(mode="after")
    def observed(self) -> SourceObservationBoundary:
        if self.expires_at.tzinfo is None:
            raise ValueError("authorization expiry must have a timezone")
        if any(span.chapter > self.visible_through_chapter for span in self.spans):
            raise ValueError("future span outside observation boundary")
        keys = [(s.chunk_asset_version_id, s.byte_start, s.byte_end) for s in self.spans]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate observation spans")
        return self


def observation_boundary(value: Any) -> SourceObservationBoundary:
    try:
        result = SourceObservationBoundary.model_validate(value)
    except ValueError as exc:
        raise KernelError("SOURCE_OBSERVATION_INVALID", str(exc)) from exc
    if result.expires_at <= datetime.now(timezone.utc):
        raise KernelError("SOURCE_OBSERVATION_EXPIRED", "registered research permission expired")
    return result


def validate_local_integrity(
    assessment: dict, units: list[dict], *, acknowledged_numbering_issue_ids: tuple[str, ...] = ()
) -> None:
    if assessment.get("acquisition_integrity") != "VERIFIED_BYTES":
        raise KernelError("SOURCE_OBSERVATION_INTEGRITY", "unverified acquired source")
    acknowledged = set(acknowledged_numbering_issue_ids)
    matched = set()
    for issue in assessment.get("issues", []):
        if not issue.get("blocking"):
            continue
        evidence = issue.get("evidence") or []
        if not evidence:
            raise KernelError("SOURCE_OBSERVATION_INTEGRITY", "unlocalized integrity issue")
        for item in evidence:
            locator = item.get("locator") or {}
            if not {"path", "original_byte_offset", "original_byte_end"} <= locator.keys():
                raise KernelError("SOURCE_OBSERVATION_INTEGRITY", "unstable integrity mapping")
            for unit in units:
                local = unit["source_locator"]
                if locator["path"] == local.get("path") and locator["original_byte_offset"] < local.get("original_byte_end", 0) and locator["original_byte_end"] > local.get("original_byte_offset", 0):
                    # INVARIANT: A numbering gap limits continuity claims, not the bytes of an exact available unit; all other local damage still blocks.
                    if (
                        issue.get("issue_id") in acknowledged
                        and issue.get("code") == "MISSING_OR_UNORDERED_CHAPTER"
                        and unit.get("status") == "AVAILABLE"
                        and unit.get("kind") in {"chapter", "extra"}
                        and locator == local
                        and locator.get("precision") == "UNIT_BYTES"
                        and item.get("content_hash")
                        and item["content_hash"] == unit.get("normalized_content_hash")
                    ):
                        matched.add(issue["issue_id"])
                        continue
                    raise KernelError("SOURCE_OBSERVATION_INTEGRITY", "integrity issue intersects observed unit")
    if acknowledged != matched:
        raise KernelError("SOURCE_OBSERVATION_INTEGRITY", "numbering acknowledgement must bind an exact observed issue")
