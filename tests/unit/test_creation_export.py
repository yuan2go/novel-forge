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


def test_knowledge_trace_keeps_selection_and_actual_accepted_prose_check_separate():
    from novel_forge.modules.mkaos_authority.trace import workspace_knowledge_trace
    workspace = accepted_workspace()
    workspace["acceptance"].update(story_state_asset_version_id="state:v1", canon_snapshot_asset_version_id="canon:v1")
    items = workspace["artifacts"]["history"]
    context = next(item for item in items if item["asset_type"] == "context_bundle")
    context["content"]["context_manifest"] = {"knowledge_usage": [{"knowledge_card_asset_version_id": "card:v1", "usage_role": "REFERENCE"}]}
    context.update(document("context_bundle", "context", context["content"]))
    review = next(item for item in items if item["asset_type"] == "re_review_report")
    review["content"]["knowledge_checks"] = [{"knowledge_card_asset_version_id": "card:v1", "status": "NOT_USED", "target_text_hash": review["content"]["target_text_hash"]}]
    review.update(document("re_review_report", "review", review["content"]))
    workspace["artifacts"]["inputs"] = [context]
    workspace["artifacts"]["diagnoses"] = [review]
    trace = workspace_knowledge_trace(workspace)["cards"][0]
    assert trace["selected"][0]["context_bundle_asset_version_id"] == "context"
    assert trace["accepted"]["check"]["status"] == "NOT_USED"
    assert trace["independent_editorial"] == "NOT_PROVEN"
    review["content"]["knowledge_checks"][0]["target_text_hash"] = "wrong-prose"
    review.update(document("re_review_report", "review", review["content"]))
    with pytest.raises(KernelError, match="accepted prose"):
        workspace_knowledge_trace(workspace)


def test_six_chapter_blind_export_uses_only_acceptance_bound_text_and_leaves_forms_empty(tmp_path):
    from scripts.prepare_knowledge_closure import blind_export
    from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
    for arm, mode in (("treatment", "ALLOW_ONLY"), ("control", "DENY_ALL")):
        access = resolve_book_knowledge_access_policy(
            production_profile={"knowledge_access_policy": {
                "mode": mode, "allowed_knowledge_card_asset_version_ids": ["card:v1"] if mode == "ALLOW_ONLY" else [],
            }}, project_id="p", book_id=arm,
        )
        folder = tmp_path / arm
        folder.mkdir()
        rows = []
        for chapter in range(1, 7):
            original = accepted_workspace()
            identities = {item["asset_version_id"] for item in original["artifacts"]["history"]} | {"outcome", "plan", "original"}
            def rewrite(value):
                if isinstance(value, str):
                    return f"{arm}:{chapter}:{value}" if value in identities else arm if value == "b" else value
                if isinstance(value, list):
                    return [rewrite(item) for item in value]
                if isinstance(value, dict):
                    return {key: rewrite(item) for key, item in value.items()}
                return value
            workspace = rewrite(original)
            workspace["root_operation_id"] = f"{arm}:root:{chapter}"
            workspace["acceptance"]["accepted_through_chapter"] = chapter
            workspace["acceptance"]["acceptance_id"] = f"{arm}:accept:{chapter}"
            workspace["acceptance"]["outcome"]["content"]["chapter_number"] = chapter
            workspace["run"]["command"]["context_version_refs"] = {"arc_plan_versions": [f"{arm}:arc:{1 if chapter <= 3 else 2}"]}
            context = next(item for item in workspace["artifacts"]["history"] if item["asset_type"] == "context_bundle")
            context["content"]["knowledge_access_policy"] = access
            for item in [workspace["acceptance"]["outcome"], *workspace["artifacts"]["history"]]:
                item.update(document(item["asset_type"], item["asset_version_id"], item["content"]))
            rows.append(workspace)
        (folder / "chapter-workspaces.json").write_text(json.dumps(rows))
        (folder / "creation-run.json").write_text(json.dumps({
            "implementation_identity": "same-source", "brief_input_hash": "same-brief", "formation_policy": {"target_chapters": 6},
            "frozen_configuration": {"models": {"review": "same-frozen-route"},
                                     "creation_policy": {"profiles": {"production_profile": {"content": {"target_chapter_count": 6}}}},
                                     "runtime_settings": {}, "cost_accounting": {"accounting_basis": "FIXTURE"}}, "book_id": arm, "project_id": "p",
            "future_plan_change": {"after_chapter": 3, "result": {"snapshot_id": arm + ":changed-input"}},
            "knowledge_access_policy": access,
        }))
    result = blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "blind")
    assert result["human_approval"] is False
    for form in (tmp_path / "blind").glob("unassigned-reader-*/knowledge-review-form.json"):
        value = json.loads(form.read_text())
        assert value["status"] == "NOT_REVIEWED"
        assert all(score is None for response in value["responses"] for score in response["scores"].values())
    context_path = tmp_path / "control/chapter-workspaces.json"
    original_export = context_path.read_text()
    contaminated = json.loads(original_export)
    context = next(item for item in contaminated[0]["artifacts"]["history"] if item["asset_type"] == "context_bundle")
    context["content"]["context_manifest"] = {"knowledge_usage": [{"asset_type": "knowledge_card", "asset_version_id": "card:v1"}]}
    context.update(document("context_bundle", context["asset_version_id"], context["content"]))
    context_path.write_text(json.dumps(contaminated))
    with pytest.raises(ValueError, match="forbidden external knowledge"):
        blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "contaminated-blind")
    context_path.write_text(original_export)
    report_path = tmp_path / "control/creation-run.json"
    changed = json.loads(report_path.read_text())
    changed["frozen_configuration"]["runtime_settings"] = {"NOVEL_FORGE_CHAPTER_PROVIDER_CAP": "100"}
    report_path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="budgets"):
        blind_export(tmp_path / "treatment", tmp_path / "control", tmp_path / "invalid-blind")


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
