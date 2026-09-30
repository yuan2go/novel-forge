from __future__ import annotations

from typing import Any, Mapping

from .cost_routing import snapshot_hash


REVIEW_TASKS = frozenset({"narrative_semantic_evaluation", "review", "rereview", "canon_support"})
COUNTERPART = {"codex-cli": "deepseek", "deepseek": "codex-cli"}


def reviewer_rejection(contract: Mapping[str, Any], candidate: Mapping[str, Any]) -> str | None:
    if contract.get("schema_version") not in {None, "cross-model-review.v1", "cross-model-review.v2"}:
        return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
    if contract.get("schema_version") == "cross-model-review.v2":
        source = contract.get("source", {})
        reviewer = contract.get("authorized_reviewer", {})
        if (contract.get("reviewer_policy") != "EXPLICIT_AUTHORIZED_REVIEWER"
                or source.get("kind") not in {"AUTHOR_ORIGINAL", "MODEL_EDITED_BY_AUTHOR", "EDITION_MIXED"}
                or not contract.get("target_asset_version_id") or not contract.get("target_content_hash")
                or contract.get("source_hash") != snapshot_hash(source)):
            return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
        if (reviewer.get("provider") not in COUNTERPART
                or not all(reviewer.get(key) for key in ("candidate_id", "model", "model_revision"))):
            return "CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED"
        if any(candidate.get(key) != reviewer[key] for key in ("candidate_id", "provider", "model", "model_revision")):
            return "CROSS_MODEL_REVIEW_AUTHORIZED_REVIEWER_REQUIRED"
        return None
    generator = contract.get("generator", {})
    required = COUNTERPART.get(generator.get("provider"))
    if (not required or contract.get("required_reviewer_provider") != required
            or not generator.get("model_revision") or not contract.get("target_content_hash")):
        return "CROSS_MODEL_REVIEW_IDENTITY_INVALID"
    if candidate.get("provider") != required or candidate.get("model") == generator.get("model"):
        return "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED"
    return None
