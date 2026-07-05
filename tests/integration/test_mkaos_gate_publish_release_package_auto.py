from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.mkaos_production_gate import run_mkaos_production_gate
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.storage.local import LocalStorage


class MkaosGatePublishReleasePackageAutoTests(unittest.TestCase):
    def test_publish_release_gate_fail_closes_on_blocking_mkaos_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            create_review_issue(
                storage,
                {
                    "project_id": "publish-gate",
                    "target_asset_id": "release-1",
                    "target_asset_type": "release_package",
                    "issue_type": "source_leakage",
                    "severity": "critical",
                    "blocking": True,
                    "message": "source leakage risk",
                    "source_system": "integration.mkaos",
                },
            )

            with self.assertRaisesRegex(ValueError, "MKAOS production gate blocked publish"):
                run_mkaos_production_gate(
                    storage,
                    {
                        "project_id": "publish-gate",
                        "flow": "publish",
                        "environment": "production",
                        "target_asset": {"id": "release-1", "type": "release_package", "content": {"chapters": ["draft-1"]}},
                        "knowledge_pack": {"id": "pack-1", "type": "knowledge_pack", "content": {"pack_items": [{"knowledge_id": "k1", "creative_principle": "safe"}]}},
                    },
                )


if __name__ == "__main__":
    unittest.main()
