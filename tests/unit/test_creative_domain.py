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
        scores = {key: score for key in score_fields}; scores["similarity_risk"] = 0.2; scores["production_difficulty"] = 0.3
        return {"candidate_id": cid, "project_id": project, "fingerprint": {key: f"{key}-{suffix}" for key in fields}, "scores": scores, "known_risks": []}
    def test_brief_requires_specific_theme_question(self):
        brief = self.brief(); brief["theme_question"] = "freedom"
        with self.assertRaisesRegex(ValueError, "testable question"): validate_creative_brief(brief)
    def test_candidate_pool_clusters_mechanisms_and_requires_longform(self):
        first = evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("a"))
        duplicate = evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("b"))
        distinct = evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("c", suffix="c"))
        clusters = cluster_candidates([first, duplicate, distinct])
        self.assertEqual(len(clusters), 2); self.assertEqual(clusters[0]["duplicate_candidate_ids"], ["b"])
        proposal = build_project_proposal(project_id="p1", brief_version_id="brief-v1", evaluations=[first, distinct])
        self.assertEqual(proposal["approval_status"], "REQUIRES_OPERATOR_APPROVAL")
    def test_cross_project_and_weak_longform_fail(self):
        with self.assertRaisesRegex(ValueError, "outside project"): evaluate_candidate(project_id="p1", brief=self.brief(), candidate=self.candidate("x", project="p2"))
        weak = self.candidate("weak"); weak["scores"]["longform_capacity"] = 0.2
        self.assertFalse(evaluate_candidate(project_id="p1", brief=self.brief(), candidate=weak)["passed"])

if __name__ == "__main__": unittest.main()
