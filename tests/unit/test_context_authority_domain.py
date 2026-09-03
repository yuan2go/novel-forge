from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_draft_context_view,
)
from novel_forge.modules.context_builder.domain import (
    CONTEXT_PROFILES,
    ContextCandidate,
    build_authority_context_bundle,
    resolve_context_profile,
    select_context_candidates,
)
from novel_forge.modules.context_contracts import ContextClass


class ContextAuthorityDomainTests(unittest.TestCase):
    def test_dynamic_required_assets_are_preserved_before_optional_context(
        self,
    ) -> None:
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
            {"asset_version_id": "world-v1", "reason": "TOTAL_CONTEXT_LIMIT"},
            bundle["rejected_asset_versions"],
        )

    def test_required_retrievable_context_precedes_optional_compressible_context(
        self,
    ) -> None:
        bundle = build_authority_context_bundle(
            project_id="project-a",
            stage="draft",
            created_by_operation_id="operation-required-ordering",
            context_profile_version="draft-v1",
            token_budget=180,
            required_asset_types=("commercial_quality_report",),
            candidates=(
                self.candidate(
                    "plan-v1",
                    "chapter_plan",
                    estimated_tokens=80,
                ),
                self.candidate(
                    "quality-required-v1",
                    "commercial_quality_report",
                    estimated_tokens=100,
                    relevance_score=0.1,
                    context_class=ContextClass.RETRIEVABLE.value,
                ),
                self.candidate(
                    "optional-compressible-v1",
                    "knowledge_card",
                    estimated_tokens=100,
                    relevance_score=1.0,
                    context_class=ContextClass.COMPRESSIBLE.value,
                    compression_method="none",
                ),
            ),
        )

        self.assertEqual(
            bundle["selected_asset_version_ids"],
            ["plan-v1", "quality-required-v1"],
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
            "provenance": {
                "authority_asset_version_id": asset_version_id,
                "source_content_hash": f"sha256:{asset_version_id}",
            },
        }
        values.update(changes)
        return ContextCandidate(**values)

    def test_all_production_stages_have_explicit_profiles(self) -> None:
        self.assertEqual(
            set(CONTEXT_PROFILES),
            {
                "creative",
                "worldbuilding",
                "character",
                "outline",
                "chapter_plan",
                "draft",
                "review",
                "revision",
                "canon_extraction",
                "quality",
                "longform_recap",
                "ending",
            },
        )
        self.assertEqual(resolve_context_profile("prose").name, "draft")

    def test_selection_fails_closed_for_cross_project_and_source_governance(
        self,
    ) -> None:
        selection = select_context_candidates(
            project_id="project-a",
            profile=resolve_context_profile("draft"),
            token_budget=600,
            candidates=[
                self.candidate("plan-v1", "chapter_plan"),
                self.candidate(
                    "other-project", "material_card", project_id="project-b"
                ),
                self.candidate("revoked", "knowledge_card", qualification="REVOKED"),
                self.candidate("stale", "knowledge_card", qualification="STALE"),
                self.candidate(
                    "quarantine", "knowledge_card", qualification="QUARANTINED"
                ),
                self.candidate(
                    "review-only", "knowledge_card", source_use_mode="review_only"
                ),
                self.candidate(
                    "structure-only", "knowledge_card", source_use_mode="structure_only"
                ),
                self.candidate("raw", "source_document", raw_source=True),
                self.candidate("observation", "source_deconstruction_observation"),
            ],
        )
        self.assertEqual(
            [item.asset_version_id for item in selection.selected],
            ["plan-v1", "structure-only"],
        )
        reasons = {
            item["asset_version_id"]: item["reason"] for item in selection.rejected
        }
        self.assertEqual(reasons["other-project"], "WRONG_PROJECT")
        self.assertEqual(reasons["revoked"], "QUALIFICATION_REVOKED")
        self.assertEqual(reasons["stale"], "QUALIFICATION_STALE")
        self.assertEqual(reasons["quarantine"], "QUALIFICATION_QUARANTINED")
        self.assertEqual(reasons["review-only"], "SOURCE_MODE_review_only")
        self.assertEqual(reasons["raw"], "RAW_SOURCE_FORBIDDEN")
        self.assertEqual(reasons["observation"], "RAW_SOURCE_FORBIDDEN")

    def test_budget_is_deterministic_and_never_exceeded(self) -> None:
        selection = select_context_candidates(
            project_id="project-a",
            profile=resolve_context_profile("draft"),
            token_budget=200,
            candidates=[
                self.candidate(
                    "plan-v1", "chapter_plan", estimated_tokens=100, relevance_score=0.5
                ),
                self.candidate(
                    "best", "knowledge_card", estimated_tokens=100, relevance_score=0.9
                ),
                self.candidate(
                    "overflow",
                    "material_card",
                    estimated_tokens=100,
                    relevance_score=0.1,
                ),
            ],
        )
        self.assertEqual(selection.estimated_tokens, 200)
        self.assertEqual(
            [item.asset_version_id for item in selection.selected], ["plan-v1", "best"]
        )
        self.assertIn(
            {"asset_version_id": "overflow", "reason": "TOTAL_CONTEXT_LIMIT"},
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
                self.candidate(
                    "plan-v1", "chapter_plan", invalidation_keys=("plan:1",)
                ),
                self.candidate(
                    "pack-v3", "knowledge_pack", invalidation_keys=("source:9",)
                ),
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
        self.assertIn(
            "Safe facts for plan-v1",
            bundle["stage_context_view"]["rendered_safe_context"],
        )
        self.assertTrue(bundle["context_segments"])
        self.assertTrue(
            all(
                not item["source_expression_included"]
                for item in bundle["context_segments"]
            )
        )

    def test_structure_only_becomes_an_abstract_segment_and_changes_digest(
        self,
    ) -> None:
        base = self.candidate("plan-v1", "chapter_plan")
        first = build_authority_context_bundle(
            project_id="project-a",
            stage="draft",
            created_by_operation_id="op-1",
            context_profile_version="draft-v3",
            token_budget=600,
            candidates=[
                base,
                self.candidate(
                    "knowledge-v1",
                    "knowledge_card",
                    source_use_mode="structure_only",
                    safe_summary="Escalate by narrowing choices",
                ),
            ],
        )
        second = build_authority_context_bundle(
            project_id="project-a",
            stage="draft",
            created_by_operation_id="op-1",
            context_profile_version="draft-v3",
            token_budget=600,
            candidates=[
                base,
                self.candidate(
                    "knowledge-v1",
                    "knowledge_card",
                    source_use_mode="structure_only",
                    safe_summary="Escalate by increasing public cost",
                ),
            ],
        )
        segment = first["context_segments"][1]
        self.assertEqual(segment["allowed_use"], "structure_only")
        self.assertEqual(segment["compression_method"], "structural_abstraction")
        self.assertFalse(segment["source_expression_included"])
        self.assertNotEqual(
            first["actual_context_digest"], second["actual_context_digest"]
        )

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

    def test_narrative_context_manifest_is_replayable_and_records_knowledge_use(
        self,
    ) -> None:
        plan = self.candidate(
            "plan-v12",
            "chapter_plan",
            estimated_tokens=80,
            relevance_score=1.0,
            narrative_function="current_chapter_plan",
        )
        knowledge = self.candidate(
            "knowledge-pack-v4",
            "knowledge_pack",
            estimated_tokens=60,
            relevance_score=0.8,
            narrative_function="conflict_escalation_constraints",
        )
        state = self.candidate(
            "story-state-v11",
            "story_state_snapshot",
            estimated_tokens=70,
            relevance_score=0.9,
            narrative_function="accepted_narrative_state",
            structured_facts=(
                {
                    "state_kind": "character_knowledge",
                    "entity_key": "character_id=hero|fact_id=fact:seal",
                    "entity_version": 2,
                    "effective_from_chapter": 8,
                    "effective_to_chapter": 0,
                    "state": {"status": "KNOWN"},
                },
                {
                    "state_kind": "narrative_obligation",
                    "entity_key": "obligation_id=obligation:seal",
                    "entity_version": 1,
                    "effective_from_chapter": 8,
                    "effective_to_chapter": 0,
                    "state": {"status": "OPEN", "obligation_type": "MYSTERY"},
                },
            ),
        )
        arguments = {
            "project_id": "project-a",
            "book_id": "book-a",
            "stage": "draft",
            "created_by_operation_id": "operation-context-12",
            "context_profile_version": "draft-v3",
            "token_budget": 500,
            "narrative_position": {
                "chapter": 12,
                "volume_id": "volume-1",
                "arc_id": "arc-2",
                "sequence_id": "sequence-4",
                "sequence_ordinal": 3,
            },
            "target_capability_id": "prose.chapter.draft",
            "capability_pack_snapshot_ref": "pack-snapshot-8",
            "authority_state_boundary": {
                "accepted_through_chapter": 11,
                "story_state_snapshot_version": "story-state-v11",
                "canon_snapshot_version": "canon-v11",
            },
        }

        first = build_authority_context_bundle(
            **arguments,
            candidates=(knowledge, plan, state),
            accessible_knowledge_fact_ids=("fact:seal",),
        )
        replayed = build_authority_context_bundle(
            **arguments,
            candidates=(state, plan, knowledge),
            accessible_knowledge_fact_ids=("fact:seal",),
        )

        self.assertEqual(
            first["context_contract_version"], "authority-context-bundle-v8"
        )
        self.assertEqual(
            first["actual_context_digest"], replayed["actual_context_digest"]
        )
        self.assertEqual(first["context_manifest"], replayed["context_manifest"])
        manifest = first["context_manifest"]
        self.assertEqual(manifest["contract_version"], "narrative-context-manifest-v4")
        self.assertEqual(manifest["accepted_boundary"]["accepted_through_chapter"], 11)
        self.assertIn("protected_context", manifest)
        self.assertIn("compressible_context", manifest)
        self.assertIn("retrievable_context", manifest)
        self.assertIn("ephemeral_context", manifest)
        self.assertTrue(manifest["context_fingerprint"].startswith("sha256:"))
        self.assertEqual(manifest["narrative_position"]["chapter"], 12)
        self.assertEqual(
            manifest["authority_state_boundary"]["accepted_through_chapter"],
            11,
        )
        self.assertEqual(
            manifest["knowledge_usage"][0],
            {
                "asset_version_id": "knowledge-pack-v4",
                "asset_type": "knowledge_pack",
                "narrative_function": "conflict_escalation_constraints",
                "target_capability_id": "prose.chapter.draft",
                "capability_pack_snapshot_ref": "pack-snapshot-8",
            },
        )
        self.assertTrue(manifest["replay"]["input_digest"].startswith("sha256:"))
        boundaries = manifest["narrative_boundaries"]
        self.assertEqual(
            boundaries["character_knowledge_and_belief"][0]["state"]["status"],
            "KNOWN",
        )
        self.assertEqual(
            boundaries["unresolved_obligations"][0]["state"]["status"],
            "OPEN",
        )
        provider_view = build_draft_context_view(first)
        self.assertEqual(provider_view["narrative_position"]["chapter"], 12)
        self.assertEqual(
            provider_view["authority_state_boundary"]["accepted_through_chapter"],
            11,
        )
        self.assertEqual(provider_view["narrative_boundaries"], boundaries)
        self.assertEqual(
            provider_view["context_replay_input_digest"],
            manifest["replay"]["input_digest"],
        )

    def test_six_context_correctness_checks_fail_closed_before_provider(self) -> None:
        plan = self.candidate("plan-v1", "chapter_plan")
        fact = {
            "state_kind": "character_knowledge",
            "entity_key": "character_id=hero|fact_id=fact:seal",
            "effective_from_chapter": 8,
            "source_chapter": 1,
            "state": {"status": "KNOWN", "fact_id": "fact:seal"},
        }
        state = self.candidate(
            "state-v1",
            "story_state_snapshot",
            structured_facts=(fact,),
        )
        base = {
            "project_id": "project-a",
            "book_id": "book-a",
            "stage": "draft",
            "created_by_operation_id": "operation-context",
            "context_profile_version": "draft-v3",
            "token_budget": 1000,
            "narrative_position": {"chapter": 30},
            "accessible_knowledge_fact_ids": ("fact:seal",),
        }

        passed = build_authority_context_bundle(
            **base,
            candidates=(plan, state),
            required_long_distance_fact_ids=("fact:seal",),
        )
        self.assertEqual(passed["context_correctness"]["overall_status"], "PASS")
        self.assertEqual(
            set(passed["context_correctness"]["checks"]),
            {
                "NO_FUTURE_FACT",
                "NO_HIDDEN_KNOWLEDGE_LEAK",
                "NO_STALE_VERSION",
                "NO_DUPLICATE_SEMANTIC_REPRESENTATION",
                "NO_IRRELEVANT_FULL_ASSET",
                "REQUIRED_LONG_DISTANCE_FACT_PRESENT",
            },
        )

        cases = {
            "NO_FUTURE_FACT": (
                plan,
                self.candidate(
                    "future-v1",
                    "story_state_snapshot",
                    structured_facts=({**fact, "effective_from_chapter": 31},),
                ),
            ),
            "NO_HIDDEN_KNOWLEDGE_LEAK": (plan, state),
            "STALE_REPRESENTATION": (
                plan,
                self.candidate(
                    "stale-v1",
                    "story_state_snapshot",
                    authority_freshness="HISTORICAL",
                ),
            ),
            "NO_DUPLICATE_SEMANTIC_REPRESENTATION": (
                plan,
                state,
                self.candidate("canon-v1", "canon_snapshot", structured_facts=(fact,)),
            ),
            "NO_IRRELEVANT_FULL_ASSET": (
                plan,
                self.candidate(
                    "world-v1",
                    "world_bible",
                    compression_method="full_asset",
                ),
            ),
        }
        for expected, candidates in cases.items():
            with self.subTest(expected=expected):
                arguments = dict(base)
                if expected == "NO_HIDDEN_KNOWLEDGE_LEAK":
                    arguments["accessible_knowledge_fact_ids"] = ()
                with self.assertRaisesRegex(ValueError, expected):
                    build_authority_context_bundle(
                        **arguments,
                        candidates=candidates,
                    )
        with self.assertRaisesRegex(ValueError, "REQUIRED_LONG_DISTANCE_FACT_PRESENT"):
            build_authority_context_bundle(
                **base,
                candidates=(plan, state),
                required_long_distance_fact_ids=("fact:missing",),
            )

        hidden_canon = self.candidate(
            "hidden-canon-v1",
            "canon_snapshot",
            structured_facts=(
                {
                    "state_kind": "canon_fact",
                    "entity_key": "fact_id=fact:hidden-truth",
                    "effective_from_chapter": 1,
                    "state": {
                        "fact_id": "fact:hidden-truth",
                        "visibility": "HIDDEN",
                    },
                },
            ),
        )
        with self.assertRaisesRegex(ValueError, "NO_HIDDEN_KNOWLEDGE_LEAK"):
            build_authority_context_bundle(
                **base,
                candidates=(plan, hidden_canon),
            )

    def test_four_context_classes_enforce_budget_and_lineage_invariants(self) -> None:
        protected = self.candidate(
            "plan-protected",
            "chapter_plan",
            estimated_tokens=120,
        )
        with self.assertRaisesRegex(ValueError, "PROTECTED_CONTEXT_BUDGET_EXCEEDED"):
            select_context_candidates(
                project_id="project-a",
                profile=resolve_context_profile("draft"),
                candidates=(protected,),
                token_budget=100,
            )

        with self.assertRaisesRegex(
            ValueError, "PROTECTED_CONTEXT_TOKEN_ESTIMATE_INVALID"
        ):
            select_context_candidates(
                project_id="project-a",
                profile=resolve_context_profile("draft"),
                candidates=(
                    self.candidate(
                        "plan-invalid-token-estimate",
                        "chapter_plan",
                        estimated_tokens=-1,
                    ),
                ),
                token_budget=100,
            )

        with self.assertRaisesRegex(
            ValueError, "PROTECTED_CONTEXT_COMPRESSION_FORBIDDEN"
        ):
            select_context_candidates(
                project_id="project-a",
                profile=resolve_context_profile("draft"),
                candidates=(
                    self.candidate(
                        "plan-compressed",
                        "chapter_plan",
                        compression_method="deterministic_bounded_extract",
                        compression_trace=({"method": "truncate"},),
                    ),
                ),
                token_budget=500,
            )

        compressed = self.candidate(
            "recap-compressed",
            "longform_recap_report",
            context_class=ContextClass.COMPRESSIBLE,
            compression_method="deterministic_bounded_extract",
            provenance={"projection": "accepted-only"},
            compression_trace=(
                {
                    "source_asset_version_id": "recap-source-v1",
                    "source_content_hash": "sha256:" + "1" * 64,
                    "method": "deterministic_bounded_extract",
                },
            ),
        )
        ephemeral = self.candidate(
            "attempt-note-v1",
            "operator_checklist",
            context_class=ContextClass.EPHEMERAL,
            memory_layer="",
            retrieval_reasons=(),
            retrieval_scores={},
        )
        bundle = build_authority_context_bundle(
            project_id="project-a",
            stage="draft",
            created_by_operation_id="context-operation-v1",
            context_profile_version="draft-v4",
            candidates=(protected, compressed, ephemeral),
            token_budget=500,
        )
        manifest = bundle["context_manifest"]
        self.assertEqual(
            [item["asset_version_id"] for item in manifest["protected_context"]],
            ["plan-protected"],
        )
        self.assertEqual(
            [item["asset_version_id"] for item in manifest["compressible_context"]],
            ["recap-compressed"],
        )
        self.assertEqual(
            [item["asset_version_id"] for item in manifest["ephemeral_context"]],
            ["attempt-note-v1"],
        )
        self.assertEqual(
            manifest["ephemeral_context"][0]["attempt_evidence_policy"],
            "FROZEN_IF_SENT_NOT_SEARCH_INDEXED",
        )
        self.assertEqual(manifest["token_budget"]["protected"], 120)
        self.assertEqual(manifest["token_budget"]["compressible"], 100)
        self.assertEqual(manifest["token_budget"]["ephemeral"], 100)

        with self.assertRaisesRegex(
            ValueError, "COMPRESSIBLE_CONTEXT_PROVENANCE_REQUIRED"
        ):
            select_context_candidates(
                project_id="project-a",
                profile=resolve_context_profile("draft"),
                candidates=(
                    protected,
                    self.candidate(
                        "recap-untraced",
                        "longform_recap_report",
                        context_class=ContextClass.COMPRESSIBLE,
                        compression_method="deterministic_bounded_extract",
                    ),
                ),
                token_budget=500,
            )

        with self.assertRaisesRegex(ValueError, "ephemeral context cannot"):
            self.candidate(
                "ephemeral-indexed",
                "operator_checklist",
                context_class=ContextClass.EPHEMERAL,
                memory_layer="L7",
            )


if __name__ == "__main__":
    unittest.main()
