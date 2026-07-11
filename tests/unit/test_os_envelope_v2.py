from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.os_envelope import normalize_os_envelope


class OsEnvelopeV2Tests(unittest.TestCase):
    def test_native_v2_preserves_canonical_refs_and_causation(self):
        envelope = normalize_os_envelope(
            {
                "schema_version": 2,
                "project_ref": "project-alpha",
                "novel_ref": "novel-alpha",
                "workflow_ref": "workflow-main",
                "run_ref": "run-parent",
                "task_ref": "task-draft-1",
                "agent_ref": "draft-agent",
                "artifact_ref": "chapter-plan-1",
                "asset_ref": "outline-1",
                "context_ref": "context-1",
                "approval_ref": "approval-1",
                "provider_ref": "provider-openai",
                "correlation_id": "corr-book-alpha",
                "causation_id": "event-plan-ready",
                "idempotency_key": "idem-draft-1",
                "operation": "chapter.start",
                "actor_type": "operator",
                "source": "unit-test",
                "source_policy": {"raw_source_text_allowed": False},
                "environment": "production",
            },
            operation="chapter.start",
        )

        self.assertEqual(envelope["schema_version"], 2)
        self.assertEqual(envelope["project_ref"], "project-alpha")
        self.assertEqual(envelope["project_id"], "project-alpha")
        self.assertEqual(envelope["correlation_id"], "corr-book-alpha")
        self.assertEqual(envelope["causation_id"], "event-plan-ready")
        self.assertFalse(envelope["legacy_derived"])

    def test_legacy_envelope_is_adapted_to_v2(self):
        envelope = normalize_os_envelope(
            {
                "project_id": "legacy-project",
                "task_type": "prose",
                "asset_type": "draft_chapter",
                "trace_id": "trace-legacy",
                "actor_type": "service",
                "source": "legacy-test",
                "source_policy": {"raw_source_text_allowed": False},
                "environment": "production",
            },
            operation="draft.generate",
        )

        self.assertEqual(envelope["schema_version"], 2)
        self.assertEqual(envelope["project_ref"], "legacy-project")
        self.assertEqual(envelope["correlation_id"], "trace-legacy")
        self.assertTrue(envelope["legacy_derived"])
        self.assertEqual(envelope["legacy_schema_version"], "0.1.0")

    def test_conflicting_legacy_and_canonical_project_refs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "project_ref conflicts with project_id"):
            normalize_os_envelope(
                {"schema_version": 2, "project_ref": "project-a", "project_id": "project-b"},
                operation="chapter.start",
            )

    def test_generated_idempotency_key_is_stable_for_immutable_request(self):
        payload = {
            "schema_version": 2,
            "project_ref": "project-alpha",
            "operation": "chapter.start",
            "task_ref": "chapter-1",
            "input_refs": ["outline-v3", "plan-v2"],
            "expected_output_types": ["draft_chapter"],
        }
        first = normalize_os_envelope(payload, operation="chapter.start")
        second = normalize_os_envelope(payload, operation="chapter.start")

        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertNotEqual(first["envelope_id"], second["envelope_id"])


if __name__ == "__main__":
    unittest.main()
