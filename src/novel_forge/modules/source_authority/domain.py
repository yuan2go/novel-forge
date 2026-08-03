"""Deterministic Source Governance rules; raw bytes never enter this domain."""
from __future__ import annotations

from dataclasses import dataclass
import re

from novel_forge.modules.command_kernel.errors import KernelError


RIGHTS_AUTHORIZATIONS = frozenset(
    {
        "owned",
        "licensed",
        "public_domain",
        "permission_granted",
        "test_fixture",
        "unknown",
        "forbidden",
        "pirated",
        "infringing",
        "private",
    }
)


@dataclass(frozen=True, slots=True)
class SourceGovernanceDecision:
    lifecycle: str
    eligibility: str
    governance: str
    governance_status: str
    analysis_allowed: bool
    generation_context_allowed: bool = False


@dataclass(frozen=True, slots=True)
class SourceChunkCandidate:
    chunk_index: int
    blob_id: str
    content_hash: str
    byte_size: int
    character_count: int
    token_count: int
    source_byte_start: int
    source_byte_end: int


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_source_chunk_candidates(
    candidates: tuple[SourceChunkCandidate, ...], *, source_size: int
) -> tuple[SourceChunkCandidate, ...]:
    if source_size <= 0:
        raise KernelError("SOURCE_SIZE_INVALID", "Source byte size must be positive")
    if not candidates or len(candidates) > 10_000:
        raise KernelError(
            "SOURCE_CHUNK_COUNT_INVALID",
            "Source transform requires between 1 and 10000 chunks",
        )
    blob_ids: set[str] = set()
    previous_end = 0
    total_bytes = 0
    for expected_index, candidate in enumerate(candidates):
        if candidate.chunk_index != expected_index:
            raise KernelError(
                "SOURCE_CHUNK_INDEX_INVALID",
                "Source chunk indexes must be contiguous and start at zero",
            )
        if not candidate.blob_id.strip() or candidate.blob_id in blob_ids:
            raise KernelError(
                "SOURCE_CHUNK_BLOB_INVALID", "Source chunk Blob identities must be unique"
            )
        if not _SHA256.fullmatch(candidate.content_hash):
            raise KernelError(
                "SOURCE_CHUNK_HASH_INVALID", "Source chunk hash must be canonical sha256"
            )
        if min(
            candidate.byte_size,
            candidate.character_count,
            candidate.token_count,
        ) <= 0:
            raise KernelError(
                "SOURCE_CHUNK_MEASURE_INVALID",
                "Source chunk byte, character and token counts must be positive",
            )
        if (
            candidate.source_byte_start < previous_end
            or candidate.source_byte_end <= candidate.source_byte_start
            or candidate.source_byte_end > source_size
        ):
            raise KernelError(
                "SOURCE_CHUNK_SPAN_INVALID",
                "Source chunk evidence spans must be ordered, non-overlapping and in bounds",
            )
        blob_ids.add(candidate.blob_id)
        previous_end = candidate.source_byte_end
        total_bytes += candidate.byte_size
    if total_bytes > source_size * 4:
        raise KernelError(
            "SOURCE_TRANSFORM_EXPANSION_INVALID",
            "normalized chunk bytes exceed the bounded transform expansion",
        )
    return candidates


def decide_source_governance(
    *, authorization: str, license_name: str, copyright_boundary: str
) -> SourceGovernanceDecision:
    normalized = authorization.strip().lower()
    if normalized not in RIGHTS_AUTHORIZATIONS:
        raise KernelError(
            "SOURCE_RIGHTS_AUTHORIZATION_INVALID",
            f"unsupported rights authorization: {authorization}",
        )
    if normalized == "licensed" and not license_name.strip():
        raise KernelError(
            "SOURCE_LICENSE_EVIDENCE_REQUIRED",
            "licensed sources require a license or permission identity",
        )
    if normalized in {"licensed", "public_domain", "permission_granted"} and not copyright_boundary.strip():
        raise KernelError(
            "SOURCE_COPYRIGHT_BOUNDARY_REQUIRED",
            "rights-dependent sources require an explicit copyright boundary",
        )
    if normalized in {
        "owned",
        "licensed",
        "public_domain",
        "permission_granted",
        "test_fixture",
    }:
        return SourceGovernanceDecision(
            lifecycle="ACTIVE",
            eligibility="ELIGIBLE",
            governance="CLEAR",
            governance_status="ELIGIBLE",
            analysis_allowed=True,
        )
    if normalized == "unknown":
        return SourceGovernanceDecision(
            lifecycle="CANDIDATE",
            eligibility="PENDING_EVALUATION",
            governance="QUARANTINED",
            governance_status="NEEDS_REVIEW",
            analysis_allowed=False,
        )
    return SourceGovernanceDecision(
        lifecycle="CANDIDATE",
        eligibility="INELIGIBLE",
        governance="QUARANTINED",
        governance_status="QUARANTINED",
        analysis_allowed=False,
    )


__all__ = [
    "RIGHTS_AUTHORIZATIONS",
    "SourceChunkCandidate",
    "SourceGovernanceDecision",
    "decide_source_governance",
    "validate_source_chunk_candidates",
]
