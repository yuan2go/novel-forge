from __future__ import annotations

import hashlib
import json
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


def resolve_accepted_manuscript(workspace: Mapping[str, Any]) -> dict[str, Any]:
    def fail(reason: str) -> None:
        raise KernelError("CHAPTER_ACCEPTED_EXPORT_INVALID", reason)

    acceptance = workspace.get("acceptance") or {}
    if acceptance.get("status") != "COMMITTED" or not acceptance.get("acceptance_id"):
        fail("A committed Book acceptance is required")
    project_id = workspace["project_id"]
    documents: dict[str, Any] = {}
    for item in [acceptance.get("outcome"), *(item for items in workspace["artifacts"].values() for item in items)]:
        if not item:
            continue
        identity = item["asset_version_id"]
        previous = documents.get(identity)
        if previous and any(previous[key] != item[key] for key in ("content_hash", "content", "asset_type")):
            fail("Conflicting immutable asset version: " + identity)
        documents[identity] = item

    def require(identity: str, kind: str) -> dict[str, Any]:
        item = documents.get(identity)
        if not identity or not item or item["asset_type"] != kind or item.get("project_id") != project_id:
            fail("Missing or out-of-scope " + kind + ": " + str(identity))
        digest = "sha256:" + hashlib.sha256(json.dumps(item["content"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if digest != item["content_hash"]:
            fail("Content hash mismatch: " + identity)
        return item

    outcome = require(acceptance.get("outcome_asset_version_id", ""), "chapter_outcome")
    value = outcome["content"]
    if (value.get("project_id") != project_id or not workspace.get("book_id")
            or value.get("book_id") != workspace["book_id"]
            or value.get("chapter_number") != acceptance["accepted_through_chapter"]):
        fail("Acceptance Book/chapter lineage differs from ChapterOutcome")
    candidate = require(value.get("accepted_draft_asset_version_id", ""), "best_draft_candidate")
    quality = require(value.get("quality_aggregate_asset_version_id", ""), "quality_score_report")
    canon = require(value.get("canon_patch_asset_version_id", ""), "canon_patch")
    review = require(quality["content"].get("review_asset_version_id", ""), "re_review_report")
    binding = require_grounded_acceptance(project_id=project_id, selected={
        "best_draft_candidate": candidate, "quality_score_report": quality,
        "canon_patch": canon, "re_review_report": review,
    })
    if value.get("grounding") != binding:
        fail("Outcome and Canon grounding differ")
    context = require(binding["context_asset_version_id"], "context_bundle")
    execution = context["content"].get("chapter_execution") or {}
    if execution.get("source_chapter_plan_asset_version_id") != value.get("chapter_plan_version_id"):
        fail("Context was compiled from a different Chapter plan")
    memo = require(execution.get("memo_asset_version_id", ""), "chapter_memo")
    gate = require(value.get("final_release_gate_asset_version_id", ""), "final_release_gate_report")
    versions = gate["content"].get("accepted_asset_version_ids") or {}
    if any(versions.get(key) != item["asset_version_id"] for key, item in (("quality", quality), ("canon", canon), ("rereview", review))):
        fail("Accepted release gate evidence differs from ChapterOutcome")
    return {"candidate": candidate, "quality": quality, "canon": canon, "review": review,
            "context": context, "memo": memo, "outcome": outcome, "gate": gate}
