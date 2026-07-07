from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.product import create_github_knowledge_handoff
from novel_forge.modules.source_intake import (
    create_license_check_result,
    create_source_policy,
    create_source_refresh_report,
    create_source_risk_report,
    create_source_snapshot,
    create_source_sync_job,
    evaluate_source_context_eligibility,
    list_github_knowledge_sources,
    list_source_policies,
    plan_source_connector_execution,
)
from novel_forge.schemas import validate_common_fields
from novel_forge.storage.local import LocalStorage


class SourceIntakeTests(unittest.TestCase):
    def test_source_policies_keep_crawler_boundaries(self):
        policies = {item["id"]: item for item in list_source_policies()}

        self.assertFalse(policies["chinese_text_project"]["crawler_allowed"])
        self.assertEqual(policies["chinese_text_project"]["method"], "manual_reference_only")
        self.assertIn("official_robot_harvest_or_mirror", policies["project_gutenberg"]["method"])
        self.assertTrue(policies["project_gutenberg"]["crawler_allowed"])

    def test_github_knowledge_sources_filter_for_knowledge_cards(self):
        ancient = list_github_knowledge_sources(category="ancient_chinese", allowed_pipeline="knowledge_card_extraction")
        repos = {item["repo"] for item in ancient}

        self.assertIn("NiuTrans/Classical-Modern", repos)
        self.assertIn("QSJDAMTX/Ancient-Chinese-Allusion-Resource-Database", repos)
        self.assertTrue(all("knowledge_card_extraction" in item["allowed_pipeline"] for item in ancient))

    def test_github_knowledge_handoff_uses_metadata_note_and_license_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_github_knowledge_handoff(
                tmp,
                {
                    "repo_refs": ["NiuTrans/Classical-Modern", "ydli-ai/CSL"],
                    "discipline": "classical Chinese and research methods",
                    "project_context": "eastern fantasy worldbuilding",
                },
            )
            source_note = result["source_note"]["asset"]
            handoff = result["handoff"]["asset"]
            content = handoff["content"]
            serialized = json.dumps(handoff, ensure_ascii=False)

            self.assertEqual(validate_common_fields(source_note), [])
            self.assertEqual(validate_common_fields(handoff), [])
            self.assertEqual(source_note["type"], "source_document")
            self.assertTrue(source_note["metadata"]["license_review_required"])
            self.assertFalse(source_note["metadata"]["rights"]["allow_downstream_generation"])
            self.assertEqual(content["operation"], "multidisciplinary_knowledge_parse")
            self.assertEqual(content["expected_output_type"], "knowledge_card")
            self.assertEqual(len(content["external_source_refs"]), 2)
            self.assertTrue(content["source_acquisition_policy"]["license_review_required"])
            self.assertIn("raw_text_used=false", " ".join(content["acceptance_checks"]))
            self.assertNotIn("Hidden source sentence", serialized)

    def test_source_governance_lifecycle_records_policy_license_risk_snapshot_and_sync_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "risk_tier": "R0",
                    "review_status": "approved",
                    "allow_raw_context": True,
                    "project_id": "source-p1",
                    "evidence_refs": ["operator-license-note"],
                },
            )
            license_check = create_license_check_result(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "authorization": "owned",
                    "license_name": "operator-owned",
                    "evidence_refs": [policy["path"]],
                    "project_id": "source-p1",
                },
            )
            risk = create_source_risk_report(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_policy_path": policy["path"],
                    "license_check_path": license_check["path"],
                    "project_id": "source-p1",
                },
            )
            snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_type": "manual_note",
                    "content": "operator private note text",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p1",
                },
            )
            sync_job = create_source_sync_job(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "status": "planned",
                    "sync_mode": "metadata_only",
                    "policy_ref": policy["path"],
                    "project_id": "source-p1",
                },
            )

            for result in [policy, license_check, risk, snapshot, sync_job]:
                self.assertEqual(validate_common_fields(result["asset"]), [])

            self.assertEqual(policy["asset"]["type"], "source_policy")
            self.assertTrue(policy["asset"]["content"]["generation_context_allowed"])
            self.assertTrue(policy["asset"]["content"]["raw_source_context_allowed"])
            self.assertEqual(risk["asset"]["content"]["risk_tier"], "R0")
            self.assertFalse(risk["asset"]["content"]["quarantine"])
            self.assertFalse(snapshot["asset"]["content"]["raw_text_included"])
            self.assertNotIn("operator private note text", json.dumps(snapshot["asset"], ensure_ascii=False))
            self.assertEqual(sync_job["asset"]["content"]["sync_mode"], "metadata_only")

    def test_source_refresh_report_audits_existing_governance_without_connector_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "risk_tier": "R0",
                    "review_status": "approved",
                    "project_id": "source-p1",
                },
            )
            license_check = create_license_check_result(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "authorization": "owned",
                    "license_name": "operator-owned",
                    "evidence_refs": [policy["path"]],
                    "project_id": "source-p1",
                },
            )
            risk = create_source_risk_report(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_policy_path": policy["path"],
                    "license_check_path": license_check["path"],
                    "project_id": "source-p1",
                },
            )
            snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_type": "manual_note",
                    "content": "operator note text",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p1",
                },
            )
            sync_job = create_source_sync_job(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "status": "completed",
                    "sync_mode": "metadata_only",
                    "policy_ref": policy["path"],
                    "project_id": "source-p1",
                },
            )

            report = create_source_refresh_report(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_policy_path": policy["path"],
                    "license_check_path": license_check["path"],
                    "risk_report_path": risk["path"],
                    "snapshot_path": snapshot["path"],
                    "sync_job_path": sync_job["path"],
                    "project_id": "source-p1",
                },
            )
            content = report["asset"]["content"]

            self.assertEqual(validate_common_fields(report["asset"]), [])
            self.assertEqual(report["asset"]["type"], "source_refresh_report")
            self.assertEqual(content["decision"], "current")
            self.assertEqual(content["refresh_mode"], "audit_only")
            self.assertFalse(content["connector_execution_allowed"])
            self.assertFalse(content["source_isolation"]["network_access_used"])
            self.assertEqual(content["stale_flags"], [])
            self.assertEqual(content["governance_refs"]["source_policy_ref"], policy["asset"]["id"])
            self.assertEqual(content["governance_refs"]["source_snapshot_ref"], snapshot["asset"]["id"])

    def test_source_refresh_report_flags_license_gap_and_hash_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(storage, {"source_ref": "operator-notebook", "risk_tier": "R1", "project_id": "source-p1"})
            risk = create_source_risk_report(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_policy_path": policy["path"],
                    "project_id": "source-p1",
                },
            )
            snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "source_type": "manual_note",
                    "content": "first version",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p1",
                },
            )

            report = create_source_refresh_report(
                storage,
                {
                    "source_ref": "operator-notebook",
                    "snapshot_path": snapshot["path"],
                    "expected_content_hash": "different-hash",
                    "connector_execution_requested": True,
                    "project_id": "source-p1",
                },
            )
            content = report["asset"]["content"]
            codes = {item["code"] for item in content["stale_flags"]}

            self.assertEqual(validate_common_fields(report["asset"]), [])
            self.assertEqual(content["decision"], "needs_snapshot_refresh")
            self.assertTrue(content["approval_required"])
            self.assertFalse(content["connector_execution_allowed"])
            self.assertIn("license_check_missing", codes)
            self.assertIn("content_hash_drift", codes)
            self.assertIn("source_sync_job_missing", codes)
            self.assertIn("invalidate downstream source-derived material", " ".join(content["next_actions"]))

    def test_source_connector_execution_plan_is_approval_gated_and_no_network_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(storage, {"source_ref": "local-corpus", "risk_tier": "R1", "project_id": "source-p3"})
            risk = create_source_risk_report(storage, {"source_ref": "local-corpus", "source_policy_path": policy["path"], "project_id": "source-p3"})
            snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content": "manifest metadata",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p3",
                },
            )
            refresh = create_source_refresh_report(
                storage,
                {
                    "source_ref": "local-corpus",
                    "risk_report_path": risk["path"],
                    "snapshot_path": snapshot["path"],
                    "project_id": "source-p3",
                },
            )

            plan = plan_source_connector_execution(
                storage,
                {
                    "source_ref": "local-corpus",
                    "connector_id": "local_manifest_connector",
                    "source_refresh_report_path": refresh["path"],
                    "environment": "production",
                    "execute": True,
                    "project_id": "source-p3",
                },
            )
            receipt = plan["execution_receipt"]
            sync_content = plan["sync_job"]["asset"]["content"]

            self.assertEqual(plan["status"], "approval_required")
            self.assertFalse(plan["allowed"])
            self.assertEqual(plan["approval_request"]["asset"]["type"], "approval_request")
            self.assertEqual(plan["approval_request"]["asset"]["content"]["action"], "approve_source_connector_execution")
            self.assertEqual(sync_content["status"], "approval_required")
            self.assertEqual(sync_content["sync_mode"], "connector_execution_plan")
            self.assertFalse(receipt["execution_performed"])
            self.assertFalse(receipt["network_access_used"])
            self.assertFalse(receipt["file_access_used"])
            self.assertEqual(receipt["connector_execution"]["execution_boundary"], "plan_only_no_connector_invocation")

    def test_source_connector_execution_plan_blocks_unknown_connector(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            plan = plan_source_connector_execution(
                storage,
                {
                    "source_ref": "external-source",
                    "connector_id": "unreviewed-network-crawler",
                    "environment": "production",
                    "execute": True,
                    "project_id": "source-p4",
                },
            )

            self.assertEqual(plan["status"], "blocked")
            self.assertFalse(plan["allowed"])
            self.assertEqual(plan["sync_job"]["asset"]["content"]["status"], "blocked")
            self.assertEqual(plan["execution_receipt"]["status"], "blocked_connector_not_allowed")
            self.assertFalse(plan["execution_receipt"]["connector_execution"]["allowlisted"])
            self.assertFalse(plan["approval_request"])

    def test_high_risk_source_stays_evidence_only_and_creates_blocking_production_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(
                storage,
                {
                    "source_ref": "NiuTrans/Classical-Modern",
                    "risk_tier": "R3",
                    "project_id": "source-p2",
                    "evidence_refs": ["docs/reports/classical-modern-mkaos-import-report.md"],
                },
            )
            risk = create_source_risk_report(
                storage,
                {
                    "source_ref": "NiuTrans/Classical-Modern",
                    "source_policy_path": policy["path"],
                    "project_id": "source-p2",
                },
            )
            eligibility = evaluate_source_context_eligibility(
                storage,
                {
                    "source_ref": "NiuTrans/Classical-Modern",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "environment": "production",
                    "project_id": "source-p2",
                    "create_approval_request": True,
                    "evidence_refs": [risk["path"]],
                },
            )

            self.assertFalse(eligibility["generation_context_allowed"])
            self.assertTrue(eligibility["evidence_only"])
            self.assertTrue(eligibility["structure_only"])
            self.assertTrue(eligibility["blocking"])
            self.assertTrue(eligibility["requires_approval_request"])
            self.assertEqual(eligibility["approval_request"]["asset"]["type"], "approval_request")
            self.assertEqual(eligibility["approval_request"]["asset"]["content"]["scope"], "source")
            self.assertTrue(eligibility["approval_request"]["asset"]["content"]["blocking"])

    def test_quarantined_source_is_not_generation_context_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            eligibility = evaluate_source_context_eligibility(
                storage,
                {
                    "source_ref": "pirated-upload",
                    "risk_tier": "R4",
                    "environment": "local",
                },
            )

            self.assertFalse(eligibility["generation_context_allowed"])
            self.assertTrue(eligibility["quarantine"])
            self.assertEqual(eligibility["usable_context_form"], "none_quarantined")


if __name__ == "__main__":
    unittest.main()
