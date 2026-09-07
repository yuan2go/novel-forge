from __future__ import annotations

from copy import deepcopy

from tests.integration.world_causal_production_support import AutonomousWorldTransport


class CreativeGroundingTransport(AutonomousWorldTransport):
    def __init__(self, *, retain_original=False):
        super().__init__(scenario="delayed_disclosure")
        self.retain_original = retain_original

    def __call__(self, stage, inputs):
        result = super().__call__(stage, inputs)
        if stage == "memo":
            result["creative_guidance"]["emotional_turn"] = "先让人物以为仍可回头，再呈现选择造成的具体代价。"
        if stage == "review" and self.retain_original:
            result.update({"decision": "PASSED", "score": 90, "issues": [], "resolution_checks": []})
        if stage == "revision" and self.retain_original:
            result["resolved_issue_codes"] = []
        if stage == "rereview" and self.retain_original:
            result.update({"decision": "PASSED", "score": 95, "issues": [], "resolution_checks": []})
        self.calls[-1]["output"] = deepcopy(result)
        return result


def verify_creative_workspace(*, composition, chapter_application, book_run_id, transport):
    from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
    from novel_forge.modules.canon_graph.grounding import text_hash
    book = composition.authority.require(book_run_id)
    chapters = ChapterAuthorityQuery(chapter_application.database_url).list_runs(project_id=book["project_id"], book_run_id=book_run_id)
    workspaces = []
    for chapter in chapters:
        root = chapter["root_operation_id"]
        if not root:
            continue
        workspace = ChapterAuthorityQuery(chapter_application.database_url).require_workspace(
            project_id=book["project_id"], root_operation_id=root,
        )
        if workspace["acceptance"] is None:
            continue
        artifacts = workspace["artifacts"]
        memo = artifacts["memo"][0]
        drafts = {item["asset_type"]: item for item in artifacts["candidates"]}
        best = drafts["best_draft_candidate"]
        assert best["content"]["creative_execution"]["memo_asset_version_id"] == memo["asset_version_id"]
        assert best["content"]["creative_execution"]["guidance"]["emotional_turn"].startswith("先让人物")
        canon = next(item for item in artifacts["facts"] if item["asset_type"] == "canon_patch")
        assert canon["content"]["grounding"]["candidate_asset_version_id"] == best["asset_version_id"]
        assert canon["content"]["grounding"]["text_hash"] == text_hash(best["content"]["text"])
        assert canon["content"]["grounding"]["support_review"]["coverage"] == "COMPLETE"
        selected = best["content"]["selected_review"]
        assert selected["target_text_hash"] == canon["content"]["grounding"]["text_hash"]
        assert selected["decision"] == "PASSED"
        if transport.retain_original:
            assert best["content"]["selected_source_asset_version_id"] == drafts["draft_chapter"]["asset_version_id"]
            assert selected["resolved_issue_codes"] == []
        else:
            assert best["content"]["selected_source_asset_version_id"] == drafts["draft_version"]["asset_version_id"]
            assert selected["resolution_checks"]
        workspaces.append(workspace)
    assert len(workspaces) >= 2
    for stage in ("memo", "draft", "review", "revision", "rereview", "canon_extraction", "canon_support"):
        assert len([call for call in transport.calls if call["stage"] == stage]) >= 2
    for call in transport.calls:
        if call["stage"] == "revision" and not transport.retain_original:
            assert call["input"]["review"]["issues"][0]["acceptance_criteria"]
        if call["stage"] == "canon_extraction":
            assert call["input"]["revision"]["selected_review"]["decision"] == "PASSED"
    ordered = sorted(workspaces, key=lambda item: item["acceptance"]["accepted_through_chapter"])
    second_intent = next(item for item in ordered[1]["artifacts"]["inputs"] if item["asset_type"] == "chapter_execution_intent")
    assert second_intent["content"]["accepted_boundary"]["story_state_asset_version_id"] == ordered[0]["acceptance"]["story_state_asset_version_id"]
    return {"proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "workspaces": workspaces}
