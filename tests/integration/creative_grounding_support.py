from __future__ import annotations

from copy import deepcopy

from tests.integration.world_causal_production_support import AutonomousWorldTransport


class CreativeGroundingTransport(AutonomousWorldTransport):
    def __init__(self, *, retain_original=False, negative=""):
        super().__init__(scenario="delayed_disclosure")
        self.retain_original = retain_original
        self.negative = negative
        self.deleted_claim = None

    def planning(self, stage, inputs):
        result = super().planning(stage, inputs)
        if self.negative == "plan" and stage == "chapter_plan.generate":
            result["scene_plan"][0]["goal"] = "发现密室"
        return result

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
        sentence = {"plan": "她决定寻找密室。", "dialogue": "守卫说：“反派已经死了。”玛拉尚未核实。", "deleted": "铜铃碎裂。"}.get(self.negative)
        if sentence and stage == "draft":
            result["scene_artifacts"][-1]["text"] += " " + sentence
            result["text"] = "\n\n".join(item["text"] for item in result["scene_artifacts"])
            self.deleted_claim = {"evidence_start": result["text"].index(sentence), "evidence_end": result["text"].index(sentence) + len(sentence), "evidence_quote": sentence}
        if self.negative == "deleted" and stage == "revision":
            for artifact in result["scene_artifacts"]:
                artifact["text"] = artifact["text"].replace("铜铃碎裂。", "铜铃仍完好。")
            result["text"] = "\n\n".join(item["text"] for item in result["scene_artifacts"])
        if self.negative and stage == "canon_extraction":
            text = inputs["revision"]["text"]
            claim = dict(result["canon_facts"][0])
            claim.update({"subject": "antagonist" if self.negative == "dialogue" else "hero",
                          "predicate": "dead" if self.negative == "dialogue" else "discovered",
                          "object": "true" if self.negative == "dialogue" else "secret-room",
                          "claim_kind": "OBJECTIVE_EVENT"})
            claim.update(self.deleted_claim if self.negative == "deleted" else {
                "evidence_start": text.index(sentence), "evidence_end": text.index(sentence) + len(sentence), "evidence_quote": sentence})
            result["canon_facts"] = [claim]
        if self.negative and stage == "canon_support":
            suspect = {item["claim"]["grounded_claim_id"] for item in inputs["claims"] if item["claim"].get("predicate") in {"dead", "discovered"}}
            for assessment in result["claims"]:
                if assessment["claim_id"] in suspect:
                    assessment.update({"assessment": "UNSUPPORTED", "observed_kind": "PLAN" if self.negative == "plan" else "DIALOGUE_ASSERTION", "reason": "正文只支持打算或对白断言，没有证明客观结果。"})
        if self.negative == "memo" and stage == "memo":
            result = {"execution_strategy": "Missing required creative guidance"}
        self.calls[-1]["output"] = deepcopy(result)
        return result


def verify_creative_workspace(*, composition, chapter_application, book_run_id, transport, minimum_chapters=2):
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
    assert len(workspaces) >= minimum_chapters
    for stage in ("memo", "draft", "review", "revision", "rereview", "canon_extraction", "canon_support"):
        assert len([call for call in transport.calls if call["stage"] == stage]) >= minimum_chapters
    for call in transport.calls:
        if call["stage"] == "revision" and not transport.retain_original:
            assert call["input"]["review"]["issues"][0]["acceptance_criteria"]
        if call["stage"] == "canon_extraction":
            assert call["input"]["revision"]["selected_review"]["decision"] == "PASSED"
    ordered = sorted(workspaces, key=lambda item: item["acceptance"]["accepted_through_chapter"])
    if len(ordered) > 1:
        second_intent = next(item for item in ordered[1]["artifacts"]["inputs"] if item["asset_type"] == "chapter_execution_intent")
        assert second_intent["content"]["accepted_boundary"]["story_state_asset_version_id"] == ordered[0]["acceptance"]["story_state_asset_version_id"]
    return {"proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "workspaces": workspaces}


def verify_rejected_creative(*, composition, chapter_application, project_id, error, transport):
    from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery
    query = ChapterAuthorityQuery(chapter_application.database_url)
    runs = query.list_runs(project_id=project_id)
    assert len(runs) == 1
    workspace = query.require_workspace(project_id=project_id, root_operation_id=runs[0]["root_operation_id"])
    assert workspace["acceptance"] is None
    assert composition.authority.require(workspace["book_run_id"])["accepted_through_chapter"] == 0
    assert not any(item["asset_type"] == "canon_patch" for item in workspace["artifacts"]["facts"])
    if transport.negative == "memo":
        assert not workspace["artifacts"]["memo"] and not workspace["artifacts"]["candidates"]
        assert [call["stage"] for call in transport.calls if call["stage"] == "memo"] == ["memo"]
        return {"book_run_id": workspace["book_run_id"], "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
                "blocked_reason": error.code, "workspace": workspace, "calls": transport.calls}
    assert workspace["artifacts"]["memo"] and workspace["artifacts"]["diagnoses"]
    assert any(call["stage"] == "canon_extraction" for call in transport.calls)
    assert error.code == ("CANON_GROUNDING_INVALID" if transport.negative == "deleted" else "CANON_GROUNDING_REEXTRACTION_REQUIRED")
    return {"book_run_id": workspace["book_run_id"], "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            "blocked_reason": error.code, "workspace": workspace, "calls": transport.calls}
