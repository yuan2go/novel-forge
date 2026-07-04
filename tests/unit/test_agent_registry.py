from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_registry import (
    agent_registry_coverage,
    create_agent_evaluation_binding,
    record_agent_lifecycle_event,
    resolve_agent_registry_entry,
    sync_runtime_profiles,
)
from novel_forge.storage.local import LocalStorage


class AgentRegistryTests(unittest.TestCase):
    def test_sync_runtime_profiles_creates_schedulable_active_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = sync_runtime_profiles(storage)
            resolved = resolve_agent_registry_entry(storage, agent_id="draft", operation="draft", require_schedulable=True)
            coverage = agent_registry_coverage(storage)

            self.assertGreaterEqual(result["count"], 1)
            self.assertEqual(resolved["lifecycle_state"], "active")
            self.assertTrue(resolved["scheduler_enabled"])
            self.assertEqual(coverage["missing_runtime_profiles"], [])
            self.assertIn("active only", coverage["scheduler_policy"])

    def test_lifecycle_blocks_production_scheduling_for_deprecated_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)

            transition = record_agent_lifecycle_event(storage, agent_id="draft", to_state="deprecated", reason="unit test")

            self.assertEqual(transition["entry"]["asset"]["content"]["lifecycle_state"], "deprecated")
            self.assertFalse(transition["entry"]["asset"]["content"]["scheduler_enabled"])
            with self.assertRaisesRegex(RuntimeError, "not schedulable"):
                resolve_agent_registry_entry(storage, agent_id="draft", operation="draft", require_schedulable=True)

    def test_evaluation_binding_is_reflected_on_registry_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            sync_runtime_profiles(storage)

            binding = create_agent_evaluation_binding(storage, agent_id="review", evaluation_suite_id="suite-review-v1")
            entry = resolve_agent_registry_entry(storage, agent_id="review")["entry"]

            self.assertEqual(binding["asset"]["type"], "agent_evaluation_binding")
            self.assertEqual(entry["content"]["evaluation_bindings"][0]["evaluation_suite_id"], "suite-review-v1")
