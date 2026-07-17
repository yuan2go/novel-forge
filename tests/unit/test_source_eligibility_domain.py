from __future__ import annotations

import unittest

from novel_forge.modules.source_intake.eligibility_domain import (
    SourceGovernanceEvidence,
    build_change_impact_report,
    build_regeneration_plan,
    decide_source_eligibility,
)


class SourceEligibilityDomainTests(unittest.TestCase):
    def evidence(self, **changes):
        values = {
            "source_asset_version_id": "source-v1", "project_id": "project-a",
            "source_policy_version": "policy-v1", "license_check_version": "license-v1",
            "source_risk_report_version": "risk-v1", "source_snapshot_version": "snapshot-v1",
            "copyright_clear": True, "license_id": "CC-BY-4.0",
            "commercial_use_allowed": True, "generation_context_allowed": True,
            "raw_text_allowed": False,
        }
        values.update(changes)
        return SourceGovernanceEvidence(**values)

    def test_clear_source_is_generation_eligible_but_raw_text_remains_forbidden(self) -> None:
        decision = decide_source_eligibility(project_id="project-a", evidence=self.evidence())
        self.assertEqual(decision["status"], "ELIGIBLE")
        self.assertEqual(decision["use_mode"], "generation")
        self.assertTrue(decision["generation_allowed"])
        self.assertFalse(decision["raw_text_allowed"])
        self.assertEqual(decision["policy_versions"]["snapshot"], "snapshot-v1")

    def test_stale_quarantine_injection_and_cross_project_fail_closed(self) -> None:
        cases = [
            (self.evidence(stale=True), "STALE"),
            (self.evidence(quarantined=True), "QUARANTINED"),
            (self.evidence(prompt_injection_clear=False), "QUARANTINED"),
            (self.evidence(project_id="project-b"), "REVOKED"),
            (self.evidence(revoked=True), "REVOKED"),
        ]
        for evidence, expected in cases:
            with self.subTest(expected=expected, evidence=evidence):
                decision = decide_source_eligibility(project_id="project-a", evidence=evidence)
                self.assertEqual(decision["status"], expected)
                self.assertFalse(decision["generation_allowed"])

    def test_unproven_rights_are_downgraded_to_structure_only(self) -> None:
        decision = decide_source_eligibility(
            project_id="project-a",
            evidence=self.evidence(copyright_clear=False, license_id=""),
        )
        self.assertEqual(decision["status"], "REQUIRES_APPROVAL")
        self.assertEqual(decision["use_mode"], "structure_only")

    def test_change_impact_only_plans_regeneration_and_never_mutates_prose(self) -> None:
        impact = build_change_impact_report(
            project_id="project-a", changed_asset_version_id="source-v2",
            previous_snapshot_version="snapshot-v1", current_snapshot_version="snapshot-v2",
            affected_assets=[
                {"project_id": "project-a", "asset_type": "context_bundle", "asset_version_id": "context-v1"},
                {"project_id": "project-a", "asset_type": "knowledge_pack", "asset_version_id": "pack-v1"},
                {"project_id": "project-b", "asset_type": "context_bundle", "asset_version_id": "foreign"},
            ],
        )
        plan = build_regeneration_plan(impact, risk_level="high")
        self.assertEqual(impact["affected_context_bundle_versions"], ["context-v1"])
        self.assertEqual(impact["cross_project_assets_ignored"], 1)
        self.assertTrue(plan["approval_request_required"])
        self.assertIn("mutate_accepted_prose", plan["forbidden_automatic_actions"])


if __name__ == "__main__":
    unittest.main()
