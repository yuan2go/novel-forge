from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.domain_handlers import (
    build_canon_patch,
    build_chapter_plan,
    build_context_bundle,
    build_export_package,
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
            provider_evidence={"provider_id": "provider-1", "real_model_call": True},
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
        self.assertEqual(quality["gate"], "PASSED_WITH_UNCALIBRATED")
        self.assertEqual(exported["release_status"], "READY_FOR_BLOB_VERIFICATION")

    def test_quality_and_export_fail_closed(self) -> None:
        with self.assertRaisesRegex(KernelError, "QUALITY_REREVIEW_REQUIRED"):
            build_quality_report(
                revision={"chapter": 1, "text": "Nothing changes."},
                revision_asset_version_id="revision-version-1",
                canon={"gate": "PASSED", "conflicts": []},
                canon_asset_version_id="canon-version-1",
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
