from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.canon_graph.grounding import text_hash
from novel_forge.modules.command_kernel.errors import KernelError


def require_grounded_acceptance(
    *, project_id: str, selected: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    draft = selected["best_draft_candidate"]
    canon = selected["canon_patch"]
    quality = selected["quality_score_report"]["content"]
    review = selected["re_review_report"]
    binding = canon["content"].get("grounding") or {}
    if not binding:
        raise KernelError("BOOK_UNGROUNDED_CANDIDATE_REBUILD_REQUIRED", "unaccepted legacy prose requires grounded extraction and support review; historical acceptance remains unchanged")
    expected_hash = text_hash(str(draft["content"].get("text") or ""))
    source_id = draft["content"].get("selected_source_asset_version_id")
    context_id = binding.get("context_asset_version_id")
    checks = {
        "contract": binding.get("contract_version") == "grounded-canon.v1",
        "project": binding.get("project_id") == project_id,
        "support": binding.get("semantic_status") == "SUPPORTED_CANDIDATE",
        "candidate": binding.get("candidate_asset_version_id") == draft["asset_version_id"],
        "prose": binding.get("text_hash") == expected_hash,
        "canon": canon["content"].get("source_asset_version_id") == draft["asset_version_id"],
        "review_source": bool(source_id) and review["content"].get("revision_version_id") == source_id,
        "review_text": review["content"].get("target_text_hash") == expected_hash,
        "review_contract": review["content"].get("diagnostic_contract_version") == "actionable-diagnostics.v1",
        "review_context": bool(context_id) and review["content"].get("context_bundle_version_id") == context_id,
        "quality_candidate": quality.get("target_asset_version_id") == draft["asset_version_id"],
        "quality_canon": quality.get("canon_patch_version_id") == canon["asset_version_id"],
        "quality_review": quality.get("review_asset_version_id") == review["asset_version_id"],
        "quality_context": quality.get("context_bundle_version_id") == context_id,
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    if failed:
        raise KernelError("BOOK_GROUNDED_ACCEPTANCE_MISMATCH", "acceptance evidence differs from the final candidate: " + ", ".join(failed))
    return dict(binding)
