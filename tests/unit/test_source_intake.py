from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.api.product import create_github_knowledge_handoff
from novel_forge.modules.source_intake import (
    apply_source_diff_repair,
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
    plan_source_diff_repair,
    rollback_source_diff_repair,
    run_source_connector,
)
from novel_forge.modules.permission_center import resolve_approval_request
from novel_forge.schemas import KnowledgeCard, validate_common_fields
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

    def test_source_diff_repair_plan_creates_reviewable_impact_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(storage, {"source_ref": "local-corpus", "risk_tier": "R1", "project_id": "source-p5"})
            risk = create_source_risk_report(storage, {"source_ref": "local-corpus", "source_policy_path": policy["path"], "project_id": "source-p5"})
            old_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "old-hash",
                    "source_path": "sources/local-corpus/manifest.json",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p5",
                },
            )
            new_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "new-hash",
                    "source_path": "sources/local-corpus/manifest.json",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p5",
                },
            )
            knowledge_path = storage.write_asset_auto(
                KnowledgeCard(
                    title="Source-derived abstraction",
                    source="local-corpus",
                    tags=["mkaos", "source-derived"],
                    content={
                        "principles": ["Only abstract source mechanisms may be reused."],
                        "principle": "Only abstract source mechanisms may be reused.",
                        "source_snapshot_ref": old_snapshot["asset"]["id"],
                        "source_snapshot_path": old_snapshot["path"],
                        "source_policy_refs": [policy["asset"]["id"]],
                        "source_risk_report_refs": [risk["asset"]["id"]],
                    },
                    metadata={
                        "project_id": "source-p5",
                        "asset_status": "active",
                        "use_in_generation_rag": False,
                        "copyright_boundary": "abstract structure only; no raw source expression",
                    },
                    references=[old_snapshot["path"], old_snapshot["asset"]["id"]],
                )
            )
            refreshed_knowledge_path = storage.write_asset_auto(
                KnowledgeCard(
                    title="Already refreshed abstraction",
                    source="independent-refresh",
                    tags=["mkaos", "source-derived"],
                    content={
                        "principles": ["This card already points at the refreshed snapshot."],
                        "principle": "This card already points at the refreshed snapshot.",
                        "source_snapshot_ref": new_snapshot["asset"]["id"],
                    },
                    metadata={
                        "project_id": "source-p5",
                        "asset_status": "active",
                        "use_in_generation_rag": False,
                        "copyright_boundary": "abstract structure only; no raw source expression",
                    },
                    references=[new_snapshot["asset"]["id"]],
                )
            )

            plan = plan_source_diff_repair(
                storage,
                {
                    "old_snapshot_path": old_snapshot["path"],
                    "new_snapshot_path": new_snapshot["path"],
                    "project_id": "source-p5",
                },
            )
            content = plan["asset"]["content"]
            issue_content = plan["review_issue"]["asset"]["content"]
            task_statuses = {task["asset"]["content"]["status"] for task in plan["agent_tasks"]}
            unchanged = storage.read_json(knowledge_path)

            self.assertEqual(validate_common_fields(plan["asset"]), [])
            self.assertEqual(plan["asset"]["type"], "change_impact_report")
            self.assertEqual(plan["source_diff"]["status"], "changed")
            self.assertIn("content_hash", plan["source_diff"]["changed_fields"])
            self.assertEqual(content["repair_contract"]["silent_mutation_allowed"], False)
            self.assertFalse(plan["mutation_applied"])
            self.assertFalse(plan["dispatch_applied"])
            self.assertEqual(issue_content["issue_type"], "source_snapshot_drift")
            self.assertTrue(issue_content["blocking"])
            self.assertIn("needs_review", task_statuses)
            self.assertIn(str(knowledge_path.relative_to(storage.root)), {item["path"] for item in plan["impacted_assets"]})
            self.assertNotIn(str(refreshed_knowledge_path.relative_to(storage.root)), {item["path"] for item in plan["impacted_assets"]})
            self.assertEqual(unchanged["metadata"]["asset_status"], "active")

    def test_source_diff_repair_apply_requires_approval_and_writes_rollback_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            policy = create_source_policy(storage, {"source_ref": "local-corpus", "risk_tier": "R1", "project_id": "source-p6"})
            risk = create_source_risk_report(storage, {"source_ref": "local-corpus", "source_policy_path": policy["path"], "project_id": "source-p6"})
            old_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "old-hash",
                    "source_path": "sources/local-corpus/manifest.json",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p6",
                },
            )
            new_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "new-hash",
                    "source_path": "sources/local-corpus/manifest.json",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p6",
                },
            )
            knowledge_path = storage.write_asset_auto(
                KnowledgeCard(
                    title="Source-derived abstraction",
                    source="local-corpus",
                    tags=["mkaos", "source-derived"],
                    content={"principles": ["Abstract source mechanism."], "principle": "Abstract source mechanism.", "source_snapshot_ref": old_snapshot["asset"]["id"]},
                    metadata={
                        "project_id": "source-p6",
                        "asset_status": "active",
                        "use_in_generation_rag": True,
                        "copyright_boundary": "abstract structure only; no raw source expression",
                    },
                    references=[old_snapshot["path"], old_snapshot["asset"]["id"]],
                )
            )
            plan = plan_source_diff_repair(storage, {"old_snapshot_path": old_snapshot["path"], "new_snapshot_path": new_snapshot["path"], "project_id": "source-p6"})

            blocked = apply_source_diff_repair(storage, {"repair_plan_path": plan["path"], "project_id": "source-p6"})
            self.assertEqual(blocked["status"], "approval_required")
            self.assertFalse(blocked["mutation_applied"])
            self.assertEqual(storage.read_json(knowledge_path)["metadata"]["asset_status"], "active")

            approval_path = blocked["approval_request"]["path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve source repair"})
            ready = apply_source_diff_repair(storage, {"repair_plan_path": plan["path"], "approval_request_path": approval_path, "project_id": "source-p6"})
            self.assertEqual(ready["status"], "ready_for_confirm")
            self.assertEqual(storage.read_json(knowledge_path)["metadata"]["asset_status"], "active")

            applied = apply_source_diff_repair(
                storage,
                {
                    "repair_plan_path": plan["path"],
                    "approval_request_path": approval_path,
                    "confirm_apply": True,
                    "actor": "unit-test",
                    "project_id": "source-p6",
                },
            )
            stale = storage.read_json(knowledge_path)
            task_statuses = {storage.read_json(storage.root / path)["content"]["status"] for path in plan["asset"]["content"]["agent_task_paths"]}

            self.assertEqual(applied["errors"], [])
            self.assertEqual(applied["status"], "applied")
            self.assertTrue(applied["mutation_applied"])
            self.assertFalse(applied["dispatch_applied"])
            self.assertEqual(applied["rollback_plan"]["asset"]["type"], "rollback_plan")
            self.assertEqual(stale["metadata"]["asset_status"], "stale")
            self.assertFalse(stale["metadata"]["use_in_generation_rag"])
            self.assertIn("approved_pending_dispatch", task_statuses)

            rollback_blocked = rollback_source_diff_repair(storage, {"rollback_plan_path": applied["rollback_plan"]["path"], "project_id": "source-p6"})
            self.assertEqual(rollback_blocked["status"], "approval_required")
            self.assertEqual(storage.read_json(knowledge_path)["metadata"]["asset_status"], "stale")
            rollback_approval_path = rollback_blocked["approval_request"]["path"]
            resolve_approval_request(storage, rollback_approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve rollback"})
            rollback_ready = rollback_source_diff_repair(
                storage,
                {"rollback_plan_path": applied["rollback_plan"]["path"], "approval_request_path": rollback_approval_path, "project_id": "source-p6"},
            )
            self.assertEqual(rollback_ready["status"], "ready_for_confirm")
            rolled_back = rollback_source_diff_repair(
                storage,
                {
                    "rollback_plan_path": applied["rollback_plan"]["path"],
                    "approval_request_path": rollback_approval_path,
                    "confirm_rollback": True,
                    "actor": "unit-test",
                    "project_id": "source-p6",
                },
            )
            restored = storage.read_json(knowledge_path)
            restored_task_statuses = {storage.read_json(storage.root / path)["content"]["status"] for path in plan["asset"]["content"]["agent_task_paths"]}
            self.assertEqual(rolled_back["status"], "applied")
            self.assertTrue(rolled_back["rollback_applied"])
            self.assertEqual(rolled_back["rollback_result"]["asset"]["type"], "rollback_result")
            self.assertEqual(restored["metadata"]["asset_status"], "active")
            self.assertTrue(restored["metadata"]["use_in_generation_rag"])
            self.assertIn("needs_review", restored_task_statuses)

    def test_source_connector_runner_executes_approved_local_file_in_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            source_dir = Path(tmp) / "sources"
            source_dir.mkdir(parents=True, exist_ok=True)
            source_file = source_dir / "manifest.txt"
            source_file.write_text("manifest version two", encoding="utf-8")
            policy = create_source_policy(storage, {"source_ref": "local-corpus", "risk_tier": "R1", "project_id": "source-p7"})
            risk = create_source_risk_report(storage, {"source_ref": "local-corpus", "source_policy_path": policy["path"], "project_id": "source-p7"})
            old_snapshot = create_source_snapshot(
                storage,
                {
                    "source_ref": "local-corpus",
                    "source_type": "local_manifest",
                    "content_hash": "old-hash",
                    "source_path": "sources/manifest.txt",
                    "source_policy_path": policy["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p7",
                },
            )
            refresh = create_source_refresh_report(
                storage,
                {
                    "source_ref": "local-corpus",
                    "snapshot_path": old_snapshot["path"],
                    "risk_report_path": risk["path"],
                    "project_id": "source-p7",
                },
            )
            pending = plan_source_connector_execution(
                storage,
                {
                    "source_ref": "local-corpus",
                    "connector_id": "local_manifest_connector",
                    "source_refresh_report_path": refresh["path"],
                    "environment": "production",
                    "execute": True,
                    "source_path": "sources/manifest.txt",
                    "project_id": "source-p7",
                },
            )
            approval_path = pending["approval_request"]["path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve connector"})
            ready = plan_source_connector_execution(
                storage,
                {
                    "source_ref": "local-corpus",
                    "connector_id": "local_manifest_connector",
                    "source_refresh_report_path": refresh["path"],
                    "approval_request_path": approval_path,
                    "environment": "production",
                    "execute": True,
                    "source_path": "sources/manifest.txt",
                    "project_id": "source-p7",
                },
            )

            result = run_source_connector(
                storage,
                {
                    "sync_job_path": ready["sync_job"]["path"],
                    "approval_request_path": approval_path,
                    "source_path": "sources/manifest.txt",
                    "allowed_roots": ["sources"],
                    "previous_snapshot_path": old_snapshot["path"],
                    "project_id": "source-p7",
                },
            )

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["execution_receipt"]["execution_performed"])
            self.assertTrue(result["file_access_used"])
            self.assertFalse(result["network_access_used"])
            self.assertEqual(result["snapshot"]["asset"]["content"]["content_hash"], hashlib.sha256(b"manifest version two").hexdigest())
            self.assertFalse(result["snapshot"]["asset"]["content"]["raw_text_included"])
            self.assertEqual(result["sync_job"]["asset"]["content"]["status"], "completed")
            self.assertEqual(result["refresh_report"]["asset"]["type"], "source_refresh_report")
            self.assertEqual(result["diff_repair_plan"]["asset"]["type"], "change_impact_report")
            self.assertTrue(result["trace_span_path"])
            self.assertTrue(result["cost_ledger_path"])

    def test_source_connector_runner_blocks_path_outside_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            outside = Path(tmp).parent / "outside-source-runner.txt"
            outside.write_text("outside", encoding="utf-8")
            policy = create_source_policy(storage, {"source_ref": "local-corpus", "risk_tier": "R1", "project_id": "source-p8"})
            refresh = create_source_refresh_report(storage, {"source_ref": "local-corpus", "source_policy_path": policy["path"], "project_id": "source-p8"})
            pending = plan_source_connector_execution(
                storage,
                {
                    "source_ref": "local-corpus",
                    "connector_id": "local_manifest_connector",
                    "source_refresh_report_path": refresh["path"],
                    "environment": "production",
                    "execute": True,
                    "source_path": str(outside),
                    "project_id": "source-p8",
                },
            )
            approval_path = pending["approval_request"]["path"]
            resolve_approval_request(storage, approval_path, {"decision": "approved", "actor": "unit-test", "reason": "approve connector"})

            blocked = run_source_connector(
                storage,
                {
                    "sync_job_path": pending["sync_job"]["path"],
                    "approval_request_path": approval_path,
                    "source_path": str(outside),
                    "allowed_roots": ["sources"],
                    "project_id": "source-p8",
                },
            )

            self.assertEqual(blocked["status"], "blocked_path_outside_allowed_roots")
            self.assertFalse(blocked["execution_performed"])
            self.assertFalse(blocked["file_access_used"])

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
