from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.production_kernel import production_entrypoints, require_production_entrypoint


class ProductionEntrypointContractTests(unittest.TestCase):
    def test_every_registered_entrypoint_declares_one_state_owner_and_policy(self):
        entries = production_entrypoints()
        self.assertTrue(entries)
        self.assertEqual(len({entry["operation"] for entry in entries}), len(entries))
        for entry in entries:
            self.assertTrue(entry["state_owner"])
            self.assertEqual(entry["envelope_policy"], "required_in_production")

    def test_unknown_production_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unregistered production operation"):
            require_production_entrypoint("unbounded.side.effect")


if __name__ == "__main__":
    unittest.main()
