from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
from novel_forge.modules.command_kernel.errors import KernelError


def document(kind, identity, content):
    return {"project_id": "p", "asset_type": kind, "asset_version_id": identity,
            "content": content, "content_hash": "sha256:" + hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def accepted_workspace():
    text = "🚪她决定寻找密室，却还不知道入口。"
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    grounding = {"contract_version": "grounded-canon.v1", "project_id": "p",
                 "semantic_status": "SUPPORTED_CANDIDATE", "candidate_asset_version_id": "chosen",
                 "text_hash": digest, "context_asset_version_id": "context"}
    artifacts = [
        document("best_draft_candidate", "chosen", {"text": text, "selected_source_asset_version_id": "original"}),
        document("quality_score_report", "q", {"target_asset_version_id": "chosen", "canon_patch_version_id": "canon", "review_asset_version_id": "review", "context_bundle_version_id": "context"}),
        document("re_review_report", "review", {"revision_version_id": "original", "target_text_hash": digest, "diagnostic_contract_version": "actionable-diagnostics.v1", "context_bundle_version_id": "context"}),
        document("canon_patch", "canon", {"source_asset_version_id": "chosen", "grounding": grounding}),
        document("context_bundle", "context", {"chapter_execution": {"memo_asset_version_id": "memo", "source_chapter_plan_asset_version_id": "plan"}}),
        document("chapter_memo", "memo", {"chapter": 1}),
        document("final_release_gate_report", "gate", {"accepted_asset_version_ids": {"quality": "q", "canon": "canon", "rereview": "review"}}),
        document("quality_score_report", "old-quality", {"target_asset_version_id": "discarded"}),
    ]
    outcome = document("chapter_outcome", "outcome", {"project_id": "p", "book_id": "b", "chapter_number": 1,
        "chapter_plan_version_id": "plan", "accepted_draft_asset_version_id": "chosen",
        "quality_aggregate_asset_version_id": "q", "canon_patch_asset_version_id": "canon",
        "final_release_gate_asset_version_id": "gate", "grounding": grounding})
    return {"project_id": "p", "book_id": "b", "root_operation_id": "chapter-root",
            "run": {"command": {"chapter_plan_content_hash": "sha256:plan"}},
            "artifacts": {"history": artifacts, "diagnoses": [], "facts": []}, "acceptance": {"status": "COMMITTED",
            "acceptance_id": "accepted", "accepted_through_chapter": 1,
            "outcome_asset_version_id": "outcome", "outcome": outcome}}


def test_formal_acceptance_resolves_retained_original_despite_historical_quality_order():
    workspace = accepted_workspace()
    resolved = resolve_accepted_manuscript(workspace)
    workspace["artifacts"]["history"].reverse()
    assert resolve_accepted_manuscript(workspace) == resolved
    assert resolved["candidate"]["asset_version_id"] == "chosen"
    assert resolved["review"]["content"]["revision_version_id"] == "original"
    assert len(workspace["artifacts"]["history"]) == 8


@pytest.mark.parametrize("fault", ["missing_quality", "wrong_hash", "wrong_book", "old_candidate", "wrong_memo", "conflicting_version"])
def test_accepted_export_rejects_incomplete_or_conflicting_evidence(fault):
    workspace = accepted_workspace()
    items = workspace["artifacts"]["history"]
    if fault == "missing_quality":
        items[:] = [item for item in items if item["asset_version_id"] != "q"]
    elif fault == "wrong_hash":
        items[0]["content"]["text"] += "改稿"
    elif fault == "wrong_book":
        workspace["book_id"] = "other-book"
    elif fault == "old_candidate":
        outcome = workspace["acceptance"]["outcome"]["content"]
        outcome["accepted_draft_asset_version_id"] = "discarded"
        workspace["acceptance"]["outcome"] = document("chapter_outcome", "outcome", outcome)
    elif fault == "wrong_memo":
        items[:] = [item for item in items if item["asset_version_id"] != "memo"]
    else:
        items.append(deepcopy(items[0]))
        items[-1]["content"]["text"] = "conflict"
    with pytest.raises(KernelError):
        resolve_accepted_manuscript(workspace)


def test_partial_export_retains_successful_prose_and_reports_conflicting_chapter(tmp_path):
    from scripts.compare_creation_exports import main
    left, right = tmp_path / "before", tmp_path / "after"
    for folder in (left, right):
        folder.mkdir()
        (folder / "chapter-workspaces.json").write_text(json.dumps([accepted_workspace()], ensure_ascii=False))
    damaged = accepted_workspace()
    damaged["acceptance"]["outcome"]["content_hash"] = "sha256:bad"
    (right / "chapter-workspaces.json").write_text(json.dumps([accepted_workspace(), damaged], ensure_ascii=False))
    output = tmp_path / "comparison"
    assert main([str(left), str(right), "--output", str(output)]) == 2
    report = json.loads((output / "comparison.json").read_text())
    assert report["status"] == "PARTIAL_EXPORT"
    assert report["errors"] and (output / "chapter-1-candidate.txt").read_text().startswith("🚪")
    assert report["candidate_cost"]["status"] == "NOT_EXPORTED"
