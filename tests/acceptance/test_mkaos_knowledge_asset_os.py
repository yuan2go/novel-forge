from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules import mkaos
from novel_forge.storage.local import LocalStorage


class MkaosKnowledgeAssetOsAcceptanceTests(unittest.TestCase):
    def test_knowledge_asset_os_vertical_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = mkaos.run_mkaos_acceptance_suite(storage, {"project_id": "mkaos-acceptance"})
            self.assertTrue(result["passed"])
            self.assertTrue(result["knowledge_pack_id"])
            self.assertTrue(result["review_issue_summary"]["issue_count"])
            self.assertTrue(result["revision_task_id"])
            self.assertEqual(result["regression_summary"]["failed"], 0)
            self.assertFalse(result["asset"]["content"]["source_isolation"]["raw_text_included"])


if __name__ == "__main__":
    unittest.main()
