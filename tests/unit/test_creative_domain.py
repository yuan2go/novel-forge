from __future__ import annotations
import unittest
from novel_forge.modules.creative.domain import build_project_proposal, cluster_candidates, evaluate_candidate, validate_creative_brief

class CreativeDomainTests(unittest.TestCase):
    def brief(self):
        return {key: "value" for key in (
            "target_genre", "subgenre", "target_platform", "target_audience", "reading_promise", "core_fantasy", "core_conflict", "protagonist_mechanism", "antagonist_mechanism", "world_novelty", "emotional_engine", "pleasure_engine", "suspense_engine", "serialization_strategy", "prohibited_elements", "source_boundaries", "quality_targets"
        )} | {"theme_question": "When survival demands betrayal, what remains of loyalty?"}
    def candidate(self, cid, project="p1", score=0.8, suffix="a"):
        fields = ("protagonist_advantage_mechanism", "conflict_loop", "growth_loop", "reward_loop", "information_asymmetry", "world_constraint", "relationship_engine", "antagonist_response_pattern", "chapter_payoff_pattern")
        score_fields = ("novelty", "genre_fit", "platform_fit", "conflict_sustainability", "longform_capacity", "protagonist_agency", "antagonist_pressure", "pleasure_potential", "suspense_potential", "theme_potential", "serialization_potential", "similarity_risk", "production_difficulty")
        scores = {key: score for key in score_fields}
        scores["similarity_risk"] = 0.2
        scores["production_difficulty"] = 0.3
        return {"candidate_id": cid, "project_id": project, "fingerprint": {key: f"{key}-{suffix}" for key in fields}, "scores": scores, "known_risks": []}
    def test_brief_requires_specific_theme_question(self):
        brief = self.brief()
        brief["theme_question"] = "freedom"
        with self.assertRaisesRegex(ValueError, "testable question"):
            validate_creative_brief(brief)
    def test_candidate_pool_clusters_mechanisms_and_requires_longform(self):
        first = evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("a"))
        duplicate = evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("b"))
        distinct = evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("c", suffix="c"))
        clusters = cluster_candidates([first, duplicate, distinct])
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["duplicate_candidate_ids"], ["b"])
        proposal = build_project_proposal(project_id="p1", brief_version_id="brief-v1", evaluations=[first, distinct])
        self.assertEqual(proposal["approval_status"], "REQUIRES_OPERATOR_APPROVAL")
    def test_cross_project_and_weak_longform_fail(self):
        with self.assertRaisesRegex(ValueError, "outside project"):
            evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("x", project="p2"))
        weak = self.candidate("weak")
        weak["scores"]["longform_capacity"] = 0.2
        self.assertFalse(evaluate_candidate(project_id="p1", brief=self.brief(), candidate=weak)["passed"])

if __name__ == "__main__":
    unittest.main()


def selected_input(**changes):
    return {"contract_version": "creative-input-selection.v1", "book_id": "book-a",
            "source_kind": "CURRENT_AUTHOR_INPUT", "purpose": "WORK_PRODUCTION",
            "intent_ref": "current-author-request", **changes}


def test_source_and_purpose_are_independent_and_historical_samples_are_not_author_intent():
    import pytest
    from novel_forge.modules.creative.input_selection import validate_input_selection
    from novel_forge.modules.command_kernel.errors import KernelError
    for purpose in ("CREATIVE_EVALUATION", "ENGINEERING_REGRESSION", "HISTORICAL_REPLAY"):
        assert validate_input_selection(selected_input(source_kind="HISTORICAL_TEST_SAMPLE", purpose=purpose))["purpose"] == purpose
        assert validate_input_selection(selected_input(purpose=purpose))["source_kind"] == "CURRENT_AUTHOR_INPUT"
    for value in ({}, selected_input(source_kind="HISTORICAL_TEST_SAMPLE"), selected_input(source_kind="REFERENCE_MATERIAL"), selected_input(book_id="")):
        with pytest.raises(KernelError):
            validate_input_selection(value)


def test_generated_proposals_inherit_exact_current_intent_without_another_author_approval():
    import pytest
    from types import SimpleNamespace
    from novel_forge.modules.creative.input_selection import bind_input_selection
    from novel_forge.modules.command_kernel.errors import KernelError
    original = bind_input_selection(selected_input(), project_id="p", workspace_id="w", actor_id="author", operation_id="selection-op")
    parent = {"asset_version_id": "brief-original", "content_hash": "sha256:" + "a" * 64}
    asset = SimpleNamespace(**parent, asset_type="creative_brief", content={"creative_input_selection": original})
    derived = selected_input(source_kind="TASK_GENERATED", parent_input=parent)
    result = bind_input_selection(derived, project_id="p", workspace_id="w", actor_id="worker", operation_id="proposal-op", inputs=(asset,))
    assert result["parent_input"] == parent
    for value in (selected_input(source_kind="TASK_GENERATED"), {**derived, "intent_ref": "other-request"}, {**derived, "purpose": "CREATIVE_EVALUATION"}, {**derived, "book_id": "book-b"}):
        with pytest.raises(KernelError):
            bind_input_selection(value, project_id="p", workspace_id="w", actor_id="worker", operation_id="proposal-op", inputs=(asset,))


def test_actual_foundation_provider_view_excludes_selection_and_executor_evidence():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
    from novel_forge.modules.creative.input_selection import bind_input_selection
    brief = {"creative_brief_contract_version": "creative-brief-v2", "idea": "姐妹协作修好乡村戏台", "genre": "生活喜剧",
             "audience": "成年读者", "constraints": ["第一人称；通过排练分歧推进人物关系"], "source_boundaries": ["本次原创输入"]}
    metadata = bind_input_selection(selected_input(source_kind="HISTORICAL_TEST_SAMPLE", purpose="ENGINEERING_REGRESSION"),
                                    project_id="p", workspace_id="w", actor_id="tester", operation_id="test-op")
    context = {"schema_version": "novelos.planning_context_bundle.v1", "project_id": "p", "book_id": "book-a",
               "input_versions": [{"role": "creative_brief", "asset_type": "creative_brief", "asset_version_id": "brief-a",
                                   "content_hash": "sha256:" + "a" * 64,
                                   "content": {**brief, "creative_input_selection": metadata,
                                               "test_execution": {"hidden_answer": "THIS_MUST_STAY_HOST_ONLY", "stop_cursor": 3}}}]}
    view = build_provider_context_view("creative.candidates.generate", context, {})
    assert view["segments"][0]["content"] == brief
    assert "THIS_MUST_STAY_HOST_ONLY" not in str(view)
    assert "ENGINEERING_REGRESSION" not in str(view)
    assert "current-author-request" not in str(view)


def test_input_scope_never_falls_back_to_another_book_or_workspace():
    import pytest
    from novel_forge.modules.creative.input_selection import bind_input_selection, require_input_scope
    from novel_forge.modules.command_kernel.errors import KernelError
    source = {"creative_input_selection": bind_input_selection(selected_input(), project_id="p", workspace_id="w", actor_id="author", operation_id="op")}
    for scope in (("p", "w", "book-b"), ("p", "other", "book-a"), ("other", "w", "book-a")):
        with pytest.raises(KernelError, match="another Project"):
            require_input_scope(source, project_id=scope[0], workspace_id=scope[1], book_id=scope[2])
    with pytest.raises(KernelError, match="original frozen run"):
        require_input_scope({}, project_id="p", workspace_id="w", book_id="book-a")
