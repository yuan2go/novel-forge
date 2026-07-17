from __future__ import annotations

import unittest

from novel_forge.modules.context_builder.domain import (
    ContextCandidate,
    build_authority_context_bundle,
)
from novel_forge.modules.mkaos.selection_domain import (
    KnowledgeCandidate,
    select_knowledge_pack,
    selection_to_context_candidates,
)


class MkaosAuthoritySelectionTests(unittest.TestCase):
    def candidate(self, asset_version_id: str, **changes):
        values = {
            "asset_version_id": asset_version_id, "project_id": "project-a",
            "asset_type": "knowledge_pack", "estimated_tokens": 100,
            "semantic_relevance": 0.9, "stage_fit": 0.9, "genre_fit": 0.8,
            "narrative_function": 0.8, "source_trust": 0.9, "source_risk": 0.1,
            "usage_history": 0.6, "quality_score": 0.9, "freshness": 0.9,
            "redundancy": 0.1, "conflict": 0.0, "project_specificity": 1.0,
            "source_policy_version": "policy-v1", "content_digest": f"sha256:{asset_version_id}",
            "narrative_function_label": asset_version_id,
        }
        values.update(changes)
        return KnowledgeCandidate(**values)

    def test_selection_records_score_reasons_versions_and_rejections(self) -> None:
        result = select_knowledge_pack(
            project_id="project-a", stage="draft", query_intent="make the choice causally costly",
            token_budget=200,
            candidates=[
                self.candidate("best"),
                self.candidate("foreign", project_id="project-b"),
                self.candidate("revoked", qualification="REVOKED"),
                self.candidate("conflict", conflict=0.9),
                self.candidate("overflow", estimated_tokens=150, semantic_relevance=0.5),
            ],
        )
        self.assertEqual([item["asset_version_id"] for item in result["selected"]], ["best"])
        reasons = {item["asset_version_id"]: item["reason"] for item in result["rejected"]}
        self.assertEqual(reasons["foreign"], "cross_project")
        self.assertEqual(reasons["revoked"], "qualification:REVOKED")
        self.assertEqual(reasons["conflict"], "blocking_conflict")
        self.assertEqual(reasons["overflow"], "token_budget")
        self.assertIn("semantic_relevance", result["selected"][0]["score_components"])
        self.assertEqual(result["selected"][0]["source_policy_version"], "policy-v1")

    def test_selection_flows_into_context_without_bypassing_project_or_profile(self) -> None:
        selection = select_knowledge_pack(
            project_id="project-a", stage="draft", query_intent="causal rule",
            token_budget=200, candidates=[self.candidate("pack-v1")],
        )
        candidates = (
            ContextCandidate(
                asset_version_id="plan-v1", asset_type="chapter_plan", project_id="project-a",
                estimated_tokens=50, relevance_score=1.0, content_digest="sha256:plan",
            ),
            *selection_to_context_candidates(selection),
        )
        bundle = build_authority_context_bundle(
            project_id="project-a", stage="draft", created_by_operation_id="operation-v1",
            context_profile_version="draft-v2", candidates=candidates, token_budget=300,
            version_refs={"chapter_plan_version": "plan-v1"},
        )
        self.assertEqual(bundle["knowledge_pack_versions"], ["pack-v1"])
        self.assertEqual(bundle["source_policy_versions"], ["policy-v1"])
        self.assertLessEqual(bundle["estimated_tokens"], bundle["token_budget"])

    def test_redundant_same_function_is_rejected(self) -> None:
        result = select_knowledge_pack(
            project_id="project-a", stage="review", query_intent="continuity",
            token_budget=300,
            candidates=[
                self.candidate("a", narrative_function_label="continuity"),
                self.candidate("b", narrative_function_label="continuity", redundancy=0.8),
            ],
        )
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["rejected"][0]["reason"], "redundant_narrative_function")


if __name__ == "__main__":
    unittest.main()
