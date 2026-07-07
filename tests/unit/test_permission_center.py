from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit_log import list_audit_events
from novel_forge.modules.permission_center import (
    create_approval_request,
    create_permission_policy,
    evaluate_permission,
    expire_approval_requests,
    list_approval_requests,
    permission_center_snapshot,
    resolve_approval_request,
    resolve_human_approval_gate,
)
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


if __name__ == "__main__":
    unittest.main()
