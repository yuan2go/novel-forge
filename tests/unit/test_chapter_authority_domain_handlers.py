from __future__ import annotations

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


class ChapterAuthorityDomainHandlerTests(unittest.TestCase):
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
            result={"decision": "PASSED", "score": 88, "issues": [], "resolved_issue_codes": ["COST_NOT_CONCRETE"]},
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
        self.assertEqual(exported["release_status"], "READY_FOR_BLOB_VERIFICATION")

    def test_quality_and_export_fail_closed(self) -> None:
        with self.assertRaisesRegex(KernelError, "QUALITY_REREVIEW_REQUIRED"):
            build_quality_report(
                revision={"chapter": 1, "text": "Nothing changes."},
                revision_asset_version_id="revision-version-1",
                canon={"gate": "PASSED", "conflicts": []},
                canon_asset_version_id="canon-version-1",
            )

    def test_context_bundle_accounts_for_optional_inputs_rejected_by_budget(self) -> None:
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
            "blob_id": "blob-1", "role": "content", "provider": "fixture-store",
            "receipt_provider": "fixture-store", "object_key": "chapter.txt",
            "expected_hash": "sha256:text", "actual_hash": "sha256:text",
            "content_hash": "sha256:text", "expected_size": 4, "actual_size": 4,
            "media_type": "text/plain", "status": "AVAILABLE",
            "external_effect_id": "effect-1", "capability": "object_store.put",
            "effect_status": "SUCCEEDED", "dispatch_id": "dispatch-1",
            "dispatch_status": "SUCCEEDED", "receipt_id": "receipt-1",
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

    def test_authority_context_consumes_governed_mkaos_and_source_decisions(self) -> None:
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
                    "asset_version_id": "pack-v1", "asset_type": "knowledge_pack",
                    "project_id": "project-a", "estimated_tokens": 100, "score": .9,
                    "allowed_use": "generation", "source_policy_version": "policy-v1",
                },
                {
                    "asset_version_id": "review-only-v1", "asset_type": "knowledge_pack",
                    "project_id": "project-a", "estimated_tokens": 100,
                    "source_use_mode": "review_only",
                },
                {
                    "asset_version_id": "foreign-v1", "asset_type": "knowledge_pack",
                    "project_id": "project-b", "estimated_tokens": 100,
                },
            ],
        )
        self.assertEqual(bundle["knowledge_pack_versions"], ["pack-v1"])
        self.assertEqual(bundle["source_policy_versions"], ["policy-v1"])
        reasons = {item["asset_version_id"]: item["reason"] for item in bundle["rejected_asset_versions"]}
        self.assertEqual(reasons["review-only-v1"], "source_mode:review_only")
        self.assertEqual(reasons["foreign-v1"], "cross_project")
        with self.assertRaisesRegex(KernelError, "CHAPTER_QUALITY_GATE_BLOCKED"):
            build_export_package(
                revision={"chapter": 1, "title": "Blocked", "text": "text"},
                revision_asset_version_id="revision-version-1",
                quality={"gate": "FAILED"},
                quality_asset_version_id="quality-version-1",
            )


if __name__ == "__main__":
    unittest.main()
