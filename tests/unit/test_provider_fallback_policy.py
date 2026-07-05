from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.model_router import create_model_route
from novel_forge.modules.provider_fallback import approve_provider_fallback, preview_provider_fallback, resolve_provider_fallback
from novel_forge.storage.local import LocalStorage


class ProviderFallbackPolicyTests(unittest.TestCase):
    def test_explicit_fallback_requires_approval_and_reports_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_model_route(
                storage,
                task_type="draft",
                provider="primary-provider",
                model_name="primary-model",
                fallbacks=[
                    {
                        "provider": "fallback-provider",
                        "model_name": "fallback-model",
                        "reason": "manual operator fallback only",
                        "cost_profile": {"per_1k": 0.02},
                    }
                ],
                project_id="fallback-p",
            )

            preview = preview_provider_fallback(storage, {"task_type": "draft", "project_id": "fallback-p", "token_estimate": 1000})
            with self.assertRaisesRegex(ValueError, "explicit provider fallback approval required"):
                resolve_provider_fallback(storage, {"task_type": "draft", "provider": "fallback-provider", "model_name": "fallback-model"})

            approved = approve_provider_fallback(
                storage,
                {
                    "preview": preview,
                    "task_type": "draft",
                    "project_id": "fallback-p",
                    "provider": "fallback-provider",
                    "model_name": "fallback-model",
                    "approved": True,
                    "approval_reason": "primary hard-stop proof reviewed; fallback cost accepted",
                },
            )
            resolved = resolve_provider_fallback(
                storage,
                {
                    "approval_gate_path": approved["approval_gate_path"],
                    "task_type": "draft",
                    "provider": "fallback-provider",
                    "model_name": "fallback-model",
                },
            )

            self.assertEqual(preview["status"], "approval_required")
            self.assertFalse(preview["silent_fallback_allowed"])
            self.assertEqual(preview["fallback_candidates"][0]["cost_prediction"]["amount"], 0.02)
            self.assertEqual(approved["status"], "approved")
            self.assertTrue(approved["fallback_decision_path"])
            decision = storage.read_json(storage.root / approved["fallback_decision_path"])
            self.assertEqual(decision["type"], "fallback_decision")
            self.assertEqual(decision["content"]["allowed"], True)
            self.assertEqual(decision["content"]["rollback_plan"]["rollback_action"], "return_to_primary_route")
            self.assertFalse(decision["content"]["silent_fallback_allowed"])
            self.assertEqual(resolved["provider"], "fallback-provider")
            self.assertEqual(resolved["hard_stop_policy"], "fail_closed")
            self.assertEqual(resolved["fallback_decision_path"], approved["fallback_decision_path"])


if __name__ == "__main__":
    unittest.main()
