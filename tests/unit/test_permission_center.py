from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.audit_log import list_audit_events
from novel_forge.modules.permission_center import (
    create_permission_policy,
    evaluate_permission,
    permission_center_snapshot,
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


if __name__ == "__main__":
    unittest.main()
