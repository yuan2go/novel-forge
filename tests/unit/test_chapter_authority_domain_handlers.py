from __future__ import annotations

from copy import deepcopy
import unittest

from novel_forge.modules.chapter_authority.domain_handlers import (
    build_canon_patch,
    build_chapter_plan,
    build_context_bundle,
    build_export_package,
    build_final_release_gate,
    build_quality_report,
    normalize_draft_result,
    normalize_review_result,
    normalize_rereview_result,
    normalize_revision_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.execution_artifacts import (
    build_chapter_execution_intent,
    qualify_chapter_memo,
)


class ChapterAuthorityDomainHandlerTests(unittest.TestCase):
    def test_context_projects_locked_mission_without_reinterpreting_plan(self) -> None:
        plan = {
            "chapter": 1,
            "title": "One causal event",
            "premise": "A public clue makes an alliance costly.",
            "objective": "Bind the clue and relationship cost.",
            "chapter_intent": "Make one event disclose the clue and alter trust.",
            "scene_sequence": ["the witness discloses the clue in public"],
            "required_arc_contributions": [
                {"arc_plan_version_id": "arc-v1", "contribution_kind": "PRIMARY"}
            ],
            "required_state_transitions": [
                {
                    "state_kind": "relationship_state",
                    "entity_key": "witness-trust",
                    "from_state": "private",
                    "to_state": "publicly conditional",
                }
            ],
            "disclosures": [
                {"fact_id": "fact:cost", "audience": "READER", "mode": "HINT"}
            ],
            "knowledge_boundaries": [
                {
                    "layer": "READER_KNOWLEDGE",
                    "fact_id": "fact:cost",
                    "status": "HINTED",
                }
            ],
            "expected_exit_state": {"summary": "trust is publicly conditional"},
            "narrative_realization_slice": {
                "realization_id": "realization:v1",
                "contract_digest": "sha256:" + "b" * 64,
                "chapter_group_plan_version_id": "chapter-group:v1",
                "chapter_number": 1,
                "events": [{"event_id": "event:v1"}],
            },
            "scene_plan": [
                {
                    "scene_id": "chapter:1:scene:1",
                    "goal": "obtain the clue",
                    "conflict": "disclosure exposes the witness",
                    "participants": ["protagonist", "witness"],
                    "arc_progress": ["arc-v1"],
                    "information_gain": ["fact:cost"],
                    "state_transitions": ["witness-trust"],
                    "entry_state": "the clue is private",
                    "exit_state": "the clue is public",
                    "reader_effect": "relief becomes dread",
                    "beats": ["disclose at a cost"],
                }
            ],
        }
        plan_hash = "sha256:" + "a" * 64
        intent = build_chapter_execution_intent(
            project_id="project-a",
            operation_id="operation:intent",
            chapter_plan_asset_version_id="plan-v1",
            chapter_plan_content_hash=plan_hash,
            chapter_plan=plan,
            accepted_inputs=(),
        )
        memo = qualify_chapter_memo(
            intent=intent,
            intent_asset_version_id="intent-v1",
            result={
                "execution_strategy": "realize the shared event",
                "tension_strategy": "delay the public implication",
                "scene_directives": [{"scene_id": "chapter:1:scene:1"}],
                "retrieval_queries": ["accepted witness relationship"],
                "obligation_actions": [],
                "arc_actions": [{"arc_plan_version_id": "arc-v1", "action": "ADVANCE"}],
            },
            execution_evidence={"qualified": True},
        )
        drifted_plan = deepcopy(plan)
        drifted_plan["required_state_transitions"].append(
            {
                "state_kind": "world_state",
                "entity_key": "unapproved-world-change",
                "from_state": "closed",
                "to_state": "open",
            }
        )
        drifted_plan["disclosures"].append(
            {"fact_id": "fact:unapproved", "audience": "READER", "mode": "CONFIRM"}
        )

        bundle = build_context_bundle(
            plan=drifted_plan,
            plan_asset_version_id="plan-v1",
            plan_content_hash=plan_hash,
            project_id="project-a",
            created_by_operation_id="operation:context",
            execution_intent=intent,
            execution_intent_asset_version_id="intent-v1",
            chapter_memo=memo,
            chapter_memo_asset_version_id="memo-v1",
        )

        expectations = bundle["chapter_execution_expectations"]
        self.assertEqual(
            expectations["required_state_transitions"],
            intent["chapter_mission"]["required_outcomes"]["state_transitions"],
        )
        self.assertEqual(
            expectations["disclosures"],
            intent["chapter_mission"]["knowledge_and_disclosure_boundaries"][
                "disclosures"
            ],
        )
        self.assertNotIn(
            "fact:unapproved",
            {item["fact_id"] for item in expectations["disclosures"]},
        )

        tampered = deepcopy(intent)
        tampered["chapter_mission"]["why_this_chapter_exists"] = "rewrite the Plan"
        with self.assertRaisesRegex(KernelError, "Chapter Mission content differs"):
            build_context_bundle(
                plan=plan,
                plan_asset_version_id="plan-v1",
                plan_content_hash=plan_hash,
                execution_intent=tampered,
                execution_intent_asset_version_id="intent-v1",
            )

    def test_context_does_not_union_knowledge_across_scene_povs(self) -> None:
        plan = {
            "chapter": 2,
            "title": "Split witness",
            "premise": "Two witnesses know different parts of the event.",
            "objective": "Preserve the split knowledge boundary.",
            "scene_sequence": ["first witness", "second witness"],
            "character_participation": [
                {"character_id": "a", "known_fact_ids": ["fact:secret"]},
                {"character_id": "b", "known_fact_ids": []},
            ],
            "scene_plan": [
                {
                    "pov_character_id": "a",
                    "focalization": "INTERNAL",
                    "accessible_knowledge": ["fact:secret"],
                },
                {
                    "pov_character_id": "b",
                    "focalization": "INTERNAL",
                    "accessible_knowledge": [],
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "NO_HIDDEN_KNOWLEDGE_LEAK"):
            build_context_bundle(
                plan=plan,
                plan_asset_version_id="plan-v2",
                plan_content_hash="sha256:plan-v2",
                project_id="project-a",
                created_by_operation_id="operation-context-v2",
                governed_candidates=[
                    {
                        "asset_version_id": "state-v1",
                        "asset_type": "story_state_snapshot",
                        "project_id": "project-a",
                        "estimated_tokens": 20,
                        "structured_facts": [
                            {
                                "state_kind": "character_knowledge",
                                "entity_key": "character_id=a|fact_id=fact:secret",
                                "state": {
                                    "fact_id": "fact:secret",
                                    "status": "KNOWN",
                                },
                            }
                        ],
                    }
                ],
                book_id="book-a",
            )

    def test_storage_free_domain_chain_preserves_gates_and_lineage(self) -> None:
        plan = build_chapter_plan(
            chapter=1,
            title="The Cost of a Promise",
            premise="A public promise must acquire an irreversible cost.",
            trace_id="trace-1",
        )
        context = build_context_bundle(
            plan=plan,
            plan_asset_version_id="plan-version-1",
            plan_content_hash="sha256:plan",
        )
        draft = normalize_draft_result(
            plan=plan,
            context_asset_version_id="context-version-1",
            result={
                "text": "The promise is made in public, but the price remains hidden.",
            },
            provider_evidence={"provider_id": "provider-1", "real_model_call": True},
        )
        review = normalize_review_result(
            draft=draft,
            draft_asset_version_id="draft-version-1",
            result={
                "decision": "NEEDS_REVISION",
                "score": 70,
                "issues": [
                    {
                        "code": "COST_NOT_CONCRETE",
                        "severity": "blocking",
                        "message": "The cost is not visible.",
                    }
                ],
            },
            provider_evidence={"provider_id": "provider-1", "real_model_call": True},
        )
        revision = normalize_revision_result(
            draft=draft,
            review=review,
            draft_asset_version_id="draft-version-1",
            review_asset_version_id="review-version-1",
            result={
                "text": "The protagonist surrenders the only safe route home before every witness.",
                "resolved_issue_codes": ["COST_NOT_CONCRETE"],
            },
            provider_evidence={"provider_id": "provider-1", "real_model_call": True},
        )
        rereview = normalize_rereview_result(
            draft_asset_version_id="draft-version-1",
            review=review,
            review_asset_version_id="review-version-1",
            revision=revision,
            revision_asset_version_id="revision-version-1",
            context_bundle_version_id="context-version-1",
            result={
                "decision": "PASSED",
                "score": 88,
                "issues": [],
                "resolved_issue_codes": ["COST_NOT_CONCRETE"],
            },
            provider_evidence={"provider_id": "fixture", "real_model_call": False},
            project_id="project-a",
        )
        canon = build_canon_patch(
            revision=revision,
            revision_asset_version_id="revision-version-1",
        )
        quality = build_quality_report(
            revision=revision,
            revision_asset_version_id="revision-version-1",
            canon=canon,
            canon_asset_version_id="canon-version-1",
            review=rereview,
            review_asset_version_id="rereview-version-1",
            context_bundle=context,
        )
        exported = build_export_package(
            revision=revision,
            revision_asset_version_id="revision-version-1",
            quality={"gate": "PASSED"},
            quality_asset_version_id="publish-gate-version-1",
        )

        self.assertEqual(context["selected_asset_version_ids"], ["plan-version-1"])
        self.assertEqual(review["blocking_issue_count"], 1)
        self.assertEqual(canon["gate"], "PASSED")
        self.assertEqual(quality["gate"], "FAILED")
        self.assertIn("originality", quality["blocking_dimensions"])
        self.assertTrue(quality["required_actions"])
        self.assertTrue(
            all(
                item["permitted_change_scope"] == "CHAPTER"
                for item in quality["required_actions"]
            )
        )
        self.assertEqual(
            quality["decision_chain"]["reevaluation_gate"],
            "chapter.quality.aggregate",
        )
        self.assertEqual(exported["release_status"], "READY_FOR_BLOB_VERIFICATION")

    def test_draft_freezes_context_and_retrieval_fingerprints(self) -> None:
        draft = normalize_draft_result(
            plan={"chapter": 1, "title": "Exact retrieval"},
            context_asset_version_id="context-version-1",
            context_content_hash="sha256:context",
            context_content={
                "context_manifest": {
                    "context_fingerprint": "sha256:context-fingerprint"
                },
                "chapter_execution": {
                    "retrieval_result_asset_version_id": "retrieval-version-1",
                    "retrieval_result_fingerprint": "sha256:retrieval-fingerprint",
                },
            },
            result={"text": "A bounded candidate draft."},
            provider_evidence={"provider_id": "provider-1", "real_model_call": True},
        )

        self.assertEqual(draft["context_bundle_content_hash"], "sha256:context")
        self.assertEqual(draft["context_fingerprint"], "sha256:context-fingerprint")
        self.assertEqual(
            draft["retrieval_result_asset_version_id"], "retrieval-version-1"
        )
        self.assertEqual(
            draft["retrieval_result_fingerprint"], "sha256:retrieval-fingerprint"
        )

    def test_draft_rejects_incomplete_context_lineage(self) -> None:
        with self.assertRaisesRegex(
            KernelError, "CHAPTER_DRAFT_CONTEXT_LINEAGE_INVALID"
        ):
            normalize_draft_result(
                plan={"chapter": 1, "title": "Missing retrieval"},
                context_asset_version_id="context-version-1",
                context_content_hash="sha256:context",
                context_content={"context_manifest": {}},
                result={"text": "A candidate draft."},
                provider_evidence={"provider_id": "provider-1"},
            )

    def test_quality_and_export_fail_closed(self) -> None:
        with self.assertRaisesRegex(KernelError, "QUALITY_REREVIEW_REQUIRED"):
            build_quality_report(
                revision={"chapter": 1, "text": "Nothing changes."},
                revision_asset_version_id="revision-version-1",
                canon={"gate": "PASSED", "conflicts": []},
                canon_asset_version_id="canon-version-1",
            )

    def test_compact_state_entity_key_rehydrates_transition_baseline(self) -> None:
        canon = build_canon_patch(
            revision={"chapter": 2, "text": "The commitment has a consequence."},
            revision_asset_version_id="revision-version-2",
            context_bundle_version_id="context-version-2",
            extraction={
                "project_id": "project-a",
                "chapter": 2,
                "canon_assertion_candidates": [],
                "character_arc_changes": [
                    {
                        "character_id": "protagonist",
                        "arc_id": "character-arc:accountability",
                        "from_state": "COMMITTED",
                        "state": "CONSEQUENT",
                    }
                ],
                "disclosure_events": [],
                "reader_knowledge_changes": [],
            },
            project_id="project-a",
            context_bundle={
                "context_segments": [
                    {
                        "asset_type": "story_state_snapshot",
                        "asset_version_id": "story-state-v1",
                        "structured_facts": [
                            {
                                "state_kind": "character_arc",
                                "entity_key": (
                                    "character_id=protagonist|"
                                    "arc_id=character-arc:accountability"
                                ),
                                "source_event_id": "event:arc:v1",
                                "state": {"state": "COMMITTED"},
                            }
                        ],
                    },
                    {
                        "asset_type": "canon_snapshot",
                        "asset_version_id": "canon-v1",
                        "structured_facts": [
                            {
                                "source_event_id": "event:canon:v1",
                                "state": {
                                    "subject": "chapter:1",
                                    "predicate": "accepted",
                                    "object": "true",
                                },
                            }
                        ],
                    },
                ],
                "chapter_execution_expectations": {
                    "required_state_transitions": [
                        {
                            "state_kind": "character_arc",
                            "entity_key": "protagonist:accountability",
                            "from_state": "COMMITTED",
                            "to_state": "CONSEQUENT",
                        }
                    ],
                    "disclosures": [],
                },
            },
        )

        self.assertEqual(canon["gate"], "PASSED")

    def test_context_bundle_accounts_for_optional_inputs_rejected_by_budget(
        self,
    ) -> None:
        plan = build_chapter_plan(
            chapter=1,
            title="A bounded context",
            premise="Required plans survive while oversized optional context is traced.",
            trace_id="trace-context-budget",
        )
        bundle = build_context_bundle(
            plan=plan,
            plan_asset_version_id="plan-version-budget",
            plan_content_hash="sha256:plan-budget",
            project_id="project-a",
            governed_candidates=[
                {
                    "asset_version_id": "world-version-large",
                    "asset_type": "world_bible",
                    "physical_asset_type": "world_bible",
                    "project_id": "project-a",
                    "estimated_tokens": 16_000,
                    "safe_summary": "Optional governed world context.",
                    "allowed_use": "generation",
                }
            ],
            token_budget=16_000,
        )

        selected = set(bundle["selected_asset_version_ids"])
        rejected = {
            item["asset_version_id"] for item in bundle["rejected_asset_versions"]
        }
        self.assertIn("plan-version-budget", selected)
        self.assertEqual(rejected, {"world-version-large"})
        self.assertTrue(selected.isdisjoint(rejected))

    def test_large_typed_plan_uses_rendered_context_size_and_keeps_continuing_state(
        self,
    ) -> None:
        plan = {
            **build_chapter_plan(
                chapter=2,
                title="A continuing chapter",
                premise="The accepted state must survive a large typed planning payload.",
                trace_id="trace-continuing-context-budget",
            ),
            "typed_planning_evidence": "x" * 50_000,
        }
        continuing = [
            {
                "asset_version_id": asset_version_id,
                "asset_type": asset_type,
                "physical_asset_type": asset_type,
                "project_id": "project-a",
                "estimated_tokens": estimated_tokens,
                "safe_summary": f"Accepted {asset_type}.",
                "structured_facts": [{"kind": asset_type, "value": "current"}],
                "allowed_use": "generation",
            }
            for asset_version_id, asset_type, estimated_tokens in (
                ("story-state-v1", "story_state_snapshot", 2_556),
                ("canon-v1", "canon_snapshot", 5_597),
                ("quality-v1", "quality_rubric", 51),
                ("platform-v1", "platform_profile", 281),
            )
        ]

        bundle = build_context_bundle(
            plan=plan,
            plan_asset_version_id="typed-plan-v2",
            plan_content_hash="sha256:typed-plan-v2",
            project_id="project-a",
            governed_candidates=continuing,
            required_asset_types=(
                "chapter_plan",
                "story_state_snapshot",
                "canon_snapshot",
                "quality_rubric",
                "platform_profile",
            ),
            token_budget=16_000,
        )

        self.assertTrue(
            {
                "typed-plan-v2",
                "story-state-v1",
                "canon-v1",
                "quality-v1",
                "platform-v1",
            }.issubset(set(bundle["selected_asset_version_ids"]))
        )
        plan_segment = next(
            item
            for item in bundle["context_segments"]
            if item["asset_type"] == "chapter_plan"
        )
        self.assertLess(plan_segment["token_count"], 1_000)

    def test_post_blob_final_release_fails_closed_and_binds_receipt(self) -> None:
        common = {
            "project_id": "project-a",
            "export_package": {
                "chapter": 1,
                "release_status": "READY_FOR_BLOB_VERIFICATION",
            },
            "export_asset_version_id": "export-v1",
            "publish_gate": {
                "gate": "PASSED",
                "rollback_metadata": {
                    "rollback_to_asset_version_id": "draft-v1",
                    "release_not_externally_published": True,
                },
            },
            "publish_gate_asset_version_id": "publish-v1",
            "quality": {"gate": "PASSED_WITH_UNCALIBRATED"},
            "quality_asset_version_id": "quality-v1",
            "review": {
                "report_type": "ReReviewReport",
                "decision": "PASSED",
                "blocking_issue_count": 0,
            },
            "review_asset_version_id": "review-v2",
            "canon": {"gate": "PASSED", "conflicts": []},
            "canon_asset_version_id": "canon-v1",
            "context_bundle_version_id": "context-v1",
        }
        verified_blob = {
            "blob_id": "blob-1",
            "role": "content",
            "provider": "fixture-store",
            "receipt_provider": "fixture-store",
            "object_key": "chapter.txt",
            "expected_hash": "sha256:text",
            "actual_hash": "sha256:text",
            "content_hash": "sha256:text",
            "expected_size": 4,
            "actual_size": 4,
            "media_type": "text/plain",
            "status": "AVAILABLE",
            "external_effect_id": "effect-1",
            "capability": "object_store.put",
            "effect_status": "SUCCEEDED",
            "dispatch_id": "dispatch-1",
            "dispatch_status": "SUCCEEDED",
            "receipt_id": "receipt-1",
            "receipt_status": "VERIFIED",
        }
        report = build_final_release_gate(
            **common,
            export_blobs=(verified_blob,),
        )
        self.assertEqual(report["gate"], "PASSED")
        self.assertFalse(report["external_publish_permitted"])
        self.assertEqual(report["blob_receipt"]["blob_id"], "blob-1")

        with self.assertRaisesRegex(KernelError, "FINAL_RELEASE_GATE_BLOCKED"):
            build_final_release_gate(
                **common,
                export_blobs=({**verified_blob, "actual_hash": "sha256:tampered"},),
            )

    def test_authority_context_consumes_governed_mkaos_and_source_decisions(
        self,
    ) -> None:
        plan = build_chapter_plan(
            chapter=1,
            title="Governed context",
            premise="A choice must obey source boundaries.",
            trace_id="trace-governed",
        )
        bundle = build_context_bundle(
            plan=plan,
            plan_asset_version_id="plan-v1",
            plan_content_hash="sha256:plan",
            project_id="project-a",
            created_by_operation_id="operation-context",
            governed_candidates=[
                {
                    "asset_version_id": "pack-v1",
                    "asset_type": "knowledge_pack",
                    "project_id": "project-a",
                    "estimated_tokens": 100,
                    "score": 0.9,
                    "allowed_use": "generation",
                    "source_policy_version": "policy-v1",
                },
                {
                    "asset_version_id": "review-only-v1",
                    "asset_type": "knowledge_pack",
                    "project_id": "project-a",
                    "estimated_tokens": 100,
                    "source_use_mode": "review_only",
                },
                {
                    "asset_version_id": "foreign-v1",
                    "asset_type": "knowledge_pack",
                    "project_id": "project-b",
                    "estimated_tokens": 100,
                },
            ],
        )
        self.assertEqual(bundle["knowledge_pack_versions"], ["pack-v1"])
        self.assertEqual(bundle["source_policy_versions"], ["policy-v1"])
        reasons = {
            item["asset_version_id"]: item["reason"]
            for item in bundle["rejected_asset_versions"]
        }
        self.assertEqual(reasons["review-only-v1"], "SOURCE_MODE_review_only")
        self.assertEqual(reasons["foreign-v1"], "WRONG_PROJECT")
        with self.assertRaisesRegex(KernelError, "CHAPTER_QUALITY_GATE_BLOCKED"):
            build_export_package(
                revision={"chapter": 1, "title": "Blocked", "text": "text"},
                revision_asset_version_id="revision-version-1",
                quality={"gate": "FAILED"},
                quality_asset_version_id="quality-version-1",
            )


if __name__ == "__main__":
    unittest.main()
