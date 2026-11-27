from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from novel_forge.modules.command_kernel.errors import KernelError


class CreativeCandidateProviderPort(Protocol):
    def generate_candidates(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ScriptedCreativeCandidateProvider:
    candidates: tuple[dict[str, Any], ...]

    def generate_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": "scripted_creative_fixture", "model": "fixture",
            "request_digest": request.get("request_digest", ""),
            "candidates": [dict(item) for item in self.candidates],
            "fixture_protocol_only": True, "real_model_call": False,
            "production_verified": False,
        }


MECHANISM_FIELDS = (
    "protagonist_advantage_mechanism", "conflict_loop", "growth_loop",
    "reward_loop", "information_asymmetry", "world_constraint",
    "relationship_engine", "antagonist_response_pattern", "chapter_payoff_pattern",
)


def build_candidate_pool(
    *, project_id: str, creative_brief_asset_version_id: str,
    provider_receipt_asset_version_id: str, receipt: dict[str, Any],
) -> dict[str, Any]:
    candidates = [dict(item) for item in receipt.get("candidates", [])]
    if len(candidates) < 3:
        raise KernelError(
            "CREATIVE_CANDIDATE_POOL_TOO_SMALL",
            "creative generation must return at least three structured candidates",
        )
    fingerprints: set[tuple[str, ...]] = set()
    for candidate in candidates:
        fingerprint = dict(candidate.get("fingerprint") or {})
        signature = tuple(str(fingerprint.get(field) or "").strip() for field in MECHANISM_FIELDS)
        if any(not value for value in signature):
            raise KernelError(
                "CREATIVE_CANDIDATE_MECHANISM_MISSING",
                "creative candidate is missing a mechanism fingerprint",
            )
        fingerprints.add(signature)
    if len(fingerprints) != len(candidates):
        raise KernelError(
            "CREATIVE_CANDIDATE_MECHANISM_DUPLICATE",
            "creative candidates differ only superficially",
        )
    return {
        "type": "CreativeCandidatePool", "project_id": project_id,
        "creative_brief_asset_version_id": creative_brief_asset_version_id,
        "provider_receipt_asset_version_id": provider_receipt_asset_version_id,
        "candidates": candidates, "candidate_count": len(candidates),
        "mechanism_distinct_count": len(fingerprints),
        "fixture_protocol_only": bool(receipt.get("fixture_protocol_only")),
        "real_model_call": bool(receipt.get("real_model_call")),
        "production_verified": False,
        "contract_version": "creative-candidate-pool-v1",
    }


__all__ = [
    "CreativeCandidateProviderPort", "ScriptedCreativeCandidateProvider",
    "build_candidate_pool",
]
