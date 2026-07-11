from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit_log import list_audit_events
from novel_forge.modules.permission_center import (
    build_approval_request_caller_readiness_report,
    create_approval_request,
    create_permission_policy,
    evaluate_permission,
    expire_approval_requests,
    list_approval_requests,
    permission_center_snapshot,
    resolve_approval_request,
    resolve_human_approval_gate,
    verify_approval_request,
)
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class PermissionCenterTests(unittest.TestCase):
    def test_production_publish_fails_closed_and_human_approval_unlocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            denied = evaluate_permission(
                storage,
                {
                    "scope": "publish",
                    "action": "release",
                    "subject_type": "agent",
                    "subject_id": "publishing-agent",
                    "resource_type": "release_package",
                    "resource_id": "release-1",
                    "environment": "production",
                    "project_id": "perm-p",
                    "trace_id": "trace-perm",
                },
            )
            policy = create_permission_policy(
                storage,
                {
                    "scope": "publish",
                    "subject_type": "agent",
                    "subject_id": "publishing-agent",
                    "resource_type": "release_package",
                    "resource_id": "release-1",
                    "actions": ["release"],
                    "environment": "production",
                    "requires_human_approval": True,
                    "project_id": "perm-p",
                },
            )
            waiting = evaluate_permission(
                storage,
                {
                    "scope": "publish",
                    "action": "release",
                    "subject_type": "agent",
                    "subject_id": "publishing-agent",
                    "resource_type": "release_package",
                    "resource_id": "release-1",
                    "environment": "production",
                    "project_id": "perm-p",
                    "trace_id": "trace-perm",
                },
            )
            gate_id = waiting["human_approval_gate"]["asset"]["content"]["gate_id"]
            resolve_human_approval_gate(storage, gate_id, {"decision": "approved", "actor": "chief-editor", "project_id": "perm-p"})
            allowed = evaluate_permission(
                storage,
                {
                    "scope": "publish",
                    "action": "release",
                    "subject_type": "agent",
                    "subject_id": "publishing-agent",
                    "resource_type": "release_package",
                    "resource_id": "release-1",
                    "environment": "production",
                    "project_id": "perm-p",
                    "trace_id": "trace-perm",
                },
            )
            snapshot = permission_center_snapshot(storage, project_id="perm-p")
            audits = list_audit_events(storage, project_id="perm-p", event_type="permission_center", limit=20)

            self.assertEqual(denied["status"], "denied")
            self.assertEqual(policy["asset"]["type"], "permission_policy")
            self.assertEqual(waiting["status"], "waiting_human")
            self.assertEqual(allowed["status"], "allowed")
            self.assertGreaterEqual(snapshot["summary"]["policy_count"], 1)
            self.assertGreaterEqual(len(audits), 4)

    def test_approval_request_lifecycle_records_blocking_decisions_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            local_request = create_approval_request(
                storage,
                {
                    "project_id": "approval-p",
                    "scope": "context",
                    "action": "override_context_bundle",
                    "risk_level": "medium",
                    "environment": "local",
                    "target_type": "context_bundle",
                    "target_id": "ctx-1",
                    "evidence_refs": ["data/contexts/ctx-1.json"],
                    "reason": "operator wants to inspect a local context override",
                    "trace_id": "trace-approval-local",
                },
            )
            production_request = create_approval_request(
                storage,
                {
                    "project_id": "approval-p",
                    "scope": "publish",
                    "action": "submit_release_package",
                    "risk_level": "high",
                    "environment": "production",
                    "target_type": "release_package",
                    "target_id": "release-1",
                    "target_refs": ["data/publishing/release-1.json"],
                    "reason": "external publish requires operator approval",
                    "trace_id": "trace-approval-prod",
                },
            )
            rejected = create_approval_request(
                storage,
                {
                    "project_id": "approval-p",
                    "scope": "story-mutation",
                    "action": "kill_major_character",
                    "risk_level": "critical",
                    "environment": "local",
                    "target_type": "outline",
                    "target_id": "outline-1",
                },
            )
            expired = create_approval_request(
                storage,
                {
                    "project_id": "approval-p",
                    "scope": "source",
                    "action": "allow_generation_context",
                    "risk_level": "high",
                    "environment": "production",
                    "expires_at": "2000-01-01T00:00:00Z",
                },
            )

            approved = resolve_approval_request(
                storage,
                production_request["asset"]["content"]["request_id"],
                {"decision": "approved", "actor": "chief-editor", "reason": "release package inspected", "project_id": "approval-p"},
            )
            denied = resolve_approval_request(
                storage,
                rejected["path"],
                {"decision": "rejected", "actor": "chief-editor", "reason": "major mutation needs a stronger impact report", "project_id": "approval-p"},
            )
            expired_result = expire_approval_requests(storage, project_id="approval-p", now="2026-01-01T00:00:00Z")
            rows = list_approval_requests(storage, project_id="approval-p", limit=20)
            snapshot = permission_center_snapshot(storage, project_id="approval-p")

            self.assertEqual(local_request["asset"]["type"], "approval_request")
            self.assertFalse(local_request["asset"]["content"]["blocking"])
            self.assertTrue(production_request["asset"]["content"]["blocking"])
            self.assertTrue(rejected["asset"]["content"]["blocking"])
            self.assertTrue(expired["asset"]["content"]["blocking"])
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(denied["status"], "rejected")
            self.assertEqual(expired_result["expired_count"], 1)
            self.assertEqual(len(rows), 4)
            self.assertEqual(snapshot["summary"]["approval_request_count"], 4)
            self.assertEqual(snapshot["summary"]["pending_approval_request_count"], 1)
            self.assertEqual(snapshot["summary"]["blocking_approval_request_count"], 0)

    def test_approval_verifier_binds_scope_project_and_target_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Versioned chapter",
                    content={"chapter": 1, "text": "原始章节正文"},
                    metadata={"project_id": "approval-version-p"},
                ),
            )
            request = create_approval_request(
                storage,
                {
                    "project_id": "approval-version-p",
                    "scope": "publish",
                    "action": "approve_platform_publish",
                    "environment": "production",
                    "target_type": "release_package",
                    "target_id": "release-version-1",
                    "target_path": str(draft_path.relative_to(storage.root)),
                },
            )
            binding = request["asset"]["content"]["target"]["version_binding"]
            self.assertTrue(binding["digest"])
            self.assertEqual(binding["asset_id"], storage.read_asset(draft_path).id)

            resolve_approval_request(storage, request["path"], {"decision": "approved", "actor": "chief-editor"})
            verified = verify_approval_request(
                storage,
                request["path"],
                project_id="approval-version-p",
                scope="publish",
                action="approve_platform_publish",
                target_ref=str(draft_path.relative_to(storage.root)),
            )
            self.assertTrue(verified["verified"], verified)
            self.assertEqual(verified["binding"]["digest"], binding["digest"])

            wrong_scope = verify_approval_request(storage, request["path"], project_id="approval-version-p", scope="source", action="approve_platform_publish", target_ref=str(draft_path.relative_to(storage.root)))
            self.assertFalse(wrong_scope["verified"])
            self.assertIn("scope_mismatch", wrong_scope["reasons"])

            mutated = storage.read_json(draft_path)
            mutated["content"]["text"] = "版本已经改变，旧审批不能继续使用"
            storage.write_json(draft_path, mutated)
            stale = verify_approval_request(storage, request["path"], project_id="approval-version-p", scope="publish", action="approve_platform_publish", target_ref=str(draft_path.relative_to(storage.root)))
            self.assertFalse(stale["verified"])
            self.assertIn("target_version_mismatch", stale["reasons"])

    def test_approval_verifier_rejects_expired_revoked_and_replayed_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            request = create_approval_request(
                storage,
                {
                    "project_id": "approval-lifecycle-p",
                    "scope": "publish",
                    "action": "approve_platform_publish",
                    "environment": "production",
                    "expires_at": "2000-01-01T00:00:00Z",
                },
            )
            resolve_approval_request(storage, request["path"], {"decision": "approved", "actor": "chief-editor"})
            expired = verify_approval_request(storage, request["path"], project_id="approval-lifecycle-p", scope="publish", action="approve_platform_publish")
            self.assertFalse(expired["verified"])
            self.assertIn("expired", expired["reasons"])

            target_path = storage.write_asset(
                "drafts",
                DraftChapter(title="Approval target", content={"chapter": 1, "text": "target"}, metadata={"project_id": "approval-lifecycle-p"}),
            )
            replay_request = create_approval_request(
                storage,
                {"project_id": "approval-lifecycle-p", "scope": "publish", "action": "approve_platform_publish", "environment": "production", "target_path": str(target_path.relative_to(storage.root))},
            )
            resolve_approval_request(storage, replay_request["path"], {"decision": "approved", "actor": "chief-editor"})
            consumed = verify_approval_request(storage, replay_request["path"], project_id="approval-lifecycle-p", scope="publish", action="approve_platform_publish", target_ref=str(target_path.relative_to(storage.root)), consume=True, actor="publishing")
            self.assertTrue(consumed["verified"], consumed)
            replayed = verify_approval_request(storage, replay_request["path"], project_id="approval-lifecycle-p", scope="publish", action="approve_platform_publish", target_ref=str(target_path.relative_to(storage.root)), consume=True, actor="publishing")
            self.assertFalse(replayed["verified"])
            self.assertIn("already_consumed", replayed["reasons"])

            revoked_request = create_approval_request(
                storage,
                {"project_id": "approval-lifecycle-p", "scope": "publish", "action": "approve_platform_publish", "environment": "production"},
            )
            resolve_approval_request(storage, revoked_request["path"], {"decision": "cancelled", "actor": "chief-editor", "reason": "revoke"})
            revoked = verify_approval_request(storage, revoked_request["path"], project_id="approval-lifecycle-p", scope="publish", action="approve_platform_publish")
            self.assertFalse(revoked["verified"])
            self.assertIn("status_cancelled", revoked["reasons"])

    def test_approval_request_caller_readiness_reports_missing_dimensions_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            report = build_approval_request_caller_readiness_report(storage, project_id="approval-readiness-p")
            content = report["asset"]["content"]

            self.assertEqual(report["asset"]["type"], "project_metric_snapshot")
            self.assertEqual(report["asset"]["metadata"]["snapshot_kind"], "approval_request_caller_readiness")
            self.assertEqual(content["status"], "partial")
            self.assertTrue(content["non_mutating"])
            self.assertEqual(content["summary"]["required_dimension_count"], 5)
            self.assertEqual(content["summary"]["covered_dimension_count"], 0)
            self.assertEqual(content["summary"]["missing_dimension_count"], 5)
            self.assertEqual(list_approval_requests(storage, project_id="approval-readiness-p"), [])

    def test_approval_request_caller_readiness_passes_when_required_callers_are_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            fixtures = [
                ("source", "allow_generation_context", "source_policy"),
                ("context", "override_context_bundle", "context_bundle"),
                ("publish", "submit_release_package", "release_package"),
                ("feedback", "apply_feedback_mutation", "feedback_plan_mutation_proposal"),
                ("story_mutation", "apply_outline_patch", "outline"),
            ]
            for scope, action, target_type in fixtures:
                request = create_approval_request(
                    storage,
                    {
                        "project_id": "approval-readiness-p",
                        "scope": scope,
                        "action": action,
                        "environment": "production",
                        "risk_level": "high",
                        "target_type": target_type,
                        "target_id": f"{scope}-fixture",
                        "reason": f"fixture coverage for {scope}",
                    },
                )
                resolve_approval_request(
                    storage,
                    request["asset"]["content"]["request_id"],
                    {"decision": "approved", "actor": "unit-test", "reason": "covered", "project_id": "approval-readiness-p"},
                )

            report = build_approval_request_caller_readiness_report(storage, project_id="approval-readiness-p")
            content = report["asset"]["content"]
            dimension_statuses = {row["dimension"]: row["status"] for row in content["caller_dimensions"]}

            self.assertEqual(content["status"], "ready")
            self.assertEqual(content["summary"]["covered_dimension_count"], 5)
            self.assertEqual(content["summary"]["missing_dimension_count"], 0)
            self.assertEqual(content["summary"]["pending_blocking_count"], 0)
            self.assertEqual(set(dimension_statuses.values()), {"covered"})
            self.assertEqual(len(content["evidence_paths"]), 5)

    def test_approval_request_caller_readiness_flags_pending_blocking_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            for scope in ["source", "context", "publish", "feedback", "story_mutation"]:
                create_approval_request(
                    storage,
                    {
                        "project_id": "approval-readiness-p",
                        "scope": scope,
                        "action": f"{scope}_operator_action",
                        "environment": "production",
                        "risk_level": "high",
                        "target_type": scope,
                        "target_id": f"{scope}-fixture",
                    },
                )

            report = build_approval_request_caller_readiness_report(storage, project_id="approval-readiness-p")
            content = report["asset"]["content"]

            self.assertEqual(content["status"], "review_required")
            self.assertEqual(content["summary"]["covered_dimension_count"], 5)
            self.assertEqual(content["summary"]["missing_dimension_count"], 0)
            self.assertEqual(content["summary"]["pending_blocking_count"], 5)
            self.assertEqual({row["status"] for row in content["caller_dimensions"]}, {"needs_review"})


if __name__ == "__main__":
    unittest.main()
