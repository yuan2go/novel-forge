from __future__ import annotations

import unittest

from novel_forge.modules.context_builder.domain import (
    CONTEXT_PROFILES,
    ContextCandidate,
    build_authority_context_bundle,
    resolve_context_profile,
    select_context_candidates,
)


class ContextAuthorityDomainTests(unittest.TestCase):
    def test_dynamic_required_assets_are_preserved_before_optional_context(self) -> None:
        required = self.candidate(
            "style-v1",
            "style_policy",
            estimated_tokens=40,
            relevance_score=0.1,
        )
        optional = self.candidate(
            "world-v1",
            "world_bible",
            estimated_tokens=90,
            relevance_score=1.0,
        )
        plan = self.candidate(
            "plan-v1",
            "chapter_plan",
            estimated_tokens=40,
            relevance_score=1.0,
        )

        bundle = build_authority_context_bundle(
            project_id="project-a",
            stage="draft",
            created_by_operation_id="operation-a",
            context_profile_version="draft-v1",
            candidates=(optional, required, plan),
            token_budget=80,
            required_asset_types=("chapter_plan", "style_policy"),
        )

        self.assertEqual(
            set(bundle["selected_asset_version_ids"]),
            {"plan-v1", "style-v1"},
        )
        self.assertIn(
            {"asset_version_id": "world-v1", "reason": "token_budget"},
            bundle["rejected_asset_versions"],
        )

    def candidate(self, asset_version_id: str, asset_type: str, **changes):
        values = {
            "asset_version_id": asset_version_id,
            "asset_type": asset_type,
            "project_id": "project-a",
            "estimated_tokens": 100,
            "relevance_score": 0.8,
            "content_digest": f"sha256:{asset_version_id}",
            "policy_version": "source-policy-v1",
            "safe_summary": f"Safe facts for {asset_version_id}",
        }
        values.update(changes)
        return ContextCandidate(**values)

    def test_all_production_stages_have_explicit_profiles(self) -> None:
        self.assertEqual(
            set(CONTEXT_PROFILES),
            {
                "creative", "worldbuilding", "character", "outline", "chapter_plan",
                "draft", "review", "revision", "canon_extraction", "quality",
                "longform_recap", "ending",
            },
        )
        self.assertEqual(resolve_context_profile("prose").name, "draft")

    def test_selection_fails_closed_for_cross_project_and_source_governance(self) -> None:
        selection = select_context_candidates(
            project_id="project-a",
            profile=resolve_context_profile("draft"),
            token_budget=600,
            candidates=[
                self.candidate("plan-v1", "chapter_plan"),
                self.candidate("other-project", "material_card", project_id="project-b"),
                self.candidate("revoked", "knowledge_card", qualification="REVOKED"),
                self.candidate("stale", "knowledge_card", qualification="STALE"),
                self.candidate("quarantine", "knowledge_card", qualification="QUARANTINED"),
                self.candidate("review-only", "knowledge_card", source_use_mode="review_only"),
                self.candidate("structure-only", "knowledge_card", source_use_mode="structure_only"),
                self.candidate("raw", "source_document", raw_source=True),
                self.candidate(
                    "observation", "source_deconstruction_observation"
                ),
            ],
        )
        self.assertEqual(
            [item.asset_version_id for item in selection.selected],
            ["plan-v1", "structure-only"],
        )
        reasons = {item["asset_version_id"]: item["reason"] for item in selection.rejected}
        self.assertEqual(reasons["other-project"], "cross_project")
        self.assertEqual(reasons["revoked"], "qualification:REVOKED")
        self.assertEqual(reasons["stale"], "qualification:STALE")
        self.assertEqual(reasons["quarantine"], "qualification:QUARANTINED")
        self.assertEqual(reasons["review-only"], "source_mode:review_only")
        self.assertEqual(reasons["raw"], "raw_source_forbidden")
        self.assertEqual(reasons["observation"], "raw_source_forbidden")

    def test_budget_is_deterministic_and_never_exceeded(self) -> None:
        selection = select_context_candidates(
            project_id="project-a",
            profile=resolve_context_profile("draft"),
            token_budget=200,
            candidates=[
                self.candidate("plan-v1", "chapter_plan", estimated_tokens=100, relevance_score=0.5),
                self.candidate("best", "knowledge_card", estimated_tokens=100, relevance_score=0.9),
                self.candidate("overflow", "material_card", estimated_tokens=100, relevance_score=0.1),
            ],
        )
        self.assertEqual(selection.estimated_tokens, 200)
        self.assertEqual([item.asset_version_id for item in selection.selected], ["plan-v1", "best"])
        self.assertIn(
            {"asset_version_id": "overflow", "reason": "token_budget"},
            selection.rejected,
        )

    def test_bundle_freezes_versions_evidence_digest_and_invalidation(self) -> None:
        bundle = build_authority_context_bundle(
            project_id="project-a",
            stage="draft",
            created_by_operation_id="operation-1",
            context_profile_version="draft-profile-v2",
            token_budget=600,
            candidates=[
                self.candidate("plan-v1", "chapter_plan", invalidation_keys=("plan:1",)),
                self.candidate("pack-v3", "knowledge_pack", invalidation_keys=("source:9",)),
            ],
            version_refs={
                "chapter_plan_version": "plan-v1",
                "outline_version": "outline-v4",
                "character_state_versions": ["char-state-v7"],
            },
        )
        self.assertEqual(bundle["project_id"], "project-a")
        self.assertEqual(bundle["chapter_plan_version"], "plan-v1")
        self.assertEqual(bundle["outline_version"], "outline-v4")
        self.assertEqual(bundle["knowledge_pack_versions"], ["pack-v3"])
        self.assertEqual(bundle["selected_asset_versions"], ["plan-v1", "pack-v3"])
        self.assertEqual(bundle["invalidation_keys"], ["plan:1", "source:9"])
        self.assertTrue(bundle["source_isolation_result"]["passed"])
        self.assertTrue(bundle["actual_context_digest"].startswith("sha256:"))
        self.assertEqual(bundle["created_by_operation_id"], "operation-1")
        self.assertIn("Safe facts for plan-v1", bundle["stage_context_view"]["rendered_safe_context"])
        self.assertTrue(bundle["context_segments"])
        self.assertTrue(
            all(not item["source_expression_included"] for item in bundle["context_segments"])
        )

    def test_structure_only_becomes_an_abstract_segment_and_changes_digest(self) -> None:
        base = self.candidate("plan-v1", "chapter_plan")
        first = build_authority_context_bundle(
            project_id="project-a", stage="draft", created_by_operation_id="op-1",
            context_profile_version="draft-v3", token_budget=600,
            candidates=[base, self.candidate("knowledge-v1", "knowledge_card", source_use_mode="structure_only", safe_summary="Escalate by narrowing choices")],
        )
        second = build_authority_context_bundle(
            project_id="project-a", stage="draft", created_by_operation_id="op-1",
            context_profile_version="draft-v3", token_budget=600,
            candidates=[base, self.candidate("knowledge-v1", "knowledge_card", source_use_mode="structure_only", safe_summary="Escalate by increasing public cost")],
        )
        segment = first["context_segments"][1]
        self.assertEqual(segment["allowed_use"], "structure_only")
        self.assertEqual(segment["compression_method"], "structural_abstraction")
        self.assertFalse(segment["source_expression_included"])
        self.assertNotEqual(first["actual_context_digest"], second["actual_context_digest"])

    def test_required_asset_and_profile_budget_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "required context asset types missing"):
            select_context_candidates(
                project_id="project-a",
                profile=resolve_context_profile("draft"),
                token_budget=100,
                candidates=[self.candidate("knowledge", "knowledge_card")],
            )
        with self.assertRaisesRegex(ValueError, "exceeds context profile maximum"):
            select_context_candidates(
                project_id="project-a",
                profile=resolve_context_profile("draft"),
                token_budget=16001,
                candidates=[self.candidate("plan-v1", "chapter_plan")],
            )


if __name__ == "__main__":
    unittest.main()
